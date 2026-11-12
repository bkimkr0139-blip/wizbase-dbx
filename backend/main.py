"""FastAPI app: WIZBASE DBX Project Rehearsal. Server-side auth, ownership and role checks on every route."""
from __future__ import annotations
import json, os, re, secrets, time, threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, Header, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import core, v11, v11_ext, guide, labs, transfer, ko_guide, sysinfo, feedback
from . import pack as pack_mod
from . import real
from . import telemetry
from . import academy, serving, ext_catalog, ext_dlt, ext_dash, ext_ml, ext_genai
from . import usage
from . import content as C
from .core import ApiError

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get("DBX_DATA_DIR", ROOT / "data"))
DATA.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="WIZBASE DBX Project Rehearsal", docs_url=None, redoc_url=None, openapi_url=None)


def _codes():
    """접근 코드 3종: admin(수퍼유저 전용) · staff(검토자) · instructor(강사). 서로 다른 값이며 admin 코드로만 admin 로그인이 가능하다."""
    f = Path(os.environ["DBX_CODES_FILE"]) if os.environ.get("DBX_CODES_FILE") else DATA / ".staff_codes.json"  # 접근 코드 파일(운영자가 별도 전달) — 저장소에 올리지 않는다
    c = json.loads(f.read_text(encoding="utf-8-sig")) if f.exists() else {}
    for k, env_k, pre in (("instructor", "DBX_INSTRUCTOR_CODE", "I-"), ("staff", "DBX_STAFF_CODE", "S-"), ("admin", "DBX_ADMIN_CODE", "A-")):
        if os.environ.get(env_k):
            c[k] = os.environ[env_k]
        elif k not in c:
            c[k] = pre + secrets.token_urlsafe(12)
    if len({c["admin"], c["staff"], c["instructor"]}) < 3:
        raise RuntimeError("admin·staff·instructor 접근 코드는 서로 달라야 합니다.")
    if not f.exists() or set(c) != set(json.loads(f.read_text(encoding="utf-8-sig"))):  # 새로 생성했거나 빠진 코드를 채운 경우에만 기록(전달받은 파일은 그대로 둠)
        f.write_text(json.dumps(c))
    return c


CODES = _codes()
TOKENS: dict[str, dict] = {}
TOK_FILE = DATA / "tokens.json"
if TOK_FILE.exists():
    try:
        TOKENS.update(json.loads(TOK_FILE.read_text()))
    except Exception:
        pass
_attempts: dict[str, list] = {}
_G = threading.RLock()


def _save_tokens():
    TOK_FILE.write_text(json.dumps(TOKENS))


def _standalone_loop():
    """설치형: 시작 직후 한 번, 이후 10분마다 — 신호 큐 전송 + AXOS 처리 상태 조회(오프라인이면 건너뜀)."""
    time.sleep(8)
    while True:
        try:
            telemetry.flush()
            feedback.sync(None, force=False)
        except Exception:
            pass
        time.sleep(600)


@app.on_event("startup")
def _startup():
    core.load_all()
    v11.init()
    if telemetry.standalone():
        threading.Thread(target=telemetry.startup_report, daemon=True).start()
        threading.Thread(target=_standalone_loop, daemon=True).start()


@app.exception_handler(ApiError)
async def api_err(request, e: ApiError):
    if e.status != 401 and e.code not in ("NO_FEEDBACK",):
        tk = (request.headers.get("authorization") or "")[7:]
        usage.log("api_error", TOKENS.get(tk) if tk else None, request, code=e.code, status=e.status, path=request.url.path[:60])
    return JSONResponse(status_code=e.status, content={"error": {"code": e.code, "message": e.message, **e.extra}})


def actor_of(authorization: Optional[str]) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise ApiError(401, "UNAUTHENTICATED", "로그인이 필요합니다.")
    t = TOKENS.get(authorization[7:])
    if not t:
        raise ApiError(401, "UNAUTHENTICATED", "세션이 만료되었습니다. 다시 로그인하세요.")
    return t


def staff_only(a, *roles):
    if a["role"] not in roles and not (a["role"] == "admin" and "admin" not in roles and roles != ("admin",)):
        raise ApiError(403, "FORBIDDEN", f"{'/'.join(roles)} 권한이 필요합니다.")


def sess(sid, a, write=False):
    S = core.SESSIONS.get(sid)
    if not S:
        raise ApiError(404, "SESSION_NOT_FOUND", "세션을 찾을 수 없거나 접근 권한이 없습니다.")
    if S["owner"] != a["user_id"] and a["role"] not in ("instructor", "admin", "reviewer"):
        raise ApiError(404, "SESSION_NOT_FOUND", "세션을 찾을 수 없거나 접근 권한이 없습니다.")
    return S


import contextvars
_METHOD = contextvars.ContextVar("dbx_method", default="GET")
MAX_BODY = 3_000_000


@app.middleware("http")
async def _limits(request: Request, call_next):
    """요청 본문 크기 제한(3MB) + 변경 요청 여부를 sess_ext 에 전달."""
    try:
        n = int(request.headers.get("content-length") or 0)
    except ValueError:
        n = 0
    if n > MAX_BODY:
        return JSONResponse({"error": {"code": "BODY_TOO_LARGE", "message": f"요청이 너무 큽니다(최대 {MAX_BODY // 1_000_000}MB)."}}, status_code=413)
    tok = _METHOD.set(request.method)
    try:
        return await call_next(request)
    finally:
        _METHOD.reset(tok)


def sess_ext(sid, a, write=False):
    """확장 기능(add-data·볼륨·파이프라인·ML·AI·대시보드·서빙)용 세션 접근: 검토자(reviewer)는 다른 사람 세션을 읽기만 하고 바꿀 수 없다."""
    S = sess(sid, a)
    if _METHOD.get() not in ("GET", "HEAD") and a["role"] == "reviewer" and S["owner"] != a["user_id"]:
        raise ApiError(403, "FORBIDDEN", "검토자는 다른 사람의 세션을 변경할 수 없습니다(읽기만 가능).")
    return S


for _m in (serving, ext_catalog, ext_dlt, ext_dash, ext_ml, ext_genai):
    _m.register(app, actor_of, sess_ext)


@app.exception_handler(ValueError)
@app.exception_handler(TypeError)
@app.exception_handler(KeyError)
@app.exception_handler(OverflowError)
async def _bad_input(request: Request, exc: Exception):
    """입력 형식 문제로 생긴 예외를 500 대신 400 으로."""
    return JSONResponse({"error": {"code": "INVALID_INPUT", "message": "입력 값의 형식이 올바르지 않습니다(숫자·목록·필드 이름을 확인하세요).", "detail": type(exc).__name__}}, status_code=400)


# ---------------------------------------------------------------- auth
class Login(BaseModel):
    name: str
    role: str = "learner"
    code: Optional[str] = None


@app.post("/api/auth/login")
def login(b: Login, request: Request):
    ip = request.client.host if request.client else "?"
    with _G:  # 속도 제한은 '실패한 직원 코드 시도'에만 적용(교육장 NAT 뒤 다수 학습자 로그인 차단 방지)
        h = [t for t in _attempts.get(ip, []) if time.time() - t < 300]
        _attempts[ip] = h
        if len(h) >= int(os.environ.get("DBX_LOGIN_LIMIT", "15")):
            raise ApiError(429, "TOO_MANY_ATTEMPTS", "접근 코드 실패가 너무 많습니다. 잠시 후 다시 시도하세요.")

    def bad_code():
        with _G:
            _attempts.setdefault(ip, []).append(time.time())
        usage.log("login_fail", {"name": (b.name or "")[:40], "role": b.role}, request, reason="BAD_CODE")
        raise ApiError(403, "BAD_CODE", "접근 코드가 올바르지 않습니다.")
    name = (b.name or "").strip()[:40]
    if not name or name in ("학습자", "관리자", "검토자", "강사"):
        raise ApiError(400, "NAME_REQUIRED", "이름(실명)을 입력하세요.")
    if b.role == "learner":
        pass
    elif b.role == "instructor":
        if not secrets.compare_digest(b.code or "", CODES["instructor"]):
            bad_code()
    elif b.role == "admin":
        if not secrets.compare_digest(b.code or "", CODES["admin"]):
            bad_code()
    elif b.role == "reviewer":
        if not (secrets.compare_digest(b.code or "", CODES["staff"]) or secrets.compare_digest(b.code or "", CODES["instructor"])):
            bad_code()
    else:
        raise ApiError(400, "BAD_ROLE", "learner|admin|reviewer|instructor")
    tok = secrets.token_urlsafe(24)
    TOKENS[tok] = {"user_id": f"{b.role[:1]}_{secrets.token_hex(4)}", "role": b.role, "name": name}
    _save_tokens()
    usage.log("login_ok", TOKENS[tok], request)
    if telemetry.standalone():            # 설치형: 로그인한 사용자를 설치 ID와 연결해 서버에 알리고, 내 피드백 처리 상태를 바로 확인한다
        telemetry.set_user(name)
        telemetry.report("login")
        threading.Thread(target=lambda: feedback.sync(None, force=False), daemon=True).start()
    return {"token": tok, **TOKENS[tok]}


