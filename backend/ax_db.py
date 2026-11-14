"""AX 레거시 DB adapter(SQLite fixture / PostgreSQL / MySQL / Oracle).
- 모든 adapter 는 같은 모양의 구조 수집 결과(objects)와 같은 Conn 인터페이스를 낸다.
- 서버가 임의 host 로 직접 접속하는 것은 개발 전용: WZ_AX_ALLOW_DIRECT_DB=1 이어야 하고, WZ_AX_DB_HOSTS 로 host allowlist 를 걸 수 있다.
  (운영 권장 구조는 고객망 connector agent 이며 이 빌드에는 없다.)
- 자격증명은 secret://name 참조 → 환경변수 WZ_SECRET_<NAME>="user:password" 로만 해석한다(저장·로그·응답에 넣지 않음).
"""
from __future__ import annotations
import hashlib, json, os, re, sqlite3
from .core import ApiError


class Row:
    """r[0] / r["name"](대소문자 무시) / keys() 를 모두 지원하는 결과 행."""
    __slots__ = ("_v", "_k")

    def __init__(self, names, values):
        self._k = [str(n).lower() for n in names]
        self._v = list(values)

    def __getitem__(self, i):
        return self._v[i] if isinstance(i, int) else self._v[self._k.index(str(i).lower())]

    def keys(self):
        return self._k

    def __iter__(self):
        return iter(self._v)

    def __len__(self):
        return len(self._v)


class Cur:
    def __init__(self, cur, rows=None):
        self._c, self.rowcount = cur, getattr(cur, "rowcount", -1)
        self._names = [d[0] for d in (cur.description or [])]

    def fetchone(self):
        r = self._c.fetchone()
        return None if r is None else Row(self._names, r)

    def fetchall(self):
        return [Row(self._names, r) for r in self._c.fetchall()]


class Conn:
    kind = "?"
    lock_suffix = " FOR UPDATE"

    def q(self, name):
        return '"' + name.replace('"', '""') + '"'

    def qual(self, schema, name):
        return f"{self.q(schema)}.{self.q(name)}" if schema else self.q(name)

    def sample(self, cols, schema, table, n):
        return f"SELECT {cols} FROM {self.qual(schema, table)} LIMIT {int(n)}"

    def _ph(self, sql):
        return sql

    def limit(self, sql, n):
        return f"{sql} LIMIT {int(n)}"

    def execute(self, sql, params=()):
        c = self.raw.cursor()
        c.execute(self._ph(sql), tuple(params))
        return Cur(c)

    def begin(self):
        pass

    def commit(self):
        self.raw.commit()

    def rollback(self):
        self.raw.rollback()

    def close(self):
        try:
            self.raw.close()
        except Exception:
            pass


class SqliteConn(Conn):
    kind = "sqlite"
    lock_suffix = ""

    def __init__(self, raw):
        self.raw = raw
        raw.row_factory = None

    def _ph(self, sql):
        return sql

    def begin(self):
        self.raw.execute("BEGIN IMMEDIATE")

    def commit(self):
        self.raw.execute("COMMIT")

    def rollback(self):
        self.raw.execute("ROLLBACK")


class PgConn(Conn):
    kind = "postgresql"

    def __init__(self, raw, schema):
        self.raw, self.schema = raw, schema
        c = raw.cursor()
        c.execute(f'SET search_path TO "{schema}"')
        raw.commit()

    def _ph(self, sql):
        return sql.replace("?", "%s")


class MyConn(Conn):
    kind = "mysql"

    def q(self, name):
        return "`" + name.replace("`", "``") + "`"

    def _ph(self, sql):
        return sql.replace("?", "%s")


class OraConn(Conn):
    kind = "oracle"

    def sample(self, cols, schema, table, n):
        return f"SELECT {cols} FROM {self.qual(schema, table)} FETCH FIRST {int(n)} ROWS ONLY"

    def limit(self, sql, n):
        return f"{sql} FETCH FIRST {int(n)} ROWS ONLY"

    def _ph(self, sql):
        i = [0]

        def sub(_):
            i[0] += 1
            return f":{i[0]}"
        return re.sub(r"\?", sub, sql)


