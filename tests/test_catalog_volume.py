"""담당 A: 다중 catalog(CREATE CATALOG) · Volumes · COPY INTO(볼륨→테이블)."""
from test_at import client, env, sql, cmd, start_wh, fix_perm  # noqa: F401

FREE = "databricks-free-edition-observed-20261112"
CSV1 = "id,name,qty\n1,a,10\n2,b,20\n"
CSV2 = "id,name,qty\n3,c,30\n"


def rows(r):
    return r["result"]["rows"]


def err(r):
    return r["result"]["error"]["code"]


def free(env):
    r = env["c"].post("/api/sessions", headers=env["L"], json={"profile_id": FREE})
    assert r.status_code == 200, r.text
    env["sid"] = r.json()["session_id"]
    return env


def upload(env, vol, path, text, who="L"):
    r = env["c"].post(f"/api/sessions/{env['sid']}/volumes/files", headers=env[who], json={"volume": vol, "path": path, "text": text})
    assert r.status_code == 200, r.text
    return r.json()


# ---------------------------------------------------------------- catalog
def test_create_catalog_needs_privilege_and_ticket_flow(env):
    start_wh(env)
    r = sql(env, "CREATE CATALOG acme")
    assert r["status"] != "ok" and err(r) == "INSUFFICIENT_PERMISSIONS"
    miss = r["result"]["error"]["missing"]
    assert miss == {"privilege": "CREATE CATALOG", "securable": "metastore:main"}
    t = env["c"].post("/api/permission-requests", headers=env["L"], json={"session_id": env["sid"], "securable": "metastore:main", "privilege": "CREATE CATALOG", "reason": "코스 전용 catalog 생성 필요"}).json()
    assert env["c"].post(f"/api/sessions/{env['sid']}/tickets/{t['ticket_id']}/resolve", headers=env["A"], json={"decision": "approve"}).status_code == 200
    assert sql(env, "CREATE CATALOG acme COMMENT 'course'")["status"] == "ok"
    assert sql(env, "CREATE CATALOG acme")["status"] != "ok"
    assert err(sql(env, "CREATE CATALOG acme")) == "CATALOG_ALREADY_EXISTS"
    assert sql(env, "CREATE CATALOG IF NOT EXISTS acme")["status"] == "ok"
    sc = rows(sql(env, "SHOW CATALOGS"))
    assert [r_ for r_ in sc if r_[0] == "acme"] == [["acme", "MANAGED(내가 만든)", "trainee@wizbase.training", "course"]]


def test_name_rules(env):
    free(env)
    for bad in ("CREATE CATALOG 1bad", "CREATE CATALOG a__b", "CREATE CATALOG food_dev", "CREATE CATALOG system"):
        r = sql(env, bad)
        assert r["status"] != "ok" and err(r) in ("INVALID_NAME", "CATALOG_RESERVED"), bad
    assert rows(sql(env, "CREATE CATALOG MixedCase"))[0] == ["mixedcase", "생성됨"]          # 이름은 소문자로 저장
    assert sql(env, "CREATE CATALOG ok1")["status"] == "ok"
    assert err(sql(env, "CREATE SCHEMA ok1.bad__name")) == "INVALID_NAME"


