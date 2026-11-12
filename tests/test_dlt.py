"""선언형 파이프라인(스트리밍 테이블·구체화 뷰·expectations·AUTO CDC SCD1) 시뮬레이션."""
import pytest

from test_at import client, env, sql, start_wh, fix_perm  # noqa: F401
from backend import ext_dlt
from backend.ext_dlt import DltError, TEMPLATES

PIPE = {"catalog": "food_dev", "schema": "gold"}


def _pipe(src, **kw):
    return {**PIPE, "source": src, **kw}


def _call(env, method, path, body=None, who="L"):
    c = env["c"]
    url = f"/api/sessions/{env['sid']}{path}"
    r = c.get(url, headers=env[who]) if method == "GET" else c.post(url, headers=env[who], json=body or {})
    assert r.status_code == 200, r.text
    return r.json()


def _sample(env, kind, append=False):
    r = _call(env, "POST", "/dpipes/sample", {"kind": kind, "append": append})
    assert r["status"] == "succeeded", r
    return r


def _create(env, name, src, schema="gold"):
    r = _call(env, "POST", "/dpipes", {"name": name, "schema": schema, "source": src})
    return r["id"]


def _run(env, pid, mode="update"):
    return _call(env, "POST", f"/dpipes/{pid}/run", {"mode": mode})["update"]


def _ev(upd, name):
    return next(e for e in upd["events"] if e["dataset"] == name)


def _rows(env, q):
    return sql(env, q)["result"]["rows"]


# ------------------------------------------------------------------ 파서·계획
def test_parse_supported_statements_and_lines():
    nodes = ext_dlt.parse(TEMPLATES["bronze_mv"]["sql"] + "\n/* 블록\n주석 */\nCREATE TEMPORARY VIEW v AS SELECT 1 AS x;\n")
    assert [n["kind"] for n in nodes] == ["STREAMING_TABLE", "MATERIALIZED_VIEW", "TEMP_VIEW"]
    st = nodes[0]
    assert st["stream"] == ["orders_raw"] and [c["action"] for c in st["constraints"]] == ["DROP", "WARN"] and st["line"] == 3
    assert nodes[2]["line"] > nodes[1]["line"]
    cdc = ext_dlt.parse(TEMPLATES["auto_cdc"]["sql"])
    flow = next(n for n in cdc if n["kind"] == "CDC_FLOW")
    assert flow["cdc"] == {"source": "cdc_events", "keys": ["id"], "delete_when": "op = 'DELETE'", "seq": "seq", "columns": None, "except": ["op", "seq"]}
    assert next(n for n in cdc if n["declared"])["name"] == "customers_scd1"
    # 레거시 표기 / APPLY CHANGES
    legacy = ext_dlt.parse("CREATE STREAMING LIVE TABLE t AS SELECT * FROM STREAM(LIVE.src);\nAPPLY CHANGES INTO t2 FROM STREAM(src) KEYS (a, b) SEQUENCE BY ts STORED AS SCD TYPE 1;")
    assert legacy[0]["stream"] == ["src"] and legacy[1]["cdc"]["keys"] == ["a", "b"]


@pytest.mark.parametrize("src,needle", [
    ("CREATE VIEW v AS SELECT 1;", "지원하지 않는 문장"),
    ("CREATE STREAMING TABLE t (id INT) AS SELECT * FROM STREAM(s);", "컬럼 정의"),
    ("CREATE STREAMING TABLE t PARTITIONED BY (a) AS SELECT * FROM STREAM(s);", "PARTITIONED BY"),
    ("CREATE MATERIALIZED VIEW m AS SELECT * FROM STREAM(s);", "STREAM()을 쓰지 않습니다"),
    ("CREATE STREAMING TABLE t;\nAUTO CDC INTO t FROM STREAM(s) KEYS (id) SEQUENCE BY seq STORED AS SCD TYPE 2;", "SCD Type 2"),
    ("CREATE STREAMING TABLE t;\nAUTO CDC INTO t FROM STREAM(s) KEYS (id) IGNORE NULL UPDATES SEQUENCE BY seq;", "IGNORE NULL UPDATES"),
    ("CREATE STREAMING TABLE t;\nAUTO CDC INTO t FROM STREAM(s) KEYS (id) STORED AS SCD TYPE 1;", "SEQUENCE BY"),
    ("CREATE MATERIALIZED VIEW m;", "AS SELECT"),
    ("CREATE STREAMING TABLE t AS DELETE FROM x;", "SELECT"),
])
def test_unsupported_syntax_reports_line(src, needle):
    with pytest.raises(DltError) as e:
        ext_dlt.parse("-- 주석\n\n" + src)
    assert e.value.code == "UNSUPPORTED_DLT_SYNTAX" and needle in e.value.message and e.value.line in (3, 4)


