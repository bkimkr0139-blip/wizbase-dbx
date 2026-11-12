"""선언형 파이프라인(Spark Declarative Pipelines) 시뮬레이션 — 스트리밍 테이블·구체화 뷰·임시 뷰·expectations·AUTO CDC(SCD Type 1).

근거: Databricks Academy 'Build data pipelines with Apache Spark Declarative Pipelines' 코스 개요(2026-11-12 Free Edition 화면 조회, 레슨 본문 미조회).
문법은 공개된 일반 지식 범위에서 '일부만' 지원한다(UNSUPPORTED_DLT_SYNTAX 로 지원 밖 문법을 알려 준다). 모든 결과는 SIMULATED/LOCAL_EXECUTED(DuckDB).

설계 요약
- 모든 데이터 접근·생성은 core.run_sql 경로(권한 검사·쿼리 이력·Delta 버전 이력 자동 유지). 만들어진 데이터셋은 일반 UC 테이블이다.
- 스트리밍 증분 = 원본 테이블의 DuckDB rowid 오프셋(마지막으로 처리한 최대 rowid). 원본이 append-only 가 아니게 바뀌면(UPDATE/DELETE/MERGE/덮어쓰기/RESTORE) 실제처럼 실패하고 full refresh 로 복구한다.
- AUTO CDC(SCD1) = 새 이벤트를 SEQUENCE BY 순으로 처리, 키별 최신 유지, 오래된 이벤트 무시, 삭제는 tombstone 시퀀스를 기억. 한 배치는 Delta 이력에 MERGE 1건으로 남긴다.
"""
from __future__ import annotations

import json
import re
import time
import uuid
from typing import Optional

import sqlglot
from sqlglot import exp
from fastapi import Header

from . import core
from .core import ApiError

EVIDENCE = "LOCAL_EXECUTED"
LIMITS = [
    "교육용 시뮬레이션입니다. 실제 Spark Declarative Pipelines(Lakeflow)와 문법·동작이 일부만 같습니다.",
    "지원: CREATE [OR REFRESH] STREAMING TABLE / MATERIALIZED VIEW / TEMPORARY VIEW, CONSTRAINT … EXPECT (…) [ON VIOLATION DROP ROW | FAIL UPDATE], AUTO CDC INTO … STORED AS SCD TYPE 1.",
    "미지원: SCD Type 2, IGNORE NULL UPDATES, 컬럼 정의/스키마 힌트, PARTITIONED BY, TBLPROPERTIES, Auto Loader(read_files), 파이프라인 설정(트리거·클러스터), 병렬 실행.",
    "스트리밍 증분은 DuckDB rowid 오프셋으로 흉내 냅니다. 업데이트당 CDC 이벤트는 500행까지 처리합니다.",
]
CHANGE_OPS = {"UPDATE", "DELETE", "MERGE", "RESTORE", "CREATE OR REPLACE TABLE AS SELECT", "CREATE OR REPLACE TABLE"}
MAX_PIPES = 5
MAX_UPDATES = 15
_NAME = re.compile(r"^[a-z][a-z0-9_]{0,40}$")

TEMPLATES = {
    "bronze_mv": {"title": "① 스트리밍 테이블 → 구체화 뷰 (+ expectations)", "needs": "orders", "sql": (
        "-- ① 원본 주문(orders_raw)을 스트리밍 테이블로 읽고, 집계는 구체화 뷰로 만듭니다.\n"
        "-- 잘못된 행: order_id 가 NULL(제외), amount <= 0(경고만).\n"
        "CREATE OR REFRESH STREAMING TABLE orders_bronze\n"
        "  (CONSTRAINT valid_order_id EXPECT (order_id IS NOT NULL) ON VIOLATION DROP ROW,\n"
        "   CONSTRAINT positive_amount EXPECT (amount > 0))\n"
        "  COMMENT '원본 주문(잘못된 행은 제외/경고)'\n"
        "AS SELECT * FROM STREAM(orders_raw);\n\n"
        "CREATE OR REFRESH MATERIALIZED VIEW store_sales\n"
        "AS SELECT store_id, count(*) AS orders, sum(amount) AS total_amount FROM orders_bronze GROUP BY store_id;\n")},
    "auto_cdc": {"title": "② AUTO CDC (SCD Type 1)", "needs": "cdc", "sql": (
        "-- ② 변경 이벤트(cdc_events)를 고객 테이블에 반영합니다(키별 최신 유지, DELETE 이벤트는 삭제).\n"
        "CREATE OR REFRESH STREAMING TABLE customers_scd1;\n\n"
        "CREATE FLOW customers_flow AS AUTO CDC INTO customers_scd1\n"
        "FROM STREAM(cdc_events)\n"
        "KEYS (id)\n"
        "APPLY AS DELETE WHEN op = 'DELETE'\n"
        "SEQUENCE BY seq\n"
        "COLUMNS * EXCEPT (op, seq)\n"
        "STORED AS SCD TYPE 1;\n")},
}


class DltError(Exception):
    def __init__(self, code, message, hint=None, line=None, **kw):
        super().__init__(message)
        self.code, self.message, self.hint, self.line, self.extra = code, message, hint, line, kw

    def as_dict(self):
        d = {"code": self.code, "message": self.message}
        if self.hint:
            d["hint"] = self.hint
        if self.line:
            d["line"] = self.line
        d.update(self.extra)
        return d


def _unsupported(msg, line):
    return DltError("UNSUPPORTED_DLT_SYNTAX", f"{line}번째 줄 근처: {msg}", "지원 문법은 화면 아래 '지원 범위'를 확인하세요. 예제 템플릿을 불러와 형식을 맞춰 보세요.", line)


# ---------------------------------------------------------------- 파서
def _strip_and_split(src: str):
    """주석(-- , /* */)을 공백으로 바꾸고(줄 번호 유지) ; 로 문장을 나눈다. [(시작 줄, 문장)]"""
    out, buf, i, n, line = [], [], 0, len(src), 1
    q = None
    start_line = None
    cur = []
    while i < n:
        ch = src[i]
        nxt = src[i + 1] if i + 1 < n else ""
        if q:
            cur.append(ch)
            if ch == q:
                if nxt == q:           # '' 이스케이프
                    cur.append(nxt); i += 1
                else:
                    q = None
            if ch == "\n":
                line += 1
        elif ch in ("'", '"', "`"):
            q = ch
            cur.append(ch)
            if start_line is None:
                start_line = line
        elif ch == "-" and nxt == "-":
            while i < n and src[i] != "\n":
                i += 1
            continue
        elif ch == "/" and nxt == "*":
            j = src.find("*/", i + 2)
            j = n if j < 0 else j + 2
            cnt = src.count("\n", i, j)
            line += cnt
            cur.append("\n" * cnt if cnt else " ")
            i = j
            continue
        elif ch == ";":
            txt = "".join(cur).strip()
            if txt:
                out.append((start_line or line, txt))
            cur, start_line = [], None
        else:
            if not ch.isspace() and start_line is None:
                start_line = line
            cur.append(ch)
            if ch == "\n":
                line += 1
        i += 1
    txt = "".join(cur).strip()
    if txt:
        out.append((start_line or line, txt))
    return out