def test_multi_catalog_ddl_dml_history_timetravel(env):
    free(env)                                                   # Free Edition: CREATE CATALOG 자동 부여, SQL 자동 시작
    assert sql(env, "CREATE CATALOG acme")["status"] == "ok"
    assert sql(env, "CREATE SCHEMA acme.silver")["status"] == "ok"
    assert sql(env, "CREATE TABLE acme.silver.t AS SELECT 1 AS x UNION ALL SELECT 2")["status"] == "ok"
    assert sql(env, "INSERT INTO acme.silver.t VALUES (3)")["status"] == "ok"
    assert sql(env, "UPDATE acme.silver.t SET x = x * 10 WHERE x = 3")["status"] == "ok"
    assert sorted(r[0] for r in rows(sql(env, "SELECT x FROM acme.silver.t"))) == [1, 2, 30]
    assert sql(env, "CREATE OR REPLACE VIEW acme.silver.v AS SELECT x FROM acme.silver.t WHERE x > 1")["status"] == "ok"
    assert sorted(r[0] for r in rows(sql(env, "SELECT * FROM acme.silver.v"))) == [2, 30]
    ops = [r[3] for r in rows(sql(env, "DESCRIBE HISTORY acme.silver.t"))]
    assert ops == ["UPDATE", "WRITE", "CREATE TABLE AS SELECT"]
    assert rows(sql(env, "SELECT count(*) FROM acme.silver.t VERSION AS OF 0"))[0][0] == 2
    assert sql(env, "RESTORE TABLE acme.silver.t TO VERSION AS OF 0")["status"] == "ok"
    assert rows(sql(env, "SELECT count(*) FROM acme.silver.t"))[0][0] == 2
    assert sql(env, "DELETE FROM acme.silver.t WHERE x = 1")["status"] == "ok"
    assert err(sql(env, "SELECT * FROM nope.silver.t")) == "TABLE_OR_VIEW_NOT_FOUND"
    assert err(sql(env, "CREATE TABLE acme.missing.t AS SELECT 1 AS x")) == "SCHEMA_NOT_FOUND"
    # 물리 스키마는 food_dev 목록에 노출되지 않고 catalog 별로 묶여 나온다
    cat = env["c"].get(f"/api/sessions/{env['sid']}/catalog", headers=env["L"]).json()
    assert cat["catalog"] == "food_dev" and all("__" not in s["schema"] for s in cat["schemas"])
    by = {c["catalog"]: c for c in cat["catalogs"]}
    assert "acme" in by and by["acme"]["kind"] == "user"
    silver = next(s for s in by["acme"]["schemas"] if s["schema"] == "silver")
    assert {t["name"] for t in silver["tables"]} == {"t", "v"} and silver["usable"]
    # 테이블 상세(Overview·History·Quality 등)도 사용자 catalog 에서 동작
    d = env["c"].get(f"/api/sessions/{env['sid']}/catalog/table?name=acme.silver.t", headers=env["L"]).json()
    assert d["kind"] == "TABLE" and d["name"] == "acme.silver.t" and len(d["history"]) >= 4 and d["row_count"] == 1
    assert env["c"].get(f"/api/sessions/{env['sid']}/catalog/table?name=acme.silver.v", headers=env["L"]).json()["kind"] == "VIEW"


def test_owner_full_rights_and_grant_isolation(env):
    free(env)
    assert sql(env, "CREATE CATALOG acme")["status"] == "ok"
    # 소유자(학습자)는 catalog 안 객체에 전권: schema 권한 부여 요청 없이 생성·조회·GRANT 가능
    assert sql(env, "CREATE SCHEMA acme.s1")["status"] == "ok"
    assert sql(env, "CREATE TABLE acme.s1.t AS SELECT 7 AS x")["status"] == "ok"
    g = sql(env, "GRANT SELECT ON TABLE acme.s1.t TO `analysts`")
    assert g["status"] == "ok", g
    assert sql(env, "GRANT USE CATALOG ON CATALOG acme TO `analysts`")["status"] == "ok"
    # 남의 catalog(food_dev) 에는 여전히 GRANT 불가
    assert err(sql(env, "GRANT SELECT ON TABLE food_dev.silver.orders TO `analysts`")) == "INSUFFICIENT_PERMISSIONS"
    # 관리자가 만든 catalog 는 학습자에게 보이지 않는 한 접근 불가
    a = env["c"].post(f"/api/sessions/{env['sid']}/commands", headers=env["A"], json={"command_type": "sql.execute", "payload": {"sql": "CREATE CATALOG admincat"}}).json()
    assert a["status"] == "ok", a
    r = sql(env, "CREATE SCHEMA admincat.x")
    assert r["status"] != "ok" and err(r) == "INSUFFICIENT_PERMISSIONS"