def _secret(ref):
    name = re.sub(r"[^A-Za-z0-9]", "_", ref[len("secret://"):]).upper()
    v = os.environ.get("WZ_SECRET_" + name)
    if not v or ":" not in v:
        raise ApiError(409, "SECRET_NOT_RESOLVED", f"secret 참조를 해석하지 못했습니다(서버 환경변수 WZ_SECRET_{name}=user:password 필요). 값은 저장·표시하지 않습니다.")
    u, p = v.split(":", 1)
    return u, p


def direct_allowed(host):
    if os.environ.get("WZ_AX_ALLOW_DIRECT_DB") != "1":
        raise ApiError(403, "DIRECT_DB_DISABLED", "서버의 직접 DB 접속은 개발 전용 설정(WZ_AX_ALLOW_DIRECT_DB=1)에서만 허용됩니다. 운영 권장 구조는 고객망 connector agent입니다.")
    allow = [h.strip() for h in os.environ.get("WZ_AX_DB_HOSTS", "").split(",") if h.strip()]
    if allow and host not in allow:
        raise ApiError(403, "HOST_NOT_ALLOWLISTED", "등록된 host allowlist에 없는 대상입니다.")


def driver_status():
    out = {}
    for n, m in (("postgresql", "psycopg2"), ("mysql", "pymysql"), ("oracle", "oracledb")):
        try:
            __import__(m)
            out[n] = "installed"
        except Exception:
            out[n] = "missing"
    return out


def open_conn(c, schema_hint=None):
    """connector dict → Conn. 실패는 단계가 드러나는 ApiError."""
    eng = c["engine"]
    schema = (c.get("schema_allowlist") or [schema_hint or ""])[0]
    direct_allowed(c.get("host"))
    user, pw = _secret(c["secret_ref"])
    to = c.get("timeout_s", 5)
    try:
        if eng == "postgresql":
            import psycopg2
            raw = psycopg2.connect(host=c["host"], port=c["port"], dbname=c["database"], user=user, password=pw, connect_timeout=to, sslmode="require" if c.get("tls") else "disable",
                                   options="-c statement_timeout=%d" % (to * 1000))
            raw.autocommit = False
            return PgConn(raw, schema)
        if eng == "mysql":
            import pymysql
            raw = pymysql.connect(host=c["host"], port=int(c["port"]), user=user, password=pw, database=c.get("database") or schema, connect_timeout=to, read_timeout=to * 2,
                                  ssl={"ca": None} if c.get("tls") else None, autocommit=False)
            return _wrap_my(raw)
        if eng == "oracle":
            import oracledb
            raw = oracledb.connect(user=user, password=pw, dsn=f"{c['host']}:{c['port']}/{c['service_name']}", tcp_connect_timeout=to)
            o = OraConn()
            o.raw = raw
            if schema:
                raw.cursor().execute(f'ALTER SESSION SET CURRENT_SCHEMA = "{schema.upper()}"')
            return o
    except ApiError:
        raise
    except ImportError:
        raise ApiError(501, "DRIVER_MISSING", f"{eng} 드라이버가 설치되어 있지 않습니다.")
    except Exception as e:
        raise ApiError(502, "DB_CONNECT_FAILED", f"{eng} 접속 실패({type(e).__name__}) — 호스트·포트·계정·secret 확인")
    raise ApiError(400, "BAD_ENGINE", eng)


def _wrap_my(raw):
    m = MyConn()
    m.raw = raw
    return m


# ------------------------------------------------------------------ 구조 수집(엔진별 딕셔너리)
def _finish(objs):
    for o in objs:
        if o["kind"] == "view" and not (o.get("view_sql") or "").strip():
            o["view_sql"] = None
            o["view_sql_note"] = "뷰 정의를 읽지 못함(권한 부족 가능: MySQL SHOW VIEW 등) — lineage 미확인"
        o["fingerprint"] = hashlib.sha256(json.dumps({k: o[k] for k in ("columns", "pk", "fks", "indexes", "view_sql")}, sort_keys=True, default=str).encode()).hexdigest()[:16]
    return objs


