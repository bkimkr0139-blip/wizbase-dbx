"""담당 C: Dashboards · Genie Code(규칙 기반) · Lakeflow Designer(시각 ETL) 시뮬레이션."""
import json
import pytest

from test_at import client, env, sql, start_wh, fix_perm  # noqa: F401
from backend import ext_dash
from backend.core import ApiError

FREE = "databricks-free-edition-observed-20261112"
G = "food_dev.gold"


def api(e, method, path, body=None, who="L"):
    c, sid = e["c"], e["sid"]
    url = f"/api/sessions/{sid}{path}"
    r = c.get(url, headers=e[who]) if method == "GET" else c.post(url, headers=e[who], json=body or {})
    return r


def mk_sample(e):
    r = api(e, "POST", "/dash/create", {"sample": True})
    assert r.status_code == 200, r.text
    return r.json()


# ---------------------------------------------------------------- Dashboards
def test_dashboard_sample_run_and_aggregate(env):
    start_wh(env)
    d = mk_sample(env)
    assert len(d["datasets"]) == 2 and len(d["pages"]) == 2
    r = api(env, "POST", f"/dash/{d['id']}/run", {"dataset": "d1"}).json()
    assert r["status"] == "ok" and r["row_count"] == 300 and len(r["preview"]) == 20
    api(env, "POST", f"/dash/{d['id']}/run", {"dataset": "d2"})
    data = api(env, "POST", f"/dash/{d['id']}/data", {"filters": {}}).json()
    w = {x["id"]: x for x in data["widgets"]}
    assert w["w1"]["value"] == 300                                       # 주문 건수
    status = dict(zip(w["w3"]["labels"], w["w3"]["values"]))
    assert status == {"CONFIRMED": 153, "SHIPPED": 84, "CANCELLED": 63}
    assert w["w3"]["labels"][0] == "CONFIRMED"                           # 값 내림차순
    assert w["w5"]["type"] == "table" and w["w5"]["total_rows"] == 300 and len(w["w5"]["rows"]) == 50
    assert w["w6"]["status"] == "OK" and len(w["w6"]["labels"]) <= 20
    # 필터: 같은 열이 있는 데이터셋에만 적용
    f = api(env, "POST", f"/dash/{d['id']}/data", {"filters": {"status": "CANCELLED"}}).json()
    fw = {x["id"]: x for x in f["widgets"]}
    assert fw["w1"]["value"] == 63 and fw["w3"]["labels"] == ["CANCELLED"]
    assert fw["w6"]["labels"] == w["w6"]["labels"]                       # inventory 에는 status 열이 없어 영향 없음
    opts = f["filters"][0]
    assert opts["column"] == "status" and set(opts["options"]) == {"CANCELLED", "CONFIRMED", "SHIPPED"} and opts["applies_to"] == ["orders"]


def test_dashboard_publish_snapshot_is_frozen(env):
    start_wh(env)
    d = mk_sample(env)
    p = api(env, "POST", f"/dash/{d['id']}/publish")
    assert p.status_code == 200 and p.json()["status"] == "published"
    # 초안 수정(위젯 제목 변경)은 게시본에 영향이 없다
    full = api(env, "GET", f"/dash/{d['id']}").json()
    full["widgets"][0]["title"] = "바뀐 제목"
    s = api(env, "POST", f"/dash/{d['id']}/save", full).json()
    assert s["summary"]["draft_ahead"] is True
    pub = api(env, "POST", f"/dash/{d['id']}/data", {"source": "published"}).json()
    assert pub["source"] == "published" and pub["published_at"] and pub["widgets"][0]["title"] == "주문 건수"
    draft = api(env, "POST", f"/dash/{d['id']}/data", {"source": "draft"}).json()
    assert draft["widgets"][0]["title"] == "바뀐 제목"
    assert api(env, "POST", f"/dash/{d['id']}/unpublish").json()["status"] == "draft"
    assert api(env, "POST", f"/dash/{d['id']}/data", {"source": "published"}).status_code == 409


