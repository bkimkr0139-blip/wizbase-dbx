"""WIZBASE DBX Project Rehearsal - state engine (A: SIMULATED / B: LOCAL_EXECUTED).
Every result is derived from session state; nothing is a canned success."""
from __future__ import annotations
import copy, hashlib, json, math, os, re, shutil, threading, time, uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import duckdb
import sqlglot
import yaml
from sqlglot import exp

from . import seed as seedmod

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get("DBX_DATA_DIR", ROOT / "data")) / "sessions"
DATA.mkdir(parents=True, exist_ok=True)
CAT = seedmod.CATALOG
KST = timezone(timedelta(hours=9))
BASE = datetime.fromisoformat(seedmod.BASE_CLOCK)

TRAINEE = "trainee@wizbase.training"
ADMIN = "uc-admin@wizbase.training"
SVC = "svc-runner"
ANALYST = "analyst-b@wizbase.training"
APPROVER = "approver@wizbase.training"

PROFILE = {
    "profile_id": "aws-seoul-training-baseline-20261111",
    "cloud": "aws", "region": "ap-northeast-2", "workspace_kind": "training", "ui_locale": "en",
    "ui_observed_at": None, "ui_release_id": "unknown", "unity_catalog_enabled": True,
    "compute": {"mode": "serverless", "dbr_version": "not_applicable", "serverless_environment": "unknown",
                "sql_warehouse_channel": "unknown"},
    "cli_version": "to_be_pinned", "cli_min_documented": "0.218.0 (Bundles 문서 기준 최소 버전, 2026-11-11 확인)", "official_names_checked": {"Genie Spaces": "Genie Agents (2026-07)", "Vector Search": "AI Search (2026-06)", "Delta Sharing": "OpenSharing (2026-06)", "Databricks Asset Bundles": "Declarative Automation Bundles", "Delta Live Tables": "Spark Declarative Pipelines on Lakeflow"}, "package_lock_sha256": "to_be_recorded",
    "evidence_status": "DOC_CHECKED", "sa_reviewed_at": None,
    "note": "단일 '2026 버전'이 아닌 분리된 기준 프로필. 이 프로필은 AWS 서울에서 모든 기능이 가능하다는 보증이 아님.",
}

PROFILE_FREE = {**copy.deepcopy(PROFILE), "profile_id": "databricks-free-edition-observed-20261112", "workspace_kind": "free_edition", "ui_observed_at": "2026-11-12", "evidence_status": "WORKSPACE_OBSERVED",
                "compute": {"mode": "serverless_only", "dbr_version": "not_applicable", "serverless_environment": "unknown", "sql_warehouse_channel": "unknown", "warehouse_create": False, "auto_start": True},
                "note": "Databricks Free Edition 워크스페이스 화면을 2026-11-12에 조회(읽기 전용)해 만든 프로필입니다. 서버리스 전용(웨어하우스 생성 비활성), 쿼리 시 자동 시작. "
                        "실제 Free Edition의 기본 catalog 이름은 workspace 이지만 이 시뮬레이터의 실습 데이터는 food_dev 를 씁니다. 유료(Enterprise) 워크스페이스와 메뉴·기능이 다를 수 있습니다."}
PROFILES = {PROFILE["profile_id"]: PROFILE, PROFILE_FREE["profile_id"]: PROFILE_FREE}


def profile_of(S):
    return PROFILES.get(S.get("profile_id"), PROFILE)


FEATURES = [
    {"feature_id": "unity_catalog", "status": "DOC_CHECKED", "workspace_enabled": "unknown", "ui_path": "Catalog", "url": "https://docs.databricks.com/aws/en/data-governance/unity-catalog/access-control/permissions-concepts", "usable": True, "doc_checked_at": "2026-11-11", "workspace_checked_at": None},
    {"feature_id": "sql_warehouse", "status": "DOC_CHECKED", "workspace_enabled": "unknown", "ui_path": "SQL Warehouses", "url": "https://docs.databricks.com/aws/en/workspace/navigate-workspace", "usable": True, "doc_checked_at": "2026-11-11", "workspace_checked_at": None},
    {"feature_id": "notebooks", "status": "DOC_CHECKED", "workspace_enabled": "unknown", "ui_path": "Workspace", "url": "https://docs.databricks.com/aws/en/workspace/navigate-workspace", "usable": True, "doc_checked_at": "2026-11-11", "workspace_checked_at": None},
    {"feature_id": "lakeflow_pipelines", "status": "DOC_CHECKED", "workspace_enabled": "unknown", "ui_path": "Jobs & Pipelines", "url": "https://docs.databricks.com/aws/en/ldp/tutorial-get-started", "usable": True, "doc_checked_at": "2026-11-11", "workspace_checked_at": None},
    {"feature_id": "lakeflow_jobs", "status": "DOC_CHECKED", "workspace_enabled": "unknown", "ui_path": "Jobs & Pipelines", "url": "https://docs.databricks.com/aws/en/jobs/privileges", "usable": True, "doc_checked_at": "2026-11-11", "workspace_checked_at": None},
    {"feature_id": "bundles", "status": "DOC_CHECKED", "workspace_enabled": "unknown", "ui_path": "CLI", "url": "https://docs.databricks.com/aws/en/dev-tools/bundles/", "usable": True, "doc_checked_at": "2026-11-11", "workspace_checked_at": None},
    {"feature_id": "genie_agents", "status": "DOC_CHECKED", "workspace_enabled": "unknown", "ui_path": "Genie (aka Genie Spaces)", "url": "https://docs.databricks.com/aws/en/genie-agents/set-up", "usable": True, "doc_checked_at": "2026-11-11", "workspace_checked_at": None},
    {"feature_id": "oracle_cdc", "status": "unverified", "workspace_enabled": "unknown", "ui_path": "-", "url": "", "usable": False, "doc_checked_at": None, "workspace_checked_at": None},
    {"feature_id": "metric_views", "status": "DRAFT", "workspace_enabled": "unknown", "ui_path": "-", "url": "", "usable": False, "doc_checked_at": None, "workspace_checked_at": None},
    {"feature_id": "model_serving", "status": "DRAFT", "workspace_enabled": "unknown", "ui_path": "-", "url": "", "usable": False, "doc_checked_at": None, "workspace_checked_at": None},
    {"feature_id": "ai_search", "status": "DRAFT", "workspace_enabled": "unknown", "ui_path": "-", "url": "", "usable": False, "doc_checked_at": None, "workspace_checked_at": None},
]

SQL_FN_ALLOW = {"ifnull", "nvl", "coalesce", "date_format", "datediff", "current_date", "current_timestamp",
                "concat_ws", "round", "abs", "upper", "lower", "trim", "length", "substr", "substring", "greatest", "least",
                "nullif", "try_cast", "date_add", "to_date", "regexp_replace", "split"}

_locks: dict[str, threading.RLock] = {}
_conns: dict[str, duckdb.DuckDBPyConnection] = {}
SESSIONS: dict[str, dict] = {}
_glock = threading.RLock()


def nid(S, prefix):
    S["seq"] = S.get("seq", 0) + 1
    return f"{prefix}-{S['seq']:04d}"


def lock_for(sid):
    with _glock:
        return _locks.setdefault(sid, threading.RLock())


def sql_str(v) -> str:
    """값을 databricks 방언 SQL 문자열 리터럴로. sqlglot(databricks)은 백슬래시를 이스케이프로 읽으므로 \\ 와 \' 로 이스케이프한다('' 는 이어붙이기로 해석되어 값이 손상됨)."""
    s = str(v)
    return "'" + s.replace("\\", "\\\\").replace("'", "\\'") + "'"


MAX_SQL_CHARS = 20000


def sha(x) -> str:
    if not isinstance(x, (str, bytes)):
        x = json.dumps(x, sort_keys=True, ensure_ascii=False, default=str)
    if isinstance(x, str):
        x = x.encode()
    return hashlib.sha256(x).hexdigest()


class ApiError(Exception):
    def __init__(self, status, code, message, **extra):
        self.status, self.code, self.message, self.extra = status, code, message, extra


# ---------------------------------------------------------------- session lifecycle
def _template(seed=seedmod.SEED_NAME):
    """Seed once per seed into a template file, then copy it per session (deterministic, fast)."""
    t = DATA / f"_template_{seed}.duckdb"
    with _glock:
        if not t.exists():
            tmp = DATA / "_template_build.duckdb"
            for x in (tmp, DATA / "_template_build.duckdb.wal"):
                x.unlink(missing_ok=True)
            c = duckdb.connect()
            c.execute(f"ATTACH '{tmp}' AS {CAT}")
            seedmod.build(c, seed)
            c.execute(f"CHECKPOINT {CAT}")
            c.close()
            os.replace(tmp, t)
    return t


def _fresh_db(sid, seed=seedmod.SEED_NAME):
    shutil.copy(_template(seed), DATA / f"{sid}.duckdb")


def _open_conn(sid, seeded=False):
    path = str(DATA / f"{sid}.duckdb")
    c = duckdb.connect()
    c.execute(f"ATTACH '{path}' AS {CAT}")
    return c


def _lockdown(c):
    c.execute("SET memory_limit='384MB'")
    c.execute("SET threads=1")
    c.execute("SET enable_external_access=false")
    c.execute("SET lock_configuration=true")


def default_state(sid, owner, lesson_id, mode, learning_mode, seed=seedmod.SEED_NAME):
    grants = [
        # data-engineers: USE CATALOG, bronze read, silver SELECT without USE SCHEMA (fault missing_use_schema), gold working set
        ["data-engineers", "USE CATALOG", f"catalog:{CAT}"],
        ["data-engineers", "USE SCHEMA", f"schema:{CAT}.bronze"], ["data-engineers", "SELECT", f"schema:{CAT}.bronze"],
        ["data-engineers", "SELECT", f"schema:{CAT}.silver"], ["data-engineers", "CREATE TABLE", f"schema:{CAT}.silver"],
        ["data-engineers", "MODIFY", f"schema:{CAT}.silver"],
        ["data-engineers", "USE SCHEMA", f"schema:{CAT}.gold"], ["data-engineers", "SELECT", f"schema:{CAT}.gold"],
        ["data-engineers", "CREATE TABLE", f"schema:{CAT}.gold"], ["data-engineers", "MODIFY", f"schema:{CAT}.gold"], ["data-engineers", "CREATE VOLUME", f"schema:{CAT}.gold"],
        ["analysts", "USE CATALOG", f"catalog:{CAT}"], ["analysts", "USE SCHEMA", f"schema:{CAT}.gold"],
        ["analysts", "SELECT", f"table:{CAT}.gold.v_order_overview"],
    ]
    return {
        "id": sid, "owner": owner, "profile_id": PROFILE["profile_id"], "lesson_id": lesson_id, "mode": mode,
        "learning_mode": learning_mode, "seed": seed, "case": seedmod.case(seed), "created_at": time.time(), "revision": 0,
        "clock_offset_s": 0, "paused": False, "actor": TRAINEE,
        "principals": {
            TRAINEE: {"kind": "user", "groups": ["data-engineers"], "entitlements": ["workspace-access", "databricks-sql-access"]},
            ADMIN: {"kind": "user", "groups": [], "entitlements": ["workspace-access", "databricks-sql-access"], "admin": True},
            SVC: {"kind": "service_principal", "groups": [], "entitlements": ["workspace-access"]},
            ANALYST: {"kind": "user", "groups": ["analysts"], "entitlements": ["workspace-access", "databricks-sql-access"]},
            APPROVER: {"kind": "user", "groups": [], "entitlements": ["workspace-access"], "role": "reviewer"},
        },
        "grants": grants, "owners": {}, "views_created_by": {},
        "warehouse": {"name": "wz-training-wh", "state": "STOPPED", "ready_rev": None, "acl": ["data-engineers", "analysts"]},
        "tickets": [], "executions": {}, "idem": {}, "audit": [], "milestones": {}, "cmd_log": [],
        "faults": [], "fault_log": [], "hints_used": 0, "hint_log": [], "admin_assisted": 0, "resets": [],
        "notebook": {"cells": [{"id": "c1", "lang": "sql", "code": f"SELECT * FROM {CAT}.silver.orders LIMIT 5", "status": "idle", "exec_order": None, "ran_at_rev": None, "edit_rev": 0, "output": None}], "exec_counter": 0, "vars": {}, "restarts": 0, "edit_counter": 0},
        "connections": {"oracle_food_conn": {"type": "oracle", "host": "oracle-food.fixture.invalid", "engine": "Oracle 19c (host: OCI)", "mode": None, "status": "UNTESTED", "last_test": None}},
        "foreign_catalogs": {},
        "pipelines": {"orders_pipeline": {
            "name": "orders_pipeline", "target": f"{CAT}.silver.orders_pl", "run_as": TRAINEE, "state": "CREATED",
            "source_sql": f"SELECT order_id, customer_id, CAST(order_date AS DATE) AS order_date, status, CAST(version AS INTEGER) AS version FROM {CAT}.bronze.raw_orders",
            "expectations": [
                {"name": "pk_unique", "rule": "pk_unique", "col": "order_id", "action": "block"},
                {"name": "customer_not_null", "rule": "not_null", "col": "customer_id", "action": "quarantine"},
                {"name": "status_valid", "rule": "in_set", "col": "status", "set": ["CONFIRMED", "SHIPPED", "CANCELLED", "PENDING"], "action": "warn"}],
            "history": [], "events": []}},
        "jobs": {"orders_job": {
            "name": "orders_job", "owner": TRAINEE, "run_as": SVC, "schedule": None, "timezone": "Asia/Seoul", "retries": 0,
            "tasks": [
                {"task_key": "check_data", "sql": f"SELECT COUNT(*) AS n FROM {CAT}.silver.orders_pl", "depends_on": []},
                {"task_key": "summarize", "sql": f"SELECT status, COUNT(*) AS n FROM {CAT}.silver.orders_pl GROUP BY status", "depends_on": ["check_data"]}],
            "runs": []}},
        "bundle": {
            "files": {
                "databricks.yml": BUNDLE_YML,
                "src/check_data.sql": f"SELECT COUNT(*) AS n FROM {CAT}.silver.orders_pl",
            },
            "deployed": None, "cli_logged_in": False, "cli_host": None, "commits": [], "runs": []},
        "policy": {"active": 1, "versions": {"1": {"rule_id": "ORDER_CHANGE_AFTER_CUTOFF", "requires_approval": True,
                   "prohibited_if": ["customer_credit_blocked", "delivery_route_closed"],
                   "revalidate_before_execution": ["available_inventory", "order_version", "approval_payload_hash"],
                   "tests_passed": True}}, "draft": None},
        "proposals": {}, "approvals": {}, "ax_idem": {},
        "genie": {"datasets": [f"{CAT}.gold.v_order_overview"], "terms": {}, "examples": [], "history": []},
        "checkpoints": {}, "eval_runs": [], "assessment": {"explain_score": None, "explain_by": None},
    }


BUNDLE_YML = """# 가상 터미널 전용 교육 예시 (A/B 모드). 실제 배포 검증 전.
bundle:
  name: food-training
  # databricks_cli_version: ">=0.0.0"   # 버전 미고정이면 배포 검수 경고
resources:
  jobs:
    training_job:
      name: food-training-job
      tasks:
        - task_key: check_data
          notebook_task:
            notebook_path: ./src/check_data.sql
targets:
  dev:
    mode: development
    default: true
"""


def create_session(owner, lesson_id="UC-SELECT-01", mode="B", learning_mode="guided", seed=seedmod.SEED_NAME, profile_id=None):
    if seed not in seedmod.CASES:
        raise ApiError(400, "UNKNOWN_SEED", "seed: " + ", ".join(seedmod.CASES))
    if mode not in ("A", "B"):
        raise ApiError(400, "MODE_NOT_AVAILABLE", "C 모드(실제 교육용 DBX)는 이 배포에 어댑터/자격증명이 없습니다. 별도 배포·승인된 워크스페이스 또는 검토형 증거 제출(UI-22)을 사용하세요.")
    if learning_mode not in ("guided", "practice", "real", "demo"):
        raise ApiError(400, "BAD_LEARNING_MODE", "learning_mode: guided/practice/real/demo")
    sid = "s_" + uuid.uuid4().hex[:12]
    S = default_state(sid, owner, lesson_id, mode, learning_mode, seed)
    if profile_id and profile_id in PROFILES:
        S["profile_id"] = profile_id
    if S["profile_id"] == PROFILE_FREE["profile_id"]:
        S["warehouse"].update({"name": "Serverless Starter Warehouse", "type": "serverless", "size": "2X-Small", "auto_start": True, "can_create": False})
        S["grants"].append(["data-engineers", "CREATE CATALOG", "metastore:main"])         # Free Edition: 코스 전용 catalog 를 만들 수 있음
    with lock_for(sid):
        _fresh_db(sid, seed)
        c = _open_conn(sid)
        _lockdown(c)
        _conns[sid] = c
        S["answer_key_ref"] = "instructor-only"
        SESSIONS[sid] = S
        S["data_digest0"] = data_digest(S)
        audit(S, "system", "SESSION_CREATED", sid, "ok", "SIMULATED", {"lesson": lesson_id, "mode": mode})
        save(S)
    return S


def delete_session(sid):
    """세션과 그 DuckDB·상태 파일을 삭제한다(되돌릴 수 없음)."""
    with lock_for(sid):
        SESSIONS.pop(sid, None)
        c = _conns.pop(sid, None)
        if c:
            try:
                c.close()
            except Exception:
                pass
        for p in DATA.glob(f"{sid}*"):
            if p.name.startswith("s_"):
                try:
                    p.unlink()
                except OSError:
                    pass
    with _glock:
        _locks.pop(sid, None)


def save(S):
    S["last_activity_at"] = time.time()
    p = DATA / f"{S['id']}.json"
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(S, ensure_ascii=False, default=str), encoding="utf-8")
    os.replace(tmp, p)


def load_all():
    for p in DATA.glob("s_*.json"):
        try:
            S = json.loads(p.read_text(encoding="utf-8"))
            dbp = DATA / f"{S['id']}.duckdb"
            if not dbp.exists():
                continue
            c = _open_conn(S["id"])
            _lockdown(c)
            _conns[S["id"]] = c
            _thist_invalidate(S)
            SESSIONS[S["id"]] = S
        except Exception as e:  # pragma: no cover
            print("load fail", p, e)


def get_session(sid, actor) -> dict:
    S = SESSIONS.get(sid)
    if not S or not (actor["role"] in ("instructor",) or S["owner"] == actor["user_id"]
                     or (actor["role"] in ("admin", "reviewer") and True)):
        raise ApiError(404, "SESSION_NOT_FOUND", "세션을 찾을 수 없거나 접근 권한이 없습니다.")
    return S


def owns(S, actor, staff_ok=True):
    if S["owner"] == actor["user_id"]:
        return True
    return staff_ok and actor["role"] in ("instructor", "admin", "reviewer")


def clock(S):
    return BASE + timedelta(seconds=S["revision"] * 5 + S["clock_offset_s"])


def now_utc():
    return datetime.now(timezone.utc).isoformat()


def audit(S, actor_id, event_type, resource, outcome, level, extra=None, code_hash=None, trace=None, effective=None):
    ev = {"event_id": "e_" + uuid.uuid4().hex[:10], "session_id": S["id"], "actor_id": actor_id,
          "effective_principal": effective or S.get("actor"), "event_type": event_type, "resource_id": resource,
          "before_revision": S["revision"], "after_revision": S["revision"], "occurred_at_utc": now_utc(),
          "scenario_clock": clock(S).isoformat(), "trace_id": trace, "code_hash": code_hash,
          "profile_version": S["profile_id"], "evidence_level": level, "outcome": outcome, "detail": extra or {}}
    S["audit"].append(ev)
    return ev


def milestone(S, name):
    S["milestones"].setdefault(name, len(S["audit"]))


# ---------------------------------------------------------------- permissions
def expand(S, p):
    info = S["principals"].get(p, {})
    return {p, *info.get("groups", [])}


