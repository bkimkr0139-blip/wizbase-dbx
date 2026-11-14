"""AX 프로젝트 스튜디오(v0.7.0, 개발 지시서 v1.0 P0~P2 + 첫 vertical slice).

범위(정직한 표기):
- 실제로 동작하는 것: 프로젝트·권한, SQLite 합성 레거시 fixture 연결·구조 수집·snapshot·diff, 통합 ERD 부분모델, 관계 후보 추론·검토,
  표본 profile, 온톨로지 release(내부 shape 검증·검토·STALE), 네이티브 파이프라인 실행, 결정적 도구 에이전트(LLM 없음),
  제안→승인→멱등 업무 명령(fixture 원천), golden 평가.
- 아직 실제로 실행하지 못한 것: Oracle/PostgreSQL/MySQL 실제 접속(드라이버 미설치·고객 개발 DB 미연결, 딕셔너리 SQL만 준비),
  DBX 경로 실제 배포(SQL 산출물 컴파일까지), 실제 LLM·embedding 검색, SHACL 검증기, 부하 시험.
"""
from __future__ import annotations
import hashlib, ipaddress, json, os, re, secrets, shutil, socket, sqlite3, ssl, threading, time
from datetime import date, datetime, timezone
from pathlib import Path

from decimal import Decimal

from .core import ApiError
from . import ax_db, ax_fixture, ax_tools, ax_search

ROOT = Path(__file__).resolve().parent.parent
BASE = Path(os.environ.get("DBX_DATA_DIR", ROOT / "data")) / "ax"
STORE = BASE / "store.json"
LOCK = threading.RLock()
S: dict = {}
MODES = ("DEMO_SYNTHETIC", "DEV_NATIVE", "DEV_DBX", "RELEASE_CANDIDATE")
ENGINES = ("native", "databricks")
PROJ_ROLES = ("architect", "domain_expert", "developer", "reviewer", "business_user")
APPROVER_ROLES = ("domain_expert", "reviewer")
EVIDENCE = "NATIVE_FIXTURE"  # 이 환경에서 얻을 수 있는 최고 증거 수준: 합성 fixture 위의 실제 실행
METRIC_REGISTRY = {"additional_available_qty": "재고 − 확정 예약 합계(해당 tenant·품목)"}
POLICY_REGISTRY = {"change_order_increase": "주문 증량: 추가 가용·여신 한도 확인 후 가능/조건부/불가", "delay_alternatives": "납기 지연 대안(부분·분할·대기)", "price_diff_reason": "단가 차이 원인(계약 유효일 기준)",
                   "receivable_summary": "거래처 미수금(원장 기준)", "purchase_reorder": "부족품목 추가 발주 대안(MOQ·pack·리드타임·가중 비교)", "supplier_switch": "공급처 변경 대안", "price_spike": "매입단가 급등 대응", "receipt_variance": "입고 차이·허용오차"}
SUPPORT = [
    {"engine": "sqlite_fixture", "version": "SQLite(내장)", "status": "EXECUTED_FIXTURE", "note": "합성 fixture로 구조 수집·ERD·profile·질의·명령을 실제 실행"},
    {"engine": "postgresql", "version": "PostgreSQL 16.16 (Docker 시험 DB)", "status": "EXECUTED_DEV_CONTAINER", "verified_on": "2026-11-14", "driver": "psycopg2 2.9.13",
     "note": "합성 fixture를 적재한 시험 DB에서 연결 7단계·구조 수집(복합키·self FK·한글 주석·뷰)·관계 후보·profile·질의·업무 명령·계정 분리 확인. 고객 DB·다른 버전·TLS는 미확인. 읽기 전용 계정은 information_schema 에서 제약이 숨겨져 pg_catalog 를 사용"},
    {"engine": "mysql", "version": "MySQL 8.4.13 (Docker 시험 DB)", "status": "EXECUTED_DEV_CONTAINER", "verified_on": "2026-11-14", "driver": "PyMySQL 1.1.x",
     "note": "위와 같은 시험 통과. 뷰 정의를 읽으려면 SHOW VIEW 권한 필요, 잠금 조회(FOR UPDATE)에는 UPDATE 권한이 필요. MariaDB·다른 버전·TLS는 미확인(별도 검증 프로필)"},
    {"engine": "oracle", "version": "Oracle AI Database 26ai Free 23.26.3 (Docker 시험 DB)", "status": "EXECUTED_DEV_CONTAINER", "verified_on": "2026-11-14", "driver": "python-oracledb 3.x(thin)",
     "note": "위와 같은 시험 통과(ALL_* 딕셔너리, DBA_* 불필요). 11g/12c/19c 등 다른 버전·RAC·TLS·고객 DB는 미확인. 따옴표 소문자 식별자는 시험하지 않음"},
    {"engine": "sqlserver", "version": "-", "status": "NOT_STARTED", "note": "다음 connector 팩"},
]
DICT_SQL = {
    "oracle": {"tables": "SELECT owner, table_name FROM all_tables WHERE owner IN (:schemas)",
               "columns": "SELECT owner, table_name, column_name, data_type, nullable, data_default, column_id FROM all_tab_columns",
               "constraints": "SELECT c.owner, c.table_name, c.constraint_name, c.constraint_type, c.status, c.validated, c.r_owner, c.r_constraint_name FROM all_constraints c",
               "key_columns": "SELECT owner, constraint_name, table_name, column_name, position FROM all_cons_columns ORDER BY owner, constraint_name, position"},
    "postgresql": {"tables": "SELECT table_schema, table_name, table_type FROM information_schema.tables WHERE table_schema = ANY(%s)",
                   "columns": "SELECT table_schema, table_name, column_name, data_type, is_nullable, column_default, ordinal_position FROM information_schema.columns",
                   "constraints": "SELECT conname, conrelid::regclass, contype, convalidated, conkey, confrelid::regclass, confkey FROM pg_constraint",
                   "key_columns": "SELECT constraint_schema, constraint_name, table_name, column_name, ordinal_position, position_in_unique_constraint FROM information_schema.key_column_usage"},
    "mysql": {"tables": "SELECT table_schema, table_name, table_type FROM information_schema.tables WHERE table_schema IN (%s)",
              "columns": "SELECT table_schema, table_name, column_name, column_type, is_nullable, column_default, ordinal_position, column_comment FROM information_schema.columns",
              "key_columns": "SELECT constraint_schema, constraint_name, table_name, column_name, ordinal_position, referenced_table_schema, referenced_table_name, referenced_column_name FROM information_schema.key_column_usage"},
}


def _now():
    return datetime.now(timezone.utc).isoformat()


def _id(p):
    return f"{p}-{secrets.token_hex(5)}"


def _save():
    with LOCK:
        BASE.mkdir(parents=True, exist_ok=True)
        tmp = STORE.with_suffix(".tmp")
        tmp.write_text(json.dumps(S, ensure_ascii=False, default=str), encoding="utf-8")
        os.replace(tmp, STORE)


def init():
    global S
    BASE.mkdir(parents=True, exist_ok=True)
    if STORE.exists():
        S = json.loads(STORE.read_text(encoding="utf-8"))
    else:
        S = {}
    for k in ("projects", "connectors", "snapshots", "relations", "profiles", "releases", "runs", "proposals", "commands", "evals", "deployments", "audit", "issues", "documents", "signals", "auto", "sources", "jobs"):
        S.setdefault(k, {} if k != "audit" else [])


def audit(actor, kind, project, ref="", outcome="ok", detail=None):
    S["audit"].append({"at": _now(), "actor": actor["user_id"], "kind": kind, "project": project, "ref": ref, "outcome": outcome, "detail": detail or {}})


# ------------------------------------------------------------------ 프로젝트·권한(서버 검사)
def _proj(a, pid, need=None, write=False):
    p = S["projects"].get(pid)
    if not p:
        raise ApiError(404, "AX_PROJECT_NOT_FOUND", "프로젝트를 찾을 수 없거나 접근 권한이 없습니다.")
    m = p["members"].get(a["user_id"])
    if not m and a["role"] != "admin":
        raise ApiError(404, "AX_PROJECT_NOT_FOUND", "프로젝트를 찾을 수 없거나 접근 권한이 없습니다.")
    role = (m or {}).get("role", "architect")
    if need and role not in need and a["role"] != "admin":
        raise ApiError(403, "AX_ROLE_REQUIRED", f"프로젝트 역할 {'/'.join(need)} 이(가) 필요합니다.")
    return p, (m or {"role": "architect", "tenants": None, "customers": None})


def _check_rev(obj, rev):
    if rev is not None and rev != obj.get("revision", 1):
        raise ApiError(409, "REVISION_CONFLICT", "다른 사용자가 먼저 수정했습니다. 새로 고친 뒤 다시 시도하세요.", current=obj.get("revision", 1))


def project_create(a, b):
    mode = b.get("mode", "DEMO_SYNTHETIC")
    engine = b.get("engine", "native")
    if mode not in MODES or engine not in ENGINES:
        raise ApiError(400, "BAD_PROJECT", f"mode={'|'.join(MODES)}, engine={'|'.join(ENGINES)}")
    name = (b.get("name") or "").strip()
    if len(name) < 2:
        raise ApiError(400, "BAD_PROJECT", "프로젝트 이름이 필요합니다.")
    if mode == "RELEASE_CANDIDATE":
        raise ApiError(400, "MODE_NOT_ALLOWED", "RELEASE_CANDIDATE는 승인된 별도 절차로만 전환합니다(새 프로젝트로 직접 만들 수 없음).")
    pid = _id("axp")
    p = {"project_id": pid, "name": name, "customer_id": (b.get("customer_id") or "demo-customer")[:60], "organization_id": (b.get("organization_id") or "wizbase")[:60],
         "environment_id": (b.get("environment_id") or "dev")[:40], "mode": mode, "engine": engine, "owner": a["user_id"],
         "source_scope": b.get("source_scope") or {"schemas": ["main"], "confirmed_by_dba": False},
         "data_contract": b.get("data_contract") or {"data_in_scope": "metadata+aggregate", "sample_rows_max": 1000},
         "retention_days": int(b.get("retention_days", 30)), "egress_policy": b.get("egress_policy") or {"external_llm": False, "raw_data_to_llm": False},
         "budget": b.get("budget") or {"profile_row_limit": 1000, "full_scan_allowed": False},
         "members": {a["user_id"]: {"role": "architect", "tenants": None, "customers": None}}, "revision": 1, "created_at": _now(), "active_release": None, "previous_release": None}
    with LOCK:
        S["projects"][pid] = p
        if mode == "DEMO_SYNTHETIC":
            _fixture_path(pid)
        audit(a, "AX_PROJECT_CREATE", pid)
        _save()
    return _pub(p)


def _pub(p):
    return {k: v for k, v in p.items()}


def project_list(a):
    return [_pub(p) for p in S["projects"].values() if a["user_id"] in p["members"] or a["role"] == "admin"]


def member_set(a, pid, b):
    p, _ = _proj(a, pid, ("architect",))
    uid, role = b.get("user_id"), b.get("role")
    if not uid or role not in PROJ_ROLES:
        raise ApiError(400, "BAD_MEMBER", f"user_id, role={'|'.join(PROJ_ROLES)}")
    p["members"][uid] = {"role": role, "tenants": b.get("tenants"), "customers": b.get("customers"), "suppliers": b.get("suppliers")}
    p["revision"] += 1
    audit(a, "AX_MEMBER_SET", pid, uid, detail={"role": role, "tenants": b.get("tenants"), "customers": b.get("customers"), "suppliers": b.get("suppliers")})
    _save()
    return {"ok": True, "members": p["members"]}


def member_remove(a, pid, uid):
    p, _ = _proj(a, pid, ("architect",))
    if uid == p["owner"]:
        raise ApiError(400, "OWNER_FIXED", "소유자는 제거할 수 없습니다.")
    p["members"].pop(uid, None)
    p["revision"] += 1
    audit(a, "AX_MEMBER_REMOVE", pid, uid)
    _save()
    return {"ok": True}


# ------------------------------------------------------------------ 합성 레거시 fixture
def _fixture_path(pid, kind="source"):
    d = BASE / pid
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"legacy_{kind}.sqlite"
    if not f.exists():
        _build_fixture(f)
    return f


def _build_fixture(f):
    ax_fixture.build_sqlite(f)


def _py(v):
    return (int(v) if v == int(v) else float(v)) if isinstance(v, Decimal) else v


def _src(pid, rw=False, purpose="runtime_read"):
    """계정 용도(purpose)별 연결. 실제 DB 연결이 등록돼 있으면 그것을, 합성 프로젝트면 fixture 를 쓴다."""
    p = S["projects"].get(pid, {})
    real = [c for c in S["connectors"].values() if c["project_id"] == pid and c["purpose"] == purpose and c["engine"] != "sqlite_fixture"]
    if real:
        return ax_db.open_conn(real[-1])
    if p.get("mode") != "DEMO_SYNTHETIC":
        raise ApiError(409, "CONNECTOR_PURPOSE_MISSING", f"용도 {purpose} 연결이 등록되지 않았습니다(계정 분리: metadata/profiling/runtime_read/command).")
    f = _fixture_path(pid)
    uri = f"file:{f.as_posix()}?mode={'rw' if rw else 'ro'}"
    c = sqlite3.connect(uri, uri=True, timeout=5)
    if not rw:
        c.execute("PRAGMA query_only=ON")
    return ax_db.SqliteConn(c)