def test_dashboard_errors_permission_and_warehouse(env):
    d = api(env, "POST", "/dash/create", {"name": "오류"}).json()
    ds = {"id": "d1", "name": "x", "sql": "SELECT * FROM food_dev.silver.orders LIMIT 3"}
    api(env, "POST", f"/dash/{d['id']}/save", {"name": "오류", "pages": d["pages"], "datasets": [ds], "widgets": [], "filters": []})
    r = api(env, "POST", f"/dash/{d['id']}/run", {"dataset": "d1"}).json()
    assert r["status"] == "failed" and r["error"]["code"] == "WAREHOUSE_NOT_RUNNING"        # 웨어하우스 꺼짐 → 그대로 안내
    start_wh(env)
    r = api(env, "POST", f"/dash/{d['id']}/run", {"dataset": "d1"}).json()
    assert r["status"] == "failed" and r["error"]["code"] == "INSUFFICIENT_PERMISSIONS"     # silver USE SCHEMA 없음
    pr = api(env, "POST", f"/dash/{d['id']}/publish")
    assert pr.status_code == 409 and pr.json()["error"]["code"] == "PUBLISH_BLOCKED"      # 실패한 데이터셋이 있으면 게시 안 함
    data = api(env, "POST", f"/dash/{d['id']}/data", {}).json()
    assert data["datasets"][0]["status"] == "failed"
    fix_perm(env)
    assert api(env, "POST", f"/dash/{d['id']}/run", {"dataset": "d1"}).json()["status"] == "ok"


def test_dashboard_dataset_must_be_a_query_and_validation(env):
    d = api(env, "POST", "/dash/create", {"name": "검증"}).json()
    base = {"name": "검증", "pages": d["pages"], "widgets": [], "filters": []}
    for bad in ("DROP TABLE food_dev.gold.v_order_overview", "INSERT INTO food_dev.gold.x VALUES (1)", "SELECT 1; SELECT 2"):
        r = api(env, "POST", f"/dash/{d['id']}/save", {**base, "datasets": [{"id": "d1", "name": "x", "sql": bad}]})
        assert r.status_code == 400 and r.json()["error"]["code"] == "DATASET_NOT_QUERY", bad
    ok = {"id": "d1", "name": "x", "sql": "SELECT 1 AS a"}
    assert api(env, "POST", f"/dash/{d['id']}/save", {**base, "datasets": [ok], "widgets": [{"type": "pie", "dataset": "d1"}]}).status_code == 400
    assert api(env, "POST", f"/dash/{d['id']}/save", {**base, "datasets": [ok], "widgets": [{"type": "bar", "dataset": "nope"}]}).status_code == 400
    assert api(env, "GET", "/dash/db_none").status_code == 404


def test_dashboard_changed_sql_drops_cached_result_and_bad_field(env):
    start_wh(env)
    d = mk_sample(env)
    api(env, "POST", f"/dash/{d['id']}/run", {"dataset": "d1"})
    full = api(env, "GET", f"/dash/{d['id']}").json()
    assert "d1" in full["results"]
    full["datasets"][0]["sql"] = f"SELECT order_id, status FROM {G}.v_order_overview"
    s = api(env, "POST", f"/dash/{d['id']}/save", full).json()
    assert "d1" not in s["results"]                                      # SQL 이 바뀌면 이전 결과는 버림
    api(env, "POST", f"/dash/{d['id']}/run", {"dataset": "d1"})
    data = api(env, "POST", f"/dash/{d['id']}/data", {}).json()
    w = {x["id"]: x for x in data["widgets"]}
    assert w["w2"]["status"] == "BAD_FIELD" and "total_boxes" in w["w2"]["message"]    # 열이 사라진 위젯은 명시적으로 알림
    assert w["w6"]["status"] == "NO_DATA"                                  # 실행 안 한 데이터셋