def _balanced(text: str, start: int):
    """text[start]=='(' 에서 짝이 맞는 ')' 위치(포함 안 함 본문 끝)를 찾는다. (본문, 다음 위치)"""
    depth, i, q = 0, start, None
    while i < len(text):
        ch = text[i]
        if q:
            if ch == q:
                q = None
        elif ch in ("'", '"', "`"):
            q = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return text[start + 1:i], i + 1
        i += 1
    return None, start


def _split_top(text: str):
    parts, depth, q, cur = [], 0, None, []
    for ch in text:
        if q:
            cur.append(ch)
            if ch == q:
                q = None
            continue
        if ch in ("'", '"', "`"):
            q = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == "," and depth == 0:
            parts.append("".join(cur).strip()); cur = []
            continue
        cur.append(ch)
    if "".join(cur).strip():
        parts.append("".join(cur).strip())
    return parts


_HDR = re.compile(r"^\s*CREATE\s+(?:OR\s+REFRESH\s+|OR\s+REPLACE\s+)?(STREAMING\s+LIVE\s+TABLE|STREAMING\s+TABLE|MATERIALIZED\s+VIEW|TEMPORARY\s+STREAMING\s+VIEW|TEMPORARY\s+LIVE\s+VIEW|TEMPORARY\s+VIEW|LIVE\s+TABLE)\s+(?:IF\s+NOT\s+EXISTS\s+)?([\w.`]+)(.*)$", re.I | re.S)
_CDC = re.compile(r"^\s*(?:CREATE\s+FLOW\s+([\w`]+)\s+AS\s+)?(?:AUTO\s+CDC|APPLY\s+CHANGES)\s+INTO\s+([\w.`]+)\s+FROM\s+(.*)$", re.I | re.S)
_CON = re.compile(r"^\s*CONSTRAINT\s+(\w+)\s+EXPECT\s*\((.*)\)\s*(?:ON\s+VIOLATION\s+(DROP\s+ROW|FAIL\s+UPDATE))?\s*$", re.I | re.S)
_STREAM1 = re.compile(r"\bSTREAM\s*\(\s*([\w.`]+)\s*\)", re.I)
_STREAM2 = re.compile(r"\bSTREAM\s+([\w`][\w.`]*)", re.I)
_LIVE = re.compile(r"\bLIVE\.([\w`]+)", re.I)


def _clean_name(s: str):
    return [p.strip("`").lower() for p in s.split(".")]


def _extract_streams(select: str):
    """STREAM(x)/STREAM x 표기를 벗기고 (벗긴 SELECT, [스트림 원본 이름...])을 돌려준다. 레거시 LIVE.x → x."""
    select = _LIVE.sub(lambda m: m.group(1), select)
    names = []

    def sub1(m):
        names.append(m.group(1))
        return m.group(1)
    select = _STREAM1.sub(sub1, select)
    select = _STREAM2.sub(sub1, select)
    return select, names


def parse(source: str) -> list:
    """파이프라인 SQL → 노드 목록. 노드: {kind, name(소문자), parts, select, stream, constraints, line, declared, cdc}. 오류는 DltError."""
    nodes = []
    for line, stmt in _strip_and_split(source):
        m = _CDC.match(stmt)
        if m:
            flow, target, rest = m.group(1), m.group(2), m.group(3)
            nodes.append(_parse_cdc(flow, target, rest, line))
            continue
        m = _HDR.match(stmt)
        if not m:
            head = " ".join(stmt.split()[:4])
            raise _unsupported(f"지원하지 않는 문장입니다: `{head} …`", line)
        kw = re.sub(r"\s+", " ", m.group(1).upper())
        kind = {"STREAMING TABLE": "STREAMING_TABLE", "STREAMING LIVE TABLE": "STREAMING_TABLE", "MATERIALIZED VIEW": "MATERIALIZED_VIEW", "LIVE TABLE": "MATERIALIZED_VIEW"}.get(kw, "TEMP_VIEW")
        parts = _clean_name(m.group(2))
        rest = m.group(3)
        constraints = []
        r = rest.lstrip()
        if r.startswith("("):
            body, nxt = _balanced(r, 0)
            if body is None:
                raise _unsupported("괄호가 닫히지 않았습니다.", line)
            for item in _split_top(body):
                cm = _CON.match(item)
                if not cm:
                    raise _unsupported(f"`{item[:40]}` — 컬럼 정의/스키마 힌트는 지원하지 않습니다. CONSTRAINT 이름 EXPECT (조건) [ON VIOLATION DROP ROW | FAIL UPDATE] 만 쓸 수 있습니다.", line)
                act = re.sub(r"\s+", " ", (cm.group(3) or "").upper())
                constraints.append({"name": cm.group(1), "expr": cm.group(2).strip(), "action": {"DROP ROW": "DROP", "FAIL UPDATE": "FAIL"}.get(act, "WARN")})
            r = r[nxt:]
        r = re.sub(r"^\s*COMMENT\s+'(?:[^']|'')*'", "", r, count=1, flags=re.I)
        am = re.match(r"^\s*AS\s+(.*)$", r, re.I | re.S)
        if not am:
            if r.strip():
                raise _unsupported(f"`{r.strip()[:40]}` — 지원하지 않는 절입니다(PARTITIONED BY·TBLPROPERTIES 등 미지원).", line)
            if kind != "STREAMING_TABLE":
                raise _unsupported("AS SELECT … 가 필요합니다(대상만 선언하는 것은 스트리밍 테이블만 가능).", line)
            nodes.append({"kind": kind, "name": parts[-1], "parts": parts, "select": None, "stream": [], "constraints": constraints, "line": line, "declared": True, "cdc": None})
            continue
        body = am.group(1).strip()
        if not re.match(r"^\(?\s*(SELECT|WITH)\b", body, re.I):
            raise _unsupported("AS 뒤에는 SELECT(또는 WITH) 문이 와야 합니다.", line)
        if kind == "TEMP_VIEW" and constraints:
            raise _unsupported("임시 뷰에는 expectations를 붙일 수 없습니다.", line)
        select, streams = _extract_streams(body)
        if kind == "MATERIALIZED_VIEW" and streams:
            raise _unsupported("구체화 뷰에서는 STREAM()을 쓰지 않습니다(전체를 다시 계산합니다). 스트리밍 테이블을 쓰세요.", line)
        nodes.append({"kind": kind, "name": parts[-1], "parts": parts, "select": select, "stream": streams, "constraints": constraints, "line": line, "declared": False, "cdc": None})
    if not nodes:
        raise DltError("EMPTY_PIPELINE", "파이프라인 SQL이 비어 있습니다.", "예제 템플릿을 불러와 시작하세요.")
    return nodes


