"""다중 catalog(CREATE CATALOG) · Volumes · COPY INTO(볼륨→테이블) — 교육용 시뮬레이션.

- 사용자가 만든 catalog 는 DuckDB 의 food_dev 안에 'catalog__schema' 라는 물리 스키마로 저장된다(core.pfq 참고).
  UC 이름·권한·이력은 모두 가상 이름(catalog.schema.table)으로 다룬다.
- Volume 은 S["volumes"]["cat.schema.vol"] 에 파일 텍스트를 보관한다(파일당 ≤200KB, 볼륨당 ≤30개). 실제 클라우드 저장소가 아니다.
- 구문 처리: core._special 이 handle_sql() 에 먼저 위임한다(정규식 기반이라 지원 범위가 좁다).
  CREATE/DROP CATALOG, SHOW CATALOGS, CREATE/DROP VOLUME, SHOW VOLUMES IN, LIST '/Volumes/...', COPY INTO ... FROM '/Volumes/...' (CSV),
  GRANT/REVOKE ... ON CATALOG|VOLUME.
"""
from __future__ import annotations

import csv
import hashlib
import io
import re
from typing import Optional

from fastapi import Header

from . import core
from .core import CAT

_NAME = re.compile(r"^[a-z][a-z0-9_]{0,30}$")
_VNAME = re.compile(r"^[a-z][a-z0-9_]{0,40}$")
_RESERVED = {CAT, "system", "samples", "main", "information_schema", "hive_metastore", "memory"}
MAX_FILE = 200_000
MAX_FILES = 30
MAX_TOTAL = 3_000_000
SIM_NOTE = "교육용 시뮬레이션입니다(실제 클라우드 저장소·Delta 엔진이 아닌 로컬 DuckDB·메모리 저장)."

_Q = r"(?:'((?:[^']|'')*)')"
_RE_CC = re.compile(r"^\s*CREATE\s+CATALOG\s+(IF\s+NOT\s+EXISTS\s+)?(\w+)(?:\s+COMMENT\s+" + _Q + r")?\s*;?\s*$", re.I)
_RE_DC = re.compile(r"^\s*DROP\s+CATALOG\s+(IF\s+EXISTS\s+)?(\w+)(\s+CASCADE)?\s*;?\s*$", re.I)
_RE_SC = re.compile(r"^\s*SHOW\s+CATALOGS\s*;?\s*$", re.I)
_RE_CV = re.compile(r"^\s*CREATE\s+VOLUME\s+(IF\s+NOT\s+EXISTS\s+)?([\w.`]+)(?:\s+COMMENT\s+" + _Q + r")?\s*;?\s*$", re.I)
_RE_DV = re.compile(r"^\s*DROP\s+VOLUME\s+(IF\s+EXISTS\s+)?([\w.`]+)\s*;?\s*$", re.I)
_RE_SV = re.compile(r"^\s*SHOW\s+VOLUMES\s+IN\s+([\w.`]+)\s*;?\s*$", re.I)
_RE_LIST = re.compile(r"""^\s*LIST\s+(?:'([^']+)'|"([^"]+)")\s*;?\s*$""", re.I)
_RE_COPY = re.compile(r"""^\s*COPY\s+INTO\s+([\w.`]+)\s+FROM\s+(?:'([^']+)'|"([^"]+)")\s*(.*?)\s*;?\s*$""", re.I | re.S)
_RE_GR = re.compile(r"^\s*(GRANT|REVOKE)\s+(.+?)\s+ON\s+(CATALOG|VOLUME)\s+([\w.`]+)\s+(?:TO|FROM)\s+`?([^`\s;]+)`?\s*;?\s*$", re.I)


# ---------------------------------------------------------------- 공통
def _out(base: dict, columns, rows, notes=None, label=None):
    base.update(status="succeeded", error=None, columns=columns, rows=rows, row_count=len(rows), tables=[], via_override="volume" if (label or "").startswith(("COPY", "LIST", "CREATE VOLUME", "DROP VOLUME", "SHOW VOLUMES")) else None)
    if notes:
        base["compat_notes"] = list(base.get("compat_notes", [])) + notes
    if label:
        base["statement_label"] = label
    return base


def _err(S, base: dict, principal, actor_id, code, msg, hint=None, label=None, audit=False, **kw):
    base.update(status="failed", columns=[], rows=[], error=core.sql_error(code, msg, hint, **kw))
    if label:
        base["statement_label"] = label
        if label.startswith(("COPY", "LIST", "CREATE VOLUME", "DROP VOLUME", "SHOW VOLUMES")):
            base["via_override"] = "volume"
    if audit:
        core.audit(S, actor_id or principal, "SQL_PERMISSION_DENIED", "sql", "failed", "LOCAL_EXECUTED", {"code": code, "msg": msg[:200], "missing": kw.get("missing")}, effective=principal)
    return base


def _need(S, base, principal, actor_id, label, checks):
    """checks = [(priv, sec), ...]. 모자라면 오류 dict, 충분하면 None."""
    for priv, sec in checks:
        if not core.has_priv(S, principal, priv, sec):
            return _err(S, base, principal, actor_id, "INSUFFICIENT_PERMISSIONS", f"{principal} 에게 {sec} 에 대한 {priv} 권한이 없습니다.",
                        "권한 요청 화면에서 최소 권한을 요청하세요(소유자·관리자는 요청 없이 가능).", label, True, missing={"privilege": priv, "securable": sec})
    return None