def test_drop_catalog_cascade_and_cleanup(env):
    free(env)
    sql(env, "CREATE CATALOG tmpc")
    sql(env, "CREATE SCHEMA tmpc.s")
    sql(env, "CREATE TABLE tmpc.s.t AS SELECT 1 AS x")
    sql(env, "CREATE VOLUME tmpc.s.v")
    assert err(sql(env, "DROP CATALOG tmpc")) == "CATALOG_NOT_EMPTY"
    assert sql(env, "DROP CATALOG tmpc CASCADE")["status"] == "ok"
    assert err(sql(env, "SELECT * FROM tmpc.s.t")) == "TABLE_OR_VIEW_NOT_FOUND"
    assert sql(env, "DROP CATALOG IF EXISTS tmpc")["status"] == "ok"
    assert err(sql(env, "DROP CATALOG tmpc")) == "CATALOG_NOT_FOUND"
    assert err(sql(env, "DROP CATALOG food_dev")) == "CATALOG_PROTECTED"
    # 같은 이름으로 다시 만들어도 이전 데이터가 남지 않는다
    sql(env, "CREATE CATALOG tmpc"); sql(env, "CREATE SCHEMA tmpc.s")
    assert err(sql(env, "SELECT * FROM tmpc.s.t")) == "TABLE_OR_VIEW_NOT_FOUND"
    assert env["c"].get(f"/api/sessions/{env['sid']}/volumes", headers=env["L"]).json()["volumes"] == []


def test_add_data_into_user_catalog(env):
    free(env)
    sql(env, "CREATE CATALOG acme"); sql(env, "CREATE SCHEMA acme.bronze")
    r = env["c"].post(f"/api/sessions/{env['sid']}/add-data", headers=env["L"], json={"catalog": "acme", "schema": "bronze", "table": "up", "csv": CSV1, "mode": "create", "filename": "a.csv"}).json()
    assert r["status"] == "succeeded" and r["table"] == "acme.bronze.up" and r["rows_total"] == 2
    assert env["c"].post(f"/api/sessions/{env['sid']}/add-data", headers=env["L"], json={"catalog": "acme", "schema": "bronze", "table": "up", "csv": CSV2, "mode": "append"}).json()["rows_total"] == 3
    assert [r_[3] for r_ in rows(sql(env, "DESCRIBE HISTORY acme.bronze.up"))] == ["COPY INTO", "CREATE TABLE"]
    bad = env["c"].post(f"/api/sessions/{env['sid']}/add-data", headers=env["L"], json={"catalog": "ghost", "schema": "x", "table": "t", "csv": CSV1, "mode": "create"}).json()
    assert bad["error"]["code"] == "TABLE_OR_VIEW_NOT_FOUND"


# ---------------------------------------------------------------- volume
def test_volume_lifecycle_and_copy_into(env):
    free(env)
    sql(env, "CREATE CATALOG acme"); sql(env, "CREATE SCHEMA acme.raw")
    assert sql(env, "CREATE VOLUME acme.raw.landing COMMENT 'csv'")["status"] == "ok"
    assert err(sql(env, "CREATE VOLUME acme.raw.landing")) == "VOLUME_ALREADY_EXISTS"
    assert sql(env, "CREATE VOLUME IF NOT EXISTS acme.raw.landing")["status"] == "ok"
    assert err(sql(env, "CREATE VOLUME acme.nope.v")) == "SCHEMA_NOT_FOUND"
    assert upload(env, "acme.raw.landing", "orders/day1.csv", CSV1)["status"] == "succeeded"
    assert upload(env, "acme.raw.landing", "orders/day2.csv", CSV2)["status"] == "succeeded"
    assert upload(env, "acme.raw.landing", "notes.txt", "hello")["status"] == "succeeded"
    ls = rows(sql(env, "LIST '/Volumes/acme/raw/landing'"))
    assert sorted(r[1] for r in ls) == ["notes.txt", "orders/"]
    assert [r[1] for r in rows(sql(env, "LIST '/Volumes/acme/raw/landing/orders'"))] == ["day1.csv", "day2.csv"]
    assert [r[0] for r in rows(sql(env, "SHOW VOLUMES IN acme.raw"))] == ["acme.raw.landing"]
    # 대상 테이블이 없으면 오류, 있으면 적재
    cp = "COPY INTO acme.raw.orders FROM '/Volumes/acme/raw/landing/orders/' FILEFORMAT = CSV FORMAT_OPTIONS ('header'='true')"
    assert err(sql(env, cp)) == "TABLE_OR_VIEW_NOT_FOUND"
    assert sql(env, "CREATE TABLE acme.raw.orders (id BIGINT, name VARCHAR, qty BIGINT)")["status"] == "ok"
    r = sql(env, cp)
    assert r["status"] == "ok", r
    assert rows(r) == [[3, 3, 0]]
    assert rows(sql(env, "SELECT count(*) FROM acme.raw.orders"))[0][0] == 3
    r2 = sql(env, cp)                                                       # 멱등: 이미 적재한 파일은 건너뜀
    assert rows(r2) == [[0, 0, 0]] and rows(sql(env, "SELECT count(*) FROM acme.raw.orders"))[0][0] == 3
    assert rows(sql(env, cp.replace("('header'='true')", "('header'='true') COPY_OPTIONS ('force'='true')")))[0][0] == 3
    assert rows(sql(env, "SELECT count(*) FROM acme.raw.orders"))[0][0] == 6
    ops = [r_[3] for r_ in rows(sql(env, "DESCRIBE HISTORY acme.raw.orders"))]
    assert ops[:2] == ["COPY INTO", "COPY INTO"] and ops[-1] == "CREATE TABLE"
    # 새 파일만 증분 적재
    upload(env, "acme.raw.landing", "orders/day3.csv", "id,name,qty\n9,z,90\n")
    assert rows(sql(env, cp))[0][0] == 1
    # 쿼리 이력에는 소스 'volume' 으로 남는다
    h = env["c"].get(f"/api/sessions/{env['sid']}/query-history?via=volume", headers=env["L"]).json()
    assert h["total"] >= 5 and any(x["statement"] == "COPY INTO" for x in h["items"])


