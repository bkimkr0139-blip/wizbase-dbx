"""시작 시 세션 연결을 한꺼번에 열지 않고, 처음 쓸 때 연다."""
from test_at import client, env, login, sql, start_wh  # noqa: F401
from backend import core


def test_data_dir_is_temp_not_live():
    assert "dbxtest_" in str(core.DATA)


def test_load_all_does_not_open_connections_and_sessions_still_work(env):
    start_wh(env)
    assert sql(env, "SELECT count(*) AS n FROM food_dev.gold.v_order_overview")["status"] == "ok"
    sid = env["sid"]
    for c in list(core._conns.values()):
        c.close()
    core._conns.clear()
    core.SESSIONS.clear()
    core.load_all()
    assert sid in core.SESSIONS and sid not in core._conns          # 로드만 하고 연결은 열지 않음
    assert sql(env, "SELECT count(*) AS n FROM food_dev.gold.v_order_overview")["status"] == "ok"
    assert sid in core._conns                                       # 처음 쓸 때 열림


def test_delete_unloaded_session(env):
    sid = env["sid"]
    core._conns.pop(sid).close()
    r = env["c"].post("/api/sessions/delete", headers=env["L"], json={"ids": [sid]})
    assert r.status_code == 200
    assert not list(core.DATA.glob(f"{sid}*"))