def _cat_exists(S, cat):
    return cat == CAT or cat in core.user_catalogs(S) or cat in S.get("foreign_catalogs", {})


def _parse3(name):
    parts = name.replace("`", "").split(".")
    return parts if len(parts) == 3 else None


def _volumes(S):
    return S.setdefault("volumes", {})


def _vol_sec(fq):
    return f"volume:{fq}"


def _split_path(path):
    """'/Volumes/c/s/v/a/b.csv' → ('c.s.v', 'a/b.csv'). 형식이 틀리면 None."""
    m = re.match(r"^/Volumes/([^/]+)/([^/]+)/([^/]+)(?:/(.*))?$", path.strip())
    if not m:
        return None
    return f"{m.group(1)}.{m.group(2)}.{m.group(3)}", (m.group(4) or "").strip("/")


def _gate(S, principal, via, need_warehouse, trace, actor_id):
    """웨어하우스·entitlement 검사를 SELECT 1 로 대신한다. 실패하면 오류 dict, 통과하면 기본 결과 dict."""
    r = core._run_sql(S, "SELECT 1 AS x", principal, via, False, need_warehouse, trace, actor_id)
    if r["status"] != "succeeded":
        return r, False
    r = dict(r)
    r.update(columns=[], rows=[], row_count=0, tables=[])
    return r, True


# ---------------------------------------------------------------- SQL 구문 위임
def handle_sql(S, sql, principal, via, need_warehouse, trace, actor_id):
    """확장 구문이면 결과 dict, 아니면 None."""
    for rx in (_RE_CC, _RE_DC, _RE_SC, _RE_CV, _RE_DV, _RE_SV, _RE_LIST, _RE_COPY, _RE_GR):
        m = rx.match(sql)
        if m:
            break
    else:
        return None
    base, ok = _gate(S, principal, via, need_warehouse, trace, actor_id)
    if not ok:
        return base
    if rx is _RE_CC:
        return _create_catalog(S, base, principal, actor_id, m)
    if rx is _RE_DC:
        return _drop_catalog(S, base, principal, actor_id, m)
    if rx is _RE_SC:
        return _show_catalogs(S, base, principal)
    if rx is _RE_CV:
        return _create_volume(S, base, principal, actor_id, m)
    if rx is _RE_DV:
        return _drop_volume(S, base, principal, actor_id, m)
    if rx is _RE_SV:
        return _show_volumes(S, base, principal, actor_id, m)
    if rx is _RE_LIST:
        return _list_path(S, base, principal, actor_id, m.group(1) or m.group(2))
    if rx is _RE_COPY:
        return _copy_into(S, base, principal, actor_id, m)
    return _grant_ext(S, base, principal, actor_id, m)


# ---------------------------------------------------------------- catalog
def _create_catalog(S, base, principal, actor_id, m):
    ine, name, comment = bool(m.group(1)), m.group(2).lower(), (m.group(3) or "").replace("''", "'")
    lab = "CREATE CATALOG"
    if not _NAME.match(name) or "__" in name or name.endswith("_"):
        return _err(S, base, principal, actor_id, "INVALID_NAME", "catalog 이름은 영문 소문자로 시작하고 소문자·숫자·_ 만 쓸 수 있습니다(최대 31자, '__' 금지).", label=lab)
    if name in _RESERVED or name in S.get("foreign_catalogs", {}):
        return _err(S, base, principal, actor_id, "CATALOG_RESERVED", f"`{name}` 은(는) 이미 쓰이는(예약된) 이름입니다.", "다른 이름을 고르세요.", lab)
    if name in core.user_catalogs(S):
        if ine:
            return _out(base, ["catalog", "result"], [[name, "이미 있음(건너뜀)"]], label=lab)
        return _err(S, base, principal, actor_id, "CATALOG_ALREADY_EXISTS", f"catalog `{name}` 이(가) 이미 있습니다.", "IF NOT EXISTS 를 쓰거나 다른 이름을 고르세요.", lab)
    e = _need(S, base, principal, actor_id, lab, [("CREATE CATALOG", "metastore:main")])
    if e:
        return e
    S.setdefault("catalogs", {})[name] = {"owner": principal, "comment": comment, "created_at": core.now_utc()}
    S["owners"][f"catalog:{name}"] = principal
    core.audit(S, actor_id or principal, "UC_CREATE_CATALOG", f"catalog:{name}", "succeeded", "LOCAL_EXECUTED", {"comment": comment[:80]}, effective=principal)
    return _out(base, ["catalog", "result"], [[name, "생성됨"]], ["catalog 는 로컬에 'catalog__schema' 스키마로 저장됩니다(시뮬레이션). 소유자는 하위 모든 객체에 전권을 가집니다."], lab)