def test_copy_into_validation_errors(env):
    free(env)
    sql(env, "CREATE CATALOG acme"); sql(env, "CREATE SCHEMA acme.raw"); sql(env, "CREATE VOLUME acme.raw.v")
    sql(env, "CREATE TABLE acme.raw.t (id BIGINT, name VARCHAR, qty BIGINT)")
    upload(env, "acme.raw.v", "a.csv", "id,name,qty\n1,a,x\n")
    upload(env, "acme.raw.v", "b.csv", "id,wrong,qty\n1,a,1\n")
    upload(env, "acme.raw.v", "c.csv", "1,a\n")
    base = "COPY INTO acme.raw.t FROM '/Volumes/acme/raw/v/{}' FILEFORMAT = CSV FORMAT_OPTIONS ('header'='{}')"
    assert err(sql(env, base.format("a.csv", "true"))) == "EXECUTION_ERROR"                 # 타입 변환 실패
    assert err(sql(env, base.format("b.csv", "true"))) == "SCHEMA_MISMATCH"
    assert err(sql(env, base.format("c.csv", "false"))) == "MALFORMED_CSV"
    assert err(sql(env, base.format("nofile.csv", "true"))) == "PATH_NOT_FOUND"
    assert err(sql(env, "COPY INTO acme.raw.t FROM '/Volumes/acme/raw/v/' FILEFORMAT = JSON")) == "UNSUPPORTED_FILEFORMAT"
    assert err(sql(env, "COPY INTO acme.raw.t FROM '/tmp/x' FILEFORMAT = CSV")) == "INVALID_PATH"
    assert err(sql(env, "LIST '/Volumes/acme/raw/ghost'")) == "VOLUME_NOT_FOUND"
    assert rows(sql(env, "SELECT count(*) FROM acme.raw.t"))[0][0] == 0                     # 실패한 적재는 아무것도 쓰지 않음