# ------------------------------------------------------------------ 연결 센터(AX-02)
_BLOCK_HOSTS = ("metadata.google.internal", "metadata", "instance-data")


def _ip_blocked(ip):
    try:
        x = ipaddress.ip_address(ip)
    except ValueError:
        return True
    return x.is_link_local or x.is_multicast or x.is_unspecified or str(x) in ("169.254.169.254", "fd00:ec2::254")


def connector_create(a, pid, b):
    p, _ = _proj(a, pid, ("architect", "developer"))
    engine = b.get("engine")
    if engine not in [x["engine"] for x in SUPPORT]:
        raise ApiError(400, "BAD_ENGINE", "지원표를 확인하세요(GET /api/ax/support).")
    for k in b:
        if re.search(r"pass(word)?|secret$|token|apikey|api_key|credential", k, re.I) and k != "secret_ref":
            raise ApiError(400, "SECRET_IN_PAYLOAD", "비밀번호·토큰은 받지 않습니다. secret_ref(예: secret://dev-oracle-ro)로 참조만 등록하세요.")
    ref = b.get("secret_ref")
    if engine != "sqlite_fixture" and not (isinstance(ref, str) and ref.startswith("secret://") and len(ref) > 10):
        raise ApiError(400, "SECRET_REF_REQUIRED", "secret_ref 는 secret:// 로 시작하는 참조여야 합니다.")
    if engine == "sqlite_fixture" and p["mode"] != "DEMO_SYNTHETIC":
        raise ApiError(400, "FIXTURE_ONLY_DEMO", "sqlite_fixture 는 DEMO_SYNTHETIC 프로젝트에서만 쓸 수 있습니다.")
    if engine != "sqlite_fixture" and not b.get("schema_allowlist"):
        raise ApiError(400, "SCHEMA_ALLOWLIST_REQUIRED", "실제 DB 연결은 schema_allowlist(허용 schema)가 필요합니다.")
    purpose = b.get("purpose", "metadata")
    if purpose not in ("metadata", "profiling", "runtime_read", "command"):
        raise ApiError(400, "BAD_PURPOSE", "purpose=metadata|profiling|runtime_read|command")
    cid = _id("axc")
    c = {"connector_id": cid, "project_id": pid, "engine": engine, "purpose": purpose, "env_label": b.get("env_label", "dev"), "host": b.get("host"), "port": b.get("port"),
         "database": b.get("database"), "service_name": b.get("service_name"), "schema_allowlist": b.get("schema_allowlist") or p["source_scope"].get("schemas", []), "tls": bool(b.get("tls", True)),
         "timeout_s": min(int(b.get("timeout_s", 5)), 30), "max_connections": min(int(b.get("max_connections", 2)), 10), "owner": b.get("owner") or a["user_id"], "schema_allowlist_set": bool(b.get("schema_allowlist")),
         "dba_confirmed_non_prod": bool(b.get("dba_confirmed_non_prod", False)), "secret_ref": ref, "revision": 1, "created_at": _now(), "last_test": None}
    S["connectors"][cid] = c
    audit(a, "AX_CONNECTOR_CREATE", pid, cid, detail={"engine": engine, "purpose": purpose})
    _save()
    return c


def connector_test(a, pid, cid):
    p, _ = _proj(a, pid, ("architect", "developer"))
    c = S["connectors"].get(cid)
    if not c or c["project_id"] != pid:
        raise ApiError(404, "AX_CONNECTOR_NOT_FOUND", "연결을 찾을 수 없습니다.")
    st = []

    def add(name, status, detail):
        st.append({"stage": name, "status": status, "detail": detail})
        return status == "PASS"
    if c["engine"] == "sqlite_fixture":
        add("DNS", "SKIPPED", "내장 fixture(네트워크 없음)")
        add("TCP", "SKIPPED", "내장 fixture(네트워크 없음)")
        add("TLS", "SKIPPED", "내장 fixture(네트워크 없음)")
        add("AUTH", "SKIPPED", "인증 없음(로컬 파일)")
        try:
            cn = _src(pid)
            v = cn.execute("select sqlite_version()").fetchone()[0]
            add("DB_IDENT", "PASS", f"SQLite {v} · 합성 fixture")
            n = cn.execute("select count(*) from sqlite_master where type in ('table','view')").fetchone()[0]
            add("METADATA_VISIBILITY", "PASS", f"객체 {n}개 가시(허용 범위는 별도 scope로 한정)")
            add("BOUNDED_QUERY", "PASS", "SELECT 1 (행 제한·읽기 전용)") if cn.execute("select 1").fetchone()[0] == 1 else None
            cn.close()
        except Exception as e:
            add("DB_IDENT", "FAIL", str(e)[:120])
    else:
        host, port = c.get("host") or "", int(c.get("port") or 0)
        if not host or not port or host.lower() in _BLOCK_HOSTS or _ip_blocked_host(host):
            add("DNS", "FAIL", "host/port 가 비었거나 허용되지 않는 대상(metadata·link-local)")
        else:
            try:
                ips = sorted({r[4][0] for r in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)})
                if any(_ip_blocked(i) for i in ips):
                    add("DNS", "FAIL", "해석된 주소 중 허용되지 않는 대상이 있음(재확인)")
                else:
                    add("DNS", "PASS", f"{len(ips)}개 주소")
                    try:
                        sk = socket.create_connection((ips[0], port), timeout=c["timeout_s"])
                        add("TCP", "PASS", f"{ips[0]}:{port}")
                        if c["tls"]:
                            try:
                                ctx = ssl.create_default_context()
                                with ctx.wrap_socket(sk, server_hostname=host) as ss:
                                    add("TLS", "PASS", ss.version() or "")
                            except Exception as e:
                                add("TLS", "FAIL", f"{type(e).__name__}: 인증서·프로토콜 확인")
                        else:
                            sk.close()
                            add("TLS", "SKIPPED", "tls=false(개발망 예외로 기록됨)")
                    except Exception as e:
                        add("TCP", "FAIL", f"{type(e).__name__}")
            except Exception as e:
                add("DNS", "FAIL", f"{type(e).__name__}")
        failed = any(x["status"] == "FAIL" for x in st)
        cn = None
        if failed:
            for nm in ("AUTH", "DB_IDENT", "METADATA_VISIBILITY", "BOUNDED_QUERY"):
                add(nm, "NOT_RUN", "앞 단계 실패로 실행하지 않음")
        else:
            try:
                cn = ax_db.open_conn(c)
                add("AUTH", "PASS", "인증·접속 성공(자격증명은 표시하지 않음)")
            except ApiError as e:
                add("AUTH", "FAIL", f"{e.code}: {e.message[:110]}")
            if cn:
                try:
                    v = cn.execute(ax_db.ident_sql(c["engine"])).fetchone()[0]
                    add("DB_IDENT", "PASS", str(v)[:120])
                    n = ax_db.visible_count(cn, c["engine"], c["schema_allowlist"])
                    add("METADATA_VISIBILITY", "PASS" if n else "FAIL", f"허용 schema에서 객체 {n}개 가시" if n else "허용 schema에서 보이는 객체가 0개(권한·이름 확인)")
                    one = cn.execute(ax_db.ping_sql(c["engine"])).fetchone()[0]
                    add("BOUNDED_QUERY", "PASS" if int(one) == 1 else "FAIL", "SELECT 1 (읽기 전용)")
                except Exception as e:
                    add("DB_IDENT", "FAIL", f"{type(e).__name__}")
                finally:
                    cn.close()
            else:
                for nm in ("DB_IDENT", "METADATA_VISIBILITY", "BOUNDED_QUERY"):
                    add(nm, "NOT_RUN", "인증 실패로 실행하지 않음")
    ok = all(x["status"] in ("PASS", "SKIPPED") for x in st)
    c["last_test"] = {"at": _now(), "stages": st, "all_pass": ok, "note": "연결 성공이 DB 전체 접근 권한을 뜻하지 않음"}
    audit(a, "AX_CONNECTOR_TEST", pid, cid, "ok" if ok else "partial")
    _save()
    return c["last_test"]


def _ip_blocked_host(h):
    try:
        ipaddress.ip_address(h)
    except ValueError:
        return False  # 호스트 이름은 DNS 해석 뒤 주소로 다시 검사
    return _ip_blocked(h)


# ------------------------------------------------------------------ 구조 수집(AX-03)
def _collect(cn, schema="main"):
    objs = []
    for r in cn.execute("select name, type, sql from sqlite_master where type in ('table','view') and name not like 'sqlite_%' order by name").fetchall():
        name, kind = r["name"], r["type"]
        cols = [{"name": x["name"], "type": x["type"] or "", "nullable": not x["notnull"], "default": x["dflt_value"], "pk_pos": x["pk"], "comment": None} for x in cn.execute(f'pragma table_info("{name}")').fetchall()]
        fks = {}
        for x in cn.execute(f'pragma foreign_key_list("{name}")').fetchall():
            fks.setdefault(x["id"], {"ref_table": x["table"], "cols": [], "ref_cols": [], "on_delete": x["on_delete"]})
            fks[x["id"]]["cols"].append((x["seq"], x["from"]))
            fks[x["id"]]["ref_cols"].append((x["seq"], x["to"]))
        fk_list = [{"name": f"fk_{name}_{i}", "columns": [c for _, c in sorted(v["cols"])], "ref_table": v["ref_table"], "ref_columns": [c for _, c in sorted(v["ref_cols"])],
                    "status": "ENABLED", "validated": True, "origin": "DECLARED"} for i, v in sorted(fks.items())]
        idx = [{"name": x["name"], "unique": bool(x["unique"]), "columns": [y["name"] for y in cn.execute(f'pragma index_info("{x["name"]}")').fetchall()]} for x in cn.execute(f'pragma index_list("{name}")').fetchall()]
        pk = [c["name"] for c in sorted([c for c in cols if c["pk_pos"]], key=lambda c: c["pk_pos"])]
        est = None
        if kind == "table":
            est = cn.execute(f'select count(*) from "{name}"').fetchone()[0]  # fixture 한정: 실제 DB에서는 통계 기반 추정치만 사용
        o = {"object_id": f"{schema}.{name}", "schema": schema, "name": name, "kind": kind, "columns": cols, "pk": pk, "fks": fk_list, "indexes": idx,
             "view_sql": r["sql"] if kind == "view" else None, "row_count": est, "row_count_basis": "exact(fixture)" if est is not None else None}
        o["fingerprint"] = hashlib.sha256(json.dumps({k: o[k] for k in ("columns", "pk", "fks", "indexes", "view_sql")}, sort_keys=True, default=str).encode()).hexdigest()[:16]
        objs.append(o)
    return objs


def scan(a, pid, b):
    p, _ = _proj(a, pid, ("architect", "developer"))
    cid = b.get("connector_id")
    c = S["connectors"].get(cid)
    if not c or c["project_id"] != pid:
        raise ApiError(404, "AX_CONNECTOR_NOT_FOUND", "연결을 찾을 수 없습니다.")
    if c["purpose"] != "metadata":
        raise ApiError(400, "WRONG_ACCOUNT_PURPOSE", "구조 수집은 metadata 용도 연결만 사용합니다(계정 분리).")
    prev = max((s for s in S["snapshots"].values() if s["project_id"] == pid), key=lambda s: s["created_at"], default=None)
    if c["engine"] == "sqlite_fixture":
        cn = _src(pid)
        try:
            objs = _collect(cn)
        finally:
            cn.close()
    else:
        cn = ax_db.open_conn(c)
        try:
            objs = ax_db.COLLECTORS[c["engine"]](cn, c["schema_allowlist"])
        finally:
            cn.close()
    baseline = b.get("dba_baseline_count")
    cov = {"collected_objects": len(objs), "dba_baseline_count": baseline,
           "completeness": "UNVERIFIED" if baseline is None else ("COMPLETE" if baseline == len(objs) else "INCOMPLETE"),
           "warning": ("DBA 기준 목록이 없어 전체 포괄성은 미확인입니다." if baseline is None else (None if baseline == len(objs) else f"DBA 기준 {baseline}개보다 적게 수집({len(objs)}개) — 전체 완료로 보지 않음")),
           "visibility_failures": 0, "unsupported": 0}
    sid = _id("axs")
    snap = {"snapshot_id": sid, "project_id": pid, "connector_id": cid, "created_at": _now(), "observed_by": a["user_id"], "engine": c["engine"], "objects": {o["object_id"]: o for o in objs}, "coverage": cov,
            "note": "여러 DB 수집 시점의 원자성은 주장하지 않음(구조 수집 중 DDL 변경 시 재수집 대상)"}
    S["snapshots"][sid] = snap
    stale = []
    if prev:
        d = _diff(prev, snap)
        snap["diff_from"] = prev["snapshot_id"]
        changed = {x["object_id"] for x in d["changed"]} | {x["object_id"] for x in d["removed"]}
        for r in S["releases"].values():
            if r["project_id"] == pid and r["status"] in ("VALIDATED", "REVIEWED", "APPROVED", "ACTIVE") and changed & set(r.get("bound_objects", [])):
                r["status_before_stale"] = r["status"]
                r["status"] = "STALE"
                r["stale_reason"] = sorted(changed & set(r["bound_objects"]))
                stale.append(r["release_id"])
    audit(a, "AX_SCAN", pid, sid, detail={"objects": len(objs), "stale": stale})
    _save()
    return _snap_pub(snap, stale)


