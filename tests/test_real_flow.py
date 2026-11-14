"""사전훈련 → 실제 DBX 수행(adapter) → 증거 검토·등급 반영 흐름 테스트.
주의: adapter 실행은 가짜 Statement API(DuckDB)로만 검증한다. 실제 Databricks 워크스페이스 대상 실행은 검증하지 못했다."""
import io, json, re, zipfile
import pytest
from test_at import client, env, login  # noqa: F401
from test_labs import FakeStatementAPI, evidence_for, submit, approve
from adapter import dbx_lab_runner as runner
from backend import labs, v11


def _me(env, who="L"):
    return env["c"].get("/api/me", headers=env[who]).json()["user_id"]


def _attempt(env, lab_id, who="L"):
    return env["c"].post(f"/api/labs/{lab_id}/attempt", headers=env[who]).json()


# ---- adapter 1.1: 시도 표식 · doctor
def test_adapter_tags_every_statement_with_attempt_id_and_stays_safe():
    api = FakeStatementAPI("cat")
    pack = labs.pack("LAB-CORE-01")
    ev = runner.run_pack(pack, "cat", "wh1", api, cleanup=True, log=lambda *_: None, attempt_id="wzA-0123456789ab")
    pack_sql = [s for s in api.log if s.strip().lower() != "select version()"]
    assert pack_sql and all(s.rstrip().endswith("/* wzA-0123456789ab */") for s in pack_sql)
    assert ev["attempt_id"] == "wzA-0123456789ab" and ev["adapter_version"] == "1.1"
    assert not any("wzA" in s for s in api.log if s.strip().lower() == "select version()")
    with pytest.raises(runner.SafetyError):
        runner.tag_sql("SELECT 1", "wzA-x; DROP SCHEMA x")               # 표식 형식이 아니면 SQL에 넣지 않는다
    # 주석 표식이 금지 키워드 검사를 우회 수단이 되지 않는다(검사는 표식 부착 전 원문에 대해 수행)
    with pytest.raises(runner.SafetyError):
        runner.check_sql_safe("SELECT 1 /* x */; DROP TABLE cat.wz_lab_x.t", "cat", "wz_lab_x")


class DoctorApi(FakeStatementAPI):
    def __init__(self, fail=None, **kw):
        super().__init__(**kw); self.fail = fail

    def call(self, method, path, body=None):
        if path.startswith("/api/2.0/preview/scim"):
            if self.fail == "auth":
                raise RuntimeError("databricks CLI 오류: 401")
            return {"userName": "someone@example.com"}
        if path.startswith("/api/2.0/sql/warehouses/"):
            if self.fail == "wh":
                raise RuntimeError("databricks CLI 오류: 403")
            return {"state": "RUNNING"}
        if self.fail == "write" and body and "CREATE SCHEMA" in body.get("statement", ""):
            return {"statement_id": "x", "status": {"state": "FAILED", "error": {"message": "PERMISSION_DENIED"}}}
        return super().call(method, path, body)


def test_doctor_reports_each_failure_with_hint_and_leaks_nothing(monkeypatch):
    monkeypatch.setattr(runner, "cli_version", lambda: "0.250.0")
    ok = runner.doctor("cat", "wh1", DoctorApi(catalog="cat"), log=lambda *_: None)
    assert ok["ok"] and len(ok["checks"]) == 5 and "someone@example.com" not in json.dumps(ok)
    for fail, name in (("auth", "CLI 인증"), ("wh", "SQL warehouse"), ("write", "catalog 쓰기")):
        r = runner.doctor("cat", "wh1", DoctorApi(fail=fail, catalog="cat"), log=lambda *_: None)
        bad = [c for c in r["checks"] if not c["ok"]]
        assert not r["ok"] and bad and name in bad[0]["name"] and bad[0]["hint"]
    monkeypatch.setattr(runner, "cli_version", lambda: "0.100.0")
    old = runner.doctor("cat", "wh1", DoctorApi(catalog="cat"), log=lambda *_: None)
    assert not old["ok"] and "0.218.0" in old["checks"][0]["hint"]


