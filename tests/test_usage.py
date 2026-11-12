"""접속·사용 기록: 수집 지점, admin 전용 열람, 민감 정보 비저장, 집계 형태, 보관 기간 삭제."""
import json
import time

from test_at import client, env, login  # noqa: F401
from backend import usage


def _events(kind=None):
    ev = usage._read(0)
    return [e for e in ev if not kind or e["e"] == kind]


def test_events_are_recorded_for_each_action_without_secrets(env):
    c = env["c"]
    n0 = len(_events())
    # 로그인 실패(잘못된 접근 코드) — 코드 값은 저장되지 않는다
    r = c.post("/api/auth/login", json={"name": "홍길동", "role": "admin", "code": "WRONG-SECRET-CODE-123"})
    assert r.status_code == 403
    L = login(c, name="로그인테스트")
    c.post("/api/usage/view", headers=L, json={"view": "sql"})
    c.post("/api/usage/view", headers=L, json={"view": "../../etc"})                       # 잘못된 화면 값은 무시
    sid = c.post("/api/sessions", headers=L, json={}).json()["session_id"]
    c.post(f"/api/sessions/{sid}/commands", headers=L, json={"command_type": "sql.execute", "payload": {"sql": "SELECT 'TOP-SECRET-SQL-BODY'"}})
    c.post("/api/guide/chat", headers=L, json={"message": "내 비밀 질문 내용 XYZ123", "session_id": sid, "view": "sql"})
    c.post("/api/feedback", headers=L, json={"kind": "OTHER", "title": "비밀제목ABC", "text": "비밀내용 본문 DEF"})
    c.get("/download/pack")
    c.post("/api/sessions/delete", headers=L, json={"ids": [sid]})
    kinds = {e["e"] for e in _events()[n0:]}
    assert {"login_fail", "login_ok", "view", "session_new", "cmd", "chat", "feedback", "download", "session_del"} <= kinds, kinds
    raw = json.dumps(_events()[n0:], ensure_ascii=False)
    for secret in ("WRONG-SECRET-CODE-123", "TOP-SECRET-SQL-BODY", "XYZ123", "비밀제목ABC", "비밀내용", "Bearer"):
        assert secret not in raw, f"기록에 민감 정보가 남음: {secret}"
    assert "../../etc" not in raw
    cmd = [e for e in _events("cmd")][-1]
    assert cmd["d"]["type"] == "sql.execute" and cmd["d"]["status"] in ("ok", "failed") and cmd["n"] == "로그인테스트"
    assert _events("chat")[-1]["d"]["intent"]                                                # 질문은 분류만 저장
    assert all(not e["ip"] or e["ip"].endswith(".x") or "::x" in e["ip"] or e["ip"] == "" or e["ip"] == "testclient"[:20] for e in _events()[n0:])


def test_usage_views_are_admin_only(env):
    c = env["c"]
    for h in (env["L"], env["R"], env["I"]):
        assert c.get("/api/usage/summary", headers=h).status_code == 403
        assert c.get("/api/usage/events", headers=h).status_code == 403
    assert c.get("/api/usage/summary").status_code == 401
    assert c.get("/api/usage/summary", headers=env["A"]).status_code == 200


def test_summary_shape_and_aggregation(env):
    c = env["c"]
    L = login(c, name="집계테스트")
    sid = c.post("/api/sessions", headers=L, json={}).json()["session_id"]
    for i in range(3):
        c.post(f"/api/sessions/{sid}/commands", headers=L, json={"command_type": "env.check", "payload": {}})
    c.post(f"/api/sessions/{sid}/commands", headers=L, json={"command_type": "sql.execute", "payload": {"sql": "SELECT * FROM nope.x.y"}})
    d = c.get("/api/usage/summary?days=7", headers=env["A"]).json()
    assert d["days"] == 7 and len(d["daily"]) == 7 and len(d["hourly"]) == 24 and len(d["heat"]) == 7 and all(len(r) == 24 for r in d["heat"])
    k = d["kpi"]
    assert k["logins"] >= 1 and k["users"] >= 1 and k["cmds"] >= 4 and k["sessions"] >= 1 and k["cmd_fail"] >= 1
    assert any(r[0] == "env.check" and r[1] >= 3 for r in d["cmds"])
    assert "learner" in d["roles"] and d["clients"] and d["top_users"] and d["top_users"][0]["events"] >= 1
    ev = c.get("/api/usage/events?limit=5&kind=cmd", headers=env["A"]).json()
    assert ev["total"] >= 4 and len(ev["items"]) == 5 and all(i["kind"] == "cmd" for i in ev["items"])
    q = c.get("/api/usage/events?q=집계테스트&limit=50", headers=env["A"]).json()
    assert q["total"] >= 4 and all("집계테스트" in i["name"] for i in q["items"])


def test_ip_masking_and_purge(tmp_path, monkeypatch):
    assert usage.mask_ip("203.0.113.77") == "203.0.113.x" and usage.mask_ip("2001:db8:1:2:3:4:5:6").endswith("::x")
    monkeypatch.setattr(usage, "_path", lambda: tmp_path / "u.jsonl")
    old = time.time() - 200 * 86400
    (tmp_path / "u.jsonl").write_text(json.dumps({"t": old, "e": "login_ok", "u": "x", "n": "old", "r": "learner", "d": {}, "ip": "", "c": ""}) + "\n" + json.dumps({"t": time.time(), "e": "login_ok", "u": "y", "n": "new", "r": "learner", "d": {}, "ip": "", "c": ""}) + "\n", encoding="utf-8")
    assert usage.purge(180) == 1
    assert [e["n"] for e in usage._read(0)] == ["new"]