def test_compute_aggregations_and_line_sorting():
    res = {"d1": {"status": "ok", "columns": ["day", "k", "v"], "rows": [["2026-11-03", "a", 3], ["2026-11-01", "a", 1], ["2026-11-02", "b", "2.5"], ["2026-11-02", "a", None]]}}
    defn = {"datasets": [{"id": "d1", "name": "t"}], "filters": [], "widgets": [
        {"id": "w1", "type": "line", "dataset": "d1", "x": "day", "y": "v", "agg": "sum", "title": "l", "page": "p1"},
        {"id": "w2", "type": "counter", "dataset": "d1", "x": "", "y": "v", "agg": "avg", "title": "a", "page": "p1"},
        {"id": "w3", "type": "counter", "dataset": "d1", "x": "", "y": "v", "agg": "count", "title": "c", "page": "p1"},
        {"id": "w4", "type": "counter", "dataset": "d1", "x": "", "y": "", "agg": "count", "title": "n", "page": "p1"},
        {"id": "w5", "type": "bar", "dataset": "d1", "x": "k", "y": "v", "agg": "max", "title": "b", "page": "p1"},
        {"id": "w6", "type": "bar", "dataset": "d1", "x": "k", "y": "", "agg": "sum", "title": "bad", "page": "p1"}]}
    w = {x["id"]: x for x in ext_dash.compute(defn, res, {})["widgets"]}
    assert w["w1"]["labels"] == ["2026-11-01", "2026-11-02", "2026-11-03"] and w["w1"]["values"] == [1, 2.5, 3]
    assert w["w2"]["value"] == pytest.approx(2.1667, abs=1e-3)           # None 은 평균에서 제외
    assert w["w3"]["value"] == 3 and w["w4"]["value"] == 4               # count(v)=non-null, count(*)=전체 행
    assert dict(zip(w["w5"]["labels"], w["w5"]["values"])) == {"a": 3, "b": 2.5}
    assert w["w6"]["status"] == "BAD_FIELD"


def test_free_edition_dataset_autostarts(env):
    r = env["c"].post("/api/sessions", headers=env["L"], json={"profile_id": FREE})
    env["sid"] = r.json()["session_id"]
    d = mk_sample(env)
    assert api(env, "POST", f"/dash/{d['id']}/run", {"dataset": "d1"}).json()["status"] == "ok"      # 시작 명령 없이 실행
    q = api(env, "GET", "/query-history?via=dashboard").json()
    assert q["total"] >= 1


# ---------------------------------------------------------------- Genie Code
def test_genie_code_template_table_and_unsupported(env):
    r = api(env, "POST", "/genie-code", {"text": "상태별 주문 건수"}).json()
    assert r["status"] == "OK" and "GROUP BY status" in r["sql"] and r["engine"] == "rule-based" and r["limits"]
    r = api(env, "POST", "/genie-code", {"text": "가용재고 상위 5개"}).json()
    assert r["status"] == "OK" and "LIMIT 5" in r["sql"]
    r = api(env, "POST", "/genie-code", {"text": "customers 테이블 region별 보여줘"}).json()
    assert r["status"] == "OK" and "GROUP BY" not in r["sql"] and r["warnings"]                 # SELECT 권한이 없으면 열 목록을 알려주지 않으므로 열 기반 추정(GROUP BY)을 하지 않는다
    r = api(env, "POST", "/genie-code", {"text": "orders 테이블 몇 건이야?"}).json()
    assert r["status"] == "OK" and "COUNT(*)" in r["sql"] and "food_dev.silver.orders" in r["sql"]
    r = api(env, "POST", "/genie-code", {"text": "다음 분기 매출을 예측해줘"}).json()
    assert r["status"] == "UNSUPPORTED" and r["examples"] and "sql" not in r                # 못 만들면 정직하게
    assert api(env, "POST", "/genie-code", {"text": ""}).json()["status"] == "EMPTY"


def test_genie_code_does_not_execute(env):
    before = api(env, "GET", "/query-history").json()["total"]
    api(env, "POST", "/genie-code", {"text": "상태별 주문 건수"})
    assert api(env, "GET", "/query-history").json()["total"] == before