def _snap_pub(s, stale=()):
    return {"snapshot_id": s["snapshot_id"], "created_at": s["created_at"], "coverage": s["coverage"], "objects": len(s["objects"]), "tables": sum(1 for o in s["objects"].values() if o["kind"] == "table"),
            "views": sum(1 for o in s["objects"].values() if o["kind"] == "view"), "diff_from": s.get("diff_from"), "stale_releases": list(stale), "note": s["note"]}


def _snap(pid, sid=None):
    if sid:
        s = S["snapshots"].get(sid)
        if not s or s["project_id"] != pid:
            raise ApiError(404, "AX_SNAPSHOT_NOT_FOUND", "snapshot 을 찾을 수 없습니다.")
        return s
    s = max((s for s in S["snapshots"].values() if s["project_id"] == pid), key=lambda s: s["created_at"], default=None)
    if not s:
        raise ApiError(409, "NO_SNAPSHOT", "먼저 구조 수집(scan)을 실행하세요.")
    return s


def snapshots(a, pid):
    _proj(a, pid)
    return [_snap_pub(s) for s in sorted((s for s in S["snapshots"].values() if s["project_id"] == pid), key=lambda s: s["created_at"], reverse=True)]


def inventory(a, pid, sid=None, q=""):
    _proj(a, pid)
    s = _snap(pid, sid)
    q = (q or "").lower()
    rows = [{"object_id": o["object_id"], "kind": o["kind"], "columns": len(o["columns"]), "pk": o["pk"], "fks": len(o["fks"]), "rows_est": o["row_count"], "basis": o["row_count_basis"], "fingerprint": o["fingerprint"]}
            for o in s["objects"].values() if not q or q in o["object_id"].lower() or any(q in c["name"].lower() for c in o["columns"])]
    return {"snapshot": _snap_pub(s), "objects": rows}


def _diff(old, new):
    oo, nn = old["objects"], new["objects"]
    added = [k for k in nn if k not in oo]
    removed = [{"object_id": k} for k in oo if k not in nn]
    changed = []
    for k in nn:
        if k in oo and oo[k]["fingerprint"] != nn[k]["fingerprint"]:
            oc, nc = {c["name"]: c for c in oo[k]["columns"]}, {c["name"]: c for c in nn[k]["columns"]}
            ch = [f"컬럼 추가 {x}" for x in nc if x not in oc] + [f"컬럼 삭제 {x}" for x in oc if x not in nc] + [f"타입 변경 {x}: {oc[x]['type']}→{nc[x]['type']}" for x in nc if x in oc and oc[x]["type"] != nc[x]["type"]]
            if oo[k]["pk"] != nn[k]["pk"]:
                ch.append("PK 변경")
            if oo[k]["fks"] != nn[k]["fks"]:
                ch.append("FK 변경")
            changed.append({"object_id": k, "changes": ch or ["기타 구조 변경"]})
    # rename 후보: 삭제+추가에서 컬럼 구성이 같은 것(자동 확정하지 않음)
    ren = []
    for r in removed:
        for ad in added:
            if [c["name"] for c in oo[r["object_id"]]["columns"]] == [c["name"] for c in nn[ad]["columns"]]:
                ren.append({"from": r["object_id"], "to": ad, "status": "CANDIDATE_NOT_CONFIRMED"})
    return {"added": [{"object_id": k} for k in added], "removed": removed, "changed": changed, "rename_candidates": ren}


def diff(a, pid, old, new):
    _proj(a, pid)
    return _diff(_snap(pid, old), _snap(pid, new))


# ------------------------------------------------------------------ 관계·ERD(AX-04/05)
def _decl_relations(s):
    out = []
    for o in s["objects"].values():
        for f in o["fks"]:
            out.append({"relation_id": f"decl:{o['name']}:{','.join(f['columns'])}>{f['ref_table']}", "from_table": o["object_id"], "from_columns": f["columns"], "to_table": f"{f.get('ref_schema') or o['schema']}.{f['ref_table']}",
                        "to_columns": f["ref_columns"], "kind": "DECLARED_FK", "status": "DECLARED", "validated": f["validated"],
                        "cardinality": "N:1", "identifying": all(c in o["pk"] for c in f["columns"]), "self": f["ref_table"] == o["name"], "composite": len(f["columns"]) > 1})
    return out


def relation_infer(a, pid, b):
    _proj(a, pid, ("architect", "developer", "domain_expert"))
    s = _snap(pid, b.get("snapshot_id"))
    p = S["projects"][pid]
    lim = min(int(b.get("sample_rows", p["budget"]["profile_row_limit"])), 5000)
    low = lambda x: str(x).lower()
    key = lambda f, fc, t: (low(f), tuple(low(x) for x in fc), low(t))
    declared = {key(r["from_table"], r["from_columns"], r["to_table"]) for r in _decl_relations(s)}
    rejected = {key(x["from_table"], x["from_columns"], x["to_table"]) for x in S["relations"].values() if x["project_id"] == pid and x["status"] == "REJECTED"}
    existing = {key(x["from_table"], x["from_columns"], x["to_table"]) for x in S["relations"].values() if x["project_id"] == pid}
    pk_cols = {}
    for o in s["objects"].values():
        if o["kind"] == "table":
            for c in o["pk"]:
                pk_cols.setdefault(low(c), []).append(o)
    cn = _src(pid, purpose="profiling")
    made = []
    try:
        for child in s["objects"].values():
            if child["kind"] != "table":
                continue
            ccn = {low(c["name"]): c["name"] for c in child["columns"]}
            for col in child["columns"]:
                if low(col["name"]) in ("tenant_id", "name", "note"):
                    continue
                for par in pk_cols.get(low(col["name"]), []):
                    if par["object_id"] == child["object_id"] or not par["pk"]:
                        continue
                    pkl = [low(x) for x in par["pk"]]
                    use_tenant = "tenant_id" in pkl and "tenant_id" in ccn
                    pmap = {low(x): x for x in par["pk"]}
                    ccols = ([ccn["tenant_id"]] if use_tenant else []) + [col["name"]]
                    pcols = ([pmap["tenant_id"]] if use_tenant else []) + [pmap[low(col["name"])]]
                    k = key(child["object_id"], ccols, par["object_id"])
                    if k in declared or k in rejected or k in existing:
                        continue
                    cl = ",".join(cn.q(x) for x in ccols)
                    on = " AND ".join(f"p.{cn.q(y)}=c.{cn.q(x)}" for x, y in zip(ccols, pcols))
                    row = cn.execute(f"SELECT COUNT(*) AS n, SUM(CASE WHEN EXISTS(SELECT 1 FROM {cn.qual(par['schema'], par['name'])} p WHERE {on}) THEN 1 ELSE 0 END) AS m FROM ({cn.sample(cl, child['schema'], child['name'], lim)}) c").fetchone()
                    n, m = int(_py(row["n"]) or 0), int(_py(row["m"]) or 0)
                    incl = (m / n) if n else 0.0
                    rid = _id("axr")
                    S["relations"][rid] = {"relation_id": rid, "project_id": pid, "snapshot_id": s["snapshot_id"], "from_table": child["object_id"], "from_columns": ccols, "to_table": par["object_id"], "to_columns": pcols,
                                          "kind": "INFERRED", "status": "CANDIDATE", "evidence": {"name_match": col["name"], "sample_rows": n, "inclusion_rate": round(incl, 3), "orphan_rate": round(1 - incl, 3), "basis": "sample", "limit": lim},
                                          "heuristic_score": round(0.4 + 0.6 * incl, 3), "score_note": "초기 heuristic 점수이며 검증된 확률이 아님. 승인 전 JOIN·도구 사용 금지", "reviews": [], "revision": 1}
                    existing.add(k)
                    made.append(S["relations"][rid])
    finally:
        cn.close()
    audit(a, "AX_RELATION_INFER", pid, detail={"candidates": len(made)})
    _save()
    return {"candidates": made, "note": "이름이 같거나 JOIN 이 된다는 이유만으로 승인하지 않습니다."}


def relations(a, pid, sid=None):
    _proj(a, pid)
    s = _snap(pid, sid)
    return {"declared": _decl_relations(s), "logical": [r for r in S["relations"].values() if r["project_id"] == pid]}


def relation_review(a, pid, b):
    p, m = _proj(a, pid, ("domain_expert", "reviewer", "architect"))
    r = S["relations"].get(b.get("relation_id"))
    if not r or r["project_id"] != pid:
        raise ApiError(404, "AX_RELATION_NOT_FOUND", "관계 후보를 찾을 수 없습니다.")
    dec = b.get("decision")
    if dec not in ("approve", "reject"):
        raise ApiError(400, "BAD_DECISION", "approve | reject")
    note = (b.get("note") or "").strip()
    if len(note) < 4:
        raise ApiError(400, "NOTE_REQUIRED", "결정 사유(4자 이상)가 필요합니다.")
    _check_rev(r, b.get("expected_revision"))
    if dec == "approve" and m["role"] not in APPROVER_ROLES and a["role"] != "admin":
        raise ApiError(403, "APPROVER_ROLE_REQUIRED", "관계 승인은 domain_expert/reviewer 역할이 필요합니다.")
    r["status"] = "APPROVED_LOGICAL" if dec == "approve" else "REJECTED"
    r["kind"] = "APPROVED_LOGICAL" if dec == "approve" else r["kind"]
    r["reviews"].append({"by": a["user_id"], "decision": dec, "note": note, "at": _now()})
    r["revision"] += 1
    audit(a, "AX_RELATION_REVIEW", pid, r["relation_id"], detail={"decision": dec})
    _save()
    return r


def erd(a, pid, sid=None, focus="", hops=1, q="", collapse=False):
    _proj(a, pid)
    s = _snap(pid, sid)
    rels = _decl_relations(s) + [dict(x, relation_id=x["relation_id"]) for x in S["relations"].values() if x["project_id"] == pid and x["status"] in ("CANDIDATE", "APPROVED_LOGICAL")]
    names = list(s["objects"])
    tables_n = len(names)
    hops = max(0, min(int(hops), 3))
    if not focus and not q and tables_n > 40:  # 대형 모델: 업무영역(접두어) 군집으로 축약
        cl = {}
        for n in names:
            cl.setdefault(n.split(".", 1)[1].split("_")[0], []).append(n)
        return {"mode": "OVERVIEW_CLUSTERS", "total_tables": tables_n, "clusters": [{"cluster": k, "tables": len(v)} for k, v in sorted(cl.items())], "note": "상세는 focus/hops 로 부분모델을 불러오세요."}
    if q:
        sel = {n for n in names if q.lower() in n.lower() or any(q.lower() in c["name"].lower() for c in s["objects"][n]["columns"])}
    elif focus:
        fl = focus.lower()
        fid = next((n for n in names if n.lower() == fl or n.lower().endswith("." + fl)), None)
        if not fid:
            raise ApiError(404, "AX_OBJECT_NOT_FOUND", "객체를 찾을 수 없습니다.")
        sel, fr = {fid}, {fid}
        for _ in range(hops):
            nx = set()
            for r in rels:
                if r["from_table"] in fr:
                    nx.add(r["to_table"])
                if r["to_table"] in fr:
                    nx.add(r["from_table"])
            sel |= nx
            fr = nx
    else:
        sel = set(names)
    nodes = []
    for n in sorted(sel):
        o = s["objects"][n]
        fkc = {c for f in o["fks"] for c in f["columns"]}
        nodes.append({"id": n, "kind": o["kind"], "rows_est": o["row_count"], "columns": ([] if collapse else [{"name": c["name"], "type": c["type"], "pk": c["name"] in o["pk"], "fk": c["name"] in fkc, "nullable": c["nullable"]} for c in o["columns"]]), "column_count": len(o["columns"])})
    edges = [{"id": r["relation_id"], "from": r["from_table"], "to": r["to_table"], "from_columns": r["from_columns"], "to_columns": r["to_columns"], "kind": r["kind"], "status": r["status"], "style": {"DECLARED_FK": "solid", "APPROVED_LOGICAL": "solid-logical", "INFERRED": "dashed"}.get(r["kind"], "solid"),
              "cardinality": r.get("cardinality", "N:1"), "composite": len(r["from_columns"]) > 1, "self": r["from_table"] == r["to_table"], "usable": r["status"] in ("DECLARED", "APPROVED_LOGICAL")}
             for r in rels if r["from_table"] in sel and r["to_table"] in sel]
    return {"mode": "SUBGRAPH", "total_tables": tables_n, "nodes": nodes, "edges": edges, "notation": "IE/Crow's Foot(N:1), 실선=선언 FK, 이중표시=승인 논리, 점선=후보(검토 전 사용 금지)"}


