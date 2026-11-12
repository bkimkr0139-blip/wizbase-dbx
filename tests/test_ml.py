"""ML·MLflow 시뮬레이션: 학습 지표, 분할, 런 기록·비교, 레지스트리·별칭, 특성 테이블, 서빙."""
import pytest

from test_at import client, env, sql, start_wh, fix_perm  # noqa: F401
from backend import ext_ml

# y = 2*x1 + 3*x2 + 1 (정확히 선형)
LIN = "x1,x2,y\n" + "\n".join(f"{a},{b},{2 * a + 3 * b + 1}" for a, b in [(1, 2), (2, 1), (3, 5), (4, 3), (5, 8), (6, 2), (7, 7), (8, 1), (9, 4), (10, 6), (11, 9), (12, 3)]) + "\n"
# 분류: x>5 → 1 (완전 분리), id 포함
CLS = "id,x,label\n" + "\n".join(f"{i},{i},{1 if i > 6 else 0}" for i in range(1, 15)) + "\n"
FEAT = "id,f1,f2\n" + "\n".join(f"{i},{i * 1.5},{(i % 4) + 0.5}" for i in range(1, 15)) + "\n"
LBL = "id,y\n" + "\n".join(f"{i},{2 * (i * 1.5) + 4 * ((i % 4) + 0.5) + 3}" for i in range(1, 15)) + "\n"


def up(e, table, csv):
    r = e["c"].post(f"/api/sessions/{e['sid']}/add-data", headers=e["L"], json={"schema": "gold", "table": table, "csv": csv, "mode": "create", "filename": f"{table}.csv"})
    assert r.json()["status"] == "succeeded", r.json()


def post(e, path, body, who="L"):
    return e["c"].post(f"/api/sessions/{e['sid']}/ml/{path}", headers=e[who], json=body)


def train(e, **kw):
    r = post(e, "train", kw)
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture()
def ml(env):
    start_wh(env)
    fix_perm(env)
    up(env, "ml_lin", LIN)
    up(env, "ml_cls", CLS)
    return env


def test_linear_regression_recovers_known_coefficients(ml):
    r = train(ml, table="food_dev.gold.ml_lin", features=["x1", "x2"], label="y", algo="linear", test_ratio=0.25)
    s = r["model_summary"]
    assert s["coef"] == pytest.approx([2.0, 3.0], abs=1e-4) and s["intercept"] == pytest.approx(1.0, abs=1e-4)
    assert r["metrics"]["test_r2"] == pytest.approx(1.0, abs=1e-6) and r["metrics"]["train_rmse"] == pytest.approx(0.0, abs=1e-4)
    assert r["data"]["rows_used"] == 12 and r["data"]["train_n"] + r["data"]["test_n"] == 12 and r["evidence_level"] == "LOCAL_EXECUTED"


def test_baseline_is_worse_than_linear(ml):
    a = train(ml, table="food_dev.gold.ml_lin", features=["x1", "x2"], label="y", algo="linear", run_name="lin")
    b = train(ml, table="food_dev.gold.ml_lin", features=["x1", "x2"], label="y", algo="baseline", run_name="base")
    assert b["metrics"]["test_rmse"] > a["metrics"]["test_rmse"] + 1


def test_classification_metrics_and_logistic(ml):
    r = train(ml, table="food_dev.gold.ml_cls", features=["x"], label="label", algo="logistic", epochs=800, lr=0.5, test_ratio=0.3)
    m = r["metrics"]
    assert m["train_accuracy"] >= 0.9 and 0.0 <= m["test_f1"] <= 1.0 and set(m) >= {"test_precision", "test_recall", "test_accuracy"}
    base = train(ml, table="food_dev.gold.ml_cls", features=["x"], label="label", algo="baseline", task="classification")
    assert base["model_summary"]["task"] == "classification"
    # 지표 함수 자체 검증
    got = ext_ml._cls_metrics([1, 1, 0, 0, 1], [1, 0, 0, 1, 1])
    assert got["accuracy"] == pytest.approx(0.6) and got["precision"] == pytest.approx(2 / 3) and got["recall"] == pytest.approx(2 / 3) and got["f1"] == pytest.approx(2 / 3)
    reg = ext_ml._reg_metrics([1.0, 2.0, 3.0], [1.0, 2.0, 4.0])
    assert reg["mae"] == pytest.approx(1 / 3) and reg["rmse"] == pytest.approx((1 / 3) ** 0.5) and reg["r2"] == pytest.approx(0.5)


def test_split_is_deterministic_and_order_independent():
    keys = [f"k{i}" for i in range(40)]
    X = [[float(i)] for i in range(40)]
    y = [float(i) for i in range(40)]
    a = ext_ml._split(X, y, keys, 0.25, 7)
    assert a == ext_ml._split(X, y, keys, 0.25, 7)
    assert a != ext_ml._split(X, y, keys, 0.25, 8)
    rk = list(reversed(keys))
    b = ext_ml._split(X, y, rk, 0.25, 7)
    assert {keys[i] for i in a[1]} == {rk[i] for i in b[1]}                 # 같은 행은 순서가 바뀌어도 같은 쪽