def _drop_catalog(S, base, principal, actor_id, m):
    ie, name, cascade = bool(m.group(1)), m.group(2).lower(), bool(m.group(3))
    lab = "DROP CATALOG"
    if name == CAT:
        return _err(S, base, principal, actor_id, "CATALOG_PROTECTED", f"교육용 기본 catalog `{CAT}` 은(는) 삭제할 수 없습니다.", label=lab)
    if name not in core.user_catalogs(S):
        if ie:
            return _out(base, ["catalog", "result"], [[name, "없음(건너뜀)"]], label=lab)
        return _err(S, base, principal, actor_id, "CATALOG_NOT_FOUND", f"내가 만든 catalog `{name}` 을(를) 찾을 수 없습니다.", "SHOW CATALOGS 로 확인하세요.", lab)
    if not (core.is_admin(S, principal) or S["owners"].get(f"catalog:{name}") == principal):
        return _err(S, base, principal, actor_id, "INSUFFICIENT_PERMISSIONS", f"catalog `{name}` 은(는) 소유자 또는 관리자만 삭제할 수 있습니다.", "권한 요청이 아닌 소유자에게 요청하세요.", lab, True)
    c = core._conns[S["id"]]
    pref = f"{name}__"
    schemas = [r[0] for r in c.execute("select schema_name from information_schema.schemata where catalog_name=?", [CAT]).fetchall() if r[0].startswith(pref)]    # LIKE 의 '_' 와일드카드로 다른 catalog 가 매치되지 않게
    vols = [k for k in _volumes(S) if k.startswith(name + ".")]
    if (schemas or vols) and not cascade:
        return _err(S, base, principal, actor_id, "CATALOG_NOT_EMPTY", f"catalog `{name}` 에 schema {len(schemas)}개·volume {len(vols)}개가 남아 있습니다.", "CASCADE 를 붙이면 모두 함께 삭제합니다(되돌릴 수 없음).", lab)
    for sch in schemas:
        for (tbl,) in c.execute("select table_name from information_schema.tables where table_catalog=? and table_schema=?", [CAT, sch]).fetchall():
            fq = f"{name}.{sch[len(pref):]}.{tbl}"
            for h in S.get("thist", {}).pop(fq, []):
                try:
                    c.execute(f'DROP TABLE IF EXISTS memory.main."{core._snap_name(S, fq, h["version"])}"')
                except Exception:
                    pass
        c.execute(f'DROP SCHEMA {CAT}."{sch}" CASCADE')
    for k in vols:
        _volumes(S).pop(k, None)
    for key in ("owners", "views_created_by"):
        d = S.get(key, {})
        for k in [k for k in d if re.match(rf"^(catalog:{name}$|(schema|table|volume):{name}\.)", k) or k.startswith(name + ".")]:
            d.pop(k, None)
    S["grants"] = [g for g in S["grants"] if not re.match(rf"^(catalog:{name}$|(schema|table|volume):{name}\.)", g[2])]
    for k in [k for k in S.get("loaded_files", {}) if k.startswith(name + ".")]:
        S["loaded_files"].pop(k, None)
    S["catalogs"].pop(name, None)
    core.audit(S, actor_id or principal, "UC_DROP_CATALOG", f"catalog:{name}", "succeeded", "LOCAL_EXECUTED", {"cascade": cascade, "schemas": len(schemas), "volumes": len(vols)}, effective=principal)
    return _out(base, ["catalog", "result"], [[name, f"삭제됨(schema {len(schemas)}·volume {len(vols)} 포함)"]], label=lab)


def _show_catalogs(S, base, principal):
    rows = []
    for cat in [CAT] + list(core.user_catalogs(S)) + list(S.get("foreign_catalogs", {})):
        if not core.has_priv(S, principal, "USE CATALOG", f"catalog:{cat}"):
            continue
        if cat == CAT:
            rows.append([cat, "MANAGED(교육 기본)", "uc-admin", ""])
        elif cat in core.user_catalogs(S):
            u = core.user_catalogs(S)[cat]
            rows.append([cat, "MANAGED(내가 만든)", u["owner"], u.get("comment", "")])
        else:
            rows.append([cat, "FOREIGN", "-", ""])
    return _out(base, ["catalog", "type", "owner", "comment"], rows, label="SHOW CATALOGS")


# ---------------------------------------------------------------- volume
def _create_volume(S, base, principal, actor_id, m):
    ine, name, comment = bool(m.group(1)), m.group(2), (m.group(3) or "").replace("''", "'")
    lab = "CREATE VOLUME"
    p3 = _parse3(name)
    if not p3 or not all(_VNAME.match(x) for x in p3):
        return _err(S, base, principal, actor_id, "INVALID_NAME", "volume 이름은 catalog.schema.volume 3단계, 각 이름은 영문 소문자로 시작하고 소문자·숫자·_ 만 가능합니다.", label=lab)
    cat, sch, vol = p3
    fq = ".".join(p3)
    if not _cat_exists(S, cat) or cat in S.get("foreign_catalogs", {}):
        return _err(S, base, principal, actor_id, "TABLE_OR_VIEW_NOT_FOUND", f"catalog `{cat}` 을(를) 찾을 수 없습니다.", "SHOW CATALOGS 로 확인하세요.", lab)
    if not core._existsS(S, core._conns[S["id"]], "schema", [cat, sch]):
        return _err(S, base, principal, actor_id, "SCHEMA_NOT_FOUND", f"schema `{cat}.{sch}` 이(가) 없습니다.", "CREATE SCHEMA 로 먼저 만드세요.", lab)
    if fq in _volumes(S):
        if ine:
            return _out(base, ["volume", "result"], [[fq, "이미 있음(건너뜀)"]], label=lab)
        return _err(S, base, principal, actor_id, "VOLUME_ALREADY_EXISTS", f"volume `{fq}` 이(가) 이미 있습니다.", "IF NOT EXISTS 를 쓰거나 다른 이름을 고르세요.", lab)
    e = _need(S, base, principal, actor_id, lab, [("USE CATALOG", f"catalog:{cat}"), ("USE SCHEMA", f"schema:{cat}.{sch}"), ("CREATE VOLUME", f"schema:{cat}.{sch}")])
    if e:
        return e
    _volumes(S)[fq] = {"owner": principal, "comment": comment, "created_at": core.now_utc(), "files": {}}
    S["owners"][_vol_sec(fq)] = principal
    core.audit(S, actor_id or principal, "UC_CREATE_VOLUME", _vol_sec(fq), "succeeded", "LOCAL_EXECUTED", {}, effective=principal)
    return _out(base, ["volume", "path", "result"], [[fq, f"/Volumes/{cat}/{sch}/{vol}", "생성됨"]], [SIM_NOTE], lab)