def is_admin(S, p):
    return bool(S["principals"].get(p, {}).get("admin"))


def sec_chain(sec):
    kind, name = sec.split(":", 1)
    parts = name.split(".")
    if kind in ("table", "volume"):
        return [sec, f"schema:{parts[0]}.{parts[1]}", f"catalog:{parts[0]}"]
    if kind == "schema":
        return [sec, f"catalog:{parts[0]}"]
    return [sec]


def has_priv(S, p, priv, sec):
    if is_admin(S, p):
        return True
    chain = sec_chain(sec)
    if any(S["owners"].get(x) == p for x in chain):      # 상위(schema/catalog) 소유자는 하위 객체에 전권
        return True
    who = expand(S, p)
    for gp, pr, se in S["grants"]:
        if gp in who and pr in (priv, "ALL PRIVILEGES"):
            if se == sec:
                return True
            if priv.startswith("USE"):
                # USE SCHEMA may be inherited from catalog grant; USE CATALOG only at catalog
                if priv == "USE SCHEMA" and se in chain[1:]:
                    return True
            elif se in chain[1:]:
                return True
    return False


def principal_of(S, actor, override=None):
    if override:
        if actor["role"] not in ("instructor", "admin"):
            raise ApiError(403, "FORBIDDEN", "다른 principal로 실행하려면 강사/관리자 권한이 필요합니다.")
        if override not in S["principals"]:
            raise ApiError(400, "UNKNOWN_PRINCIPAL", override)
        S["admin_assisted"] += 1
        return override
    if actor["role"] == "admin":
        return ADMIN
    return S["principals"] and TRAINEE


# ---------------------------------------------------------------- warehouse
def wh_state(S):
    w = S["warehouse"]
    if w["state"] == "STARTING" and w["ready_rev"] is not None and S["revision"] >= w["ready_rev"]:
        w["state"] = "RUNNING"
    return w["state"]


def warehouse_cmd(S, actor, payload, principal):
    action = payload.get("action")
    w = S["warehouse"]
    if action == "start":
        if "warehouse_start_fail" in S["faults"]:
            w["state"] = "FAILED"
            audit(S, actor["user_id"], "WAREHOUSE_START", w["name"], "failed", "SIMULATED", {"reason": "capacity/quota (injected fault)"})
            return "failed", {"state": "FAILED", "error": {"code": "WAREHOUSE_START_FAILED", "message": "웨어하우스 시작 실패(주입된 장애). 강사/관리자에 quota·용량 확인을 요청하세요."}}
        if not (set(w["acl"]) & expand(S, principal)) and not is_admin(S, principal):
            return "failed", {"error": {"code": "NO_CAN_USE", "message": "Warehouse CAN USE 권한이 없습니다. UC 권한만으로는 실행되지 않습니다."}}
        if wh_state(S) in ("STARTING", "RUNNING"):   # 이미 시작 중/실행 중이면 다시 눌러도 시작 시계를 되돌리지 않는다(재클릭으로 영원히 STARTING에 머무는 문제 방지)
            return "ok", {"state": w["state"], "note": "이미 시작 중이거나 실행 중입니다. 몇 번의 명령 뒤 RUNNING이 됩니다."}
        w["state"] = "STARTING"
        w["ready_rev"] = S["revision"] + 2
        return "ok", {"state": "STARTING"}
    if action == "stop":
        w["state"], w["ready_rev"] = "STOPPED", None
        return "ok", {"state": "STOPPED"}
    return "failed", {"error": {"code": "BAD_ACTION", "message": "start|stop"}}


# ---------------------------------------------------------------- SQL engine
def _ser(v):
    if isinstance(v, float) and (v != v or v in (float("inf"), float("-inf"))):
        return None
    if isinstance(v, timedelta):
        return str(v)
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (datetime,)):
        return v.isoformat()
    if hasattr(v, "isoformat"):
        return v.isoformat()
    if isinstance(v, (bytes, bytearray)):
        return v.hex()
    return v


def user_catalogs(S):
    return S.get("catalogs", {})


def _phys(S, cat, db):
    """(가상 catalog, schema) → DuckDB 물리 (catalog, schema). 사용자 catalog 는 food_dev 안의 'catalog__schema'."""
    if cat in user_catalogs(S):
        return CAT, f"{cat}__{db}"
    return cat, db


def _existsS(S, c, kind, parts):
    """_exists 의 catalog 인식판: parts = [cat, db] | [cat, db, name] (가상 이름)."""
    pc, pdb = _phys(S, parts[0], parts[1])
    return _exists(c, kind, [pc, pdb] + list(parts[2:]))


def _exists(c, kind, parts):
    if kind == "schema":
        return bool(c.execute("select 1 from information_schema.schemata where catalog_name=? and schema_name=?", [parts[0], parts[1]]).fetchall())
    return bool(c.execute("select 1 from information_schema.tables where table_catalog=? and table_schema=? and table_name=?", parts).fetchall())


def _tbl_parts(t: exp.Table):
    if not isinstance(t.this, exp.Identifier):
        raise ApiError(400, "UNSUPPORTED_SQL", "테이블 함수/외부 경로 읽기는 시뮬레이터 미지원입니다.")
    cat = t.catalog or None
    db = t.db or None
    name = t.name
    if cat is None and db is not None:
        cat = CAT
    if cat is None and db is None:
        raise ApiError(400, "TABLE_OR_VIEW_NOT_FOUND", f"`{name}`: 3단계 이름(catalog.schema.table)을 사용하세요.")
    return cat, db, name


def sql_error(code, message, hint=None, **kw):
    return {"code": code, "message": message, "hint": hint, **kw}


def _run_sql(S, sql, principal, via="sql_editor", system=False, need_warehouse=True, trace=None, actor_id=None, swap=None):
    """Parse -> support check -> principal/UC permissions -> warehouse -> isolated compute -> audit."""
    h = sha(sql)
    out = {"status": "failed", "columns": [], "rows": [], "error": None, "sql_hash": h, "evidence_level": "LOCAL_EXECUTED",
           "tables": [], "principal": principal, "compat_notes": ["DuckDB 로컬 실행: Spark/Databricks와 타입·NULL·decimal·시간 의미가 다를 수 있음(호환성 목록 관리)."]}
    c = _conns[S["id"]]

    def fail(err, code_ev="SQL_FAILED"):
        out["error"] = err
        if not system:
            audit(S, actor_id or principal, code_ev, "sql", "failed", "LOCAL_EXECUTED", {"code": err["code"], "msg": err["message"][:200], "missing": err.get("missing")}, code_hash=h, trace=trace, effective=principal)
        return out

    try:
        stmts = sqlglot.parse(sql, read="databricks")
    except Exception as e:
        return fail(sql_error("PARSE_ERROR", f"SQL 구문 분석 실패: {str(e)[:200]}"))
    stmts = [s for s in stmts if s is not None]
    if len(stmts) != 1:
        return fail(sql_error("UNSUPPORTED_SQL", "한 번에 하나의 SQL 문만 실행합니다."))
    st = stmts[0]
    kind = type(st).__name__

    if need_warehouse and not system:
        if "databricks-sql-access" not in S["principals"].get(principal, {}).get("entitlements", []) and not is_admin(S, principal):
            return fail(sql_error("NO_SQL_ENTITLEMENT", "사용자에게 databricks-sql-access entitlement가 없습니다.", "entitlement와 UC 권한은 별도입니다."))
        ws = wh_state(S)
        if ws == "STOPPED" and S["warehouse"].get("auto_start"):
            S["warehouse"]["state"], S["warehouse"]["ready_rev"] = "RUNNING", None
            ws = "RUNNING"
            audit(S, actor_id or principal, "WAREHOUSE_AUTOSTART", S["warehouse"]["name"], "succeeded", "SIMULATED", {"reason": "서버리스: 쿼리 시 자동 시작"})
            out["compat_notes"].append("서버리스 웨어하우스가 쿼리 시 자동으로 시작되었습니다(Free Edition 동작을 본뜬 시뮬레이션).")
        if ws != "RUNNING":
            return fail(sql_error("WAREHOUSE_NOT_RUNNING", f"SQL Warehouse 상태: {ws}. 먼저 Warehouse를 시작하세요.", "Compute/SQL Warehouses 화면에서 시작"))
        if not (set(S["warehouse"]["acl"]) & expand(S, principal)) and not is_admin(S, principal):
            return fail(sql_error("NO_CAN_USE", "Warehouse CAN USE 권한이 없습니다."))

    # --- statement routing
    if kind in ("Grant", "Revoke"):
        return _grant(S, st, kind, principal, out, fail, h, actor_id)
    if kind == "Select" or kind == "Union" or kind == "Subquery" or isinstance(st, exp.Query):
        mode = "query"
    elif kind == "Create" and st.args.get("kind") in ("SCHEMA", "TABLE", "VIEW"):
        mode = "create"
    elif kind == "Insert":
        mode = "insert"
    elif kind in ("Update", "Delete", "Merge"):
        mode = "dml"
    else:
        return fail(sql_error("SIMULATOR_UNSUPPORTED", f"시뮬레이터 미지원 구문: {kind}. 지원: SELECT/JOIN/GROUP BY/CTE/CAST/CASE, CREATE SCHEMA/TABLE/VIEW, INSERT, GRANT/REVOKE(부분집합). Databricks가 지원하지 않는다는 뜻이 아닙니다.",
                                 "공식 문서: https://docs.databricks.com/aws/en/sql/language-manual/"))

    # function allowlist / path functions
    for f in st.find_all(exp.Anonymous):
        nm = (f.name or "").lower()
        if nm not in SQL_FN_ALLOW:
            return fail(sql_error("SIMULATOR_UNSUPPORTED", f"시뮬레이터 미지원 함수: {f.name}()", "공식 문서 경로를 확인하세요. 파일/외부 접근 함수는 차단됩니다."))
    banned = tuple(getattr(exp, n) for n in ("Command", "Copy", "Attach", "Pragma", "ReadCSV", "ReadParquet", "Pivot", "Unnest", "Values") if hasattr(exp, n) and n not in ("Values", "Unnest", "Pivot"))
    if any(True for _ in st.find_all(*banned)):
        return fail(sql_error("SIMULATOR_UNSUPPORTED", "지원하지 않는 구문입니다."))

    # collect referenced tables (excluding CTE aliases and DDL target)
    cte_names = {cte.alias_or_name for cte in st.find_all(exp.CTE)}
    target = None
    if mode in ("create", "insert", "dml"):
        tnode = st.this if mode == "create" else st.this
        if isinstance(tnode, exp.Schema):
            tnode = tnode.this
        target = tnode
    reads = []
    for t in st.find_all(exp.Table):
        if t is target:
            continue
        if not t.name and not t.db:
            continue
        if t.name in cte_names and not t.db:
            continue
        try:
            reads.append((t, _tbl_parts(t)))
        except ApiError as e:
            return fail(sql_error(e.code, e.message))

    # foreign catalog rewrite (after checks)
    resolved = []
    for t, (cat, db, name) in reads:
        if cat in S["foreign_catalogs"]:
            fc = S["foreign_catalogs"][cat]
            if not has_priv(S, principal, "USE CATALOG", f"catalog:{cat}") and not is_admin(S, principal):
                return fail(sql_error("INSUFFICIENT_PERMISSIONS", f"foreign catalog `{cat}` 사용 권한 없음"))
            resolved.append((t, cat, db, name, "foreign"))
            continue
        if cat != CAT and cat not in user_catalogs(S):
            return fail(sql_error("TABLE_OR_VIEW_NOT_FOUND", f"카탈로그 `{cat}`를 찾을 수 없습니다."))
        if not _existsS(S, c, "table", [cat, db, name]):
            return fail(sql_error("TABLE_OR_VIEW_NOT_FOUND", f"`{cat}.{db}.{name}`을(를) 찾을 수 없습니다.", "이름 철자와 schema를 확인하세요."))
        resolved.append((t, cat, db, name, "uc"))
    for t, cat, db, name, src in resolved:
        if src == "foreign":
            continue
        need = [("USE CATALOG", f"catalog:{cat}"), ("USE SCHEMA", f"schema:{cat}.{db}"), ("SELECT", f"table:{cat}.{db}.{name}")]
        for priv, sec in need:
            if not has_priv(S, principal, priv, sec):
                return fail(sql_error("INSUFFICIENT_PERMISSIONS", f"{principal} 에게 {sec} 에 대한 {priv} 권한이 없습니다.",
                                      "부모 USE 권한과 SELECT는 별개입니다. 전체 관리자 권한 대신 최소권한을 요청하세요.", missing={"privilege": priv, "securable": sec}), "SQL_PERMISSION_DENIED")
    out["tables"] = [f"{cat}.{db}.{name}" for _, cat, db, name, _ in resolved]

    vtarget = vschema = None
    if mode == "create":
        k = st.args.get("kind")
        if k == "SCHEMA":
            cat, db = (target.catalog or CAT), target.db
            vschema = (cat, db)
            if cat != CAT and cat not in user_catalogs(S):
                return fail(sql_error("TABLE_OR_VIEW_NOT_FOUND", f"카탈로그 `{cat}`를 찾을 수 없습니다.", "SHOW CATALOGS 로 확인하거나 CREATE CATALOG 로 만드세요."))
            if "__" in (db or "") or (db or "").startswith("_"):
                return fail(sql_error("INVALID_NAME", "schema 이름에는 '__' 를 쓸 수 없습니다."))
            if not has_priv(S, principal, "USE CATALOG", f"catalog:{cat}") or not has_priv(S, principal, "CREATE SCHEMA", f"catalog:{cat}"):
                return fail(sql_error("INSUFFICIENT_PERMISSIONS", f"CREATE SCHEMA on catalog:{cat} 필요", "전체 관리자 대신 CREATE SCHEMA 최소권한 요청"), "SQL_PERMISSION_DENIED")
        else:
            cat, db, name = _tbl_parts(target)
            for priv, sec in [("USE CATALOG", f"catalog:{cat}"), ("USE SCHEMA", f"schema:{cat}.{db}"), ("CREATE TABLE", f"schema:{cat}.{db}")]:
                if not has_priv(S, principal, priv, sec):
                    return fail(sql_error("INSUFFICIENT_PERMISSIONS", f"{principal}: {sec} 에 {priv} 권한 없음", missing={"privilege": priv, "securable": sec}), "SQL_PERMISSION_DENIED")
            if cat != CAT and cat not in user_catalogs(S):
                return fail(sql_error("SIMULATOR_UNSUPPORTED", "교육 카탈로그 또는 내가 만든 catalog 에서만 생성할 수 있습니다.", "CREATE CATALOG 로 catalog 를 먼저 만드세요."))
            if not _existsS(S, c, "schema", [cat, db]):
                return fail(sql_error("SCHEMA_NOT_FOUND", f"schema `{cat}.{db}`이(가) 없습니다.", "CREATE SCHEMA 로 먼저 만드세요."))
            vtarget = (cat, db, name)
            if st.args.get("replace") and _existsS(S, c, "table", [cat, db, name]):
                sec = f"table:{cat}.{db}.{name}"
                if not (S["owners"].get(sec) == principal or has_priv(S, principal, "MODIFY", sec) or is_admin(S, principal)):
                    return fail(sql_error("INSUFFICIENT_PERMISSIONS", f"{sec} 소유자/MODIFY 권한 필요"))
    if mode in ("insert", "dml"):
        if not isinstance(target, exp.Table):
            return fail(sql_error("SIMULATOR_UNSUPPORTED", "대상 테이블을 해석할 수 없습니다."))
        cat, db, name = _tbl_parts(target)
        if (cat != CAT and cat not in user_catalogs(S)) or not _existsS(S, c, "table", [cat, db, name]):
            return fail(sql_error("TABLE_OR_VIEW_NOT_FOUND", f"`{cat}.{db}.{name}`을(를) 찾을 수 없습니다."))
        vtarget = (cat, db, name)
        for priv, sec in [("USE CATALOG", f"catalog:{cat}"), ("USE SCHEMA", f"schema:{cat}.{db}"), ("MODIFY", f"table:{cat}.{db}.{name}")]:
            if not has_priv(S, principal, priv, sec):
                return fail(sql_error("INSUFFICIENT_PERMISSIONS", f"{sec} 에 {priv} 권한 없음", missing={"privilege": priv, "securable": sec}), "SQL_PERMISSION_DENIED")

    # rewrite foreign catalog refs (AST) then transpile
    try:
        for t, cat, db, name, src in resolved:
            if src == "foreign":
                fc = S["foreign_catalogs"][cat]
                t.set("catalog", exp.to_identifier(CAT))
                t.set("db", exp.to_identifier("src_oracle"))
                t.set("this", exp.to_identifier(fc["table_map"].get(name, name)))
            elif swap and f"{cat}.{db}.{name}" in swap:
                t.set("catalog", exp.to_identifier("memory"))
                t.set("db", exp.to_identifier("main"))
                t.set("this", exp.to_identifier(swap[f"{cat}.{db}.{name}"]))
            elif cat in user_catalogs(S):
                t.set("catalog", exp.to_identifier(CAT))
                t.set("db", exp.to_identifier(f"{cat}__{db}"))
        if (vtarget or vschema) and isinstance(target, exp.Table):          # DDL/DML 대상도 물리 이름으로
            tc = (vschema or vtarget)[0]
            if tc in user_catalogs(S):
                target.set("catalog", exp.to_identifier(CAT))
                target.set("db", exp.to_identifier(f"{tc}__{(vschema or vtarget)[1]}"))
        duck = st.sql(dialect="duckdb")
    except Exception as e:
        return fail(sql_error("TRANSPILE_ERROR", f"변환 실패: {e}"))
    if mode in ("insert", "dml") and vtarget:
        try:
            _hist_ensure(S, c, ".".join(vtarget))
        except Exception:
            pass
    timer = threading.Timer(15.0, c.interrupt)
    timer.start()
    try:
        cur = c.execute(duck)
        if mode == "query":
            cols = [d[0] for d in cur.description]
            rows = cur.fetchmany(500)
            out.update(columns=cols, rows=[[_ser(v) for v in r] for r in rows], row_count=len(rows))
        else:
            if mode == "create":
                if st.args.get("kind") == "SCHEMA":
                    S["owners"][f"schema:{vschema[0]}.{vschema[1]}"] = principal
                else:
                    cat, db, name = vtarget
                    S["owners"][f"table:{cat}.{db}.{name}"] = principal
                    if st.args.get("kind") == "VIEW":
                        S["views_created_by"][f"{cat}.{db}.{name}"] = principal
            out["row_count"] = 0
            try:
                if mode in ("insert", "dml") or (mode == "create" and st.args.get("kind") == "TABLE"):
                    _c1, _d1, _n1 = vtarget
                    _fq1 = f"{_c1}.{_d1}.{_n1}"
                    _hop = S.pop("_hop", None) or {}
                    if mode == "create":
                        _op = "CREATE OR REPLACE TABLE AS SELECT" if st.args.get("replace") else ("CREATE TABLE AS SELECT" if st.args.get("expression") is not None else "CREATE TABLE")
                        if not st.args.get("replace"):
                            _thist(S).pop(_fq1, None)
                    else:
                        _op = {"Insert": "WRITE", "Update": "UPDATE", "Delete": "DELETE", "Merge": "MERGE"}.get(kind, kind.upper())
                    if not _hop.get("skip"):
                        _hist_add(S, c, _fq1, _hop.get("op") or _op, {"mode": "Append"} if kind == "Insert" else {"statement": kind}, actor_id or principal)
            except Exception:
                pass
        out["status"] = "succeeded"
    except Exception as e:
        return fail(sql_error("EXECUTION_ERROR", str(e)[:300]))
    finally:
        timer.cancel()
    audit(S, actor_id or principal, "SQL_EXECUTED", out["tables"][0] if out["tables"] else "sql", "succeeded", "LOCAL_EXECUTED",
          {"statement": kind, "rows": out.get("row_count")}, code_hash=h, trace=trace, effective=principal)
    return out