# ---- 시도 ID
def test_attempt_required_one_time_and_bound_to_learner_and_lab(env):
    ev = evidence_for("LAB-CORE-01")
    no_attempt = env["c"].post("/api/lab-evidence", headers=env["L"], json=ev).json()
    assert no_attempt["status"] == "REJECTED_ATTEMPT" and no_attempt["attempt_state"] == "UNKNOWN"
    a = _attempt(env, "LAB-CORE-01")
    assert re.fullmatch(r"wzA-[0-9a-f]{12}", a["attempt_id"]) and a["pack_hash"] == labs.LABS["LAB-CORE-01"]["pack_hash"] and "--attempt-id " + a["attempt_id"] in a["command"]
    other = login(env["c"], "learner", "borrower")
    stolen = env["c"].post("/api/lab-evidence", headers=other, json={**ev, "attempt_id": a["attempt_id"]}).json()
    assert stolen["status"] == "REJECTED_ATTEMPT" and stolen["attempt_state"] == "MISMATCH"
    wrong_lab = env["c"].post("/api/lab-evidence", headers=env["L"], json={**evidence_for("LAB-DE-02"), "attempt_id": a["attempt_id"]}).json()
    assert wrong_lab["attempt_state"] == "MISMATCH"
    good = env["c"].post("/api/lab-evidence", headers=env["L"], json={**ev, "attempt_id": a["attempt_id"]}).json()
    assert good["status"] == "SUBMITTED" and good["attempt_state"] == "OK"
    again = env["c"].post("/api/lab-evidence", headers=env["L"], json={**ev, "attempt_id": a["attempt_id"]}).json()
    assert again["status"] == "REJECTED_ATTEMPT" and again["attempt_state"] == "REUSED"


def test_old_adapter_is_not_accepted_for_sql_labs(env):
    ev = {**evidence_for("LAB-CORE-01"), "adapter_version": "1.0"}
    r = submit(env, "L", ev).json()
    assert r["status"] == "NEEDS_ORIGINAL" and r["auto_check"]["state"] == "ADAPTER_OLD" and "doctor" in r["reason"]
    r = submit(env, "L", {k: v for k, v in evidence_for("LAB-CORE-01").items() if k != "adapter_version"}).json()
    assert r["auto_check"]["state"] == "ADAPTER_OLD"


# ---- 검토 센터 큐 · 구조화된 원본 확인 · 보류/반려
def test_review_queue_counts_only_reviewable_and_exposes_what_reviewer_needs(env):
    ok = submit(env, "L", evidence_for("LAB-CORE-01")).json()
    bad_ev = evidence_for("LAB-DE-02"); bad_ev["task_results"]["dedupe"]["checksum"] = "0" * 64
    bad = submit(env, "L", bad_ev).json()
    assert bad["status"] == "REJECTED_RESULT_MISMATCH"
    q = env["c"].get("/api/review/queue", headers=env["R"]).json()
    ids = [x["evidence_id"] for x in q["lab_queue"]]
    assert ok["evidence_id"] in ids and bad["evidence_id"] not in ids                      # 검토할 수 없는 증거는 대기로 세지 않는다
    assert q["lab_evidence_pending"] == len(ids)
    row = next(x for x in q["lab_queue"] if x["evidence_id"] == ok["evidence_id"])
    assert row["auto_check"] == "MATCHED" and row["attempt_state"] == "OK" and row["adapter_version"] == "1.1" and row["pack_current"]
    assert set(row["tasks_to_check"]) == {"count", "available"}
    full = {k: (v or {}).get("statement_id") for k, v in v11.V["lab_evidence"][ok["evidence_id"]]["task_results"].items()}
    for k, t in row["tasks_to_check"].items():
        assert len(t["statement_prefix"]) == 8 and full[k] not in json.dumps(row)         # 전체 ID는 노출하지 않음 — 검토자가 Query History에서 읽어 입력
    assert row["pretrain"]["state"] in ("NONE", "IN_PROGRESS", "PASSED")
    assert env["c"].get("/api/review/queue", headers=env["L"]).status_code == 403


