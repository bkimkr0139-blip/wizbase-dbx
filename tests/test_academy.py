"""Academy 역할별 경로 대응표 + 자동 실습 확인."""
from test_at import client, env, sql, start_wh, fix_perm  # noqa: F401
from backend import academy


def test_catalog_shape():
    ids = [p["id"] for p in academy.PATHS]
    assert ids == ["data-engineers", "data-analysts", "ml-practitioners", "generative-ai-engineers"]
    for p in academy.PATHS:
        assert p["topics"]
        for c in p["courses"]:
            assert c["status"] in ("available", "coming_soon")
            for kind, title, view, cov, chk, note in c["lessons"]:
                assert cov in ("full", "partial", "none", "lecture") and kind in ("Demo", "Lab", "Lecture")
                assert (view is None) == (cov in ("none", "lecture")) or cov == "partial" or view is not None
    de1 = academy.PATHS[0]["courses"][0]
    assert len(de1["lessons"]) == 18                      # 개요 1 + 18 = 코스 화면의 0/19


def test_views_exist_and_auto_check(env):
    from test_ui_integrity import views
    v = views()
    for p in academy.PATHS:
        for c in p["courses"]:
            for _, _, view, _, _, _ in c["lessons"]:
                assert view is None or view in v, view
    start_wh(env); fix_perm(env)
    c, sid, L = env["c"], env["sid"], env["L"]
    r0 = c.get(f"/api/sessions/{sid}/academy", headers=L).json()
    de1 = r0["paths"][0]["courses"][0]
    assert de1["practice_done"] == 0 and de1["practice_total"] >= 8
    sql(env, "SELECT * FROM food_dev.silver.orders LIMIT 2")
    sql(env, "CREATE TABLE food_dev.gold.ac_t AS SELECT 1 AS x")
    sql(env, "INSERT INTO food_dev.gold.ac_t VALUES (2)")
    sql(env, "SELECT * FROM food_dev.gold.ac_t VERSION AS OF 0")
    r1 = c.get(f"/api/sessions/{sid}/academy", headers=L).json()
    done = {l["check"] for l in r1["paths"][0]["courses"][0]["lessons"] if l["done"]}
    assert {"select", "ctas", "dml", "timetravel"} <= done and "copy_into" not in done
    assert r1["gaps"] and r1["limits"]
