"""P1: 쿼리 이력(필터) · Delta 버전 이력/타임 트래블/RESTORE · 테이블 상세 탭 데이터."""
from test_at import client, env, sql, start_wh, fix_perm  # noqa: F401

T = "food_dev.silver.orders"


def _prep(env):
    start_wh(env)
    fix_perm(env)
    return env


def _res(r):
    return r["result"]


def test_query_history_records_and_filters(env):
    _prep(env)
    assert sql(env, f"SELECT * FROM {T} LIMIT 2")["status"] == "ok"
    assert sql(env, "SELECT * FROM food_dev.silver.no_such LIMIT 1")["status"] != "ok"
    c, sid, L = env["c"], env["sid"], env["L"]
    h = c.get(f"/api/sessions/{sid}/query-history", headers=L).json()
    assert h["total"] >= 2 and {"FINISHED", "FAILED"} <= {x["status"] for x in h["items"]}
    assert h["items"][0]["sql"].startswith("SELECT") and h["items"][0]["duration_ms"] >= 0
    f = c.get(f"/api/sessions/{sid}/query-history?status=FAILED", headers=L).json()
    assert f["total"] >= 1 and all(x["status"] == "FAILED" and x["error"]["code"] for x in f["items"])
    q = c.get(f"/api/sessions/{sid}/query-history?q=no_such", headers=L).json()
    assert q["total"] >= 1 and "statements" in q["facets"]
    assert c.get(f"/api/sessions/{sid}/query-history?min_ms=99999999", headers=L).json()["total"] == 0


def test_delta_history_time_travel_restore(env):
    _prep(env)
    c, sid, L = env["c"], env["sid"], env["L"]
    assert sql(env, "CREATE TABLE food_dev.gold.tt_demo AS SELECT 1 AS x UNION ALL SELECT 2")["status"] == "ok"
    assert sql(env, "INSERT INTO food_dev.gold.tt_demo VALUES (3)")["status"] == "ok"
    assert sql(env, "DELETE FROM food_dev.gold.tt_demo WHERE x < 3")["status"] == "ok"
    d = sql(env, "DESCRIBE HISTORY food_dev.gold.tt_demo")
    assert d["status"] == "ok", d
    ops = [r[3] for r in _res(d)["rows"]]
    assert ops[0] == "DELETE" and ops[-1].startswith("CREATE") and len(ops) == 3
    old = sql(env, "SELECT count(*) AS n FROM food_dev.gold.tt_demo VERSION AS OF 0")
    assert old["status"] == "ok" and _res(old)["rows"][0][0] == 2
    now = sql(env, "SELECT count(*) AS n FROM food_dev.gold.tt_demo")
    assert _res(now)["rows"][0][0] == 1
    rs = sql(env, "RESTORE TABLE food_dev.gold.tt_demo TO VERSION AS OF 0")
    assert rs["status"] == "ok", rs
    assert _res(sql(env, "SELECT count(*) AS n FROM food_dev.gold.tt_demo"))["rows"][0][0] == 2
    assert _res(sql(env, "DESCRIBE HISTORY food_dev.gold.tt_demo LIMIT 1"))["rows"][0][3] == "RESTORE"
    bad = sql(env, "SELECT * FROM food_dev.gold.tt_demo VERSION AS OF 99")
    assert bad["status"] != "ok"
    t = c.get(f"/api/sessions/{sid}/catalog/table?name=food_dev.gold.tt_demo", headers=L).json()
    assert t["kind"] == "TABLE" and len(t["history"]) == 4 and t["history"][0]["operation"] == "RESTORE"
    assert {"columns", "grants", "quality", "insights", "details", "lineage", "preview_columns"} <= set(t)
    assert t["insights"]["query_count"] >= 3


def test_view_has_no_delta_history(env):
    _prep(env)
    r = sql(env, "DESCRIBE HISTORY food_dev.gold.v_order_overview")
    assert r["status"] != "ok" or "뷰" in str(r)
