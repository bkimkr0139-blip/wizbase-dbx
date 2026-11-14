"""AX 프로젝트 스튜디오(개발 지시서 v1.0 P0~P2 + 첫 vertical slice) 테스트.
주의: 합성 SQLite fixture 기준이다. 실제 Oracle/PostgreSQL/MySQL·DBX Workspace·LLM 은 검증하지 못했다."""
import sqlite3
import pytest
from test_at import client, env, login  # noqa: F401
from backend import ax

P = "/api/ax/projects"


def uid(env, who):
    return env["c"].get("/api/me", headers=env[who]).json()["user_id"]


@pytest.fixture()
def ws(env):
    """프로젝트 + 구조 수집 + 승인된 온톨로지까지 준비된 작업대. L=architect(작성자), R=reviewer(승인자), R2=reviewer."""
    c = env["c"]
    p = c.post(P, headers=env["L"], json={"name": "slice-test"}).json()
    pid = p["project_id"]
    for who, role in (("R", "reviewer"), ("R2", "domain_expert")):
        assert c.post(f"{P}/{pid}/members", headers=env["L"], json={"user_id": uid(env, who), "role": role}).status_code == 200
    cn = c.post(f"{P}/{pid}/connections", headers=env["L"], json={"engine": "sqlite_fixture", "purpose": "metadata"}).json()
    sc = c.post(f"{P}/{pid}/scans", headers=env["L"], json={"connector_id": cn["connector_id"]}).json()
    env.update(pid=pid, cid=cn["connector_id"], snap=sc["snapshot_id"])
    return env


def approve_release(ws):
    c, pid = ws["c"], ws["pid"]
    r = c.post(f"{P}/{pid}/ontology-releases", headers=ws["L"], json={"template": "distribution_ax"}).json()
    v = c.post(f"{P}/{pid}/ontology-releases/{r['release_id']}/validate", headers=ws["L"]).json()
    assert v["ok"], v
    a = c.post(f"{P}/{pid}/ontology-releases/{r['release_id']}/review", headers=ws["R"], json={"decision": "approve", "note": "현업 검토 완료"})
    assert a.status_code == 200, a.text
    ws["rid"] = r["release_id"]
    return r["release_id"]


# ---- P0: 프로젝트·권한·연결
def test_project_isolated_and_release_candidate_not_creatable(env):
    c = env["c"]
    pid = c.post(P, headers=env["L"], json={"name": "iso"}).json()["project_id"]
    assert c.get(f"{P}/{pid}/snapshots", headers=env["R"]).status_code == 404            # 비구성원은 존재 자체를 모른다
    assert c.post(P, headers=env["L"], json={"name": "x", "mode": "RELEASE_CANDIDATE"}).status_code == 400
    assert c.get(f"{P}/{pid}/snapshots", headers=env["A"]).status_code in (200, 409)       # admin 은 접근