def test_genie_code_debug(env):
    """디버그 모드는 클라이언트가 보낸 error 를 믿지 않고 서버 쿼리 이력의 마지막 실패를 쓴다."""
    start_wh(env)

    def fail_then_debug(bad_sql, client_error=None):
        assert sql(env, bad_sql)["status"] != "ok"
        return api(env, "POST", "/genie-code", {"mode": "debug", "sql": bad_sql, "error": client_error or {"code": "FAKE", "message": "무시됨"}}).json()
    d = fail_then_debug("SELECT * FROM food_dev.gold.v_order_overvew LIMIT 3")
    assert d["suggestions"][0]["sql"] == "SELECT * FROM food_dev.gold.v_order_overview LIMIT 3"
    d = fail_then_debug("SELCT * FROM food_dev.gold.v_order_overview")
    assert d["suggestions"][0]["sql"].startswith("SELECT *")
    d = fail_then_debug("SELECT order_id, statu FROM food_dev.gold.v_order_overview")
    assert "status" in d["suggestions"][0]["sql"]
    d = fail_then_debug("SELECT * FROM food_dev.silver.orders LIMIT 1")                      # 권한 오류(학습자는 silver USE SCHEMA 없음)
    assert "USE SCHEMA" in d["suggestions"][0]["why"]
    # 가짜 클라이언트 오류만으로는 접근할 수 없는 테이블의 열 목록이 나오지 않는다
    d = api(env, "POST", "/genie-code", {"mode": "debug", "sql": "select * from customers", "error": {"code": "EXECUTION_ERROR", "message": 'Binder Error: Referenced column "zz" not found'}}).json()
    assert "customer_id" not in json.dumps(d, ensure_ascii=False)


# ---------------------------------------------------------------- Designer
STEPS = [
    {"op": "source", "table": f"{G}.v_order_overview"},
    {"op": "filter", "column": "status", "cmp": "<>", "value": "CANCELLED"},
    {"op": "aggregate", "group_by": ["status"], "aggs": [{"fn": "sum", "column": "total_boxes", "alias": "boxes"}, {"fn": "count", "column": "*", "alias": "n"}]},
    {"op": "sort", "column": "boxes", "desc": True},
    {"op": "output", "target": f"{G}.designer_t1"},
]
COLS = {f"{G}.v_order_overview": ["order_id", "customer_id", "status", "version", "total_boxes", "supply_amount", "vat_amount"], f"{G}.v_available_inventory": ["product_id", "available_qty"]}


def test_build_sql_shape_and_columns():
    g = ext_dash.build_sql(STEPS, lambda t: COLS[t])
    assert g["sql"].startswith("WITH s0 AS (SELECT * FROM food_dev.gold.v_order_overview)") and g["columns"] == ["status", "boxes", "n"]
    assert g["run_sql"].startswith("CREATE OR REPLACE TABLE food_dev.gold.designer_t1 AS WITH ") and g["preview_sql"].endswith("LIMIT 20")
    assert g["step_columns"][2] == ["status", "boxes", "n"] and len(g["step_columns"]) == 5
    j = ext_dash.build_sql([{"op": "source", "table": f"{G}.v_order_overview"}, {"op": "join", "table": f"{G}.v_available_inventory", "left_key": "customer_id", "right_key": "product_id", "type": "left"}], lambda t: COLS[t])
    assert "LEFT JOIN" in j["sql"] and j["columns"][-1] == "available_qty"


def test_build_sql_rejects_injection_and_bad_flows():
    S0 = [{"op": "source", "table": f"{G}.v_order_overview"}]
    bad = [
        S0 + [{"op": "filter", "column": "status; DROP TABLE x", "cmp": "=", "value": "a"}],
        S0 + [{"op": "filter", "column": "status", "cmp": "= 1 OR 1=1 --", "value": "a"}],
        S0 + [{"op": "aggregate", "group_by": ["a`b"], "aggs": []}],
        S0 + [{"op": "sort", "column": "x desc, (select 1)"}],
        S0 + [{"op": "filter", "column": "status", "cmp": "=", "value": "a\\' OR 1=1"}],
        [{"op": "source", "table": "food_dev.gold.t; DROP TABLE y"}],
        [{"op": "source", "table": "only_name"}],
        [{"op": "filter", "column": "a"}],
        S0 + [{"op": "output", "target": "x"}],
        S0 + [{"op": "output", "target": f"{G}.a"}, {"op": "limit", "n": 1}],
        S0 + [{"op": "limit", "n": "9999999"}],
        S0 + [{"op": "nope"}],
    ]
    for steps in bad:
        with pytest.raises(ApiError):
            ext_dash.build_sql(steps)
    # 값의 작은따옴표는 databricks 방언 방식(백슬래시)으로 인용 — sqlglot 이 ('') 를 문자열 이어붙이기로 읽어 값이 손상되므로
    g = ext_dash.build_sql(S0 + [{"op": "filter", "column": "status", "cmp": "=", "value": "O'Brien"}])
    assert "'O" + chr(92) + "'Brien'" in g["sql"]
    g = ext_dash.build_sql(S0 + [{"op": "filter", "column": "status", "cmp": "contains", "value": "a'b"}])
    assert "LIKE '%a" + chr(92) + "'b%'" in g["sql"]
    with pytest.raises(ApiError):
        ext_dash.build_sql(S0 + [{"op": "filter", "column": "nope", "cmp": "=", "value": 1}], lambda t: COLS[t])      # 없는 열