def _parse_cdc(flow, target, rest, line):
    rest = rest.strip()
    sm = re.match(r"^(?:STREAM\s*\(\s*([\w.`]+)\s*\)|STREAM\s+([\w.`]+)|([\w.`]+))\s+(.*)$", rest, re.I | re.S)
    if not sm:
        raise _unsupported("AUTO CDC INTO 대상 FROM STREAM(원본) KEYS (키) … 형식이어야 합니다.", line)
    src = sm.group(1) or sm.group(2) or sm.group(3)
    tail = sm.group(4)
    km = re.match(r"^KEYS\s*\(([^)]*)\)\s*(.*)$", tail, re.I | re.S)
    if not km:
        raise _unsupported("KEYS (컬럼, …) 절이 필요합니다.", line)
    keys = [k.strip().strip("`") for k in km.group(1).split(",") if k.strip()]
    tail = km.group(2)
    if re.search(r"IGNORE\s+NULL\s+UPDATES", tail, re.I):
        raise _unsupported("IGNORE NULL UPDATES 는 지원하지 않습니다.", line)
    st = re.search(r"STORED\s+AS\s+SCD\s+TYPE\s+(\d)", tail, re.I)
    scd = int(st.group(1)) if st else 1
    if scd != 1:
        raise _unsupported(f"SCD Type {scd} 는 지원하지 않습니다(Type 1 만).", line)
    dm = re.search(r"APPLY\s+AS\s+DELETE\s+WHEN\s+(.+?)\s+SEQUENCE\s+BY", tail, re.I | re.S)
    sq = re.search(r"SEQUENCE\s+BY\s+([\w`]+)", tail, re.I)
    if not sq:
        raise _unsupported("SEQUENCE BY 컬럼이 필요합니다.", line)
    cm = re.search(r"COLUMNS\s+(.+?)(?:\s+STORED\s+AS|$)", tail, re.I | re.S)
    cols_spec, except_cols = None, []
    if cm:
        spec = cm.group(1).strip()
        em = re.match(r"^\*\s+EXCEPT\s*\(([^)]*)\)$", spec, re.I | re.S)
        if em:
            except_cols = [c.strip().strip("`") for c in em.group(1).split(",") if c.strip()]
        elif spec == "*":
            pass
        else:
            cols_spec = [c.strip().strip("`") for c in spec.split(",") if c.strip()]
    left = tail
    for pat in (r"APPLY\s+AS\s+DELETE\s+WHEN\s+.+?\s+(?=SEQUENCE\s+BY)", r"SEQUENCE\s+BY\s+[\w`]+", r"COLUMNS\s+.+?(?=\s+STORED\s+AS|$)", r"STORED\s+AS\s+SCD\s+TYPE\s+\d"):
        left = re.sub(pat, " ", left, count=1, flags=re.I | re.S)
    if left.strip():
        raise _unsupported(f"`{left.strip()[:40]}` — 알 수 없는 절입니다.", line)
    parts = _clean_name(target)
    return {"kind": "CDC_FLOW", "name": parts[-1], "parts": parts, "select": None, "stream": [src], "constraints": [], "line": line, "declared": False, "flow": flow,
            "cdc": {"source": src, "keys": keys, "delete_when": dm.group(1).strip() if dm else None, "seq": sq.group(1).strip("`"), "columns": cols_spec, "except": except_cols}}


# ---------------------------------------------------------------- 계획(데이터셋·의존 그래프)
def _resolve(pipe, parts):
    parts = [p.lower() for p in parts]
    if len(parts) == 1:
        return f"{pipe['catalog']}.{pipe['schema']}.{parts[0]}"
    if len(parts) == 2:
        return f"{pipe['catalog']}.{parts[0]}.{parts[1]}"
    return ".".join(parts[-3:])


def build_plan(pipe) -> dict:
    nodes = parse(pipe["source"])
    ds, temps, flows = {}, {}, []
    for nd in nodes:
        if nd["kind"] == "CDC_FLOW":
            flows.append(nd)
            continue
        if len(nd["parts"]) > 1 and _resolve(pipe, nd["parts"]) != _resolve(pipe, [nd["name"]]):
            raise DltError("DLT_TARGET_OUTSIDE_SCHEMA", f"{nd['line']}번째 줄: `{'.'.join(nd['parts'])}` — 파이프라인 대상 schema({pipe['catalog']}.{pipe['schema']}) 밖에는 만들 수 없습니다.", "이름만 쓰거나 대상 schema와 같은 이름을 쓰세요.", nd["line"])
        key = nd["name"]
        if key in ds or key in temps:
            raise DltError("DLT_DUPLICATE_DATASET", f"{nd['line']}번째 줄: 데이터셋 `{key}`이(가) 두 번 정의되었습니다.", "이름을 바꾸거나 하나를 지우세요.", nd["line"])
        nd["fq"] = _resolve(pipe, [key])
        (temps if nd["kind"] == "TEMP_VIEW" else ds)[key] = nd
    for fl in flows:
        key = fl["name"]
        t = ds.get(key)
        if t is None:
            t = {"kind": "STREAMING_TABLE", "name": key, "parts": [key], "select": None, "stream": [], "constraints": [], "line": fl["line"], "declared": True, "cdc": None, "fq": _resolve(pipe, [key]), "auto_declared": True}
            ds[key] = t
        if t["kind"] != "STREAMING_TABLE":
            raise DltError("DLT_CDC_TARGET_INVALID", f"{fl['line']}번째 줄: AUTO CDC 대상 `{key}`은(는) 스트리밍 테이블이어야 합니다.", None, fl["line"])
        if t.get("cdc") or t["select"]:
            raise DltError("DLT_DUPLICATE_DATASET", f"{fl['line']}번째 줄: `{key}`은(는) 이미 쿼리 또는 다른 흐름이 있습니다(한 대상에 하나의 흐름만 지원).", None, fl["line"])
        t["cdc"] = fl["cdc"]
        t["flow"] = fl.get("flow")
        t["stream"] = [fl["cdc"]["source"]]
    plan = {"datasets": ds, "temps": temps}
    # 의존 관계
    fqmap = {d["fq"]: k for k, d in ds.items()}
    for k, d in ds.items():
        if d["cdc"]:
            refs = {_resolve(pipe, _clean_name(d["cdc"]["source"]))}
            used = set(refs)
        elif d["select"]:
            _, refs, used = render(pipe, plan, d, None)
            if d["kind"] == "STREAMING_TABLE" and not used:
                raise DltError("UNSUPPORTED_DLT_SYNTAX", f"{d['line']}번째 줄: 스트리밍 테이블 `{k}`은(는) FROM STREAM(원본) 이 필요합니다.", "STREAM(원본테이블)로 읽거나 구체화 뷰로 바꾸세요.", d["line"])
        else:
            refs, used = set(), set()
        d["refs"], d["stream_fqs"] = sorted(refs), sorted(used)
        d["deps"] = sorted({fqmap[r] for r in refs if r in fqmap and fqmap[r] != k})
        for sf in used:
            sd = fqmap.get(sf)
            if sd and ds[sd]["kind"] == "MATERIALIZED_VIEW":
                raise DltError("STREAM_FROM_MATERIALIZED_VIEW", f"{d['line']}번째 줄: 구체화 뷰 `{sd}`은(는) 스트리밍 원본이 될 수 없습니다(append-only 가 아님).", "스트리밍 테이블을 원본으로 쓰세요.", d["line"])
        if d["declared"] and not d["cdc"]:
            d["note"] = "대상만 선언되고 AUTO CDC 흐름이 없어 비어 있습니다."
    # 위상 정렬(정의 순서 유지)
    order, done, temp_mark = [], set(), set()

    def visit(n, stack):
        if n in done:
            return
        if n in stack:
            cyc = stack[stack.index(n):] + [n]
            raise DltError("DLT_CYCLE", "데이터셋 순환 의존: " + " → ".join(cyc), "순환이 없도록 한 데이터셋의 원본을 바꾸세요.")
        for dep in ds[n]["deps"]:
            visit(dep, stack + [n])
        done.add(n)
        order.append(n)
    for k in ds:
        visit(k, [])
    plan["order"] = order
    return plan