# ---------------------------------------------------------------- Delta 버전 이력(시뮬레이션) · 타임 트래블 · 쿼리 이력
_SNAP_MAX = 30
_RE_DH = re.compile(r"^\s*DESCRIBE\s+HISTORY\s+([\w.`]+)(?:\s+LIMIT\s+(\d+))?\s*;?\s*$", re.I)
_RE_RESTORE = re.compile(r"^\s*RESTORE\s+(?:TABLE\s+)?([\w.`]+)\s+TO\s+VERSION\s+AS\s+OF\s+(\d+)\s*;?\s*$", re.I)
_RE_VAO = re.compile(r"([\w.`]+)\s+VERSION\s+AS\s+OF\s+(\d+)", re.I)


def _thist(S):
    return S.setdefault("thist", {})


def _thist_invalidate(S):
    """스냅샷은 메모리 DB(memory.main)에만 있어 세션을 다시 불러오면 사라진다 → '읽기 가능' 표시를 거짓으로 두지 않는다."""
    for h in (S.get("thist") or {}).values():
        for x in h:
            x["snapshot"] = False


def hop(S, op=None, skip=False):
    """다음 run_sql 한 건의 Delta 이력 연산명을 바꾸거나(op) 기록을 건너뛴다(skip). 확장 기능(선언형 파이프라인 등)이 쓴다."""
    S["_hop"] = {"op": op, "skip": skip}


def pfq(S, fq):
    """UC 3단계 이름(가상) → DuckDB 물리 이름. 사용자가 만든 catalog(S['catalogs'])는 food_dev 안의 'catalog__schema' 스키마로 저장된다."""
    parts = fq.replace("`", "").split(".")
    if len(parts) == 3 and parts[0] in S.get("catalogs", {}):
        return f"{CAT}.{parts[0]}__{parts[1]}.{parts[2]}"
    return fq


def _snap_name(S, fq, v):
    return f"snap_{hashlib.md5((S['id'] + fq).encode()).hexdigest()[:10]}_v{v}"


def _hist_add(S, c, fq, op, params, user, rows=None):
    h = _thist(S).setdefault(fq, [])
    v = (h[-1]["version"] + 1) if h else 0
    ok = True
    try:
        c.execute(f'CREATE OR REPLACE TABLE memory.main."{_snap_name(S, fq, v)}" AS SELECT * FROM {pfq(S, fq)}')
        if rows is None:
            rows = c.execute(f"SELECT count(*) FROM {pfq(S, fq)}").fetchone()[0]
    except Exception:
        ok = False
    h.append({"version": v, "timestamp": now_utc(), "userName": user, "operation": op, "operationParameters": params, "numOutputRows": rows, "snapshot": ok})
    if len(h) > 200:
        del h[:len(h) - 200]
    if len(h) > _SNAP_MAX:
        old = h[-_SNAP_MAX - 1]
        if old.get("snapshot"):
            try:
                c.execute(f'DROP TABLE IF EXISTS memory.main."{_snap_name(S, fq, old["version"])}"')
            except Exception:
                pass
            old["snapshot"] = False


def _hist_ensure(S, c, fq):
    if fq not in _thist(S):
        _hist_add(S, c, fq, "CREATE TABLE AS SELECT", {"origin": "시드 데이터(세션 시작 상태)"}, "system")


def _is_view(c, fq, S=None):
    cat, db, name = fq.split(".")
    if S is not None:
        cat, db = _phys(S, cat, db)
    r = c.execute("select table_type from information_schema.tables where table_catalog=? and table_schema=? and table_name=?", [cat, db, name]).fetchall()
    return bool(r) and "VIEW" in str(r[0][0])


def _special(S, sql, principal, via, need_warehouse, trace, actor_id):
    """DESCRIBE HISTORY / RESTORE / VERSION AS OF. 처리하면 결과 dict, 해당 없으면 None."""
    c = _conns[S["id"]]
    from . import ext_catalog
    ext = ext_catalog.handle_sql(S, sql, principal, via, need_warehouse, trace, actor_id)
    if ext is not None:
        return ext
    m_dh, m_rs = _RE_DH.match(sql), _RE_RESTORE.match(sql)
    if m_dh or m_rs:
        m = m_dh or m_rs
        tbl = m.group(1).replace("`", "")
        probe = _run_sql(S, f"SELECT * FROM {tbl} LIMIT 0", principal, via, False, need_warehouse, trace, actor_id)
        if probe["status"] != "succeeded":
            return probe
        fq = probe["tables"][0]
        if _is_view(c, fq, S):
            probe.update(status="failed", error=sql_error("UNSUPPORTED_SQL", f"`{fq}`는 뷰입니다. DESCRIBE HISTORY/RESTORE는 Delta 테이블에만 적용됩니다."))
            return probe
        _hist_ensure(S, c, fq)
        h = _thist(S)[fq]
        if m_dh:
            n = int(m.group(2)) if m.group(2) else len(h)
            rows = [[x["version"], x["timestamp"], x["userName"], x["operation"], json.dumps(x["operationParameters"], ensure_ascii=False), x["numOutputRows"]] for x in reversed(h)][:n]
            probe.update(columns=["version", "timestamp", "userName", "operation", "operationParameters", "numOutputRows"], rows=rows, row_count=len(rows),
                         compat_notes=["Delta 버전 이력은 시뮬레이션입니다(DuckDB 스냅샷 기반). 공식 DESCRIBE HISTORY의 열 일부만 제공합니다."])
            return probe
        ver = int(m.group(2))
        ent = next((x for x in h if x["version"] == ver), None)
        if not ent or not ent.get("snapshot"):
            probe.update(status="failed", error=sql_error("EXECUTION_ERROR", f"버전 {ver}을(를) 복원할 수 없습니다(없는 버전이거나 스냅샷이 보관되지 않음).", f"DESCRIBE HISTORY {fq} 로 가능한 버전을 확인하세요."))
            return probe
        sec = f"table:{fq}"
        if not (has_priv(S, principal, "MODIFY", sec) or S["owners"].get(sec) == principal or is_admin(S, principal)):
            probe.update(status="failed", error=sql_error("INSUFFICIENT_PERMISSIONS", f"{sec} 에 MODIFY 권한 필요", missing={"privilege": "MODIFY", "securable": sec}))
            return probe
        try:
            c.execute(f'CREATE OR REPLACE TABLE {pfq(S, fq)} AS SELECT * FROM memory.main."{_snap_name(S, fq, ver)}"')
            n = c.execute(f"SELECT count(*) FROM {pfq(S, fq)}").fetchone()[0]
        except Exception as e:
            probe.update(status="failed", error=sql_error("EXECUTION_ERROR", str(e)[:300]))
            return probe
        _hist_add(S, c, fq, "RESTORE", {"version": ver}, actor_id or principal, rows=n)
        audit(S, actor_id or principal, "SQL_EXECUTED", fq, "succeeded", "LOCAL_EXECUTED", {"statement": "RESTORE", "rows": n}, effective=principal)
        probe.update(columns=["table", "restored_to_version", "new_version", "num_restored_rows"], rows=[[fq, ver, _thist(S)[fq][-1]["version"], n]], row_count=1,
                     compat_notes=["RESTORE는 시뮬레이션입니다(스냅샷으로 테이블 내용을 되돌리고 새 버전을 기록)."])
        return probe
    ms = list(_RE_VAO.finditer(sql)) if re.search(r"VERSION\s+AS\s+OF", sql, re.I) else []
    if not ms:
        return None
    swap, clean, last = {}, "", 0
    for m in ms:
        tbl = m.group(1).replace("`", "")
        ver = int(m.group(2))
        probe = _run_sql(S, f"SELECT * FROM {tbl} LIMIT 0", principal, via, False, need_warehouse, trace, actor_id)
        if probe["status"] != "succeeded":
            return probe
        fq = probe["tables"][0]
        if _is_view(c, fq, S):
            probe.update(status="failed", error=sql_error("UNSUPPORTED_SQL", f"`{fq}`는 뷰입니다. VERSION AS OF는 Delta 테이블에만 적용됩니다."))
            return probe
        _hist_ensure(S, c, fq)
        ent = next((x for x in _thist(S)[fq] if x["version"] == ver), None)
        if not ent or not ent.get("snapshot"):
            probe.update(status="failed", error=sql_error("EXECUTION_ERROR", f"`{fq}` 의 버전 {ver}을(를) 읽을 수 없습니다(없는 버전이거나 스냅샷이 보관되지 않음).", f"DESCRIBE HISTORY {fq} 로 가능한 버전을 확인하세요."))
            return probe
        if fq in swap and swap[fq] != _snap_name(S, fq, ver):
            probe.update(status="failed", error=sql_error("SIMULATOR_UNSUPPORTED", "한 쿼리에서 같은 테이블의 서로 다른 버전을 동시에 읽는 구문은 시뮬레이터 미지원입니다."))
            return probe
        swap[fq] = _snap_name(S, fq, ver)
        clean += sql[last:m.start()] + tbl
        last = m.end()
    clean += sql[last:]
    for nm in {m.group(1).replace("`", "").lower() for m in ms}:
        total = len(re.findall(r"(?<![\w.])" + re.escape(nm) + r"(?![\w])", clean, re.I))
        versioned = sum(1 for m in ms if m.group(1).replace("`", "").lower() == nm)
        if total > versioned:
            return {"status": "failed", "columns": [], "rows": [], "sql_hash": sha(sql), "evidence_level": "LOCAL_EXECUTED", "tables": [], "principal": principal, "compat_notes": [],
                    "error": sql_error("SIMULATOR_UNSUPPORTED", f"한 쿼리에서 `{nm}` 의 현재 버전과 과거 버전을 함께 읽는 구문(시점 비교 조인 등)은 시뮬레이터 미지원입니다.", "과거 버전 결과를 CREATE TABLE 로 따로 만든 뒤 비교하세요.")}
    r = _run_sql(S, clean, principal, via, False, need_warehouse, trace, actor_id, swap=swap)
    if r["status"] == "succeeded":
        r["compat_notes"] = r.get("compat_notes", []) + ["VERSION AS OF는 시뮬레이션입니다(해당 버전 시점의 스냅샷을 읽음)."]
    return r


def run_sql(S, sql, principal, via="sql_editor", system=False, need_warehouse=True, trace=None, actor_id=None):
    """_run_sql 의 겉껍질: 특수 구문(DESCRIBE HISTORY·RESTORE·VERSION AS OF) 처리 + 쿼리 이력 기록."""
    t0 = time.time()
    out = None
    if len(sql) > MAX_SQL_CHARS:
        out = {"status": "failed", "columns": [], "rows": [], "error": sql_error("SQL_TOO_LONG", f"SQL이 너무 깁니다({len(sql):,}자). 최대 {MAX_SQL_CHARS:,}자까지 실행합니다.", "여러 문장으로 나누거나 뷰를 사용하세요."), "sql_hash": sha(sql[:200]),
               "evidence_level": "LOCAL_EXECUTED", "tables": [], "principal": principal, "compat_notes": []}
        sql = sql[:2000]
    try:
        if out is None and not system:
            try:
                out = _special(S, sql, principal, via, need_warehouse, trace, actor_id)
            except Exception as e:  # pragma: no cover
                out = {"status": "failed", "columns": [], "rows": [], "error": sql_error("EXECUTION_ERROR", str(e)[:300]), "sql_hash": sha(sql), "evidence_level": "LOCAL_EXECUTED", "tables": [], "principal": principal, "compat_notes": []}
        if out is None:
            out = _run_sql(S, sql, principal, via, system, need_warehouse, trace, actor_id)
    finally:
        S.pop("_hop", None)
    if not system:
        try:
            q = S.setdefault("qh", [])
            w = (sql.strip().split() or ["?"])[0].upper()
            if w == "DESCRIBE" and _RE_DH.match(sql):
                w = "DESCRIBE HISTORY"
            w = out.pop("statement_label", None) or w
            via = out.pop("via_override", None) or via
            q.append({"id": "q_" + uuid.uuid4().hex[:10], "at": now_utc(), "scenario_clock": clock(S).isoformat(), "user": actor_id or principal, "principal": principal, "via": via,
                      "statement": w[:20], "sql": sql[:2000], "status": "FINISHED" if out["status"] == "succeeded" else "FAILED", "duration_ms": int((time.time() - t0) * 1000),
                      "rows": out.get("row_count"), "tables": out.get("tables", []), "sql_hash": out.get("sql_hash"),
                      "error": ({"code": out["error"].get("code"), "message": str(out["error"].get("message"))[:300], "hint": out["error"].get("hint"), "missing": out["error"].get("missing")} if out.get("error") else None)})
            if len(q) > 300:
                del q[:len(q) - 300]
        except Exception:
            pass
    return out


# ---------------------------------------------------------------- Add data: CSV 업로드 → 테이블 / COPY INTO 증분 적재(시뮬레이션)
_IDENT = re.compile(r"^[a-z][a-z0-9_]{0,40}$")


def _col_names(header):
    out, seen = [], set()
    for i, h in enumerate(header):
        n = re.sub(r"[^0-9a-z_]", "_", str(h).strip().lower()) or f"col{i + 1}"
        if n[0].isdigit():
            n = "c_" + n
        base, k = n, 2
        while n in seen:
            n = f"{base}_{k}"; k += 1
        seen.add(n); out.append(n)
    return out


def _infer(vals):
    vs = [v for v in vals if v != ""]
    if not vs:
        return "VARCHAR"
    def ok(f):
        try:
            for v in vs:
                f(v)
            return True
        except Exception:
            return False
    if ok(int):
        return "BIGINT"
    if ok(lambda v: (_ for _ in ()).throw(ValueError()) if not math.isfinite(float(v)) else float(v)):
        return "DOUBLE"
    if ok(lambda v: datetime.strptime(v, "%Y-%m-%d")):
        return "DATE"
    return "VARCHAR"


def add_data(S, actor, principal, schema, table, text, mode, filename, catalog=None):
    """CSV 텍스트를 테이블로 만든다. mode: create | replace | append(COPY INTO: 같은 파일은 다시 적재하지 않음)."""
    import csv, io
    c = _conns[S["id"]]
    err = lambda code, msg, hint=None, **kw: {"status": "failed", "error": sql_error(code, msg, hint, **kw)}
    schema, table = (schema or "").strip().lower(), (table or "").strip().lower()
    if not _IDENT.match(schema) or not _IDENT.match(table):
        return err("INVALID_NAME", "schema/테이블 이름은 영문 소문자로 시작하고 영문 소문자·숫자·_ 만 쓸 수 있습니다(최대 41자).")
    if mode not in ("create", "replace", "append"):
        return err("INVALID_MODE", "mode는 create, replace, append 중 하나입니다.")
    if len(text.encode("utf-8")) > 200_000:
        return err("FILE_TOO_LARGE", "시뮬레이터는 200KB 이하 CSV만 받습니다.")
    rows = list(csv.reader(io.StringIO(text.strip("\ufeff\r\n "))))
    if len(rows) < 2:
        return err("EMPTY_FILE", "머리글과 데이터가 1행 이상 필요합니다.")
    header, data = _col_names(rows[0]), rows[1:]
    if len(header) > 30 or len(data) > 2000:
        return err("FILE_TOO_LARGE", "최대 30열·2,000행까지 받습니다.")
    if any(len(r) != len(header) for r in data):
        bad = next(i for i, r in enumerate(data, 2) if len(r) != len(header))
        return err("MALFORMED_CSV", f"{bad}행의 열 수가 머리글({len(header)}열)과 다릅니다.", "쉼표가 들어간 값은 큰따옴표로 감싸세요.")
    cat = (catalog or CAT).strip().lower()
    if cat != CAT and cat not in user_catalogs(S):
        return err("TABLE_OR_VIEW_NOT_FOUND", f"catalog `{cat}`을(를) 찾을 수 없습니다.", "SHOW CATALOGS 로 확인하거나 CREATE CATALOG 로 만드세요.")
    sec_s, fq = f"schema:{cat}.{schema}", f"{cat}.{schema}.{table}"
    if not _existsS(S, c, "schema", [cat, schema]):
        return err("SCHEMA_NOT_FOUND", f"schema `{cat}.{schema}`이(가) 없습니다.", "SQL Editor에서 CREATE SCHEMA 하거나 기존 schema를 고르세요.")
    for priv, sec in [("USE CATALOG", f"catalog:{cat}"), ("USE SCHEMA", sec_s), ("CREATE TABLE", sec_s)]:
        if not has_priv(S, principal, priv, sec):
            return err("INSUFFICIENT_PERMISSIONS", f"{principal}: {sec} 에 {priv} 권한 없음", "권한 요청 화면에서 최소 권한을 요청하세요.", missing={"privilege": priv, "securable": sec})
    exists = _existsS(S, c, "table", [cat, schema, table])
    sec_t = f"table:{fq}"
    if exists and mode == "create":
        return err("TABLE_ALREADY_EXISTS", f"`{fq}`이(가) 이미 있습니다.", "덮어쓰기(replace) 또는 COPY INTO 증분 추가(append)를 고르세요.")
    if exists and not (S["owners"].get(sec_t) == principal or has_priv(S, principal, "MODIFY", sec_t) or is_admin(S, principal)):
        return err("INSUFFICIENT_PERMISSIONS", f"{sec_t} 소유자/MODIFY 권한 필요", missing={"privilege": "MODIFY", "securable": sec_t})
    if mode == "append" and not exists:
        return err("TABLE_OR_VIEW_NOT_FOUND", f"`{fq}`이(가) 없어 추가할 수 없습니다.", "먼저 create로 만드세요.")
    sha_ = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    loaded = S.setdefault("loaded_files", {}).setdefault(fq, [])
    skipped = False
    if mode == "append":
        if sha_ in loaded:
            skipped = True
        else:
            cols = [r[0] for r in c.execute(f"DESCRIBE {pfq(S, fq)}").fetchall()]
            if cols != header:
                return err("SCHEMA_MISMATCH", f"파일의 열({', '.join(header)})이 테이블의 열({', '.join(cols)})과 다릅니다.", "열 이름과 순서를 맞추세요(실제 COPY INTO는 mergeSchema 옵션으로 확장할 수 있습니다).")
    types = [_infer([r[i] for r in data]) for i in range(len(header))]

    def conv(v, t):
        if v == "":
            return None
        return int(v) if t == "BIGINT" else float(v) if t == "DOUBLE" else v

    if mode == "replace" and exists:
        _hist_ensure(S, c, fq)                              # 덮어쓰기 전 현재 상태를 버전으로 남긴다(이력은 이어서 증가)
    old_loaded = list(loaded)
    try:
        c.execute("BEGIN TRANSACTION")
        if mode in ("create", "replace"):
            c.execute(f"DROP TABLE IF EXISTS {pfq(S, fq)}") if mode == "replace" else None
            c.execute(f"CREATE TABLE {pfq(S, fq)} ({', '.join(f'\"{h}\" {t}' for h, t in zip(header, types))})")
            loaded.clear()
            S["owners"][sec_t] = S["owners"].get(sec_t) or principal
        if not skipped:
            ph = ", ".join("?" for _ in header)
            if mode == "append":
                tys = [r[1] for r in c.execute(f"DESCRIBE {pfq(S, fq)}").fetchall()]
                types = ["BIGINT" if "INT" in t else "DOUBLE" if t in ("DOUBLE", "FLOAT") else "DATE" if t == "DATE" else "VARCHAR" for t in tys]
            c.executemany(f"INSERT INTO {pfq(S, fq)} VALUES ({ph})", [[conv(v, t) for v, t in zip(r, types)] for r in data])
            loaded.append(sha_)
        c.execute("COMMIT")
    except Exception as e:
        try:
            c.execute("ROLLBACK")
        except Exception:
            pass
        loaded[:] = old_loaded
        return err("EXECUTION_ERROR", str(e)[:300], "숫자 열에 숫자가 아닌 값이 섞였는지 확인하세요(실패해도 기존 테이블은 그대로 유지됩니다).")
    if _is_view(c, fq, S):
        pass
    op = {"create": "CREATE TABLE", "replace": "CREATE OR REPLACE TABLE", "append": "COPY INTO"}[mode]
    if mode == "create":
        _thist(S).pop(fq, None)
    if not skipped:
        _hist_add(S, c, fq, op, {"file": (filename or "upload.csv")[:60], "format": "CSV", "sha": sha_, "rows": len(data)}, actor["user_id"])
    total = c.execute(f"SELECT count(*) FROM {pfq(S, fq)}").fetchone()[0]
    audit(S, actor["user_id"], "FILE_UPLOAD_TABLE", fq, "skipped" if skipped else "succeeded", "LOCAL_EXECUTED", {"mode": mode, "rows": len(data), "file_sha": sha_}, effective=principal)
    S.setdefault("qh", []).append({"id": "q_" + uuid.uuid4().hex[:10], "at": now_utc(), "scenario_clock": clock(S).isoformat(), "user": actor["user_id"], "principal": principal, "via": "add_data",
                                  "statement": "COPY INTO" if mode == "append" else "CREATE TABLE", "sql": f"-- Add data: {filename or 'upload.csv'} → {fq} ({mode})", "status": "FINISHED", "duration_ms": 0,
                                  "rows": 0 if skipped else len(data), "tables": [fq], "sql_hash": sha_, "error": None})
    return {"status": "succeeded", "table": fq, "mode": mode, "skipped": skipped, "rows_loaded": 0 if skipped else len(data), "rows_total": total,
            "columns": [{"name": h, "type": t} for h, t in zip(header, types)],
            "note": ("같은 내용의 파일이 이미 적재되어 건너뛰었습니다(COPY INTO는 멱등합니다)." if skipped else "적재했습니다.")}