def profile(a, pid, b):
    p, _ = _proj(a, pid, ("architect", "developer"))
    s = _snap(pid, b.get("snapshot_id"))
    oid = b.get("object_id", "")
    o = s["objects"].get(oid)
    if not o or o["kind"] != "table":
        raise ApiError(404, "AX_OBJECT_NOT_FOUND", "table 객체를 찾을 수 없습니다.")
    full = bool(b.get("full_scan"))
    if full and not (p["budget"].get("full_scan_allowed") and b.get("budget_approval")):
        raise ApiError(403, "FULL_SCAN_NOT_APPROVED", "full scan 은 별도 작업·예산 승인이 필요합니다(프로젝트 budget.full_scan_allowed + budget_approval).")
    lim = min(int(b.get("sample_rows", p["budget"]["profile_row_limit"])), 5000)
    cn = _src(pid, purpose="profiling")
    cols = []
    try:
        tq = cn.qual(o["schema"], o["name"])
        src = f"(SELECT * FROM {tq}) x" if full else f"({cn.sample('*', o['schema'], o['name'], lim)}) x"
        for c in o["columns"]:
            qc = cn.q(c["name"])
            r = cn.execute(f"SELECT COUNT(*) AS n, SUM(CASE WHEN {qc} IS NULL THEN 1 ELSE 0 END) AS nul, COUNT(DISTINCT {qc}) AS d, MIN({qc}) AS mn, MAX({qc}) AS mx FROM {src}").fetchone()
            n = int(_py(r["n"]) or 0)
            sens = bool(re.search(r"biz_no|name|note", c["name"], re.I))  # 민감 후보는 값 대신 집계만
            d = int(_py(r["d"]))
            cols.append({"column": c["name"], "rows": n, "null_ratio": round(int(_py(r["nul"]) or 0) / n, 4) if n else None, "distinct": d, "sampled_uniqueness": round(d / n, 4) if n else None,
                         "min": None if sens else _py(r["mn"]), "max": None if sens else _py(r["mx"]), "masked": sens})
    finally:
        cn.close()
    pr = {"profile_id": _id("axf"), "project_id": pid, "object_id": oid, "snapshot_id": s["snapshot_id"], "basis": "exact" if full else "sample", "sample_limit": None if full else lim, "columns": cols, "at": _now(),
          "limits": "표본 기반 값입니다. distinct·uniqueness 는 표본 범위에서만 유효합니다."}
    S["profiles"][pr["profile_id"]] = pr
    audit(a, "AX_PROFILE", pid, oid, detail={"basis": pr["basis"]})
    _save()
    return pr


def issue_add(a, pid, b):
    _proj(a, pid)
    iid = _id("axi")
    S["issues"][iid] = {"issue_id": iid, "project_id": pid, "target": b.get("target", ""), "title": (b.get("title") or "")[:200], "severity": b.get("severity", "mid"), "assignee": b.get("assignee"), "status": "OPEN", "by": a["user_id"], "at": _now()}
    audit(a, "AX_ISSUE_ADD", pid, iid)
    _save()
    return S["issues"][iid]


# ------------------------------------------------------------------ 온톨로지(AX-06)
def _approved_rel(pid, s, from_t, from_c, to_t):
    lw = lambda xs: {str(x).lower() for x in xs}
    for r in _decl_relations(s):
        if r["from_table"].lower() == from_t.lower() and r["to_table"].lower() == to_t.lower() and lw(r["from_columns"]) == lw(from_c):
            return True
    return any(x["project_id"] == pid and x["status"] == "APPROVED_LOGICAL" and x["from_table"].lower() == from_t.lower() and x["to_table"].lower() == to_t.lower() and lw(x["from_columns"]) == lw(from_c) for x in S["relations"].values())


def _find(s, t):
    return next((o for o in s["objects"].values() if o["name"].lower() == t.lower()), None)


def _template(s):
    def ent(i, t, k):
        o = _find(s, t)
        cn = {c["name"].lower(): c["name"] for c in o["columns"]} if o else {}
        return {"id": i, "source_binding": o["object_id"] if o else f"main.{t}", "key": [cn.get(x, x) for x in k]}

    def jk(ent_id, keys, ents):
        o = _find(s, next(e for e in ents if e["id"] == ent_id)["source_binding"].split(".", 1)[1])
        cn = {c["name"].lower(): c["name"] for c in o["columns"]} if o else {}
        return [cn.get(x, x) for x in keys]
    ents = [ent("Party", "party", ["tenant_id", "party_id"]), ent("CustomerRole", "customer_role", ["tenant_id", "customer_id"]), ent("SupplierRole", "supplier_role", ["tenant_id", "supplier_id"]),
            ent("Product", "product", ["tenant_id", "product_id"]), ent("Stock", "stock", ["tenant_id", "product_id"]), ent("SalesOrder", "sales_orders", ["tenant_id", "order_id"]), ent("Contract", "contract", ["tenant_id", "contract_id"]),
            ent("SupplierItem", "supplier_item", ["tenant_id", "supplier_id", "product_id", "valid_from"]), ent("PurchaseOrder", "purchase_orders", ["tenant_id", "po_id"]), ent("ArLedger", "ar_ledger", ["tenant_id", "entry_id"])]
    rels = [("role_party", "CustomerRole", "Party", ["tenant_id", "party_id"]), ("order_customer", "SalesOrder", "CustomerRole", ["tenant_id", "customer_id"]), ("order_product", "SalesOrder", "Product", ["tenant_id", "product_id"]),
            ("quote_supplier", "SupplierItem", "SupplierRole", ["tenant_id", "supplier_id"]), ("po_supplier", "PurchaseOrder", "SupplierRole", ["tenant_id", "supplier_id"]), ("ledger_customer", "ArLedger", "CustomerRole", ["tenant_id", "customer_id"])]
    return {"model_id": "distribution_ax", "entities": ents,
            "relations": [{"id": i, "from": f, "to": t, "join_keys": jk(f, k, ents)} for i, f, t, k in rels],
            "metrics": [{"id": "additional_available_qty", "grain": ["tenant_id", "product_id"], "expression_ref": "additional_available_qty", "unit": "box", "includes_signed_returns": False}],
            "policies": [{"id": "change_order_increase", "implementation_ref": "change_order_increase", "required_tests": ["stock", "credit", "approval", "version_conflict", "tenant_scope"]},
                         {"id": "delay_alternatives", "implementation_ref": "delay_alternatives", "required_tests": ["stock", "inbound"]},
                         {"id": "price_diff_reason", "implementation_ref": "price_diff_reason", "required_tests": ["contract_validity"]},
                         {"id": "receivable_summary", "implementation_ref": "receivable_summary", "required_tests": ["tenant_scope", "customer_scope"]},
                         {"id": "purchase_reorder", "implementation_ref": "purchase_reorder", "weights": {"total_cost": 0.5, "lead_days": 0.3, "quality": 0.2}, "weights_approved_by": "release review", "required_tests": ["moq", "pack", "inbound"]},
                         {"id": "supplier_switch", "implementation_ref": "supplier_switch", "min_quality_grade": "B", "required_tests": ["quality", "internal_only"]},
                         {"id": "price_spike", "implementation_ref": "price_spike", "threshold_pct": 10, "required_tests": ["quote_validity", "internal_only"]},
                         {"id": "receipt_variance", "implementation_ref": "receipt_variance", "required_tests": ["tolerance", "supplier_scope"]}],
            "competency_questions": ["주문 SO-1001을 20에서 35박스로 증량할 수 있는가?", "추가 가용 재고는 몇 박스인가?", "다른 tenant의 같은 주문번호가 섞이지 않는가?", "부족 품목은 어느 공급처에 얼마를 발주하는 것이 좋은가?", "이 거래처의 미수금은 얼마인가?"]}


def release_create(a, pid, b):
    p, _ = _proj(a, pid, ("architect", "developer", "domain_expert"))
    s = _snap(pid, b.get("snapshot_id"))
    spec = _template(s) if b.get("template") == "distribution_ax" else b.get("spec")
    if not isinstance(spec, dict):
        raise ApiError(400, "BAD_SPEC", "template=distribution_ax 또는 spec(JSON)이 필요합니다.")
    ver = b.get("version") or "1.0.0"
    rid = _id("axo")
    bound = sorted({e.get("source_binding") for e in spec.get("entities", []) if e.get("source_binding")})
    r = {"release_id": rid, "project_id": pid, "model_id": spec.get("model_id", "model"), "version": ver, "spec": spec, "snapshot_id": s["snapshot_id"], "bound_objects": bound, "status": "DRAFT", "author": a["user_id"],
         "created_at": _now(), "validation": None, "reviews": [], "revision": 1, "drivers": ax_db.driver_status(), "embedding": ax_search.embed_mode(), "tools": sorted(ax_tools.CONTRACTS), "standards_note": "SKOS/PROV/SHACL 은 참고 방법론입니다. 내부 shape 검증은 SHACL 준수가 아닙니다."}
    S["releases"][rid] = r
    audit(a, "AX_ONTOLOGY_CREATE", pid, rid)
    _save()
    return r


def release_validate(a, pid, rid):
    _proj(a, pid, ("architect", "developer", "domain_expert", "reviewer"))
    r = _rel(pid, rid)
    s = S["snapshots"][r["snapshot_id"]]
    cur = _snap(pid)
    errs, warns = [], []
    ents = {e["id"]: e for e in r["spec"].get("entities", [])}
    for e in ents.values():
        o = s["objects"].get(e.get("source_binding"))
        if not o:
            errs.append({"code": "BINDING_MISSING", "target": e["id"], "fix": f"source_binding {e.get('source_binding')} 객체가 snapshot 에 없습니다."})
            continue
        lw = lambda xs: sorted(str(x).lower() for x in xs)
        miss = [k for k in e.get("key", []) if k.lower() not in {c["name"].lower() for c in o["columns"]}]
        if miss:
            errs.append({"code": "KEY_COLUMN_MISSING", "target": e["id"], "fix": f"키 컬럼 {miss} 없음"})
        elif lw(e["key"]) != lw(o["pk"]) and not any(i["unique"] and lw(i["columns"]) == lw(e["key"]) for i in o["indexes"]):
            warns.append({"code": "KEY_NOT_DECLARED_UNIQUE", "target": e["id"], "fix": "선언된 PK/UK 와 다름 — 현업·DBA 확인 필요"})
    for rel in r["spec"].get("relations", []):
        if rel.get("from") not in ents or rel.get("to") not in ents:
            errs.append({"code": "RELATION_ENDPOINT_UNKNOWN", "target": rel.get("id"), "fix": "from/to 엔터티가 정의되지 않았습니다."})
            continue
        if not _approved_rel(pid, s, ents[rel["from"]]["source_binding"], rel.get("join_keys", []), ents[rel["to"]]["source_binding"]):
            errs.append({"code": "RELATION_NOT_APPROVED", "target": rel.get("id"), "fix": "선언 FK 또는 승인된 논리 관계가 없습니다(추론 후보는 사용 불가)."})
    for m in r["spec"].get("metrics", []):
        if m.get("expression_ref") not in METRIC_REGISTRY:
            errs.append({"code": "EXPRESSION_NOT_IN_REGISTRY", "target": m.get("id"), "fix": "승인 registry 의 표현식만 참조합니다(임의 SQL/eval 금지)."})
    for po in r["spec"].get("policies", []):
        if po.get("implementation_ref") not in POLICY_REGISTRY:
            errs.append({"code": "POLICY_NOT_IN_REGISTRY", "target": po.get("id"), "fix": "승인 registry 의 정책 구현만 참조합니다."})
        if po.get("implementation_ref") == "purchase_reorder":
            try:
                ax_tools._weights(po)
            except ApiError:
                errs.append({"code": "POLICY_WEIGHTS_INVALID", "target": po.get("id"), "fix": "가중치는 total_cost·lead_days·quality 세 항목이며 합이 1.0이어야 합니다(현업 승인 값)."})
    if "CustomerRole" in ents and "SupplierRole" in ents and "Party" not in ents:
        errs.append({"code": "PARTY_ROLE_SEPARATION", "target": "Party", "fix": "Party 와 Customer/SupplierRole 을 분리하세요(겸업 업체 병합 방지)."})
    if r["snapshot_id"] != cur["snapshot_id"]:
        ch = {x["object_id"] for x in _diff(s, cur)["changed"]} | {x["object_id"] for x in _diff(s, cur)["removed"]}
        if ch & set(r["bound_objects"]):
            errs.append({"code": "SOURCE_CHANGED", "target": ",".join(sorted(ch & set(r["bound_objects"]))), "fix": "원천 구조가 바뀌었습니다. 새 snapshot 으로 release 를 다시 만드세요."})
    ok = not errs
    r["validation"] = {"at": _now(), "ok": ok, "errors": errs, "warnings": warns, "validator": "INTERNAL_SHAPE_CHECK(SHACL 아님)"}
    if ok and r["status"] in ("DRAFT", "STALE"):
        r["status"] = "VALIDATED"
    if not ok and r["status"] in ("VALIDATED", "REVIEWED", "APPROVED"):
        r["status"] = "DRAFT"
    r["revision"] += 1
    audit(a, "AX_ONTOLOGY_VALIDATE", pid, rid, "ok" if ok else "failed", {"errors": len(errs)})
    _save()
    return r["validation"]


def _rel(pid, rid):
    r = S["releases"].get(rid)
    if not r or r["project_id"] != pid:
        raise ApiError(404, "AX_RELEASE_NOT_FOUND", "온톨로지 release 를 찾을 수 없습니다.")
    return r