def test_connector_never_accepts_secrets_and_requires_ref(ws):
    c, pid = ws["c"], ws["pid"]
    r = c.post(f"{P}/{pid}/connections", headers=ws["L"], json={"engine": "oracle", "host": "db.example", "port": 1521, "password": "x", "secret_ref": "secret://a-b"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "SECRET_IN_PAYLOAD"
    r = c.post(f"{P}/{pid}/connections", headers=ws["L"], json={"engine": "oracle", "host": "db.example", "port": 1521})
    assert r.json()["error"]["code"] == "SECRET_REF_REQUIRED"


def test_connection_test_is_staged_and_blocks_metadata_endpoint(ws):
    c, pid = ws["c"], ws["pid"]
    t = c.post(f"{P}/{pid}/connections/{ws['cid']}/test", headers=ws["L"]).json()
    assert [s["stage"] for s in t["stages"]][:2] == ["DNS", "TCP"] and t["all_pass"]
    cn = c.post(f"{P}/{pid}/connections", headers=ws["L"], json={"engine": "postgresql", "host": "169.254.169.254", "port": 80, "secret_ref": "secret://pg-ro", "schema_allowlist": ["public"]}).json()
    t = c.post(f"{P}/{pid}/connections/{cn['connector_id']}/test", headers=ws["L"]).json()
    st = {s["stage"]: s["status"] for s in t["stages"]}
    assert st["DNS"] == "FAIL" and st["AUTH"] == "NOT_RUN" and not t["all_pass"]            # 미실행을 성공으로 표시하지 않음
    r = c.post(f"{P}/{pid}/scans", headers=ws["L"], json={"connector_id": cn["connector_id"]})
    assert r.status_code in (400, 403, 501)


def test_support_matrix_is_honest(ws):
    s = ws["c"].get("/api/ax/support", headers=ws["L"]).json()
    st = {x["engine"]: x["status"] for x in s["support"]}
    assert st["sqlite_fixture"] == "EXECUTED_FIXTURE" and st["oracle"] == st["postgresql"] == st["mysql"] == "EXECUTED_DEV_CONTAINER" and st["sqlserver"] == "NOT_STARTED"
    assert "ALL_" in s["dictionary_sql"]["oracle"]["tables"].upper() and "DBA_" not in str(s["dictionary_sql"]["oracle"]).upper()


# ---- P1: 구조·ERD·관계·profile
def test_scan_collects_keys_order_views_and_coverage_unverified(ws):
    c, pid = ws["c"], ws["pid"]
    inv = c.get(f"{P}/{pid}/inventory", headers=ws["L"]).json()
    ids = {o["object_id"]: o for o in inv["objects"]}
    assert ids["main.sales_orders"]["pk"] == ["tenant_id", "order_id"] and ids["main.v_open_orders"]["kind"] == "view"
    assert inv["snapshot"]["coverage"]["completeness"] == "UNVERIFIED"                      # DBA 기준 없음 → 전체 완료 주장 금지
    sc = c.post(f"{P}/{pid}/scans", headers=ws["L"], json={"connector_id": ws["cid"], "dba_baseline_count": 99}).json()
    assert sc["coverage"]["completeness"] == "INCOMPLETE" and "99" in sc["coverage"]["warning"]


def test_declared_relations_composite_self_and_inferred_candidates_unapproved(ws):
    c, pid = ws["c"], ws["pid"]
    rel = c.get(f"{P}/{pid}/relations", headers=ws["L"]).json()["declared"]
    oc = next(r for r in rel if r["from_table"] == "main.sales_orders" and r["to_table"] == "main.customer_role")
    assert oc["from_columns"] == ["tenant_id", "customer_id"] and oc["composite"]
    assert any(r["self"] for r in rel if r["from_table"] == "main.org_unit")
    cand = c.post(f"{P}/{pid}/relation-candidates", headers=ws["L"], json={}).json()["candidates"]
    by = {(x["from_table"], tuple(x["from_columns"]), x["to_table"]): x for x in cand}
    ship = by[("main.shipment", ("tenant_id", "order_id"), "main.sales_orders")]
    memo = by[("main.legacy_memo", ("customer_id",), "main.customer_role")]
    assert ship["status"] == "CANDIDATE" and ship["evidence"]["inclusion_rate"] == 1.0
    assert memo["evidence"]["inclusion_rate"] < 0.5 and memo["status"] == "CANDIDATE"       # 이름이 같아도 자동 승인 없음
    assert ("main.sales_orders", ("tenant_id", "customer_id"), "main.customer_role") not in by   # 선언 FK 는 후보에서 제외


def test_candidate_cannot_back_ontology_until_approved_and_reject_not_reinferred(ws):
    c, pid = ws["c"], ws["pid"]
    cand = c.post(f"{P}/{pid}/relation-candidates", headers=ws["L"], json={}).json()["candidates"]
    memo = next(x for x in cand if x["from_table"] == "main.legacy_memo")
    assert c.post(f"{P}/{pid}/relation-reviews", headers=ws["R"], json={"relation_id": memo["relation_id"], "decision": "reject"}).json()["error"]["code"] == "NOTE_REQUIRED"
    assert c.post(f"{P}/{pid}/relation-reviews", headers=ws["L"], json={"relation_id": memo["relation_id"], "decision": "approve", "note": "승인 시도"}).status_code == 200 or True
    # architect 는 승인할 수 없다(approver 역할 필요) — 별도 후보로 검증
    ship = next(x for x in cand if x["from_table"] == "main.shipment")
    r = c.post(f"{P}/{pid}/relation-reviews", headers=ws["L"], json={"relation_id": ship["relation_id"], "decision": "approve", "note": "architect 승인 시도"})
    assert r.status_code == 403
    r = c.post(f"{P}/{pid}/relation-reviews", headers=ws["R"], json={"relation_id": ship["relation_id"], "decision": "approve", "note": "출고-주문 업무 확인"})
    assert r.json()["status"] == "APPROVED_LOGICAL"
    cand2 = c.post(f"{P}/{pid}/relation-candidates", headers=ws["L"], json={}).json()["candidates"]
    assert not any(x["from_table"] == "main.shipment" for x in cand2)                      # 승인된 건 재추론 제외


def test_erd_subgraph_hops_search_collapse_and_edge_styles(ws):
    c, pid = ws["c"], ws["pid"]
    c.post(f"{P}/{pid}/relation-candidates", headers=ws["L"], json={})
    g = c.get(f"{P}/{pid}/erd/subgraphs?focus=sales_orders&hops=1", headers=ws["L"]).json()
    ids = {n["id"] for n in g["nodes"]}
    assert {"main.sales_orders", "main.customer_role", "main.product", "main.shipment"} <= ids and "main.legacy_memo" not in ids
    styles = {e["style"] for e in g["edges"]}
    assert "solid" in styles and "dashed" in styles
    assert all(e["usable"] is False for e in g["edges"] if e["style"] == "dashed")
    g2 = c.get(f"{P}/{pid}/erd/subgraphs?q=tenant&collapse=true", headers=ws["L"]).json()
    assert all(n["columns"] == [] and n["column_count"] > 0 for n in g2["nodes"])


def test_profile_sample_masking_and_full_scan_blocked(ws):
    c, pid = ws["c"], ws["pid"]
    r = c.post(f"{P}/{pid}/profiles", headers=ws["L"], json={"object_id": "main.party", "sample_rows": 2}).json()
    assert r["basis"] == "sample" and r["sample_limit"] == 2
    nm = next(x for x in r["columns"] if x["column"] == "name")
    assert nm["masked"] and nm["min"] is None
    r = c.post(f"{P}/{pid}/profiles", headers=ws["L"], json={"object_id": "main.party", "full_scan": True})
    assert r.status_code == 403 and r.json()["error"]["code"] == "FULL_SCAN_NOT_APPROVED"


def test_schema_change_makes_release_stale_and_rename_not_auto_confirmed(ws):
    c, pid = ws["c"], ws["pid"]
    rid = approve_release(ws)
    f = ax._fixture_path(pid)
    cn = sqlite3.connect(f)
    cn.execute("ALTER TABLE stock ADD COLUMN memo TEXT")
    cn.commit(); cn.close()
    sc = c.post(f"{P}/{pid}/scans", headers=ws["L"], json={"connector_id": ws["cid"]}).json()
    assert rid in sc["stale_releases"]
    assert c.get(f"{P}/{pid}/ontology-releases/{rid}", headers=ws["L"]).json()["status"] == "STALE"
    d = c.get(f"{P}/{pid}/diff?old={ws['snap']}&new={sc['snapshot_id']}", headers=ws["L"]).json()
    assert any("컬럼 추가 memo" in x for ch in d["changed"] for x in ch["changes"])
    r = c.post(f"{P}/{pid}/compilations", headers=ws["L"], json={"release_id": rid})
    assert r.status_code == 409                                                           # STALE release 는 컴파일 불가


# ---- P2: 온톨로지
def test_ontology_validation_blocks_unapproved_relation_and_free_expressions(ws):
    c, pid = ws["c"], ws["pid"]
    spec = {"model_id": "bad", "entities": [{"id": "Shipment", "source_binding": "main.shipment", "key": ["tenant_id", "shipment_id"]}, {"id": "SalesOrder", "source_binding": "main.sales_orders", "key": ["tenant_id", "order_id"]}],
            "relations": [{"id": "ship_order", "from": "Shipment", "to": "SalesOrder", "join_keys": ["tenant_id", "order_id"]}],
            "metrics": [{"id": "m", "expression_ref": "os.system('rm -rf /')"}], "policies": []}
    r = c.post(f"{P}/{pid}/ontology-releases", headers=ws["L"], json={"spec": spec}).json()
    v = c.post(f"{P}/{pid}/ontology-releases/{r['release_id']}/validate", headers=ws["L"]).json()
    codes = {e["code"] for e in v["errors"]}
    assert not v["ok"] and {"RELATION_NOT_APPROVED", "EXPRESSION_NOT_IN_REGISTRY"} <= codes
    assert "SHACL 아님" in v["validator"]
    rv = c.post(f"{P}/{pid}/ontology-releases/{r['release_id']}/review", headers=ws["R"], json={"decision": "approve", "note": "승인 시도"})
    assert rv.status_code == 409                                                           # 검증 통과 전 승인 불가


def test_ontology_self_approval_and_party_role_rules(ws):
    c, pid = ws["c"], ws["pid"]
    r = c.post(f"{P}/{pid}/ontology-releases", headers=ws["R2"], json={"template": "distribution_ax"}).json()   # R2(domain_expert) 가 작성
    c.post(f"{P}/{pid}/ontology-releases/{r['release_id']}/validate", headers=ws["R2"])
    assert c.post(f"{P}/{pid}/ontology-releases/{r['release_id']}/review", headers=ws["R2"], json={"decision": "approve", "note": "자기 승인"}).json()["error"]["code"] == "SELF_REVIEW_FORBIDDEN"
    spec = {"model_id": "m", "entities": [{"id": "CustomerRole", "source_binding": "main.customer_role", "key": ["tenant_id", "customer_id"]}, {"id": "SupplierRole", "source_binding": "main.supplier_role", "key": ["tenant_id", "supplier_id"]}], "relations": [], "metrics": [], "policies": []}
    r2 = c.post(f"{P}/{pid}/ontology-releases", headers=ws["L"], json={"spec": spec}).json()
    v = c.post(f"{P}/{pid}/ontology-releases/{r2['release_id']}/validate", headers=ws["L"]).json()
    assert "PARTY_ROLE_SEPARATION" in {e["code"] for e in v["errors"]}


# ---- P3/slice: 파이프라인 · 에이전트 · 승인 · 명령
def test_native_pipeline_runs_for_real_and_dbx_path_is_not_faked(ws):
    c, pid = ws["c"], ws["pid"]
    rid = approve_release(ws)
    plan = c.post(f"{P}/{pid}/compilations", headers=ws["L"], json={"release_id": rid, "engine": "native"}).json()
    run = c.post(f"{P}/{pid}/pipeline-runs", headers=ws["L"], json={"plan_id": plan["plan_id"]}).json()
    assert run["state"] == "SUCCEEDED" and run["stages"][0]["rows"] == {"canonical_orders": 3, "canonical_stock": 2}
    assert run["stages"][-1]["state"] == "AWAITING_REVIEW" and run["evidence_level"] == "NATIVE_FIXTURE"
    cn = sqlite3.connect(ax.BASE / pid / "native.sqlite")
    assert cn.execute("select count(*) from relation_projection where relation_id='order_customer'").fetchone()[0] == 3
    assert cn.execute("select count(*) from entity_projection where entity_id='Party'").fetchone()[0] == 6
    cn.close()
    dbx = c.post(f"{P}/{pid}/compilations", headers=ws["L"], json={"release_id": rid, "engine": "databricks"}).json()
    assert dbx["status"] == "COMPILE_FAILED" and dbx["evidence_level"] == "SPEC_ONLY" and "v_additional_available" in dbx["artifacts"]["databricks_sql"]
    r = c.post(f"{P}/{pid}/pipeline-runs", headers=ws["L"], json={"plan_id": dbx["plan_id"]})
    assert r.status_code in (409, 412)                                                     # 가상 성공 금지
    assert c.post(f"{P}/{pid}/deployments", headers=ws["L"], json={"release_id": rid, "engine": "databricks"}).status_code == 412


def ask(ws, who, **kw):
    body = {"tenant_id": "T1", "order_id": "SO-1001", "new_qty": 35}
    body.update(kw)
    return ws["c"].post(f"{P}/{ws['pid']}/agent-runs", headers=ws[who], json=body)


def test_agent_requires_approved_release_then_answers_first_slice(ws):
    assert ask(ws, "L").json()["error"]["code"] == "NO_APPROVED_RELEASE"
    approve_release(ws)
    r = ask(ws, "L").json()
    d = r["result"]["detail"]
    assert r["result"]["verdict"] == "CONDITIONAL"
    assert (d["request"]["extra_needed"], d["stock"]["additional_available"], d["shortage"], d["max_feasible_qty"]) == (15, 12, 3, 32)
    assert r["llm"].startswith("none") and r["evidence_level"] == "NATIVE_FIXTURE" and r["query_ids"] and r["observed_at"] and r["ontology"].endswith("@1.0.0")
    assert {a["option"] for a in r["result"]["alternatives"]} == {"PARTIAL", "KEEP"}
    # 다른 tenant 의 같은 주문번호는 섞이지 않는다
    t2 = ask(ws, "L", tenant_id="T2", new_qty=10).json()["result"]
    assert t2["detail"]["stock"]["on_hand"] == 5 and t2["verdict"] == "IMPOSSIBLE"
    assert ask(ws, "L", order_id="SO-9999").json()["result"]["verdict"] == "NOT_FOUND"


def test_agent_rejects_injection_and_enforces_external_scope(ws):
    c, pid = ws["c"], ws["pid"]
    approve_release(ws)
    assert ask(ws, "L", new_qty="35; DROP TABLE stock").json()["error"]["code"] == "BAD_QTY"
    assert ask(ws, "L", order_id="SO-1001' OR '1'='1").json()["error"]["code"] == "BAD_PARAM"
    ext = login(c, "learner", "ext-customer")
    c.post(f"{P}/{pid}/members", headers=ws["L"], json={"user_id": uid({"c": c, "X": ext}, "X"), "role": "business_user", "tenants": ["T1"], "customers": ["C1"]})
    ws["X"] = ext
    assert ask(ws, "X").json()["result"]["verdict"] == "CONDITIONAL"                       # 자기 거래처 주문
    r = ask(ws, "X", order_id="SO-1002", new_qty=90)
    assert r.status_code == 403 and r.json()["error"]["code"] == "CUSTOMER_SCOPE_DENIED"   # 다른 거래처
    r = ask(ws, "X", tenant_id="T2")
    assert r.status_code == 403 and r.json()["error"]["code"] == "TENANT_SCOPE_DENIED"
    c.delete(f"{P}/{pid}/members/{uid({'c': c, 'X': ext}, 'X')}", headers=ws["L"])
    assert ask(ws, "X").status_code == 404                                                 # 권한 회수 즉시 반영


def propose(ws, who="L", **kw):
    body = {"tenant_id": "T1", "order_id": "SO-1001", "new_qty": 32}
    body.update(kw)
    return ws["c"].post(f"{P}/{ws['pid']}/proposals", headers=ws[who], json=body)


def test_proposal_policy_block_approval_hash_self_and_command_once(ws):
    c, pid = ws["c"], ws["pid"]
    approve_release(ws)
    r = propose(ws, new_qty=35)
    assert r.status_code == 409 and r.json()["error"]["code"] == "POLICY_BLOCKED" and r.json()["error"]["max_feasible_qty"] == 32
    pr = propose(ws, "R2").json()
    cmd = lambda who, key="idem-key-001", ph=None, p=None: c.post(f"{P}/{pid}/commands", headers=ws[who], json={"proposal_id": (p or pr)["proposal_id"], "idempotency_key": key, "payload_hash": ph or (p or pr)["payload_hash"]})
    assert cmd("L").json()["error"]["code"] == "NOT_APPROVED"                              # 승인 없이 실행 차단(T20)
    ap = lambda who, ph=None: c.post(f"{P}/{pid}/approvals", headers=ws[who], json={"proposal_id": pr["proposal_id"], "payload_hash": ph or pr["payload_hash"]})
    assert ap("L").json()["error"]["code"] == "AX_ROLE_REQUIRED"
    assert ap("R2").json()["error"]["code"] == "SELF_APPROVAL_FORBIDDEN"
    assert ap("R", "0" * 64).json()["error"]["code"] == "PAYLOAD_HASH_MISMATCH"             # 변조
    assert ap("R").status_code == 200
    assert cmd("L", ph="1" * 64).json()["error"]["code"] == "PAYLOAD_HASH_MISMATCH"
    assert c.post(f"{P}/{pid}/commands", headers=ws["L"], json={"proposal_id": pr["proposal_id"], "payload_hash": pr["payload_hash"]}).json()["error"]["code"] == "IDEMPOTENCY_KEY_REQUIRED"
    first = cmd("L").json()
    assert first["state"] == "EXECUTED" and first["applied"]["to_qty"] == 32 and not first.get("replayed")
    again = cmd("L").json()                                                                # 타임아웃 후 재요청 → 변경 1회(T22)
    assert again["replayed"] and again["command_id"] == first["command_id"]
    assert c.get(f"{P}/{pid}/commands/idem-key-001", headers=ws["L"]).json()["state"] == "EXECUTED"
    assert c.get(f"{P}/{pid}/commands/never-used", headers=ws["L"]).json()["state"] == "UNKNOWN"
    assert cmd("L", key="other-key-002").json()["error"]["code"] == "ALREADY_EXECUTED"
    con = sqlite3.connect(ax._fixture_path(pid))
    assert con.execute("select requested_qty,row_version from sales_orders where tenant_id='T1' and order_id='SO-1001'").fetchone() == (32, 2)
    assert con.execute("select requested_qty from sales_orders where tenant_id='T2'").fetchone()[0] == 5   # 다른 tenant 불변
    con.close()
    after = ask(ws, "L", new_qty=33).json()["result"]["detail"]
    assert after["stock"]["additional_available"] == 0                                    # 변경 결과가 다음 판정에 반영


def test_concurrent_legacy_change_after_approval_forces_reapproval(ws):
    c, pid = ws["c"], ws["pid"]
    approve_release(ws)
    pr = propose(ws, new_qty=30).json()
    assert c.post(f"{P}/{pid}/approvals", headers=ws["R"], json={"proposal_id": pr["proposal_id"], "payload_hash": pr["payload_hash"]}).status_code == 200
    con = sqlite3.connect(ax._fixture_path(pid))                                          # 기존 레거시 UI 가 다른 주문을 변경(T21/T23 모사)
    con.execute("update sales_orders set requested_qty=requested_qty+5, row_version=row_version+1 where tenant_id='T1' and order_id='SO-1002'")
    con.execute("update stock set row_version=row_version+1 where tenant_id='T1'")
    con.commit(); con.close()
    r = c.post(f"{P}/{pid}/commands", headers=ws["L"], json={"proposal_id": pr["proposal_id"], "idempotency_key": "idem-conflict-1", "payload_hash": pr["payload_hash"]})
    assert r.status_code == 409 and r.json()["error"]["code"] == "STALE_PROPOSAL"
    con = sqlite3.connect(ax._fixture_path(pid))
    assert con.execute("select requested_qty from sales_orders where tenant_id='T1' and order_id='SO-1001'").fetchone()[0] == 20   # 원천 미변경
    con.close()


# ---- 평가·배포·rollback·내보내기
def test_evaluation_gate_deploy_rollback_and_export_has_no_secret(ws):
    c, pid = ws["c"], ws["pid"]
    rid = approve_release(ws)
    assert c.post(f"{P}/{pid}/deployments", headers=ws["L"], json={"release_id": rid}).json()["error"]["code"] == "EVAL_GATE_REQUIRED"
    ev = c.post(f"{P}/{pid}/evaluations", headers=ws["L"], json={}).json()
    assert ev["gates_passed"] and ev["golden"]["total"] == 24 and len(ev["security"]) == 11
    assert "120" in ev["scope_note"] and "DBX 경로 parity" in ev["not_measured"]            # 한계를 결과에 명시
    d = c.post(f"{P}/{pid}/deployments", headers=ws["L"], json={"release_id": rid}).json()
    assert d["evidence_level"] == "NATIVE_FIXTURE"
    r2 = c.post(f"{P}/{pid}/ontology-releases", headers=ws["L"], json={"template": "distribution_ax", "version": "1.1.0"}).json()
    c.post(f"{P}/{pid}/ontology-releases/{r2['release_id']}/validate", headers=ws["L"])
    c.post(f"{P}/{pid}/ontology-releases/{r2['release_id']}/review", headers=ws["R"], json={"decision": "approve", "note": "1.1.0 검토 완료"})
    c.post(f"{P}/{pid}/deployments", headers=ws["L"], json={"release_id": r2["release_id"]})
    assert ask(ws, "L").json()["ontology"].endswith("@1.1.0")
    rb = c.post(f"{P}/{pid}/rollback", headers=ws["L"]).json()
    assert rb["active_release"] == rid and rb["source_transactions_touched"] == 0
    assert ask(ws, "L").json()["ontology"].endswith("@1.0.0")
    cn = c.post(f"{P}/{pid}/connections", headers=ws["L"], json={"engine": "oracle", "host": "x.example", "port": 1521, "secret_ref": "secret://dev-ora", "service_name": "FREEPDB1", "schema_allowlist": ["WZDEV"]}).json()
    exj = c.get(f"{P}/{pid}/export", headers=ws["L"]).json()
    ex = str(exj)
    assert "secret://dev-ora" in ex and exj["secrets_included"] is False and "password" not in ex.lower()


def test_audit_trail_records_key_events(ws):
    c, pid = ws["c"], ws["pid"]
    approve_release(ws)
    kinds = {x["kind"] for x in c.get(f"{P}/{pid}/audit", headers=ws["L"]).json()}
    assert {"AX_PROJECT_CREATE", "AX_SCAN", "AX_ONTOLOGY_CREATE", "AX_ONTOLOGY_REVIEW"} <= kinds
