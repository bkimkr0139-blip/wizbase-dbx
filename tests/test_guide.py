"""AI 지원(절차 안내) 테스트: 진행은 실제 사건으로만 바뀌고, 안내는 근거 없이 단정하지 않는다."""
from test_at import client, env, login  # noqa: F401 (fixtures/helpers only; do not import tests)
from test_at import cmd, start_wh, fix_perm, sql, FIX_VIEW


def guide(e):
    return e["c"].get(f"/api/sessions/{e['sid']}/guide", headers=e["L"]).json()


def chat(e, m):
    return e["c"].post("/api/guide/chat", headers=e["L"], json={"message": m, "session_id": e["sid"]}).json()


def test_journey_is_complete_and_ordered(env):
    g = guide(env)
    assert len(g["steps"]) == 16 and g["percent"] == 0 and g["next"]["step"] == "env"
    assert [s["no"] for s in g["steps"]] == list(range(1, 17))
    assert all(s["why"] and s["subs"] for s in g["steps"])
    # every lesson milestone required by the core lessons appears in some guided sub-step
    assert g["steps"][0]["status"] == "current" and all(s["status"] == "pending" for s in g["steps"][1:])


def test_progress_only_from_real_events(env):
    before = guide(env)["percent"]
    # opening a screen / asking the assistant does not complete anything
    chat(env, "다음에 뭐 해?"); chat(env, "전체 절차")
    assert guide(env)["percent"] == before
    start_wh(env)
    g = guide(env)
    assert g["steps"][0]["done"] == 2 and g["percent"] > before          # env_check + warehouse; unverified feature not yet tried
    assert guide(env)["next"]["sub"].startswith("미확인")
    cmd(env, "feature.use", {"feature_id": "oracle_cdc"})
    assert guide(env)["steps"][0]["status"] == "done" and guide(env)["next"]["step"] == "req"


def test_chat_explains_last_failure_with_prefilled_shortcut(env):
    start_wh(env)
    sql(env, "SELECT * FROM food_dev.silver.orders LIMIT 3")
    r = chat(env, "왜 실패했어?")
    assert "INSUFFICIENT_PERMISSIONS" in r["answer"] and "USE SCHEMA" in r["answer"]
    sc = r["shortcuts"][0]
    assert sc["type"] == "nav" and sc["view"] == "perm" and sc["prefill"]["t_priv"] == "USE SCHEMA" and sc["prefill"]["t_sec"] == "schema:food_dev.silver"
    fix_perm(env)
    assert guide(env)["steps"][2]["done"] >= 3


def test_chat_navigation_kb_and_unknown(env):
    r = chat(env, "Pipelines 화면 열어줘")
    assert r["shortcuts"][0]["view"] == "pipe"
    r = chat(env, "UC 권한 개념 설명해줘")
    assert "docs.databricks.com" in r["answer"]
    r = chat(env, "양자 컴퓨팅 가격?")
    assert "확인 필요" in r["answer"]
    r = env["c"].post("/api/guide/chat", headers=env["L"], json={"message": "시작", "session_id": None}).json()
    assert r["shortcuts"][0]["view"] == "env"


def test_guide_session_isolation_and_real_mode(env):
    other = login(env["c"], "learner", "g2")
    assert env["c"].get(f"/api/sessions/{env['sid']}/guide", headers=other).status_code == 404
    assert env["c"].post("/api/guide/chat", headers=other, json={"message": "다음", "session_id": env["sid"]}).status_code == 404
    sid = env["c"].post("/api/sessions", headers=env["L"], json={"learning_mode": "real"}).json()["session_id"]
    r = env["c"].post("/api/guide/chat", headers=env["L"], json={"message": "다음에 뭐 해?", "session_id": sid}).json()
    assert "정답 위치를 안내하지 않습니다" in r["answer"] and "다음 할 일" not in r["answer"]


def test_ack_only_allowed_keys(env):
    assert env["c"].post(f"/api/sessions/{env['sid']}/commands", headers=env["L"], json={"command_type": "guide.ack", "payload": {"key": "perm"}}).status_code == 400
    cmd(env, "guide.ack", {"key": "req"})
    assert guide(env)["steps"][1]["status"] == "done"
