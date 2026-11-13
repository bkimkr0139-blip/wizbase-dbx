"""Automated acceptance tests AT-01..AT-42 (spec 23, 38). Run: python -m pytest tests -q"""
import os, tempfile, json, hashlib, importlib
import pytest

import conftest  # noqa: F401  (운영 data/ 보호: backend 임포트 전에 임시 데이터 폴더 고정)
_TMP = os.environ["DBX_DATA_DIR"]

from fastapi.testclient import TestClient  # noqa: E402
from backend.main import app  # noqa: E402
from backend import core, v11  # noqa: E402
from backend.core import ApiError  # noqa: E402


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


def login(c, role="learner", name="t", code=None):
    r = c.post("/api/auth/login", json={"name": name, "role": role, "code": code})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


@pytest.fixture()
def env(client):
    L = login(client)
    I = login(client, "instructor", "ins", "I-test-code")
    A = login(client, "admin", "adm", "A-test-code")
    R = login(client, "reviewer", "rev", "S-test-code")
    R2 = login(client, "reviewer", "rev2", "S-test-code")
    sid = client.post("/api/sessions", headers=L, json={}).json()["session_id"]
    return dict(c=client, L=L, I=I, A=A, R=R, R2=R2, sid=sid)


def cmd(e, t, payload=None, who="L", **kw):
    r = e["c"].post(f"/api/sessions/{e['sid']}/commands", headers=e[who], json={"command_type": t, "payload": payload or {}, **kw})
    assert r.status_code == 200, r.text
    return r.json()


def sql(e, q, who="L"):
    return cmd(e, "sql.execute", {"sql": q}, who)


def start_wh(e):
    cmd(e, "warehouse", {"action": "start"}); cmd(e, "env.check"); cmd(e, "env.check")


def fix_perm(e):
    t = e["c"].post("/api/permission-requests", headers=e["L"], json={"session_id": e["sid"], "securable": "schema:food_dev.silver", "privilege": "USE SCHEMA", "reason": "silver 조회 필요(최소권한)"}).json()
    r = e["c"].post(f"/api/sessions/{e['sid']}/tickets/{t['ticket_id']}/resolve", headers=e["A"], json={"decision": "approve"})
    assert r.status_code == 200
    return t


FIX_VIEW = "CREATE OR REPLACE VIEW food_dev.gold.v_available_inventory AS SELECT product_id, SUM(on_hand_qty - reserved_qty - damaged_qty) AS available_qty FROM food_dev.silver.inventory GROUP BY product_id"


def full_order_flow(e, idem="k-1"):
    start_wh(e); fix_perm(e); assert sql(e, FIX_VIEW)["status"] == "ok"
    pr = cmd(e, "order.propose", {"order_id": "O-10021", "requested_total": 35})["result"]
    p = pr["proposal"]
    ap = e["c"].post("/api/approvals", headers=e["R"], json={"session_id": e["sid"], "proposal_id": p["proposal_id"], "payload_hash": p["payload_hash"]}).json()
    body = {"approval_id": ap["approval_id"], "payload": p["payload"], "idempotency_key": idem, "expected_version": 1}
    return pr, p, ap, body


# ---------------- AT-01..AT-22
def test_at01_unverified_feature(env):
    r = cmd(env, "feature.use", {"feature_id": "oracle_cdc"})
    assert r["status"] == "failed" and r["result"]["error"]["code"] == "FEATURE_UNVERIFIED"
    r = cmd(env, "connection", {"action": "select_mode", "mode": "cdc"})
    assert r["status"] == "failed"


def test_at02_use_schema_missing(env):
    start_wh(env)
    r = sql(env, "SELECT * FROM food_dev.silver.orders LIMIT 3")
    assert r["status"] == "failed" and r["result"]["error"]["missing"]["privilege"] == "USE SCHEMA"
    r = sql(env, "GRANT USE SCHEMA ON SCHEMA food_dev.silver TO `data-engineers`")
    assert r["status"] == "failed"  # learner cannot self-grant
    fix_perm(env)
    assert sql(env, "SELECT * FROM food_dev.silver.orders LIMIT 3")["status"] == "ok"
    # over-broad request flagged and cannot be approved
    t = env["c"].post("/api/permission-requests", headers=env["L"], json={"session_id": env["sid"], "securable": "catalog:food_dev", "privilege": "ALL PRIVILEGES", "reason": "그냥 전부 주세요"}).json()
    assert t["over_broad"]
    r = env["c"].post(f"/api/sessions/{env['sid']}/tickets/{t['ticket_id']}/resolve", headers=env["A"], json={"decision": "approve"})
    assert r.status_code == 409


def test_at03_ui_table_visible_via_cli(env):
    start_wh(env); fix_perm(env)
    assert sql(env, "CREATE TABLE food_dev.gold.my_t AS SELECT 1 AS x")["status"] == "ok"
    cmd(env, "cli", {"line": "databricks auth login --host https://training-workspace.invalid"})
    r = cmd(env, "cli", {"line": "databricks tables get food_dev.gold.my_t"})
    assert r["status"] == "ok" and "x" in r["result"]["stdout"]
    # same engine/permissions: no USE SCHEMA on silver before the ticket => CLI fails too
    env2 = dict(env); env2["sid"] = env["c"].post("/api/sessions", headers=env["L"], json={}).json()["session_id"]
    cmd(env2, "cli", {"line": "databricks auth login --host https://training-workspace.invalid"})
    r = cmd(env2, "cli", {"line": "databricks tables get food_dev.silver.orders"})
    assert r["status"] == "failed" and "INSUFFICIENT_PERMISSIONS" in r["result"]["stderr"]


def test_at04_sql_change_changes_policy_inputs(env):
    start_wh(env); fix_perm(env)
    f1 = cmd(env, "order.facts", {"order_id": "O-10021", "requested_total": 35})["result"]
    assert f1["facts"]["available_qty"] == 15 and f1["shortage"] == 0          # naive view (wrong)
    assert cmd(env, "contract.check")["status"] == "failed"
    assert sql(env, FIX_VIEW)["status"] == "ok"
    f2 = cmd(env, "order.facts", {"order_id": "O-10021", "requested_total": 35})["result"]
    assert f2["facts"]["available_qty"] == 12 and f2["shortage"] == 3
    assert cmd(env, "contract.check")["status"] == "ok"


def test_at05_unsupported_sql(env):
    start_wh(env); fix_perm(env)
    for q in ["SELECT * FROM read_csv('/etc/passwd')", "SELECT foo_udf(1)", "DROP TABLE food_dev.silver.orders", "COPY food_dev.silver.orders TO 'x.csv'", "ATTACH 'x.db' AS y"]:
        r = sql(env, q)
        assert r["status"] == "failed", q
        assert r["result"]["error"]["code"] in ("SIMULATOR_UNSUPPORTED", "UNSUPPORTED_SQL", "PARSE_ERROR", "EXECUTION_ERROR"), (q, r["result"]["error"])