def release_review(a, pid, rid, b):
    p, m = _proj(a, pid, APPROVER_ROLES)
    r = _rel(pid, rid)
    _check_rev(r, b.get("expected_revision"))
    if r["author"] == a["user_id"]:
        raise ApiError(403, "SELF_REVIEW_FORBIDDEN", "작성자는 자신의 release 를 승인할 수 없습니다.")
    dec = b.get("decision")
    if dec not in ("approve", "reject"):
        raise ApiError(400, "BAD_DECISION", "approve | reject")
    note = (b.get("note") or "").strip()
    if len(note) < 4:
        raise ApiError(400, "NOTE_REQUIRED", "결정 사유(4자 이상)가 필요합니다.")
    if dec == "approve":
        if r["status"] != "VALIDATED" or not (r["validation"] or {}).get("ok"):
            raise ApiError(409, "NOT_VALIDATED", "검증을 통과(VALIDATED)한 release 만 승인할 수 있습니다.")
        r["status"] = "APPROVED"
    else:
        r["status"] = "DRAFT"
    r["reviews"].append({"by": a["user_id"], "decision": dec, "note": note, "at": _now()})
    r["revision"] += 1
    audit(a, "AX_ONTOLOGY_REVIEW", pid, rid, detail={"decision": dec})
    _save()
    return r


def release_list(a, pid):
    _proj(a, pid)
    return [{k: v for k, v in r.items() if k != "spec"} | {"entities": len(r["spec"].get("entities", [])), "relations": len(r["spec"].get("relations", []))} for r in S["releases"].values() if r["project_id"] == pid]


def release_get(a, pid, rid):
    _proj(a, pid)
    return _rel(pid, rid)


# ------------------------------------------------------------------ 컴파일·파이프라인(AX-08)
def compile_plan(a, pid, b):
    p, _ = _proj(a, pid, ("architect", "developer"))
    r = _rel(pid, b.get("release_id"))
    engine = b.get("engine") or p["engine"]
    if engine not in ENGINES:
        raise ApiError(400, "BAD_ENGINE", "native | databricks")
    if r["status"] not in ("APPROVED", "ACTIVE"):
        raise ApiError(409, "RELEASE_NOT_APPROVED", "승인된 release 만 컴파일합니다.")
    stages = [{"id": "normalize", "kind": "Normalize", "executor_ref": "transforms/order_stock_v1"}, {"id": "project", "kind": "MapRelation", "depends_on": ["normalize"], "mapping_ref": "relations/order_customer_v1"},
              {"id": "validate", "kind": "ValidateBusinessRule", "depends_on": ["project"], "tests_ref": "golden/domain_core_v1", "on_failure": "block_publish"},
              {"id": "publish", "kind": "Publish", "depends_on": ["validate"], "requires_review": True}]
    diag, artifacts = [], {}
    if engine == "databricks":
        diag.append({"level": "ERROR", "stage": "ProjectGraph", "code": "UNSUPPORTED", "msg": "graph projection 은 DBX 경로에서 지원하지 않음 — 가상 성공으로 대체하지 않음"})
        art = ["-- Databricks SQL 산출물(컴파일만 수행, 배포·실행 안 함). <catalog>.<schema> 는 배포 시 지정",
               "CREATE OR REPLACE VIEW <catalog>.<schema>.v_additional_available AS",
               "SELECT s.tenant_id, s.product_id, s.on_hand - COALESCE(SUM(o.requested_qty),0) AS additional_available_qty",
               "FROM <catalog>.<schema>.stock s LEFT JOIN <catalog>.<schema>.sales_orders o",
               "  ON o.tenant_id=s.tenant_id AND o.product_id=s.product_id AND o.status IN ('CONFIRMED','ALLOCATED')",
               "GROUP BY s.tenant_id, s.product_id, s.on_hand;"]
        artifacts["databricks_sql"] = "\n".join(art)
    plan = {"plan_id": _id("axl"), "project_id": pid, "release_id": r["release_id"], "ontology_release": f"{r['model_id']}@{r['version']}", "engine": engine, "stages": stages, "diagnostics": diag, "artifacts": artifacts,
            "evidence_level": "SPEC_ONLY" if engine == "databricks" else EVIDENCE, "status": "COMPILE_FAILED" if any(d["level"] == "ERROR" for d in diag) else "COMPILED", "at": _now(),
            "note": "WIZBASE 내부 API 이며 DBX 공식 API 가 아닙니다."}
    S["runs"][plan["plan_id"]] = plan
    audit(a, "AX_COMPILE", pid, plan["plan_id"], plan["status"])
    _save()
    return plan


def pipeline_run(a, pid, b):
    p, _ = _proj(a, pid, ("architect", "developer"))
    plan = S["runs"].get(b.get("plan_id"))
    if not plan or plan["project_id"] != pid or "stages" not in plan:
        raise ApiError(404, "AX_PLAN_NOT_FOUND", "plan 을 찾을 수 없습니다.")
    if plan["engine"] != "native":
        raise ApiError(412, "ENGINE_NOT_EXECUTABLE", "DBX 경로 실제 실행은 이 빌드에서 수행하지 않았습니다(컴파일 산출물만 제공). Workspace 연결·배포 증거 후 지원합니다.")
    if plan["status"] != "COMPILED":
        raise ApiError(409, "PLAN_NOT_COMPILED", "컴파일에 실패한 plan 은 실행하지 않습니다.")
    rel = _rel(pid, plan["release_id"])
    if rel["status"] not in ("APPROVED", "ACTIVE"):
        raise ApiError(409, "RELEASE_NOT_APPROVED", "release 가 더 이상 승인 상태가 아닙니다(STALE 등).")
    run = {"run_id": _id("axu"), "project_id": pid, "plan_id": plan["plan_id"], "engine": "native", "state": "RUNNING", "stages": [], "started_at": _now(), "evidence_level": EVIDENCE}
    (BASE / pid).mkdir(parents=True, exist_ok=True)
    work = BASE / pid / "native.sqlite"
    src = _src(pid)
    dst = sqlite3.connect(work)
    t0 = time.time()
    try:
        # Normalize: 승인 binding 의 canonical 복사(명시 컬럼, tenant 포함 키)
        dst.executescript("DROP TABLE IF EXISTS canonical_orders; DROP TABLE IF EXISTS canonical_stock; DROP TABLE IF EXISTS entity_projection; DROP TABLE IF EXISTS relation_projection;"
                          "CREATE TABLE canonical_orders(tenant_id, order_id, customer_id, product_id, requested_qty, status, source_row_version);"
                          "CREATE TABLE canonical_stock(tenant_id, product_id, on_hand, source_row_version);"
                          "CREATE TABLE entity_projection(entity_id, tenant_id, entity_key, src_table);"
                          "CREATE TABLE relation_projection(relation_id, tenant_id, from_key, to_key);")
        core = {"SalesOrder", "Stock"} <= {e["id"] for e in rel["spec"]["entities"]}
        if core:
            o = src.execute("select tenant_id, order_id, customer_id, product_id, requested_qty, status, row_version from sales_orders").fetchall()
            dst.executemany("insert into canonical_orders values(?,?,?,?,?,?,?)", [tuple(_py(v) for v in x) for x in o])
            st = src.execute("select tenant_id, product_id, on_hand, row_version from stock").fetchall()
            dst.executemany("insert into canonical_stock values(?,?,?,?)", [tuple(_py(v) for v in x) for x in st])
            run["stages"].append({"id": "normalize", "state": "SUCCEEDED", "rows": {"canonical_orders": len(o), "canonical_stock": len(st)}, "query_ids": [_qid("select sales_orders"), _qid("select stock")]})
        else:
            run["stages"].append({"id": "normalize", "state": "SUCCEEDED", "rows": {}, "note": "주문·재고 표준화 대상 엔터티가 없어 건너뜀(일반 모델)"})
        n_e = 0
        for e in rel["spec"]["entities"]:
            sch, tb = e["source_binding"].split(".", 1)
            ks = ", ".join(src.q(k) for k in e["key"])
            rows = src.execute(f"select {ks} from {src.qual(sch, tb)}").fetchall()
            dst.executemany("insert into entity_projection values(?,?,?,?)", [(e["id"], (str(r["tenant_id"]) if "tenant_id" in r.keys() else None), "|".join(str(x) for x in tuple(r)), tb) for r in rows])
            n_e += len(rows)
        n_r = 0
        for rl in rel["spec"].get("relations", []):
            fe = next(e for e in rel["spec"]["entities"] if e["id"] == rl["from"])
            te = next(e for e in rel["spec"]["entities"] if e["id"] == rl["to"])
            (fs, ft), (ts, tt) = fe["source_binding"].split(".", 1), te["source_binding"].split(".", 1)
            jk = rl["join_keys"]
            on = " AND ".join(f"t.{src.q(k)}=f.{src.q(k)}" for k in jk)
            fk_sel = ", ".join(f"f.{src.q(k)}" for k in fe["key"])
            tk_sel = ", ".join(f"t.{src.q(k)}" for k in te["key"])
            kn = len(fe["key"])
            tcol = next((k for k in fe["key"] if k.lower() == "tenant_id"), fe["key"][0])
            rows = src.execute(f"select f.{src.q(tcol)} AS tn, {fk_sel}, {tk_sel} from {src.qual(fs, ft)} f join {src.qual(ts, tt)} t on {on}").fetchall()
            dst.executemany("insert into relation_projection values(?,?,?,?)", [(rl["id"], str(r1[0]), "|".join(str(x) for x in tuple(r1)[1:1 + kn]), "|".join(str(x) for x in tuple(r1)[1 + kn:])) for r1 in rows])
            n_r += len(rows)
        run["stages"].append({"id": "project", "state": "SUCCEEDED", "rows": {"entity_projection": n_e, "relation_projection": n_r}})
        dst.commit()
        g = _gate(a, pid, rel)
        run["stages"].append({"id": "validate", "state": "SUCCEEDED" if g["gates_passed"] else "FAILED", "detail": {"passed": g["passed"], "total": g["total"]}})
        if not g["gates_passed"]:
            run["state"] = "FAILED"
            run["stages"].append({"id": "publish", "state": "SKIPPED", "reason": "품질 gate 실패 → block_publish"})
        else:
            run["stages"].append({"id": "publish", "state": "AWAITING_REVIEW", "reason": "requires_review: 배포(deployment)는 별도 승인 후"})
            run["state"] = "SUCCEEDED"
    except Exception as e:
        run["state"] = "FAILED"
        run["error"] = f"{type(e).__name__}: {e}"[:300]
    finally:
        src.close()
        dst.close()
    run["finished_at"] = _now()
    run["elapsed_ms"] = int((time.time() - t0) * 1000)
    S["runs"][run["run_id"]] = run
    audit(a, "AX_PIPELINE_RUN", pid, run["run_id"], run["state"])
    _save()
    return run


def _gate(a, pid, rel):
    if _policy(rel, "change_order_increase"):
        return evaluate_core(pid, persist=False, rel=rel)
    from . import ax_auto
    return ax_auto.generic_eval(a, pid, rel, _proj(a, pid)[1])


def _qid(sql, params=()):
    return "q-" + hashlib.sha256((sql + repr(params)).encode()).hexdigest()[:12]


# ------------------------------------------------------------------ 에이전트·도구(AX-09)
def _scope_check(m, tenant, customer=None):
    if m.get("suppliers") is not None:
        raise ApiError(403, "SUPPLIER_CANNOT_USE_SALES", "공급처 계정은 매출처 도구를 사용할 수 없습니다.")
    if m.get("tenants") is not None and tenant not in m["tenants"]:
        raise ApiError(403, "TENANT_SCOPE_DENIED", "접근 범위(tenant) 밖입니다.")
    if m.get("customers") is not None and customer is not None and customer not in m["customers"]:
        raise ApiError(403, "CUSTOMER_SCOPE_DENIED", "접근 범위(거래처) 밖입니다.")


def _qty(v):
    if isinstance(v, bool) or not isinstance(v, (int, float, str)):
        raise ApiError(400, "BAD_QTY", "수량은 정수여야 합니다.")
    if isinstance(v, str) and not re.fullmatch(r"\d{1,6}", v.strip()):
        raise ApiError(400, "BAD_QTY", "수량은 정수여야 합니다.")
    if isinstance(v, float) and v != int(v):
        raise ApiError(400, "BAD_QTY", "수량은 정수여야 합니다.")
    q = int(v)
    if q < 0 or q > 1_000_000:
        raise ApiError(400, "BAD_QTY", "수량 범위를 벗어났습니다.")
    return q


def _ident(v, field):
    if not isinstance(v, str) or not re.fullmatch(r"[A-Za-z0-9_\-]{1,40}", v):
        raise ApiError(400, "BAD_PARAM", f"{field} 형식이 올바르지 않습니다.")
    return v


def _active_release(p, rid=None):
    r = S["releases"].get(rid or p.get("active_release") or "")
    if not r:
        cands = [x for x in S["releases"].values() if x["project_id"] == p["project_id"] and x["status"] in ("APPROVED", "ACTIVE")]
        r = cands[-1] if cands else None
    if not r or r["status"] not in ("APPROVED", "ACTIVE"):
        raise ApiError(409, "NO_APPROVED_RELEASE", "승인된 온톨로지 release 가 없어 도구를 실행하지 않습니다(승인되지 않은 개념은 실서비스 도구 대상 제외).")
    return r


