"""실제 PostgreSQL/MySQL/Oracle 개발 DB(Docker 컨테이너, 합성 fixture)에 대한 adapter 검증(AX-T03/T04/T06/T07, 업무 slice, 계정 분리).
기본은 건너뜀. 실행: tools/ax_seed_real.py 로 컨테이너를 준비하고 WZ_AX_REAL=pg,mysql,oracle 설정.
(고객 DB·운영 DB 검증이 아니다 — 같은 합성 fixture 를 각 엔진에 적재한 시험 DB 기준.)"""
import os, sys
import pytest
from test_at import client, env, login  # noqa: F401
sys.path.insert(0, ".")

ENG = {
    "pg": dict(engine="postgresql", host="127.0.0.1", port=15432, database="wzdev", schema="wzdev", ro="WZ_SECRET_PG_RO", cmd="WZ_SECRET_PG_CMD"),
    "mysql": dict(engine="mysql", host="127.0.0.1", port=13306, database="wzdev", schema="wzdev", ro="WZ_SECRET_MY_RO", cmd="WZ_SECRET_MY_CMD"),
    "oracle": dict(engine="oracle", host="127.0.0.1", port=11521, service_name="FREEPDB1", schema="WZDEV", ro="WZ_SECRET_ORA_RO", cmd="WZ_SECRET_ORA_CMD"),
}
SEC = {"pg": ("wz_ro:ropass", "wz_cmd:cmdpass"), "mysql": ("wz_ro:ropass", "wz_cmd:cmdpass"), "oracle": ("WZ_RO:ropass", "WZ_CMD:cmdpass")}
WANT = [k for k in os.environ.get("WZ_AX_REAL", "").split(",") if k]
P = "/api/ax/projects"
low = lambda x: str(x).lower()


def _ref(envname):
    return "secret://" + envname[len("WZ_SECRET_"):].lower().replace("_", "-")


@pytest.fixture(params=WANT or ["none"])
def real(request, env, monkeypatch):
    if request.param == "none":
        pytest.skip("WZ_AX_REAL 미설정 — 실제 DB 컨테이너 시험 생략")
    k = request.param
    from tools.ax_seed_real import seed
    seed(k)                                                           # 매 시험 전 원천을 초기 상태로
    e = ENG[k]
    monkeypatch.setenv("WZ_AX_ALLOW_DIRECT_DB", "1")
    monkeypatch.setenv(e["ro"], SEC[k][0])
    monkeypatch.setenv(e["cmd"], SEC[k][1])
    c = env["c"]
    pid = c.post(P, headers=env["L"], json={"name": f"real-{k}", "mode": "DEV_NATIVE"}).json()["project_id"]
    for who, role in (("R", "reviewer"), ("R2", "domain_expert")):
        uid = c.get("/api/me", headers=env[who]).json()["user_id"]
        c.post(f"{P}/{pid}/members", headers=env["L"], json={"user_id": uid, "role": role})
    ids = {}
    for purpose, sec in (("metadata", e["ro"]), ("profiling", e["ro"]), ("runtime_read", e["ro"]), ("command", e["cmd"])):
        body = {k2: v for k2, v in e.items() if k2 in ("engine", "host", "port", "database", "service_name")}
        body.update(purpose=purpose, secret_ref=_ref(sec), schema_allowlist=[e["schema"]], tls=False)
        r = c.post(f"{P}/{pid}/connections", headers=env["L"], json=body)
        assert r.status_code == 200, r.text
        ids[purpose] = r.json()["connector_id"]
    env.update(pid=pid, cids=ids, k=k, eng=e)
    return env


def post(w, path, who="L", **body):
    return w["c"].post(f"{P}/{w['pid']}{path}", headers=w[who], json=body)


def scan(w):
    r = post(w, "/scans", connector_id=w["cids"]["metadata"])
    assert r.status_code == 200, r.text
    return r.json()