def test_approval_requires_statement_ids_seen_in_query_history(env):
    r = submit(env, "L", evidence_for("LAB-DE-02")).json()
    eid = r["evidence_id"]
    url = f"/api/lab-evidence/{eid}/review"
    rv = lambda body: env["c"].post(url, headers=env["R"], json=body)
    r1 = rv({"decision": "approve", "original_checked": True})
    assert r1.status_code == 400 and r1.json()["error"]["code"] == "STATEMENT_CHECK_REQUIRED"
    need = v11._compare_sids(v11.V["lab_evidence"][eid])
    assert set(need) == {"dedupe", "join_total", "running", "decimal"}
    wrong = {**need, "running": "01f0-" + "0" * 32}
    r2 = rv({"decision": "approve", "original_checked": True, "checked_statements": wrong})
    assert r2.status_code == 409 and r2.json()["error"]["code"] == "STATEMENT_MISMATCH" and "running" in r2.json()["error"]["message"]
    assert v11.V["lab_evidence"][eid]["status"] == "SUBMITTED"
    done = rv({"decision": "approve", "original_checked": True, "checked_statements": need}).json()
    assert done["status"] == "APPROVED" and done["checked_statements"] == sorted(need)
    assert any(a["kind"] == "LAB_REVIEW_STATEMENT_MISMATCH" for a in v11.V["audit"])


def test_hold_and_reject_need_reason_and_are_distinct(env):
    r = submit(env, "L", evidence_for("LAB-CORE-01")).json()
    url = f"/api/lab-evidence/{r['evidence_id']}/review"
    assert env["c"].post(url, headers=env["R"], json={"decision": "reject"}).status_code == 400
    assert env["c"].post(url, headers=env["R"], json={"decision": "maybe", "note": "????"}).status_code == 400
    assert env["c"].post(url, headers=env["L"], json={"decision": "reject", "note": "내 것 반려"}).status_code == 403
    held = env["c"].post(url, headers=env["R"], json={"decision": "hold", "note": "Query History에서 시간대가 다름"}).json()
    assert held["status"] == "ON_HOLD" and held["note"]
    rej = env["c"].post(url, headers=env["R"], json={"decision": "reject", "note": "statement가 다른 워크스페이스 것"}).json()
    assert rej["status"] == "REJECTED_BY_REVIEWER"
    assert env["c"].post(url, headers=env["R"], json={"decision": "hold", "note": "다시 보류 시도"}).status_code == 409   # 확정 반려는 되돌리지 않는다
    q = env["c"].get("/api/review/queue", headers=env["R"]).json()
    assert r["evidence_id"] not in [x["evidence_id"] for x in q["lab_queue"]]


# ---- 팩 변경 시 승인 증거 무효화(STALE)
def test_approval_goes_stale_when_pack_changes_and_blocks_grade(env, monkeypatch):
    r = submit(env, "L", evidence_for("LAB-CORE-01")).json()
    assert approve(env, r).json()["status"] == "APPROVED"
    me = _me(env)
    assert "LAB-CORE-01" in v11.labs_status(me, "DE-A")["approved"]
    flow = env["c"].get("/api/real-flow/DE-A", headers=env["L"]).json()
    assert next(x for x in flow["rows"] if x["lab_id"] == "LAB-CORE-01")["stage"] == "GRADE_READY"
    monkeypatch.setitem(labs.LABS["LAB-CORE-01"], "pack_hash", "e" * 64)
    st = v11.labs_status(me, "DE-A")
    assert "LAB-CORE-01" not in st["approved"] and "LAB-CORE-01" in st["stale"] and "LAB-CORE-01" in st["missing"]
    flow = env["c"].get("/api/real-flow/DE-A", headers=env["L"]).json()
    assert next(x for x in flow["rows"] if x["lab_id"] == "LAB-CORE-01")["stage"] == "STALE"
    g = env["c"].post("/api/grade-decisions", headers=env["R"], json={"learner": me, "track": "DE-A", "grade": "L2", "scores": {"practical": 90, "explain": 90}}).json()
    assert g["status"] == "HOLD_REAL_VERIFICATION_PENDING"                                  # 낡은 증거로는 등급 승급 불가