def _parse_select(text, line=None):
    try:
        return sqlglot.parse_one(text, read="databricks")
    except Exception as e:
        raise DltError("PARSE_ERROR", f"SELECT 구문 분석 실패: {str(e)[:160]}", "SELECT 문의 괄호·쉼표·키워드 철자를 확인하세요.", line)


def render(pipe, plan, ds, bounds, _depth=0):
    """데이터셋 SELECT → (3단계 이름으로 정규화한 SQL, 참조 fq 집합, 스트림 원본 fq 집합). bounds={fq:(lo,hi)} 이면 스트림 원본을 rowid 구간 서브쿼리로 바꾼다."""
    if _depth > 8:
        raise DltError("DLT_CYCLE", "임시 뷰 참조가 너무 깊습니다(순환 가능).")
    tree = _parse_select(ds["select"], ds.get("line"))
    cte = {c.alias_or_name.lower() for c in tree.find_all(exp.CTE)}
    streams = {_resolve(pipe, _clean_name(n)) for n in ds["stream"]}
    refs, used = set(), set()
    for t in list(tree.find_all(exp.Table)):
        if not t.name:
            continue
        if t.name.lower() in cte and not t.db:
            continue
        parts = [p for p in (t.catalog, t.db, t.name) if p]
        nm = parts[-1].lower()
        alias = t.alias or t.name
        if len(parts) == 1 and nm in plan["temps"]:
            inner_sql, r2, u2 = render(pipe, plan, plan["temps"][nm], bounds, _depth + 1)
            refs |= r2
            used |= u2
            sub = exp.Subquery(this=_parse_select(inner_sql), alias=exp.TableAlias(this=exp.to_identifier(alias)))
            t.replace(sub)
            continue
        fq = _resolve(pipe, parts)
        refs.add(fq)
        if fq in streams:
            used.add(fq)
            if bounds is not None and fq in bounds:
                lo, hi = bounds[fq]
                sub = exp.Subquery(this=_parse_select(f"SELECT * FROM {fq} WHERE rowid > {lo} AND rowid <= {hi}"), alias=exp.TableAlias(this=exp.to_identifier(alias)))
                t.replace(sub)
                continue
        c, d_, n_ = fq.split(".")
        t.set("catalog", exp.to_identifier(c))
        t.set("db", exp.to_identifier(d_))
        t.set("this", exp.to_identifier(n_))
        if not t.alias:
            t.set("alias", exp.TableAlias(this=exp.to_identifier(alias)))
    return tree.sql(dialect="databricks"), refs, used


# ---------------------------------------------------------------- 실행
def _lit(v):
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, (int, float)):
        return repr(v)
    return core.sql_str(v)


class _Ctx:
    def __init__(self, S, actor, principal):
        self.S, self.actor, self.principal = S, actor, principal
        self.c = core._conns[S["id"]]

    def q(self, sql, system=True):
        r = core.run_sql(self.S, sql, self.principal, via="dlt", system=system, need_warehouse=False, actor_id=self.actor["user_id"])
        if r["status"] != "succeeded":
            e = r.get("error") or {}
            raise DltError(e.get("code", "EXECUTION_ERROR"), e.get("message", "실행 실패"), e.get("hint"), None, **({"missing": e["missing"]} if e.get("missing") else {}))
        return r

    def count(self, sql):
        return int(self.q(f"SELECT count(*) FROM ({sql}) AS _t").get("rows")[0][0])

    def exists(self, fq):
        r = core.run_sql(self.S, f"SELECT count(*) FROM {fq}", self.principal, via="dlt", system=True, need_warehouse=False, actor_id=self.actor["user_id"])
        return r["status"] == "succeeded"

    def max_rowid(self, fq):
        return int(self.q(f"SELECT coalesce(max(rowid), -1) FROM {fq}").get("rows")[0][0])

    def version(self, fq):
        core._hist_ensure(self.S, self.c, fq)
        h = core._thist(self.S).get(fq) or []
        return h[-1]["version"] if h else 0

    def changed_since(self, fq, v_last):
        """v_last 이후 append-only 가 아닌 변경이 있었는지 → (변경 여부, 연산명)"""
        core._hist_ensure(self.S, self.c, fq)
        h = core._thist(self.S).get(fq) or []
        if not h or h[-1]["version"] < v_last:
            return True, "테이블 재생성(이력 초기화)"
        for x in h:
            if x["version"] > v_last and x["operation"] in CHANGE_OPS:
                return True, x["operation"]
        return False, None


def _state(pipe):
    return pipe.setdefault("state", {"offsets": {}, "versions": {}, "cdc": {}, "created": {}})