def approve(w):
    r = post(w, "/ontology-releases", template="distribution_ax").json()
    v = post(w, f"/ontology-releases/{r['release_id']}/validate").json()
    assert v["ok"], v
    assert post(w, f"/ontology-releases/{r['release_id']}/review", "R", decision="approve", note="현업 검토 완료").status_code == 200
    return r["release_id"]


def snap(sc):
    from backend import ax
    return ax.S["snapshots"][sc["snapshot_id"]]


def test_connection_test_runs_all_stages(real):
    t = post(real, f"/connections/{real['cids']['metadata']}/test").json()
    st = {s["stage"]: s["status"] for s in t["stages"]}
    assert st["DNS"] == st["TCP"] == st["AUTH"] == st["DB_IDENT"] == st["METADATA_VISIBILITY"] == st["BOUNDED_QUERY"] == "PASS", t
    assert "ropass" not in str(t) and "cmdpass" not in str(t)


def test_wrong_secret_fails_at_auth_only(real, monkeypatch):
    monkeypatch.setenv(real["eng"]["ro"], "nobody:wrongpw")
    t = post(real, f"/connections/{real['cids']['metadata']}/test").json()
    st = {s["stage"]: s["status"] for s in t["stages"]}
    assert st["TCP"] == "PASS" and st["AUTH"] == "FAIL" and st["DB_IDENT"] == "NOT_RUN" and not t["all_pass"]
    assert "wrongpw" not in str(t)


def test_direct_db_requires_dev_flag(real, monkeypatch):
    monkeypatch.delenv("WZ_AX_ALLOW_DIRECT_DB")
    t = post(real, f"/connections/{real['cids']['metadata']}/test").json()
    assert {s["stage"]: s["status"] for s in t["stages"]}["AUTH"] == "FAIL" and "DIRECT_DB_DISABLED" in str(t)


def test_scan_matches_golden_structure(real):
    from backend import ax_fixture as fx
    sc = scan(real)
    s = snap(sc)
    o = {low(x["name"]): x for x in s["objects"].values()}
    assert set(o) == {n for n, *_ in fx.TABLES} | {"v_open_orders"}, set(o)
    for n, cols, pk, fks in fx.TABLES:                                   # 모든 테이블의 컬럼 순서·PK 순서·FK(복합 포함)가 정의와 일치
        assert [low(c["name"]) for c in o[n]["columns"]] == [c for c, _ in cols], n
        assert [low(c) for c in o[n]["pk"]] == pk, n
        got = sorted(([low(c) for c in f["columns"]], low(f["ref_table"]), [low(c) for c in f["ref_columns"]]) for f in o[n]["fks"])
        assert got == sorted((fc, rt, rc) for fc, rt, rc in fks), n
    assert o["v_open_orders"]["kind"] == "view" and o["v_open_orders"]["view_sql"]
    assert all(f["validated"] and f["status"] == "ENABLED" for x in o.values() for f in x["fks"])
    assert sc["coverage"]["completeness"] == "UNVERIFIED"
    com = {low(c["name"]): c["comment"] for c in o["customer_role"]["columns"]}
    assert com["credit_limit"] == "여신 한도(원)"                          # 한글 주석
    assert o["stock"]["row_count_basis"].startswith("estimate")           # COUNT(*) 대신 추정치
    assert s["engine"] == real["eng"]["engine"]
    sc2 = scan(real)                                                       # 재수집: 구조 변화 없음 → diff 비어 있음, fingerprint 안정
    d = real["c"].get(f"{P}/{real['pid']}/diff?old={sc['snapshot_id']}&new={sc2['snapshot_id']}", headers=real["L"]).json()
    assert d["added"] == [] and d["removed"] == [] and d["changed"] == []