def _grant_sec(st):
    sec_kind = str(st.args.get("kind") or "TABLE").lower()
    sn = st.args["securable"]
    parts = [x for x in [sn.catalog, sn.db, sn.name] if x]
    if sec_kind == "catalog":
        return f"catalog:{sn.name}"
    if sec_kind == "schema":
        return f"schema:{sn.db or CAT}.{sn.name}"
    return "table:" + ".".join(parts)


def _grant(S, st, kind, principal, out, fail, h, actor_id):
    try:
        _owner_ok = any(S["owners"].get(x) == principal for x in sec_chain(_grant_sec(st)))
    except Exception:
        _owner_ok = False
    if not is_admin(S, principal) and not _owner_ok:
        audit(S, actor_id or principal, "FORBIDDEN_SELF_GRANT_ATTEMPT", "grant", "blocked", "SIMULATED", {"stmt": kind}, code_hash=h, effective=principal)
        milestone(S, "self_grant_attempt")
        return fail(sql_error("INSUFFICIENT_PERMISSIONS", "GRANT/REVOKE는 소유자·MANAGE·관리자만 수행합니다. 권한 요청 티켓(UI-15)을 제출하세요.", "자기 권한 부여 시도는 금지 이벤트로 기록됩니다."), "SQL_PERMISSION_DENIED")
    privs = [p.this.name if hasattr(p.this, "name") else str(p.this) for p in st.args["privileges"]]
    sec_kind = str(st.args.get("kind") or "TABLE").lower()
    sn = st.args["securable"]
    parts = [x for x in [sn.catalog, sn.db, sn.name] if x]
    if sec_kind == "catalog":
        sec = f"catalog:{sn.name}"
    elif sec_kind == "schema":
        sec = f"schema:{sn.db or CAT}.{sn.name}" if sn.db else f"schema:{CAT}.{sn.name}"
    else:
        sec = "table:" + ".".join(parts)
    for pr in st.args["principals"]:
        who = pr.this.name if hasattr(pr.this, "name") else str(pr.this)
        for p in privs:
            if kind == "Grant":
                S["grants"].append([who, p.upper(), sec])
            else:
                S["grants"] = [g for g in S["grants"] if not (g[0] == who and g[1] == p.upper() and g[2] == sec)]
    out["status"] = "succeeded"
    audit(S, actor_id or principal, f"UC_{kind.upper()}", sec, "succeeded", "LOCAL_EXECUTED", {"privileges": privs}, code_hash=h, effective=principal)
    return out


# ---------------------------------------------------------------- tickets (permission requests)
def create_ticket(S, actor, privilege, securable, reason, grantee=None):
    if not reason or len(reason.strip()) < 5:
        raise ApiError(400, "REASON_REQUIRED", "사유를 구체적으로 작성하세요.")
    privilege = privilege.upper().strip()
    over = privilege in ("ALL PRIVILEGES", "ALL", "METASTORE ADMIN", "ACCOUNT ADMIN") or securable.strip().lower() in ("metastore", "account")
    t = {"ticket_id": nid(S, "T"), "requester": actor["user_id"], "grantee": grantee or TRAINEE, "privilege": privilege,
         "securable": securable.strip(), "reason": reason.strip(), "status": "OPEN", "over_broad": over, "created_rev": S["revision"]}
    S["tickets"].append(t)
    audit(S, actor["user_id"], "PERMISSION_REQUEST", securable, "open", "SIMULATED", {"privilege": privilege, "over_broad": over})
    milestone(S, "ticket_created")
    if over:
        milestone(S, "over_broad_request")
    return t


SEC_RE = re.compile(r"^(catalog:[\w]+|schema:[\w]+\.[\w]+|table:[\w]+\.[\w]+\.[\w]+|connection:[\w]+|metastore:[\w]+)$")


def resolve_ticket(S, actor, ticket_id, decision, note=""):
    if actor["role"] not in ("admin", "instructor"):
        raise ApiError(403, "FORBIDDEN", "권한 요청 처리는 관리자/강사 역할만 가능합니다.")
    t = next((x for x in S["tickets"] if x["ticket_id"] == ticket_id), None)
    if not t or t["status"] != "OPEN":
        raise ApiError(404, "TICKET_NOT_FOUND", ticket_id)
    if decision == "approve":
        if t["over_broad"]:
            raise ApiError(409, "OVER_BROAD", "과도한 권한 요청입니다. 최소권한으로 다시 요청하도록 반려하세요.")
        if not SEC_RE.match(t["securable"]):
            raise ApiError(400, "BAD_SECURABLE", "securable 형식: catalog:x | schema:c.s | table:c.s.t | connection:name")
        S["grants"].append([t["grantee"], t["privilege"], t["securable"]])
        t["status"] = "APPROVED"
        milestone(S, "ticket_resolved")
        if actor["role"] == "instructor":
            S["admin_assisted"] += 1
    else:
        t["status"] = "REJECTED"
    t["resolved_by"], t["note"] = actor["user_id"], note
    audit(S, actor["user_id"], "PERMISSION_REQUEST_RESOLVED", t["securable"], t["status"], "SIMULATED", {"privilege": t["privilege"], "grantee": t["grantee"]})
    return t


# ---------------------------------------------------------------- order change domain
def q1(S, sql, params=None):
    c = _conns[S["id"]]
    return c.execute(sql, params or []).fetchall()


def order_facts(S, order_id, requested_total):
    rows = q1(S, f"SELECT o.order_id,o.customer_id,o.version,o.route_id,o.status FROM {CAT}.silver.orders o WHERE o.order_id=?", [order_id])
    if not rows:
        raise ApiError(404, "ORDER_NOT_FOUND", order_id)
    _, cust, ver, route, status = rows[0]
    line = q1(S, f"SELECT product_id, SUM(qty_boxes) FROM {CAT}.silver.order_lines WHERE order_id=? AND line_no=1 GROUP BY product_id", [order_id])
    pid, cur = line[0][0], int(line[0][1])
    # available inventory is read from the learner-owned gold view (contract-checked separately)
    try:
        av = q1(S, f"SELECT COALESCE(SUM(available_qty),0) FROM {CAT}.gold.v_available_inventory WHERE product_id=?", [pid])
        available = int(av[0][0])
        view_err = None
    except Exception as e:
        available, view_err = 0, str(e)[:120]
    credit = bool(q1(S, f"SELECT credit_blocked FROM {CAT}.silver.customers WHERE customer_id=?", [cust])[0][0])
    exc = bool(q1(S, f"SELECT exception_cutoff FROM {CAT}.silver.customer_contracts WHERE customer_id=?", [cust])[0][0])
    route_open = bool(q1(S, f"SELECT is_open FROM {CAT}.silver.delivery_routes WHERE route_id=?", [route])[0][0])
    subs = [{"substitute_id": r[0]} for r in q1(S, f"SELECT substitute_id FROM {CAT}.silver.product_substitutes WHERE product_id=? AND unit_match", [pid])]
    cutoff_hhmm = "15:00"
    now = clock(S)
    after_cutoff = (now.hour, now.minute) > (15, 0)
    return {"order_id": order_id, "customer_id": cust, "order_version": ver, "route_id": route, "product_id": pid, "current_qty": cur,
            "requested_total": requested_total, "available_qty": available, "credit_blocked": credit, "exception_contract": exc,
            "route_open": route_open, "after_cutoff": after_cutoff, "cutoff": cutoff_hhmm, "substitutes": subs, "view_error": view_err}


def extra_gap(current, requested, free):
    if min(current, requested, free) < 0:
        raise ApiError(400, "NEGATIVE_QTY", "수량은 0 이상이어야 합니다")
    return max(max(requested - current, 0) - free, 0)


def policy_decide(f, rule=None):
    """Pure function: facts -> decision. Used by orders, policy tests and the 40-case eval set."""
    rule = rule or {"requires_approval": True, "prohibited_if": ["customer_credit_blocked", "delivery_route_closed"]}
    additional = max(f["requested_total"] - f["current_qty"], 0)
    gap = max(additional - f["available_qty"], 0)
    res = {"additional": additional, "shortage": gap, "alternatives": [], "decision": None, "reasons": []}
    if f["credit_blocked"] and "customer_credit_blocked" in rule["prohibited_if"]:
        res.update(decision="PROHIBITED"); res["reasons"].append("여신 차단: 자동 실행/제안 금지"); return res
    if not f["route_open"]:
        res.update(decision="ESCALATE" if "delivery_route_closed" in rule["prohibited_if"] else "REQUIRES_APPROVAL")
        res["reasons"].append("배송 노선 마감: 담당자 이관"); return res
    if f["after_cutoff"] and not f["exception_contract"]:
        res.update(decision="ESCALATE"); res["reasons"].append("마감 이후이고 예외계약 없음: 이관"); return res
    if gap > 0:
        res["decision"] = "REQUIRES_APPROVAL"
        res["reasons"].append(f"원안 즉시 실행 불가: 추가 필요 {additional}, 가용 {f['available_qty']}, 추가 부족 {gap}")
        res["alternatives"].append({"type": "INCREASE_WITHIN_AVAILABLE", "new_total": f["current_qty"] + f["available_qty"], "label": f"가용재고 범위 증량({f['current_qty'] + f['available_qty']}박스)"})
        for s in f["substitutes"]:
            res["alternatives"].append({"type": "SUBSTITUTE", "substitute_id": s["substitute_id"], "qty": gap, "new_total": f["current_qty"] + f["available_qty"], "label": f"가용분 {f['current_qty'] + f['available_qty']}박스 + 대체 {s['substitute_id']} {gap}박스(단위 일치)"})
        return res
    res["decision"] = "REQUIRES_APPROVAL" if (rule.get("requires_approval") and (f["after_cutoff"] or True)) else "AUTO_OK"
    res["reasons"].append("가용재고 충분하나 마감 이후 변경: 승인 필요" if f["after_cutoff"] else "승인 정책 적용")
    res["alternatives"].append({"type": "AS_REQUESTED", "new_total": f["requested_total"], "label": f"원안({f['requested_total']}박스)"})
    return res


def active_rule(S):
    return S["policy"]["versions"][str(S["policy"]["active"])]


def order_propose(S, actor, order_id, requested_total, alt_index=0):
    f = order_facts(S, order_id, int(requested_total))
    if f["view_error"]:
        raise ApiError(409, "GOLD_VIEW_BROKEN", f"gold.v_available_inventory 조회 실패: {f['view_error']}")
    d = policy_decide(f, active_rule(S))
    audit(S, actor["user_id"], "POLICY_EVALUATED", order_id, d["decision"], "LOCAL_EXECUTED", {"facts": {k: f[k] for k in ("available_qty", "current_qty", "requested_total")}, "shortage": d["shortage"]}, effective=TRAINEE)
    if d["decision"] in ("PROHIBITED", "ESCALATE"):
        return {"facts": f, "policy": d, "proposal": None}
    if not d["alternatives"]:
        return {"facts": f, "policy": d, "proposal": None}
    alt = d["alternatives"][min(alt_index, len(d["alternatives"]) - 1)]
    payload = {"order_id": order_id, "product_id": f["product_id"], "new_qty": alt["new_total"], "alternative": alt["type"],
               "order_version": f["order_version"], "policy_version": S["policy"]["active"], "available_snapshot": f["available_qty"]}
    if alt.get("substitute_id"):
        payload["substitute_id"], payload["substitute_qty"] = alt["substitute_id"], alt["qty"]
    pid = nid(S, "PR")
    prop = {"proposal_id": pid, "payload": payload, "payload_hash": sha(payload), "status": "PENDING", "proposer": actor["user_id"],
            "created_clock": clock(S).isoformat(), "expires_clock": (clock(S) + timedelta(minutes=30)).isoformat(), "decision": d["decision"], "alt": alt}
    S["proposals"][pid] = prop
    audit(S, actor["user_id"], "PROPOSAL_CREATED", pid, "pending", "LOCAL_EXECUTED", {"hash": prop["payload_hash"], "new_qty": alt["new_total"]}, code_hash=prop["payload_hash"])
    milestone(S, "proposal_made")
    if d["shortage"] == 3:
        milestone(S, "shortage_3_found")
    return {"facts": f, "policy": d, "proposal": prop}


def approve(S, actor, proposal_id, payload_hash):
    if actor["role"] not in ("reviewer", "instructor", "admin"):
        audit(S, actor["user_id"], "APPROVAL_DENIED_ROLE", proposal_id, "blocked", "SIMULATED", {})
        raise ApiError(403, "FORBIDDEN", "승인은 리뷰어/강사 역할만 가능합니다(요청자·승인자 분리).")
    p = S["proposals"].get(proposal_id)
    if not p:
        raise ApiError(404, "PROPOSAL_NOT_FOUND", proposal_id)
    if payload_hash != sha(p["payload"]) or payload_hash != p["payload_hash"]:
        audit(S, actor["user_id"], "APPROVAL_PAYLOAD_TAMPER", proposal_id, "blocked", "SIMULATED", {})
        milestone(S, "tamper_blocked")
        raise ApiError(400, "PAYLOAD_HASH_MISMATCH", "승인 대상 payload hash가 제안과 다릅니다(변조 의심).")
    if clock(S) > datetime.fromisoformat(p["expires_clock"]):
        raise ApiError(409, "PROPOSAL_EXPIRED", "제안이 만료되었습니다. 새 제안이 필요합니다.")
    cur_ver = q1(S, f"SELECT version FROM {CAT}.silver.orders WHERE order_id=?", [p["payload"]["order_id"]])[0][0]
    if cur_ver != p["payload"]["order_version"]:
        raise ApiError(409, "ORDER_VERSION_CONFLICT", f"주문 버전이 변경됨(제안 {p['payload']['order_version']} → 현재 {cur_ver}). 재조회·새 제안 필요.")
    if p["payload"]["policy_version"] != S["policy"]["active"]:
        raise ApiError(409, "POLICY_VERSION_CHANGED", "정책 버전이 바뀌었습니다. 새 제안이 필요합니다.")
    aid = nid(S, "AP")
    ap = {"approval_id": aid, "proposal_id": proposal_id, "approver": actor["user_id"], "approver_role": actor["role"],
          "payload_hash": payload_hash, "order_version": cur_ver, "expires_clock": p["expires_clock"], "policy_version": p["payload"]["policy_version"], "status": "APPROVED"}
    S["approvals"][aid] = ap
    p["status"] = "APPROVED"
    audit(S, actor["user_id"], "APPROVAL_GRANTED", aid, "approved", "SIMULATED", {"proposal": proposal_id}, code_hash=payload_hash)
    milestone(S, "approved")
    return ap


def ax_execute(S, actor, order_id, body):
    """Virtual customer API (only mutates the session store)."""
    key = body.get("idempotency_key")
    if not key:
        raise ApiError(400, "IDEMPOTENCY_KEY_REQUIRED", "idempotency_key 필수")
    if key in S["ax_idem"]:
        r = copy.deepcopy(S["ax_idem"][key]); r["replayed"] = True
        audit(S, actor["user_id"], "AX_IDEMPOTENT_REPLAY", order_id, "replayed", "SIMULATED", {"key": key})
        milestone(S, "idem_replayed")
        return r
    payload = body.get("payload") or {}
    ap = S["approvals"].get(body.get("approval_id") or "")
    if not ap:
        audit(S, actor["user_id"], "AX_BLOCKED_NO_APPROVAL", order_id, "blocked", "SIMULATED", {})
        milestone(S, "ax_no_approval_blocked")
        raise ApiError(403, "NO_APPROVAL", "유효한 승인 없이 주문을 변경할 수 없습니다.")
    if sha(payload) != ap["payload_hash"]:
        audit(S, actor["user_id"], "AX_BLOCKED_PAYLOAD_TAMPER", order_id, "blocked", "SIMULATED", {"approval": ap["approval_id"]})
        milestone(S, "tamper_blocked")
        raise ApiError(400, "PAYLOAD_TAMPERED", "요청 payload가 승인된 내용과 다릅니다.")
    if ap["status"] != "APPROVED":
        raise ApiError(409, "APPROVAL_NOT_USABLE", f"승인 상태: {ap['status']}")
    if clock(S) > datetime.fromisoformat(ap["expires_clock"]):
        ap["status"] = "EXPIRED"
        audit(S, actor["user_id"], "AX_BLOCKED_EXPIRED", order_id, "blocked", "SIMULATED", {})
        milestone(S, "approval_expired_seen")
        raise ApiError(409, "APPROVAL_EXPIRED", "승인이 만료되었습니다. 재조회·새 제안·재승인이 필요합니다.")
    cur_ver = q1(S, f"SELECT version FROM {CAT}.silver.orders WHERE order_id=?", [order_id])[0][0]
    if cur_ver != body.get("expected_version") or cur_ver != ap["order_version"]:
        audit(S, actor["user_id"], "AX_VERSION_CONFLICT", order_id, "conflict", "SIMULATED", {"current": cur_ver})
        milestone(S, "version_conflict_seen")
        raise ApiError(409, "VERSION_CONFLICT", f"주문 버전 충돌(현재 {cur_ver}). 재조회 → 새 제안 → 재승인 필요.")
    f = order_facts(S, order_id, payload["new_qty"])
    if f["available_qty"] != payload["available_snapshot"]:
        audit(S, actor["user_id"], "AX_REVALIDATION_FAILED", order_id, "conflict", "SIMULATED", {"snapshot": payload["available_snapshot"], "now": f["available_qty"]})
        milestone(S, "inventory_changed_seen")
        raise ApiError(409, "INVENTORY_CHANGED", f"승인 이후 가용재고 변경({payload['available_snapshot']}→{f['available_qty']}). 재검증 실패, 새 제안 필요.")
    if payload["new_qty"] - f["current_qty"] > f["available_qty"]:
        raise ApiError(409, "INSUFFICIENT_STOCK", "가용재고 부족")
    old = f["current_qty"]
    c = _conns[S["id"]]
    c.execute(f"UPDATE {CAT}.silver.order_lines SET qty_boxes=? WHERE order_id=? AND line_no=1", [payload["new_qty"], order_id])
    if payload.get("substitute_id"):
        c.execute(f"INSERT INTO {CAT}.silver.order_lines VALUES (?,?,?,?,?,?,?)", [order_id, 4, payload["substitute_id"], payload["substitute_qty"], "SALE", 0, 0])
    c.execute(f"UPDATE {CAT}.silver.orders SET version=version+1 WHERE order_id=?", [order_id])
    aid = nid(S, "ACT")
    c.execute(f"INSERT INTO {CAT}.silver.action_audit VALUES (?,?,?,?,?,?,?)", [aid, order_id, old, payload["new_qty"], ap["approval_id"], key, "APPLIED"])
    ap["status"] = "CONSUMED"
    after = q1(S, f"SELECT SUM(qty_boxes) FROM {CAT}.silver.order_lines WHERE order_id=? AND line_no=1", [order_id])[0][0]
    recon = "OK" if after == payload["new_qty"] else "확인 필요"
    res = {"action_id": aid, "order_id": order_id, "old_qty": old, "new_qty": payload["new_qty"], "new_version": cur_ver + 1,
           "post_reconciliation": recon, "profile": S["profile_id"], "policy_version": S["policy"]["active"], "replayed": False}
    S["ax_idem"][key] = res
    audit(S, actor["user_id"], "AX_ORDER_CHANGED", order_id, "applied", "SIMULATED", {"old": old, "new": payload["new_qty"], "post": recon}, code_hash=ap["payload_hash"])
    milestone(S, "ax_executed")
    return res