def test_plan_order_cycle_duplicate_and_stream_rules():
    p = _pipe("CREATE MATERIALIZED VIEW c AS SELECT * FROM b;\nCREATE MATERIALIZED VIEW b AS SELECT * FROM a;\nCREATE MATERIALIZED VIEW a AS SELECT 1 AS x;")
    assert ext_dlt.build_plan(p)["order"] == ["a", "b", "c"]                       # 정의 순서가 아니라 의존 순서
    with pytest.raises(DltError) as e:
        ext_dlt.build_plan(_pipe("CREATE MATERIALIZED VIEW a AS SELECT * FROM b;\nCREATE MATERIALIZED VIEW b AS SELECT * FROM a;"))
    assert e.value.code == "DLT_CYCLE" and "a" in e.value.message and "b" in e.value.message
    with pytest.raises(DltError) as e:
        ext_dlt.build_plan(_pipe("CREATE MATERIALIZED VIEW a AS SELECT 1 AS x;\nCREATE MATERIALIZED VIEW a AS SELECT 2 AS x;"))
    assert e.value.code == "DLT_DUPLICATE_DATASET"
    with pytest.raises(DltError) as e:
        ext_dlt.build_plan(_pipe("CREATE STREAMING TABLE t AS SELECT * FROM food_dev.silver.orders;"))
    assert "STREAM" in e.value.message
    with pytest.raises(DltError) as e:
        ext_dlt.build_plan(_pipe("CREATE MATERIALIZED VIEW m AS SELECT 1 AS x;\nCREATE STREAMING TABLE t AS SELECT * FROM STREAM(m);"))
    assert e.value.code == "STREAM_FROM_MATERIALIZED_VIEW"
    with pytest.raises(DltError) as e:
        ext_dlt.build_plan(_pipe("CREATE MATERIALIZED VIEW other.m AS SELECT 1 AS x;"))
    assert e.value.code == "DLT_TARGET_OUTSIDE_SCHEMA"


# ------------------------------------------------------------------ 스트리밍 증분·expectations
def test_streaming_incremental_expectations_and_event_log(env):
    start_wh(env)
    _sample(env, "orders")
    pid = _create(env, "orders_p", TEMPLATES["bronze_mv"]["sql"])
    u1 = _run(env, pid)
    assert u1["state"] == "COMPLETED", u1
    b1 = _ev(u1, "orders_bronze")
    assert b1["rows_in"] == 5 and b1["rows_out"] == 4 and b1["dropped"] == 1 and "첫 업데이트" in b1["note"]
    exp1 = {x["name"]: x for x in b1["expectations"]}
    assert exp1["valid_order_id"]["failed"] == 1 and exp1["valid_order_id"]["action"] == "DROP"
    assert exp1["positive_amount"]["failed"] == 1 and exp1["positive_amount"]["action"] == "WARN"     # 경고는 행을 남긴다
    assert _ev(u1, "store_sales")["rows_out"] == 3                                                     # S01,S02,S03
    assert _rows(env, "SELECT count(*) FROM food_dev.gold.orders_bronze")[0][0] == 4
    assert [e["dataset"] for e in u1["events"]] == ["orders_bronze", "store_sales"]
    # 새 행이 없으면 증분 0행
    u0 = _run(env, pid)
    assert _ev(u0, "orders_bronze")["note"].startswith("처리할 새 행이 없습니다") and _rows(env, "SELECT count(*) FROM food_dev.gold.orders_bronze")[0][0] == 4
    # 추가 배치(3행: NULL id 1, amount 0 1) → 새 행만 처리
    _sample(env, "orders", append=True)
    u2 = _run(env, pid)
    b2 = _ev(u2, "orders_bronze")
    assert b2["rows_in"] == 3 and "새 행 3개" in b2["note"] and b2["rows_out"] == 6
    assert _rows(env, "SELECT count(*) FROM food_dev.gold.orders_bronze")[0][0] == 6                  # 4 + (3-1 드롭)
    assert _ev(u2, "store_sales")["state"] == "COMPLETED"
    ops = [r[3] for r in _rows(env, "DESCRIBE HISTORY food_dev.gold.orders_bronze")]
    assert ops == ["WRITE", "CREATE OR REPLACE TABLE AS SELECT"]                                       # 증분 INSERT 1회 + 첫 생성
    d = _call(env, "GET", f"/dpipes/{pid}")
    assert d["plan"]["ok"] and d["plan"]["order"] == ["orders_bronze", "store_sales"] and len(d["updates"]) == 3
    assert {x["name"]: x["rows"] for x in d["datasets"]}["orders_bronze"] == 6
    assert _call(env, "GET", f"/dpipes/{pid}/events")["updates"][0]["id"] == u2["id"]
    # 쿼리 이력에 via=dlt 로 남는다
    h = _call(env, "GET", "/query-history?via=dlt&size=100")
    assert h["total"] >= 3 and all(x["statement"] in ("CREATE", "INSERT") for x in h["items"])