def _check_source(ctx, st, dsname, sfq, full):
    """스트림 원본 검사 → (lo, hi). 원본이 append-only 가 아니게 바뀌었으면 DltError."""
    if not ctx.exists(sfq):
        # run_sql 오류를 그대로 보여 주기 위해 다시 실행
        ctx.q(f"SELECT count(*) FROM {sfq}")
    try:
        if core._is_view(ctx.c, core.pfq(ctx.S, sfq)):
            raise DltError("STREAMING_SOURCE_INVALID", f"`{sfq}`은(는) 뷰입니다. 스트리밍 원본은 테이블이어야 합니다.", "원본 테이블을 가리키세요.")
    except DltError:
        raise
    except Exception:
        pass
    offs = st["offsets"].setdefault(dsname, {})
    vers = st["versions"].setdefault(dsname, {})
    if full or sfq not in offs:
        lo = -1
    else:
        lo = offs[sfq]
        ch, op = ctx.changed_since(sfq, vers.get(sfq, 0))
        if ch:
            raise DltError("STREAMING_SOURCE_CHANGED", f"스트리밍 원본 `{sfq}`에 append-only 가 아닌 변경({op})이 있었습니다.", "원본의 UPDATE/DELETE/덮어쓰기/RESTORE 는 스트리밍 테이블이 처리할 수 없습니다. '전체 새로고침(full refresh)'으로 다시 만드세요.", None, source=sfq, operation=op)
    hi = ctx.max_rowid(sfq)
    return lo, hi


def _evaluate_expectations(ctx, sel_sql, constraints):
    """→ (final_sql, rows_in, 지표목록). FAIL 위반이면 DltError."""
    rows_in = ctx.count(sel_sql)
    metrics, drops = [], []
    for c in constraints:
        failed = ctx.count(f"SELECT * FROM ({sel_sql}) AS _t WHERE NOT coalesce(({c['expr']}), false)") if rows_in else 0
        metrics.append({"name": c["name"], "expr": c["expr"], "action": c["action"], "total": rows_in, "failed": failed, "passed": rows_in - failed})
        if c["action"] == "FAIL" and failed:
            raise DltError("EXPECTATION_FAILED", f"expectation `{c['name']}` 위반 {failed}행 — ON VIOLATION FAIL UPDATE 로 업데이트를 중단했습니다.", "데이터를 고치거나 조치를 DROP ROW/경고로 바꾸세요.", None, metrics=metrics)
        if c["action"] == "DROP":
            drops.append(f"coalesce(({c['expr']}), false)")
    final = f"SELECT * FROM ({sel_sql}) AS _t WHERE " + " AND ".join(drops) if drops else sel_sql
    return final, rows_in, metrics


def _run_dataset(ctx, pipe, plan, name, full, ev):
    d = plan["datasets"][name]
    st = _state(pipe)
    fq = d["fq"]
    if d["cdc"]:
        return _run_cdc(ctx, pipe, d, full, ev)
    if d["select"] is None:
        ev["state"], ev["note"] = "COMPLETED", d.get("note", "쿼리가 없어 만들지 않았습니다.")
        return
    if d["kind"] == "MATERIALIZED_VIEW":
        sel, _, _ = render(pipe, plan, d, None)
        final, rows_in, metrics = _evaluate_expectations(ctx, sel, d["constraints"])
        ev["rows_in"], ev["expectations"] = rows_in, metrics
        ctx.q(f"CREATE OR REPLACE TABLE {fq} AS {final}", system=False)
        ev["rows_out"] = ctx.count(f"SELECT * FROM {fq}")
        ev["note"] = "전체 재계산(구체화 뷰)"
        st["created"][name] = True
        return
    # 스트리밍 테이블
    first = full or not st["created"].get(name) or not ctx.exists(fq)
    bounds, newrows = {}, 0
    for sfq in d["stream_fqs"]:
        lo, hi = _check_source(ctx, st, name, sfq, first)
        bounds[sfq] = (lo, hi)
        newrows += max(0, hi - lo)
    ev["bounds"] = {k: [v[0], v[1]] for k, v in bounds.items()}
    if not first and newrows == 0:
        ev["rows_in"], ev["rows_out"], ev["note"] = 0, ctx.count(f"SELECT * FROM {fq}"), "처리할 새 행이 없습니다(증분 0행)."
        return
    sel, _, _ = render(pipe, plan, d, bounds)
    final, rows_in, metrics = _evaluate_expectations(ctx, sel, d["constraints"])
    ev["rows_in"], ev["expectations"] = rows_in, metrics
    if first:
        ctx.q(f"CREATE OR REPLACE TABLE {fq} AS {final}", system=False)
        ev["note"] = "첫 업데이트: 원본 전체를 읽어 만들었습니다." + (" (full refresh)" if full else "")
    else:
        ctx.q(f"INSERT INTO {fq} {final}", system=False)
        ev["note"] = f"증분: 새 행 {newrows}개만 처리했습니다."
    ev["rows_out"] = ctx.count(f"SELECT * FROM {fq}")
    ev["dropped"] = rows_in - ctx.count(final) if d["constraints"] else 0
    for sfq, (lo, hi) in bounds.items():
        st["offsets"].setdefault(name, {})[sfq] = hi
        st["versions"].setdefault(name, {})[sfq] = ctx.version(sfq)
    st["created"][name] = True


def _cmp(a, b):
    try:
        return (a > b) - (a < b)
    except TypeError:
        a, b = str(a), str(b)
        return (a > b) - (a < b)


