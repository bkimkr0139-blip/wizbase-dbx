"""실제 DBX 실습(C 경로) 테스트: adapter 안전장치, 서버 자동 대조, 위변조·재사용 차단.
주의: adapter는 가짜 Statement API(DuckDB)로 검증한다. 실제 Databricks 워크스페이스 대상 실행은 이 환경에서 검증하지 못했다."""
import json, re
import duckdb
import pytest
from decimal import Decimal
from test_at import client, env, login  # noqa: F401
from adapter import dbx_lab_runner as runner, dbx_lab_common as common
from backend import labs


class FakeStatementAPI:
    """Databricks SQL Statement Execution API 응답 형태(JSON_ARRAY, 모든 값 문자열)를 DuckDB로 흉내 낸다."""
    def __init__(self, catalog="cat"):
        self.c = duckdb.connect(); self.n = 0; self.catalog = catalog; self.log = []

    def call(self, method, path, body=None):
        if method == "post" and path == "/api/2.0/sql/statements":
            sql = body["statement"]; self.log.append(sql)
            self.n += 1; sid = "01f0-" + __import__("uuid").uuid4().hex
            low = sql.strip().lower()
            if low == "select version()":
                return {"statement_id": sid, "status": {"state": "SUCCEEDED"}, "manifest": {"schema": {"columns": [{"name": "version()"}]}}, "result": {"data_array": [["4.0.0 fakehash"]]}}
            if low.startswith("show tables in"):
                return {"statement_id": sid, "status": {"state": "SUCCEEDED"}, "manifest": {"schema": {"columns": [{"name": "tableName"}]}}, "result": {"data_array": [["inventory"]]}}
            if low.startswith("describe history"):
                return {"statement_id": sid, "status": {"state": "SUCCEEDED"}, "manifest": {"schema": {"columns": [{"name": "operation"}]}}, "result": {"data_array": [["CREATE TABLE"], ["MERGE"]]}}
            q = re.sub(r"\s+USING\s+DELTA", "", sql.replace(self.catalog + ".", ""), flags=re.I)
            try:
                cur = self.c.execute(q)
            except Exception as e:
                return {"statement_id": sid, "status": {"state": "FAILED", "error": {"message": str(e)}}}
            rows = [] if cur.description is None else [[None if v is None else str(v) for v in r] for r in cur.fetchall()]
            cols = [] if cur.description is None else [{"name": d[0]} for d in cur.description]
            return {"statement_id": sid, "status": {"state": "SUCCEEDED"}, "manifest": {"schema": {"columns": cols}}, "result": {"data_array": rows}}
        raise AssertionError(path)


def evidence_for(lab_id, **kw):
    pack = labs.pack(lab_id)
    ev = runner.run_pack(pack, "cat", "wh1", FakeStatementAPI("cat"), cleanup=True, log=lambda *_: None)
    ev.update(workspace_ref="ws-***1234", cloud="aws", region="ap-northeast-2", exam_id="DE-A", **kw)
    return ev


# ---- 콘텐츠·정규화
def test_expected_results_computable_for_all_machine_labs():
    for k, l in labs.LABS.items():
        if l["kind"] == "machine":
            exp = labs.expected(k)
            assert exp and all(len(v[0]) == 64 for v in exp.values()), k
    assert labs.expected("LAB-DE-03")["after_merge"][1] == 3  # P-001 갱신, P-003 삭제, P-004 삽입


def test_normalization_matches_spark_string_output():
    assert common.checksum_rows([("P-001", "12")]) == common.checksum_rows([("P-001", 12)])
    assert common.checksum_rows([("37.40",)]) == common.checksum_rows([(Decimal("37.4"),)]) == common.checksum_rows([(37.4,)])
    assert common.checksum_rows([("a", None)]) == common.checksum_rows([("a", None)])
    assert common.checksum_rows([(1,), (2,)]) == common.checksum_rows([(2,), (1,)])        # 행 순서 무관
    assert common.checksum_rows([("x",)]) != common.checksum_rows([("y",)])


def test_public_catalog_never_exposes_expected_values(env):
    cat = env["c"].get("/api/labs", headers=env["L"]).json()
    blob = json.dumps(cat) + json.dumps(env["c"].get("/api/labs/LAB-DE-02/pack", headers=env["L"]).json())
    for lab_id in ("LAB-CORE-01", "LAB-DE-02", "LAB-DE-03"):
        for chk, _ in labs.expected(lab_id).values():
            assert chk not in blob
    assert cat["authored"] == len(labs.LABS) == cat["total_packs_in_spec"] == 21      # 지시서 팩 21개 전부 작성(검증 상태는 별도)
    assert env["c"].get("/api/labs").status_code == 401