def test_designer_flow_validate_preview_run_history(env):
    start_wh(env)
    f = api(env, "POST", "/designer/create", {"sample": True}).json()
    fid = f["id"]
    v = api(env, "POST", f"/designer/{fid}/validate").json()
    assert v["status"] == "ok" and v["columns"] == ["customer_id", "total_boxes", "amount"] and "WITH" in v["sql"]
    p = api(env, "POST", f"/designer/{fid}/preview", {}).json()
    assert p["status"] == "ok" and len(p["rows"]) == 20 and p["rows"][0][2] >= p["rows"][1][2]            # amount 내림차순
    p2 = api(env, "POST", f"/designer/{fid}/preview", {"upto": 1}).json()                                  # 2단계(필터)까지
    assert p2["status"] == "ok" and p2["columns"][0] == "order_id"
    r = api(env, "POST", f"/designer/{fid}/run").json()
    assert r["status"] == "ok" and r["table"] == f"{G}.designer_top_customers" and r["rows"] == 20
    h = sql(env, f"DESCRIBE HISTORY {G}.designer_top_customers")["result"]["rows"]
    assert h[0][3] == "CREATE TABLE AS SELECT" or "CREATE" in h[0][3]
    r2 = api(env, "POST", f"/designer/{fid}/run").json()                                                    # 다시 실행 → 새 버전
    assert r2["status"] == "ok"
    assert len(sql(env, f"DESCRIBE HISTORY {G}.designer_top_customers")["result"]["rows"]) == len(h) + 1
    q = api(env, "GET", "/query-history?via=designer").json()
    assert q["total"] >= 3 and all(x["via"] == "designer" for x in q["items"])
    assert api(env, "GET", f"/designer/{fid}").json()["last_run"]["rows"] == 20


def test_designer_errors(env):
    start_wh(env)
    f = api(env, "POST", "/designer/create", {"name": "e"}).json()
    fid = f["id"]
    api(env, "POST", f"/designer/{fid}/save", {"name": "e", "steps": [{"op": "source", "table": "food_dev.silver.orders"}, {"op": "output", "target": f"{G}.designer_x"}]})
    v = api(env, "POST", f"/designer/{fid}/validate").json()
    assert v["status"] == "failed" and v["error"]["code"] == "INSUFFICIENT_PERMISSIONS"                    # silver 권한 없음
    api(env, "POST", f"/designer/{fid}/save", {"name": "e", "steps": [{"op": "source", "table": f"{G}.v_order_overview"}, {"op": "filter", "column": "nope", "cmp": "=", "value": 1}]})
    v = api(env, "POST", f"/designer/{fid}/validate").json()
    assert v["status"] == "failed" and v["error"]["code"] == "COLUMN_NOT_FOUND" and v["error"]["step"] == 1
    api(env, "POST", f"/designer/{fid}/save", {"name": "e", "steps": [{"op": "source", "table": f"{G}.v_order_overview"}]})
    assert api(env, "POST", f"/designer/{fid}/run").json()["error"]["code"] == "NO_OUTPUT"
    assert api(env, "POST", f"/designer/{fid}/save", {"name": "e", "steps": [{"op": "zzz"}]}).status_code == 400
    c = api(env, "GET", f"/designer/columns?table={G}.v_available_inventory").json()
    assert c["status"] == "ok" and c["columns"] == ["product_id", "available_qty"]
    assert api(env, "GET", "/designer/columns?table=bad").json()["status"] == "failed"
    sch = api(env, "POST", f"/designer/{fid}/save", {"name": "s", "steps": STEPS[:1], "schedule": {"enabled": True, "cron": "0 6 * * *"}}).json()
    assert sch["schedule"]["enabled"] is True and "실행되지 않음" in sch["schedule"]["note"]