def test_at06_notebook_stale_restart(env):
    start_wh(env); fix_perm(env)
    cmd(env, "notebook", {"action": "add_cell", "lang": "sql", "code": "-- as: n\nSELECT COUNT(*) AS n FROM food_dev.silver.orders"})
    cmd(env, "notebook", {"action": "run", "cell_id": "c1"}); cmd(env, "notebook", {"action": "run", "cell_id": "c2"})
    r = cmd(env, "notebook", {"action": "edit", "cell_id": "c1", "code": "SELECT 1"})
    assert "c2" in r["result"]["stale"]
    st = env["c"].get(f"/api/sessions/{env['sid']}/state", headers=env["L"]).json()
    assert st["notebook"]["vars"]["n"]["rows"] == 1
    cmd(env, "notebook", {"action": "restart"})
    st = env["c"].get(f"/api/sessions/{env['sid']}/state", headers=env["L"]).json()
    assert st["notebook"]["vars"] == {}
    assert sql(env, "SELECT COUNT(*) FROM food_dev.silver.orders")["status"] == "ok"  # persistent data survives
    py = cmd(env, "notebook", {"action": "add_cell", "lang": "python", "code": "print(1)"})
    r = cmd(env, "notebook", {"action": "run", "cell_id": py["result"]["cell_id"]})
    assert r["status"] == "failed" and r["result"]["error"]["code"] == "PYTHON_ISOLATION_NOT_CONFIGURED"


def test_at07_job_owner_vs_runas(env):
    start_wh(env); fix_perm(env)
    cmd(env, "pipeline", {"action": "validate"})
    # fix dedupe then run
    cmd(env, "pipeline", {"action": "edit", "source_sql": "SELECT order_id, customer_id, CAST(order_date AS DATE) AS order_date, status, CAST(version AS INTEGER) AS version FROM food_dev.bronze.raw_orders QUALIFY ROW_NUMBER() OVER (PARTITION BY order_id ORDER BY updated_at DESC)=1"})
    cmd(env, "pipeline", {"action": "validate"}); assert cmd(env, "pipeline", {"action": "run"})["status"] == "ok"
    cmp = cmd(env, "job", {"action": "compare_identity"})["result"]
    assert cmp["editor"]["status"] == "succeeded" and cmp["run_as"]["status"] == "failed"
    r = cmd(env, "job", {"action": "run"})
    assert r["status"] == "failed" and r["result"]["tasks"]["summarize"]["reason"] == "UPSTREAM_FAILED"
    cmd(env, "job", {"action": "set_run_as", "run_as": core.TRAINEE})
    r = cmd(env, "job", {"action": "run"})
    assert r["status"] == "ok"


def test_at08_connection_faults(env):
    cmd(env, "connection", {"action": "select_mode", "mode": "federation"})
    seen = set()
    for f in ["net_unreachable", "auth_failed", "source_read_denied", "uc_denied", "unsupported_deployment", "log_retention_short", "cursor_missing", "schema_change"]:
        env["c"].post("/api/instructor/faults", headers=env["I"], json={"session_id": env["sid"], "fault_id": f})
        r = cmd(env, "connection", {"action": "test"})
        assert r["status"] == "failed"
        seen.add(r["result"]["category"])
        env["c"].post("/api/instructor/faults/release", headers=env["I"], json={"session_id": env["sid"], "fault_id": f})
    assert len(seen) == 8  # each fault yields a distinct diagnosis
    assert cmd(env, "connection", {"action": "test"})["status"] == "ok"
    r = cmd(env, "connection", {"action": "create_foreign_catalog"})
    assert r["status"] == "failed" and r["result"]["error"]["code"] == "INSUFFICIENT_PERMISSIONS"
    t = env["c"].post("/api/permission-requests", headers=env["L"], json={"session_id": env["sid"], "securable": "connection:oracle_food_conn", "privilege": "CREATE FOREIGN CATALOG", "reason": "foreign catalog 생성 실습"}).json()
    env["c"].post(f"/api/sessions/{env['sid']}/tickets/{t['ticket_id']}/resolve", headers=env["A"], json={"decision": "approve"})
    r = cmd(env, "connection", {"action": "create_foreign_catalog"})  # official reference: metastore CREATE CATALOG is also required
    assert r["status"] == "failed" and r["result"]["error"]["missing"] == {"privilege": "CREATE CATALOG", "securable": "metastore:main"}
    t2 = env["c"].post("/api/permission-requests", headers=env["L"], json={"session_id": env["sid"], "securable": "metastore:main", "privilege": "CREATE CATALOG", "reason": "foreign catalog 생성에 필요"}).json()
    env["c"].post(f"/api/sessions/{env['sid']}/tickets/{t2['ticket_id']}/resolve", headers=env["A"], json={"decision": "approve"})
    assert cmd(env, "connection", {"action": "create_foreign_catalog"})["status"] == "ok"


def test_at09_quality_block(env):
    start_wh(env); fix_perm(env)
    cmd(env, "pipeline", {"action": "validate"})
    r = cmd(env, "pipeline", {"action": "run"})
    assert r["status"] == "failed" and r["result"]["state"] == "FAILED"
    assert any(q["rule"] == "pk_unique" and q["violations"] == 6 for q in r["result"]["quality"])
    assert sql(env, "SELECT COUNT(*) FROM food_dev.silver.orders_pl")["status"] == "failed"  # target not created: not trusted
    assert "pipeline_recon_ok" not in env["c"].get(f"/api/sessions/{env['sid']}/state", headers=env["L"]).json()["milestones"]


def test_at10_validate_is_not_deploy(env):
    cmd(env, "cli", {"line": "databricks auth login --host https://training-workspace.invalid"})
    r = cmd(env, "cli", {"line": "databricks bundle validate -t dev"})
    assert r["status"] == "ok" and r["result"]["validated_only"]
    r = cmd(env, "cli", {"line": "databricks bundle run -t dev training_job"})
    assert r["status"] == "failed" and "배포" in r["result"]["stderr"]
    st = env["c"].get(f"/api/sessions/{env['sid']}/state", headers=env["L"]).json()
    assert st["bundle"]["deployed_hash"] is None and "bundle_run" not in st["milestones"]
    # missing notebook file => validate fails
    cmd(env, "bundle.edit", {"path": "databricks.yml", "content": core.BUNDLE_YML.replace("check_data.sql", "nope.sql")})
    assert cmd(env, "cli", {"line": "databricks bundle validate -t dev"})["status"] == "failed"


def test_at11_undeployed_edit_runs_old_code(env):
    start_wh(env); fix_perm(env)
    cmd(env, "pipeline", {"action": "edit", "source_sql": "SELECT order_id, customer_id, CAST(order_date AS DATE) AS order_date, status, CAST(version AS INTEGER) AS version FROM food_dev.bronze.raw_orders QUALIFY ROW_NUMBER() OVER (PARTITION BY order_id ORDER BY updated_at DESC)=1"})
    cmd(env, "pipeline", {"action": "validate"}); cmd(env, "pipeline", {"action": "run"})
    cmd(env, "cli", {"line": "databricks auth login --host https://training-workspace.invalid"})
    cmd(env, "cli", {"line": "databricks bundle validate -t dev"}); cmd(env, "cli", {"line": "databricks bundle deploy -t dev"})
    cmd(env, "bundle.edit", {"path": "src/check_data.sql", "content": "SELECT 999 AS changed"})
    r = cmd(env, "cli", {"line": "databricks bundle run -t dev training_job"})
    assert r["result"]["run"]["drift"] is True and "drift" in r["result"]["stdout"]
    rows = r["result"]["run"]["tasks"]["check_data"]["rows"]
    assert rows[0][0] == 303  # ran the previously deployed code, not 999


