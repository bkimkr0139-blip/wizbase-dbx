"""검증용 개발 DB 컨테이너에 합성 fixture 를 적재한다(개발·검증 전용). 사용: python tools/ax_seed_real.py pg|mysql|oracle"""
import sys, time
sys.path.insert(0, ".")
from backend import ax_fixture as fx

def retry(fn, n=60, wait=3):
    last = None
    for _ in range(n):
        try:
            return fn()
        except Exception as e:
            last = e; time.sleep(wait)
    raise last

def pg():
    import psycopg2
    cn = retry(lambda: psycopg2.connect(host="127.0.0.1", port=15432, dbname="wzdev", user="postgres", password="wzpass"))
    cn.autocommit = True
    c = cn.cursor()
    c.execute("DROP SCHEMA IF EXISTS wzdev CASCADE"); c.execute("CREATE SCHEMA wzdev"); c.execute("SET search_path TO wzdev")
    for s in fx.ddl("postgresql"): c.execute(s)
    for sql, rows in fx.inserts("postgresql"): c.executemany(sql, rows)
    c.execute("ANALYZE")
    # 읽기 전용 계정(metadata/runtime_read)과 command 계정을 분리
    c.execute("DROP ROLE IF EXISTS wz_ro"); c.execute("CREATE ROLE wz_ro LOGIN PASSWORD 'ropass'")
    c.execute("GRANT USAGE ON SCHEMA wzdev TO wz_ro"); c.execute("GRANT SELECT ON ALL TABLES IN SCHEMA wzdev TO wz_ro")
    c.execute("DROP ROLE IF EXISTS wz_cmd"); c.execute("CREATE ROLE wz_cmd LOGIN PASSWORD 'cmdpass'")
    c.execute("GRANT USAGE ON SCHEMA wzdev TO wz_cmd"); c.execute("GRANT SELECT ON ALL TABLES IN SCHEMA wzdev TO wz_cmd")
    c.execute("GRANT UPDATE (requested_qty, row_version) ON wzdev.sales_orders TO wz_cmd")
    c.execute("GRANT UPDATE (row_version) ON wzdev.stock TO wz_cmd")  # 잠금용(FOR UPDATE 가 UPDATE 권한을 요구). on_hand 는 수정 불가
    print("pg ok")

def mysql():
    import pymysql
    cn = retry(lambda: pymysql.connect(host="127.0.0.1", port=13306, user="root", password="wzpass", autocommit=True))
    c = cn.cursor()
    c.execute("DROP DATABASE IF EXISTS wzdev"); c.execute("CREATE DATABASE wzdev CHARACTER SET utf8mb4"); c.execute("USE wzdev")
    for s in fx.ddl("mysql"): c.execute(s)
    for sql, rows in fx.inserts("mysql"): c.executemany(sql, rows)
    c.execute("ANALYZE TABLE " + ",".join(n for n, *_ in fx.TABLES))
    for u, pw in (("wz_ro", "ropass"), ("wz_cmd", "cmdpass")):
        c.execute(f"DROP USER IF EXISTS '{u}'@'%'"); c.execute(f"CREATE USER '{u}'@'%' IDENTIFIED BY '{pw}'")
    c.execute("GRANT SELECT, SHOW VIEW ON wzdev.* TO 'wz_ro'@'%'")
    c.execute("GRANT SELECT ON wzdev.* TO 'wz_cmd'@'%'"); c.execute("GRANT UPDATE (requested_qty, row_version) ON wzdev.sales_orders TO 'wz_cmd'@'%'")
    c.execute("GRANT UPDATE (row_version) ON wzdev.stock TO 'wz_cmd'@'%'")  # 잠금용. on_hand 는 수정 불가
    print("mysql ok")

def oracle():
    import oracledb
    cn = retry(lambda: oracledb.connect(user="system", password="wzpass", dsn="127.0.0.1:11521/FREEPDB1"), n=120, wait=5)
    c = cn.cursor()
    for u in ("WZDEV", "WZ_RO", "WZ_CMD"):
        try: c.execute(f"DROP USER {u} CASCADE")
        except Exception: pass
    c.execute("CREATE USER WZDEV IDENTIFIED BY wzpass QUOTA UNLIMITED ON USERS")
    c.execute("GRANT CREATE SESSION, CREATE TABLE, CREATE VIEW TO WZDEV")
    cn2 = oracledb.connect(user="wzdev", password="wzpass", dsn="127.0.0.1:11521/FREEPDB1")
    d = cn2.cursor()
    for s in fx.ddl("oracle"): d.execute(s)
    for sql, rows in fx.inserts("oracle"):
        d.executemany(sql, rows)
    cn2.commit()
    d.execute("BEGIN DBMS_STATS.GATHER_SCHEMA_STATS('WZDEV'); END;")
    for u, pw in (("WZ_RO", "ropass"), ("WZ_CMD", "cmdpass")):
        try: c.execute(f"CREATE USER {u} IDENTIFIED BY {pw}")
        except Exception: pass
        c.execute(f"GRANT CREATE SESSION TO {u}")
        for n, *_ in fx.TABLES: c.execute(f"GRANT SELECT ON WZDEV.{n} TO {u}")
        c.execute(f"GRANT SELECT ON WZDEV.v_open_orders TO {u}")
    c.execute("GRANT UPDATE (requested_qty, row_version) ON WZDEV.sales_orders TO WZ_CMD")
    print("oracle ok")

def seed(name):
    {"pg": pg, "mysql": mysql, "oracle": oracle}[name]()


if __name__ == "__main__":
    seed(sys.argv[1])