def _drop_volume(S, base, principal, actor_id, m):
    ie, name = bool(m.group(1)), m.group(2).replace("`", "")
    lab = "DROP VOLUME"
    if name not in _volumes(S):
        if ie:
            return _out(base, ["volume", "result"], [[name, "없음(건너뜀)"]], label=lab)
        return _err(S, base, principal, actor_id, "VOLUME_NOT_FOUND", f"volume `{name}` 을(를) 찾을 수 없습니다.", "SHOW VOLUMES IN catalog.schema 로 확인하세요.", lab)
    if not (core.is_admin(S, principal) or core.has_priv(S, principal, "MANAGE", _vol_sec(name)) or S["owners"].get(_vol_sec(name)) == principal or S["owners"].get(f"catalog:{name.split('.')[0]}") == principal):
        return _err(S, base, principal, actor_id, "INSUFFICIENT_PERMISSIONS", f"volume `{name}` 은(는) 소유자 또는 관리자만 삭제할 수 있습니다.", label=lab, audit=True)
    n = len(_volumes(S)[name]["files"])
    del _volumes(S)[name]
    S["owners"].pop(_vol_sec(name), None)
    S["grants"] = [g for g in S["grants"] if g[2] != _vol_sec(name)]
    core.audit(S, actor_id or principal, "UC_DROP_VOLUME", _vol_sec(name), "succeeded", "LOCAL_EXECUTED", {"files": n}, effective=principal)
    return _out(base, ["volume", "result"], [[name, f"삭제됨(파일 {n}개 포함)"]], label=lab)


def _show_volumes(S, base, principal, actor_id, m):
    name = m.group(1).replace("`", "")
    lab = "SHOW VOLUMES"
    parts = name.split(".")
    if len(parts) != 2:
        return _err(S, base, principal, actor_id, "INVALID_NAME", "SHOW VOLUMES IN catalog.schema 형식으로 쓰세요.", label=lab)
    e = _need(S, base, principal, actor_id, lab, [("USE CATALOG", f"catalog:{parts[0]}"), ("USE SCHEMA", f"schema:{name}")])
    if e:
        return e
    rows = [[k, v["owner"], len(v["files"]), v.get("comment", "")] for k, v in sorted(_volumes(S).items()) if k.rsplit(".", 1)[0] == name]
    return _out(base, ["volume", "owner", "files", "comment"], rows, label=lab)


def _vol_access(S, base, principal, actor_id, label, fq, priv):
    if fq not in _volumes(S):
        return _err(S, base, principal, actor_id, "VOLUME_NOT_FOUND", f"volume `{fq}` 을(를) 찾을 수 없습니다.", "경로는 /Volumes/catalog/schema/volume/... 형식입니다.", label)
    cat, sch, _ = fq.split(".")
    return _need(S, base, principal, actor_id, label, [("USE CATALOG", f"catalog:{cat}"), ("USE SCHEMA", f"schema:{cat}.{sch}"), (priv, _vol_sec(fq))])


def _list_path(S, base, principal, actor_id, path):
    lab = "LIST"
    sp = _split_path(path)
    if not sp:
        return _err(S, base, principal, actor_id, "INVALID_PATH", "경로는 /Volumes/catalog/schema/volume/... 형식이어야 합니다.", label=lab)
    fq, rest = sp
    e = _vol_access(S, base, principal, actor_id, lab, fq, "READ VOLUME")
    if e:
        return e
    files = _volumes(S)[fq]["files"]
    pref = rest + "/" if rest else ""
    if rest and rest in files:                                   # 파일 하나를 가리킴
        f = files[rest]
        return _out(base, ["path", "name", "size", "modification_time"], [[f"/Volumes/{fq.replace('.', '/')}/{rest}", rest.rsplit('/', 1)[-1], f["size"], f["uploaded_at"]]], label=lab)
    seen, rows = set(), []
    for rel in sorted(files):
        if not rel.startswith(pref):
            continue
        tail = rel[len(pref):]
        if "/" in tail:
            d = tail.split("/", 1)[0] + "/"
            if d in seen:
                continue
            seen.add(d)
            rows.append([f"/Volumes/{fq.replace('.', '/')}/{pref}{d}", d, 0, ""])
        else:
            f = files[rel]
            rows.append([f"/Volumes/{fq.replace('.', '/')}/{rel}", tail, f["size"], f["uploaded_at"]])
    return _out(base, ["path", "name", "size", "modification_time"], rows, label=lab)