def _increase_decision(cn, tenant, order_id, new_qty, today="2026-11-14"):
    o = cn.execute("select * from sales_orders where tenant_id=? and order_id=?", (tenant, order_id)).fetchone()
    if not o:
        return None
    stk = cn.execute("select on_hand,row_version from stock where tenant_id=? and product_id=?", (tenant, o["product_id"])).fetchone()
    res = cn.execute("select coalesce(sum(requested_qty),0) from sales_orders where tenant_id=? and product_id=? and status in ('CONFIRMED','ALLOCATED')", (tenant, o["product_id"])).fetchone()[0]
    res = int(_py(res))
    on_hand = int(_py(stk["on_hand"]))
    avail = on_hand - res
    cur = int(_py(o["requested_qty"]))
    extra = new_qty - cur
    cust = cn.execute("select credit_limit, credit_used from customer_role where tenant_id=? and customer_id=?", (tenant, o["customer_id"])).fetchone()
    ct = cn.execute("select unit_price from contract where tenant_id=? and customer_id=? and product_id=? and valid_from<=? and valid_to>=?", (tenant, o["customer_id"], o["product_id"], today, today)).fetchone()
    price = int(_py(ct["unit_price"])) if ct else None
    headroom = int(_py(cust["credit_limit"]) - _py(cust["credit_used"])) if cust else None
    credit_ok = None if price is None or headroom is None else (extra <= 0 or extra * price <= headroom)
    if extra <= 0:
        verdict, mx = "NO_INCREASE", cur
    elif credit_ok is None:
        verdict, mx = "UNCONFIRMED", None
    elif not credit_ok:
        verdict, mx = "IMPOSSIBLE", cur
    elif avail >= extra:
        verdict, mx = "POSSIBLE", new_qty
    elif avail > 0:
        verdict, mx = "CONDITIONAL", cur + avail
    else:
        verdict, mx = "IMPOSSIBLE", cur
    return {"order": {"tenant_id": tenant, "order_id": order_id, "customer_id": o["customer_id"], "product_id": o["product_id"], "current_qty": cur, "row_version": int(_py(o["row_version"])), "status": o["status"]},
            "request": {"new_qty": new_qty, "extra_needed": max(extra, 0)}, "stock": {"on_hand": on_hand, "reserved_total": res, "additional_available": max(avail, 0), "row_version": int(_py(stk["row_version"]))},
            "shortage": max(extra - max(avail, 0), 0) if extra > 0 else 0, "max_feasible_qty": mx, "verdict": verdict,
            "credit": {"headroom": headroom, "unit_price": price, "extra_amount": (extra * price if price is not None and extra > 0 else 0), "ok": credit_ok}}


_VERDICT_KO = {"POSSIBLE": "증량 가능", "CONDITIONAL": "조건부 가능(부분 증량)", "IMPOSSIBLE": "증량 불가", "NO_INCREASE": "증량 요청 아님", "UNCONFIRMED": "확인 불가(계약 단가 또는 거래처 정보 없음) — 담당자 이관"}


def _policy(rel, name):
    return next((x for x in rel["spec"].get("policies", []) if x.get("id") == name or x.get("implementation_ref") == name), None)


def _tool_run(a, pid, p, m, rel, qt, b):
    if qt in ("entity_lookup", "entity_related"):
        from . import ax_auto
        return ax_auto.generic_tool(a, pid, p, m, rel, qt, b)
    if qt not in ax_tools.FUNCS:
        raise ApiError(400, "UNSUPPORTED_QUESTION", f"question_type={'|'.join(['order_increase', 'entity_lookup', 'entity_related'] + list(ax_tools.FUNCS))}")
    pol = _policy(rel, qt)
    if not pol:
        raise ApiError(409, "POLICY_NOT_IN_RELEASE", f"승인된 release 에 정책 {qt} 가 없어 실행하지 않습니다(새 release 에 포함·승인 필요).")
    args = ax_tools.validate(qt, b)
    cn = _src(pid)
    try:
        owner = ax_tools.pre_owner(cn, qt, args)
        ax_tools.check_scope(ax_tools.CONTRACTS[qt]["scope"], m, args, owner)  # 도구 실행 전 권한 검사
        out = ax_tools.FUNCS[qt](cn, args, pol, args.get("as_of") or str(date.today()))
    finally:
        cn.close()
    run = {"run_id": _id("axa"), "project_id": pid, "engine": p["engine"], "evidence_level": EVIDENCE, "llm": "none(결정적 도구)", "ontology": f"{rel['model_id']}@{rel['version']}", "policy": f"{pol['id']}@1",
           "tool": f"{qt}@1", "observed_at": _now(), "query_ids": [_qid(qt, tuple(sorted(args.items())))], "freshness": "실시간 원천 조회(조회 시각 기준)", "result": out, "by": a["user_id"], "tenant_id": args["tenant_id"]}
    S["runs"][run["run_id"]] = run
    audit(a, "AX_AGENT_RUN", pid, run["run_id"], out["verdict"], {"tool": qt})
    _save()
    return run


def agent_run(a, pid, b):
    p, m = _proj(a, pid)
    rel = _active_release(p, b.get("release_id"))
    qt = b.get("question_type", "order_increase")
    if qt != "order_increase":
        return _tool_run(a, pid, p, m, rel, qt, b)
    tenant, oid = _ident(b.get("tenant_id"), "tenant_id"), _ident(b.get("order_id"), "order_id")
    q = _qty(b.get("new_qty"))
    cn = _src(pid)
    try:
        pre = cn.execute("select customer_id from sales_orders where tenant_id=? and order_id=?", (tenant, oid)).fetchone()
        _scope_check(m, tenant, pre["customer_id"] if pre else None)  # 도구 실행 전 권한 검사(검색 전·도구 실행 시·응답 직전 중 2단계 적용)
        d = _increase_decision(cn, tenant, oid, q)
    finally:
        cn.close()
    if d is None:
        out = {"verdict": "NOT_FOUND", "answer": "해당 tenant에서 주문을 찾을 수 없습니다. 추정하지 않고 담당자에게 이관합니다."}
    else:
        _scope_check(m, tenant, d["order"]["customer_id"])
        alts = []
        if d["verdict"] == "CONDITIONAL":
            alts.append({"option": "PARTIAL", "qty": d["max_feasible_qty"], "desc": f"{d['max_feasible_qty']}박스까지 부분 증량(부족 {d['shortage']}박스는 입고 후 재요청)"})
        if d["verdict"] in ("CONDITIONAL", "IMPOSSIBLE"):
            alts.append({"option": "KEEP", "qty": d["order"]["current_qty"], "desc": "기존 수량 유지"})
        out = {"verdict": d["verdict"], "detail": d, "alternatives": alts,
               "answer": f"{_VERDICT_KO[d['verdict']]}: 현재 {d['order']['current_qty']}박스 → 요청 {q}박스, 추가 필요 {d['request']['extra_needed']}박스, 추가 가용 {d['stock']['additional_available']}박스, 부족 {d['shortage']}박스."
                         " (추가 가용은 기존 주문분 예약 이후의 추가 할당 가능량)"}
    run = {"run_id": _id("axa"), "project_id": pid, "engine": p["engine"], "evidence_level": EVIDENCE, "llm": "none(결정적 도구)", "ontology": f"{rel['model_id']}@{rel['version']}", "policy": "change_order_increase@1",
           "tool": "order_increase_check@1", "observed_at": _now(), "query_ids": [_qid("order_increase", (tenant, oid, q))], "freshness": "실시간 원천 조회(조회 시각 기준)", "result": out, "by": a["user_id"], "tenant_id": tenant}
    S["runs"][run["run_id"]] = run
    audit(a, "AX_AGENT_RUN", pid, run["run_id"], out["verdict"])
    _save()
    return run


# ------------------------------------------------------------------ 제안→승인→명령(AX-12)
def _ph(payload):
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def proposal_create(a, pid, b):
    p, m = _proj(a, pid, ("architect", "developer", "business_user", "domain_expert", "reviewer"))
    rel = _active_release(p)
    tenant, oid, q = _ident(b.get("tenant_id"), "tenant_id"), _ident(b.get("order_id"), "order_id"), _qty(b.get("new_qty"))
    cn = _src(pid)
    try:
        pre = cn.execute("select customer_id from sales_orders where tenant_id=? and order_id=?", (tenant, oid)).fetchone()
        _scope_check(m, tenant, pre["customer_id"] if pre else None)
        d = _increase_decision(cn, tenant, oid, q)
    finally:
        cn.close()
    if d is None:
        raise ApiError(404, "ORDER_NOT_FOUND", "주문을 찾을 수 없습니다.")
    if d["verdict"] not in ("POSSIBLE", "NO_INCREASE") or (d["max_feasible_qty"] is not None and q > d["max_feasible_qty"]):
        raise ApiError(409, "POLICY_BLOCKED", f"정책상 요청 수량을 제안할 수 없습니다({d['verdict']}). 가능한 최대 수량: {d['max_feasible_qty']}", max_feasible_qty=d["max_feasible_qty"], verdict=d["verdict"])
    payload = {"tenant_id": tenant, "order_id": oid, "new_qty": q, "from_qty": d["order"]["current_qty"], "order_row_version": d["order"]["row_version"], "stock_row_version": d["stock"]["row_version"]}
    pr = {"proposal_id": _id("axq"), "project_id": pid, "payload": payload, "payload_hash": _ph(payload), "proposer": a["user_id"], "policy_version": "change_order_increase@1", "ontology": f"{rel['model_id']}@{rel['version']}",
          "expires_at": time.time() + 1800, "state": "PROPOSED", "approver": None, "created_at": _now(), "decision": d["verdict"]}
    S["proposals"][pr["proposal_id"]] = pr
    audit(a, "AX_PROPOSAL_CREATE", pid, pr["proposal_id"], detail={"hash": pr["payload_hash"][:12]})
    _save()
    return pr


def approval_create(a, pid, b):
    p, m = _proj(a, pid, APPROVER_ROLES)
    pr = S["proposals"].get(b.get("proposal_id"))
    if not pr or pr["project_id"] != pid:
        raise ApiError(404, "PROPOSAL_NOT_FOUND", "제안을 찾을 수 없습니다.")
    if pr["proposer"] == a["user_id"]:
        audit(a, "AX_APPROVAL_DENIED", pid, pr["proposal_id"], "denied", {"why": "self"})
        _save()
        raise ApiError(403, "SELF_APPROVAL_FORBIDDEN", "제안자는 자신의 제안을 승인할 수 없습니다.")
    if b.get("payload_hash") != pr["payload_hash"]:
        audit(a, "AX_APPROVAL_DENIED", pid, pr["proposal_id"], "denied", {"why": "hash"})
        _save()
        raise ApiError(409, "PAYLOAD_HASH_MISMATCH", "승인 대상과 제안 내용이 다릅니다(변조 또는 이전 버전).")
    if time.time() > pr["expires_at"]:
        pr["state"] = "EXPIRED"
        raise ApiError(409, "PROPOSAL_EXPIRED", "제안 유효시간이 지났습니다. 다시 제안하세요.")
    if pr["state"] != "PROPOSED":
        raise ApiError(409, "BAD_STATE", f"현재 상태 {pr['state']} 에서는 승인할 수 없습니다.")
    pr["state"], pr["approver"], pr["approved_at"] = "APPROVED", a["user_id"], _now()
    audit(a, "AX_APPROVAL", pid, pr["proposal_id"])
    _save()
    return pr