@app.get("/api/me")
def me(authorization: Optional[str] = Header(None)):
    return actor_of(authorization)


@app.get("/api/meta")
def meta():
    return {"product": "WIZBASE DBX Project Rehearsal", "version": "v1.1-impl", "banner": "WIZBASE 교육 환경 — Databricks 공식 제품·인증·교육과정이 아닙니다", "profile": core.PROFILE,
            "modes": {"A": "SIMULATED", "B": "LOCAL_EXECUTED", "C": "DBX_VERIFIED (이 배포에는 어댑터·자격증명 없음)"}, "python_execution": "DISABLED (격리 실행기 미구성)", "lessons": core.LESSONS,
            "learning_modes": ["guided", "practice", "real", "demo"]}


@app.get("/api/features")
def features(authorization: Optional[str] = Header(None)):
    actor_of(authorization)
    return {"features": v11_ext.feature_view(core.FEATURES), "profile": core.PROFILE["profile_id"], "note": "기능별 지원·미노출 원인(제품/리전/관리자/entitlement/ACL/UI개편)은 구분하며 unknown이면 '확인 필요'."}


# ---------------------------------------------------------------- sessions
class NewSession(BaseModel):
    profile_id: str = core.PROFILE["profile_id"]
    lesson_id: str = "UC-SELECT-01"
    mode: str = "B"
    learning_mode: str = "guided"
    seed: str = "food-order-v1"


@app.post("/api/sessions")
def new_session(b: NewSession, request: Request, authorization: Optional[str] = Header(None)):
    a = actor_of(authorization)
    if b.profile_id not in core.PROFILES:
        raise ApiError(400, "UNKNOWN_PROFILE", "지원 프로필: " + ", ".join(core.PROFILES))
    if a["role"] == "learner" and sum(1 for s in core.SESSIONS.values() if s["owner"] == a["user_id"]) >= 5:
        raise ApiError(429, "SESSION_LIMIT", "세션은 사용자당 5개까지입니다.")
    if len(core.SESSIONS) >= int(os.environ.get("DBX_MAX_SESSIONS", "300")):
        raise ApiError(503, "CAPACITY", "서버 세션 용량 초과")
    S = core.create_session(a["user_id"], b.lesson_id, b.mode, b.learning_mode, b.seed, b.profile_id)
    S["owner_name"] = a["name"]
    core.save(S)
    usage.log("session_new", a, request, mode=S["mode"], learning=S["learning_mode"])
    return {"session_id": S["id"], "seed": S["seed"], "effective_actor": core.TRAINEE, "mode": S["mode"], "profile_id": S["profile_id"], "seed": S["seed"], "evidence_level": "A=SIMULATED / B=LOCAL_EXECUTED"}


@app.get("/api/sessions")
def list_sessions(authorization: Optional[str] = Header(None)):
    a = actor_of(authorization)
    out = []
    for S in core.SESSIONS.values():
        if S["owner"] == a["user_id"] or a["role"] in ("instructor", "admin", "reviewer"):
            out.append({"session_id": S["id"], "owner": S["owner"], "owner_name": S.get("owner_name") or next((t["name"] for t in TOKENS.values() if t["user_id"] == S["owner"]), ""), "lesson_id": S["lesson_id"], "mode": S["mode"], "learning_mode": S["learning_mode"], "revision": S["revision"],
                        "completed": sum(1 for p in core.progress(S) if p["completed"]), "lessons": len(core.LESSONS), "paused": S["paused"], "created_at": S["created_at"], "last_activity_at": S.get("last_activity_at") or (core.DATA / f"{S['id']}.json").stat().st_mtime if (core.DATA / f"{S['id']}.json").exists() else S["created_at"], "admin_assisted": S["admin_assisted"]})
    return sorted(out, key=lambda x: -x["created_at"])


