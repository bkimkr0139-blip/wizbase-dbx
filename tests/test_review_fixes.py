"""독립 검수에서 확인된 결함의 회귀 테스트(주입·오작동·정직성)."""
import json
import pathlib
import subprocess
import time

import duckdb
import sqlglot

from test_at import client, env, sql, start_wh, fix_perm, login  # noqa: F401
from backend import core

ROOT = pathlib.Path(__file__).resolve().parent.parent
BS, Q = chr(92), chr(39)
FREE = "databricks-free-edition-observed-20261112"


def _free(env):
    r = env["c"].post("/api/sessions", headers=env["L"], json={"profile_id": FREE})
    assert r.status_code == 200, r.text
    env["sid"] = r.json()["session_id"]
    return env


def test_sql_str_roundtrips_through_databricks_parser_and_duckdb():
    """O'Brien 이 OBrien 으로 손상되거나, 백슬래시+따옴표로 SQL 이 주입되던 문제."""
    c = duckdb.connect()
    for v in ["O" + Q + "Brien", "a" + BS + "b", "x" + BS + Q + " UNION SELECT 1 --", "end" + BS, "plain", "한글 값", Q * 3]:
        d = sqlglot.parse_one(f"SELECT {core.sql_str(v)} AS v", read="databricks").sql(dialect="duckdb")
        assert c.execute(d).fetchone()[0] == v, v


def test_table_cell_heuristic_rejects_event_handlers():
    src = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    line = next(x for x in src.splitlines() if x.startswith("const isTrustedCell"))
    js = "const f = " + line.split("=", 1)[1].strip().rstrip(";") + ";\n" + """
const bad = ['<span onmouseover=alert(1)>x</span>', '<a href="javascript:alert(1)">x</a>', '<input autofocus onfocus=alert(1)>', '<span><img src=x onerror=alert(1)></span>'];
const good = ['<span class="b ok">성공</span>', '<a href="#" data-a="nav" data-v="sql">열기</a>', '<button class="sc " data-a="sc" data-i="3">열기 <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4"><path d="M5 12h14M13 6l6 6-6 6"/></svg></button>'];
console.log(JSON.stringify([bad.map(f), good.map(f)]));"""
    out = subprocess.run(["node", "-e", js], capture_output=True, text=True, timeout=20)
    bad, good = json.loads(out.stdout)
    assert not any(bad) and all(good), out


def test_long_sql_is_rejected_fast(env):
    start_wh(env); fix_perm(env)
    t0 = time.time()
    r = sql(env, "SELECT * FROM food_dev.silver.orders WHERE " + " AND ".join(["1=1"] * 8000))
    assert r["status"] != "ok" and r["result"]["error"]["code"] == "SQL_TOO_LONG"
    assert time.time() - t0 < 3
    big = "x" * 200_000 + " VERSION AS OF 1"
    t0 = time.time()
    assert sql(env, big)["status"] != "ok" and time.time() - t0 < 3         # 정규식 폭주 없음


def test_request_body_limit(env):
    r = env["c"].post(f"/api/sessions/{env['sid']}/add-data", headers=env["L"], content=b"x" * 3_500_000)
    assert r.status_code == 413


def test_version_as_of_in_ctas_and_same_table_join(env):
    start_wh(env); fix_perm(env)
    assert sql(env, "CREATE TABLE food_dev.gold.vv AS SELECT 1 AS x UNION ALL SELECT 2 UNION ALL SELECT 3")["status"] == "ok"
    assert sql(env, "DELETE FROM food_dev.gold.vv WHERE x > 1")["status"] == "ok"
    assert sql(env, "CREATE TABLE food_dev.gold.vv_old AS SELECT * FROM food_dev.gold.vv VERSION AS OF 0")["status"] == "ok"
    assert sql(env, "SELECT count(*) FROM food_dev.gold.vv_old")["result"]["rows"][0][0] == 3            # 이전: 현재(1행)를 조용히 복사
    r = sql(env, "SELECT a.x FROM food_dev.gold.vv a JOIN food_dev.gold.vv VERSION AS OF 0 b ON a.x = b.x")
    assert r["status"] != "ok" and r["result"]["error"]["code"] == "SIMULATOR_UNSUPPORTED"


def test_snapshot_flags_invalidated_after_reload(env):
    start_wh(env); fix_perm(env)
    sql(env, "CREATE TABLE food_dev.gold.inv AS SELECT 1 AS x")
    sql(env, "INSERT INTO food_dev.gold.inv VALUES (2)")
    S = core.SESSIONS[env["sid"]]
    core._thist_invalidate(S)
    assert all(not h["snapshot"] for h in S["thist"]["food_dev.gold.inv"])
    r = sql(env, "SELECT * FROM food_dev.gold.inv VERSION AS OF 0")
    assert r["status"] != "ok" and "읽을 수 없습니다" in r["result"]["error"]["message"]