def command_exec(a, pid, b):
    p, m = _proj(a, pid, ("architect", "developer", "business_user", "domain_expert", "reviewer"))
    if p["mode"] == "RELEASE_CANDIDATE":
        raise ApiError(403, "COMMAND_NOT_IN_THIS_MODE", "RELEASE_CANDIDATE 모드는 이 서비스에서 업무 명령을 실행하지 않습니다(별도 승인 절차).")
    key = b.get("idempotency_key")
    if not isinstance(key, str) or len(key) < 8:
        raise ApiError(400, "IDEMPOTENCY_KEY_REQUIRED", "idempotency_key(8자 이상)가 필요합니다.")
    pr = S["proposals"].get(b.get("proposal_id"))
    if not pr or pr["project_id"] != pid:
        raise ApiError(404, "PROPOSAL_NOT_FOUND", "제안을 찾을 수 없습니다.")
    prev = S["commands"].get(f"{pid}:{key}")
    if prev:
        if prev["proposal_id"] != pr["proposal_id"]:
            raise ApiError(409, "IDEMPOTENCY_KEY_REUSED", "같은 키가 다른 제안에 사용되었습니다.")
        return dict(prev, replayed=True)
    if pr["state"] == "EXECUTED":
        raise ApiError(409, "ALREADY_EXECUTED", "이미 실행된 제안입니다.")
    if pr["state"] != "APPROVED":
        audit(a, "AX_COMMAND_DENIED", pid, pr["proposal_id"], "denied", {"why": "not approved"})
        _save()
        raise ApiError(403, "NOT_APPROVED", "승인되지 않은 제안은 실행할 수 없습니다.")
    if b.get("payload_hash") != pr["payload_hash"] or _ph(pr["payload"]) != pr["payload_hash"]:
        audit(a, "AX_COMMAND_DENIED", pid, pr["proposal_id"], "denied", {"why": "hash"})
        _save()
        raise ApiError(409, "PAYLOAD_HASH_MISMATCH", "승인된 내용과 실행 내용이 다릅니다.")
    if time.time() > pr["expires_at"]:
        pr["state"] = "EXPIRED"
        _save()
        raise ApiError(409, "PROPOSAL_EXPIRED", "제안 유효시간이 지났습니다.")
    pl = pr["payload"]
    cn = _src(pid, rw=True, purpose="command")  # command 계정(별도 연결·최소 변경: 주문 수량·row_version 만)
    try:
        cn.begin()
        lk = cn.lock_suffix
        pre = cn.execute("select product_id from sales_orders where tenant_id=? and order_id=?", (pl["tenant_id"], pl["order_id"])).fetchone()
        if not pre:
            cn.rollback()
            raise ApiError(404, "ORDER_NOT_FOUND", "주문을 찾을 수 없습니다.")
        # 잠금 순서 고정(재고 → 주문)으로 교착을 피하고, 같은 품목을 쓰는 다른 명령을 직렬화한다
        stv = cn.execute("select row_version from stock where tenant_id=? and product_id=?" + lk, (pl["tenant_id"], pre["product_id"])).fetchone()
        cur = cn.execute("select row_version, requested_qty from sales_orders where tenant_id=? and order_id=?" + lk, (pl["tenant_id"], pl["order_id"])).fetchone()
        if not cur or int(_py(cur["row_version"])) != pl["order_row_version"] or int(_py(stv["row_version"])) != pl["stock_row_version"] or int(_py(cur["requested_qty"])) != pl["from_qty"]:
            cn.rollback()
            pr["state"] = "STALE"
            audit(a, "AX_COMMAND_CONFLICT", pid, pr["proposal_id"], "conflict", {"why": "row_version"})
            _save()
            raise ApiError(409, "STALE_PROPOSAL", "승인 이후 원천 데이터가 바뀌었습니다. 다시 제안하고 재승인하세요.")
        d = _increase_decision(cn, pl["tenant_id"], pl["order_id"], pl["new_qty"])
        if d["verdict"] not in ("POSSIBLE", "NO_INCREASE"):
            cn.rollback()
            pr["state"] = "STALE"
            _save()
            raise ApiError(409, "POLICY_RECHECK_FAILED", f"원천 재검증에서 정책을 통과하지 못했습니다({d['verdict']}).")
        n = cn.execute("update sales_orders set requested_qty=?, row_version=row_version+1 where tenant_id=? and order_id=? and row_version=?", (pl["new_qty"], pl["tenant_id"], pl["order_id"], pl["order_row_version"])).rowcount
        if n != 1:
            cn.rollback()
            raise ApiError(409, "STALE_PROPOSAL", "동시 변경이 감지되었습니다.")
        cn.commit()
    finally:
        cn.close()
    res = {"command_id": _id("axm"), "proposal_id": pr["proposal_id"], "idempotency_key": key, "state": "EXECUTED", "applied": {"order_id": pl["order_id"], "from_qty": pl["from_qty"], "to_qty": pl["new_qty"]},
           "executed_by": a["user_id"], "approved_by": pr["approver"], "at": _now(), "note": "원천 트랜잭션에서 재고·정책·버전을 재검증한 뒤 처리(fixture). 파생 인덱스(native.sqlite)는 다음 파이프라인 실행 전까지 STALE"}
    pr["state"] = "EXECUTED"
    S["commands"][f"{pid}:{key}"] = res
    audit(a, "AX_COMMAND_EXEC", pid, pr["proposal_id"], detail={"to": pl["new_qty"]})
    _save()
    return res


def command_status(a, pid, key):
    _proj(a, pid)
    c = S["commands"].get(f"{pid}:{key}")
    return c or {"state": "UNKNOWN", "note": "해당 키로 실행된 명령이 없습니다(타임아웃 후 재시도 전에 이 조회를 사용)."}


def proposals(a, pid):
    _proj(a, pid)
    return [pr for pr in S["proposals"].values() if pr["project_id"] == pid]


# ------------------------------------------------------------------ 평가(AX-11)
GOLDEN = [
    {"id": "G01", "axis": "수치", "tenant": "T1", "order": "SO-1001", "qty": 35, "expect": {"verdict": "CONDITIONAL", "extra_needed": 15, "additional_available": 12, "shortage": 3, "max_feasible_qty": 32}},
    {"id": "G02", "axis": "수치", "tenant": "T1", "order": "SO-1001", "qty": 30, "expect": {"verdict": "POSSIBLE", "extra_needed": 10, "additional_available": 12, "shortage": 0}},
    {"id": "G03", "axis": "경계", "tenant": "T1", "order": "SO-1001", "qty": 32, "expect": {"verdict": "POSSIBLE", "shortage": 0}},
    {"id": "G04", "axis": "경계", "tenant": "T1", "order": "SO-1001", "qty": 33, "expect": {"verdict": "CONDITIONAL", "shortage": 1, "max_feasible_qty": 32}},
    {"id": "G05", "axis": "경계", "tenant": "T1", "order": "SO-1001", "qty": 20, "expect": {"verdict": "NO_INCREASE"}},
    {"id": "G06", "axis": "tenant 혼합", "tenant": "T2", "order": "SO-1001", "qty": 10, "expect": {"verdict": "IMPOSSIBLE", "additional_available": 0, "shortage": 5}},
    {"id": "G07", "axis": "다른 주문", "tenant": "T1", "order": "SO-1002", "qty": 90, "expect": {"verdict": "CONDITIONAL", "additional_available": 12, "shortage": 10, "max_feasible_qty": 80}},
    {"id": "G08", "axis": "불확실", "tenant": "T1", "order": "SO-9999", "qty": 10, "expect": {"verdict": "NOT_FOUND"}},
]


def _path(o, path):
    for k in path.split("."):
        if o is None:
            return None
        o = o[int(k)] if isinstance(o, list) and k.isdigit() and int(k) < len(o) else (o.get(k) if isinstance(o, dict) else None)
    return o


T = lambda i, ax_, ty, args, exp: {"id": i, "axis": ax_, "type": ty, "args": {"tenant_id": "T1", "as_of": "2026-11-14", **args}, "expect": exp}
GOLDEN_TOOLS = [
    T("G09", "납기 대안", "delay_alternatives", dict(order_id="SO-1001", new_qty=35), {"verdict": "DELAY_RISK", "detail.shortage": 3, "alternatives.0.qty_now": 32, "alternatives.1.option": "SPLIT", "alternatives.1.delay_days": 4}),
    T("G10", "납기 대안", "delay_alternatives", dict(order_id="SO-1001"), {"verdict": "ON_TIME_FROM_STOCK"}),
    T("G11", "단가 차이", "price_diff_reason", dict(order_id="SO-1002"), {"verdict": "BILLED_ABOVE_CONTRACT", "detail.diff": 50, "detail.diff_pct": 5.26}),
    T("G12", "단가 차이", "price_diff_reason", dict(order_id="SO-1001"), {"verdict": "MATCHES_CONTRACT"}),
    T("G13", "미수금", "receivable_summary", dict(customer_id="C1"), {"verdict": "OK", "detail.balance": 50000, "detail.matches_credit_used": True}),
    T("G14", "미수금", "receivable_summary", dict(customer_id="C2"), {"verdict": "OK", "detail.invoiced": 400000, "detail.paid": 300000, "detail.balance": 100000}),
    T("G15", "미수금 기준일", "receivable_summary", dict(customer_id="C1", as_of="2026-11-02"), {"verdict": "OK", "detail.balance": 100000, "detail.paid": 0}),
    T("G16", "발주", "purchase_reorder", dict(product_id="PRD1", needed_qty=3), {"verdict": "COVERED_BY_INBOUND"}),
    T("G17", "발주", "purchase_reorder", dict(product_id="PRD1", needed_qty=150), {"verdict": "ORDER_OPTIONS", "recommended": "S2", "alternatives.0.order_qty": 50, "alternatives.0.total_cost": 35000, "alternatives.1.supplier_id": "S1", "alternatives.1.order_qty": 60}),
    T("G18", "공급처 변경", "supplier_switch", dict(product_id="PRD1", current_supplier_id="S1", needed_qty=50), {"verdict": "ALTERNATIVES_AVAILABLE", "alternatives.0.supplier_id": "S2", "alternatives.0.vs_current.cost_diff": -11800}),
    T("G19", "단가 급등", "price_spike", dict(supplier_id="S1", product_id="PRD1"), {"verdict": "SPIKE", "detail.change_pct": 30.0}),
    T("G20", "단가 급등", "price_spike", dict(supplier_id="S2", product_id="PRD1"), {"verdict": "NO_PREVIOUS_QUOTE"}),
    T("G21", "입고 차이", "receipt_variance", dict(po_id="PO-2"), {"verdict": "OUT_OF_TOLERANCE", "detail.variance_pct": 4.0}),
    T("G22", "입고 차이", "receipt_variance", dict(po_id="PO-3"), {"verdict": "WITHIN_TOLERANCE", "detail.variance_pct": 2.0}),
    T("G23", "입고 차이", "receipt_variance", dict(po_id="PO-1"), {"verdict": "NOT_RECEIVED_YET"}),
    T("G24", "불확실", "receipt_variance", dict(po_id="PO-9"), {"verdict": "NOT_FOUND"}),
]


def evaluate_core(pid, persist=True, rel=None):
    pols = {x["id"]: x for x in (rel["spec"]["policies"] if rel else _template({"objects": {}})["policies"])}
    res = []
    cn = _src(pid)
    try:
        for g in GOLDEN + GOLDEN_TOOLS:
            if "type" in g:
                try:
                    args = {k: v for k, v in g["args"].items() if k in ax_tools.CONTRACTS[g["type"]]["input_schema"]["properties"]}
                    out = ax_tools.FUNCS[g["type"]](cn, ax_tools.validate(g["type"], args), pols.get(g["type"]), g["args"].get("as_of", "2026-11-14"))
                except ApiError as e:
                    out = {"error": e.code}
                bad = {k: (v, _path(out, k)) for k, v in g["expect"].items() if _path(out, k) != v}
            else:
                d = _increase_decision(cn, g["tenant"], g["order"], g["qty"])
                got = {"verdict": "NOT_FOUND"} if d is None else {"verdict": d["verdict"], "extra_needed": d["request"]["extra_needed"], "additional_available": d["stock"]["additional_available"], "shortage": d["shortage"], "max_feasible_qty": d["max_feasible_qty"]}
                bad = {k: (v, got.get(k)) for k, v in g["expect"].items() if got.get(k) != v}
            res.append({"id": g["id"], "axis": g["axis"], "pass": not bad, "mismatch": bad})
    finally:
        cn.close()
    p = sum(1 for r in res if r["pass"])
    return {"cases": res, "passed": p, "total": len(res), "gates_passed": p == len(res)}