@app.get("/api/sessions/page")
def sessions_page(q: str = "", page: int = 0, size: int = 25, authorization: Optional[str] = Header(None)):
    """UI-01 세션 목록(검색·쪽 나누기): admin은 전체, 그 외는 본인 세션만."""
    a = actor_of(authorization)
    size = max(5, min(int(size or 25), 100))
    q = (q or "").strip().lower()
    rows = []
    for S in core.SESSIONS.values():
        if S["owner"] != a["user_id"] and a["role"] != "admin":
            continue
        name = S.get("owner_name") or next((t["name"] for t in TOKENS.values() if t["user_id"] == S["owner"]), "")
        if q and not any(q in str(x).lower() for x in (S["id"], name, S["owner"], S["lesson_id"], S["mode"], S["learning_mode"])):
            continue
        rows.append({"session_id": S["id"], "owner": S["owner"], "owner_name": name, "lesson_id": S["lesson_id"], "mode": S["mode"], "learning_mode": S["learning_mode"], "revision": S["revision"],
                     "completed": sum(1 for p in core.progress(S) if p["completed"]), "lessons": len(core.LESSONS), "paused": S["paused"], "created_at": S["created_at"],
                     "last_activity_at": S.get("last_activity_at") or S["created_at"]})
    rows.sort(key=lambda x: -x["created_at"])
    total = len(rows)
    pages = max(1, -(-total // size))
    page = max(0, min(int(page or 0), pages - 1))
    return {"items": rows[page * size:(page + 1) * size], "total": total, "page": page, "pages": pages, "size": size, "ids": [r["session_id"] for r in rows[:500]], "scope": "all" if a["role"] == "admin" else "own"}


class DelSessions(BaseModel):
    ids: list[str]


@app.post("/api/sessions/delete")
def delete_sessions(b: DelSessions, request: Request, authorization: Optional[str] = Header(None)):
    """본인 세션만(admin은 전체) 선택 삭제. 권한 없는 id는 삭제하지 않고 denied로 돌려준다."""
    a = actor_of(authorization)
    done, denied = [], []
    for sid in dict.fromkeys(b.ids[:100]):
        S = core.SESSIONS.get(sid)
        if not S or (S["owner"] != a["user_id"] and a["role"] != "admin"):
            denied.append(sid)
            continue
        core.delete_session(sid)
        done.append(sid)
    if done:
        usage.log("session_del", a, request, count=len(done), by_admin=bool(a["role"] == "admin"))
        v11.audit(a, "SESSION_DELETE", ",".join(done), detail={"count": len(done)})
        v11.save()
    return {"deleted": done, "denied": denied}


class Cmd(BaseModel):
    command_type: str
    payload: dict[str, Any] = {}
    idempotency_key: Optional[str] = None
    expected_revision: Optional[int] = None


@app.post("/api/sessions/{sid}/commands")
def command(sid: str, b: Cmd, request: Request, authorization: Optional[str] = Header(None)):
    a = actor_of(authorization)
    S = sess(sid, a)
    with core.lock_for(sid):
        if b.command_type in ("genie.config",) and a["role"] == "reviewer":
            raise ApiError(403, "FORBIDDEN", "")
        ex = core.commands(S, a, b.command_type, b.payload, b.idempotency_key, b.expected_revision)
    usage.log("cmd", a, request, type=b.command_type, status=ex.get("status") if isinstance(ex, dict) else None)
    return ex


@app.get("/api/executions/{eid}")
def execution(eid: str, session_id: str, authorization: Optional[str] = Header(None)):
    a = actor_of(authorization)
    S = sess(session_id, a)
    ex = S["executions"].get(eid)
    if not ex:
        raise ApiError(404, "EXECUTION_NOT_FOUND", eid)
    return ex


def _visible_catalog(S, principal):
    return ext_catalog.visible_catalog(S, principal)


def _visible_catalog_legacy(S, principal):
    c = core._conns[S["id"]]
    rows = c.execute("select table_catalog, table_schema, table_name, table_type from information_schema.tables where table_catalog=? order by 1,2,3", [core.CAT]).fetchall()
    tree = {}
    for cat, sch, tbl, tt in rows:
        usable_schema = core.has_priv(S, principal, "USE SCHEMA", f"schema:{cat}.{sch}") and core.has_priv(S, principal, "USE CATALOG", f"catalog:{cat}")
        can_sel = usable_schema and core.has_priv(S, principal, "SELECT", f"table:{cat}.{sch}.{tbl}")
        tree.setdefault(sch, {"schema": sch, "usable": usable_schema, "tables": []})["tables"].append({"name": tbl, "type": "VIEW" if "VIEW" in tt else "TABLE", "can_select": can_sel, "owner": S["owners"].get(f"table:{cat}.{sch}.{tbl}", "uc-admin")})
    fc = [{"catalog": k, "connection": v["connection"], "kind": "FOREIGN"} for k, v in S["foreign_catalogs"].items()]
    return {"catalog": core.CAT, "schemas": list(tree.values()), "foreign_catalogs": fc, "principal": principal}


LINEAGE = [("food_dev.bronze.raw_orders", "food_dev.silver.orders_pl"), ("food_dev.silver.inventory", "food_dev.gold.v_available_inventory"), ("food_dev.silver.orders", "food_dev.gold.v_order_overview"),
           ("food_dev.silver.order_lines", "food_dev.gold.v_order_overview"), ("food_dev.silver.orders_pl", "job:orders_job"), ("food_dev.gold.v_available_inventory", "policy:ORDER_CHANGE_AFTER_CUTOFF")]


@app.get("/api/sessions/{sid}/state")
def state(sid: str, principal: Optional[str] = None, authorization: Optional[str] = Header(None)):
    a = actor_of(authorization)
    S = sess(sid, a)
    with core.lock_for(sid):
        p = core.principal_of(S, a, principal if principal and principal != core.TRAINEE else None) if principal else (core.ADMIN if a["role"] == "admin" else core.TRAINEE)
        b = S["bundle"]
        local = core.bundle_hash(b["files"])
        s = {"session": {k: S[k] for k in ("id", "owner", "profile_id", "lesson_id", "mode", "learning_mode", "seed", "revision", "paused", "hints_used", "admin_assisted")}, "case": S["case"],
             "clock": core.clock(S).isoformat(), "principal": p, "warehouse": {**S["warehouse"], "state": core.wh_state(S)},
             "principals": S["principals"], "grants": S["grants"], "tickets": S["tickets"], "notebook": core.nb_view(S), "connections": S["connections"], "foreign_catalogs": S["foreign_catalogs"],
             "pipelines": S["pipelines"], "jobs": S["jobs"],
             "bundle": {"files": b["files"], "local_hash": local, "deployed_hash": (b["deployed"] or {}).get("hash"), "deploy_review": (b["deployed"] or {}).get("deploy_review"),
                        "drift": bool(b["deployed"]) and local != b["deployed"]["hash"], "cli_logged_in": b["cli_logged_in"], "commits": [{"id": c["id"], "msg": c["msg"]} for c in b["commits"]], "runs": b["runs"][-5:]},
             "policy": S["policy"], "proposals": S["proposals"], "approvals": S["approvals"], "genie": S["genie"], "progress": core.progress(S), "milestones": list(S["milestones"]),
             "evidence_levels": {"SIMULATED": "시뮬레이션", "LOCAL_EXECUTED": "로컬 DuckDB 실행", "DBX_VERIFIED": "해당 없음(이 배포)"}, "lineage": LINEAGE,
             "eval_runs": S["eval_runs"], "ontology": core.ONTOLOGY_MAP, "usage_index": {"executions": len(S["executions"]), "sql_runs": sum(1 for e in S["executions"].values() if e["type"] == "sql.execute"),
                                                                                         "note": "단가 출처·기준일이 없어 사용량 지수만 표시(실제 청구액 아님)"}, "cost": core.cost_view(S)}
        if a["role"] == "instructor":
            s["faults"] = S["faults"]; s["fault_log"] = S["fault_log"]; s["checkpoints"] = list(S["checkpoints"])
        return s


@app.get("/api/sessions/{sid}/catalog")
def catalog(sid: str, principal: Optional[str] = None, authorization: Optional[str] = Header(None)):
    a = actor_of(authorization)
    S = sess(sid, a)
    with core.lock_for(sid):
        p = core.principal_of(S, a, principal) if principal and principal != core.TRAINEE else (core.ADMIN if a["role"] == "admin" else core.TRAINEE)
        return _visible_catalog(S, p)


@app.get("/api/sessions/{sid}/catalog/table")
def catalog_table(sid: str, name: str, authorization: Optional[str] = Header(None)):
    """테이블 상세: Overview·Sample Data·Details·Permissions·History·Lineage·Insights·Quality 탭의 데이터를 한 번에 돌려준다."""
    a = actor_of(authorization)
    S = sess(sid, a)
    with core.lock_for(sid):
        p = core.ADMIN if a["role"] == "admin" else core.TRAINEE
        r = core.run_sql(S, f"SELECT * FROM {name} LIMIT 10", p, via="catalog", need_warehouse=False, actor_id=a["user_id"])
        if r["status"] != "succeeded":
            return {"name": name, "error": r["error"], "columns": [], "rows": []}
        c = core._conns[sid]
        if not r.get("tables") or (r["tables"][0].split(".")[0] != core.CAT and r["tables"][0].split(".")[0] not in core.user_catalogs(S)):
            return {"name": name, "error": core.sql_error("UNSUPPORTED_SQL", "이 이름은 상세를 지원하지 않습니다(외부(foreign) catalog 이거나 3단계 테이블 이름이 아닙니다).", "SQL Editor에서 SELECT 로 조회하세요."), "columns": [], "rows": []}
        fq = r["tables"][0]
        cols = c.execute(f"DESCRIBE {core.pfq(S, fq)}").fetchall()
        is_view = core._is_view(c, fq, S)
        total = c.execute(f"SELECT count(*) FROM {core.pfq(S, fq)}").fetchone()[0]
        quality = []
        for col in cols[:40]:
            q = f'"{col[0]}"'
            try:
                nn, dd = c.execute(f"SELECT count({q}), count(DISTINCT {q}) FROM {core.pfq(S, fq)}").fetchone()
                quality.append({"column": col[0], "type": col[1], "nulls": total - nn, "null_pct": round(100 * (total - nn) / total, 1) if total else 0, "distinct": dd})
            except Exception:
                quality.append({"column": col[0], "type": col[1], "nulls": None, "null_pct": None, "distinct": None})
        sec = f"table:{fq}"
        chain = core.sec_chain(sec)
        grants = [{"principal": g[0], "privilege": g[1], "securable": g[2], "inherited": g[2] != sec} for g in S["grants"] if g[2] in chain]
        owner = S["owners"].get(sec, "uc-admin")
        if not is_view:
            core._hist_ensure(S, c, fq)
        hist = [] if is_view else [{k: v for k, v in h.items()} for h in reversed(core._thist(S).get(fq, []))]
        touched = [q for q in S.get("qh", []) if fq in (q.get("tables") or []) and q.get("via") != "catalog"]
        users = {}
        for q in touched:
            users[q["principal"]] = users.get(q["principal"], 0) + 1
        insights = {"query_count": len(touched), "failed": sum(1 for q in touched if q["status"] == "FAILED"), "top_users": sorted(users.items(), key=lambda x: -x[1])[:5],
                    "recent": [{"at": q["at"], "principal": q["principal"], "via": q["via"], "statement": q["statement"], "status": q["status"], "sql": q["sql"][:300]} for q in touched[-5:][::-1]]}
        kind = "VIEW" if is_view else "TABLE"
        return {"name": fq, "kind": kind, "columns": [{"name": c_[0], "type": c_[1]} for c_ in cols], "rows": r["rows"], "preview_columns": r["columns"], "row_count": total,
                "grants": grants, "history": hist, "quality": quality, "insights": insights,
                "details": {"type": "Managed(시뮬레이션)" if not is_view else "View", "data_source": "Delta(시뮬레이션: DuckDB 스냅샷)" if not is_view else "-", "columns": len(cols), "rows": total, "versions": len(hist), "owner": owner,
                            "created_by_learner": bool(S["views_created_by"].get(fq)) or sec in S["owners"]},
                "lineage": [e for e in LINEAGE if fq in e], "evidence_level": "LOCAL_EXECUTED", "owner": owner}


@app.post("/api/sessions/{sid}/add-data")
def add_data_ep(sid: str, b: dict, authorization: Optional[str] = Header(None)):
    a = actor_of(authorization)
    S = sess_ext(sid, a)
    with core.lock_for(sid):
        p = core.ADMIN if a["role"] == "admin" else core.TRAINEE
        r = core.add_data(S, a, p, str(b.get("schema", "")), str(b.get("table", "")), str(b.get("csv", "")), str(b.get("mode", "create")), str(b.get("filename", "")), str(b.get("catalog", "")) or None)
        core.save(S)
        return r


@app.get("/api/sessions/{sid}/academy")
def academy_view(sid: str, authorization: Optional[str] = Header(None)):
    """Academy 역할별 경로 ↔ 시뮬레이터 대응표(제목 단위)와 세션 기록 기반 자동 실습 확인."""
    a = actor_of(authorization)
    S = sess(sid, a)
    with core.lock_for(sid):
        return academy.view(S)


@app.get("/api/sessions/{sid}/query-history")
def query_history(sid: str, status: str = "", statement: str = "", via: str = "", principal: str = "", q: str = "", minutes: int = 0, min_ms: int = 0,
                  page: int = 0, size: int = 25, authorization: Optional[str] = Header(None)):
    """Query History 화면: 필터(상태·구문·소스·주체·기간·최소 소요시간·텍스트)와 페이지."""
    a = actor_of(authorization)
    S = sess(sid, a)
    with core.lock_for(sid):
        items = [x for x in S.get("qh", []) if x.get("via") != "catalog"]
        facets = {"statements": sorted({x["statement"] for x in items}), "vias": sorted({x["via"] for x in items}), "principals": sorted({x["principal"] for x in items})}
        if status:
            items = [x for x in items if x["status"] == status]
        if statement:
            items = [x for x in items if x["statement"] == statement]
        if via:
            items = [x for x in items if x["via"] == via]
        if principal:
            items = [x for x in items if x["principal"] == principal]
        if min_ms:
            items = [x for x in items if x["duration_ms"] >= min_ms]
        if minutes:
            cut = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()
            items = [x for x in items if x["at"] >= cut]
        if q:
            ql = q.lower()
            items = [x for x in items if ql in x["sql"].lower() or ql in (x["id"] or "").lower() or ql in json.dumps(x.get("error") or {}).lower()]
        items = items[::-1]
        size = max(5, min(100, size))
        total = len(items)
        return {"total": total, "page": page, "size": size, "items": items[page * size:(page + 1) * size], "facets": facets}


@app.get("/api/resources/{rid:path}")
def resource(rid: str, session_id: str, authorization: Optional[str] = Header(None)):
    a = actor_of(authorization)
    S = sess(session_id, a)
    kind, _, nm = rid.partition(":")
    p = core.TRAINEE
    if kind == "warehouse":
        spec, perms = S["warehouse"], {"can_use": bool(set(S["warehouse"]["acl"]) & core.expand(S, p))}
    elif kind == "pipeline":
        spec, perms = S["pipelines"].get(nm), {"run_as": (S["pipelines"].get(nm) or {}).get("run_as")}
    elif kind == "job":
        spec, perms = S["jobs"].get(nm), {"owner": (S["jobs"].get(nm) or {}).get("owner"), "run_as": (S["jobs"].get(nm) or {}).get("run_as")}
    elif kind == "table":
        spec = {"name": nm, "owner": S["owners"].get(rid, "uc-admin")}
        parts = nm.split(".")
        perms = {pr: core.has_priv(S, p, pr, f"table:{nm}") for pr in ("SELECT", "MODIFY")} if len(parts) == 3 else {}
        perms["USE SCHEMA"] = core.has_priv(S, p, "USE SCHEMA", f"schema:{parts[0]}.{parts[1]}") if len(parts) == 3 else None
    else:
        raise ApiError(404, "RESOURCE_NOT_FOUND", rid)
    if spec is None:
        raise ApiError(404, "RESOURCE_NOT_FOUND", rid)
    return {"id": rid, "spec": spec, "revision": S["revision"], "permissions_for": {"principal": p, **perms}, "lineage": [e for e in LINEAGE if nm in e],
            "profile_id": S["profile_id"], "policy_version": S["policy"]["active"], "evidence_level": "SIMULATED"}


class PermReq(BaseModel):
    session_id: str
    securable: str
    privilege: str
    reason: str
    grantee: Optional[str] = None


@app.post("/api/permission-requests")
def perm_request(b: PermReq, authorization: Optional[str] = Header(None)):
    a = actor_of(authorization)
    S = sess(b.session_id, a)
    with core.lock_for(b.session_id):
        return core.api(S, a, "ticket.create", b.model_dump())


class Resolve(BaseModel):
    decision: str
    note: str = ""


@app.post("/api/sessions/{sid}/tickets/{tid}/resolve")
def resolve(sid: str, tid: str, b: Resolve, authorization: Optional[str] = Header(None)):
    a = actor_of(authorization)
    S = sess(sid, a)
    with core.lock_for(sid):
        return core.api(S, a, "ticket.resolve", {"ticket_id": tid, "decision": b.decision, "note": b.note})


class Approval(BaseModel):
    session_id: str
    proposal_id: str
    payload_hash: str


@app.post("/api/approvals")
def approvals(b: Approval, authorization: Optional[str] = Header(None)):
    a = actor_of(authorization)
    S = sess(b.session_id, a)
    with core.lock_for(b.session_id):
        return core.api(S, a, "approval", {"proposal_id": b.proposal_id, "payload_hash": b.payload_hash})


class AxBody(BaseModel):
    approval_id: Optional[str] = None
    payload: dict[str, Any] = {}
    idempotency_key: Optional[str] = None
    expected_version: Optional[int] = None


@app.post("/api/sessions/{sid}/ax/orders/{oid}/change")
def ax(sid: str, oid: str, b: AxBody, authorization: Optional[str] = Header(None)):
    a = actor_of(authorization)
    S = sess(sid, a)
    with core.lock_for(sid):
        return core.api(S, a, "ax.execute", {"order_id": oid, **b.model_dump()})


@app.get("/api/sessions/{sid}/ax/orders/{oid}")
def ax_get(sid: str, oid: str, authorization: Optional[str] = Header(None)):
    a = actor_of(authorization)
    S = sess(sid, a)
    with core.lock_for(sid):
        f = core.order_facts(S, oid, 0)
        return {"order_id": oid, "version": f["order_version"], "qty": f["current_qty"], "product_id": f["product_id"], "source": "virtual AX API store (session-local)"}


@app.get("/api/sessions/{sid}/hints")
def hints(sid: str, authorization: Optional[str] = Header(None)):
    a = actor_of(authorization)
    S = sess(sid, a)
    if S["learning_mode"] in ("real", "demo"):
        raise ApiError(403, "HINTS_DISABLED", "실전형/시연형에서는 힌트가 기본 숨김입니다.")
    nxt = S["hints_used"]
    lesson = next((p for p in core.progress(S) if not p["completed"]), None)
    ladder = ["오류 맥락: 어떤 계층(권한/데이터/코드/배포)에서 실패했는지 로그의 error code부터 확인하세요.", "개념: 부모 USE 권한과 SELECT는 별개입니다. 실행 신원(run-as)과 편집자도 별개입니다.",
              "디버깅 순서: 오류 → 누락 권한 식별 → 최소권한 티켓 → 재실행 → 결과 대조.", "부분 안내: 다음 미완료 항목을 보면 어떤 사건이 필요한지 알 수 있습니다.", "해설: 정답 SQL을 그대로 제공하지 않고 결과 동등성·근거를 평가합니다."]
    S["hints_used"] += 1
    S["hint_log"].append({"level": min(nxt, 4) + 1, "rev": S["revision"]})
    core.save(S)
    return {"level": min(nxt, 4) + 1, "hint": ladder[min(nxt, 4)], "current_lesson": lesson and {"lesson_id": lesson["lesson_id"], "pending": lesson["pending"]}, "hints_used": S["hints_used"]}


@app.get("/api/sessions/{sid}/evidence")
def evidence(sid: str, authorization: Optional[str] = Header(None)):
    a = actor_of(authorization)
    S = sess(sid, a)
    with core.lock_for(sid):
        return core.evidence(S)


@app.get("/api/sessions/{sid}/guide")
def guide_get(sid: str, authorization: Optional[str] = Header(None)):
    a = actor_of(authorization)
    S = sess(sid, a)
    with core.lock_for(sid):
        return guide.journey(S)


class GuideMsg(BaseModel):
    message: str
    session_id: Optional[str] = None
    view: Optional[str] = None


@app.post("/api/guide/chat")
def guide_chat(b: GuideMsg, request: Request, authorization: Optional[str] = Header(None)):
    a = actor_of(authorization)
    S = sess(b.session_id, a) if b.session_id else None
    if len(b.message) > 500:
        raise ApiError(400, "TOO_LONG", "500자 이내")
    if S:
        with core.lock_for(S["id"]):
            r = guide.chat(S, a, b.message, S["learning_mode"] in ("real", "demo"), b.view)
    else:
        r = guide.chat(None, a, b.message, False, b.view)
    usage.log("chat", a, request, intent=r.get("intent"), view=b.view, qlen=len(b.message))   # 질문 본문은 저장하지 않는다
    return r


@app.get("/api/sessions/{sid}/audit")
def audit_log(sid: str, authorization: Optional[str] = Header(None)):
    a = actor_of(authorization)
    S = sess(sid, a)
    return S["audit"][-300:]


# ---------------------------------------------------------------- instructor
class Fault(BaseModel):
    session_id: str
    fault_id: str


@app.get("/api/instructor/faults")
def fault_catalog(authorization: Optional[str] = Header(None)):
    staff_only(actor_of(authorization), "instructor")
    return core.FAULT_CATALOG


@app.post("/api/instructor/faults")
def inject(b: Fault, authorization: Optional[str] = Header(None)):
    a = actor_of(authorization)
    staff_only(a, "instructor")
    S = sess(b.session_id, a)
    with core.lock_for(b.session_id):
        return core.api(S, a, "fault.inject", {"fault_id": b.fault_id})


@app.post("/api/instructor/faults/release")
def release(b: Fault, authorization: Optional[str] = Header(None)):
    a = actor_of(authorization)
    staff_only(a, "instructor")
    S = sess(b.session_id, a)
    with core.lock_for(b.session_id):
        return core.api(S, a, "fault.release", {"fault_id": b.fault_id})


class SidBody(BaseModel):
    session_id: str
    name: Optional[str] = None
    paused: Optional[bool] = None
    explain_score: Optional[int] = None


@app.post("/api/instructor/pause")
def pause(b: SidBody, authorization: Optional[str] = Header(None)):
    a = actor_of(authorization); staff_only(a, "instructor"); S = sess(b.session_id, a)
    S["paused"] = bool(b.paused); core.save(S); return {"paused": S["paused"]}


@app.post("/api/instructor/reset")
def reset(b: SidBody, authorization: Optional[str] = Header(None)):
    a = actor_of(authorization)
    S = sess(b.session_id, a)
    if a["role"] not in ("instructor",) and S["owner"] != a["user_id"]:
        raise ApiError(403, "FORBIDDEN", "")
    with core.lock_for(b.session_id):
        r = core.reset_session(S, a); core.save(S); return r


@app.post("/api/instructor/checkpoint")
def ckpt(b: SidBody, authorization: Optional[str] = Header(None)):
    a = actor_of(authorization); staff_only(a, "instructor"); S = sess(b.session_id, a)
    with core.lock_for(b.session_id):
        r = core.checkpoint(S, b.name or "cp1"); core.save(S); return r


@app.post("/api/instructor/restore")
def restore(b: SidBody, authorization: Optional[str] = Header(None)):
    a = actor_of(authorization); staff_only(a, "instructor"); S = sess(b.session_id, a)
    with core.lock_for(b.session_id):
        r = core.restore(S, b.name or "cp1"); core.save(S); return r


@app.post("/api/instructor/evaluate")
def evaluate(b: SidBody, authorization: Optional[str] = Header(None)):
    a = actor_of(authorization); staff_only(a, "instructor", "reviewer"); S = sess(b.session_id, a)
    if b.explain_score is not None:
        if not 0 <= b.explain_score <= 15:
            raise ApiError(400, "RANGE", "설명 점수 0~15")
        S["assessment"] = {"explain_score": b.explain_score, "explain_by": a["user_id"]}
    core.save(S)
    return core.score(S)


@app.get("/api/sessions/{sid}/score")
def score(sid: str, authorization: Optional[str] = Header(None)):
    a = actor_of(authorization); S = sess(sid, a)
    return core.score(S)


@app.post("/api/instructor/replay")
def replay(b: SidBody, authorization: Optional[str] = Header(None)):
    a = actor_of(authorization); staff_only(a, "instructor"); S = sess(b.session_id, a)
    with core.lock_for(b.session_id):
        return core.replay_digest(S)


@app.get("/api/instructor/answer-key")
def answer_key(seed: str = "food-order-v1", authorization: Optional[str] = Header(None)):
    staff_only(actor_of(authorization), "instructor")
    from . import seed as sd
    if seed not in sd.CASES:
        raise ApiError(400, "UNKNOWN_SEED", seed)
    return sd.answer_key(seed_name=seed)


# ---------------------------------------------------------------- v1.1 routes
def A(authorization):
    return actor_of(authorization)


@app.get("/api/exam-profiles")
def exam_profiles(authorization: Optional[str] = Header(None)):
    A(authorization); return v11.profiles()


@app.get("/api/exam-profiles/{eid}/coverage")
def exam_cov(eid: str, authorization: Optional[str] = Header(None)):
    A(authorization); return v11.coverage(eid)


class Obj(BaseModel):
    exam_id: str
    summary: str
    domain_key: str
    lab_ids: list[str] = []


@app.post("/api/objectives")
def add_obj(b: Obj, authorization: Optional[str] = Header(None)):
    return v11.add_objective(A(authorization), b.exam_id, b.summary, b.domain_key, b.lab_ids)


class ObjVerify(BaseModel):
    source_checked: bool = False


@app.post("/api/objectives/{oid}/verify")
def obj_verify(oid: str, b: ObjVerify, authorization: Optional[str] = Header(None)):
    return v11.verify_objective(A(authorization), oid, b.source_checked)


@app.get("/api/source-conflicts")
def src_conf(exam_id: Optional[str] = None, authorization: Optional[str] = Header(None)):
    A(authorization); return {"conflicts": v11.conflicts(exam_id), "sources": {k: {"title": t, "url": u} for k, (t, u) in C.SOURCES.items()}}


class ConfRes(BaseModel):
    resolution: str
    evidence_refs: list[str]


@app.post("/api/source-conflicts/{cid}/resolve")
def conf_resolve(cid: str, b: ConfRes, authorization: Optional[str] = Header(None)):
    return v11.resolve_conflict(A(authorization), cid, b.resolution, b.evidence_refs)


class Rev(BaseModel):
    guide_revision: str
    objectives: list[dict[str, Any]] = []


@app.post("/api/source-docs/{exam}/revisions")
def revision(exam: str, b: Rev, authorization: Optional[str] = Header(None)):
    return v11.new_revision(A(authorization), exam, b.guide_revision, b.objectives)


@app.post("/api/source-docs/{exam}/revisions/{idx}/ack")
def rev_ack(exam: str, idx: int, authorization: Optional[str] = Header(None)):
    return v11.ack_revision(A(authorization), exam, idx)


@app.get("/api/items")
def items(exam: Optional[str] = None, authorization: Optional[str] = Header(None)):
    return v11.list_items(A(authorization), exam)


class Stage(BaseModel):
    stage: str


@app.post("/api/items/{iid}/review")
def item_rev(iid: str, b: Stage, authorization: Optional[str] = Header(None)):
    return v11.item_review(A(authorization), iid, b.stage)


class Recall(BaseModel):
    reason: str


@app.post("/api/items/{iid}/recall")
def item_recall(iid: str, b: Recall, authorization: Optional[str] = Header(None)):
    return v11.recall_item(A(authorization), iid, b.reason)


@app.get("/api/content-quality")
def quality(authorization: Optional[str] = Header(None)):
    staff_only(A(authorization), "instructor", "reviewer")
    return {**v11.item_quality(), "recalls": v11.V["recalls"]}


class Attempt(BaseModel):
    exam_id: str
    kind: str = "practice"
    max_items: Optional[int] = None
    duration_override_s: Optional[int] = None


@app.post("/api/exam-attempts")
def attempt(b: Attempt, authorization: Optional[str] = Header(None)):
    return v11.create_attempt(A(authorization), b.exam_id, b.kind, b.max_items, b.duration_override_s)


@app.get("/api/exam-attempts/{aid}")
def attempt_get(aid: str, authorization: Optional[str] = Header(None)):
    a = A(authorization)
    return v11.attempt_view(a, v11._get_attempt(a, aid))


class Resp(BaseModel):
    item_id: str
    answer: list[str]
    client_version: int = 1


@app.post("/api/exam-attempts/{aid}/responses")
def attempt_resp(aid: str, b: Resp, authorization: Optional[str] = Header(None)):
    return v11.respond(A(authorization), aid, b.item_id, b.answer, b.client_version)


@app.post("/api/exam-attempts/{aid}/submit")
def attempt_submit(aid: str, authorization: Optional[str] = Header(None)):
    return v11.submit(A(authorization), aid)


@app.get("/api/learners/{lid}/skills")
def l_skills(lid: str, authorization: Optional[str] = Header(None)):
    a = A(authorization)
    return v11.skills(a, a["user_id"] if lid == "me" else lid)


@app.get("/api/learners/{lid}/profile")
def l_profile(lid: str, authorization: Optional[str] = Header(None)):
    a = A(authorization)
    return v11.learner_profile(a, a["user_id"] if lid == "me" else lid)


class Plan(BaseModel):
    exam_id: str
    diagnostic: dict[str, float] = {}
    weekly_hours: int = 6


@app.post("/api/learning-plans")
def plan(b: Plan, authorization: Optional[str] = Header(None)):
    return v11.make_plan(A(authorization), b.exam_id, b.diagnostic, b.weekly_hours)


class LabEv(BaseModel):
    model_config = {"extra": "allow"}
    lab_id: str


@app.post("/api/lab-evidence")
def lab_submit(b: LabEv, authorization: Optional[str] = Header(None)):
    return v11.lab_submit(A(authorization), b.model_dump())


class LabRev(BaseModel):
    decision: str
    original_checked: bool = False
    note: str = ""
    rubric_scores: dict[str, int] = {}


@app.post("/api/lab-evidence/{eid}/review")
def lab_review(eid: str, b: LabRev, authorization: Optional[str] = Header(None)):
    return v11.lab_review(A(authorization), eid, b.decision, b.original_checked, b.note, b.rubric_scores)


@app.get("/api/lab-evidence")
def lab_list(authorization: Optional[str] = Header(None)):
    a = A(authorization)
    return [e for e in v11.V["lab_evidence"].values() if a["role"] in v11.STAFF or e["learner"] == a["user_id"]]


@app.get("/api/labs")
def labs_catalog(authorization: Optional[str] = Header(None)):
    A(authorization)
    return {"labs": labs.catalog(), "status_note": labs.STATUS_NOTE, "authored": len(labs.LABS), "total_packs_in_spec": len(__import__("backend.content", fromlist=["PACKS"]).PACKS),
            "path": "C 경로(검토형 증거 제출): 학습자 PC의 adapter가 본인 교육용 워크스페이스에서 실행 → 체크섬 증거 제출 → 서버 자동 대조 → 검토자 원본 확인. 이 서버는 Databricks 자격증명을 받지 않음."}


@app.get("/api/labs/{lab_id}/pack")
def lab_pack(lab_id: str, authorization: Optional[str] = Header(None)):
    A(authorization)
    p = labs.pack(lab_id)
    if not p:
        raise ApiError(404, "NO_LAB", lab_id)
    return p


@app.get("/api/required-labs/{exam}")
def req_labs(exam: str, authorization: Optional[str] = Header(None)):
    a = A(authorization)
    return v11.labs_status(a["user_id"], exam)


class Pract(BaseModel):
    learner: str
    exam_id: str
    practical: int
    explain: int
    capstone_hintless: bool = True


@app.post("/api/practical-records")
def pract(b: Pract, authorization: Optional[str] = Header(None)):
    return v11.record_practical(A(authorization), b.learner, b.exam_id, b.practical, b.explain, b.capstone_hintless)


class Ready(BaseModel):
    learner: Optional[str] = None
    exam_id: str


@app.post("/api/readiness-decisions")
def ready(b: Ready, authorization: Optional[str] = Header(None)):
    a = A(authorization)
    return v11.readiness(a, b.learner or a["user_id"], b.exam_id)


class Grade(BaseModel):
    model_config = {"extra": "allow"}
    learner: str
    track: str
    grade: str


@app.post("/api/grade-decisions")
def grade(b: Grade, authorization: Optional[str] = Header(None)):
    return v11.grade_decide(A(authorization), b.model_dump())


class Cred(BaseModel):
    model_config = {"extra": "allow"}
    name: str


@app.post("/api/credentials")
def cred(b: Cred, authorization: Optional[str] = Header(None)):
    return v11.cred_add(A(authorization), b.model_dump())


class CredV(BaseModel):
    issuer: Optional[str] = None
    credential_id: Optional[str] = None
    verification_url: Optional[str] = None
    obtained: Optional[str] = None
    expires: Optional[str] = None


@app.post("/api/credentials/{ref}/verify")
def cred_v(ref: str, b: CredV, authorization: Optional[str] = Header(None)):
    return v11.cred_verify(A(authorization), ref, b.model_dump())


@app.get("/api/partner-dashboard")
def partner(authorization: Optional[str] = Header(None)):
    staff_only(A(authorization), "instructor", "reviewer")
    return v11.partner_dashboard()


class Tutor(BaseModel):
    question: str
    hint_level: Optional[int] = None


@app.post("/api/tutor/ask")
def tutor(b: Tutor, authorization: Optional[str] = Header(None)):
    return v11.tutor_ask(A(authorization), b.question, b.hint_level)


@app.get("/api/issues")
def issues(authorization: Optional[str] = Header(None)):
    staff_only(A(authorization), "instructor", "reviewer")
    return v11.list_issues()


@app.get("/api/v11/audit")
def v11_audit(authorization: Optional[str] = Header(None)):
    staff_only(A(authorization), "instructor", "reviewer")
    return v11.V["audit"][-200:]


class Recheck(BaseModel):
    workspace_checked: bool = False


@app.post("/api/features/{fid}/recheck")
def feature_recheck(fid: str, b: Recheck, authorization: Optional[str] = Header(None)):
    return v11_ext.recheck_feature(A(authorization), core.FEATURES, fid, b.workspace_checked)


@app.get("/api/verification-matrix")
def matrix(authorization: Optional[str] = Header(None)):
    A(authorization)
    return v11_ext.matrix_summary(core.FEATURES)


class Row(BaseModel):
    model_config = {"extra": "allow"}


@app.post("/api/verification-matrix")
def matrix_add(b: Row, authorization: Optional[str] = Header(None)):
    return v11_ext.matrix_add(A(authorization), b.model_dump())


class Free(BaseModel):
    model_config = {"extra": "allow"}


@app.post("/api/academy-records")
def academy_add(b: Free, authorization: Optional[str] = Header(None)):
    return v11_ext.academy_add(A(authorization), b.model_dump())


class SrcRef(BaseModel):
    source_url: str = ""


@app.post("/api/academy-records/{rid}/verify")
def academy_verify(rid: str, b: SrcRef, authorization: Optional[str] = Header(None)):
    return v11_ext.academy_verify(A(authorization), rid, b.source_url)


@app.get("/api/learners/{lid}/academy")
def academy_list(lid: str, authorization: Optional[str] = Header(None)):
    a = A(authorization)
    return v11_ext.academy_list(a, a["user_id"] if lid == "me" else lid)


@app.post("/api/assignment-authorizations")
def assign(b: Free, authorization: Optional[str] = Header(None)):
    return v11_ext.assignment_grant(A(authorization), b.model_dump())


class Reason(BaseModel):
    reason: str = ""


@app.post("/api/assignment-authorizations/{aid}/revoke")
def assign_revoke(aid: str, b: Reason, authorization: Optional[str] = Header(None)):
    return v11_ext.assignment_revoke(A(authorization), aid, b.reason)


@app.get("/api/learners/{lid}/assignments")
def assign_list(lid: str, authorization: Optional[str] = Header(None)):
    a = A(authorization)
    return v11_ext.assignments_for(a, a["user_id"] if lid == "me" else lid)


@app.get("/api/privacy-policy")
def privacy_policy(authorization: Optional[str] = Header(None)):
    A(authorization)
    return v11_ext.PRIVACY


@app.get("/api/learners/me/export")
def privacy_export(authorization: Optional[str] = Header(None)):
    return v11_ext.privacy_export(A(authorization))


@app.post("/api/learners/me/delete")
def privacy_delete(authorization: Optional[str] = Header(None)):
    return v11_ext.privacy_delete(A(authorization))


@app.get("/api/sessions/{sid}/track")
def track(sid: str, authorization: Optional[str] = Header(None)):
    a = actor_of(authorization); S = sess(sid, a)
    with core.lock_for(sid):
        return guide.track(S)


@app.get("/api/sessions/{sid}/demo")
def demo(sid: str, authorization: Optional[str] = Header(None)):
    a = actor_of(authorization); S = sess(sid, a)
    with core.lock_for(sid):
        return guide.demo(S)


@app.get("/api/sessions/{sid}/cost")
def cost(sid: str, authorization: Optional[str] = Header(None)):
    a = actor_of(authorization); S = sess(sid, a)
    return core.cost_view(S)


@app.get("/api/pilot-report")
def pilot_report(authorization: Optional[str] = Header(None)):
    staff_only(A(authorization), "instructor", "reviewer")
    ss = list(core.SESSIONS.values())
    prog = [guide.journey(S)["percent"] for S in ss]
    atts = [a for a in v11.V["attempts"].values() if a["status"] != "IN_PROGRESS"]
    ev = {}
    for e in v11.V["lab_evidence"].values():
        ev[e["status"]] = ev.get(e["status"], 0) + 1
    n = len(ss)
    return {"sessions": n, "learners": len({S["owner"] for S in ss}), "avg_progress_pct": round(sum(prog) / n, 1) if n else None, "completed_100": sum(1 for x in prog if x == 100),
            "avg_hints_used": round(sum(S["hints_used"] for S in ss) / n, 2) if n else None, "admin_assisted_total": sum(S["admin_assisted"] for S in ss), "resets": sum(len(S["resets"]) for S in ss),
            "failed_or_blocked_events": sum(1 for S in ss for e in S["audit"] if e["outcome"] in ("failed", "blocked", "conflict")), "exam_attempts": len(atts),
            "lab_evidence_by_status": ev, "sample_note": "표본이 작으면 일반화·효과 주장을 하지 않습니다. 사전-사후·지연 평가 비교(12명 이상 목표)는 실제 파일럿 수행 후 이 지표로 산출합니다(파일럿 미수행).",
            "metrics_defined": ["objective별 향상", "새 과제 성공률", "힌트 의존도", "치명적 실패", "소요시간", "중도 포기", "검토자 간 일치"], "metrics_collected_now": ["진행률", "힌트", "대리처리", "초기화", "실패 이벤트", "응시", "증거 상태"]}


@app.get("/api/health")
def health():
    return {"ok": True, "sessions": len(core.SESSIONS)}


# ---------------------------------------------------------------- static
app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")


# ---------------------------------------------------------------- 전이 산업 시드 · 협업 훈련
@app.get("/api/transfer-seeds")
def transfer_seeds(authorization: Optional[str] = Header(None)):
    A(authorization)
    return transfer.seed_list()


@app.get("/api/transfer-seeds/{sid}/files")
def transfer_seed_files(sid: str, authorization: Optional[str] = Header(None)):
    A(authorization)
    return transfer.seed_files(sid)


@app.get("/api/transfer-seeds/{sid}/answer-key")
def transfer_seed_key(sid: str, authorization: Optional[str] = Header(None)):
    return transfer.seed_answer_key(A(authorization), sid)


@app.get("/api/ko-guide")
def ko_guide_view(authorization: Optional[str] = Header(None)):
    A(authorization)
    return ko_guide.ko_guide()


@app.get("/api/review/queue")
def review_queue(authorization: Optional[str] = Header(None)):
    a = A(authorization); staff_only(a, "reviewer", "instructor")
    V = v11.V
    objs = [o for o in V["objectives"] if o.get("granularity") == "OFFICIAL_BULLET"]
    nv = [o for o in objs if not o.get("verified_at")]
    items = list(V["items"].values())
    nxt = {"DRAFT": "tech", "TECH_REVIEWED": "assessment", "ASSESSMENT_REVIEWED": "pilot", "PILOTED": "activate"}
    feats = [f for f in core.FEATURES if f.get("status") != "WORKSPACE_CHECKED"]
    return {"me": a["user_id"], "objectives": {"total": len(objs), "verified": len(objs) - len(nv), "unverified_sample": [{"id": o["objective_id_internal"], "exam": o["exam_id"], "summary": o.get("objective_summary", "")[:90]} for o in nv[:15]]},
            "items": {"total": len(items), "by_status": {k: sum(1 for i in items if i["status"] == k) for k in sorted({i["status"] for i in items})},
                      "queue": [{"id": i["item_id"], "exam": i["exam"], "status": i["status"], "next": nxt.get(i["status"]), "tech_reviewer": i.get("technical_reviewer")} for i in items if i["status"] in nxt][:15]},
            "features": {"total": len(core.FEATURES), "not_workspace_checked": [{"id": f["feature_id"], "status": f.get("status")} for f in feats]},
            "lab_evidence_pending": sum(1 for e in V["lab_evidence"].values() if e.get("status") not in ("APPROVED", "REJECTED")),
            "matrix_rows": len(V.get("verification_matrix", [])),
            "note": "문항 기술 검토와 출제 검토는 서로 다른 사람이어야 합니다 — 컨설턴트 1인이 기술 검토, 다른 직원(강사)이 출제 검토를 수행하세요."}


@app.get("/api/system/info")
def system_info(authorization: Optional[str] = Header(None)):
    A(authorization)
    return sysinfo.info()


@app.get("/api/system/update-check")
def system_update(build: str = "", authorization: Optional[str] = Header(None)):
    A(authorization)
    return sysinfo.update_check(build)


@app.get("/api/app/manifest")
def app_manifest():
    return sysinfo.app_manifest()


def _dl_log(request: Request, what: str):
    """다운로드 기록: 웹에서 받았는지, 설치형 앱이 업데이트로 받았는지(설치 ID·버전 헤더)를 함께 남긴다."""
    h = request.headers
    inst = (h.get("x-dbx-install") or "")[:32]
    ok = bool(re.fullmatch(r"[0-9a-f]{32}", inst))
    usage.log("download", None, request, what=what, inst=inst[:12] if ok else None, app=(h.get("x-dbx-app") or "")[:40] or None, via="app" if ok else "web")


@app.post("/api/feedback/intake")
async def fb_intake(request: Request):
    """중앙 서버 전용: 단독형 앱의 피드백 접수(비로그인, 한도 있음)."""
    if int(request.headers.get("content-length", "0") or 0) > 25 * 1024 * 1024:
        raise ApiError(413, "TOO_LARGE", "요청이 너무 큽니다.")
    ip = (request.headers.get("x-forwarded-for") or request.headers.get("x-real-ip") or (request.client.host if request.client else "?")).split(",")[0].strip()
    body = await request.json()
    r = feedback.intake(ip, body)
    ins = body.get("install") if isinstance(body, dict) else None
    usage.log("feedback", {"name": str(body.get("name", ""))[:40], "role": "standalone"}, request, kind=str(body.get("kind", ""))[:20], source="standalone", inst=(str(ins.get("install"))[:12] if isinstance(ins, dict) and ins.get("install") else None))
    return r


@app.post("/api/feedback/intake/status-batch")
async def fb_intake_status_batch(request: Request):
    ip = (request.headers.get("x-forwarded-for") or request.headers.get("x-real-ip") or (request.client.host if request.client else "?")).split(",")[0].strip()
    body = await request.json()
    return feedback.intake_status_batch(ip, (body or {}).get("items") or [])


@app.post("/api/feedback/sync")
def fb_sync(authorization: Optional[str] = Header(None)):
    """설치형 앱: 내 피드백의 운영 서버 처리 상태를 지금 확인한다([지금 확인] 버튼)."""
    a = A(authorization)
    if not feedback.standalone():
        return {"standalone": False}
    r = feedback.sync(a, force=True)
    return {"standalone": True, **r}


@app.get("/api/feedback/intake/{fid}")
def fb_intake_status(fid: str, receipt: str = ""):
    return feedback.intake_status(fid, receipt)


@app.get("/download/pack")
def download_pack(request: Request):
    _dl_log(request, "pack")
    from fastapi.responses import Response
    data, mf = pack_mod.build(sysinfo.VERSION, sysinfo.STANDALONE_COMPAT, sysinfo.ROOT)
    return Response(data, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="dbx-pack-{mf["content_id"]}.zip"', "Cache-Control": "no-store"})


@app.get("/download/standalone-mac-arm64")
def download_mac_arm64(request: Request):
    _dl_log(request, "mac_arm64")
    return _mac_file("mac_arm64")


@app.get("/download/standalone-mac-x64")
def download_mac_x64(request: Request):
    _dl_log(request, "mac_x64")
    return _mac_file("mac_x64")


def _mac_file(k):
    f = sysinfo.MAC_FILES[k]
    if not f.is_file():
        raise ApiError(404, "APP_NOT_BUILT", "Mac용 설치 파일이 아직 준비되지 않았습니다.")
    return FileResponse(str(f), media_type="application/zip", filename=f.name)


@app.get("/download/standalone")
def download_standalone(request: Request):
    _dl_log(request, "windows_standalone")
    if not sysinfo.STANDALONE_FILE.is_file():
        raise ApiError(404, "APP_NOT_BUILT", "단독 설치형 파일이 아직 준비되지 않았습니다.")
    return FileResponse(str(sysinfo.STANDALONE_FILE), media_type="application/octet-stream", filename=sysinfo.STANDALONE_FILE.name)


_TEL_HITS: dict = {}
_TEL_EVENTS = {"login": "app_login", "start": "app_start", "update_offered": "app_update", "update_applied": "app_update", "update_failed": "app_update"}


@app.post("/api/app/telemetry")
def app_telemetry(b: Free, request: Request):
    """설치형 앱의 실행·업데이트 신호 수신(비로그인, 한도 있음). 서버 접속 기록(usage)에 남는다."""
    d = b.model_dump()
    ev = str(d.get("event", ""))
    inst = str(d.get("install", ""))
    if ev not in _TEL_EVENTS or not re.fullmatch(r"[0-9a-f]{32}", inst):
        raise ApiError(400, "BAD_TELEMETRY", "형식이 올바르지 않습니다.")
    ip = usage.ip_of(request) or "?"
    now = time.time()
    for key in (inst, "ip:" + ip):
        hits = [t for t in _TEL_HITS.get(key, []) if now - t < 3600]
        if len(hits) >= (60 if key == inst else 300):
            raise ApiError(429, "TOO_MANY", "잠시 후 다시 시도하세요.")
        _TEL_HITS[key] = hits + [now]
    plat = str(d.get("platform", ""))[:20]
    detail = {"inst": inst[:12], "ver": str(d.get("app_version", ""))[:20], "plat": plat if re.fullmatch(r"[a-z0-9_]{1,20}", plat) else "?", "os": str(d.get("os", ""))[:60], "cid": str(d.get("content_id", ""))[:16]}
    if ev not in ("start", "login"):
        detail.update(result={"update_offered": "offered", "update_applied": "applied", "update_failed": "failed"}[ev], kind=str(d.get("kind", ""))[:8], frm=str(d.get("from_version", ""))[:20],
                      to=str(d.get("to_version", ""))[:20], err=str(d.get("error", ""))[:80] or None)
    user = str(d.get("user", "")).strip()[:40]
    if user:
        detail["usr"] = user
    if ev == "login":
        if len(user) < 2:
            raise ApiError(400, "BAD_TELEMETRY", "사용자 이름이 필요합니다.")
        usage.log("app_login", {"name": user, "role": "standalone"}, request, **detail)
    else:
        usage.log(_TEL_EVENTS[ev], None, request, **detail)
    return {"ok": True}


@app.get("/api/app/telemetry-setting")
def telemetry_get(authorization: Optional[str] = Header(None)):
    A(authorization)
    return {"standalone": telemetry.standalone(), "enabled": telemetry.enabled(), "install": telemetry.install_id()[:8] if telemetry.standalone() else ""}


@app.post("/api/app/telemetry-setting")
def telemetry_set(b: Free, authorization: Optional[str] = Header(None)):
    A(authorization)
    if not telemetry.standalone():
        raise ApiError(400, "NOT_STANDALONE", "설치형 앱에서만 설정할 수 있습니다.")
    telemetry.set_enabled(bool(b.model_dump().get("on")))
    return {"standalone": True, "enabled": telemetry.enabled(), "install": telemetry.install_id()[:8]}


@app.get("/api/usage/installs")
def usage_installs(days: int = 30, q: str = "", offset: int = 0, limit: int = 15, authorization: Optional[str] = Header(None)):
    staff_only(A(authorization), "admin")
    return usage.installs(days, q, offset, limit)


@app.get("/download/app")
def download_app(request: Request):
    _dl_log(request, "windows_shell")
    if not sysinfo.APP_FILE.is_file():
        raise ApiError(404, "APP_NOT_BUILT", "설치 파일이 아직 준비되지 않았습니다.")
    return FileResponse(str(sysinfo.APP_FILE), media_type="application/octet-stream", filename=sysinfo.APP_FILE.name)


@app.get("/api/system/document")
def system_document(authorization: Optional[str] = Header(None), user_agent: Optional[str] = Header(None)):
    staff_only(A(authorization), "admin")  # 시스템 문서는 admin(수퍼유저) 전용
    if "DBXDesktop" in (user_agent or ""):
        raise ApiError(403, "NOT_IN_DESKTOP_APP", "시스템 문서는 PC 앱에 포함되지 않습니다. 웹 사이트에서 내려받으세요.")
    from fastapi.responses import Response
    return Response(sysinfo.system_document(), media_type="text/markdown; charset=utf-8", headers={"Content-Disposition": "attachment; filename*=UTF-8''%EC%8B%9C%EC%8A%A4%ED%85%9C%EB%AC%B8%EC%84%9C.md"})


@app.get("/api/review/manual")
def review_manual(authorization: Optional[str] = Header(None)):
    staff_only(A(authorization), "reviewer", "instructor")
    from fastapi.responses import Response
    return Response(sysinfo.reviewer_manual(), media_type="text/markdown; charset=utf-8", headers={"Content-Disposition": "attachment; filename*=UTF-8''%EA%B2%80%ED%86%A0%EC%9E%90_%EB%A7%A4%EB%89%B4%EC%96%BC.md"})


@app.get("/api/collab/scenario")
def collab_scenario(authorization: Optional[str] = Header(None)):
    A(authorization)
    return transfer.collab_scenario()


@app.post("/api/collab/teams")
def collab_create(b: Free, authorization: Optional[str] = Header(None)):
    return transfer.collab_create(A(authorization), b.model_dump())


@app.post("/api/collab/teams/{tid}/join")
def collab_join(tid: str, b: Free, authorization: Optional[str] = Header(None)):
    return transfer.collab_join(A(authorization), tid, b.model_dump().get("role", ""))


@app.post("/api/collab/teams/{tid}/tasks/{task_id}/submit")
def collab_submit(tid: str, task_id: str, b: Free, authorization: Optional[str] = Header(None)):
    return transfer.collab_submit(A(authorization), tid, task_id, b.model_dump())


@app.post("/api/collab/teams/{tid}/tasks/{task_id}/review")
def collab_review(tid: str, task_id: str, b: Free, authorization: Optional[str] = Header(None)):
    d = b.model_dump()
    return transfer.collab_review(A(authorization), tid, task_id, bool(d.get("approve")), str(d.get("reason", "")))


@app.get("/api/collab/teams/{tid}")
def collab_status(tid: str, authorization: Optional[str] = Header(None)):
    return transfer.collab_status(A(authorization), tid)



@app.get("/api/feedback/meta")
def fb_meta(authorization: Optional[str] = Header(None)):
    A(authorization)
    return {"kinds": feedback.KINDS, "status": feedback.STATUS, "max_images": feedback.MAX_IMAGES, "max_image_mb": feedback.MAX_IMG_BYTES // 1048576}


@app.post("/api/feedback")
def fb_submit(b: Free, request: Request, authorization: Optional[str] = Header(None)):
    a = A(authorization)
    r = feedback.submit(a, b.model_dump())
    usage.log("feedback", a, request, kind=b.model_dump().get("kind"))
    return r


@app.get("/api/feedback/mine")
def fb_mine(authorization: Optional[str] = Header(None)):
    return feedback.mine(A(authorization))


@app.post("/api/feedback/mine/seen")
def fb_seen(authorization: Optional[str] = Header(None)):
    return feedback.mark_seen(A(authorization))


@app.get("/api/feedback/admin")
def fb_admin(status: str = "", q: str = "", page: int = 0, size: int = 25, authorization: Optional[str] = Header(None)):
    return feedback.admin_list(A(authorization), status, q, page, size)


@app.get("/api/feedback/queue.md")
def fb_queue(authorization: Optional[str] = Header(None)):
    from fastapi.responses import Response
    return Response(feedback.queue_md(A(authorization)), media_type="text/markdown; charset=utf-8", headers={"Content-Disposition": "attachment; filename*=UTF-8''%EA%B0%9C%EB%B0%9C%ED%81%90.md"})


@app.post("/api/feedback/delete")
def fb_delete(b: Free, request: Request, authorization: Optional[str] = Header(None)):
    a = A(authorization)
    r = feedback.delete(a, b.model_dump().get("ids") or [])
    usage.log("feedback_admin", a, request, action="delete", count=len(r["deleted"]))
    return r


@app.post("/api/feedback/bulk")
def fb_bulk(b: Free, request: Request, authorization: Optional[str] = Header(None)):
    a = A(authorization)
    d = b.model_dump()
    r = feedback.bulk_transition(a, d.get("ids") or [], str(d.get("to", "")), d.get("note", ""), d.get("priority"), d.get("released_version"))
    usage.log("feedback_admin", a, request, action="bulk", to=d.get("to"), ok=len(r["ok"]), failed=len(r["failed"]))
    return r


@app.post("/api/feedback/{fid}/edit")
def fb_edit(fid: str, b: Free, request: Request, authorization: Optional[str] = Header(None)):
    a = A(authorization)
    r = feedback.edit(a, fid, b.model_dump())
    usage.log("feedback_admin", a, request, action="edit")
    return r


@app.get("/api/feedback/{fid}")
def fb_get(fid: str, authorization: Optional[str] = Header(None)):
    return feedback.get(A(authorization), fid)


@app.get("/api/feedback/{fid}/image/{n}")
def fb_image(fid: str, n: int, authorization: Optional[str] = Header(None)):
    path, ext = feedback.image(A(authorization), fid, n)
    return FileResponse(str(path), media_type={"png": "image/png", "jpg": "image/jpeg", "gif": "image/gif", "webp": "image/webp"}[ext], headers={"X-Content-Type-Options": "nosniff", "Content-Security-Policy": "default-src 'none'"})


@app.post("/api/feedback/{fid}/transition")
def fb_transition(fid: str, b: Free, authorization: Optional[str] = Header(None)):
    d = b.model_dump()
    return feedback.transition(A(authorization), fid, str(d.get("to", "")), d.get("note", ""), d.get("priority"), d.get("released_version"))



class ViewBeat(BaseModel):
    view: str


@app.post("/api/usage/view")
def usage_view(b: ViewBeat, request: Request, authorization: Optional[str] = Header(None)):
    a = actor_of(authorization)
    if re.fullmatch(r"[a-z0-9]{2,12}", b.view or ""):
        usage.log("view", a, request, view=b.view)
    return {"ok": True}


@app.get("/api/usage/summary")
def usage_summary(days: int = 30, authorization: Optional[str] = Header(None)):
    staff_only(A(authorization), "admin")
    return usage.summary(days)


@app.get("/api/usage/pulse")
def usage_pulse(authorization: Optional[str] = Header(None)):
    """새 기록이 생겼는지만 알려 주는 초경량 호출(화면이 주기적으로 확인한다)."""
    staff_only(A(authorization), "admin")
    return {"fp": usage.fingerprint()}


@app.get("/api/usage/events")
def usage_events(limit: int = 100, offset: int = 0, kind: str = "", q: str = "", days: int = 0, authorization: Optional[str] = Header(None)):
    staff_only(A(authorization), "admin")
    return usage.events(limit, offset, kind, q, days)


@app.get("/api/usage/users")
def usage_users(days: int = 30, q: str = "", offset: int = 0, limit: int = 15, authorization: Optional[str] = Header(None)):
    staff_only(A(authorization), "admin")
    return usage.users(days, q, offset, limit)


@app.get("/api/real/status")
def real_status(authorization: Optional[str] = Header(None)):
    A(authorization)
    return real.status()


@app.post("/api/real/config")
def real_config(b: Free, request: Request, authorization: Optional[str] = Header(None)):
    a = A(authorization)
    r = real.save_config(b.model_dump())
    usage.log("real_conn", a, request, action="save")                 # 호스트·토큰은 기록하지 않는다
    return r


@app.delete("/api/real/config")
def real_clear(request: Request, authorization: Optional[str] = Header(None)):
    a = A(authorization)
    usage.log("real_conn", a, request, action="clear")
    return real.clear_config()


@app.post("/api/real/test")
def real_test(request: Request, authorization: Optional[str] = Header(None)):
    a = A(authorization)
    r = real.test()
    usage.log("real_conn", a, request, action="test")
    return r


@app.post("/api/real/sql")
def real_sql(b: Free, request: Request, authorization: Optional[str] = Header(None)):
    a = A(authorization)
    d = b.model_dump()
    try:
        r = real.run_sql(str(d.get("sql", "")), bool(d.get("confirm")))
    except ApiError as e:
        usage.log("real_sql", a, request, ok=False, code=e.code)
        raise
    usage.log("real_sql", a, request, ok=True, kw=r["keyword"], ms=r["ms"])
    return r


@app.get("/")
def index():
    return FileResponse(str(ROOT / "static" / "index.html"), headers={"Cache-Control": "no-store"})