# ---- 흐름 상태
def test_real_flow_stages_follow_the_learner(env):
    me = _me(env)
    f = env["c"].get("/api/real-flow/DE-A", headers=env["L"]).json()
    row = lambda lab: next(x for x in f["rows"] if x["lab_id"] == lab)
    assert f["total"] == len(f["rows"]) and f["done"] == 0 and "DBX 검증 0건" in f["note"] and len(f["flow"]) == 6
    assert row("LAB-CORE-01")["stage"] in ("PRETRAIN", "READY_FOR_REAL")
    pt = v11._pretrain(me, "LAB-CORE-01")
    assert pt["state"] in ("NONE", "IN_PROGRESS") and "70%" in pt["rule"]
    a = _attempt(env, "LAB-CORE-01")
    assert next(x for x in env["c"].get("/api/real-flow/DE-A", headers=env["L"]).json()["rows"] if x["lab_id"] == "LAB-CORE-01")["stage"] == "ATTEMPT_ISSUED"
    r = env["c"].post("/api/lab-evidence", headers=env["L"], json={**evidence_for("LAB-CORE-01"), "attempt_id": a["attempt_id"]}).json()
    assert next(x for x in env["c"].get("/api/real-flow/DE-A", headers=env["L"]).json()["rows"] if x["lab_id"] == "LAB-CORE-01")["stage"] == "IN_REVIEW"
    env["c"].post(f"/api/lab-evidence/{r['evidence_id']}/review", headers=env["R"], json={"decision": "hold", "note": "원본 다시 확인 필요"})
    x = next(x for x in env["c"].get("/api/real-flow/DE-A", headers=env["L"]).json()["rows"] if x["lab_id"] == "LAB-CORE-01")
    assert x["stage"] == "ON_HOLD" and "원본" in x["label"]
    assert env["c"].get(f"/api/real-flow/DE-A?learner={me}", headers=env["R"]).status_code == 200
    other = login(env["c"], "learner", "peeker")
    assert env["c"].get(f"/api/real-flow/DE-A?learner={me}", headers=other).status_code == 403
    assert env["c"].get("/api/real-flow/XX", headers=env["L"]).status_code == 400


def test_pretrain_signal_uses_domain_practice(env):
    me = _me(env)
    per = [{"item_id": f"p{i}", "domain": "platform", "correct": i < 4, "answered": True, "eligible": False, "family": "f"} for i in range(5)]
    v11.V["attempts"]["PT1"] = {"learner": me, "exam_id": "DE-A", "status": "SUBMITTED", "kind": "practice", "result": {"per_item": per}}
    try:
        assert v11._pretrain(me, "LAB-CORE-01")["state"] == "PASSED"                          # 5문항 중 4개 = 80%
        v11.V["attempts"]["PT1"]["result"]["per_item"][3]["correct"] = False
        assert v11._pretrain(me, "LAB-CORE-01")["state"] == "IN_PROGRESS"                     # 60%
    finally:
        v11.V["attempts"].pop("PT1")


# ---- adapter 배포
def test_adapter_zip_download_contains_only_code_and_docs(env):
    r = env["c"].get("/download/adapter")
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    z = zipfile.ZipFile(io.BytesIO(r.content))
    names = set(z.namelist())
    assert names == {"wizbase-dbx-adapter/README.md", "wizbase-dbx-adapter/dbx_lab_runner.py", "wizbase-dbx-adapter/dbx_lab_common.py"}
    body = b"".join(z.read(n) for n in names).decode("utf-8")
    assert "doctor" in body and "dapi" not in body