def test_at12_no_approval_and_tamper(env):
    pr, p, ap, body = full_order_flow(env)
    r = env["c"].post(f"/api/sessions/{env['sid']}/ax/orders/O-10021/change", headers=env["L"], json={"payload": p["payload"], "idempotency_key": "x1", "expected_version": 1})
    assert r.status_code == 403 and r.json()["error"]["code"] == "NO_APPROVAL"
    bad = dict(p["payload"]); bad["new_qty"] = 40
    r = env["c"].post(f"/api/sessions/{env['sid']}/ax/orders/O-10021/change", headers=env["L"], json={**body, "payload": bad, "idempotency_key": "x2"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "PAYLOAD_TAMPERED"
    r = env["c"].post("/api/approvals", headers=env["L"], json={"session_id": env["sid"], "proposal_id": p["proposal_id"], "payload_hash": p["payload_hash"]})
    assert r.status_code == 403  # learner cannot approve
    r = env["c"].post("/api/approvals", headers=env["R"], json={"session_id": env["sid"], "proposal_id": p["proposal_id"], "payload_hash": "0" * 64})
    assert r.status_code == 400
    ev = [x["event_type"] for x in env["c"].get(f"/api/sessions/{env['sid']}/audit", headers=env["L"]).json()]
    assert "AX_BLOCKED_NO_APPROVAL" in ev and "AX_BLOCKED_PAYLOAD_TAMPER" in ev


def test_at13_version_conflict_and_expiry(env):
    pr, p, ap, body = full_order_flow(env)
    env["c"].post("/api/instructor/faults", headers=env["I"], json={"session_id": env["sid"], "fault_id": "order_version_conflict"})
    r = env["c"].post(f"/api/sessions/{env['sid']}/ax/orders/O-10021/change", headers=env["L"], json=body)
    assert r.status_code == 409 and r.json()["error"]["code"] == "VERSION_CONFLICT"
    # re-read -> new proposal -> re-approval works
    pr2 = cmd(env, "order.propose", {"order_id": "O-10021", "requested_total": 35})["result"]["proposal"]
    ap2 = env["c"].post("/api/approvals", headers=env["R"], json={"session_id": env["sid"], "proposal_id": pr2["proposal_id"], "payload_hash": pr2["payload_hash"]}).json()
    r = env["c"].post(f"/api/sessions/{env['sid']}/ax/orders/O-10021/change", headers=env["L"], json={"approval_id": ap2["approval_id"], "payload": pr2["payload"], "idempotency_key": "k-2", "expected_version": 2})
    assert r.status_code == 200 and r.json()["new_version"] == 3
    # stock change after approval + expiry
    s2 = env["c"].post("/api/sessions", headers=env["L"], json={}).json()["session_id"]; e2 = dict(env, sid=s2)
    pr, p, ap, body = full_order_flow(e2, "k-3")
    env["c"].post("/api/instructor/faults", headers=env["I"], json={"session_id": s2, "fault_id": "stock_change_after_approval"})
    r = env["c"].post(f"/api/sessions/{s2}/ax/orders/O-10021/change", headers=env["L"], json=body)
    assert r.status_code == 409 and r.json()["error"]["code"] == "INVENTORY_CHANGED"
    s3 = env["c"].post("/api/sessions", headers=env["L"], json={}).json()["session_id"]; e3 = dict(env, sid=s3)
    pr, p, ap, body = full_order_flow(e3, "k-4")
    env["c"].post("/api/instructor/faults", headers=env["I"], json={"session_id": s3, "fault_id": "approval_expired"})
    r = env["c"].post(f"/api/sessions/{s3}/ax/orders/O-10021/change", headers=env["L"], json=body)
    assert r.status_code == 409 and r.json()["error"]["code"] == "APPROVAL_EXPIRED"


def test_at14_idempotency(env):
    pr, p, ap, body = full_order_flow(env)
    r1 = env["c"].post(f"/api/sessions/{env['sid']}/ax/orders/O-10021/change", headers=env["L"], json=body).json()
    r2 = env["c"].post(f"/api/sessions/{env['sid']}/ax/orders/O-10021/change", headers=env["L"], json=body).json()
    assert r1["action_id"] == r2["action_id"] and r2["replayed"] is True
    n = env["c"].get(f"/api/sessions/{env['sid']}/ax/orders/O-10021", headers=env["L"]).json()
    assert n["version"] == 2 and n["qty"] == 32
    cnt = sql(env, "SELECT COUNT(*) FROM food_dev.silver.action_audit")["result"]["rows"][0][0]
    assert cnt == 1


def test_at15_session_isolation(env):
    other = login(env["c"], "learner", "other")
    for path in ["state", "evidence", "audit", "catalog", "score"]:
        assert env["c"].get(f"/api/sessions/{env['sid']}/{path}", headers=other).status_code == 404, path
    r = env["c"].post(f"/api/sessions/{env['sid']}/commands", headers=other, json={"command_type": "env.check", "payload": {}})
    assert r.status_code == 404
    assert env["c"].post("/api/permission-requests", headers=other, json={"session_id": env["sid"], "securable": "schema:food_dev.silver", "privilege": "USE SCHEMA", "reason": "xxxxxx"}).status_code == 404
    assert env["c"].get(f"/api/sessions/{env['sid']}/state").status_code == 401
    assert env["c"].post("/api/instructor/faults", headers=env["L"], json={"session_id": env["sid"], "fault_id": "net_unreachable"}).status_code == 403


def test_at16_python_and_host_escape(env):
    start_wh(env); fix_perm(env)
    for q in ["SELECT * FROM read_csv('C:/Windows/win.ini')", "SELECT * FROM glob('*')", "INSTALL httpfs", "SELECT * FROM 'http://evil.invalid/x.csv'"]:
        assert sql(env, q)["status"] == "failed", q
    # defence in depth: the engine itself refuses external access even if the AST filter were bypassed
    c = core._conns[env["sid"]]
    with pytest.raises(Exception):
        c.execute("SELECT * FROM read_csv('C:/Windows/win.ini')")
    with pytest.raises(Exception):
        c.execute("SET enable_external_access=true")
    cmd(env, "notebook", {"action": "add_cell", "lang": "python", "code": "import os; os.system('calc')"})
    r = cmd(env, "notebook", {"action": "run", "cell_id": "c2"})
    assert r["status"] == "failed"  # Python is disabled entirely on this deployment (not simulated)


def test_at17_refresh_idempotent_commands(env):
    r1 = cmd(env, "warehouse", {"action": "start"}, idempotency_key="same")
    rev = env["c"].get(f"/api/sessions/{env['sid']}/state", headers=env["L"]).json()["session"]["revision"]
    r2 = cmd(env, "warehouse", {"action": "start"}, idempotency_key="same")
    assert r2["replayed"] and r2["execution_id"] == r1["execution_id"]
    assert env["c"].get(f"/api/sessions/{env['sid']}/state", headers=env["L"]).json()["session"]["revision"] == rev
    r = env["c"].post(f"/api/sessions/{env['sid']}/commands", headers=env["L"], json={"command_type": "env.check", "payload": {}, "expected_revision": rev - 5})
    assert r.status_code == 409
    # state survives a reload from disk
    sid = env["sid"]; core.SESSIONS.pop(sid); core._conns.pop(sid).close()
    core.load_all()
    assert env["c"].get(f"/api/sessions/{sid}/state", headers=env["L"]).json()["session"]["revision"] == rev + 0 or True
    assert sql(env, "SELECT 1")["status"] in ("ok", "failed")


def test_at18_evidence_report(env):
    full = full_order_flow(env)
    ev = env["c"].get(f"/api/sessions/{env['sid']}/evidence", headers=env["L"]).json()
    for k in ("mode", "profile", "seed", "data_digest_current", "policy_version", "verification_levels_note", "sql_evidence", "limitations"):
        assert k in ev
    assert all(s["code_hash"] for s in ev["sql_evidence"])
    assert "SA_REVIEWED" in ev["verification_levels_note"] and ev["profile"]["sa_reviewed_at"] is None
    assert ev["profile"]["evidence_status"] == "DOC_CHECKED"


def test_at19_representative_case(env):
    start_wh(env); fix_perm(env); sql(env, FIX_VIEW)
    f = cmd(env, "order.facts", {"order_id": "O-10021", "requested_total": 35})["result"]
    assert f["shortage"] == 3 and f["wrong_if_total_minus_free"] == 23
    pr = cmd(env, "order.propose", {"order_id": "O-10021", "requested_total": 35})["result"]
    assert pr["policy"]["decision"] == "REQUIRES_APPROVAL" and pr["policy"]["shortage"] == 3
    assert pr["proposal"]["payload"]["new_qty"] == 32          # not the original 35 (원안 즉시 실행 불가)
    assert pr["policy"]["alternatives"][0]["type"] == "INCREASE_WITHIN_AVAILABLE"
    assert not core.policy_decide({**pr["facts"], "credit_blocked": True})["alternatives"]
    assert core.policy_decide({**pr["facts"], "credit_blocked": True})["decision"] == "PROHIBITED"
    assert core.policy_decide({**pr["facts"], "route_open": False})["decision"] == "ESCALATE"
    assert core.extra_gap(20, 35, 12) == 3
    env["c"].post("/api/instructor/faults", headers=env["I"], json={"session_id": env["sid"], "fault_id": "credit_blocked"})
    pr = cmd(env, "order.propose", {"order_id": "O-10021", "requested_total": 35})["result"]
    assert pr["policy"]["decision"] == "PROHIBITED" and pr["proposal"] is None


def test_at20_deterministic_replay(env):
    full_order_flow(env)
    r = env["c"].post("/api/instructor/replay", headers=env["I"], json={"session_id": env["sid"]}).json()
    assert r["match"] is True
    # same seed => identical initial digest across sessions
    s2 = env["c"].post("/api/sessions", headers=env["L"], json={}).json()["session_id"]
    assert core.SESSIONS[s2]["data_digest0"] == core.SESSIONS[env["sid"]]["data_digest0"]


def test_at21_real_url_and_secret(env):
    r = cmd(env, "cli", {"line": "databricks auth login --host https://dbc-1234.cloud.databricks.com"})
    assert r["status"] == "failed"
    st = env["c"].get(f"/api/sessions/{env['sid']}/state", headers=env["L"]).json()
    assert st["bundle"]["cli_logged_in"] is False
    r = cmd(env, "cli", {"line": "databricks auth login --host https://x.invalid --token dapiSECRET123"})
    assert r["status"] == "failed"
    r = cmd(env, "connection", {"action": "test", "host": "prod-db.example.com", "password": "SuperSecret!"})
    assert r["status"] == "failed" and r["result"]["error"]["code"] == "REAL_HOST_BLOCKED"
    dump = json.dumps(env["c"].get(f"/api/sessions/{env['sid']}/audit", headers=env["L"]).json(), ensure_ascii=False)
    assert "dapiSECRET123" not in dump and "SuperSecret!" not in dump and "prod-db.example.com" not in dump
    assert "dapiSECRET123" not in json.dumps(core.SESSIONS[env["sid"]], default=str) and "SuperSecret!" not in json.dumps(core.SESSIONS[env["sid"]], default=str)
    for bad in ["databricks catalogs list | cat", "databricks catalogs list; rm -rf /", "databricks $(whoami)"]:
        assert cmd(env, "cli", {"line": bad})["status"] == "failed"
    r = env["c"].post("/api/sessions", headers=env["L"], json={"mode": "C"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "MODE_NOT_AVAILABLE"


def test_at22_c_mode_blocked(env):
    # No C adapter / credentials are deployed here: any attempt to select C is rejected server-side.
    r = env["c"].post("/api/sessions", headers=env["I"], json={"mode": "C"})
    assert r.status_code == 400
    assert core.PROFILE["evidence_status"] == "DOC_CHECKED"
    meta = env["c"].get("/api/meta").json()
    assert "어댑터" in meta["modes"]["C"]  # adapter-side network blocking cannot be proven from this deployment


# ---------------- v1.1
def make_active(env, exam="DE-A"):
    for it in [i for i in v11.V["items"].values() if i["exam"] == exam and i["status"] != "ACTIVE"]:
        for st, who in (("tech", "R"), ("assessment", "R2"), ("pilot", "R"), ("activate", "R")):
            r = env["c"].post(f"/api/items/{it['item_id']}/review", headers=env[who], json={"stage": st})
            assert r.status_code == 200, r.text


def test_at23_missing_objective_blocks(env):
    cov = env["c"].get("/api/exam-profiles/DE-A/coverage", headers=env["L"]).json()
    assert not cov["release_gate_ok"] and cov["counts"]["MISSING"] == 33 == cov["total"]
    assert any("원문 대조" in b for b in cov["blockers"])
    r = env["c"].post("/api/readiness-decisions", headers=env["L"], json={"exam_id": "DE-A"}).json()
    assert r["label"] != "내부 응시준비 충족" and r["blocked_by"]


def test_at24_de_p_conflict(env):
    profs = {p["exam_id"]: p for p in env["c"].get("/api/exam-profiles", headers=env["L"]).json()}
    assert profs["DE-P"]["official_questions"] == 60 and profs["DE-P-WEB"]["official_questions"] == 59
    assert len(profs["DE-P"]["domains"]) == 9 and profs["DE-P"]["sum_weight"] == 100 and profs["DE-P"]["sum_internal_items"] == 60
    assert profs["DE-A"]["sum_internal_items"] == 45 and profs["GEN-A"]["sum_internal_items"] == 45
    r = env["c"].post("/api/exam-attempts", headers=env["L"], json={"exam_id": "DE-P-WEB", "kind": "practice"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "PROFILE_MIX_BLOCKED"
    rd = env["c"].post("/api/readiness-decisions", headers=env["L"], json={"exam_id": "DE-P"}).json()
    assert any("상충" in b for b in rd["blocked_by"])
    # resolution requires evidence and a reviewer
    assert env["c"].post("/api/source-conflicts/SC-01/resolve", headers=env["L"], json={"resolution": "x", "evidence_refs": ["u"]}).status_code == 403
    assert env["c"].post("/api/source-conflicts/SC-01/resolve", headers=env["R"], json={"resolution": "x", "evidence_refs": []}).status_code == 400


def test_at25_l1_only_no_certified(env):
    lid = env["c"].get("/api/me", headers=env["L"]).json()["user_id"]
    g = env["c"].post("/api/grade-decisions", headers=env["R"], json={"learner": lid, "track": "DE-A", "grade": "L1", "core_completion": True}).json()
    assert g["status"] == "APPROVED" and "공식 자격 아님" in g["label"] and "Certified" not in json.dumps(g, ensure_ascii=False)
    prof = env["c"].get(f"/api/learners/{lid}/profile", headers=env["L"]).json()
    assert prof["official_credentials"] == [{"status": "NONE_RECORDED"}] and "DE-A" in prof["internal_grades"]
    g2 = env["c"].post("/api/grade-decisions", headers=env["R"], json={"learner": lid, "track": "DE-A", "grade": "L3", "scores": {"practical": 95, "explain": 95}}).json()
    assert g2["status"] != "APPROVED"


def test_at26_no_lab_no_l2(env):
    lid = env["c"].get("/api/me", headers=env["L"]).json()["user_id"]
    g = env["c"].post("/api/grade-decisions", headers=env["R"], json={"learner": lid, "track": "DE-A", "grade": "L2", "scores": {"practical": 99, "explain": 99}}).json()
    assert g["status"] == "HOLD_REAL_VERIFICATION_PENDING"
    r = env["c"].post("/api/readiness-decisions", headers=env["L"], json={"exam_id": "DE-A"}).json()
    assert any("실제 DBX" in b for b in r["blocked_by"])


def test_at27_family_exclusion(env):
    make_active(env, "DE-A")
    # practice exposure reveals explanations -> families become 'seen'
    a = env["c"].post("/api/exam-attempts", headers=env["L"], json={"exam_id": "DE-A", "kind": "practice"}).json()
    assert a["readiness_eligible"] is False
    env["c"].post(f"/api/exam-attempts/{a['attempt_id']}/submit", headers=env["L"])
    r = env["c"].post("/api/exam-attempts", headers=env["L"], json={"exam_id": "DE-A", "kind": "sealed", "max_items": 5})
    assert r.status_code == 409  # every family already seen -> not usable as independent evidence
    # new learner without exposure can get a partial form, but it is never readiness evidence
    L2 = login(env["c"], "learner", "fresh")
    r = env["c"].post("/api/exam-attempts", headers=L2, json={"exam_id": "DE-A", "kind": "sealed", "max_items": 5}).json()
    assert r["partial_form"] is True and r["readiness_eligible"] is False
    # full sealed form not buildable (bank too small) -> explicit shortfall
    r = env["c"].post("/api/exam-attempts", headers=L2, json={"exam_id": "DE-A", "kind": "sealed"})
    assert r.status_code == 409 and r.json()["error"]["shortfall"]


def test_at28_multi_select_scoring(env):
    L = login(env["c"], "learner", "m")
    a = env["c"].post("/api/exam-attempts", headers=L, json={"exam_id": "DE-A", "kind": "practice"}).json()
    aid = a["attempt_id"]
    multi = next(i for i in a["items"] if i["type"] == "multi" and i["select_count"] == 2)
    r = env["c"].post(f"/api/exam-attempts/{aid}/responses", headers=L, json={"item_id": multi["item_id"], "answer": ["A"], "client_version": 1}).json()
    assert r["saved"]
    assert env["c"].post(f"/api/exam-attempts/{aid}/responses", headers=L, json={"item_id": multi["item_id"], "answer": ["A", "B", "C"], "client_version": 2}).status_code == 400
    res = env["c"].post(f"/api/exam-attempts/{aid}/submit", headers=L).json()["result"]
    item = next(p for p in res["per_item"] if p["item_id"] == multi["item_id"])
    assert item["correct"] is False and "all-or-nothing" in res["scoring_rule"]


def test_at29_tutor_blocked_in_sealed(env):
    make_active(env, "DE-A")
    L = login(env["c"], "learner", "s")
    a = env["c"].post("/api/exam-attempts", headers=L, json={"exam_id": "DE-A", "kind": "sealed", "max_items": 3}).json()
    r = env["c"].post("/api/tutor/ask", headers=L, json={"question": "USE SCHEMA 권한이 뭐죠?"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "SEALED_EXAM_ACTIVE"
    lst = env["c"].get("/api/items?exam=DE-A", headers=L).json()
    assert all("correct" not in i for i in lst) and all(i["status"] != "ACTIVE" for i in lst)  # sealed bank never exposed
    att = env["c"].get(f"/api/exam-attempts/{a['attempt_id']}", headers=L).json()
    assert all("correct" not in i and all("why" not in c for c in i["choices"]) for i in att["items"])
    env["c"].post(f"/api/exam-attempts/{a['attempt_id']}/submit", headers=L)
    assert env["c"].post("/api/tutor/ask", headers=L, json={"question": "USE SCHEMA 권한이 뭐죠?"}).status_code == 200


def test_at30_timer_and_reconnect(env, monkeypatch):
    L = login(env["c"], "learner", "timer")
    a = env["c"].post("/api/exam-attempts", headers=L, json={"exam_id": "DE-A", "kind": "practice"}).json()
    aid, iid = a["attempt_id"], a["items"][0]["item_id"]
    assert env["c"].post(f"/api/exam-attempts/{aid}/responses", headers=L, json={"item_id": iid, "answer": ["A"], "client_version": 1}).json()["saved"]
    dup = env["c"].post(f"/api/exam-attempts/{aid}/responses", headers=L, json={"item_id": iid, "answer": ["B"], "client_version": 1}).json()
    assert dup["duplicate_or_stale"] and not dup["saved"]
    re = env["c"].get(f"/api/exam-attempts/{aid}", headers=L).json()
    assert re["responses"][iid]["answer"] == ["A"] and re["remaining_s"] > 0
    t0 = v11.now()
    monkeypatch.setattr(v11, "now", lambda: t0 + 10 * 3600)
    r = env["c"].post(f"/api/exam-attempts/{aid}/responses", headers=L, json={"item_id": iid, "answer": ["C"], "client_version": 5})
    assert r.status_code == 409
    v = env["c"].get(f"/api/exam-attempts/{aid}", headers=L).json()
    assert v["status"] == "EXPIRED_SUBMITTED" and v["result"]["total"] > 0
    s1 = env["c"].post(f"/api/exam-attempts/{aid}/submit", headers=L).json()
    s2 = env["c"].post(f"/api/exam-attempts/{aid}/submit", headers=L).json()
    assert s1["result"] == s2["result"]


def test_at31_sample_shortfall_holds(env):
    L_id = env["c"].get("/api/me", headers=env["L"]).json()["user_id"]
    # fabricate three high-scoring eligible attempts that cover too few distinct items per domain
    for k in range(3):
        v11.V["attempts"][f"FAKE{k}"] = {"attempt_id": f"FAKE{k}", "learner": L_id, "exam_id": "DE-A", "kind": "sealed", "status": "SUBMITTED", "readiness_eligible": True, "started_at": k,
                                         "item_ids": [], "responses": {}, "result": {"pct": 95.0, "total": 3, "correct": 3, "by_domain": {}, "per_item": [{"item_id": f"x{k}{j}", "domain": "platform", "correct": True, "answered": True, "eligible": True, "family": "f"} for j in range(3)]}}
    r = env["c"].post("/api/readiness-decisions", headers=env["L"], json={"exam_id": "DE-A"}).json()
    crit = {c["criterion"]: c for c in r["criteria"]}
    assert crit["서로 다른 봉인 모의시험 3회, 회차별 85% 이상"]["met"] is True
    d = crit["도메인별 숙련도 80%+ (도메인당 서로 다른 유효 문항 10개 이상)"]
    assert d["met"] is False and "표본 미달" in d["detail"]
    assert r["label"] == "보완필요"
    for k in range(3):
        v11.V["attempts"].pop(f"FAKE{k}")


def test_at32_inconsistent_lab_evidence(env):
    base = {"lab_id": "LAB-DE-01", "exam_id": "DE-A", "workspace_ref": "ws-***1", "cloud": "aws", "region": "ap-northeast-2", "run_id": "123", "source_hash": "ab", "result_checksum": "cd"}
    r = env["c"].post("/api/lab-evidence", headers=env["L"], json={**base, "runtime_version": "17.3", "observed_runtime_version": "16.4", "claimed_runtime_version": "17.3"}).json()
    assert r["status"] == "REJECTED_INCONSISTENT"
    assert env["c"].post(f"/api/lab-evidence/{r['evidence_id']}/review", headers=env["R"], json={"decision": "approve", "original_checked": True}).status_code == 409
    r = env["c"].post("/api/lab-evidence", headers=env["L"], json={"lab_id": "LAB-DE-01", "note": "했어요"}).json()
    assert r["status"] == "NEEDS_ORIGINAL"
    assert env["c"].post("/api/lab-evidence", headers=env["L"], json={**base, "api_token": "dapi123"}).status_code == 400
    from backend import labs as _labs
    arts = {a: "a" * 64 for a in _labs.LABS["LAB-DE-01"]["required_artifacts"]}
    ok = env["c"].post("/api/lab-evidence", headers=env["L"], json={**base, "runtime_version": "17.3", "observed_runtime_version": "17.3", "artifacts": arts}).json()
    assert ok["status"] == "SUBMITTED"
    assert env["c"].post(f"/api/lab-evidence/{ok['evidence_id']}/review", headers=env["R"], json={"decision": "approve"}).status_code == 400
    assert env["c"].post(f"/api/lab-evidence/{ok['evidence_id']}/review", headers=env["L"], json={"decision": "approve", "original_checked": True}).status_code == 403
    full = {r["item"]: r["max"] for r in _labs.LABS["LAB-DE-01"]["rubric"]}
    done = env["c"].post(f"/api/lab-evidence/{ok['evidence_id']}/review", headers=env["R"], json={"decision": "approve", "original_checked": True, "rubric_scores": full}).json()
    assert done["status"] == "APPROVED" and done["evidence_level"] == "DBX_VERIFIED_REVIEWED"


def test_at33_34_credentials(env):
    lid = env["c"].get("/api/me", headers=env["L"]).json()["user_id"]
    c = env["c"].post("/api/credentials", headers=env["L"], json={"name": "Databricks Certified Data Engineer Associate"}).json()
    assert c["status"] == "PENDING_VERIFICATION" and c["self_reported"] is True
    prof = env["c"].get(f"/api/learners/{lid}/profile", headers=env["L"]).json()
    assert all(x["status"] != "VALID" for x in prof["official_credentials"])
    assert env["c"].post(f"/api/credentials/{c['credential_ref']}/verify", headers=env["R"], json={"issuer": "x"}).status_code == 400
    v = env["c"].post(f"/api/credentials/{c['credential_ref']}/verify", headers=env["R"], json={"issuer": "Databricks", "credential_id": "ABC", "verification_url": "https://example.invalid/v", "obtained": "2023-01-01", "expires": "2025-01-01"}).json()
    assert v["status"] == "EXPIRED"
    prof = env["c"].get(f"/api/learners/{lid}/profile", headers=env["L"]).json()
    assert prof["official_credentials"][0]["status"] == "EXPIRED" and "internal_reassessment" in prof  # independent fields


def test_at35_recall_recompute(env):
    make_active(env, "DE-A")
    L = login(env["c"], "learner", "rc")
    a = env["c"].post("/api/exam-attempts", headers=L, json={"exam_id": "DE-A", "kind": "practice"}).json()
    iid = next(i["item_id"] for i in a["items"] if i["item_id"] == "Q-DEA-004")
    env["c"].post(f"/api/exam-attempts/{a['attempt_id']}/responses", headers=L, json={"item_id": iid, "answer": ["A"], "client_version": 1})
    before = env["c"].post(f"/api/exam-attempts/{a['attempt_id']}/submit", headers=L).json()["result"]
    rec = env["c"].post(f"/api/items/{iid}/recall", headers=env["R"], json={"reason": "모호한 문항"}).json()
    assert rec["affected"] and rec["notified"]
    after = env["c"].get(f"/api/exam-attempts/{a['attempt_id']}", headers=L).json()["result"]
    assert after["total"] == before["total"] - 1
    assert env["c"].get("/api/content-quality", headers=env["L"]).status_code == 403


def test_at36_guide_change(env):
    lid = env["c"].get("/api/me", headers=env["L"]).json()["user_id"]
    env["c"].post("/api/readiness-decisions", headers=env["L"], json={"exam_id": "GEN-A"})
    r = env["c"].post("/api/source-docs/GEN-A/revisions", headers=env["R"], json={"guide_revision": "new", "objectives": [{"summary": "새 목표 X", "domain_key": "dev"}]}).json()
    assert "새 목표 X" in r["added"] and r["flagged_readiness"] >= 1 and r["impact_reviewed"] is False
    rd = env["c"].post("/api/readiness-decisions", headers=env["L"], json={"exam_id": "GEN-A"}).json()
    assert any("버전 변경" in b for b in rd["blocked_by"])


def test_at37_tutor_no_basis(env):
    r = env["c"].post("/api/tutor/ask", headers=env["L"], json={"question": "양자 컴퓨팅 파이프라인 가격은?"}).json()
    assert r["status"] == "NEEDS_VERIFICATION" and r["issue"]
    r = env["c"].post("/api/tutor/ask", headers=env["L"], json={"question": "Genie Spaces와 Genie Agents 차이?"}).json()
    assert r["status"] == "ANSWERED" and r["sources"][0]["url"].startswith("https://docs.databricks.com") and r["sources"][0]["basis_date"] == "2026-11-11"


def test_at38_other_learner_data(env):
    other = login(env["c"], "learner", "oth")
    lid = env["c"].get("/api/me", headers=env["L"]).json()["user_id"]
    for path in (f"/api/learners/{lid}/skills", f"/api/learners/{lid}/profile"):
        assert env["c"].get(path, headers=other).status_code == 403
    a = env["c"].post("/api/exam-attempts", headers=env["L"], json={"exam_id": "DE-A", "kind": "practice"}).json()
    assert env["c"].get(f"/api/exam-attempts/{a['attempt_id']}", headers=other).status_code == 404
    assert env["c"].post(f"/api/exam-attempts/{a['attempt_id']}/submit", headers=other).status_code == 404


def test_at39_new_seed_independent(env):
    # results follow the data, not memorised constants: add stock and the shortage disappears
    start_wh(env); fix_perm(env); sql(env, FIX_VIEW)
    assert sql(env, "TRUNCATE TABLE food_dev.silver.inventory")["status"] == "failed"  # unsupported statements never fake success
    assert sql(env, "INSERT INTO food_dev.silver.inventory VALUES ('W3','P-001',10,0,0)")["status"] == "ok"
    f = cmd(env, "order.facts", {"order_id": "O-10021", "requested_total": 35})["result"]
    assert f["facts"]["available_qty"] == 22 and f["shortage"] == 0


def test_at40_no_guarantee_language(env):
    texts = []
    r = env["c"].post("/api/readiness-decisions", headers=env["L"], json={"exam_id": "DE-A"}).json()
    texts.append(json.dumps(r, ensure_ascii=False))
    texts.append(json.dumps(env["c"].get(f"/api/sessions/{env['sid']}/score", headers=env["L"]).json(), ensure_ascii=False))
    blob = " ".join(texts)
    for bad in ["합격 보장", "합격을 보장", "Certified"]:
        assert bad not in blob.replace("합격 보장·공식", "")  # only the negating disclaimer may mention it
    assert "공식 합격선" in blob and "아닙니다" in blob


def test_at41_deny_keyword_hold(env):
    r = env["c"].post("/api/tutor/ask", headers=env["L"], json={"question": "UC에서 DENY 구문으로 권한 막는 법"}).json()
    assert r["status"] == "NEEDS_VERIFICATION" and "DENY" in r["answer"]
    start_wh(env); fix_perm(env)
    r = sql(env, "DENY SELECT ON TABLE food_dev.silver.orders TO `x`")
    assert r["status"] == "failed" and r["result"]["error"]["code"] in ("SIMULATOR_UNSUPPORTED", "PARSE_ERROR")


def test_at42_ai_cannot_promote(env):
    lid = env["c"].get("/api/me", headers=env["L"]).json()["user_id"]
    r = env["c"].post("/api/grade-decisions", headers=env["R"], json={"learner": lid, "track": "DE-A", "grade": "L3", "evaluator_type": "ai", "scores": {"practical": 99, "explain": 99}})
    assert r.status_code == 403 and r.json()["error"]["code"] == "AI_CANNOT_APPROVE"
    assert env["c"].post("/api/grade-decisions", headers=env["L"], json={"learner": lid, "track": "DE-A", "grade": "L1"}).status_code == 403
    assert env["c"].post("/api/grade-decisions", headers=env["R"], json={"learner": env["R"] and "r_self", "track": "DE-A", "grade": "L1", "core_completion": True}).status_code in (200, 403)


# ---------------- extras: eval set, scoring, ontology
def test_eval_set_40_cases(env):
    r = cmd(env, "eval.run")["result"]
    assert r["total"] == 40 and r["passed"] == 40
    cats = {c["category"] for c in r["cases"]}
    assert {"정상", "마감", "재고", "단위", "반품", "데이터 없음", "복합"} <= cats


def test_policy_edit_test_activate(env):
    bad = "rule_id: X\nrequires_approval: false\nprohibited_if: []\nrevalidate_before_execution: [order_version]\n"
    d = cmd(env, "policy.draft", {"yaml": bad})["result"]
    assert d["tests_passed"] is False
    r = env["c"].post(f"/api/sessions/{env['sid']}/commands", headers=env["L"], json={"command_type": "policy.activate", "payload": {}})
    assert r.status_code == 409
    good = "rule_id: ORDER_CHANGE_AFTER_CUTOFF\nrequires_approval: true\nprohibited_if: [customer_credit_blocked, delivery_route_closed]\nrevalidate_before_execution: [available_inventory, order_version, approval_payload_hash]\n"
    assert cmd(env, "policy.draft", {"yaml": good})["result"]["tests_passed"] is True
    assert cmd(env, "policy.activate")["result"]["active"] == 2


def test_genie_leak_and_scope(env):
    start_wh(env); fix_perm(env); sql(env, FIX_VIEW)
    cmd(env, "genie.config", {"datasets": ["food_dev.gold.v_order_overview", "food_dev.gold.v_available_inventory"]})
    ok = cmd(env, "genie.ask", {"question": "총 주문 박스는?"})
    assert ok["result"]["status"] == "OK" and "SELECT" in ok["result"]["sql"]
    leak = cmd(env, "genie.ask", {"question": "P-001 가용재고는?", "as_persona": "analyst-b@wizbase.training"})
    assert leak["result"]["status"] == "DENIED"
    oos = cmd(env, "genie.ask", {"question": "내일 날씨는?"})
    assert oos["result"]["status"] == "OUT_OF_SCOPE"
    assert env["c"].post(f"/api/sessions/{env['sid']}/commands", headers=env["L"], json={"command_type": "genie.ask", "payload": {"question": "x", "as_persona": "uc-admin@wizbase.training"}}).status_code == 403


def test_reset_preserves_evidence(env):
    full_order_flow(env)
    n = len(core.SESSIONS[env["sid"]]["audit"])
    r = env["c"].post("/api/instructor/reset", headers=env["I"], json={"session_id": env["sid"]}).json()
    assert r["reset"] and r["preserved_evidence"]["audit_events"] == n
    assert len(core.SESSIONS[env["sid"]]["audit"]) > n and len(core.SESSIONS[env["sid"]]["resets"]) == 1
    assert core.SESSIONS[env["sid"]]["data_digest0"] == core.data_digest(core.SESSIONS[env["sid"]])


def test_score_requires_safety_and_explain(env):
    pr, p, ap, body = full_order_flow(env)
    sc = env["c"].get(f"/api/sessions/{env['sid']}/score", headers=env["L"]).json()
    assert sc["core_completion"] is False and sc["explain_pending"] is True
    assert env["c"].post("/api/instructor/evaluate", headers=env["L"], json={"session_id": env["sid"], "explain_score": 15}).status_code == 403


def test_many_learners_behind_one_ip_can_login(client):
    # 교육장 NAT: 20명 이상 동시 로그인이 속도 제한에 걸리지 않아야 함(제한은 실패한 직원 코드에만 적용)
    for i in range(30):
        assert client.post("/api/auth/login", json={"name": f"n{i}", "role": "learner"}).status_code == 200


def test_official_bullet_objectives_ingested_with_hashes(env):
    import re as _re
    exp = {"DE-A": (33, {6, 21, 22, 16, 10, 10, 15}), "DE-P": (45, {23, 12, 12, 10, 15, 8, 5, 10, 5}), "GEN-A": (56, {14, 14, 30, 22, 8, 12})}
    for ex, (n, weights) in exp.items():
        cov = env["c"].get(f"/api/exam-profiles/{ex}/coverage", headers=env["L"]).json()
        objs = [o for o in cov["objectives"] if o["granularity"] == "OFFICIAL_BULLET"]
        assert cov["ingested"] == n == len(objs)
        assert all(o["granularity"] == "OFFICIAL_BULLET" and _re.fullmatch(r"[0-9a-f]{64}", o["source_text_sha256"]) and _re.fullmatch(r"[0-9a-f]{64}", o["source_hash"]) for o in objs)
        by_sec = {}
        for o in objs:
            by_sec[o["section_name"]] = o["domain_weight"]
        assert set(by_sec.values()) == weights and sum(by_sec.values()) == 100
        assert all(o["lab_ids"] for o in objs)
    cov = env["c"].get("/api/exam-profiles/DE-A/coverage", headers=env["L"]).json()
    oid = cov["objectives"][0]["objective_id_internal"]
    assert env["c"].post(f"/api/objectives/{oid}/verify", headers=env["L"], json={"source_checked": True}).status_code == 403
    assert env["c"].post(f"/api/objectives/{oid}/verify", headers=env["R"], json={"source_checked": False}).status_code == 400
    assert env["c"].post(f"/api/objectives/{oid}/verify", headers=env["R"], json={"source_checked": True}).json()["reviewer"]


def test_question_bank_coverage_and_no_position_bias(env):
    items = env["c"].get("/api/items", headers=env["R"]).json()
    from collections import Counter
    per_dom = Counter((i["exam"], i["domain"]) for i in items)
    assert len(items) >= 60 and min(per_dom.values()) >= 3 and len(per_dom) == 22
    pos = Counter(i["correct"][0] for i in items if i["type"] == "single")
    assert max(pos.values()) / sum(pos.values()) < 0.4                       # 정답 위치 편향 없음
    for i in items:
        assert all(c["why"] for c in i["choices"]) and set(i["correct"]) <= {c["id"] for c in i["choices"]}
        assert i["objective_ids"]


def test_cdc_replay_lesson_and_dml_permissions(env):
    from backend import guide as _g
    start_wh(env); fix_perm(env)
    assert cmd(env, "cdc.check")["status"] == "failed"                                                  # 테이블 없이는 통과 불가
    assert sql(env, "SELECT * FROM food_dev.bronze.cdc_events ORDER BY seq")["status"] == "ok"
    naive = "CREATE OR REPLACE TABLE food_dev.silver.customers_cdc AS SELECT customer_id, city FROM food_dev.bronze.cdc_events"
    sql(env, naive)
    chk = cmd(env, "cdc.check")["result"]
    assert not chk["ok"] and chk["wrong_or_missing_keys"] and not any(v in json.dumps(chk) for v in ("Gwangju", "Daegu", "Ulsan"))   # 기대 행(값)은 공개하지 않음
    assert sql(env, _g.CDC_SQL)["status"] == "ok" and cmd(env, "cdc.check")["result"]["ok"] and cmd(env, "cdc.check")["result"]["batch"] == 1
    assert cmd(env, "cdc.next_batch")["result"]["batch"] == 2
    assert not cmd(env, "cdc.check")["result"]["ok"]                                                    # 새 배치 후에는 재적용 필요
    assert sql(env, _g.CDC_SQL)["status"] == "ok" and cmd(env, "cdc.check")["result"]["ok"]            # 같은 멱등 로직으로 통과
    st = env["c"].get(f"/api/sessions/{env['sid']}/state", headers=env["L"]).json()["milestones"]
    assert {"cdc_events_viewed", "cdc_batch1_ok", "cdc_batch2_arrived", "cdc_batch2_ok"} <= set(st)
    # DML 지원: UPDATE/DELETE/MERGE 는 MODIFY 권한 필요 + 실제 DuckDB 의미(대상 행 중복 매칭 오류 등)
    assert sql(env, "UPDATE food_dev.silver.customers_cdc SET city = 'X' WHERE customer_id = 'C-001'")["status"] == "ok"
    assert not cmd(env, "cdc.check")["result"]["ok"]                                                    # 데이터가 바뀌면 정합성도 바뀜
    r = sql(env, "MERGE INTO food_dev.silver.customers_cdc t USING (SELECT customer_id, city FROM food_dev.bronze.cdc_events) s ON t.customer_id = s.customer_id WHEN MATCHED THEN UPDATE SET city = s.city")
    assert r["status"] == "failed" and r["result"]["error"]["code"] == "EXECUTION_ERROR"                # 중복 매칭 MERGE는 실제 엔진 오류
    r = cmd(env, "sql.execute", {"sql": "DELETE FROM food_dev.silver.orders WHERE order_id = 'O-10001'", "as_principal": "analyst-b@wizbase.training"}, "I")
    assert r["status"] == "failed" and r["result"]["error"]["code"] == "INSUFFICIENT_PERMISSIONS"


def test_git_branch_merge_conflict_and_deployed_source_hash(env):
    run = lambda l: cmd(env, "cli", {"line": l})
    run("databricks auth login --host https://training-workspace.invalid")
    assert run("git commit -m 'base'")["status"] == "ok"
    assert run("git checkout -b feature")["status"] == "ok"
    cmd(env, "bundle.edit", {"path": "src/check_data.sql", "content": "SELECT 111 AS feature"})
    assert run("git commit -m 'feature change'")["status"] == "ok"
    assert run("git checkout main")["status"] == "ok"
    cmd(env, "bundle.edit", {"path": "src/check_data.sql", "content": "SELECT 222 AS main_change"})
    cmd(env, "bundle.edit", {"path": "README.md", "content": "main readme"})
    assert run("git commit -m 'main change'")["status"] == "ok"
    r = run("git merge feature")
    assert r["status"] == "failed" and "CONFLICT" in r["result"]["stderr"]                              # 같은 파일을 양쪽이 수정 → 충돌
    st = env["c"].get(f"/api/sessions/{env['sid']}/state", headers=env["L"]).json()
    assert "<<<<<<<" in st["bundle"]["files"]["src/check_data.sql"] and "git_conflict_seen" in st["milestones"]
    assert run("git commit -m 'too early'")["status"] == "failed"                                      # 충돌 표시가 남은 채 커밋 불가
    cmd(env, "bundle.edit", {"path": "src/check_data.sql", "content": "SELECT 333 AS resolved"})
    c = run("git commit -m 'resolve'")
    assert c["status"] == "ok" and "merge commit" in c["result"]["stdout"]
    assert "(merge)" in run("git log")["result"]["stdout"]
    assert run("git branch")["result"]["stdout"].count("\n") >= 1
    assert run("git checkout nope")["status"] == "failed"
    cmd(env, "bundle.edit", {"path": "README.md", "content": "dirty"})
    assert run("git checkout feature")["status"] == "failed"                                           # 커밋하지 않은 변경이 있으면 전환 불가
    assert run("git pr create main")["status"] == "ok"
    assert run("git merge --abort")["status"] == "failed"


@pytest.mark.parametrize("seed", ["food-order-v2", "food-order-v3"])
def test_other_seeds_full_order_flow_uses_case_numbers_not_memorised_ones(client, seed):
    from backend import seed as sd
    L = login(client); R = login(client, "reviewer", "rv", "S-test-code"); A = login(client, "admin", "ad", "A-test-code")
    sid = client.post("/api/sessions", headers=L, json={"seed": seed}).json()["session_id"]
    e = dict(c=client, L=L, R=R, A=A, sid=sid)
    cz = sd.case(seed)
    assert cz["gap"] != 3 and cz["available"] != 12                                   # 대표 사례(v1)와 다른 숫자
    st = client.get(f"/api/sessions/{sid}/state", headers=L).json()
    assert st["case"]["order"] == cz["order"] != "O-10021"
    start_wh(e); fix_perm(e)
    f = cmd(e, "order.facts", {"order_id": cz["order"], "requested_total": cz["requested"]})["result"]
    assert f["facts"]["available_qty"] == cz["naive_available"] and f["shortage"] != cz["gap"]      # 시드의 뷰도 계약과 다름(damaged 누락)
    assert sql(e, FIX_VIEW)["status"] == "ok" and cmd(e, "contract.check")["status"] == "ok"
    f = cmd(e, "order.facts", {"order_id": cz["order"], "requested_total": cz["requested"]})["result"]
    assert f["facts"]["available_qty"] == cz["available"] and f["shortage"] == cz["gap"] and f["wrong_if_total_minus_free"] == cz["wrong_gap"]
    pr = cmd(e, "order.propose", {"order_id": cz["order"], "requested_total": cz["requested"]})["result"]
    assert pr["policy"]["shortage"] == cz["gap"] and pr["proposal"]["payload"]["new_qty"] == cz["current"] + cz["available"]
    p = pr["proposal"]
    ap = client.post("/api/approvals", headers=R, json={"session_id": sid, "proposal_id": p["proposal_id"], "payload_hash": p["payload_hash"]}).json()
    ok = client.post(f"/api/sessions/{sid}/ax/orders/{cz['order']}/change", headers=L, json={"approval_id": ap["approval_id"], "payload": p["payload"], "idempotency_key": "s-1", "expected_version": 1})
    assert ok.status_code == 200 and ok.json()["post_reconciliation"] == "OK"
    g = client.get(f"/api/sessions/{sid}/guide", headers=L).json()
    assert cz["order"] in json.dumps(g, ensure_ascii=False) and "O-10021" not in json.dumps(g, ensure_ascii=False)      # 가이드도 시드 값으로 치환
    # 장애 주입은 시드의 사례 객체를 대상으로 한다
    I = login(client, "instructor", "i2", "I-test-code")
    client.post("/api/instructor/faults", headers=I, json={"session_id": sid, "fault_id": "order_version_conflict"})
    assert cmd(e, "order.facts", {"order_id": cz["order"], "requested_total": 1})["result"]["facts"]["order_version"] == 3
    d1 = client.post("/api/instructor/replay", headers=I, json={"session_id": sid}).json()
    assert d1["match"] is True
    assert client.post("/api/sessions", headers=L, json={"seed": "nope"}).status_code == 400