# ---------------------------------------------------------------- COPY INTO
def _opts(txt):
    """FORMAT_OPTIONS ('a'='b', ...) → dict(소문자 키)."""
    return {k.lower(): v for k, v in re.findall(r"'([^']+)'\s*=\s*'([^']*)'", txt or "")}


def _conv(v, t):
    t = (t or "").upper()
    if v == "" or v is None:
        return None
    if "INT" in t:
        return int(v)
    if t in ("DOUBLE", "FLOAT", "REAL") or t.startswith("DECIMAL"):
        return float(v)
    if t == "BOOLEAN":
        return str(v).strip().lower() in ("true", "1", "t", "yes")
    return v


def _copy_into(S, base, principal, actor_id, m):
    lab = "COPY INTO"
    tbl = m.group(1).replace("`", "")
    path = m.group(2) or m.group(3)
    tail = m.group(4) or ""
    fmt = re.search(r"FILEFORMAT\s*=\s*(\w+)", tail, re.I)
    if not fmt or fmt.group(1).upper() != "CSV":
        return _err(S, base, principal, actor_id, "UNSUPPORTED_FILEFORMAT", "시뮬레이터는 FILEFORMAT = CSV 만 지원합니다.", "예: COPY INTO c.s.t FROM '/Volumes/c/s/v/' FILEFORMAT = CSV FORMAT_OPTIONS ('header'='true')", lab)
    fo = _opts((re.search(r"FORMAT_OPTIONS\s*\((.*?)\)", tail, re.I | re.S) or [None, ""])[1])
    co = _opts((re.search(r"COPY_OPTIONS\s*\((.*?)\)", tail, re.I | re.S) or [None, ""])[1])
    force = co.get("force", "false").lower() == "true"
    header = fo.get("header", "false").lower() == "true"
    delim = fo.get("delimiter", fo.get("sep", ","))[:1] or ","
    p3 = _parse3(tbl)
    if not p3:
        return _err(S, base, principal, actor_id, "TABLE_OR_VIEW_NOT_FOUND", f"`{tbl}`: 3단계 이름(catalog.schema.table)을 사용하세요.", label=lab)
    cat, sch, name = p3
    sp = _split_path(path)
    if not sp:
        return _err(S, base, principal, actor_id, "INVALID_PATH", "경로는 /Volumes/catalog/schema/volume/... 형식이어야 합니다.", label=lab)
    vfq, rest = sp
    e = _vol_access(S, base, principal, actor_id, lab, vfq, "READ VOLUME")
    if e:
        return e
    c = core._conns[S["id"]]
    if (cat != CAT and cat not in core.user_catalogs(S)) or not core._existsS(S, c, "table", [cat, sch, name]):
        return _err(S, base, principal, actor_id, "TABLE_OR_VIEW_NOT_FOUND", f"`{tbl}` 을(를) 찾을 수 없습니다.", "COPY INTO 는 대상 테이블이 먼저 있어야 합니다(CREATE TABLE 로 만드세요).", lab)
    fq = f"{cat}.{sch}.{name}"
    if core._is_view(c, fq, S):
        return _err(S, base, principal, actor_id, "UNSUPPORTED_SQL", f"`{fq}` 은(는) 뷰입니다. COPY INTO 대상은 테이블이어야 합니다.", label=lab)
    e = _need(S, base, principal, actor_id, lab, [("USE CATALOG", f"catalog:{cat}"), ("USE SCHEMA", f"schema:{cat}.{sch}"), ("MODIFY", f"table:{fq}")])
    if e:
        return e
    files = _volumes(S)[vfq]["files"]
    pref = rest + "/" if rest else ""
    chosen = sorted(r for r in files if r == rest or (not rest) or r.startswith(pref))
    chosen = [r for r in chosen if r.lower().endswith(".csv")] if rest not in files else chosen
    if not chosen:
        return _err(S, base, principal, actor_id, "PATH_NOT_FOUND", f"`{path}` 에 CSV 파일이 없습니다.", "LIST '/Volumes/...' 로 파일을 확인하세요.", lab)
    loaded = S.setdefault("loaded_files", {}).setdefault(fq, [])
    cols = c.execute(f"DESCRIBE {core.pfq(S, fq)}").fetchall()
    names, types = [r[0].lower() for r in cols], [r[1] for r in cols]
    todo, skipped, batches = [], 0, []
    for rel in chosen:
        key = f"vol:/Volumes/{vfq.replace('.', '/')}/{rel}:{files[rel]['sha']}"
        if key in loaded and not force:
            skipped += 1
            continue
        todo.append((rel, key))
    n_total = 0
    for rel, key in todo:
        rows = list(csv.reader(io.StringIO(files[rel]["text"].strip("﻿\r\n ")), delimiter=delim))
        if header:
            if not rows:
                continue
            h = [x.strip().lower() for x in rows[0]]
            if sorted(h) != sorted(names):
                return _err(S, base, principal, actor_id, "SCHEMA_MISMATCH", f"파일 `{rel}` 의 열({', '.join(h)})이 테이블의 열({', '.join(names)})과 다릅니다.", "열 이름을 맞추거나 테이블을 바꾸세요(시뮬레이터는 스키마 자동 확장 미지원).", lab)
            order = [h.index(n) for n in names]
            body = [[r[i] for i in order] for r in rows[1:] if len(r) == len(h)]
            bad = [i for i, r in enumerate(rows[1:], 2) if len(r) != len(h)]
        else:
            body = [r for r in rows if len(r) == len(names)]
            bad = [i for i, r in enumerate(rows, 1) if len(r) != len(names)]
        if bad:
            return _err(S, base, principal, actor_id, "MALFORMED_CSV", f"파일 `{rel}` {bad[0]}행의 열 수가 테이블({len(names)}열)과 다릅니다.", "header 옵션('header'='true')과 구분자를 확인하세요.", lab)
        try:
            batches.append((rel, key, [[_conv(v, t) for v, t in zip(r, types)] for r in body]))
        except Exception as ex:
            return _err(S, base, principal, actor_id, "EXECUTION_ERROR", f"파일 `{rel}` 값을 열 타입으로 바꾸지 못했습니다: {str(ex)[:120]}", "header 옵션이 맞는지, 숫자 열에 문자가 섞였는지 확인하세요.", lab)
    if batches:
        core._hist_ensure(S, c, fq)
        ph = ", ".join("?" for _ in names)
        try:
            for rel, key, data in batches:
                c.executemany(f"INSERT INTO {core.pfq(S, fq)} VALUES ({ph})", data)
                n_total += len(data)
                if key not in loaded:
                    loaded.append(key)
        except Exception as ex:
            return _err(S, base, principal, actor_id, "EXECUTION_ERROR", str(ex)[:300], label=lab)
        core._hist_add(S, c, fq, "COPY INTO", {"source": f"/Volumes/{vfq.replace('.', '/')}", "files": [b[0] for b in batches][:5], "format": "CSV", "force": force}, actor_id or principal)
    core.audit(S, actor_id or principal, "VOLUME_COPY_INTO", fq, "succeeded" if batches else "skipped", "LOCAL_EXECUTED", {"files": len(batches), "skipped": skipped, "rows": n_total}, effective=principal)
    note = ("이미 적재한 파일만 있어 모두 건너뛰었습니다(COPY INTO 는 멱등합니다. 다시 적재하려면 COPY_OPTIONS ('force'='true'))." if not batches else
            f"파일 {len(batches)}개를 적재했고 {skipped}개는 이미 적재되어 건너뛰었습니다.")
    return _out(base, ["num_affected_rows", "num_inserted_rows", "num_skipped_corrupt_files"], [[n_total, n_total, 0]], [note], lab)