def _mk(schema, name, kind, cols, pk, fks, idx, vsql, rows, basis):
    return {"object_id": f"{schema}.{name}", "schema": schema, "name": name, "kind": kind, "columns": cols, "pk": pk, "fks": fks, "indexes": idx, "view_sql": vsql, "row_count": rows, "row_count_basis": basis}


def collect_pg(cn, schemas):
    out = []
    for sch in schemas:
        tabs = cn.execute("SELECT table_name, table_type FROM information_schema.tables WHERE table_schema=? ORDER BY table_name", (sch,)).fetchall()
        for t in tabs:
            name, kind = t[0], ("view" if t[1] == "VIEW" else "table")
            cols = [{"name": r[0], "type": r[1], "nullable": r[2] == "YES", "default": r[3], "pk_pos": 0, "comment": r[5]}
                    for r in cn.execute("SELECT column_name, data_type, is_nullable, column_default, ordinal_position, "
                                        "col_description((quote_ident(table_schema)||'.'||quote_ident(table_name))::regclass, ordinal_position) "
                                        "FROM information_schema.columns WHERE table_schema=? AND table_name=? ORDER BY ordinal_position", (sch, name)).fetchall()]
            pk = [r[0] for r in cn.execute("SELECT a.attname FROM pg_constraint c JOIN pg_class t ON t.oid=c.conrelid JOIN pg_namespace n ON n.oid=t.relnamespace "
                                           "JOIN LATERAL unnest(c.conkey) WITH ORDINALITY k(attnum,ord) ON true JOIN pg_attribute a ON a.attrelid=c.conrelid AND a.attnum=k.attnum "
                                           "WHERE c.contype='p' AND n.nspname=? AND t.relname=? ORDER BY k.ord", (sch, name)).fetchall()]  # information_schema 는 SELECT 만 가진 계정에게 제약을 숨기므로 pg_constraint 사용
            for c in cols:
                c["pk_pos"] = (pk.index(c["name"]) + 1) if c["name"] in pk else 0
            fks = []
            for r in cn.execute("SELECT c.conname, rn.nspname, rt.relname, c.convalidated, "
                                "array(SELECT a.attname FROM unnest(c.conkey) WITH ORDINALITY k(attnum,ord) JOIN pg_attribute a ON a.attrelid=c.conrelid AND a.attnum=k.attnum ORDER BY k.ord), "
                                "array(SELECT a.attname FROM unnest(c.confkey) WITH ORDINALITY k(attnum,ord) JOIN pg_attribute a ON a.attrelid=c.confrelid AND a.attnum=k.attnum ORDER BY k.ord) "
                                "FROM pg_constraint c JOIN pg_class t ON t.oid=c.conrelid JOIN pg_namespace n ON n.oid=t.relnamespace JOIN pg_class rt ON rt.oid=c.confrelid JOIN pg_namespace rn ON rn.oid=rt.relnamespace "
                                "WHERE c.contype='f' AND n.nspname=? AND t.relname=? ORDER BY c.conname", (sch, name)).fetchall():
                fks.append({"name": r[0], "columns": list(r[4]), "ref_table": r[2], "ref_schema": r[1], "ref_columns": list(r[5]), "status": "ENABLED", "validated": bool(r[3]), "origin": "DECLARED"})
            idx = [{"name": r[0], "unique": bool(r[1]), "columns": list(r[2])} for r in cn.execute(
                "SELECT i.relname, x.indisunique, array(SELECT a.attname FROM unnest(x.indkey) WITH ORDINALITY k(attnum,ord) JOIN pg_attribute a ON a.attrelid=x.indrelid AND a.attnum=k.attnum ORDER BY k.ord) "
                "FROM pg_index x JOIN pg_class i ON i.oid=x.indexrelid JOIN pg_class t ON t.oid=x.indrelid JOIN pg_namespace n ON n.oid=t.relnamespace WHERE n.nspname=? AND t.relname=? AND NOT x.indisprimary ORDER BY i.relname", (sch, name)).fetchall()]
            vs = None
            if kind == "view":
                vs = cn.execute("SELECT pg_get_viewdef((quote_ident(?)||'.'||quote_ident(?))::regclass)", (sch, name)).fetchone()[0].strip()
            est = None
            if kind == "table":
                est = cn.execute("SELECT reltuples::bigint FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=? AND c.relname=?", (sch, name)).fetchone()[0]
                est = None if est is None or est < 0 else est
            out.append(_mk(sch, name, kind, cols, pk, fks, idx, vs, est, "estimate(pg_class.reltuples)" if est is not None else None))
    cn.rollback()
    return _finish(out)