# ---------------------------------------------------------------- contracts / reconciliation
def contract_check(S):
    """Compare gold.v_available_inventory against the data contract using an exact reference query."""
    c = _conns[S["id"]]
    try:
        got = dict(c.execute(f"SELECT product_id, SUM(available_qty) FROM {CAT}.gold.v_available_inventory GROUP BY 1").fetchall())
    except Exception as e:
        return {"ok": False, "error": str(e)[:120]}
    ref = dict(c.execute(f"SELECT product_id, SUM(on_hand_qty - reserved_qty - damaged_qty) FROM {CAT}.silver.inventory GROUP BY 1").fetchall())
    bad = [k for k in ref if got.get(k) != ref[k]]
    ok = not bad and len(got) == len(ref)
    if ok:
        milestone(S, "view_fixed"); milestone(S, "recon_ok")
    return {"ok": ok, "mismatch_products": len(bad), "sample": bad[:5], "case_product_available": got.get(S["case"]["product"]), "contract": "available_qty = SUM(on_hand_qty - reserved_qty - damaged_qty)"}


def data_digest(S):
    c = _conns[S["id"]]
    parts = [c.execute(f"SELECT order_id,version FROM {CAT}.silver.orders ORDER BY 1").fetchall(),
             c.execute(f"SELECT order_id,line_no,qty_boxes FROM {CAT}.silver.order_lines ORDER BY 1,2").fetchall(),
             c.execute(f"SELECT product_id, SUM(on_hand_qty-reserved_qty-damaged_qty) FROM {CAT}.silver.inventory GROUP BY 1 ORDER BY 1").fetchall()]
    return sha([[list(map(_ser, r)) for r in p] for p in parts])


# ---------------------------------------------------------------- 비용(가상): 단가 출처·기준일이 있을 때만 금액 환산
USAGE_WEIGHT = {"sql_runs": 1, "pipeline_runs": 5, "job_runs": 3, "genie_queries": 1}


def usage_units(S):
    u = {"sql_runs": sum(1 for e in S["executions"].values() if e["type"] == "sql.execute"), "pipeline_runs": sum(len(p["history"]) for p in S["pipelines"].values()),
         "job_runs": sum(len(j["runs"]) for j in S["jobs"].values()), "genie_queries": len(S["genie"]["history"])}
    return u, sum(USAGE_WEIGHT[k] * v for k, v in u.items())


def cost_view(S):
    u, units = usage_units(S)
    prof = S.get("price_profile")
    out = {"usage": u, "usage_index_units": units, "weights": USAGE_WEIGHT, "unit": "교육용 사용량 단위(DBU 아님)", "estimate": None, "profile": prof,
           "components_note": "실제 청구는 DBU·클라우드 인프라·모델 호출·데이터 전송료로 구분되며 이 화면은 실제 청구액이 아닙니다."}
    if prof:
        out["estimate"] = {"amount": round(units * prof["unit_price"], 4), "currency": prof["currency"], "basis": f"단가 {prof['unit_price']} x {units} (출처 {prof['source']}, 기준일 {prof['as_of']})"}
    else:
        out["note"] = "단가 출처·기준일이 등록되지 않아 사용량 지수만 표시합니다(실가격을 기본값으로 쓰지 않음)."
    return out


def cost_set_profile(S, p):
    for k in ("unit_price", "currency", "source", "as_of"):
        if p.get(k) in (None, ""):
            raise ApiError(400, "PRICE_PROFILE_INCOMPLETE", f"단가 프로필에는 {k} 필요(출처·기준일 없는 단가는 사용 금지)")
    try:
        up = float(p["unit_price"])
    except Exception:
        raise ApiError(400, "BAD_PRICE", "unit_price 숫자")
    if up < 0:
        raise ApiError(400, "BAD_PRICE", "0 이상")
    S["price_profile"] = {"unit_price": up, "currency": str(p["currency"])[:8], "source": str(p["source"])[:200], "as_of": str(p["as_of"])[:20]}
    return cost_view(S)


# ---------------------------------------------------------------- CDC 재생(교육용)
def cdc_next_batch(S):
    c = _conns[S["id"]]
    if S.get("cdc_batch", 1) >= 2:
        return {"already_loaded": True, "batch": 2}
    c.execute(f"INSERT INTO {CAT}.bronze.cdc_events SELECT * FROM {CAT}.bronze.cdc_events_next")
    c.execute(f"DELETE FROM {CAT}.bronze.cdc_events_next")
    S["cdc_batch"] = 2
    milestone(S, "cdc_batch2_arrived")
    audit(S, "system", "CDC_BATCH_ARRIVED", "bronze.cdc_events", "ok", "SIMULATED", {"note": "교육용 CDC 재생 — 실제 Lakeflow 커넥터 실행과 별개"})
    return {"batch": 2, "note": "새 이벤트가 도착했습니다(중복·seq 누락 포함). 멱등하게 다시 적용하세요.", "evidence_level": "SIMULATED"}


def cdc_check(S):
    """learner의 silver.customers_cdc(customer_id, city) 를 시드 기준 기대 상태와 대조. 기대 행 자체는 공개하지 않고 불일치 건수·키만 알려준다."""
    key = seedmod.answer_key()
    batch = S.get("cdc_batch", 1)
    exp = key["cdc_expected_final"] if batch >= 2 else key["cdc_expected_batch1"]
    c = _conns[S["id"]]
    try:
        rows = c.execute(f"SELECT customer_id, city FROM {CAT}.silver.customers_cdc").fetchall()
        got = dict(rows)
        dup = sorted({k for k, _ in rows if sum(1 for r in rows if r[0] == k) > 1})
    except Exception as e:
        return {"ok": False, "batch": batch, "error": "silver.customers_cdc 테이블을 먼저 만드세요(" + str(e)[:80] + ")", "evidence_level": "LOCAL_EXECUTED"}
    wrong = sorted(set(k for k in exp if got.get(k) != exp[k]) | set(dup))
    extra = sorted(k for k in got if k not in exp)
    ok = not wrong and not extra and not dup
    if ok:
        milestone(S, "cdc_batch2_ok" if batch >= 2 else "cdc_batch1_ok")
    return {"ok": ok, "batch": batch, "expected_rows": len(exp), "got_rows": len(got), "wrong_or_missing_keys": wrong, "unexpected_keys": extra, "duplicate_keys": dup,
            "hints": ["중복 event_id는 한 번만", "seq 기준 최신 이벤트만(도착 순서 아님)", "op='D'는 삭제", "재삽입(I)은 다시 존재"] if not ok else [],
            "evidence_level": "LOCAL_EXECUTED", "note": "교육용 CDC 재생이며 실제 Lakeflow 커넥터 실행과 별개입니다."}


# ---------------------------------------------------------------- notebook
def nb_cmd(S, actor, payload, principal):
    nb = S["notebook"]
    a = payload.get("action")
    if a == "add_cell":
        nb["edit_counter"] += 1
        cid = "c" + str(len(nb["cells"]) + 1)
        nb["cells"].append({"id": cid, "lang": payload.get("lang", "sql"), "code": payload.get("code", ""), "status": "idle", "exec_order": None, "ran_at_rev": None, "edit_rev": nb["edit_counter"], "output": None})
        return "ok", {"cell_id": cid}
    cell = next((x for x in nb["cells"] if x["id"] == payload.get("cell_id")), None)
    if a == "restart":
        nb["vars"] = {}; nb["restarts"] += 1
        for x in nb["cells"]:
            x["status"] = "idle"; x["exec_order"] = None; x["output"] = None
        milestone(S, "notebook_restart")
        return "ok", {"vars": {}, "note": "메모리 변수 초기화. 영속 테이블은 유지됩니다."}
    if not cell:
        return "failed", {"error": sql_error("CELL_NOT_FOUND", "cell_id")}
    if a == "edit":
        nb["edit_counter"] += 1
        cell["code"] = payload.get("code", ""); cell["edit_rev"] = nb["edit_counter"]
        stale = [x["id"] for x in nb["cells"] if nb_stale(nb, x)]
        if stale:
            milestone(S, "notebook_stale_seen")
        return "ok", {"stale": stale}
    if a == "run":
        nb["exec_counter"] += 1
        cell["exec_order"] = nb["exec_counter"]; cell["ran_at_rev"] = nb["edit_counter"]; cell["code_hash"] = sha(cell["code"])
        if cell["lang"] == "python":
            cell["status"] = "failed"
            cell["output"] = {"error": sql_error("PYTHON_ISOLATION_NOT_CONFIGURED", "이 배포에는 Python 격리 실행기(비루트·네트워크 차단·세션 볼륨·자원 제한)가 구성되어 있지 않아 Python 셀 실행을 차단합니다. 가짜 spark 객체로 흉내 내지 않습니다.", "AT-16은 격리 실행기 구성 후에만 통과로 표시됩니다.")}
            return "failed", cell["output"]
        r = run_sql(S, cell["code"], principal, via="notebook", actor_id=actor["user_id"])
        cell["status"] = "ok" if r["status"] == "succeeded" else "failed"
        cell["output"] = {k: r[k] for k in ("columns", "rows", "error", "sql_hash")}
        m = re.match(r"\s*--\s*as:\s*(\w+)", cell["code"])
        if m and r["status"] == "succeeded":
            nb["vars"][m.group(1)] = {"rows": len(r["rows"]), "first": r["rows"][0] if r["rows"] else None}
        return ("ok" if r["status"] == "succeeded" else "failed"), cell["output"]
    return "failed", {"error": sql_error("BAD_ACTION", a)}


def nb_stale(nb, cell):
    if cell["exec_order"] is None:
        return False
    for x in nb["cells"]:
        if x is cell:
            break
        if x["edit_rev"] > cell["ran_at_rev"]:
            return True
    return cell["edit_rev"] > cell["ran_at_rev"]


def nb_view(S):
    nb = copy.deepcopy(S["notebook"])
    for x in nb["cells"]:
        x["stale"] = nb_stale(S["notebook"], next(y for y in S["notebook"]["cells"] if y["id"] == x["id"]))
    return nb


# ---------------------------------------------------------------- connections
FAULT_DIAG = {
    "net_unreachable": ("NETWORK", "DNS/네트워크 불통", "네트워크/방화벽·PrivateLink 담당(고객 인프라)에 경로 확인 요청"),
    "auth_failed": ("AUTH", "원천 DB 인증 실패", "원천 DB 계정/자격증명 확인(DBA). UC 권한 문제가 아님"),
    "source_read_denied": ("SOURCE_PRIVILEGE", "원천 읽기 권한 부족", "DBA에 대상 테이블 SELECT 권한 요청"),
    "uc_denied": ("UC_PRIVILEGE", "UC connection/foreign catalog 권한 부족", "UC 관리자에 최소권한 요청(DB 계정과 별개)"),
    "unsupported_deployment": ("UNSUPPORTED", "지원하지 않는 소스 배포 유형", "공식 문서 지원 매트릭스 확인, 대체 수집 경로 검토"),
    "log_retention_short": ("CDC_PREREQ", "변경 로그 보존 부족", "DBA 증거·승인 요청 제출(직접 설정 변경하지 않음)"),
    "cursor_missing": ("INCREMENTAL", "증분 커서 컬럼 누락", "데이터 계약에 증분 키 정의 후 재수집"),
    "schema_change": ("SCHEMA_DRIFT", "소스 스키마 변경", "계약 갱신·파이프라인 스키마 진화 정책 검토"),
}


def conn_cmd(S, actor, payload, principal):
    a = payload.get("action")
    cn = S["connections"][payload.get("name", "oracle_food_conn")]
    if a == "select_mode":
        m = payload.get("mode")
        if m == "cdc":
            return "failed", {"error": sql_error("FEATURE_UNVERIFIED", "oracle_cdc 기능은 이 프로필에서 'unverified' 입니다. 확인 필요 — 성공을 모사하지 않습니다. DBA 증거·승인 요청을 제출하세요.")}
        if m not in ("federation", "batch"):
            return "failed", {"error": sql_error("BAD_MODE", "federation|batch|cdc")}
        cn["mode"] = m
        return "ok", {"mode": m}
    if a == "test":
        host = payload.get("host", cn["host"])
        if not host.endswith(".invalid"):
            audit(S, actor["user_id"], "BLOCKED_REAL_HOST", "connection", "blocked", "SIMULATED", {"host": "[REDACTED]"})
            milestone(S, "external_url_blocked")
            return "failed", {"error": sql_error("REAL_HOST_BLOCKED", "A/B 모드는 .invalid 합성 호스트만 허용합니다. 입력값은 저장·접속되지 않았습니다.")}
        if payload.get("password"):
            audit(S, actor["user_id"], "SECRET_INPUT_DISCARDED", "connection", "ok", "SIMULATED", {})
        for f in S["faults"]:
            if f in FAULT_DIAG:
                cat, msg, owner = FAULT_DIAG[f]
                cn["status"] = "FAILED"; cn["last_test"] = {"ok": False, "category": cat, "message": msg, "who": owner}
                audit(S, actor["user_id"], "CONNECTION_TEST", "oracle_food_conn", "failed", "SIMULATED", {"category": cat})
                milestone(S, "conn_fault_seen")
                return "failed", {"error": sql_error(cat, msg, owner), "category": cat}
        cn["status"] = "OK"; cn["last_test"] = {"ok": True}
        audit(S, actor["user_id"], "CONNECTION_TEST", "oracle_food_conn", "ok", "SIMULATED", {})
        return "ok", {"status": "OK"}
    if a == "diagnose":
        cat = payload.get("category")
        t = cn.get("last_test") or {}
        ok = t.get("category") == cat
        if ok:
            milestone(S, "conn_fault_diag")
        return ("ok" if ok else "failed"), {"correct": ok, "answer_hint": None if ok else "다시 로그와 오류 문구를 확인하세요. 단순 재시도로는 해결되지 않습니다."}
    if a == "create_foreign_catalog":
        if cn["status"] != "OK":
            return "failed", {"error": sql_error("CONNECTION_NOT_READY", "연결 테스트가 통과해야 합니다.")}
        # 공식 privileges reference: CREATE FOREIGN CATALOG(connection 또는 metastore) + metastore의 CREATE CATALOG 가 모두 필요
        for priv, sec, why in (("CREATE FOREIGN CATALOG", "connection:oracle_food_conn", "connection 에 CREATE FOREIGN CATALOG 필요 (DB 계정 권한과 별개)"),
                               ("CREATE CATALOG", "metastore:main", "metastore 에 CREATE CATALOG 도 필요 (foreign catalog 생성 시)")):
            if not has_priv(S, principal, priv, sec):
                milestone(S, "foreign_perm_denied")
                return "failed", {"error": sql_error("INSUFFICIENT_PERMISSIONS", f"{sec}: {why}", "권한 요청 티켓 제출 — 두 권한을 각각 최소로 요청", missing={"privilege": priv, "securable": sec})}
        nm = payload.get("catalog_name", "oracle_food")
        S["foreign_catalogs"][nm] = {"connection": "oracle_food_conn", "table_map": {"orders": "orders_src", "orders_src": "orders_src"}}
        S["owners"][f"catalog:{nm}"] = principal
        milestone(S, "foreign_catalog_created")
        return "ok", {"catalog": nm, "note": f"3단계 이름: {nm}.<schema>.orders (원천 매핑은 fixture)"}
    return "failed", {"error": sql_error("BAD_ACTION", str(a))}


# ---------------------------------------------------------------- pipelines
def _pl_priv(S, p, principal):
    # source tables read + target create
    r = run_sql(S, p["source_sql"], principal, via="pipeline", system=False, need_warehouse=False)
    return r