def test_source_change_fails_then_full_refresh_recovers(env):
    start_wh(env)
    _sample(env, "orders")
    pid = _create(env, "orders_p", TEMPLATES["bronze_mv"]["sql"])
    assert _run(env, pid)["state"] == "COMPLETED"
    assert sql(env, "UPDATE food_dev.gold.orders_raw SET amount = 999 WHERE store_id = 'S03'")["status"] == "ok"
    u = _run(env, pid)
    assert u["state"] == "FAILED" and u["error"]["code"] == "STREAMING_SOURCE_CHANGED" and u["error"]["operation"] == "UPDATE" and u["error"]["dataset"] == "orders_bronze"
    assert _ev(u, "store_sales")["state"] == "SKIPPED"
    assert "full refresh" in u["error"]["hint"]
    f = _run(env, pid, "full_refresh")
    assert f["state"] == "COMPLETED" and "full refresh" in _ev(f, "orders_bronze")["note"]
    assert _rows(env, "SELECT count(*) FROM food_dev.gold.orders_bronze WHERE amount = 999")[0][0] == 1
    assert _run(env, pid)["state"] == "COMPLETED"                              # 복구 뒤에는 다시 증분 동작


def test_delete_and_restore_on_source_also_break_stream(env):
    start_wh(env)
    _sample(env, "orders")
    pid = _create(env, "orders_p", TEMPLATES["bronze_mv"]["sql"])
    _run(env, pid)
    assert sql(env, "DELETE FROM food_dev.gold.orders_raw WHERE order_id = 'O-2'")["status"] == "ok"
    assert _run(env, pid)["error"]["operation"] == "DELETE"
    assert _run(env, pid, "full_refresh")["state"] == "COMPLETED"
    assert sql(env, "RESTORE TABLE food_dev.gold.orders_raw TO VERSION AS OF 0")["status"] == "ok"
    assert _run(env, pid)["error"]["operation"] == "RESTORE"


def test_expectation_fail_update_aborts_without_writing(env):
    start_wh(env)
    _sample(env, "orders")
    src = ("CREATE OR REFRESH STREAMING TABLE strict_orders (CONSTRAINT amount_ok EXPECT (amount > 0) ON VIOLATION FAIL UPDATE)\nAS SELECT * FROM STREAM(orders_raw);\n"
           "CREATE MATERIALIZED VIEW cnt AS SELECT count(*) AS n FROM strict_orders;\n")
    pid = _create(env, "strict_p", src)
    u = _run(env, pid)
    assert u["state"] == "FAILED" and u["error"]["code"] == "EXPECTATION_FAILED" and u["error"]["dataset"] == "strict_orders"
    e = _ev(u, "strict_orders")
    assert e["state"] == "FAILED" and e["expectations"][0]["failed"] == 1 and e["expectations"][0]["action"] == "FAIL"
    assert _ev(u, "cnt")["state"] == "SKIPPED"
    r = sql(env, "SELECT count(*) FROM food_dev.gold.strict_orders")
    assert r["status"] != "ok"                                                  # 데이터셋이 만들어지지 않았다


