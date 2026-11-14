"""확장 기능 테스트: 현장 대조표·기능 만료·투입 승인·개인정보·비용 프로필·프로젝트 트랙·고객 시연·파일럿 보고."""
import json
from datetime import datetime, timedelta, timezone
from test_at import client, env, login, cmd, sql, start_wh, fix_perm, FIX_VIEW  # noqa: F401
from test_labs import evidence_for
from backend import v11_ext, core


def test_feature_staleness_and_recheck(env):
    old = (datetime.now(timezone.utc) - timedelta(days=40)).date().isoformat()
    fs = [{"feature_id": "x", "status": "DOC_CHECKED", "doc_checked_at": old}, {"feature_id": "y", "status": "DOC_CHECKED", "doc_checked_at": datetime.now(timezone.utc).date().isoformat()}, {"feature_id": "z", "status": "DRAFT", "doc_checked_at": None}]
    v = {f["feature_id"]: f for f in v11_ext.feature_view(fs)}
    assert v["x"]["stale"] and v["x"]["status_effective"] == "STALE" and not v["y"]["stale"] and not v["z"]["stale"]
    api = env["c"].get("/api/features", headers=env["L"]).json()["features"]
    assert all("status_effective" in f for f in api)
    assert env["c"].post("/api/features/unity_catalog/recheck", headers=env["L"], json={}).status_code == 403
    r = env["c"].post("/api/features/unity_catalog/recheck", headers=env["R"], json={"workspace_checked": True}).json()
    assert r["status"] == "WORKSPACE_CHECKED" and r["workspace_checked_at"]
    core.FEATURES[0]["status"] = "DOC_CHECKED"; core.FEATURES[0]["workspace_checked_at"] = None     # 다른 테스트에 영향 없도록 복원


def test_verification_matrix_columns_and_honest_rate(env):
    m0 = env["c"].get("/api/verification-matrix", headers=env["L"]).json()
    assert m0["match_rate"] is None and m0["unverified_features"]                                  # 대조 전에는 일치율을 주장하지 않음
    row = {c: "x" for c in v11_ext.MATRIX_COLS}; row.update(severity="none", feature_id="unity_catalog")
    assert env["c"].post("/api/verification-matrix", headers=env["L"], json=row).status_code == 403
    bad = dict(row); bad.pop("actual")
    assert env["c"].post("/api/verification-matrix", headers=env["R"], json=bad).status_code == 400
    assert env["c"].post("/api/verification-matrix", headers=env["R"], json={**row, "severity": "bogus"}).status_code == 400
    assert env["c"].post("/api/verification-matrix", headers=env["R"], json=row).status_code == 200
    env["c"].post("/api/verification-matrix", headers=env["R"], json={**row, "feature_id": "genie_agents", "severity": "high", "diff": "메뉴 위치 다름"})
    m = env["c"].get("/api/verification-matrix", headers=env["L"]).json()
    assert m["match_rate"] == 50.0 and "unity_catalog" in m["verified_features"] and "genie_agents" not in m["unverified_features"] and m["critical_or_high_mismatches"]
    assert "oracle_cdc" in m["unverified_features"]                                                  # 미검증은 분모에 넣지 않고 별도 표시


def test_assignment_authorization_requires_basis_and_separation(env):
    me = env["c"].get("/api/me", headers=env["L"]).json()["user_id"]
    body = {"learner": me, "role": "data_engineer", "scope": "교육용 PoC 모듈"}
    r = env["c"].post("/api/assignment-authorizations", headers=env["R"], json=body)
    assert r.status_code == 409 and r.json()["error"]["code"] == "NO_BASIS_GRADE"                  # 공식 자격/학습 완료만으로는 부여 불가
    from test_labs import submit as _submit, approve as _approve
    ev = _submit(env, "L", evidence_for("LAB-CORE-01")).json()
    assert _approve(env, ev).json()["status"] == "APPROVED"
    g = env["c"].post("/api/grade-decisions", headers=env["R"], json={"learner": me, "track": "DE-A", "grade": "L2", "scores": {"practical": 90, "explain": 90}}).json()
    assert g["status"] == "APPROVED"
    assert env["c"].post("/api/assignment-authorizations", headers=env["L"], json=body).status_code == 403
    a = env["c"].post("/api/assignment-authorizations", headers=env["R"], json=body).json()
    assert a["status"] == "ACTIVE" and a["basis_grade_decision"] == g["decision_id"] and a["valid_until"]
    rev_id = env["c"].get("/api/me", headers=env["R"]).json()["user_id"]
    assert env["c"].post("/api/assignment-authorizations", headers=env["R"], json={**body, "learner": rev_id}).status_code == 403   # 본인 승인 불가
    mine = env["c"].get("/api/learners/me/assignments", headers=env["L"]).json()
    assert mine[0]["effective"] is True
    other = login(env["c"], "learner", "snoop")
    assert env["c"].get(f"/api/learners/{me}/assignments", headers=other).status_code == 403
    env["c"].post(f"/api/assignment-authorizations/{a['authorization_id']}/revoke", headers=env["R"], json={"reason": "범위 종료"})
    assert env["c"].get("/api/learners/me/assignments", headers=env["L"]).json()[0]["effective"] is False