def test_relations_candidates_and_erd(real):
    scan(real)
    rel = real["c"].get(f"{P}/{real['pid']}/relations", headers=real["L"]).json()["declared"]
    assert any(low(r["from_table"]).endswith("sales_orders") and low(r["to_table"]).endswith("customer_role") and r["composite"] for r in rel)
    assert any(r["self"] for r in rel)
    cand = post(real, "/relation-candidates").json()["candidates"]
    by = {(low(x["from_table"].split(".")[1]), tuple(low(c) for c in x["from_columns"]), low(x["to_table"].split(".")[1])): x for x in cand}
    ship = by[("shipment", ("tenant_id", "order_id"), "sales_orders")]
    memo = by[("legacy_memo", ("customer_id",), "customer_role")]
    assert ship["evidence"]["inclusion_rate"] == 1.0 and memo["evidence"]["inclusion_rate"] < 0.5 and memo["status"] == "CANDIDATE"
    g = real["c"].get(f"{P}/{real['pid']}/erd/subgraphs?focus=sales_orders&hops=1", headers=real["L"]).json()
    assert len(g["nodes"]) >= 4 and any(e["style"] == "dashed" for e in g["edges"])


def test_profile_sample_and_masking(real):
    s = snap(scan(real))
    oid = next(k for k, v in s["objects"].items() if low(v["name"]) == "party")
    r = post(real, "/profiles", object_id=oid, sample_rows=3).json()
    assert r["basis"] == "sample" and all(c["rows"] <= 3 for c in r["columns"])
    assert all(c["masked"] and c["min"] is None for c in r["columns"] if low(c["column"]) in ("name", "biz_no"))


def test_first_slice_decision_and_tenant_isolation(real):
    scan(real)
    approve(real)
    r = post(real, "/agent-runs", tenant_id="T1", order_id="SO-1001", new_qty=35).json()
    d = r["result"]["detail"]
    assert r["result"]["verdict"] == "CONDITIONAL" and (d["request"]["extra_needed"], d["stock"]["additional_available"], d["shortage"], d["max_feasible_qty"]) == (15, 12, 3, 32)
    t2 = post(real, "/agent-runs", tenant_id="T2", order_id="SO-1001", new_qty=10).json()["result"]
    assert t2["detail"]["stock"]["on_hand"] == 5 and t2["verdict"] == "IMPOSSIBLE"


def test_native_pipeline(real):
    scan(real)
    rid = approve(real)
    plan = post(real, "/compilations", release_id=rid, engine="native").json()
    run = post(real, "/pipeline-runs", plan_id=plan["plan_id"]).json()
    assert run["state"] == "SUCCEEDED", run
    assert run["stages"][0]["rows"] == {"canonical_orders": 3, "canonical_stock": 2}


def _legacy_change(k):
    sql = "update sales_orders set requested_qty=requested_qty+5, row_version=row_version+1 where tenant_id='T1' and order_id='SO-1002'"
    sql2 = "update stock set row_version=row_version+1 where tenant_id='T1'"
    if k == "pg":
        import psycopg2
        c = psycopg2.connect(host="127.0.0.1", port=15432, dbname="wzdev", user="postgres", password="wzpass")
        c.autocommit = True
        cu = c.cursor()
        cu.execute("set search_path to wzdev")
        cu.execute(sql)
        cu.execute(sql2)
    elif k == "mysql":
        import pymysql
        c = pymysql.connect(host="127.0.0.1", port=13306, user="root", password="wzpass", database="wzdev", autocommit=True)
        cu = c.cursor()
        cu.execute(sql)
        cu.execute(sql2)
    else:
        import oracledb
        c = oracledb.connect(user="wzdev", password="wzpass", dsn="127.0.0.1:11521/FREEPDB1")
        cu = c.cursor()
        cu.execute(sql)
        cu.execute(sql2)
        c.commit()
    c.close()