def test_validation_and_permission_errors(ml):
    assert post(ml, "train", {"table": "food_dev.gold.ml_lin", "features": ["x1"], "label": "y", "algo": "nope"}).status_code == 400
    r = post(ml, "train", {"table": "food_dev.silver.customers", "features": ["customer_id"], "label": "customer_id"})
    assert r.status_code == 400 and r.json()["error"]["code"] in ("NON_NUMERIC", "TABLE_OR_VIEW_NOT_FOUND", "EXECUTION_ERROR")
    assert post(ml, "train", {"table": "food_dev.gold.ml_cls", "features": ["x"], "label": "id", "algo": "logistic"}).json()["error"]["code"] == "LABEL_NOT_BINARY"
    assert post(ml, "train", {"table": "food_dev.bronze.raw_orders", "features": ["version"], "label": "version"}).status_code == 400   # USE SCHEMA 없음
    assert post(ml, "train", {"table": "bad name", "features": ["x"], "label": "y"}).json()["error"]["code"] == "INVALID_NAME"


def test_runs_tracking_and_compare(ml):
    train(ml, table="food_dev.gold.ml_lin", features=["x1", "x2"], label="y", algo="linear", experiment="exp-a", run_name="r1")
    train(ml, table="food_dev.gold.ml_lin", features=["x1"], label="y", algo="linear", experiment="exp-a", run_name="r2")
    st = ml["c"].get(f"/api/sessions/{ml['sid']}/ml/state", headers=ml["L"]).json()
    assert [r["name"] for r in st["runs"]][:2] == ["r2", "r1"] and st["experiments"][0]["name"] == "exp-a"
    best = min(st["runs"], key=lambda r: r["metrics"]["test_rmse"])
    assert best["name"] == "r1" and all("test_rmse" in r["metrics"] and r["params"]["features"] for r in st["runs"])
    assert st["limits"] and st["max_rows"] == 500


def test_registry_versions_aliases_and_permissions(ml):
    r1 = train(ml, table="food_dev.gold.ml_lin", features=["x1", "x2"], label="y", algo="linear", run_name="v1")
    r2 = train(ml, table="food_dev.gold.ml_lin", features=["x1", "x2"], label="y", algo="linear", l2=5.0, run_name="v2")
    assert post(ml, "models/register", {"run_id": r1["run_id"], "name": "food_dev.gold.price_model"}).json() == {"name": "food_dev.gold.price_model", "version": 1}
    assert post(ml, "models/register", {"run_id": r2["run_id"], "name": "food_dev.gold.price_model"}).json()["version"] == 2
    assert post(ml, "models/register", {"run_id": r1["run_id"], "name": "food_dev.bronze.m"}).status_code == 403          # bronze 에 CREATE 권한 없음
    assert post(ml, "models/register", {"run_id": "r_none", "name": "food_dev.gold.zz"}).status_code == 404
    assert post(ml, "models/register", {"run_id": r1["run_id"], "name": "BadName"}).json()["error"]["code"] == "INVALID_NAME"
    assert post(ml, "models/register", {"run_id": r1["run_id"], "name": "food_dev.nosuch.m"}).status_code == 404
    assert post(ml, "models/alias", {"name": "food_dev.gold.price_model", "alias": "champion", "version": 1}).json()["aliases"] == {"champion": 1}
    assert post(ml, "models/alias", {"name": "food_dev.gold.price_model", "alias": "champion", "version": 2}).json()["aliases"] == {"champion": 2}
    assert post(ml, "models/alias", {"name": "food_dev.gold.price_model", "alias": "x", "version": 9}).status_code == 404
    g = post(ml, "models/get", {"name": "food_dev.gold.price_model", "ref": "@champion"}).json()
    assert g["version"] == 2 and g["features"] == ["x1", "x2"]
    assert post(ml, "models/get", {"name": "food_dev.gold.price_model", "ref": "@nope"}).status_code == 404
    assert post(ml, "runs/" + r1["run_id"] + "/delete", {}).status_code == 409                                              # 등록된 런은 삭제 불가
    assert post(ml, "models/alias", {"name": "food_dev.gold.price_model", "alias": "champion", "version": 1}, who="A").json()["aliases"]["champion"] == 1   # 관리자는 가능