def collect_mysql(cn, schemas):
    out = []
    for sch in schemas:
        for t in cn.execute("SELECT table_name, table_type, table_rows FROM information_schema.tables WHERE table_schema=? ORDER BY table_name", (sch,)).fetchall():
            name, kind = t[0], ("view" if t[1] == "VIEW" else "table")
            cols = [{"name": r[0], "type": r[1], "nullable": r[2] == "YES", "default": r[3], "pk_pos": 0, "comment": r[5] or None}
                    for r in cn.execute("SELECT column_name, column_type, is_nullable, column_default, ordinal_position, column_comment FROM information_schema.columns WHERE table_schema=? AND table_name=? ORDER BY ordinal_position", (sch, name)).fetchall()]
            pk = [r[0] for r in cn.execute("SELECT column_name FROM information_schema.key_column_usage WHERE table_schema=? AND table_name=? AND constraint_name='PRIMARY' ORDER BY ordinal_position", (sch, name)).fetchall()]
            for c in cols:
                c["pk_pos"] = (pk.index(c["name"]) + 1) if c["name"] in pk else 0
            fk = {}
            for r in cn.execute("SELECT constraint_name, column_name, referenced_table_schema, referenced_table_name, referenced_column_name FROM information_schema.key_column_usage "
                                "WHERE table_schema=? AND table_name=? AND referenced_table_name IS NOT NULL ORDER BY constraint_name, ordinal_position", (sch, name)).fetchall():
                f = fk.setdefault(r[0], {"name": r[0], "columns": [], "ref_table": r[3], "ref_schema": r[2], "ref_columns": [], "status": "ENABLED", "validated": True, "origin": "DECLARED"})
                f["columns"].append(r[1]); f["ref_columns"].append(r[4])
            ix = {}
            for r in cn.execute("SELECT index_name, non_unique, column_name FROM information_schema.statistics WHERE table_schema=? AND table_name=? AND index_name<>'PRIMARY' ORDER BY index_name, seq_in_index", (sch, name)).fetchall():
                ix.setdefault(r[0], {"name": r[0], "unique": r[1] == 0, "columns": []})["columns"].append(r[2])
            vs = None
            if kind == "view":
                vs = cn.execute("SELECT view_definition FROM information_schema.views WHERE table_schema=? AND table_name=?", (sch, name)).fetchone()[0]
            est = t[2] if kind == "table" else None
            out.append(_mk(sch, name, kind, cols, pk, list(fk.values()), list(ix.values()), vs, est, "estimate(information_schema.table_rows)" if est is not None else None))
    cn.rollback()
    return _finish(out)