# ---------------------------------------------------------------- GRANT/REVOKE on CATALOG|VOLUME
def _grant_ext(S, base, principal, actor_id, m):
    kind, privs, on, name, who = m.group(1).upper(), [p.strip().upper() for p in m.group(2).split(",") if p.strip()], m.group(3).upper(), m.group(4).replace("`", "").lower(), m.group(5)
    lab = kind
    if on == "CATALOG":
        if name != CAT and name not in core.user_catalogs(S) and name not in S.get("foreign_catalogs", {}):
            return _err(S, base, principal, actor_id, "TABLE_OR_VIEW_NOT_FOUND", f"catalog `{name}` 을(를) 찾을 수 없습니다.", label=lab)
        sec = f"catalog:{name}"
    else:
        if name not in _volumes(S):
            return _err(S, base, principal, actor_id, "VOLUME_NOT_FOUND", f"volume `{name}` 을(를) 찾을 수 없습니다.", label=lab)
        sec = _vol_sec(name)
    if not (core.is_admin(S, principal) or any(S["owners"].get(x) == principal for x in core.sec_chain(sec))):
        core.milestone(S, "self_grant_attempt")
        return _err(S, base, principal, actor_id, "INSUFFICIENT_PERMISSIONS", "GRANT/REVOKE는 소유자·관리자만 수행합니다. 권한 요청 티켓(UI-15)을 제출하세요.", "자기 권한 부여는 허용되지 않습니다.", lab, True)
    for p in privs:
        if kind == "GRANT":
            if [who, p, sec] not in S["grants"]:
                S["grants"].append([who, p, sec])
        else:
            S["grants"] = [g for g in S["grants"] if not (g[0] == who and g[1] == p and g[2] == sec)]
    core.audit(S, actor_id or principal, f"UC_{kind}", sec, "succeeded", "LOCAL_EXECUTED", {"privileges": privs}, effective=principal)
    return _out(base, ["securable", "principal", "privileges", "result"], [[sec, who, ", ".join(privs), "완료"]], label=lab)