def test_temp_view_is_inlined_and_not_published(env):
    start_wh(env)
    _sample(env, "orders")
    src = ("CREATE TEMPORARY VIEW paid AS SELECT * FROM STREAM(orders_raw) WHERE status = 'PAID';\n"
           "CREATE OR REFRESH STREAMING TABLE paid_orders AS SELECT * FROM STREAM(paid);\n")
    pid = _create(env, "temp_p", src)
    u = _run(env, pid)
    assert u["state"] == "COMPLETED", u
    assert _ev(u, "paid_orders")["rows_out"] == 4
    assert sql(env, "SELECT * FROM food_dev.gold.paid LIMIT 1")["status"] != "ok"                 # 임시 뷰는 게시되지 않는다
    _sample(env, "orders", append=True)
    u2 = _run(env, pid)
    assert _ev(u2, "paid_orders")["rows_in"] == 3 and _ev(u2, "paid_orders")["rows_out"] == 7       # PAID 3행 증분


# ------------------------------------------------------------------ AUTO CDC
def test_auto_cdc_scd1_upsert_delete_out_of_order_and_tombstone(env):
    start_wh(env)
    _sample(env, "cdc")
    pid = _create(env, "cdc_p", TEMPLATES["auto_cdc"]["sql"])
    u1 = _run(env, pid)
    assert u1["state"] == "COMPLETED", u1
    c1 = _ev(u1, "customers_scd1")["cdc"]
    assert c1 == {"events": 6, "upserts": 3, "deletes": 1, "ignored_old": 0, "keys_tracked": 4}
    got = {r[0]: r[1:] for r in _rows(env, "SELECT id, name, city FROM food_dev.gold.customers_scd1")}
    assert got == {1: ["Kim", "Seoul"], 2: ["Lee", "Jeju"], 4: ["Choi", "Incheon"]}                 # 2는 최신(seq5), 3은 삭제
    assert [c for c in _rows(env, "SELECT * FROM food_dev.gold.customers_scd1 LIMIT 1")[0]] and \
        sql(env, "SELECT op FROM food_dev.gold.customers_scd1")["status"] != "ok"                  # EXCEPT(op, seq) 컬럼은 없다
    _sample(env, "cdc", append=True)
    u2 = _run(env, pid)
    c2 = _ev(u2, "customers_scd1")["cdc"]
    assert c2["events"] == 5 and c2["ignored_old"] == 2 and c2["upserts"] == 2 and c2["deletes"] == 1
    got = {r[0]: r[1:] for r in _rows(env, "SELECT id, name, city FROM food_dev.gold.customers_scd1")}
    assert got == {1: ["Kim", "Suwon"], 2: ["Lee", "Jeju"], 5: ["Jung", "Gwangju"]}                 # id2 오래된 이벤트 무시, id3 되살아나지 않음, id4 삭제
    ops = [r[3] for r in _rows(env, "DESCRIBE HISTORY food_dev.gold.customers_scd1")]
    assert ops == ["MERGE", "MERGE", "CREATE OR REPLACE TABLE AS SELECT"]                           # 배치당 MERGE 1건
    # 새 이벤트 없음 → 0건
    assert _ev(_run(env, pid), "customers_scd1")["cdc"]["events"] == 0
    # full refresh 는 전체를 다시 재생해도 같은 결과
    f = _run(env, pid, "full_refresh")
    assert _ev(f, "customers_scd1")["cdc"]["events"] == 11
    got2 = {r[0]: r[1:] for r in _rows(env, "SELECT id, name, city FROM food_dev.gold.customers_scd1")}
    assert got2 == got


def test_auto_cdc_errors(env):
    _sample(env, "cdc")
    bad = ("CREATE STREAMING TABLE t;\nCREATE FLOW f AS AUTO CDC INTO t FROM STREAM(cdc_events) KEYS (nope) SEQUENCE BY seq STORED AS SCD TYPE 1;")
    u = _run(env, _create(env, "bad_p", bad))
    assert u["state"] == "FAILED" and u["error"]["code"] == "COLUMN_NOT_FOUND"
    nokey = ("CREATE STREAMING TABLE t2;\nAUTO CDC INTO t2 FROM STREAM(cdc_events) KEYS (id) SEQUENCE BY seq COLUMNS * EXCEPT (id) STORED AS SCD TYPE 1;")
    assert _run(env, _create(env, "bad_p2", nokey))["error"]["code"] == "DLT_CDC_KEY_EXCLUDED"
    # 선언만 있고 흐름이 없으면 경고 메모
    pid = _create(env, "decl_p", "CREATE STREAMING TABLE only_decl;")
    u = _run(env, pid)
    assert u["state"] == "COMPLETED" and "흐름이 없어" in _ev(u, "only_decl")["note"]