def _run_cdc(ctx, pipe, d, full, ev):
    st = _state(pipe)
    name, fq, cdc = d["name"], d["fq"], d["cdc"]
    sfq = _resolve(pipe, _clean_name(cdc["source"]))
    first = full or not st["created"].get(name) or not ctx.exists(fq)
    lo, hi = _check_source(ctx, st, name, sfq, first)
    cs = st["cdc"].setdefault(name, {"seq": {}})
    if first:
        cs["seq"] = {}
    ev["bounds"] = {sfq: [lo, hi]}
    n_new = max(0, hi - lo)
    if n_new > 500:
        raise DltError("DLT_BATCH_TOO_LARGE", f"한 업데이트에서 처리할 CDC 이벤트가 {n_new}행으로 500행을 넘습니다.", "원본을 나눠 넣거나 시뮬레이터 한계(500행)를 고려해 줄이세요.")
    probe = ctx.q(f"SELECT * FROM {sfq} WHERE rowid < 0")
    cols_all = probe["columns"]
    for k in cdc["keys"] + [cdc["seq"]]:
        if k not in cols_all:
            raise DltError("COLUMN_NOT_FOUND", f"컬럼 `{k}`이(가) 원본 `{sfq}`에 없습니다(있는 컬럼: {', '.join(cols_all)}).", "KEYS/SEQUENCE BY 컬럼 이름을 확인하세요.")
    out_cols = cdc["columns"] or [c for c in cols_all if c not in set(cdc["except"])]
    for c in out_cols:
        if c not in cols_all:
            raise DltError("COLUMN_NOT_FOUND", f"컬럼 `{c}`이(가) 원본에 없습니다.", None)
    for k in cdc["keys"]:
        if k not in out_cols:
            raise DltError("DLT_CDC_KEY_EXCLUDED", f"키 컬럼 `{k}`은(는) 결과 컬럼에 포함되어야 합니다.", "EXCEPT 목록에서 키를 빼세요.")
    dcol = f"coalesce(({cdc['delete_when']}), false)" if cdc["delete_when"] else "false"
    created = False
    if first:
        ctx.q(f"CREATE OR REPLACE TABLE {fq} AS SELECT {', '.join(out_cols)} FROM {sfq} WHERE rowid < 0", system=False)
        created = True
    rows = ctx.q(f"SELECT {', '.join(cols_all)}, {dcol} AS __del FROM {sfq} WHERE rowid > {lo} AND rowid <= {hi} ORDER BY {cdc['seq']}")
    names = rows["columns"]
    ki = [names.index(k) for k in cdc["keys"]]
    si, di = names.index(cdc["seq"]), names.index("__del")
    actions, skipped = {}, 0
    for r in rows["rows"]:
        key = json.dumps([r[i] for i in ki], ensure_ascii=False, default=str)
        seq = r[si]
        if seq is None:
            skipped += 1                      # 시퀀스가 NULL 인 이벤트는 순서를 알 수 없어 무시(실제 AUTO CDC 도 SEQUENCE BY 가 NULL 이면 안 됨)
            continue
        prev = cs["seq"].get(key)
        if prev is not None and _cmp(seq, prev["seq"]) <= 0:
            skipped += 1                      # 이미 반영한 시퀀스보다 오래된(또는 같은) 이벤트 → 무시
            continue
        if r[di]:
            actions[key] = ("delete", None)
            cs["seq"][key] = {"seq": seq, "deleted": True}
        else:
            actions[key] = ("upsert", {c: r[names.index(c)] for c in out_cols})
            cs["seq"][key] = {"seq": seq, "deleted": False}
    ups = [v[1] for v in actions.values() if v[0] == "upsert"]
    dels = [k for k, v in actions.items() if v[0] == "delete"]
    touched = list(actions)
    if touched:
        conds = []
        for key in touched:
            kv = json.loads(key)
            conds.append("(" + " AND ".join(f"{k} = {_lit(v)}" for k, v in zip(cdc["keys"], kv)) + ")")
        if ups:
            core.hop(ctx.S, skip=True)
        else:
            core.hop(ctx.S, op="MERGE")
        ctx.q(f"DELETE FROM {fq} WHERE " + " OR ".join(conds), system=False)
        if ups:
            vals = ", ".join("(" + ", ".join(_lit(u[c]) for c in out_cols) + ")" for u in ups)
            core.hop(ctx.S, op="MERGE")
            ctx.q(f"INSERT INTO {fq} ({', '.join(out_cols)}) VALUES {vals}", system=False)
    ev["rows_in"], ev["rows_out"] = len(rows["rows"]), ctx.count(f"SELECT * FROM {fq}")
    ev["cdc"] = {"events": len(rows["rows"]), "upserts": len(ups), "deletes": len(dels), "ignored_old": skipped, "keys_tracked": len(cs["seq"])}
    ev["note"] = ("첫 업데이트(대상 생성). " if created else "") + f"이벤트 {len(rows['rows'])}건 → 반영(업서트 {len(ups)}·삭제 {len(dels)}), 오래된 이벤트 {skipped}건 무시."
    st["offsets"].setdefault(name, {})[sfq] = hi
    st["versions"].setdefault(name, {})[sfq] = ctx.version(sfq)
    st["created"][name] = True


def run_update(S, actor, principal, pipe, mode="update") -> dict:
    full = mode == "full_refresh"
    t0 = time.time()
    upd = {"id": "u_" + uuid.uuid4().hex[:8], "at": core.now_utc(), "mode": "full_refresh" if full else "update", "state": "COMPLETED", "error": None, "events": [], "principal": principal, "datasets": []}
    st = _state(pipe)
    try:
        plan = build_plan(pipe)
    except DltError as e:
        upd.update(state="FAILED", error=e.as_dict())
        upd["duration_ms"] = int((time.time() - t0) * 1000)
        _push(pipe, upd)
        return upd
    if full:
        pipe["state"] = {"offsets": {}, "versions": {}, "cdc": {}, "created": {}}
        st = pipe["state"]
    ctx = _Ctx(S, actor, principal)
    failed = False
    for name in plan["order"]:
        d = plan["datasets"][name]
        ev = {"dataset": name, "fq": d["fq"], "kind": d["kind"] if not d["cdc"] else "STREAMING_TABLE(AUTO CDC)", "state": "SKIPPED", "rows_in": None, "rows_out": None, "expectations": [], "note": "", "at": core.now_utc()}
        upd["events"].append(ev)
        if failed:
            ev["note"] = "앞선 데이터셋 실패로 건너뜀"
            continue
        try:
            ev["state"] = "RUNNING"
            _run_dataset(ctx, pipe, plan, name, full, ev)
            ev["state"] = "COMPLETED"
        except DltError as e:
            failed = True
            ev["state"] = "FAILED"
            ev["error"] = e.as_dict()
            if e.extra.get("metrics"):
                ev["expectations"] = e.extra["metrics"]
            upd["state"], upd["error"] = "FAILED", {**e.as_dict(), "dataset": name}
        except ApiError as e:  # pragma: no cover
            failed = True
            ev["state"], ev["error"] = "FAILED", {"code": e.code, "message": e.message}
            upd["state"], upd["error"] = "FAILED", {"code": e.code, "message": e.message, "dataset": name}
    upd["datasets"] = summarize(ctx, pipe, plan)
    upd["duration_ms"] = int((time.time() - t0) * 1000)
    _push(pipe, upd)
    core.audit(S, actor["user_id"], "DLT_UPDATE", pipe["id"], "succeeded" if not failed else "failed", EVIDENCE, {"mode": upd["mode"], "datasets": len(plan["order"])}, effective=principal)
    return upd


def _push(pipe, upd):
    pipe.setdefault("updates", []).append(upd)
    del pipe["updates"][:-MAX_UPDATES]
    pipe["updated_at"] = core.now_utc()


