"""P1: Add data — CSV 업로드 → 테이블, COPY INTO 증분(멱등), 권한·검증 오류."""
from test_at import client, env, sql, start_wh, fix_perm  # noqa: F401

CSV1 = "order_date,store_id,sku,qty,unit_price\n2026-11-01,S01,A100,3,1200\n2026-11-02,S02,A200,5,800\n"
CSV2 = "order_date,store_id,sku,qty,unit_price\n2026-11-03,S01,A300,4,450\n"


def up(e, csv, mode="create", table="store_sales", schema="gold", who="L"):
    r = e["c"].post(f"/api/sessions/{e['sid']}/add-data", headers=e[who], json={"schema": schema, "table": table, "csv": csv, "mode": mode, "filename": "t.csv"})
    assert r.status_code == 200, r.text
    return r.json()


def test_create_then_copy_into_is_idempotent(env):
    start_wh(env)
    fix_perm(env)
    a = up(env, CSV1)
    assert a["status"] == "succeeded" and a["rows_total"] == 2 and {c["type"] for c in a["columns"]} >= {"DATE", "BIGINT", "VARCHAR"}
    b = up(env, CSV2, "append")
    assert b["status"] == "succeeded" and b["rows_loaded"] == 1 and b["rows_total"] == 3
    c = up(env, CSV2, "append")                       # 같은 파일 → 건너뜀
    assert c["skipped"] and c["rows_loaded"] == 0 and c["rows_total"] == 3
    ops = [r[3] for r in sql(env, "DESCRIBE HISTORY food_dev.gold.store_sales")["result"]["rows"]]
    assert ops == ["COPY INTO", "CREATE TABLE"]
    assert sql(env, "SELECT count(*) FROM food_dev.gold.store_sales")["result"]["rows"][0][0] == 3
    assert up(env, CSV1)["error"]["code"] == "TABLE_ALREADY_EXISTS"


def test_validation_errors(env):
    start_wh(env)
    fix_perm(env)
    assert up(env, "a,b\n1,2,3\n")["error"]["code"] == "MALFORMED_CSV"
    assert up(env, "a,b\n")["error"]["code"] == "EMPTY_FILE"
    assert up(env, CSV1, table="Bad Name")["error"]["code"] == "INVALID_NAME"
    assert up(env, CSV1, schema="nope")["error"]["code"] == "SCHEMA_NOT_FOUND"
    assert up(env, CSV1, "append", table="never_made")["error"]["code"] == "TABLE_OR_VIEW_NOT_FOUND"
    up(env, CSV1)
    assert up(env, "x,y\n1,2\n", "append")["error"]["code"] == "SCHEMA_MISMATCH"


def test_requires_create_table_privilege(env):
    r = up(env, CSV1, schema="silver")                  # 학습자는 silver에 CREATE TABLE/USE 권한이 없다
    assert r["status"] == "failed" and r["error"]["code"] == "INSUFFICIENT_PERMISSIONS"