# ---- adapter 안전장치
def test_adapter_safety_rules():
    ok = runner.check_sql_safe("SELECT * FROM cat.wz_lab_x.t", "cat", "wz_lab_x")
    assert ok
    bad = ["GRANT SELECT ON TABLE cat.wz_lab_x.t TO `a`", "SELECT * FROM cat.other.t", "SELECT * FROM prod.wz_lab_x.t", "SELECT 1; SELECT 2", "DROP TABLE cat.wz_lab_x.t",
           "CREATE SCHEMA IF NOT EXISTS cat.other", "ALTER TABLE cat.wz_lab_x.t ADD COLUMN c INT", "COPY INTO cat.wz_lab_x.t FROM 's3://b'", "CREATE CATALOG x", "DROP SCHEMA IF EXISTS cat.other CASCADE", "UPDATE cat.wz_lab_x.t SET a=1"]
    for q in bad:
        with pytest.raises(runner.SafetyError):
            runner.check_sql_safe(q, "cat", "wz_lab_x")
    with pytest.raises(runner.SafetyError):
        runner.check_sql_safe("SELECT 1", "system", "wz_lab_x")
    with pytest.raises(runner.SafetyError):
        runner.check_sql_safe("SELECT 1", "cat", "production")


def test_adapter_rejects_tampered_pack_and_stays_in_schema():
    pack = labs.pack("LAB-CORE-01")
    tampered = json.loads(json.dumps(pack)); tampered["setup"].append("GRANT ALL PRIVILEGES ON CATALOG cat TO `x`")
    with pytest.raises(runner.SafetyError):
        runner.run_pack(tampered, "cat", "wh", FakeStatementAPI("cat"), log=lambda *_: None)
    api = FakeStatementAPI("cat")
    runner.run_pack(pack, "cat", "wh", api, cleanup=True, log=lambda *_: None)
    assert all(("wz_lab_core01" in q) or q.strip().lower() == "select version()" for q in api.log)   # 모든 SQL이 지정 스키마 범위


def test_evidence_contains_no_credentials():
    ev = evidence_for("LAB-CORE-01")
    s = json.dumps(ev)
    for bad in ("dapi", "token", "password", "Bearer", "https://", "host"):
        assert bad not in s, bad


# ---- 서버 자동 대조
def submit(env, who, ev):
    return env["c"].post("/api/lab-evidence", headers=env[who], json=ev)


def test_matching_evidence_flow_and_review(env):
    ev = evidence_for("LAB-DE-02")
    r = submit(env, "L", ev).json()
    assert r["status"] == "SUBMITTED" and r["auto_check"]["state"] == "MATCHED" and set(r["auto_check"]["per_task"].values()) == {"MATCH"}
    assert "expected" not in json.dumps(r).lower()
    assert env["c"].post(f"/api/lab-evidence/{r['evidence_id']}/review", headers=env["R"], json={"decision": "approve"}).status_code == 400       # 원본 확인 필수
    done = env["c"].post(f"/api/lab-evidence/{r['evidence_id']}/review", headers=env["R"], json={"decision": "approve", "original_checked": True}).json()
    assert done["status"] == "APPROVED" and done["evidence_level"] == "DBX_VERIFIED_REVIEWED"
    me = env["c"].get("/api/me", headers=env["L"]).json()["user_id"]
    from backend import v11
    st = v11.labs_status(me, "DE-A")
    assert "LAB-DE-02" in st["approved"] and not st["not_authored"] and "LAB-DE-01" in st["missing"]


def test_wrong_results_are_rejected_without_leaking_expected(env):
    ev = evidence_for("LAB-CORE-01")
    ev["task_results"]["available"]["checksum"] = "0" * 64
    r = submit(env, "L", ev).json()
    assert r["status"] == "REJECTED_RESULT_MISMATCH" and r["auto_check"]["per_task"]["available"] == "MISMATCH" and r["auto_check"]["per_task"]["count"] == "MATCH"
    assert labs.expected("LAB-CORE-01")["available"][0] not in json.dumps(r)      # 틀린 task의 기대값은 응답에 없음(맞게 제출한 task 값은 본인 제출값의 반향)
    assert env["c"].post(f"/api/lab-evidence/{r['evidence_id']}/review", headers=env["R"], json={"decision": "approve", "original_checked": True}).status_code == 409


def test_stale_pack_missing_task_and_missing_statement_id(env):
    ev = evidence_for("LAB-CORE-01"); ev["pack_hash"] = "f" * 64
    assert submit(env, "L", ev).json()["status"] == "REJECTED_PACK_STALE"
    ev = evidence_for("LAB-CORE-01"); ev["task_results"].pop("count")
    assert submit(env, "L", ev).json()["status"] == "NEEDS_ORIGINAL"
    ev = evidence_for("LAB-CORE-01"); ev["task_results"]["count"]["statement_id"] = ""
    assert submit(env, "L", ev).json()["status"] == "NEEDS_ORIGINAL"