def summarize(ctx, pipe, plan):
    out = []
    last = {}
    for u in reversed(pipe.get("updates", [])):
        for e in u.get("events", []):
            last.setdefault(e["dataset"], e)
    for name in plan["order"]:
        d = plan["datasets"][name]
        rows = None
        if d["select"] is not None or d["cdc"]:
            try:
                rows = ctx.count(f"SELECT * FROM {d['fq']}") if ctx.exists(d["fq"]) else None
            except DltError:
                rows = None
        e = last.get(name) or {}
        out.append({"name": name, "fq": d["fq"], "kind": "STREAMING_TABLE(AUTO CDC)" if d["cdc"] else d["kind"], "deps": d["deps"], "stream": [s for s in d["stream_fqs"]], "rows": rows, "state": e.get("state"),
                    "expectations": e.get("expectations", []), "note": e.get("note") or d.get("note", ""), "constraints": len(d["constraints"])})
    for k, t in plan["temps"].items():
        out.append({"name": k, "fq": None, "kind": "TEMP_VIEW", "deps": [], "stream": [], "rows": None, "state": "INLINE", "expectations": [], "note": "게시되지 않는 임시 뷰(참조하는 데이터셋 안에 펼쳐짐)", "constraints": 0})
    return out


def plan_view(pipe) -> dict:
    """저장된 파이프라인의 계획(그래프). 문법 오류는 error 로 돌려준다."""
    try:
        plan = build_plan(pipe)
    except DltError as e:
        return {"ok": False, "error": e.as_dict()}
    nodes = [{"name": n, "kind": "STREAMING_TABLE(AUTO CDC)" if plan["datasets"][n]["cdc"] else plan["datasets"][n]["kind"], "fq": plan["datasets"][n]["fq"], "deps": plan["datasets"][n]["deps"], "stream": plan["datasets"][n]["stream_fqs"],
              "constraints": [{"name": c["name"], "expr": c["expr"], "action": c["action"]} for c in plan["datasets"][n]["constraints"]], "line": plan["datasets"][n]["line"]} for n in plan["order"]]
    nodes += [{"name": k, "kind": "TEMP_VIEW", "fq": None, "deps": [], "stream": [], "constraints": [], "line": t["line"]} for k, t in plan["temps"].items()]
    return {"ok": True, "order": plan["order"], "nodes": nodes}


# ---------------------------------------------------------------- 샘플 원본
def _orders_batch(n):
    """n 번째 배치(0=처음). 잘못된 행(NULL id·음수 금액)을 일부러 섞는다."""
    base = n * 10
    rows = [(f"O-{base + 1}", "S01", 1200, "PAID"), (f"O-{base + 2}", "S02", 800, "PAID"), (None, "S01", 500, "PAID"), (f"O-{base + 4}", "S03", -100, "REFUND"),
            (f"O-{base + 5}", "S02", 450, "PAID")] if n == 0 else [(f"O-{base + 1}", "S01", 700, "PAID"), (None, "S03", 300, "PAID"), (f"O-{base + 3}", "S02", 0, "PAID")]
    return rows


def _cdc_batch(n):
    if n == 0:
        return [(1, "Kim", "Seoul", "UPSERT", 1), (2, "Lee", "Busan", "UPSERT", 2), (3, "Park", "Daegu", "UPSERT", 3), (4, "Choi", "Incheon", "UPSERT", 4),
                (2, "Lee", "Jeju", "UPSERT", 5), (3, "Park", "Daegu", "DELETE", 6)]
    return [(2, "Lee", "Ulsan", "UPSERT", 3),            # 이미 반영한 시퀀스(5)보다 오래됨 → 무시
            (1, "Kim", "Suwon", "UPSERT", 7), (5, "Jung", "Gwangju", "UPSERT", 8), (4, "Choi", "Incheon", "DELETE", 9),
            (3, "Park", "Seoul", "UPSERT", 5)]          # 삭제(시퀀스 6)보다 오래된 늦은 이벤트 → 되살리지 못함


def make_sample(ctx, S, kind, catalog, schema, append):
    key = f"{catalog}.{schema}.{'orders_raw' if kind == 'orders' else 'cdc_events'}"
    cnt = S.setdefault("dpipe_samples", {})
    exists = ctx.exists(key)
    if append and not exists:
        raise DltError("TABLE_OR_VIEW_NOT_FOUND", f"원본 `{key}`이(가) 없습니다.", "먼저 '샘플 원본 만들기'를 누르세요.")
    n = cnt.get(key, -1) + 1 if (append or exists) else 0
    if exists and not append:
        raise DltError("TABLE_ALREADY_EXISTS", f"`{key}`이(가) 이미 있습니다.", "'추가 배치 넣기'로 새 행을 넣거나 SQL Editor에서 지우세요.")
    if kind == "orders":
        rows, cols = _orders_batch(n), ("order_id", "store_id", "amount", "status")
        sel = " UNION ALL ".join("SELECT " + ", ".join(f"CAST({_lit(v)} AS {t}) AS {c}" for v, c, t in zip(r, cols, ("VARCHAR", "VARCHAR", "BIGINT", "VARCHAR"))) for r in rows)
    else:
        rows, cols = _cdc_batch(n), ("id", "name", "city", "op", "seq")
        sel = " UNION ALL ".join("SELECT " + ", ".join(f"CAST({_lit(v)} AS {t}) AS {c}" for v, c, t in zip(r, cols, ("BIGINT", "VARCHAR", "VARCHAR", "VARCHAR", "BIGINT"))) for r in rows)
    if n == 0:
        ctx.q(f"CREATE TABLE {key} AS {sel}", system=False)
    else:
        ctx.q(f"INSERT INTO {key} {sel}", system=False)
    cnt[key] = n
    return {"table": key, "batch": n, "rows": len(rows)}


# ---------------------------------------------------------------- 엔드포인트
def _summary(p):
    last = (p.get("updates") or [None])[-1]
    return {"id": p["id"], "name": p["name"], "catalog": p["catalog"], "schema": p["schema"], "updated_at": p.get("updated_at"), "last_state": last["state"] if last else None, "last_at": last["at"] if last else None, "updates": len(p.get("updates", []))}