def pipeline_cmd(S, actor, payload, principal):
    p = S["pipelines"][payload.get("name", "orders_pipeline")]
    a = payload.get("action")
    c = _conns[S["id"]]
    if a == "edit":
        p["source_sql"] = payload["source_sql"]; p["state"] = "CREATED"
        return "ok", {"state": p["state"]}
    if a == "set_run_as":
        p["run_as"] = payload["run_as"]
        return "ok", {"run_as": p["run_as"]}
    if a == "validate":
        p["state"] = "VALIDATING"
        # declarative code validator (separate from SQL Editor): must be a single SELECT with no DDL
        try:
            tree = sqlglot.parse_one(p["source_sql"], read="databricks")
        except Exception as e:
            p["state"] = "CREATED"
            return "failed", {"error": sql_error("PIPELINE_PARSE_ERROR", str(e)[:200])}
        if not isinstance(tree, exp.Query):
            p["state"] = "CREATED"
            return "failed", {"error": sql_error("PIPELINE_SOURCE_INVALID", "선언적 파이프라인 소스는 데이터셋 SELECT 정의여야 합니다(SQL Editor DDL과 별도 검증).")}
        rr = run_sql(S, f"SELECT * FROM ({p['source_sql']}) LIMIT 1", p["run_as"], via="pipeline", need_warehouse=False)
        if rr["status"] != "succeeded":
            p["state"] = "CREATED"
            return "failed", {"error": rr["error"], "note": "실행 신원(run_as) 기준 검증"}
        p["state"] = "READY"
        p["events"].append({"event": "VALIDATED", "rev": S["revision"]})
        milestone(S, "pipeline_validated")
        return "ok", {"state": "READY", "validated": True, "note": "검증 성공 ≠ 실행 성공 ≠ 업무 정합성"}
    if a == "run":
        if p["state"] not in ("READY", "SUCCEEDED", "FAILED"):
            return "failed", {"error": sql_error("NOT_READY", "먼저 validate 하세요.")}
        p["state"] = "RUNNING"
        tgt_cat, tgt_db, tgt = p["target"].split(".")
        sec_t = f"schema:{tgt_cat}.{tgt_db}"
        for priv, sec in [("USE CATALOG", f"catalog:{tgt_cat}"), ("USE SCHEMA", sec_t), ("CREATE TABLE", sec_t)]:
            if not has_priv(S, p["run_as"], priv, sec):
                p["state"] = "FAILED"
                p["history"].append({"rev": S["revision"], "state": "FAILED", "reason": f"run_as {p['run_as']}: {sec} {priv} 없음"})
                return "failed", {"state": "FAILED", "error": sql_error("INSUFFICIENT_PERMISSIONS", f"파이프라인 실행 신원 {p['run_as']} 에 {sec} {priv} 없음. 파이프라인 ACL과 데이터 권한은 별개.")}
        rr = run_sql(S, f"SELECT * FROM ({p['source_sql']})", p["run_as"], via="pipeline", need_warehouse=False)
        if rr["status"] != "succeeded":
            p["state"] = "FAILED"
            p["history"].append({"rev": S["revision"], "state": "FAILED", "reason": rr["error"]["message"]})
            return "failed", {"state": "FAILED", "error": rr["error"]}
        cols = [x.lower() for x in rr["columns"]]
        # evaluate expectations against the learner-defined dataset via DuckDB
        duck = sqlglot.parse_one(p["source_sql"], read="databricks").sql(dialect="duckdb")
        c.execute(f"CREATE OR REPLACE TEMP TABLE _pl_stage AS {duck}")
        total = c.execute("SELECT COUNT(*) FROM _pl_stage").fetchone()[0]
        report, blocked, quarantine_where = [], False, []
        for e in p["expectations"]:
            col = e["col"]
            if col not in cols:
                report.append({**e, "violations": None, "note": f"컬럼 {col} 없음"}); blocked = blocked or e["action"] == "block"; continue
            if e["rule"] == "pk_unique":
                v = c.execute(f"SELECT COALESCE(SUM(n-1),0) FROM (SELECT COUNT(*) n FROM _pl_stage GROUP BY {col} HAVING COUNT(*)>1)").fetchone()[0]
            elif e["rule"] == "not_null":
                v = c.execute(f"SELECT COUNT(*) FROM _pl_stage WHERE {col} IS NULL").fetchone()[0]
                if e["action"] == "quarantine":
                    quarantine_where.append(f"{col} IS NULL")
            else:
                inset = ",".join("'" + x + "'" for x in e["set"])
                v = c.execute(f"SELECT COUNT(*) FROM _pl_stage WHERE {col} NOT IN ({inset})").fetchone()[0]
            v = int(v)
            report.append({**e, "violations": v})
            if v and e["action"] == "block":
                blocked = True
        p["last_quality"] = report
        if blocked:
            p["state"] = "FAILED"
            p["history"].append({"rev": S["revision"], "state": "FAILED", "reason": "차단 규칙 위반", "quality": report, "total": total})
            milestone(S, "pipeline_failed_dq")
            audit(S, actor["user_id"], "PIPELINE_RUN", p["name"], "failed", "LOCAL_EXECUTED", {"reason": "dq_block"})
            return "failed", {"state": "FAILED", "quality": report, "note": "품질 차단: 대상 테이블은 갱신되지 않음(성공 상태로 숨기지 않음)"}
        where = " OR ".join(quarantine_where)
        if where:
            c.execute(f"CREATE OR REPLACE TABLE {p['target']}_quarantine AS SELECT * FROM _pl_stage WHERE {where}")
            c.execute(f"CREATE OR REPLACE TABLE {p['target']} AS SELECT * FROM _pl_stage WHERE NOT ({where})")
        else:
            c.execute(f"CREATE OR REPLACE TABLE {p['target']} AS SELECT * FROM _pl_stage")
        S["owners"][f"table:{p['target']}"] = p["run_as"]
        n = c.execute(f"SELECT COUNT(*) FROM {p['target']}").fetchone()[0]
        q = c.execute(f"SELECT COUNT(*) FROM {p['target']}_quarantine").fetchone()[0] if where else 0
        key = seedmod.answer_key()
        recon = {"rows": n, "expected": key["pipeline_expected_rows"], "match": n == key["pipeline_expected_rows"], "quarantined": q}
        p["state"] = "SUCCEEDED"
        p["history"].append({"rev": S["revision"], "state": "SUCCEEDED", "quality": report, "rows": n, "recon": recon})
        milestone(S, "pipeline_ok")
        if recon["match"]:
            milestone(S, "pipeline_recon_ok")
        audit(S, actor["user_id"], "PIPELINE_RUN", p["name"], "succeeded", "LOCAL_EXECUTED", {"rows": n})
        return "ok", {"state": "SUCCEEDED", "quality": report, "reconciliation": recon, "note": "실행 성공과 업무 정합성은 별도 사건입니다."}
    return "failed", {"error": sql_error("BAD_ACTION", str(a))}


# ---------------------------------------------------------------- jobs
def _run_tasks(S, job_name, tasks, run_as, actor, source="job", retries=0):
    results, failed = {}, set()
    for t in tasks:
        k = t["task_key"]
        if any(d in failed or results.get(d, {}).get("status") != "succeeded" for d in t["depends_on"]):
            results[k] = {"status": "skipped", "reason": "UPSTREAM_FAILED"}; failed.add(k); continue
        attempts = 0
        while True:
            attempts += 1
            r = run_sql(S, t["sql"], run_as, via="job", need_warehouse=False, actor_id=actor["user_id"])
            if r["status"] == "succeeded" or attempts > retries:
                break
        results[k] = {"status": r["status"], "attempts": attempts, "rows": r.get("rows"), "columns": r.get("columns"), "error": r["error"]}
        if r["status"] != "succeeded":
            failed.add(k)
    status = "succeeded" if not failed else "failed"
    return status, results


def job_cmd(S, actor, payload, principal):
    j = S["jobs"][payload.get("name", "orders_job")]
    a = payload.get("action")
    if a == "set_run_as":
        rp = payload["run_as"]
        if rp != principal and rp not in S["principals"]:
            return "failed", {"error": sql_error("UNKNOWN_PRINCIPAL", rp)}
        if S["principals"][rp]["kind"] == "user" and rp != principal and actor["role"] not in ("instructor", "admin"):
            return "failed", {"error": sql_error("FORBIDDEN", "다른 사용자 신원으로 run-as 설정은 관리자만 가능합니다.")}
        j["run_as"] = rp
        return "ok", {"run_as": rp}
    if a == "edit_task":
        for t in j["tasks"]:
            if t["task_key"] == payload["task_key"]:
                t["sql"] = payload["sql"]
        return "ok", {}
    if a == "set_retries":
        j["retries"] = int(payload.get("retries", 0)); return "ok", {"retries": j["retries"]}
    if a == "set_schedule":
        j["schedule"] = payload.get("cron"); j["timezone"] = payload.get("timezone", "Asia/Seoul"); return "ok", {}
    if a == "run":
        # editor sees data as themselves, executor identity is run_as
        status, res = _run_tasks(S, j["name"], j["tasks"], j["run_as"], actor, retries=j["retries"])
        run = {"run_id": nid(S, "run"), "run_as": j["run_as"], "triggered_by": principal, "status": status, "tasks": res, "rev": S["revision"]}
        j["runs"].append(run)
        if status == "succeeded":
            milestone(S, "job_ok")
        elif any((t.get("error") or {}).get("code") == "INSUFFICIENT_PERMISSIONS" for t in res.values()):
            milestone(S, "job_runas_fail")
        audit(S, actor["user_id"], "JOB_RUN", j["name"], status, "LOCAL_EXECUTED", {"run_as": j["run_as"], "triggered_by": principal})
        return ("ok" if status == "succeeded" else "failed"), run
    if a == "compare_identity":
        mine = run_sql(S, j["tasks"][0]["sql"], principal, via="job", need_warehouse=False)
        theirs = run_sql(S, j["tasks"][0]["sql"], j["run_as"], via="job", need_warehouse=False)
        return "ok", {"editor": {"principal": principal, "status": mine["status"], "error": mine["error"]}, "run_as": {"principal": j["run_as"], "status": theirs["status"], "error": theirs["error"]}}
    return "failed", {"error": sql_error("BAD_ACTION", str(a))}


# ---------------------------------------------------------------- CLI / bundle / git
FORBIDDEN_CHARS = re.compile(r"[|;&<>`]|\$\(")


def bundle_validate(S):
    files = S["bundle"]["files"]
    msgs, errs, warns = [], [], []
    try:
        y = yaml.safe_load(files.get("databricks.yml", ""))
    except Exception as e:
        return {"ok": False, "errors": [f"YAML 오류: {e}"], "warnings": []}
    if not isinstance(y, dict) or "bundle" not in y or not (y.get("bundle") or {}).get("name"):
        errs.append("bundle.name 필수")
    if "targets" not in (y or {}):
        errs.append("targets 필수")
    jobs = ((y or {}).get("resources") or {}).get("jobs") or {}
    for jk, jv in jobs.items():
        for t in jv.get("tasks", []):
            nt = t.get("notebook_task")
            if nt:
                path = nt["notebook_path"].lstrip("./")
                if path not in files:
                    errs.append(f"{jk}.{t['task_key']}: notebook_path {nt['notebook_path']} 파일 없음")
    if "databricks_cli_version" not in (y or {}).get("bundle", {}):
        warns.append("bundle.databricks_cli_version 미고정 → 배포 검수(DEPLOY_REVIEW) 경고")
    return {"ok": not errs, "errors": errs, "warnings": warns, "note": "validate는 구조·참조 검사입니다. 배포·실행·업무 정합성을 보증하지 않습니다."}


def bundle_hash(files):
    return sha(files)


def cli_run(S, actor, line, principal):
    line = (line or "").strip()
    if not line:
        return "failed", {"stderr": "빈 명령"}
    if FORBIDDEN_CHARS.search(line):
        audit(S, actor["user_id"], "CLI_BLOCKED_SYNTAX", "cli", "blocked", "SIMULATED", {})
        return "failed", {"stderr": "파이프·명령 치환·리다이렉션·임의 shell은 지원하지 않는 명령 파서입니다."}
    import shlex
    try:
        a = shlex.split(line)
    except Exception as e:
        return "failed", {"stderr": f"파싱 오류: {e}"}
    b = S["bundle"]
    if a[0] == "git":
        return _git(S, a, b)
    if a[0] != "databricks":
        return "failed", {"stderr": "OS shell이 아닙니다. databricks / git 명령만 해석합니다."}
    args = a[1:]
    if any(x.startswith("--token") or x.startswith("--password") for x in args):
        audit(S, actor["user_id"], "SECRET_INPUT_DISCARDED", "cli", "blocked", "SIMULATED", {})
        return "failed", {"stderr": "자격증명 옵션은 저장하지 않으며 시뮬레이터에서 지원하지 않습니다."}
    if args[:2] == ["auth", "login"]:
        host = args[args.index("--host") + 1] if "--host" in args and len(args) > args.index("--host") + 1 else None
        if not host or not re.match(r"^https://[a-z0-9.-]+\.invalid/?$", host):
            audit(S, actor["user_id"], "CLI_BLOCKED_REAL_HOST", "cli", "blocked", "SIMULATED", {"host": "[REDACTED]"})
            milestone(S, "external_url_blocked")
            return "failed", {"stderr": "A/B 모드: 합성 .invalid 호스트만 허용. 입력된 호스트는 저장·접속되지 않았습니다(가상 로그인도 생성 안 함)."}
        b["cli_logged_in"] = True; b["cli_host"] = host
        audit(S, actor["user_id"], "CLI_VIRTUAL_LOGIN", "cli", "ok", "SIMULATED", {})
        return "ok", {"stdout": f"[가상 로그인] {host} — 실제 OAuth를 시작하지 않음"}
    if not b["cli_logged_in"]:
        return "failed", {"stderr": "먼저 `databricks auth login --host https://training-workspace.invalid` 를 실행하세요."}
    if args[:2] == ["auth", "describe"] or args[:2] == ["current-user", "me"]:
        return "ok", {"stdout": json.dumps({"user": principal, "host": b["cli_host"], "groups": S["principals"][principal]["groups"]}, ensure_ascii=False, indent=1)}
    if args[:2] == ["catalogs", "list"]:
        cats = [CAT] + list(user_catalogs(S)) + list(S["foreign_catalogs"])
        vis = [c for c in cats if has_priv(S, principal, "USE CATALOG", f"catalog:{c}")]
        return "ok", {"stdout": "\n".join(vis)}
    if args[:2] == ["schemas", "list"] and len(args) >= 3:
        rows = [r[0] for r in q1(S, "select schema_name from information_schema.schemata where catalog_name=?", [args[2]]) if r[0] not in ("information_schema", "main", "pg_catalog")]
        vis = [s for s in rows if has_priv(S, principal, "USE SCHEMA", f"schema:{args[2]}.{s}")]
        return "ok", {"stdout": "\n".join(vis)}
    if args[:2] == ["tables", "list"] and len(args) >= 4:
        if not has_priv(S, principal, "USE SCHEMA", f"schema:{args[2]}.{args[3]}"):
            return "failed", {"stderr": f"INSUFFICIENT_PERMISSIONS: USE SCHEMA schema:{args[2]}.{args[3]}"}
        rows = q1(S, "select table_name from information_schema.tables where table_catalog=? and table_schema=?", [args[2], args[3]])
        return "ok", {"stdout": "\n".join(r[0] for r in rows)}
    if args[:2] == ["tables", "get"] and len(args) >= 3:
        r = run_sql(S, f"SELECT * FROM {args[2]} LIMIT 5", principal, via="cli", need_warehouse=False)
        if r["status"] != "succeeded":
            return "failed", {"stderr": f"{r['error']['code']}: {r['error']['message']}"}
        return "ok", {"stdout": json.dumps({"name": args[2], "columns": r["columns"], "sample": r["rows"]}, ensure_ascii=False, default=str), "same_engine_as_ui": True}
    if args[:1] == ["bundle"] and len(args) >= 2:
        return _bundle(S, actor, args, principal)
    return "failed", {"stderr": f"지원하지 않는 명령입니다(시뮬레이터 부분집합): {' '.join(args)[:80]}"}


def _bundle(S, actor, args, principal):
    b = S["bundle"]; sub = args[1]
    tgt = args[args.index("-t") + 1] if "-t" in args else "dev"
    if tgt != "dev" and tgt != "prod":
        return "failed", {"stderr": f"target `{tgt}` 없음"}
    if sub == "validate":
        v = bundle_validate(S)
        if v["ok"]:
            milestone(S, "bundle_validate")
        return ("ok" if v["ok"] else "failed"), {"stdout": json.dumps(v, ensure_ascii=False, indent=1), "validated_only": True}
    if sub == "deploy":
        v = bundle_validate(S)
        if not v["ok"]:
            return "failed", {"stderr": "validate 실패: " + "; ".join(v["errors"])}
        b["deployed"] = {"files": copy.deepcopy(b["files"]), "hash": bundle_hash(b["files"]), "target": tgt, "at_rev": S["revision"],
                         "deploy_review": "WARN_CLI_VERSION_UNPINNED" if v["warnings"] else "PASS", "source_branch": b.get("head", "main"), "source_commit": ((b.get("branches") or {}).get(b.get("head", "main")))}
        y = yaml.safe_load(b["files"]["databricks.yml"])
        jobs = ((y.get("resources") or {}).get("jobs") or {})
        for jk, jv in jobs.items():
            S["jobs"]["bundle:" + jk] = {"name": jv.get("name", jk), "owner": principal, "run_as": principal, "schedule": None, "timezone": "Asia/Seoul", "retries": 0, "tasks": [], "runs": [], "from_bundle": True}
        milestone(S, "bundle_deploy")
        label = "가상 prod" if tgt == "prod" else "dev"
        return "ok", {"stdout": f"[가상 배포:{label}] hash={b['deployed']['hash'][:12]} review={b['deployed']['deploy_review']}\n배포 성공 ≠ 실행 성공 ≠ 정합성", "deployed_hash": b["deployed"]["hash"]}
    if sub == "run":
        if not b["deployed"]:
            return "failed", {"stderr": "배포된 버전이 없습니다. 먼저 bundle deploy 하세요."}
        key = args[-1]
        y = yaml.safe_load(b["deployed"]["files"]["databricks.yml"])
        job = ((y.get("resources") or {}).get("jobs") or {}).get(key)
        if not job:
            return "failed", {"stderr": f"resource `{key}` 없음"}
        tasks = []
        for t in job.get("tasks", []):
            path = t["notebook_task"]["notebook_path"].lstrip("./")
            tasks.append({"task_key": t["task_key"], "sql": b["deployed"]["files"].get(path, ""), "depends_on": t.get("depends_on", [])})
        local = bundle_hash(b["files"])
        drift = local != b["deployed"]["hash"]
        status, res = _run_tasks(S, key, tasks, principal, actor)
        run = {"status": status, "ran_deployed_hash": b["deployed"]["hash"], "local_hash": local, "drift": drift, "tasks": {k: {"status": v["status"], "rows": v.get("rows"), "error": v["error"]} for k, v in res.items()}}
        b["runs"].append(run)
        milestone(S, "bundle_run")
        if drift:
            milestone(S, "drift_seen")
        diff = ""
        if drift:
            import difflib
            for fn in sorted(set(b["files"]) | set(b["deployed"]["files"])):
                d = list(difflib.unified_diff(b["deployed"]["files"].get(fn, "").splitlines(), b["files"].get(fn, "").splitlines(), "deployed/" + fn, "local/" + fn, lineterm=""))
                diff += "\n".join(d) + ("\n" if d else "")
        return ("ok" if status == "succeeded" else "failed"), {"stdout": f"run {status}; 실행한 것은 **배포된 버전**({b['deployed']['hash'][:12]})" + (f"\n⚠ 로컬 파일이 배포본과 다름(drift). 차이:\n{diff}" if drift else ""), "run": run}
    if sub == "summary":
        return "ok", {"stdout": json.dumps({"local_hash": bundle_hash(b["files"]), "deployed_hash": (b["deployed"] or {}).get("hash"), "drift": bool(b["deployed"]) and bundle_hash(b["files"]) != b["deployed"]["hash"]}, indent=1)}
    return "failed", {"stderr": "지원: validate|deploy|run|summary"}