def test_command_via_separate_account_once_and_conflict_detection(real):
    scan(real)
    approve(real)
    pr = post(real, "/proposals", "R2", tenant_id="T1", order_id="SO-1001", new_qty=32).json()
    assert post(real, "/approvals", "R", proposal_id=pr["proposal_id"], payload_hash=pr["payload_hash"]).status_code == 200
    r1 = post(real, "/commands", proposal_id=pr["proposal_id"], payload_hash=pr["payload_hash"], idempotency_key="real-key-0001")
    assert r1.status_code == 200 and r1.json()["state"] == "EXECUTED", r1.text
    r2 = post(real, "/commands", proposal_id=pr["proposal_id"], payload_hash=pr["payload_hash"], idempotency_key="real-key-0001").json()
    assert r2["replayed"] and r2["command_id"] == r1.json()["command_id"]
    after = post(real, "/agent-runs", tenant_id="T1", order_id="SO-1001", new_qty=33).json()["result"]["detail"]
    assert after["order"]["current_qty"] == 32 and after["order"]["row_version"] == 2 and after["stock"]["additional_available"] == 0
    # 승인 뒤 기존 레거시 UI 가 다른 주문을 바꾼 경우 → STALE(원천 미변경)
    from tools import ax_seed_real as sd
    sd.seed(real["k"])
    pr2 = post(real, "/proposals", "R2", tenant_id="T1", order_id="SO-1001", new_qty=30).json()
    post(real, "/approvals", "R", proposal_id=pr2["proposal_id"], payload_hash=pr2["payload_hash"])
    _legacy_change(real["k"])
    r = post(real, "/commands", proposal_id=pr2["proposal_id"], payload_hash=pr2["payload_hash"], idempotency_key="real-key-0002")
    assert r.status_code == 409 and r.json()["error"]["code"] == "STALE_PROPOSAL", r.text
    after = post(real, "/agent-runs", tenant_id="T1", order_id="SO-1001", new_qty=30).json()["result"]["detail"]
    assert after["order"]["current_qty"] == 20


def test_account_separation_ro_cannot_write_and_command_is_column_limited(real):
    k = real["k"]
    ro_u, ro_p = SEC[k][0].split(":")
    cm_u, cm_p = SEC[k][1].split(":")

    def conn(u, p):
        if k == "pg":
            import psycopg2
            c = psycopg2.connect(host="127.0.0.1", port=15432, dbname="wzdev", user=u, password=p)
            cu = c.cursor()
            cu.execute("set search_path to wzdev")
            return c, cu
        if k == "mysql":
            import pymysql
            c = pymysql.connect(host="127.0.0.1", port=13306, user=u, password=p, database="wzdev")
            return c, c.cursor()
        import oracledb
        c = oracledb.connect(user=u, password=p, dsn="127.0.0.1:11521/FREEPDB1")
        cu = c.cursor()
        cu.execute("ALTER SESSION SET CURRENT_SCHEMA=WZDEV")
        return c, cu
    c, cu = conn(ro_u, ro_p)
    with pytest.raises(Exception):
        cu.execute("update sales_orders set requested_qty=1")
        c.commit()
    c, cu = conn(cm_u, cm_p)
    with pytest.raises(Exception):
        cu.execute("update stock set on_hand=0")
        c.commit()
    with pytest.raises(Exception):
        cu.execute("update sales_orders set status='X'")
        c.commit()


def test_all_golden_and_security_cases_pass_on_real_engine(real):
    """매출·매입 8개 도구의 golden 24건·보안 11건이 실제 엔진 SQL(방언 차이 포함)에서도 같은 값을 낸다."""
    scan(real)
    approve(real)
    ev = post(real, "/evaluations").json()
    bad = [c for c in ev["golden"]["cases"] if not c["pass"]]
    assert not bad, bad
    assert ev["golden"]["total"] == 24 and ev["gates_passed"] and all(x["pass"] for x in ev["security"])


def test_signals_on_real_engine(real):
    scan(real)
    r = post(real, "/signals/scan", as_of="2026-12-01").json()
    kinds = {x["kind"] for x in real["c"].get(f"{P}/{real['pid']}/signals", headers=real["L"]).json()}
    assert r["new"] >= 4 and {"CONTRACT_EXPIRING", "RECEIPT_OUT_OF_TOLERANCE"} <= kinds
