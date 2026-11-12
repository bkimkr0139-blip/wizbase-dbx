"""통합: 사용자 catalog(CREATE CATALOG) 위에서 선언형 파이프라인·ML·AI Search·이력이 함께 동작한다(Free Edition 프로필)."""
from test_at import client, env, sql  # noqa: F401

FREE = "databricks-free-edition-observed-20261112"
C, SC = "course_a", "work"
T = f"{C}.{SC}"


def _free(env):
    r = env["c"].post("/api/sessions", headers=env["L"], json={"profile_id": FREE})
    assert r.status_code == 200, r.text
    env["sid"] = r.json()["session_id"]
    return env


def _post(env, path, body=None):
    return env["c"].post(f"/api/sessions/{env['sid']}{path}", headers=env["L"], json=body or {})


def _ok(r):
    assert r.status_code == 200, r.text
    return r.json()


def _setup(env):
    _free(env)
    for q in (f"CREATE CATALOG {C}", f"CREATE SCHEMA {T}",
              f"CREATE TABLE {T}.orders_raw AS SELECT 1 AS order_id, 'A' AS store, 100.0 AS amount UNION ALL SELECT 2, 'B', 200.0 UNION ALL SELECT 3, 'A', 300.0 UNION ALL SELECT 4, 'B', 400.0"):
        r = sql(env, q)
        assert r["status"] == "ok", (q, r)


def test_dlt_incremental_in_user_catalog(env):
    _setup(env)
    src = f"""CREATE OR REFRESH STREAMING TABLE orders_silver (CONSTRAINT pos EXPECT (amount > 0) ON VIOLATION DROP ROW) AS SELECT * FROM STREAM({T}.orders_raw);
CREATE OR REFRESH MATERIALIZED VIEW store_totals AS SELECT store, SUM(amount) AS total FROM orders_silver GROUP BY store;"""
    p = _ok(_post(env, "/dpipes", {"name": "uc_pipe", "catalog": C, "schema": SC, "source": src}))
    upd = _ok(_post(env, f"/dpipes/{p['id']}/run", {"mode": "update"}))["update"]
    assert upd["state"] == "COMPLETED", upd
    assert sql(env, f"SELECT count(*) FROM {T}.orders_silver")["result"]["rows"][0][0] == 4
    assert sql(env, f"INSERT INTO {T}.orders_raw VALUES (5, 'A', 500.0)")["status"] == "ok"
    upd2 = _ok(_post(env, f"/dpipes/{p['id']}/run", {"mode": "update"}))["update"]
    assert upd2["state"] == "COMPLETED", upd2
    assert sql(env, f"SELECT count(*) FROM {T}.orders_silver")["result"]["rows"][0][0] == 5          # 새 행만 증분
    tot = dict(sql(env, f"SELECT store, total FROM {T}.store_totals")["result"]["rows"])
    assert tot["A"] == 900.0
    ops = [r[3] for r in sql(env, f"DESCRIBE HISTORY {T}.orders_silver")["result"]["rows"]]
    assert "WRITE" in ops and any(o.startswith("CREATE") for o in ops)
    # 원본을 수정하면 append-only 위반 → 실패, full refresh 로 복구
    assert sql(env, f"UPDATE {T}.orders_raw SET amount = 1 WHERE order_id = 1")["status"] == "ok"
    bad = _ok(_post(env, f"/dpipes/{p['id']}/run", {"mode": "update"}))["update"]
    assert bad["state"] != "COMPLETED"
    fix = _ok(_post(env, f"/dpipes/{p['id']}/run", {"mode": "full_refresh"}))["update"]
    assert fix["state"] == "COMPLETED"


def test_ml_and_ai_search_on_user_catalog_tables(env):
    _setup(env)
    r = _post(env, "/ml/train", {"table": f"{T}.orders_raw", "features": ["order_id"], "label": "amount", "algo": "linear", "test_ratio": 0.25})
    assert r.status_code == 200, r.text
    assert sql(env, f"CREATE TABLE {T}.docs AS SELECT 1 AS doc_id, 'Unity Catalog 권한과 카탈로그 설명' AS content UNION ALL SELECT 2, 'Delta 테이블 버전 이력과 타임 트래블'")["status"] == "ok"
    ix = _post(env, "/genai/index", {"name": f"{T}.idx", "source": f"{T}.docs", "pk": "doc_id", "text_col": "content", "meta_cols": []})
    assert ix.status_code == 200, ix.text
    q = _ok(_post(env, "/genai/index/query", {"name": f"{T}.idx", "query": "버전 이력", "k": 1}))
    assert str(q).count("2") >= 1


def test_user_catalog_detail_history_time_travel_and_listing(env):
    _setup(env)
    assert sql(env, f"DELETE FROM {T}.orders_raw WHERE order_id > 2")["status"] == "ok"
    old = sql(env, f"SELECT count(*) FROM {T}.orders_raw VERSION AS OF 0")
    assert old["status"] == "ok" and old["result"]["rows"][0][0] == 4
    d = env["c"].get(f"/api/sessions/{env['sid']}/catalog/table?name={T}.orders_raw", headers=env["L"]).json()
    assert d["kind"] == "TABLE" and d["row_count"] == 2 and d["history"][0]["operation"] == "DELETE"
    cat = env["c"].get(f"/api/sessions/{env['sid']}/catalog", headers=env["L"]).json()
    names = [x["catalog"] for x in cat.get("catalogs", [])]
    assert C in names and "food_dev" in names
    flat = [s["schema"] for s in cat["schemas"]]
    assert not any("__" in s for s in flat)                                                     # 물리 스키마는 숨김