def test_volume_permissions(env):
    start_wh(env)
    fix_perm(env)
    # 기본 프로필: 학습자는 gold 에 CREATE VOLUME 이 있고 silver 에는 없다
    assert err(sql(env, "CREATE VOLUME food_dev.silver.v1")) == "INSUFFICIENT_PERMISSIONS"
    assert sql(env, "CREATE VOLUME food_dev.gold.vg")["status"] == "ok"
    # 관리자가 만든 volume 은 READ/WRITE VOLUME 없이 접근 불가
    a = env["c"].post(f"/api/sessions/{env['sid']}/commands", headers=env["A"], json={"command_type": "sql.execute", "payload": {"sql": "CREATE VOLUME food_dev.gold.adminvol"}}).json()
    assert a["status"] == "ok", a
    up_admin = upload(env, "food_dev.gold.adminvol", "x.csv", CSV1, who="A")
    assert up_admin["status"] == "succeeded"
    assert err(sql(env, "LIST '/Volumes/food_dev/gold/adminvol'")) == "INSUFFICIENT_PERMISSIONS"
    denied = upload(env, "food_dev.gold.adminvol", "y.csv", CSV1)
    assert denied["status"] == "failed" and denied["error"]["code"] == "INSUFFICIENT_PERMISSIONS"
    # 학습자가 스스로 GRANT 는 불가, 관리자가 부여하면 가능
    assert err(sql(env, "GRANT READ VOLUME ON VOLUME food_dev.gold.adminvol TO `data-engineers`")) == "INSUFFICIENT_PERMISSIONS"
    g = env["c"].post(f"/api/sessions/{env['sid']}/commands", headers=env["A"], json={"command_type": "sql.execute", "payload": {"sql": "GRANT READ VOLUME ON VOLUME food_dev.gold.adminvol TO `data-engineers`"}}).json()
    assert g["status"] == "ok", g
    assert sql(env, "LIST '/Volumes/food_dev/gold/adminvol'")["status"] == "ok"
    # 삭제는 소유자/관리자만
    assert err(sql(env, "DROP VOLUME food_dev.gold.adminvol")) == "INSUFFICIENT_PERMISSIONS"
    assert sql(env, "DROP VOLUME food_dev.gold.vg")["status"] == "ok"


def test_volume_upload_limits_and_rest(env):
    free(env)
    sql(env, "CREATE CATALOG acme"); sql(env, "CREATE SCHEMA acme.raw")
    c, sid, L = env["c"], env["sid"], env["L"]
    r = c.post(f"/api/sessions/{sid}/volumes", headers=L, json={"name": "acme.raw.v", "comment": "it's"}).json()
    assert r["status"] == "succeeded" and r["volumes"][0]["path"] == "/Volumes/acme/raw/v" and "acme.raw" in r["create_targets"]
    assert upload(env, "acme.raw.v", "../x.csv", "a")["error"]["code"] == "INVALID_PATH"
    assert upload(env, "acme.raw.v", "big.csv", "x" * 200_001)["error"]["code"] == "FILE_TOO_LARGE"
    for i in range(30):
        assert upload(env, "acme.raw.v", f"f{i}.csv", "a")["status"] == "succeeded"
    assert upload(env, "acme.raw.v", "one_more.csv", "a")["error"]["code"] == "VOLUME_FULL"
    assert upload(env, "acme.raw.v", "f0.csv", "b")["status"] == "succeeded"              # 덮어쓰기는 허용
    fl = c.get(f"/api/sessions/{sid}/volumes/files?volume=acme.raw.v", headers=L).json()
    assert fl["status"] == "succeeded" and len(fl["files"]) == 30 and "text" not in fl["files"][0]
    d = c.post(f"/api/sessions/{sid}/volumes/files/delete", headers=L, json={"volume": "acme.raw.v", "path": "f0.csv"}).json()
    assert d["status"] == "succeeded" and d["files"] == 29
    assert c.post(f"/api/sessions/{sid}/volumes/delete", headers=L, json={"name": "acme.raw.v"}).json()["status"] == "succeeded"


def test_other_users_cannot_see_session(env):
    free(env)
    sql(env, "CREATE CATALOG acme")
    other = env["c"].post("/api/auth/login", json={"name": "other", "role": "learner"}).json()["token"]
    h2 = {"Authorization": "Bearer " + other}
    assert env["c"].get(f"/api/sessions/{env['sid']}/volumes", headers=h2).status_code == 404


def test_total_volume_bytes_cap(env):
    free(env)
    sql(env, "CREATE CATALOG acme"); sql(env, "CREATE SCHEMA acme.raw"); sql(env, "CREATE VOLUME acme.raw.v1"); sql(env, "CREATE VOLUME acme.raw.v2")
    big = "x" * 199_000
    ok = sum(upload(env, "acme.raw.v1" if i < 15 else "acme.raw.v2", f"f{i}.csv", big)["status"] == "succeeded" for i in range(15))
    assert ok == 15                                                   # 약 2.99MB
    r = upload(env, "acme.raw.v2", "f99.csv", big)
    assert r["status"] == "failed" and r["error"]["code"] == "VOLUME_FULL"
    assert upload(env, "acme.raw.v1", "f0.csv", "small")["status"] == "succeeded"        # 덮어쓰기로 줄이는 것은 허용