def test_academy_record_needs_verification(env):
    r = env["c"].post("/api/academy-records", headers=env["L"], json={"course": "Data Engineering with Databricks", "completed_on": "2026-10-01", "proof_ref": "badge-123"}).json()
    assert r["status"] == "PENDING_VERIFICATION"
    assert env["c"].post(f"/api/academy-records/{r['record_id']}/verify", headers=env["L"], json={"source_url": "u"}).status_code == 403
    assert env["c"].post(f"/api/academy-records/{r['record_id']}/verify", headers=env["R"], json={}).status_code == 400
    assert env["c"].post(f"/api/academy-records/{r['record_id']}/verify", headers=env["R"], json={"source_url": "https://example.invalid/b"}).json()["status"] == "VERIFIED"
    assert len(env["c"].get("/api/learners/me/academy", headers=env["L"]).json()) == 1


def test_privacy_export_and_delete_retains_audit_records(env):
    me = env["c"].get("/api/me", headers=env["L"]).json()["user_id"]
    env["c"].post("/api/credentials", headers=env["L"], json={"name": "x-cert"})
    env["c"].post("/api/learning-plans", headers=env["L"], json={"exam_id": "DE-A", "diagnostic": {"ingest": 40}})
    env["c"].post("/api/exam-attempts", headers=env["L"], json={"exam_id": "DE-A", "kind": "practice"})
    env["c"].post("/api/grade-decisions", headers=env["R"], json={"learner": me, "track": "DE-A", "grade": "L1", "core_completion": True})
    ex = env["c"].get("/api/learners/me/export", headers=env["L"]).json()
    assert ex["learner"] == me and ex["credentials"] and ex["plans"] and ex["attempts"] and ex["grades"] and ex["policy"]["rights"]
    assert "per_item" not in json.dumps(ex)
    d = env["c"].post("/api/learners/me/delete", headers=env["L"]).json()
    assert d["deleted"]["credentials"] >= 1 and d["deleted"]["plans"] >= 1 and d["deleted"]["attempts"] >= 1
    ex2 = env["c"].get("/api/learners/me/export", headers=env["L"]).json()
    assert not ex2["credentials"] and not ex2["plans"] and not ex2["attempts"] and ex2["grades"]     # 등급 결정은 보존
    assert env["c"].get("/api/privacy-policy", headers=env["L"]).json()["note"]


def test_cost_requires_price_source_and_date(env):
    start_wh(env)
    sql(env, "SELECT 1")
    c0 = env["c"].get(f"/api/sessions/{env['sid']}/cost", headers=env["L"]).json()
    assert c0["estimate"] is None and c0["usage_index_units"] >= 1 and "사용량 지수만" in c0["note"]
    r = env["c"].post(f"/api/sessions/{env['sid']}/commands", headers=env["L"], json={"command_type": "cost.set_profile", "payload": {"unit_price": 0.5, "currency": "USD"}})
    assert r.status_code == 400                                                                      # 출처·기준일 없으면 거부
    ok = cmd(env, "cost.set_profile", {"unit_price": 0.5, "currency": "USD", "source": "사내 교육용 단가표 v1(가정)", "as_of": "2026-11-11"})["result"]
    assert ok["estimate"]["amount"] == round(ok["usage_index_units"] * 0.5, 4) and "실제 청구액이 아닙니다" in ok["components_note"]


def test_project_track_and_customer_demo_from_real_evidence(env):
    t0 = env["c"].get(f"/api/sessions/{env['sid']}/track", headers=env["L"]).json()
    assert len(t0["modules"]) == 8 and t0["percent"] == 0 and {s["id"] for m in t0["modules"] for s in m["steps"]} >= {"env", "perm", "pipe", "cdc", "order", "bundle"}
    d0 = env["c"].get(f"/api/sessions/{env['sid']}/demo", headers=env["L"]).json()
    assert d0["minutes_total"] == 20 and len(d0["segments"]) == 6 and len(d0["qa"]) == 6
    assert not any(s["ready"] for s in d0["segments"]) and not d0["qa"][0]["demonstrated"] and "아직 재현하지 않음" in d0["qa"][0]["answer"]
    start_wh(env)
    sql(env, "SELECT * FROM food_dev.silver.orders LIMIT 1")                                          # 권한 오류 재현
    d1 = env["c"].get(f"/api/sessions/{env['sid']}/demo", headers=env["L"]).json()
    assert d1["qa"][0]["demonstrated"] and d1["qa"][0]["evidence"] and "USE SCHEMA" in d1["qa"][0]["answer"]
    assert d1["segments"][0]["ready"]                                                                 # 환경 점검 증거가 생기면 1구간 준비 완료


def test_pilot_report_is_staff_only_and_honest(env):
    assert env["c"].get("/api/pilot-report", headers=env["L"]).status_code == 403
    r = env["c"].get("/api/pilot-report", headers=env["I"]).json()
    assert r["sessions"] >= 1 and "파일럿 미수행" in r["sample_note"] and "objective별 향상" in r["metrics_defined"]