def test_evidence_reuse_by_another_learner_rejected(env):
    ev = evidence_for("LAB-DE-03")
    assert submit(env, "L", ev).json()["status"] == "SUBMITTED"
    other = login(env["c"], "learner", "copycat")
    r = env["c"].post("/api/lab-evidence", headers=other, json=ev).json()
    assert r["status"] == "REJECTED_DUPLICATE"


def test_cli_bundle_evidence_checks(env):
    base = {"lab_id": "LAB-DE-12", "exam_id": "DE-A", "workspace_ref": "ws-***9", "cloud": "aws", "region": "ap-northeast-2", "run_id": "run-1", "source_hash": "ab", "result_checksum": "cd"}
    good = submit(env, "L", {**base, "cli_version": "0.221.0", "validate_exit": 0, "runtime_version": "0.221.0", "observed_runtime_version": "0.221.0"}).json()
    assert good["status"] == "SUBMITTED" and good["auto_check"]["state"] == "CLI_OK"
    old = submit(env, "L", {**base, "cli_version": "0.200.0", "validate_exit": 0, "runtime_version": "0.200.0", "observed_runtime_version": "0.200.0"}).json()
    assert old["status"] == "REJECTED_CLI_CHECK"
    failed = submit(env, "L", {**base, "cli_version": "0.221.0", "validate_exit": 1, "runtime_version": "x", "observed_runtime_version": "x"}).json()
    assert failed["status"] == "REJECTED_CLI_CHECK"


def test_manual_labs_require_artifact_hashes_and_rubric(env):
    base = {"exam_id": "DE-A", "workspace_ref": "ws-***9", "cloud": "aws", "region": "ap-northeast-2", "run_id": "r", "source_hash": "ab", "result_checksum": "cd", "runtime_version": "1", "observed_runtime_version": "1"}
    lab = labs.LABS["LAB-DE-06"]
    m = submit(env, "L", {**base, "lab_id": "LAB-DE-06"}).json()
    assert m["status"] == "NEEDS_ORIGINAL" and m["auto_check"]["state"] == "ARTIFACTS_MISSING"            # 산출물 없이는 통과 불가
    arts = {a: common.checksum_rows([(a,)])[0] for a in lab["required_artifacts"]}
    bad = dict(arts); bad[lab["required_artifacts"][0]] = "not-a-hash"
    assert submit(env, "L", {**base, "lab_id": "LAB-DE-06", "artifacts": bad}).json()["status"] == "NEEDS_ORIGINAL"
    ok = submit(env, "L", {**base, "lab_id": "LAB-DE-06", "artifacts": arts}).json()
    assert ok["status"] == "SUBMITTED" and ok["auto_check"]["state"] == "ARTIFACTS_COMPLETE"
    rv = lambda body: env["c"].post(f"/api/lab-evidence/{ok['evidence_id']}/review", headers=env["R"], json=body)
    full = {r["item"]: r["max"] for r in lab["rubric"]}
    assert rv({"decision": "approve", "original_checked": True}).status_code == 400                       # 루브릭 필수
    part = dict(full); part.pop(lab["rubric"][0]["item"])
    assert rv({"decision": "approve", "original_checked": True, "rubric_scores": part}).status_code == 400
    over = dict(full); over[lab["rubric"][0]["item"]] = lab["rubric"][0]["max"] + 1
    assert rv({"decision": "approve", "original_checked": True, "rubric_scores": over}).status_code == 400
    low = {k: 0 for k in full}
    held = rv({"decision": "approve", "original_checked": True, "rubric_scores": low}).json()
    assert held["status"] == "ON_HOLD" and held["rubric_total"] == 0                                        # 합격 점수 미달은 보류
    ok2 = submit(env, "L", {**base, "lab_id": "LAB-DE-06", "artifacts": arts}).json()
    done = env["c"].post(f"/api/lab-evidence/{ok2['evidence_id']}/review", headers=env["R"], json={"decision": "approve", "original_checked": True, "rubric_scores": full}).json()
    assert done["status"] == "APPROVED" and done["rubric_total"] == 100


def test_all_21_pack_ids_defined_and_scd_lab_machine_checked(env):
    from backend.content import PACKS
    assert {f"LAB-{p}" for p in PACKS} == set(labs.LABS)
    assert labs.LABS["LAB-DE-05"]["kind"] == "machine" and set(labs.expected("LAB-DE-05")) == {"scd1_latest", "scd2_history"}
    for l in labs.LABS.values():
        if l["kind"] == "manual":
            assert sum(r["max"] for r in l["rubric"]) == 100 and l["required_artifacts"] and l["steps"]
    ev = evidence_for("LAB-DE-05")
    r = submit(env, "L", ev).json()
    assert r["status"] == "SUBMITTED" and r["auto_check"]["state"] == "MATCHED"
    import tempfile, os
    f = tempfile.NamedTemporaryFile(delete=False, suffix=".md"); f.write(b"hello"); f.close()
    h = runner.hash_artifacts([f.name])
    assert list(h.values())[0] == __import__("hashlib").sha256(b"hello").hexdigest(); os.unlink(f.name)