def _git(S, a, b):
    """내부 가상 저장소: commit/diff/log/branch/checkout/merge(충돌)/pr. 외부 clone·push 불가."""
    import difflib
    b.setdefault("branches", {"main": (b["commits"][-1]["id"] if b["commits"] else None)}); b.setdefault("head", "main"); b.setdefault("merge_state", None); b.setdefault("prs", [])
    byid = {c["id"]: c for c in b["commits"]}
    tip = lambda br: byid.get(b["branches"].get(br)) if b["branches"].get(br) else None
    tipfiles = lambda br: (tip(br) or {"files": {}})["files"]
    cur = tipfiles(b["head"])
    sub = a[1] if len(a) > 1 else ""
    dirty = [f for f in set(b["files"]) | set(cur) if b["files"].get(f) != cur.get(f)]

    def ancestors(cid):
        seen, st = [], [cid]
        while st:
            x = st.pop()
            if x and x not in seen:
                seen.append(x); st.extend(byid[x].get("parents", []))
        return seen
    if sub == "status":
        return "ok", {"stdout": f"브랜치 {b['head']}" + (" · 병합 진행 중(충돌 해결 후 commit)" if b["merge_state"] else "") + (" · 변경: " + ", ".join(sorted(dirty)) if dirty else " · 깨끗함")}
    if sub == "diff":
        out = ""
        for f in sorted(b["files"]):
            out += "\n".join(difflib.unified_diff(cur.get(f, "").splitlines(), b["files"][f].splitlines(), "a/" + f, "b/" + f, lineterm="")) + "\n"
        return "ok", {"stdout": out.strip() or "(차이 없음)"}
    if sub == "commit" and "-m" in a:
        if any("<<<<<<<" in v for v in b["files"].values()):
            return "failed", {"stderr": "충돌 표시(<<<<<<<)가 남아 있습니다. 파일을 정리한 뒤 commit 하세요."}
        parents = [tip(b["head"])["id"]] if tip(b["head"]) else []
        if b["merge_state"]:
            parents.append(b["merge_state"]["theirs_tip"])
        cid = sha({"f": b["files"], "p": parents, "m": a[a.index("-m") + 1]})[:8]
        b["commits"].append({"id": cid, "msg": a[a.index("-m") + 1], "files": copy.deepcopy(b["files"]), "parents": parents, "branch": b["head"]})
        b["branches"][b["head"]] = cid; b["merge_state"] = None
        return "ok", {"stdout": f"[{b['head']} {cid}] {a[a.index('-m') + 1]}" + (" (merge commit)" if len(parents) > 1 else "")}
    if sub == "log":
        return "ok", {"stdout": "\n".join(f"{c['id']} [{c.get('branch', 'main')}] {c['msg']}" + (" (merge)" if len(c.get("parents", [])) > 1 else "") for c in reversed(b["commits"])) or "(커밋 없음)"}
    if sub == "branch":
        if len(a) == 2:
            return "ok", {"stdout": "\n".join(("* " if k == b["head"] else "  ") + k for k in b["branches"])}
        if a[2] in b["branches"]:
            return "failed", {"stderr": "이미 있는 브랜치"}
        b["branches"][a[2]] = b["branches"][b["head"]]
        return "ok", {"stdout": f"브랜치 {a[2]} 생성 (기준 {b['head']})"}
    if sub == "checkout":
        name = a[-1]
        create = "-b" in a
        if dirty:
            return "failed", {"stderr": "커밋하지 않은 변경이 있어 브랜치를 바꿀 수 없습니다(commit 또는 변경 취소)."}
        if create:
            if name in b["branches"]:
                return "failed", {"stderr": "이미 있는 브랜치"}
            b["branches"][name] = b["branches"][b["head"]]
        elif name not in b["branches"]:
            return "failed", {"stderr": f"브랜치 {name} 없음"}
        b["head"] = name; b["files"] = copy.deepcopy(tipfiles(name))
        return "ok", {"stdout": f"브랜치 {name} 로 전환"}
    if sub == "merge":
        if "--abort" in a:
            if not b["merge_state"]:
                return "failed", {"stderr": "진행 중인 병합 없음"}
            b["files"] = copy.deepcopy(cur); b["merge_state"] = None
            return "ok", {"stdout": "병합 취소"}
        name = a[-1]
        if name not in b["branches"] or name == b["head"]:
            return "failed", {"stderr": "병합할 다른 브랜치를 지정하세요"}
        if dirty:
            return "failed", {"stderr": "커밋하지 않은 변경이 있습니다."}
        ours, theirs = tip(b["head"]), tip(name)
        if not theirs:
            return "failed", {"stderr": "대상 브랜치에 커밋 없음"}
        anc_o = ancestors(ours["id"]) if ours else []
        base = next((byid[x] for x in ancestors(theirs["id"]) if x in anc_o), None)
        if base and base["id"] == theirs["id"]:
            return "ok", {"stdout": "이미 최신(Already up to date)"}
        bf = base["files"] if base else {}
        merged, conflicts = {}, []
        for f in sorted(set(bf) | set(cur) | set(theirs["files"])):
            o, t, bb = cur.get(f), theirs["files"].get(f), bf.get(f)
            if o == t:
                merged[f] = o
            elif o == bb:
                merged[f] = t
            elif t == bb:
                merged[f] = o
            else:
                conflicts.append(f); merged[f] = f"<<<<<<< {b['head']}\n{o or ''}\n=======\n{t or ''}\n>>>>>>> {name}"
        b["files"] = {k: v for k, v in merged.items() if v is not None}
        if conflicts:
            b["merge_state"] = {"theirs": name, "theirs_tip": theirs["id"], "conflicts": conflicts}
            milestone(S, "git_conflict_seen")
            return "failed", {"stderr": "CONFLICT: " + ", ".join(conflicts) + " — 파일의 충돌 표시를 해결한 뒤 `git commit -m ...` 하세요(또는 `git merge --abort`)."}
        b["merge_state"] = {"theirs": name, "theirs_tip": theirs["id"], "conflicts": []}
        r = _git(S, ["git", "commit", "-m", f"Merge {name} into {b['head']}"], b)
        milestone(S, "git_merge_ok")
        return r
    if sub == "pr" and len(a) >= 3 and a[2] == "create":
        src = a[3] if len(a) > 3 else b["head"]
        pr = {"pr_id": nid(S, "PR-git"), "source": src, "target": "main", "status": "OPEN", "changed_files": sorted(f for f in tipfiles(src) if tipfiles(src).get(f) != tipfiles("main").get(f)), "source_tip": b["branches"].get(src)}
        b["prs"].append(pr)
        milestone(S, "git_pr_created")
        return "ok", {"stdout": f"PR {pr['pr_id']}: {src} → main (변경 파일 {len(pr['changed_files'])}) — 리뷰어 검토 후 병합"}
    if sub == "pr" and len(a) >= 2 and a[2:3] == ["list"]:
        return "ok", {"stdout": "\n".join(f"{p['pr_id']} {p['source']}→{p['target']} {p['status']}" for p in b["prs"]) or "(PR 없음)"}
    return "failed", {"stderr": "지원: git status|diff|commit -m|log|branch [이름]|checkout [-b] 이름|merge 이름|merge --abort|pr create [브랜치]|pr list (내부 가상 저장소, 외부 clone·push 불가)"}


# ---------------------------------------------------------------- Genie (deterministic templates)
GENIE_TEMPLATES = [
    ("총 주문 박스", ["총", "박스"], f"SELECT SUM(total_boxes) AS total_boxes FROM {CAT}.gold.v_order_overview"),
    ("주문 건수 상태별", ["상태별", "주문"], f"SELECT status, COUNT(*) AS orders FROM {CAT}.gold.v_order_overview GROUP BY status ORDER BY status"),
    ("{ORDER} 주문 개요", ["{order}"], f"SELECT * FROM {CAT}.gold.v_order_overview WHERE order_id='{{ORDER}}'"),
    ("공급가 합계", ["공급가"], f"SELECT SUM(supply_amount) AS supply_amount, SUM(vat_amount) AS vat_amount FROM {CAT}.gold.v_order_overview"),
    ("{PRODUCT} 가용재고", ["{product}", "가용"], f"SELECT product_id, available_qty FROM {CAT}.gold.v_available_inventory WHERE product_id='{{PRODUCT}}'"),
    ("가용재고 상위 5", ["가용재고", "상위"], f"SELECT product_id, available_qty FROM {CAT}.gold.v_available_inventory ORDER BY available_qty DESC, product_id LIMIT 5"),
    ("거래처 {CUST} 주문", ["{cust}"], f"SELECT order_id,total_boxes FROM {CAT}.gold.v_order_overview WHERE customer_id='{{CUST}}' ORDER BY order_id"),
    ("취소 주문 수", ["취소"], f"SELECT COUNT(*) AS cancelled FROM {CAT}.gold.v_order_overview WHERE status='CANCELLED'"),
    ("주문당 평균 박스", ["평균"], f"SELECT AVG(total_boxes) AS avg_boxes FROM {CAT}.gold.v_order_overview"),
    ("VAT 합계", ["vat"], f"SELECT SUM(vat_amount) AS vat FROM {CAT}.gold.v_order_overview"),
]


def genie_ask(S, actor, question, as_principal):
    q = (question or "").lower()
    g = S["genie"]
    cz = S["case"]
    fill = lambda x: x.replace("{ORDER}", cz["order"]).replace("{PRODUCT}", cz["product"]).replace("{CUST}", cz["cust"]).replace("{order}", cz["order"].lower()).replace("{product}", cz["product"].lower()).replace("{cust}", cz["cust"].lower())
    hit = next(((fill(t[0]), [fill(k) for k in t[1]], fill(t[2])) for t in GENIE_TEMPLATES if all(fill(k) in q for k in t[1])), None)
    rec = {"question": question, "principal": as_principal}
    if not hit:
        rec.update(status="OUT_OF_SCOPE", note="결정적 질의 템플릿 밖의 질문입니다(실제 Genie 모델 품질·추론을 재현하지 않음).")
        g["history"].append(rec); return rec
    name, _, sql = hit
    ds = re.findall(r"food_dev\.\w+\.\w+", sql)[0]
    if ds not in g["datasets"]:
        rec.update(status="DATASET_NOT_REGISTERED", sql=sql, note=f"{ds} 가 Genie 데이터셋에 등록되지 않았습니다. 설정을 수정하세요.")
        g["history"].append(rec); return rec
    r = run_sql(S, sql, as_principal, via="genie", need_warehouse=False, actor_id=actor["user_id"])
    rec.update(sql=sql, template=name, status="OK" if r["status"] == "succeeded" else "DENIED", columns=r["columns"], rows=r["rows"], error=r["error"], evidence_level="LOCAL_EXECUTED")
    if r["status"] == "succeeded":
        milestone(S, "genie_ok")
    elif r["error"] and r["error"]["code"] == "INSUFFICIENT_PERMISSIONS" and as_principal != TRAINEE:
        milestone(S, "genie_leak_blocked")
    g["history"].append(rec)
    return rec


# ---------------------------------------------------------------- policy edit/test/activate
def policy_cases():
    base = {"order_id": "T", "customer_id": "C", "order_version": 1, "route_id": "R", "product_id": "P", "current_qty": 20, "requested_total": 35,
            "available_qty": 12, "credit_blocked": False, "exception_contract": True, "route_open": True, "after_cutoff": True, "substitutes": []}
    return [("대표사례: 추가부족 3·승인 필요", dict(base), lambda d: d["shortage"] == 3 and d["decision"] == "REQUIRES_APPROVAL"),
            ("여신 차단 → 금지", {**base, "credit_blocked": True}, lambda d: d["decision"] == "PROHIBITED"),
            ("노선 마감 → 이관", {**base, "route_open": False}, lambda d: d["decision"] == "ESCALATE"),
            ("마감 이후+예외계약 없음 → 이관", {**base, "exception_contract": False}, lambda d: d["decision"] == "ESCALATE")]


def policy_test(rule):
    res = []
    for name, f, chk in policy_cases():
        d = policy_decide(f, rule)
        res.append({"case": name, "decision": d["decision"], "pass": bool(chk(d))})
    return res


def policy_save_draft(S, text):
    try:
        y = yaml.safe_load(text)
    except Exception as e:
        raise ApiError(400, "YAML_ERROR", str(e))
    need = {"rule_id", "requires_approval", "prohibited_if", "revalidate_before_execution"}
    if not isinstance(y, dict) or not need <= set(y):
        raise ApiError(400, "POLICY_SCHEMA", f"필수 키: {sorted(need)}")
    y["tests"] = policy_test(y)
    y["tests_passed"] = all(t["pass"] for t in y["tests"])
    S["policy"]["draft"] = y
    return y


def policy_activate(S, actor):
    d = S["policy"]["draft"]
    if not d or not d.get("tests_passed"):
        raise ApiError(409, "TESTS_NOT_PASSED", "테스트를 통과한 버전만 활성화할 수 있습니다.")
    v = str(max(int(k) for k in S["policy"]["versions"]) + 1)
    S["policy"]["versions"][v] = d
    S["policy"]["active"] = int(v); S["policy"]["draft"] = None
    audit(S, actor["user_id"], "POLICY_ACTIVATED", v, "ok", "LOCAL_EXECUTED", {})
    return {"active": int(v)}


# ---------------------------------------------------------------- faults / reset / checkpoint
FAULT_CATALOG = {
    "missing_use_schema": "silver USE SCHEMA 누락(기본 상태)",
    "warehouse_start_fail": "Warehouse 시작 실패",
    "net_unreachable": "원천 DNS/네트워크 불통", "auth_failed": "원천 인증 실패", "source_read_denied": "원천 읽기 권한 부족",
    "uc_denied": "UC 권한 부족", "unsupported_deployment": "미지원 소스 배포 유형", "log_retention_short": "변경 로그 보존 부족",
    "cursor_missing": "증분 커서 누락", "schema_change": "스키마 변경",
    "stock_change_after_approval": "승인 후 재고 변경(P-001 damaged+1)", "order_version_conflict": "주문 버전 외부 변경",
    "approval_expired": "승인 만료(시계 +31분)", "credit_blocked": "거래처 여신 차단", "route_closed": "배송 노선 마감",
}


def inject_fault(S, actor, fault_id):
    if actor["role"] != "instructor":
        raise ApiError(403, "FORBIDDEN", "장애 주입은 강사 권한이 필요합니다.")
    if fault_id not in FAULT_CATALOG:
        raise ApiError(400, "UNKNOWN_FAULT", fault_id)
    c = _conns[S["id"]]
    if fault_id == "stock_change_after_approval":
        c.execute(f"UPDATE {CAT}.silver.inventory SET damaged_qty=damaged_qty+1 WHERE product_id=? AND warehouse_id='W1'", [S["case"]["product"]])
    elif fault_id == "order_version_conflict":
        c.execute(f"UPDATE {CAT}.silver.orders SET version=version+1 WHERE order_id=?", [S["case"]["order"]])
    elif fault_id == "approval_expired":
        S["clock_offset_s"] += 31 * 60
    elif fault_id == "credit_blocked":
        c.execute(f"UPDATE {CAT}.silver.customers SET credit_blocked=true WHERE customer_id=?", [S["case"]["cust"]])
    elif fault_id == "route_closed":
        c.execute(f"UPDATE {CAT}.silver.delivery_routes SET is_open=false WHERE route_id=?", [S["case"]["route"]])
    else:
        if fault_id not in S["faults"]:
            S["faults"].append(fault_id)
    S["fault_log"].append({"fault": fault_id, "at_rev": S["revision"], "by": actor["user_id"], "release": "reset 또는 강사 해제"})
    audit(S, actor["user_id"], "FAULT_INJECTED", fault_id, "ok", "SIMULATED", {})
    return {"fault": fault_id, "description": FAULT_CATALOG[fault_id]}


def release_fault(S, actor, fault_id):
    if actor["role"] != "instructor":
        raise ApiError(403, "FORBIDDEN", "강사 권한")
    if fault_id in S["faults"]:
        S["faults"].remove(fault_id)
    c = _conns[S["id"]]
    if fault_id == "credit_blocked":
        c.execute(f"UPDATE {CAT}.silver.customers SET credit_blocked=false WHERE customer_id=?", [S["case"]["cust"]])
    if fault_id == "route_closed":
        c.execute(f"UPDATE {CAT}.silver.delivery_routes SET is_open=true WHERE route_id=?", [S["case"]["route"]])
    audit(S, actor["user_id"], "FAULT_RELEASED", fault_id, "ok", "SIMULATED", {})
    return {"released": fault_id}


def reset_session(S, actor):
    """Re-seed data/resources/permissions/clock. Evidence before reset is preserved in resets[]."""
    snap = {"at": now_utc(), "by": actor["user_id"], "revision": S["revision"], "milestones": list(S["milestones"]), "audit_events": len(S["audit"]), "digest": data_digest(S)}
    c = _conns.pop(S["id"], None)
    if c:
        c.close()
    for ext in (".duckdb", ".duckdb.wal"):
        try:
            (DATA / f"{S['id']}{ext}").unlink()
        except FileNotFoundError:
            pass
    prev_audit, prev_resets = S["audit"], S["resets"] + [snap]
    new = default_state(S["id"], S["owner"], S["lesson_id"], S["mode"], S["learning_mode"], S.get("seed", seedmod.SEED_NAME))
    _fresh_db(S["id"], S.get("seed", seedmod.SEED_NAME))
    cc = _open_conn(S["id"]); _lockdown(cc); _conns[S["id"]] = cc
    S.clear(); S.update(new)
    S["audit"] = prev_audit; S["resets"] = prev_resets
    S["data_digest0"] = data_digest(S)
    audit(S, actor["user_id"], "SESSION_RESET", S["id"], "ok", "SIMULATED", {"preserved_events": len(prev_audit)})
    return {"reset": True, "preserved_evidence": snap}


def checkpoint(S, name):
    c = _conns[S["id"]]
    c.execute(f"CHECKPOINT {CAT}")
    shutil.copy(DATA / f"{S['id']}.duckdb", DATA / f"{S['id']}.{name}.ckpt")
    S["checkpoints"][name] = {"state": copy.deepcopy({k: v for k, v in S.items() if k not in ("checkpoints", "audit")}), "rev": S["revision"]}
    return {"checkpoint": name}


def restore(S, name):
    if name not in S["checkpoints"]:
        raise ApiError(404, "NO_CHECKPOINT", name)
    c = _conns.pop(S["id"]); c.close()
    shutil.copy(DATA / f"{S['id']}.{name}.ckpt", DATA / f"{S['id']}.duckdb")
    cp = S["checkpoints"][name]
    keep = {"checkpoints": S["checkpoints"], "audit": S["audit"]}
    S.clear(); S.update(copy.deepcopy(cp["state"])); S.update(keep)
    cc = _open_conn(S["id"]); _lockdown(cc); _conns[S["id"]] = cc
    _thist_invalidate(S)
    audit(S, "instructor", "CHECKPOINT_RESTORED", name, "ok", "SIMULATED", {})
    return {"restored": name}


# ---------------------------------------------------------------- logged API calls (replayable)
def api(S, actor, kind, payload):
    """Ticket/approval/AX calls go through here so cmd_log can replay them deterministically."""
    S["cmd_log"].append({"type": "api." + kind, "payload": copy.deepcopy(payload), "actor_role": actor["role"]})
    try:
        if kind == "ticket.create":
            r = create_ticket(S, actor, payload["privilege"], payload["securable"], payload.get("reason", ""), payload.get("grantee"))
        elif kind == "ticket.resolve":
            r = resolve_ticket(S, actor, payload["ticket_id"], payload["decision"], payload.get("note", ""))
        elif kind == "approval":
            r = approve(S, actor, payload["proposal_id"], payload["payload_hash"])
        elif kind == "ax.execute":
            r = ax_execute(S, actor, payload["order_id"], payload)
        elif kind == "fault.inject":
            r = inject_fault(S, actor, payload["fault_id"])
        elif kind == "fault.release":
            r = release_fault(S, actor, payload["fault_id"])
        else:
            raise ApiError(400, "UNKNOWN_API", kind)
        return r
    finally:
        S["revision"] += 1
        save(S)


_SECRET_RE = re.compile(r"(--(?:token|password|secret)(?:=|\s+))\S+", re.I)


def redact_payload(payload):
    """Never persist credentials or real hosts (AT-21)."""
    out = {}
    for k, v in payload.items():
        if k in ("password", "token", "secret"):
            continue
        if isinstance(v, str):
            v = _SECRET_RE.sub(r"[REDACTED]", v)
            if k == "host" and not v.endswith(".invalid"):
                v = "[REDACTED]"
            v = re.sub(r"--host\s+(?!https://[a-z0-9.-]+\.invalid)\S+", "--host [REDACTED]", v)
        out[k] = v
    return out


