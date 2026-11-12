"""실제 환경 연결(내 교육용 Databricks SQL Warehouse): 웹 차단, 호스트·운영 이름·동의 검사, 읽기 전용, 위험 문장 확인, 토큰 비노출·암호화 저장."""
import json
import os

from test_at import client, env, login  # noqa: F401
from backend import real, usage

TOKEN = "dapiSECRETTOKEN1234567890"
CALLS = []


def fake_api(host, token, method, path, body=None, timeout=45):
    CALLS.append({"host": host, "token": token, "path": path, "body": body})
    sql = (body or {}).get("statement", "")
    if "BOOM" in sql:
        return {"statement_id": "s2", "status": {"state": "FAILED", "error": {"error_code": "PARSE_SYNTAX_ERROR", "message": "syntax error near BOOM"}}}
    if "current_user" in sql:
        return {"statement_id": "s1", "status": {"state": "SUCCEEDED"}, "manifest": {"schema": {"columns": [{"name": "user"}, {"name": "catalog"}, {"name": "schema"}]}, "total_row_count": 1}, "result": {"data_array": [["me@example.com", "main", "default"]]}}
    return {"statement_id": "s3", "status": {"state": "SUCCEEDED"}, "manifest": {"schema": {"columns": [{"name": "n"}, {"name": "s"}]}, "total_row_count": 2}, "result": {"data_array": [["1", "a"], ["2", None]]}}


GOOD = {"host": "adb-1234567890.1.azuredatabricks.net", "warehouse_id": "1a2b3c4d5e6f7a8b", "catalog": "training", "schema": "demo", "token": TOKEN, "consent": True}


def test_web_server_blocks_direct_connection_by_default(env, monkeypatch):
    monkeypatch.delenv("DBX_REAL_ALLOW", raising=False); monkeypatch.delenv("DBX_STANDALONE", raising=False)
    c = env["c"]
    assert c.get("/api/real/status", headers=env["L"]).json()["enabled"] is False
    r = c.post("/api/real/config", headers=env["L"], json=GOOD)
    assert r.status_code == 403 and r.json()["error"]["code"] == "REAL_DISABLED"
    assert c.post("/api/real/sql", headers=env["L"], json={"sql": "select 1"}).status_code == 403