def test_feature_table_join_training_and_lookup_serving(ml):
    up(ml, "ft_items", FEAT)
    up(ml, "lb_items", LBL)
    assert post(ml, "features", {"table": "food_dev.gold.ft_items", "pk": ["nope"]}).json()["error"]["code"] == "PK_NOT_FOUND"
    up(ml, "ft_dup", "id,v\n1,1\n1,2\n")
    assert post(ml, "features", {"table": "food_dev.gold.ft_dup", "pk": ["id"]}).json()["error"]["code"] == "PK_NOT_UNIQUE"
    ft = post(ml, "features", {"table": "food_dev.gold.ft_items", "pk": ["id"], "description": "품목 특성"}).json()
    assert ft["pk"] == ["id"] and "f1" in ft["columns"]
    # 등록 전 테이블은 조인 학습 불가
    bad = post(ml, "train", {"training_set": {"label_table": "food_dev.gold.lb_items", "label": "y", "lookups": [{"feature_table": "food_dev.gold.lb_items", "features": ["y"]}]}})
    assert bad.json()["error"]["code"] == "NOT_A_FEATURE_TABLE"
    run = train(ml, training_set={"label_table": "food_dev.gold.lb_items", "label": "y", "lookups": [{"feature_table": "food_dev.gold.ft_items", "features": ["f1", "f2"]}]}, algo="linear")
    assert run["model_summary"]["coef"] == pytest.approx([2.0, 4.0], abs=1e-3) and run["model_summary"]["lookups"][0]["pk"] == ["id"]
    assert post(ml, "models/register", {"run_id": run["run_id"], "name": "food_dev.gold.item_model"}).json()["version"] == 1
    post(ml, "models/alias", {"name": "food_dev.gold.item_model", "alias": "champion", "version": 1})
    c, sid, L = ml["c"], ml["sid"], ml["L"]
    ep = c.post(f"/api/sessions/{sid}/serving", headers=L, json={"name": "item-ep", "kind": "model", "config": {"model": "food_dev.gold.item_model", "ref": "@champion"}})
    assert ep.status_code == 200, ep.text
    q = c.post(f"/api/sessions/{sid}/serving/item-ep/query", headers=L, json={"dataframe_records": [{"id": 2}]}).json()["result"]     # 키만 → 특성 조회
    assert q["predictions"][0] == pytest.approx(2 * 3.0 + 4 * 2.5 + 3, abs=1e-2)
    miss = c.post(f"/api/sessions/{sid}/serving/item-ep/query", headers=L, json={"dataframe_records": [{"id": 999}]})
    assert miss.status_code == 404 and miss.json()["error"]["code"] == "FEATURE_ROW_NOT_FOUND"


def test_serving_alias_move_changes_answer_quota_and_delete(ml):
    r1 = train(ml, table="food_dev.gold.ml_lin", features=["x1", "x2"], label="y", algo="linear", run_name="exact")
    r2 = train(ml, table="food_dev.gold.ml_lin", features=["x1", "x2"], label="y", algo="baseline", run_name="mean")
    name = "food_dev.gold.sv_model"
    post(ml, "models/register", {"run_id": r1["run_id"], "name": name})
    post(ml, "models/register", {"run_id": r2["run_id"], "name": name})
    post(ml, "models/alias", {"name": name, "alias": "champion", "version": 1})
    c, sid, L = ml["c"], ml["sid"], ml["L"]
    S = lambda p, b=None, m="post": getattr(c, m)(f"/api/sessions/{sid}/{p}", headers=L, **({"json": b} if m == "post" else {}))
    assert S("serving", {"name": "bad-ep", "kind": "model", "config": {"model": "food_dev.gold.nothing"}}).status_code == 404       # 없는 모델은 생성 시 거부
    assert S("serving", {"name": "ep-one", "kind": "model", "config": {"model": name, "ref": "@champion"}}).status_code == 200
    one = S("serving/ep-one/query", {"dataframe_records": [{"x1": 10, "x2": 10}]}).json()["result"]
    assert one["model_version"] == 1 and one["predictions"][0] == pytest.approx(51.0, abs=1e-3)
    assert S("serving/ep-one/query", {"inputs": [[1, 1]]}).json()["result"]["predictions"][0] == pytest.approx(6.0, abs=1e-3)
    post(ml, "models/alias", {"name": name, "alias": "champion", "version": 2})                                                       # 별칭 이동 → 같은 엔드포인트가 새 버전 서빙
    two = S("serving/ep-one/query", {"dataframe_records": [{"x1": 10, "x2": 10}]}).json()["result"]
    assert two["model_version"] == 2 and two["predictions"][0] != one["predictions"][0]
    for bad in ({}, {"dataframe_records": [{"x1": 1}]}, {"dataframe_records": [{"x1": "a", "x2": 1}]}, {"inputs": [[1]]}, {"inputs": []}):
        rr = S("serving/ep-one/query", bad)
        assert rr.status_code == 400 and rr.json()["error"]["code"] == "INVALID_INPUT", bad
    assert S("serving", {"name": "ep-two", "kind": "model", "config": {"model": name, "ref": "1"}}).status_code == 200
    q = S("serving", {"name": "ep-three", "kind": "model", "config": {"model": name, "ref": "1"}})
    assert q.status_code == 429 and q.json()["error"]["code"] == "SERVING_QUOTA"
    assert S("serving/ep-one/delete", {}).status_code == 200
    assert S("serving", {"name": "ep-three", "kind": "model", "config": {"model": name, "ref": "1"}}).status_code == 200
    assert {e["name"] for e in S("serving", m="get").json()["endpoints"]} == {"ep-two", "ep-three"}


def test_no_cross_session_access(ml, client):
    from test_at import login
    other = login(client, "learner", "someone-else")
    r = client.get(f"/api/sessions/{ml['sid']}/ml/state", headers=other)
    assert r.status_code == 404