# ---------------------------------------------------------------- command dispatcher
def commands(S, actor, command_type, payload, idem_key=None, expected_revision=None):
    if S["paused"] and actor["role"] == "learner":
        raise ApiError(423, "SESSION_PAUSED", "강사가 세션을 일시정지했습니다.")
    if idem_key and idem_key in S["idem"]:
        r = copy.deepcopy(S["idem"][idem_key]); r["replayed"] = True
        return r
    if expected_revision is not None and expected_revision != S["revision"]:
        raise ApiError(409, "REVISION_CONFLICT", f"세션 revision 불일치(현재 {S['revision']}). 새로고침 후 재시도.")
    persona = payload.get("as_persona") if command_type == "genie.ask" else None
    if persona and persona != ANALYST:
        raise ApiError(403, "FORBIDDEN", "허용된 페르소나는 analyst-b 뿐입니다.")
    principal = principal_of(S, actor, None if persona else payload.get("as_principal"))
    S["actor"] = principal
    trace = "tr_" + uuid.uuid4().hex[:8]
    eid = "x_" + uuid.uuid4().hex[:8]
    status, result = "ok", {}
    ct = command_type
    if ct == "sql.execute":
        r = run_sql(S, payload.get("sql", ""), principal, trace=trace, actor_id=actor["user_id"])
        status = "ok" if r["status"] == "succeeded" else "failed"; result = r
        if r["status"] != "succeeded" and r["error"] and r["error"]["code"] == "INSUFFICIENT_PERMISSIONS" and any("silver" in t for t in re.findall(r"food_dev\.\w+\.\w+", payload.get("sql", ""))):
            milestone(S, "sql_perm_denied")
        if r["status"] == "succeeded" and any(t.startswith(f"{CAT}.silver.") for t in r.get("tables", [])):
            milestone(S, "select_ok_silver")
        if r["status"] == "succeeded" and any("cdc_events" in t for t in r.get("tables", [])):
            milestone(S, "cdc_events_viewed")
        if r["status"] == "succeeded" and "v_available_inventory" in payload.get("sql", "") and re.search(r"create\s+(or\s+replace\s+)?view", payload["sql"], re.I):
            contract_check(S)
        if r["status"] != "succeeded" and r["error"]["code"] == "SIMULATOR_UNSUPPORTED":
            milestone(S, "unsupported_sql_seen")
    elif ct == "warehouse":
        status, result = warehouse_cmd(S, actor, payload, principal)
    elif ct == "notebook":
        status, result = nb_cmd(S, actor, payload, principal)
    elif ct == "connection":
        status, result = conn_cmd(S, actor, payload, principal)
    elif ct == "pipeline":
        status, result = pipeline_cmd(S, actor, payload, principal)
    elif ct == "job":
        status, result = job_cmd(S, actor, payload, principal)
    elif ct == "cli":
        status, result = cli_run(S, actor, payload.get("line", ""), principal)
    elif ct == "bundle.edit":
        _p, _t = str(payload.get("path", "")), str(payload.get("content", ""))
        if not re.fullmatch(r"[A-Za-z0-9_./-]{1,100}", _p) or ".." in _p or len(_t) > 200_000 or (_p not in S["bundle"]["files"] and len(S["bundle"]["files"]) >= 50):
            raise ApiError(400, "INVALID_PATH", "파일 경로는 영문·숫자·_ . / - 만 쓰고(100자 이하, '..' 불가), 내용은 200KB 이하, 파일은 50개까지입니다.")
        S["bundle"]["files"][_p] = _t
        result = {"hash": bundle_hash(S["bundle"]["files"])}
    elif ct == "genie.ask":
        ap = persona or payload.get("as_principal") or principal
        result = genie_ask(S, actor, payload.get("question", ""), ap)
        status = "ok" if result.get("status") == "OK" else "failed"
    elif ct == "genie.config":
        S["genie"]["datasets"] = payload.get("datasets", S["genie"]["datasets"])
        S["genie"]["terms"] = payload.get("terms", S["genie"]["terms"])
        result = S["genie"]
    elif ct == "env.check":
        milestone(S, "env_checked")
        result = {"profile": profile_of(S), "identity": {"principal": principal, "groups": S["principals"][principal]["groups"], "entitlements": S["principals"][principal]["entitlements"], "admin": is_admin(S, principal)},
                  "warehouse": wh_state(S), "unknown_items": ["ui_release_id", "serverless_environment", "sql_warehouse_channel", "cli_version", "genie_agents.workspace_enabled", "oracle_cdc.workspace_enabled"]}
    elif ct == "feature.use":
        f = next((x for x in FEATURES if x["feature_id"] == payload.get("feature_id")), None)
        if not f:
            status, result = "failed", {"error": sql_error("UNKNOWN_FEATURE", "feature_id")}
        elif not f["usable"]:
            milestone(S, "unverified_feature_blocked")
            status, result = "failed", {"error": sql_error("FEATURE_UNVERIFIED", f"'{f['feature_id']}' 는 {f['status']} 상태 — 확인 필요/미지원 사유로 성공을 모사하지 않습니다.", "지원 여부는 클라우드·리전·관리자 설정·entitlement·ACL·UI 개편으로 구분해 확인")}
        else:
            result = {"feature": f, "note": f"문서 확인({f['status']})만 되었고 워크스페이스 실측 전: SIMULATED"}
    elif ct == "order.propose":
        result = order_propose(S, actor, payload["order_id"], payload["requested_total"], payload.get("alt_index", 0))
    elif ct == "order.facts":
        f = order_facts(S, payload["order_id"], int(payload.get("requested_total", 0)))
        result = {"facts": f, "wrong_if_total_minus_free": f["requested_total"] - f["available_qty"],
                  "shortage": extra_gap(f["current_qty"], f["requested_total"], f["available_qty"])}
    elif ct == "cost.set_profile":
        result = cost_set_profile(S, payload)
    elif ct == "cdc.next_batch":
        result = cdc_next_batch(S)
    elif ct == "cdc.check":
        result = cdc_check(S)
        status = "ok" if result["ok"] else "failed"
    elif ct == "contract.check":
        result = contract_check(S)
        status = "ok" if result["ok"] else "failed"
    elif ct == "policy.draft":
        result = policy_save_draft(S, payload["yaml"])
    elif ct == "policy.activate":
        result = policy_activate(S, actor)
    elif ct == "eval.run":
        result = eval_run(S)
        milestone(S, "eval_run")
    elif ct == "guide.ack":
        if payload.get("key") not in ("req", "wrap"):
            raise ApiError(400, "BAD_ACK", "key")
        milestone(S, "ack_" + payload["key"])
        result = {"acknowledged": payload["key"]}
    elif ct == "ontology.map":
        result = ONTOLOGY_MAP
    else:
        raise ApiError(400, "UNKNOWN_COMMAND", ct)
    S["revision"] += 1
    ex = {"command_id": "cmd_" + uuid.uuid4().hex[:8], "execution_id": eid, "status": status, "result": result, "trace_id": trace,
          "evidence_level": result.get("evidence_level") if isinstance(result, dict) and result.get("evidence_level") else ("LOCAL_EXECUTED" if ct in ("sql.execute", "contract.check", "order.propose", "order.facts", "pipeline", "job") else "SIMULATED"),
          "revision": S["revision"], "profile_id": S["profile_id"], "policy_version": S["policy"]["active"], "code_hash": result.get("sql_hash") if isinstance(result, dict) else None,
          "type": ct, "principal": principal}
    S["executions"][eid] = ex
    S["cmd_log"].append({"type": ct, "payload": redact_payload(payload), "actor_role": actor["role"]})
    S["idem"].update({idem_key: ex} if idem_key else {})
    save(S)
    return ex


ONTOLOGY_MAP = {
    "note": "'온톨로지 적용' 한 번으로 모든 기능이 생성되지 않습니다. 각 요소가 어느 계층에 반영되는지 별도 작업입니다.",
    "entities": [{"name": "Order", "maps_to": "UC 테이블/뷰 메타데이터(COMMENT, 태그)"}, {"name": "Customer", "maps_to": "UC 테이블 + 권한"}, {"name": "Inventory", "maps_to": "gold.v_available_inventory (계약 산식)"}],
    "relations": [{"name": "Order-Customer", "maps_to": "Genie JOIN 지식 설정"}, {"name": "Order-Line-Product", "maps_to": "Genie JOIN 지식 설정"}],
    "metrics": [{"name": "available_qty", "maps_to": "Metric View 후보(프로필 DRAFT: 미확인) / 현재는 gold 뷰"}],
    "policies": [{"name": "ORDER_CHANGE_AFTER_CUTOFF", "maps_to": "WIZBASE 정책 엔진(Databricks 설정 아님)"}],
}


# ---------------------------------------------------------------- evaluation set (40 cases)
def eval_cases():
    out = []
    base = {"order_id": "T", "customer_id": "C", "order_version": 1, "route_id": "R", "product_id": "P", "current_qty": 20, "requested_total": 35,
            "available_qty": 12, "credit_blocked": False, "exception_contract": True, "route_open": True, "after_cutoff": True, "substitutes": [{"substitute_id": "P-002"}]}
    def add(cat, name, over, exp_dec, exp_gap=None):
        out.append({"id": f"E{len(out) + 1:02d}", "category": cat, "name": name, "facts": {**base, **over}, "expect_decision": exp_dec, "expect_shortage": exp_gap})
    for i, (cur, req, av) in enumerate([(20, 35, 12), (10, 20, 10), (5, 30, 5), (20, 20, 12), (0, 12, 12), (15, 40, 8)]):
        add("재고", f"재고 시나리오 {i + 1}", {"current_qty": cur, "requested_total": req, "available_qty": av}, "REQUIRES_APPROVAL", max(max(req - cur, 0) - av, 0))
    for i in range(4):
        add("정상", f"정상 {i + 1}", {"current_qty": 10, "requested_total": 12 + i, "available_qty": 50}, "REQUIRES_APPROVAL", 0)
    for i in range(4):
        add("마감", f"마감 이후 예외계약 없음 {i + 1}", {"exception_contract": False, "requested_total": 25 + i}, "ESCALATE")
    for i in range(4):
        add("여신", f"여신 차단 {i + 1}", {"credit_blocked": True, "requested_total": 30 + i}, "PROHIBITED")
    for i in range(4):
        add("노선", f"노선 마감 {i + 1}", {"route_open": False, "requested_total": 22 + i}, "ESCALATE")
    for i in range(3):
        add("단위", f"대체 단위 불일치 {i + 1}", {"substitutes": []}, "REQUIRES_APPROVAL", 3)
    for i in range(3):
        add("반품", f"반품/감량 {i + 1}", {"requested_total": 10 - i, "current_qty": 20}, "REQUIRES_APPROVAL", 0)
    for i in range(3):
        add("데이터 없음", f"가용 0 {i + 1}", {"available_qty": 0, "requested_total": 21 + i}, "REQUIRES_APPROVAL", 1 + i)
    for i in range(3):
        add("경계", f"경계값 {i + 1}", {"available_qty": 15 - i, "requested_total": 35}, "REQUIRES_APPROVAL", max(15 - (15 - i), 0))
    for i in range(6):
        add("복합", f"여신+노선 {i + 1}", {"credit_blocked": bool(i % 2), "route_open": bool(i % 3), "requested_total": 26 + i}, "PROHIBITED" if i % 2 else ("ESCALATE" if not (i % 3) else "REQUIRES_APPROVAL"))
    return out  # 40


def eval_run(S):
    rule = active_rule(S)
    res, ok = [], 0
    for c in eval_cases():
        d = policy_decide(c["facts"], rule)
        p1 = d["decision"] == c["expect_decision"]
        p2 = c["expect_shortage"] is None or d["shortage"] == c["expect_shortage"]
        res.append({"id": c["id"], "category": c["category"], "name": c["name"], "decision": d["decision"], "shortage": d["shortage"], "expect": c["expect_decision"], "expect_shortage": c["expect_shortage"], "pass": p1 and p2,
                    "criteria": {"policy_decision": p1, "data_result(shortage)": p2}})
        ok += p1 and p2
    run = {"policy_version": S["policy"]["active"], "total": len(res), "passed": ok, "cases": res}
    S["eval_runs"].append({k: run[k] for k in ("policy_version", "total", "passed")})
    return run


# ---------------------------------------------------------------- lessons / progress / scoring / evidence
LESSONS = [
    {"lesson_id": "ENV-01", "title": "환경·신원·프로필 확인", "objective": "클라우드·프로필·실행 신원·미확인 항목을 구분한다", "requires": ["env_checked", "unverified_feature_blocked"], "evidence_level": "SIMULATED"},
    {"lesson_id": "UC-SELECT-01", "title": "권한 오류 진단·최소권한 요청", "objective": "거래처 테이블 조회 권한 누락을 진단한다", "faults": ["missing_use_schema"], "requires": ["sql_perm_denied", "ticket_created", "ticket_resolved", "select_ok_silver"], "forbidden": ["self_grant_attempt", "over_broad_request"], "evidence_level": "LOCAL_EXECUTED"},
    {"lesson_id": "SQL-CONTRACT-01", "title": "계약 산식으로 재고 뷰 수정", "objective": "available_qty = on_hand-reserved-damaged 로 gold 뷰를 수정하고 정합성을 증명한다", "requires": ["view_fixed", "recon_ok"], "evidence_level": "LOCAL_EXECUTED"},
    {"lesson_id": "ORDER-CHANGE-01", "title": "주문 변경 제안·승인·가상 API", "objective": "추가 부족량 3을 계산하고 승인형 대안으로 실행한다", "requires": ["shortage_3_found", "proposal_made", "approved", "ax_executed"], "evidence_level": "SIMULATED"},
    {"lesson_id": "ORDER-SAFETY-01", "title": "무승인·변조·멱등·충돌", "objective": "서버 통제를 확인한다", "requires": ["ax_no_approval_blocked", "tamper_blocked", "idem_replayed", "version_conflict_seen"], "evidence_level": "SIMULATED"},
    {"lesson_id": "PIPELINE-01", "title": "품질 차단과 복구", "objective": "중복키 차단을 진단·수정하고 정합성을 대조한다", "requires": ["pipeline_validated", "pipeline_failed_dq", "pipeline_ok", "pipeline_recon_ok"], "evidence_level": "LOCAL_EXECUTED"},
    {"lesson_id": "JOB-RUNAS-01", "title": "Job 소유자 vs run-as", "objective": "편집자 조회 성공과 실행자 실패를 비교·복구", "requires": ["job_runas_fail", "job_ok"], "evidence_level": "LOCAL_EXECUTED"},
    {"lesson_id": "CONN-01", "title": "연결 실패 진단·foreign catalog", "objective": "네트워크/인증/권한/지원 차이를 구분", "requires": ["conn_fault_seen", "conn_fault_diag", "foreign_perm_denied", "foreign_catalog_created"], "evidence_level": "SIMULATED"},
    {"lesson_id": "BUNDLE-01", "title": "validate / deploy / run / drift", "objective": "검증≠배포≠실행, 미배포 코드 차이", "requires": ["bundle_validate", "bundle_deploy", "bundle_run", "drift_seen"], "evidence_level": "SIMULATED"},
    {"lesson_id": "GENIE-01", "title": "Genie 설정·질의·누출 차단", "objective": "생성 SQL 확인, 다른 사용자 접근 차단", "requires": ["genie_ok", "genie_leak_blocked"], "evidence_level": "LOCAL_EXECUTED"},
    {"lesson_id": "CDC-01", "title": "CDC 이벤트 재생(중복·역순·삭제·재삽입)", "objective": "이벤트 로그에서 최신 상태 테이블을 멱등하게 구축·재적용한다", "requires": ["cdc_events_viewed", "cdc_batch1_ok", "cdc_batch2_ok"], "evidence_level": "LOCAL_EXECUTED"},
    {"lesson_id": "NB-01", "title": "Notebook 오래된 결과·재시작", "objective": "stale 셀 식별과 변수 초기화", "requires": ["notebook_stale_seen", "notebook_restart"], "evidence_level": "LOCAL_EXECUTED"},
    {"lesson_id": "ISOLATION-01", "title": "실제 URL·자격증명 차단", "objective": "외부 연결 시도가 차단된다", "requires": ["external_url_blocked"], "evidence_level": "SIMULATED"},
]


def progress(S):
    out = []
    for l in LESSONS:
        done = [m for m in l["requires"] if m in S["milestones"]]
        forb = [m for m in l.get("forbidden", []) if m in S["milestones"]]
        out.append({"lesson_id": l["lesson_id"], "title": l["title"], "objective": l["objective"], "done": done, "pending": [m for m in l["requires"] if m not in done],
                    "completed": len(done) == len(l["requires"]), "forbidden_events": forb, "evidence_level": l["evidence_level"]})
    return out


REQUIRED_SAFETY = [("실제 운영계 연결 시도 차단", "external_url_blocked"), ("무권한 조회 차단", "sql_perm_denied"), ("무승인 변경 차단", "ax_no_approval_blocked"),
                   ("payload 변조 차단", "tamper_blocked"), ("반복 실행 중복 방지", "idem_replayed"), ("버전 충돌 재승인", "version_conflict_seen"),
                   ("모의 결과와 실제 검증 결과 구분", "env_checked")]


def score(S):
    m = S["milestones"]
    def pts(names, each):
        return sum(each for n in names if n in m)
    env = pts(["sql_perm_denied", "ticket_created", "ticket_resolved", "select_ok_silver", "job_runas_fail"], 4)
    if "self_grant_attempt" in m: env -= 4
    if "over_broad_request" in m: env -= 4
    data = pts(["view_fixed", "recon_ok", "shortage_3_found", "pipeline_recon_ok", "genie_ok"], 5)
    code = pts(["pipeline_ok", "job_ok", "bundle_validate", "bundle_deploy", "bundle_run"], 4)
    fault = pts(["ax_no_approval_blocked", "tamper_blocked", "idem_replayed", "version_conflict_seen", "ax_executed"], 4)
    ex = S["assessment"]["explain_score"]
    areas = {"환경·권한·책임 구분 (20)": max(env, 0), "데이터·업무 의미·정합성 (25)": data, "코드·파이프라인·배포 (20)": code, "장애 복구·감사·승인 (20)": fault,
             "고객/SA 설명·인수 (15)": ex if ex is not None else None}
    total = sum(v for v in areas.values() if v is not None)
    safety = [{"item": n, "passed": k in m} for n, k in REQUIRED_SAFETY]
    all_safe = all(s["passed"] for s in safety)
    return {"areas": areas, "auto_total": total, "explain_pending": ex is None, "safety": safety,
            "core_completion": bool(total >= 80 and all_safe and ex is not None),
            "note": "입문 코어 기준(80점+필수 안전 항목+설명 평가). 전문 등급·응시준비와 무관. 힌트/대리처리/실패수정/소요시간은 별도 표시.",
            "hints_used": S["hints_used"], "admin_assisted": S["admin_assisted"], "resets": len(S["resets"]), "failed_events": sum(1 for e in S["audit"] if e["outcome"] in ("failed", "blocked"))}


def evidence(S):
    sqls = [{"code_hash": e["code_hash"], "outcome": e["outcome"], "principal": e["effective_principal"], "clock": e["scenario_clock"], "level": e["evidence_level"]} for e in S["audit"] if e["event_type"] in ("SQL_EXECUTED", "SQL_FAILED", "SQL_PERMISSION_DENIED")]
    return {
        "report": "WIZBASE DBX Project Rehearsal 증거 보고서 (교육 환경, Databricks 공식 서비스·인증 아님)",
        "mode": S["mode"], "learning_mode": S["learning_mode"], "profile": profile_of(S), "seed": S["seed"], "scenario_clock_base": seedmod.BASE_CLOCK,
        "data_digest_initial": S["data_digest0"], "data_digest_current": data_digest(S), "policy_version": S["policy"]["active"],
        "verification_levels_note": "SQL 결과=LOCAL_EXECUTED(DuckDB), 그 외 리소스·승인·가상 API=SIMULATED. DBX_VERIFIED/WORKSPACE_CHECKED/SA_REVIEWED 없음.",
        "timeline": [{"t": e["scenario_clock"], "type": e["event_type"], "actor": e["actor_id"], "principal": e["effective_principal"], "outcome": e["outcome"], "level": e["evidence_level"], "trace": e["trace_id"]} for e in S["audit"]],
        "sql_evidence": sqls, "approvals": list(S["approvals"].values()), "proposals": [{k: v for k, v in p.items() if k != "alt"} for p in S["proposals"].values()],
        "ax_actions": list(S["ax_idem"].values()), "tickets": S["tickets"], "score": score(S), "progress": progress(S), "faults_injected": S["fault_log"], "resets": S["resets"],
        "limitations": ["Spark/Databricks 의미 차이 가능(타입·null·decimal·시간)", "Python/PySpark/MLflow 실제 실행 없음(격리 실행기 미구성)",
                        "실제 교육용 DBX(C 모드)·한국 SA 검토 미수행", "시뮬레이터 점수는 공식 인증·시험 합격을 의미하지 않음"],
    }


def replay_digest(S):
    """AT-20: deterministic replay of the command log in a fresh session; compare data digests."""
    owner = {"user_id": "replay", "role": "learner"}
    R = create_session("replay", S["lesson_id"], S["mode"], S["learning_mode"], S.get("seed", seedmod.SEED_NAME))
    try:
        staff = {"user_id": "replay", "role": "instructor"}
        for cmd in S["cmd_log"]:
            try:
                a = staff if cmd["actor_role"] != "learner" else owner
                if cmd["type"].startswith("api."):
                    api(R, a, cmd["type"][4:], dict(cmd["payload"]))
                else:
                    commands(R, a, cmd["type"], dict(cmd["payload"]))
            except ApiError:
                pass
        return {"original": data_digest(S), "replayed": data_digest(R), "match": data_digest(S) == data_digest(R),
                "nondeterministic_elements": ["tickets/approvals는 별도 API 호출이라 command log 재생에 미포함(데이터 digest는 영향 없음)"]}
    finally:
        c = _conns.pop(R["id"], None)
        if c:
            c.close()
        SESSIONS.pop(R["id"], None)
        for p in DATA.glob(f"{R['id']}*"):
            try:
                p.unlink()
            except OSError:
                pass