def collect_oracle(cn, schemas):
    out = []
    for sch in schemas:
        o = sch.upper()
        tabs = [(r[0], "table", r[1]) for r in cn.execute("SELECT table_name, num_rows FROM all_tables WHERE owner=? ORDER BY table_name", (o,)).fetchall()] + \
               [(r[0], "view", None) for r in cn.execute("SELECT view_name FROM all_views WHERE owner=? ORDER BY view_name", (o,)).fetchall()]
        for name, kind, nrows in sorted(tabs):
            com = {r[0]: r[1] for r in cn.execute("SELECT column_name, comments FROM all_col_comments WHERE owner=? AND table_name=?", (o, name)).fetchall()}
            cols = [{"name": r[0], "type": r[1] if r[1] not in ("VARCHAR2", "CHAR", "NVARCHAR2") else f"{r[1]}({r[4]})", "nullable": r[2] == "Y", "default": (str(r[3]).strip() if r[3] is not None else None), "pk_pos": 0, "comment": com.get(r[0])}
                    for r in cn.execute("SELECT column_name, data_type, nullable, data_default, data_length, column_id FROM all_tab_columns WHERE owner=? AND table_name=? ORDER BY column_id", (o, name)).fetchall()]
            pkc = cn.execute("SELECT constraint_name FROM all_constraints WHERE owner=? AND table_name=? AND constraint_type='P'", (o, name)).fetchone()
            pk = [r[0] for r in cn.execute("SELECT column_name FROM all_cons_columns WHERE owner=? AND constraint_name=? ORDER BY position", (o, pkc[0])).fetchall()] if pkc else []
            for c in cols:
                c["pk_pos"] = (pk.index(c["name"]) + 1) if c["name"] in pk else 0
            fks = []
            for r in cn.execute("SELECT c.constraint_name, c.status, c.validated, c.r_owner, c.r_constraint_name FROM all_constraints c WHERE c.owner=? AND c.table_name=? AND c.constraint_type='R' ORDER BY c.constraint_name", (o, name)).fetchall():
                cc = [x[0] for x in cn.execute("SELECT column_name FROM all_cons_columns WHERE owner=? AND constraint_name=? ORDER BY position", (o, r[0])).fetchall()]
                rc = cn.execute("SELECT table_name FROM all_constraints WHERE owner=? AND constraint_name=?", (r[3], r[4])).fetchone()
                rcols = [x[0] for x in cn.execute("SELECT column_name FROM all_cons_columns WHERE owner=? AND constraint_name=? ORDER BY position", (r[3], r[4])).fetchall()]
                fks.append({"name": r[0], "columns": cc, "ref_table": rc[0], "ref_schema": r[3], "ref_columns": rcols, "status": r[1], "validated": r[2] == "VALIDATED", "origin": "DECLARED"})
            ix = {}
            for r in cn.execute("SELECT i.index_name, i.uniqueness, c.column_name FROM all_indexes i JOIN all_ind_columns c ON c.index_owner=i.owner AND c.index_name=i.index_name "
                                "WHERE i.table_owner=? AND i.table_name=? AND i.index_name NOT IN (SELECT constraint_name FROM all_constraints WHERE owner=? AND table_name=? AND constraint_type='P') ORDER BY i.index_name, c.column_position", (o, name, o, name)).fetchall():
                ix.setdefault(r[0], {"name": r[0], "unique": r[1] == "UNIQUE", "columns": []})["columns"].append(r[2])
            vs = None
            if kind == "view":
                vs = str(cn.execute("SELECT text FROM all_views WHERE owner=? AND view_name=?", (o, name)).fetchone()[0]).strip()
            out.append(_mk(o, name, kind, cols, pk, fks, list(ix.values()), vs, nrows, "estimate(all_tables.num_rows)" if nrows is not None else None))
    cn.rollback()
    return _finish(out)


COLLECTORS = {"postgresql": collect_pg, "mysql": collect_mysql, "oracle": collect_oracle}


def visible_count(cn, kind, schemas):
    sch = schemas[0] if kind != "oracle" else schemas[0].upper()
    sql = {"postgresql": "SELECT count(*) FROM information_schema.tables WHERE table_schema=?", "mysql": "SELECT count(*) FROM information_schema.tables WHERE table_schema=?",
           "oracle": "SELECT (SELECT count(*) FROM all_tables WHERE owner=?) + (SELECT count(*) FROM all_views WHERE owner=?) FROM dual"}[kind]
    n = cn.execute(sql, (sch, sch) if kind == "oracle" else (sch,)).fetchone()[0]
    cn.rollback()
    return n


def ident_sql(kind):
    return {"postgresql": "SELECT version()", "mysql": "SELECT version()", "oracle": "SELECT banner FROM v$version WHERE ROWNUM=1"}[kind]


def ping_sql(kind):
    return "SELECT 1 FROM dual" if kind == "oracle" else "SELECT 1"
