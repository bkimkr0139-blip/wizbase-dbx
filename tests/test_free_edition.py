"""P2: Free Edition 프로필(서버리스 전용·쿼리 시 자동 시작), 기본 프로필은 수동 시작 유지."""
from test_at import client, env, login, sql, cmd, fix_perm  # noqa: F401

FREE = "databricks-free-edition-observed-20261112"


def _free(env):
    r = env["c"].post("/api/sessions", headers=env["L"], json={"profile_id": FREE})
    assert r.status_code == 200, r.text
    assert r.json()["profile_id"] == FREE
    env["sid"] = r.json()["session_id"]
    return env


def test_unknown_profile_rejected(env):
    assert env["c"].post("/api/sessions", headers=env["L"], json={"profile_id": "nope"}).status_code == 400


def test_free_edition_autostarts_on_query(env):
    _free(env)
    fix_perm(env)
    st = env["c"].get(f"/api/sessions/{env['sid']}/state", headers=env["L"]).json()
    assert st["warehouse"]["state"] == "STOPPED" and st["warehouse"]["can_create"] is False and st["warehouse"]["type"] == "serverless"
    r = sql(env, "SELECT * FROM food_dev.silver.orders LIMIT 1")
    assert r["status"] == "ok", r                                   # 시작 명령 없이 바로 실행
    st = env["c"].get(f"/api/sessions/{env['sid']}/state", headers=env["L"]).json()
    assert st["warehouse"]["state"] == "RUNNING"
    cmd(env, "warehouse", {"action": "stop"})
    assert sql(env, "SELECT * FROM food_dev.silver.orders LIMIT 1")["status"] == "ok"      # 중지 후에도 다시 자동 시작


def test_default_profile_still_manual(env):
    fix_perm(env)
    r = sql(env, "SELECT * FROM food_dev.silver.orders LIMIT 1")
    assert r["status"] != "ok" and r["result"]["error"]["code"] == "WAREHOUSE_NOT_RUNNING"