# ---------------------------------------------------------------- 카탈로그 트리(Catalog Explorer)
def visible_catalog(S, principal) -> dict:
    """여러 catalog 를 함께 보여 준다. 응답은 하위 호환: catalog/schemas(교육 기본 catalog) + catalogs 배열."""
    c = core._conns[S["id"]]
    rows = c.execute("select table_schema, table_name, table_type from information_schema.tables where table_catalog=? order by 1,2", [CAT]).fetchall()
    schemata = [r[0] for r in c.execute("select schema_name from information_schema.schemata where catalog_name=?", [CAT]).fetchall()]
    cats = {CAT: {"catalog": CAT, "kind": "managed", "owner": "uc-admin", "comment": "교육 기본 catalog", "schemas": {}}}
    for k, v in core.user_catalogs(S).items():
        cats[k] = {"catalog": k, "kind": "user", "owner": v["owner"], "comment": v.get("comment", ""), "schemas": {}}

    def put(cat, sch):
        usable = core.has_priv(S, principal, "USE SCHEMA", f"schema:{cat}.{sch}") and core.has_priv(S, principal, "USE CATALOG", f"catalog:{cat}")
        return cats[cat]["schemas"].setdefault(sch, {"schema": sch, "usable": usable, "tables": [], "volumes": []})
    for psch in schemata:
        if psch in ("main", "information_schema", "pg_catalog"):
            continue
        cat, sch = (psch.split("__", 1) if "__" in psch else (CAT, psch))
        if cat in cats:
            put(cat, sch)
    for psch, tbl, tt in rows:
        cat, sch = (psch.split("__", 1) if "__" in psch else (CAT, psch))
        if cat not in cats:
            continue
        node = put(cat, sch)
        can_sel = node["usable"] and core.has_priv(S, principal, "SELECT", f"table:{cat}.{sch}.{tbl}")
        node["tables"].append({"name": tbl, "type": "VIEW" if "VIEW" in tt else "TABLE", "can_select": can_sel, "owner": S["owners"].get(f"table:{cat}.{sch}.{tbl}", "uc-admin")})
    for fq, v in sorted(_volumes(S).items()):
        cat, sch, name = fq.split(".")
        if cat in cats:
            node = put(cat, sch)
            node["volumes"].append({"name": name, "owner": v["owner"], "files": len(v["files"]), "can_read": node["usable"] and core.has_priv(S, principal, "READ VOLUME", _vol_sec(fq))})
    out = []
    for cat, d in cats.items():
        d = dict(d)
        d["usable"] = core.has_priv(S, principal, "USE CATALOG", f"catalog:{cat}")
        d["schemas"] = list(d["schemas"].values())
        out.append(d)
    fc = [{"catalog": k, "connection": v["connection"], "kind": "FOREIGN"} for k, v in S["foreign_catalogs"].items()]
    return {"catalog": CAT, "schemas": out[0]["schemas"], "catalogs": out, "foreign_catalogs": fc, "principal": principal}