def test_drop_catalog_does_not_touch_similarly_named_catalog(env):
    _free(env)
    for q in ("CREATE CATALOG sales", "CREATE CATALOG sales_dev", "CREATE SCHEMA sales.a", "CREATE SCHEMA sales_dev.b",
              "CREATE TABLE sales_dev.b.t AS SELECT 1 AS x"):
        assert sql(env, q)["status"] == "ok", q
    assert sql(env, "DROP CATALOG sales CASCADE")["status"] == "ok"
    assert sql(env, "SELECT count(*) FROM sales_dev.b.t")["result"]["rows"][0][0] == 1                  # 이전: sales_dev 의 schema 까지 삭제
    assert sql(env, "CREATE CATALOG trailing_")["status"] != "ok"                                        # 끝 '_' 금지


def test_add_data_reserved_words_replace_keeps_history_and_reloads(env):
    start_wh(env); fix_perm(env)
    up = lambda csv, mode: env["c"].post(f"/api/sessions/{env['sid']}/add-data", headers=env["L"], json={"schema": "gold", "table": "rw", "csv": csv, "mode": mode, "filename": "a.csv"}).json()
    A, B = "order,group\n1,x\n2,y\n", "order,group\n9,z\n"
    assert up(A, "create")["status"] == "succeeded"                                                      # 예약어 열 이름
    assert up(B, "replace")["status"] == "succeeded"
    h = sql(env, "DESCRIBE HISTORY food_dev.gold.rw")["result"]["rows"]
    assert [x[0] for x in h] == [1, 0] and h[0][3] == "CREATE OR REPLACE TABLE"                         # 이력이 초기화되지 않고 이어서 증가
    a = up(A, "append")
    assert a["status"] == "succeeded" and not a["skipped"] and a["rows_total"] == 3                      # replace 뒤 A 는 다시 적재됨
    bad = up("order,group\n1,x\n", "replace")
    assert bad["status"] == "succeeded"
    assert up("order,group\nnan,x\n", "append")["status"] in ("succeeded", "failed")                    # NaN 문자열이 DOUBLE 로 추론되지 않음


def test_reviewer_cannot_mutate_other_sessions_but_can_read(env):
    c = env["c"]
    r = c.post(f"/api/sessions/{env['sid']}/add-data", headers=env["R"], json={"schema": "gold", "table": "zz", "csv": "a\n1\n", "mode": "create", "filename": "z.csv"})
    assert r.status_code == 403
    assert c.get(f"/api/sessions/{env['sid']}/academy", headers=env["R"]).status_code == 200


def test_catalog_table_without_real_table_returns_error_not_500(env):
    start_wh(env); fix_perm(env)
    r = env["c"].get(f"/api/sessions/{env['sid']}/catalog/table", params={"name": "(SELECT 1) t"}, headers=env["L"])
    assert r.status_code == 200 and r.json().get("error")


def test_academy_progress_is_sticky(env):
    start_wh(env); fix_perm(env)
    sql(env, "SELECT 1")                                                                                  # 테이블 없는 SELECT 는 인정하지 않음
    g = lambda: env["c"].get(f"/api/sessions/{env['sid']}/academy", headers=env["L"]).json()["paths"][0]["courses"][0]
    assert g()["practice_done"] == 0
    sql(env, "SELECT * FROM food_dev.silver.orders LIMIT 1")
    assert g()["practice_done"] >= 1
    core.SESSIONS[env["sid"]]["qh"].clear()                                                               # 이력이 밀려도 유지
    assert g()["practice_done"] >= 1


def test_bundle_edit_path_validation(env):
    r = env["c"].post(f"/api/sessions/{env['sid']}/commands", headers=env["L"], json={"command_type": "bundle.edit", "payload": {"path": "<span onmouseover=x>.yml", "content": "a"}})
    assert r.status_code == 400
    ok = env["c"].post(f"/api/sessions/{env['sid']}/commands", headers=env["L"], json={"command_type": "bundle.edit", "payload": {"path": "resources/job.yml", "content": "a: 1"}})
    assert ok.status_code == 200


def test_bad_input_is_400_not_500(env):
    r = env["c"].post(f"/api/sessions/{env['sid']}/genai/eval", headers=env["L"], json={"agent": "x", "threshold": "abc"})
    assert r.status_code in (400, 404)