def register(app, actor_of, sess):
    def _pipes(S):
        return S.setdefault("dpipes", {})

    def _principal(a):
        return core.ADMIN if a["role"] == "admin" else core.TRAINEE

    def _get(S, pid):
        p = _pipes(S).get(pid)
        if not p:
            raise ApiError(404, "PIPELINE_NOT_FOUND", "파이프라인을 찾을 수 없습니다.")
        return p

    def _check_def(b, S, cur=None):
        name = str(b.get("name", cur["name"] if cur else "")).strip()
        catalog = str(b.get("catalog", cur["catalog"] if cur else core.CAT)).strip().lower()
        schema = str(b.get("schema", cur["schema"] if cur else "gold")).strip().lower()
        source = str(b.get("source", cur["source"] if cur else ""))
        if not _NAME.match(name.lower().replace("-", "_")) or len(name) > 41:
            raise ApiError(400, "INVALID_NAME", "파이프라인 이름은 영문 소문자로 시작하고 영문·숫자·_ 로 41자 이하여야 합니다.")
        if not _NAME.match(catalog) or not _NAME.match(schema):
            raise ApiError(400, "INVALID_NAME", "catalog/schema 이름이 올바르지 않습니다.")
        if len(source) > 20000:
            raise ApiError(400, "TOO_LARGE", "파이프라인 SQL은 20,000자까지입니다.")
        return name.lower(), catalog, schema, source

    @app.get("/api/sessions/{sid}/dpipes")
    def dpipes_list(sid: str, authorization: Optional[str] = Header(None)):
        S = sess(sid, actor_of(authorization))
        with core.lock_for(sid):
            return {"pipelines": [_summary(p) for p in _pipes(S).values()], "templates": TEMPLATES, "limits": LIMITS, "evidence_level": EVIDENCE, "default": {"catalog": core.CAT, "schema": "gold"}}

    @app.post("/api/sessions/{sid}/dpipes")
    def dpipes_create(sid: str, b: dict, authorization: Optional[str] = Header(None)):
        a = actor_of(authorization)
        S = sess(sid, a)
        with core.lock_for(sid):
            if len(_pipes(S)) >= MAX_PIPES:
                raise ApiError(429, "PIPELINE_LIMIT", f"파이프라인은 세션당 {MAX_PIPES}개까지입니다.")
            name, catalog, schema, source = _check_def(b, S)
            if any(p["name"] == name for p in _pipes(S).values()):
                raise ApiError(409, "PIPELINE_EXISTS", f"`{name}` 파이프라인이 이미 있습니다.")
            p = {"id": "dp_" + uuid.uuid4().hex[:8], "name": name, "catalog": catalog, "schema": schema, "source": source, "created_by": a["user_id"], "created_at": core.now_utc(), "updated_at": core.now_utc(), "updates": [], "state": {"offsets": {}, "versions": {}, "cdc": {}, "created": {}}}
            _pipes(S)[p["id"]] = p
            core.save(S)
            return {**_summary(p), "plan": plan_view(p)}

    @app.get("/api/sessions/{sid}/dpipes/{pid}")
    def dpipes_get(sid: str, pid: str, authorization: Optional[str] = Header(None)):
        a = actor_of(authorization)
        S = sess(sid, a)
        with core.lock_for(sid):
            p = _get(S, pid)
            plan = plan_view(p)
            datasets = []
            if plan["ok"]:
                ctx = _Ctx(S, a, _principal(a))
                try:
                    datasets = summarize(ctx, p, build_plan(p))
                except Exception:
                    datasets = []
            return {"pipeline": {k: v for k, v in p.items() if k not in ("updates", "state")}, "plan": plan, "datasets": datasets, "updates": list(reversed(p.get("updates", [])))[:8],
                    "state_offsets": p["state"]["offsets"], "evidence_level": EVIDENCE, "limits": LIMITS}

    @app.post("/api/sessions/{sid}/dpipes/{pid}/save")
    def dpipes_save(sid: str, pid: str, b: dict, authorization: Optional[str] = Header(None)):
        a = actor_of(authorization)
        S = sess(sid, a)
        with core.lock_for(sid):
            p = _get(S, pid)
            name, catalog, schema, source = _check_def(b, S, p)
            if (catalog, schema) != (p["catalog"], p["schema"]) and p.get("updates"):
                raise ApiError(409, "TARGET_LOCKED", "업데이트를 실행한 뒤에는 대상 schema를 바꿀 수 없습니다. 새 파이프라인을 만드세요.")
            p.update(name=name, catalog=catalog, schema=schema, source=source, updated_at=core.now_utc())
            core.save(S)
            return {**_summary(p), "plan": plan_view(p)}

    @app.post("/api/sessions/{sid}/dpipes/{pid}/delete")
    def dpipes_delete(sid: str, pid: str, authorization: Optional[str] = Header(None)):
        S = sess(sid, actor_of(authorization))
        with core.lock_for(sid):
            _get(S, pid)
            del _pipes(S)[pid]
            core.save(S)
            return {"deleted": pid, "note": "만들어진 테이블은 남아 있습니다(실제 파이프라인 삭제와 같음). 필요하면 SQL Editor에서 지우세요."}

    @app.post("/api/sessions/{sid}/dpipes/{pid}/run")
    def dpipes_run(sid: str, pid: str, b: dict, authorization: Optional[str] = Header(None)):
        a = actor_of(authorization)
        S = sess(sid, a)
        with core.lock_for(sid):
            p = _get(S, pid)
            mode = str(b.get("mode", "update"))
            if mode not in ("update", "full_refresh"):
                raise ApiError(400, "INVALID_MODE", "mode는 update 또는 full_refresh 입니다.")
            upd = run_update(S, a, _principal(a), p, mode)
            core.save(S)
            return {"update": upd, "evidence_level": EVIDENCE}

    @app.get("/api/sessions/{sid}/dpipes/{pid}/events")
    def dpipes_events(sid: str, pid: str, authorization: Optional[str] = Header(None)):
        S = sess(sid, actor_of(authorization))
        with core.lock_for(sid):
            p = _get(S, pid)
            return {"updates": list(reversed(p.get("updates", [])))}

    @app.post("/api/sessions/{sid}/dpipes/sample")
    def dpipes_sample(sid: str, b: dict, authorization: Optional[str] = Header(None)):
        a = actor_of(authorization)
        S = sess(sid, a)
        with core.lock_for(sid):
            kind = str(b.get("kind", ""))
            if kind not in ("orders", "cdc"):
                raise ApiError(400, "INVALID_KIND", "kind는 orders 또는 cdc 입니다.")
            catalog = str(b.get("catalog", core.CAT)).lower()
            schema = str(b.get("schema", "gold")).lower()
            if not _NAME.match(catalog) or not _NAME.match(schema):
                raise ApiError(400, "INVALID_NAME", "catalog/schema 이름이 올바르지 않습니다.")
            try:
                r = make_sample(_Ctx(S, a, _principal(a)), S, kind, catalog, schema, bool(b.get("append")))
            except DltError as e:
                core.save(S)
                return {"status": "failed", "error": e.as_dict()}
            core.save(S)
            return {"status": "succeeded", **r, "note": "합성 데이터입니다. 잘못된 행(NULL id·음수 금액)이나 오래된 이벤트가 일부러 섞여 있습니다."}