# ---------------------------------------------------------------- REST
def register(app, actor_of, sess):
    def P(a):
        return core.ADMIN if a["role"] == "admin" else core.TRAINEE

    def _run(S, a, sql):
        r = core.run_sql(S, sql, P(a), via="volume", need_warehouse=False, actor_id=a["user_id"])
        core.save(S)
        return r

    def _vols_view(S, p):
        c = core._conns[S["id"]]
        vols = []
        for fq, v in sorted(_volumes(S).items()):
            cat, sch, name = fq.split(".")
            usable = core.has_priv(S, p, "USE CATALOG", f"catalog:{cat}") and core.has_priv(S, p, "USE SCHEMA", f"schema:{cat}.{sch}")
            vols.append({"volume": fq, "path": f"/Volumes/{cat}/{sch}/{name}", "owner": v["owner"], "comment": v.get("comment", ""), "created_at": v["created_at"], "files": len(v["files"]),
                         "can_read": usable and core.has_priv(S, p, "READ VOLUME", _vol_sec(fq)), "can_write": usable and core.has_priv(S, p, "WRITE VOLUME", _vol_sec(fq))})
        targets = []
        for cat in [CAT] + list(core.user_catalogs(S)):
            for (sch,) in c.execute("select schema_name from information_schema.schemata where catalog_name=?", [CAT]).fetchall():
                psch = sch
                cc, ss = (psch.split("__", 1) if "__" in psch else (CAT, psch))
                if cc != cat or ss in ("main", "information_schema", "pg_catalog"):
                    continue
                if core.has_priv(S, p, "USE CATALOG", f"catalog:{cat}") and core.has_priv(S, p, "USE SCHEMA", f"schema:{cat}.{ss}") and core.has_priv(S, p, "CREATE VOLUME", f"schema:{cat}.{ss}"):
                    targets.append(f"{cat}.{ss}")
        return {"volumes": vols, "create_targets": sorted(set(targets)), "max_file_kb": MAX_FILE // 1000, "max_files": MAX_FILES, "evidence_level": "SIMULATED", "note": SIM_NOTE}

    @app.get("/api/sessions/{sid}/volumes")
    def volumes_list(sid: str, authorization: Optional[str] = Header(None)):
        a = actor_of(authorization)
        S = sess(sid, a)
        with core.lock_for(sid):
            return _vols_view(S, P(a))

    @app.post("/api/sessions/{sid}/volumes")
    def volumes_create(sid: str, b: dict, authorization: Optional[str] = Header(None)):
        a = actor_of(authorization)
        S = sess(sid, a)
        with core.lock_for(sid):
            name = str(b.get("name", "")).strip()
            cm = str(b.get("comment", "")).replace("'", "''")[:120]
            r = _run(S, a, f"CREATE VOLUME {name}" + (f" COMMENT '{cm}'" if cm else ""))
            return {"status": r["status"], "error": r.get("error"), "rows": r.get("rows"), **_vols_view(S, P(a))}

    @app.post("/api/sessions/{sid}/volumes/delete")
    def volumes_delete(sid: str, b: dict, authorization: Optional[str] = Header(None)):
        a = actor_of(authorization)
        S = sess(sid, a)
        with core.lock_for(sid):
            r = _run(S, a, f"DROP VOLUME {str(b.get('name', '')).strip()}")
            return {"status": r["status"], "error": r.get("error"), **_vols_view(S, P(a))}

    @app.get("/api/sessions/{sid}/volumes/files")
    def volume_files(sid: str, volume: str, authorization: Optional[str] = Header(None)):
        a = actor_of(authorization)
        S = sess(sid, a)
        with core.lock_for(sid):
            r = _run(S, a, f"LIST '/Volumes/{volume.replace('.', '/')}'")
            files = [{"path": k, "size": v["size"], "uploaded_at": v["uploaded_at"], "by": v.get("by")} for k, v in sorted(_volumes(S).get(volume, {}).get("files", {}).items())] if r["status"] == "succeeded" else []
            return {"status": r["status"], "error": r.get("error"), "files": files}

    @app.post("/api/sessions/{sid}/volumes/files")
    def volume_upload(sid: str, b: dict, authorization: Optional[str] = Header(None)):
        a = actor_of(authorization)
        S = sess(sid, a)
        with core.lock_for(sid):
            vol, rel, text = str(b.get("volume", "")).strip(), str(b.get("path", "")).strip().strip("/"), str(b.get("text", ""))
            base = {"compat_notes": []}
            fail = lambda code, msg, hint=None, **kw: {"status": "failed", "error": core.sql_error(code, msg, hint, **kw)}
            if vol not in _volumes(S):
                return fail("VOLUME_NOT_FOUND", f"volume `{vol}` 을(를) 찾을 수 없습니다.")
            p = P(a)
            cat, sch, _ = vol.split(".")
            e = _need(S, base, p, a["user_id"], "UPLOAD", [("USE CATALOG", f"catalog:{cat}"), ("USE SCHEMA", f"schema:{cat}.{sch}"), ("WRITE VOLUME", _vol_sec(vol))])
            if e:
                return {"status": "failed", "error": e["error"]}
            if not re.match(r"^[A-Za-z0-9_][A-Za-z0-9_.\-/]{0,78}$", rel) or ".." in rel or "//" in rel:
                return fail("INVALID_PATH", "파일 경로는 영문·숫자·_ . - / 만 쓸 수 있고 80자 이하여야 합니다('..' 금지).")
            if len(text.encode("utf-8")) > MAX_FILE:
                return fail("FILE_TOO_LARGE", f"시뮬레이터는 파일당 {MAX_FILE // 1000}KB 이하만 받습니다.")
            files = _volumes(S)[vol]["files"]
            if rel not in files and len(files) >= MAX_FILES:
                return fail("VOLUME_FULL", f"volume 당 파일은 {MAX_FILES}개까지입니다.")
            used = sum(f["size"] for v in _volumes(S).values() for k, f in v["files"].items() if not (v is _volumes(S)[vol] and k == rel))
            if used + len(text.encode("utf-8")) > MAX_TOTAL:
                return fail("VOLUME_FULL", f"세션당 volume 파일 총량은 {MAX_TOTAL // 1_000_000}MB까지입니다(합성 데이터만 사용하세요).")
            files[rel] = {"text": text, "size": len(text.encode("utf-8")), "sha": hashlib.sha256(text.encode("utf-8")).hexdigest()[:16], "uploaded_at": core.now_utc(), "by": a["user_id"]}
            core.audit(S, a["user_id"], "VOLUME_UPLOAD", _vol_sec(vol), "succeeded", "LOCAL_EXECUTED", {"path": rel, "size": files[rel]["size"]}, effective=p)
            core.save(S)
            return {"status": "succeeded", "path": f"/Volumes/{vol.replace('.', '/')}/{rel}", "size": files[rel]["size"], "files": len(files)}

    @app.post("/api/sessions/{sid}/volumes/files/delete")
    def volume_file_delete(sid: str, b: dict, authorization: Optional[str] = Header(None)):
        a = actor_of(authorization)
        S = sess(sid, a)
        with core.lock_for(sid):
            vol, rel = str(b.get("volume", "")).strip(), str(b.get("path", "")).strip().strip("/")
            base = {}
            if vol not in _volumes(S):
                return {"status": "failed", "error": core.sql_error("VOLUME_NOT_FOUND", f"volume `{vol}` 을(를) 찾을 수 없습니다.")}
            p = P(a)
            cat, sch, _ = vol.split(".")
            e = _need(S, base, p, a["user_id"], "DELETE FILE", [("USE CATALOG", f"catalog:{cat}"), ("USE SCHEMA", f"schema:{cat}.{sch}"), ("WRITE VOLUME", _vol_sec(vol))])
            if e:
                return {"status": "failed", "error": e["error"]}
            _volumes(S)[vol]["files"].pop(rel, None)
            core.audit(S, a["user_id"], "VOLUME_FILE_DELETE", _vol_sec(vol), "succeeded", "LOCAL_EXECUTED", {"path": rel}, effective=p)
            core.save(S)
            return {"status": "succeeded", "files": len(_volumes(S)[vol]["files"])}