def evaluate(a, pid, b):
    p, m = _proj(a, pid, ("architect", "developer", "reviewer", "domain_expert"))
    rel0 = _active_release(p)
    if not _policy(rel0, "change_order_increase"):
        from . import ax_auto
        g = ax_auto.generic_eval(a, pid, rel0, m)
        sec = []
        try:
            ax_auto._keyvals({"key": ["id"]}, {"id": "1' OR '1'='1"})
            sec.append({"id": "S01 키 값 SQL 주입", "pass": False, "got": "허용됨"})
        except ApiError as e:
            sec.append({"id": "S01 키 값 SQL 주입", "pass": e.code == "BAD_KEY", "got": e.code})
        ev = {"eval_id": _id("axe"), "project_id": pid, "kind": "GENERIC_STRUCTURAL", "golden": g, "generic": g, "security": sec, "gates_passed": g["gates_passed"] and all(x["pass"] for x in sec), "evidence_level": EVIDENCE, "at": _now(),
              "scope_note": "구조·접근·검색 자동 검사입니다(엔터티 키 조회, tenant 분리, 관계 탐색, 문서 자기 회수). 현업 정답(golden)·업무 정책 검증이 아니며 현업 검토가 필요합니다.",
              "not_measured": ["업무 정답성", "성능·부하", "실제 LLM 응답 품질", "DBX 경로 parity"]}
        S["evals"][ev["eval_id"]] = ev
        audit(a, "AX_EVALUATE", pid, ev["eval_id"], "ok" if ev["gates_passed"] else "failed", {"kind": ev["kind"]})
        _save()
        return ev
    core = evaluate_core(pid, rel=rel0)
    sec = []
    # 보안·범위 음성 시험(읽기 전용, 별도 호출 경로로 실제 서버 검사를 통과해야 함)
    ext = {"role": "business_user", "tenants": ["T1"], "customers": ["C1"]}

    def deny(name, fn, code):
        try:
            fn()
            sec.append({"id": name, "pass": False, "got": "허용됨"})
        except ApiError as e:
            sec.append({"id": name, "pass": e.code == code, "got": e.code})
    deny("S01 외부 사용자가 다른 tenant 조회", lambda: _scope_check(ext, "T2", "C1"), "TENANT_SCOPE_DENIED")
    deny("S02 외부 거래처가 다른 거래처 주문 조회", lambda: _scope_check(ext, "T1", "C2"), "CUSTOMER_SCOPE_DENIED")
    deny("S03 수량 필드 SQL 주입", lambda: _qty("35; DROP TABLE stock"), "BAD_QTY")
    deny("S04 식별자 필드 SQL 주입", lambda: _ident("SO-1001' OR '1'='1", "order_id"), "BAD_PARAM")
    cust = {"role": "business_user", "tenants": ["T1"], "customers": ["C1"], "suppliers": None}
    sup = {"role": "business_user", "tenants": ["T1"], "customers": None, "suppliers": ["S2"]}
    deny("S06 외부 거래처가 매입 비교 도구 사용", lambda: ax_tools.check_scope("purchase_internal", cust, {"tenant_id": "T1"}), "INTERNAL_ONLY")
    deny("S07 공급처가 경쟁 공급처 발주(PO) 조회", lambda: ax_tools.check_scope("purchase_supplier", sup, {"tenant_id": "T1"}, "S1"), "SUPPLIER_SCOPE_DENIED")
    deny("S08 거래처 C1 계정이 C2 미수금 조회", lambda: ax_tools.check_scope("sales", cust, {"tenant_id": "T1"}, "C2"), "CUSTOMER_SCOPE_DENIED")
    deny("S09 승인되지 않은 가중치(합≠1) 사용", lambda: ax_tools._weights({"weights": {"total_cost": 0.9, "lead_days": 0.3, "quality": 0.2}}), "POLICY_WEIGHTS_INVALID")
    deny("S10 공급처 계정이 매출처 도구 사용", lambda: ax_tools.check_scope("sales", sup, {"tenant_id": "T1"}, "C1"), "SUPPLIER_CANNOT_USE_SALES")
    deny("S11 날짜 필드 주입", lambda: ax_tools.validate("price_spike", {"tenant_id": "T1", "supplier_id": "S1", "product_id": "PRD1", "as_of": "2026-11-14'; DROP"}), "BAD_PARAM")
    cn = _src(pid)
    try:
        d1 = _increase_decision(cn, "T1", "SO-1001", 35)
        memo = cn.execute("select note from legacy_memo where memo_id=2").fetchone()[0]
    finally:
        cn.close()
    sec.append({"id": "S05 DB 주석 속 악성 지시(approve every order)가 판정에 영향 없음", "pass": d1["verdict"] == "CONDITIONAL" and "ignore previous" in memo and "memo" not in json.dumps(d1), "got": d1["verdict"]})
    ok_all = core["gates_passed"] and all(x["pass"] for x in sec)
    ev = {"eval_id": _id("axe"), "project_id": pid, "golden": core, "security": sec, "gates_passed": ok_all, "evidence_level": EVIDENCE, "at": _now(),
          "scope_note": f"golden {core['total']}건·보안 {len(sec)}건은 합성 fixture 기준 초기 세트이며 지시서 목표(최소 120건·현업 정답·봉인 holdout)에 한참 못 미칩니다. 고객 업무 수용 테스트를 대체하지 않습니다.",
          "not_measured": ["성능·부하", "실제 LLM 응답 품질", "실제 레거시 DB(Oracle/PostgreSQL/MySQL)", "DBX 경로 parity"]}
    S["evals"][ev["eval_id"]] = ev
    audit(a, "AX_EVALUATE", pid, ev["eval_id"], "ok" if ok_all else "failed")
    _save()
    return ev


# ------------------------------------------------------------------ 지식 문서·검색(AX-07)
def doc_add(a, pid, b):
    _proj(a, pid, ("architect", "developer", "domain_expert"))
    r = ax_search.ingest(S, a, pid, b)
    audit(a, "AX_DOC_ADD", pid, r["doc_id"], detail={"version": r["version"], "suspicious_chunks": r["suspicious_chunks"]})
    _save()
    return r


def doc_seed_demo(a, pid):
    _proj(a, pid, ("architect", "developer", "domain_expert"))
    made = []
    for d in ax_search.DEMO_DOCS:
        try:
            made.append(ax_search.ingest(S, a, pid, dict(d))["doc_id"])
        except ApiError:
            pass
    audit(a, "AX_DOC_SEED_DEMO", pid, detail={"docs": len(made)})
    _save()
    return {"added": made, "note": "합성 데모 문서입니다. 외부 입력 메모에는 악성 지시문 예시가 포함되어 있습니다(데이터로만 취급)."}


def doc_list(a, pid):
    p, m = _proj(a, pid)
    today = str(date.today())
    return [{k: v for k, v in d.items() if k != "chunks"} | {"chunks": len(d["chunks"]), "visible_now": ax_search.visible(d, m, today, True)}
            for d in S["documents"].values() if d["project_id"] == pid and ax_search.visible(d, m, "9999-12-31", True)]


def doc_search(a, pid, q, mode="hybrid", k=5, as_of=None, rerank=False, include_old=False):
    p, m = _proj(a, pid)
    r = ax_search.search(S, pid, m, q, mode, max(1, min(int(k), 20)), as_of, rerank, include_old)
    audit(a, "AX_DOC_SEARCH", pid, detail={"mode": mode, "q_len": len(q), "hits": len(r["results"])})
    _save()
    return r


def doc_eval(a, pid):
    p, m = _proj(a, pid, ("architect", "developer", "reviewer", "domain_expert"))
    r = ax_search.evaluate(S, pid, m)
    audit(a, "AX_DOC_EVAL", pid, detail={k: v["recall@3"] for k, v in r["modes"].items()})
    _save()
    return r


# ------------------------------------------------------------------ 적극적 지원 신호(탐지·제안만, 무승인 실행 없음)
def signals_scan(a, pid, b=None):
    p, m = _proj(a, pid, ("architect", "developer", "reviewer", "domain_expert"))
    if not ax_tools.internal(m):
        raise ApiError(403, "INTERNAL_ONLY", "신호 inbox 는 내부 사용자 전용입니다.")
    today = (b or {}).get("as_of") or str(date.today())
    cn = _src(pid)
    try:
        found = ax_tools.detect_signals(cn, today)
    finally:
        cn.close()
    now = _now()
    seen, new, upd = set(), 0, 0
    for f in found:
        key = f"{pid}:{f['kind']}:{f['ref']}"
        seen.add(key)
        cur = S["signals"].get(key)
        if cur and cur["status"] in ("OPEN", "ACK", "DISMISSED"):
            cur["last_seen"] = now
            if cur["message"] != f["message"] and cur["status"] != "DISMISSED":
                cur["message"], cur["changed_summary"], cur["status"] = f["message"], "내용이 바뀌어 다시 올림", "OPEN"
            upd += 1
            continue
        S["signals"][key] = dict(f, signal_id=key, project_id=pid, status="OPEN", first_seen=now, last_seen=now, as_of=today, valid_until=str(date.fromisoformat(today).fromordinal(date.fromisoformat(today).toordinal() + 7)),
                                 proposal_note="제안/탐지만 합니다. 외부 발송·주문·발주는 초안→승인→발송 권한이 갖춰진 뒤에만 가능합니다.")
        new += 1
    resolved = 0
    for k, v in S["signals"].items():
        if v["project_id"] == pid and k not in seen and v["status"] in ("OPEN", "ACK"):
            v["status"], v["resolved_at"] = "RESOLVED", now
            resolved += 1
    audit(a, "AX_SIGNAL_SCAN", pid, detail={"new": new, "updated": upd, "resolved": resolved})
    _save()
    return {"new": new, "updated": upd, "resolved": resolved, "open": sum(1 for v in S["signals"].values() if v["project_id"] == pid and v["status"] == "OPEN")}


def signals_list(a, pid):
    p, m = _proj(a, pid)
    if not ax_tools.internal(m):
        raise ApiError(403, "INTERNAL_ONLY", "신호 inbox 는 내부 사용자 전용입니다.")
    return sorted((v for v in S["signals"].values() if v["project_id"] == pid), key=lambda v: (v["status"] != "OPEN", v["kind"], v["ref"]))


def signal_ack(a, pid, sid, b):
    p, m = _proj(a, pid, ("architect", "developer", "reviewer", "domain_expert"))
    v = S["signals"].get(sid)
    if not v or v["project_id"] != pid:
        raise ApiError(404, "SIGNAL_NOT_FOUND", "신호를 찾을 수 없습니다.")
    st = b.get("status")
    if st not in ("ACK", "DISMISSED"):
        raise ApiError(400, "BAD_STATUS", "ACK | DISMISSED")
    if st == "DISMISSED" and len((b.get("note") or "").strip()) < 4:
        raise ApiError(400, "NOTE_REQUIRED", "무시(DISMISSED)는 사유(4자 이상)가 필요합니다.")
    v["status"], v["handled_by"], v["note"] = st, a["user_id"], b.get("note", "")
    audit(a, "AX_SIGNAL_ACK", pid, sid, detail={"status": st})
    _save()
    return v


def tool_contracts(a, pid):
    _proj(a, pid)
    return list(ax_tools.CONTRACTS.values())


# ------------------------------------------------------------------ 배포·rollback·내보내기
def deploy(a, pid, b):
    p, _ = _proj(a, pid, ("architect", "reviewer", "domain_expert"))
    r = _rel(pid, b.get("release_id"))
    engine = b.get("engine") or p["engine"]
    if engine == "databricks":
        raise ApiError(412, "PREFLIGHT_FAILED", "DBX 경로 배포 preflight 실패: Workspace 연결·권한·실제 배포 증거가 없습니다(컴파일 산출물만 제공).",
                       checks=[{"check": "workspace_connected", "ok": False}, {"check": "unsupported_stage ProjectGraph", "ok": False}])
    if r["status"] not in ("APPROVED", "ACTIVE"):
        raise ApiError(409, "RELEASE_NOT_APPROVED", "승인된 release 만 배포합니다.")
    ev = [x for x in S["evals"].values() if x["project_id"] == pid and x["gates_passed"]]
    if not ev:
        raise ApiError(409, "EVAL_GATE_REQUIRED", "필수 gate(golden·보안 100%)를 통과한 평가가 없어 배포하지 않습니다.")
    if p["active_release"] and p["active_release"] != r["release_id"]:
        p["previous_release"] = p["active_release"]
        S["releases"][p["previous_release"]]["status"] = "APPROVED"
    p["active_release"] = r["release_id"]
    r["status"] = "ACTIVE"
    d = {"deployment_id": _id("axd"), "project_id": pid, "release_id": r["release_id"], "engine": engine, "at": _now(), "by": a["user_id"], "evidence_level": EVIDENCE, "rollback_to": p["previous_release"]}
    S["deployments"][d["deployment_id"]] = d
    audit(a, "AX_DEPLOY", pid, d["deployment_id"])
    _save()
    return d


def rollback(a, pid, b=None):
    p, _ = _proj(a, pid, ("architect", "reviewer", "domain_expert"))
    prev = p.get("previous_release")
    if not prev:
        raise ApiError(409, "NO_PREVIOUS_RELEASE", "되돌릴 이전 release 가 없습니다.")
    cur = p["active_release"]
    S["releases"][cur]["status"] = "APPROVED"
    S["releases"][prev]["status"] = "ACTIVE"
    p["active_release"], p["previous_release"] = prev, None
    audit(a, "AX_ROLLBACK", pid, cur, detail={"to": prev, "note": "원천 거래는 건드리지 않음"})
    _save()
    return {"active_release": prev, "rolled_back_from": cur, "source_transactions_touched": 0}


def export_project(a, pid):
    p, _ = _proj(a, pid)
    cons = [dict(c, secret_ref=c["secret_ref"]) for c in S["connectors"].values() if c["project_id"] == pid]
    out = {"format": "wizbase-ax-project/1", "project": {k: v for k, v in p.items() if k != "members"}, "connectors": cons, "releases": [r for r in S["releases"].values() if r["project_id"] == pid],
           "relations": [r for r in S["relations"].values() if r["project_id"] == pid], "secrets_included": False,
           "engine_notes": ["엔진 전환은 export→capability preflight→dry-run→golden parity→shadow read→활성화 순서이며 단일 버튼 무손실 전환을 약속하지 않음", "DBX 경로: ProjectGraph 미지원, 실제 배포 미검증"]}
    audit(a, "AX_EXPORT", pid)
    _save()
    return out


def capabilities(a, pid=None):
    return {"engines": {"native": {"metadata_scan": "sqlite_fixture만 실행", "pipeline": "실제 실행(fixture)", "agent": "결정적 도구(LLM 없음)", "search": "keyword/vector/hybrid(RRF) 구현 — 임베딩은 해시 n-gram(비신경망), Ollama 선택", "graph": "관계형 projection + bounded traversal(후속)", "shacl": "미구현"},
                        "databricks": {"compile": "SQL 산출물 생성", "deploy": "미검증(412)", "run": "미검증", "ProjectGraph": "UNSUPPORTED"}}, "support": SUPPORT, "dictionary_sql": DICT_SQL,
            "standards_note": "SKOS/PROV-O/SHACL 은 참고 방법론이며 준수·인증을 주장하지 않음"}


def audit_list(a, pid, limit=200):
    _proj(a, pid)
    return [x for x in S["audit"] if x["project"] == pid][-limit:]


init()