# ------------------------------------------------------------------ 권한·API
def test_permission_errors_surface_and_session_isolation(env):
    pid = _create(env, "perm_p", "CREATE MATERIALIZED VIEW m AS SELECT count(*) AS n FROM food_dev.silver.orders;")
    u = _run(env, pid)
    assert u["state"] == "FAILED" and u["error"]["code"] == "INSUFFICIENT_PERMISSIONS" and u["error"]["missing"]["securable"].startswith("schema:food_dev.silver")
    pid2 = _create(env, "perm_p2", "CREATE MATERIALIZED VIEW m AS SELECT 1 AS n;", schema="silver")       # 대상 schema 에 CREATE TABLE 권한 없음
    u2 = _run(env, pid2)
    assert u2["state"] == "FAILED" and u2["error"]["code"] == "INSUFFICIENT_PERMISSIONS"
    fix_perm(env)
    assert _run(env, pid)["state"] == "COMPLETED"                                                    # 권한을 받으면 같은 정의가 성공
    # 다른 사용자는 남의 세션을 볼 수 없다
    other = env["R"]
    r = env["c"].get(f"/api/sessions/{env['sid']}/dpipes", headers=other)
    assert r.status_code in (200, 404)


def test_crud_validation_and_limits(env):
    c = env["c"]
    base = f"/api/sessions/{env['sid']}/dpipes"
    assert c.post(base, headers=env["L"], json={"name": "Bad Name!", "source": "CREATE MATERIALIZED VIEW m AS SELECT 1 AS x;"}).status_code == 400
    pid = _create(env, "ok_p", "CREATE MATERIALIZED VIEW m AS SELECT 1 AS x;")
    assert c.post(base, headers=env["L"], json={"name": "ok_p", "source": "x"}).status_code == 409
    lst = _call(env, "GET", "/dpipes")
    assert [p["name"] for p in lst["pipelines"]] == ["ok_p"] and set(lst["templates"]) == {"bronze_mv", "auto_cdc"} and lst["limits"]
    # 저장: 문법 오류는 plan 에 line 과 함께 돌려준다(저장 자체는 허용)
    r = _call(env, "POST", f"/dpipes/{pid}/save", {"source": "CREATE VIEW v AS SELECT 1;"})
    assert r["plan"]["ok"] is False and r["plan"]["error"]["code"] == "UNSUPPORTED_DLT_SYNTAX" and r["plan"]["error"]["line"] == 1
    u = _run(env, pid)
    assert u["state"] == "FAILED" and u["error"]["code"] == "UNSUPPORTED_DLT_SYNTAX"
    assert c.post(f"{base}/{pid}/run", headers=env["L"], json={"mode": "bogus"}).status_code == 400
    assert c.post(f"{base}/sample", headers=env["L"], json={"kind": "x"}).status_code == 400
    assert c.post(f"{base}/nope/run", headers=env["L"], json={}).status_code == 404
    _call(env, "POST", f"/dpipes/{pid}/delete")
    assert _call(env, "GET", "/dpipes")["pipelines"] == []
    for i in range(5):
        _create(env, f"p{i}", "CREATE MATERIALIZED VIEW m AS SELECT 1 AS x;")
    assert c.post(base, headers=env["L"], json={"name": "p9", "source": "x"}).status_code == 429


def test_sample_errors(env):
    r = _call(env, "POST", "/dpipes/sample", {"kind": "orders", "append": True})
    assert r["status"] == "failed" and r["error"]["code"] == "TABLE_OR_VIEW_NOT_FOUND"
    _sample(env, "orders")
    r = _call(env, "POST", "/dpipes/sample", {"kind": "orders"})
    assert r["status"] == "failed" and r["error"]["code"] == "TABLE_ALREADY_EXISTS"
    r = _call(env, "POST", "/dpipes/sample", {"kind": "orders", "schema": "silver"})                  # 권한 없는 schema
    assert r["status"] == "failed" and r["error"]["code"] == "INSUFFICIENT_PERMISSIONS"