def test_connect_validate_read_only_and_secrets(env, monkeypatch):
    monkeypatch.setenv("DBX_REAL_ALLOW", "1"); monkeypatch.setattr(real, "_api", fake_api)
    c, L = env["c"], env["L"]
    c.delete("/api/real/config", headers=L)
    for bad in ("evil.com", "127.0.0.1", "adb-1.azuredatabricks.net.evil.com", "169.254.169.254", "http://internal.cloud.databricks.com.attacker.io"):
        r = c.post("/api/real/config", headers=L, json={**GOOD, "host": bad})
        assert r.status_code == 400 and r.json()["error"]["code"] == "BAD_HOST", bad                    # 공식 도메인만(SSRF 방지)
    assert c.post("/api/real/config", headers=L, json={**GOOD, "warehouse_id": "x"}).json()["error"]["code"] == "BAD_WAREHOUSE"
    assert c.post("/api/real/config", headers=L, json={**GOOD, "catalog": "prod_sales"}).json()["error"]["code"] == "LOOKS_LIKE_PROD"
    assert c.post("/api/real/config", headers=L, json={**GOOD, "catalog": "prod_sales", "confirm_nonprod": True}).status_code == 200
    assert c.post("/api/real/config", headers=L, json={**GOOD, "consent": False}).json()["error"]["code"] == "CONSENT_REQUIRED"
    assert c.post("/api/real/config", headers=L, json={**GOOD, "token": ""}).status_code == 200            # 이미 저장된 토큰 유지
    r = c.post("/api/real/config", headers=L, json=GOOD); assert r.status_code == 200
    body = json.dumps(c.get("/api/real/status", headers=L).json())
    assert TOKEN not in body and "token" not in c.get("/api/real/status", headers=L).json()           # 토큰은 다시 내려주지 않는다
    # 저장 파일에는 토큰이 평문으로 없다(Windows는 DPAPI)
    raw = (real._dir() / "token.bin").read_bytes()
    if os.name == "nt":
        assert TOKEN.encode() not in raw
    assert real.load_secret() == TOKEN
    t = c.post("/api/real/test", headers=L).json()
    assert t["identity"]["user"] == "me@example.com" and "성공" in t["last_test"]
    assert CALLS[-1]["host"] == GOOD["host"] and CALLS[-1]["token"] == TOKEN and CALLS[-1]["body"]["warehouse_id"] == GOOD["warehouse_id"]
    # 읽기 전용: SELECT 허용, 쓰기·다문장 거부
    ok = c.post("/api/real/sql", headers=L, json={"sql": "-- 주석\nSELECT * FROM t"}).json()
    assert ok["columns"] == ["n", "s"] and ok["rows"][1][1] is None and len(ok["result_sha256"]) == 64 and ok["evidence_level"] == "REAL_WORKSPACE_EXECUTED"
    h1 = ok["result_sha256"]; assert c.post("/api/real/sql", headers=L, json={"sql": "SELECT * FROM t"}).json()["result_sha256"] == h1   # 같은 결과 → 같은 해시
    for q in ("INSERT INTO t VALUES (1)", "DROP TABLE t", "CREATE TABLE x AS SELECT 1"):
        r = c.post("/api/real/sql", headers=L, json={"sql": q}); assert r.status_code == 403 and r.json()["error"]["code"] == "READ_ONLY", q
    assert c.post("/api/real/sql", headers=L, json={"sql": "SELECT 1; DROP TABLE t"}).json()["error"]["code"] == "ONE_STATEMENT"
    assert c.post("/api/real/sql", headers=L, json={"sql": "SELECT ';' AS a"}).status_code == 200          # 문자열 안의 ; 는 문장 구분이 아니다
    e = c.post("/api/real/sql", headers=L, json={"sql": "SELECT BOOM"}).json()["error"]
    assert e["code"] == "REAL_SQL_PARSE_SYNTAX_ERROR" and "syntax" in e["message"]
    # 쓰기 허용 + 위험 문장은 매번 확인
    assert c.post("/api/real/config", headers=L, json={**GOOD, "write_allowed": True}).status_code == 200
    assert c.post("/api/real/sql", headers=L, json={"sql": "INSERT INTO t VALUES (1)"}).status_code == 200
    r = c.post("/api/real/sql", headers=L, json={"sql": "DROP TABLE t"}); assert r.status_code == 409 and r.json()["error"]["code"] == "CONFIRM_REQUIRED"
    assert c.post("/api/real/sql", headers=L, json={"sql": "DROP TABLE t", "confirm": True}).status_code == 200
    # 감사·사용 기록·상태 어디에도 토큰이 없다
    audit = (real._dir() / "audit.jsonl").read_text(encoding="utf-8")
    assert TOKEN not in audit and "sql_sha256" in audit
    assert TOKEN not in json.dumps(usage._read(0), ensure_ascii=False)
    assert any(e["e"] == "real_sql" for e in usage._read(0))
    # 삭제하면 설정과 토큰 파일이 사라진다
    c.delete("/api/real/config", headers=L)
    assert not (real._dir() / "token.bin").exists() and c.get("/api/real/status", headers=L).json()["configured"] is False


def test_connect_request_kind_and_assistant_answers(env):
    c = env["c"]
    r = c.post("/api/feedback", headers=env["L"], json={"kind": "CONNECT_REQUEST", "title": "실제 환경 연결 신청", "text": "[연결 대상] Postgres 테스트 DB [목적] 연습 [환경 구분] 비운영"})
    assert r.status_code == 200
    g = c.get(f"/api/feedback/{r.json()['id']}", headers=env["A"]).json(); assert g["kind_label"] == "실제 환경 연결 신청"
    a = c.post("/api/guide/chat", headers=env["L"], json={"message": "테스트 DB를 연결하고 싶어요", "session_id": None, "view": "env"}).json()
    assert a["intent"] == "howto" and "방법 A" in a["answer"] and any(s.get("view") == "real" for s in a["shortcuts"])
    a = c.post("/api/guide/chat", headers=env["L"], json={"message": "실제 환경 연결 화면은 뭐야?", "session_id": None, "view": "env"}).json()
    assert "실제 환경 연결" in a["answer"]
