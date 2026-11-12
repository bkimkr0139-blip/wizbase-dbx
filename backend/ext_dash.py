"""Dashboards · Genie Code(규칙 기반) · Lakeflow Designer(시각 ETL) — 담당 C.

모두 교육용 시뮬레이션이다.
- Dashboards: 데이터셋(SQL)을 core.run_sql(via="dashboard")로 실행해 결과(최대 500행)를 세션에 캐시하고, 위젯 집계는 서버에서 계산한다.
  게시하면 그 시점의 정의+결과를 스냅샷으로 얼려 '게시본'으로 따로 본다(초안을 고쳐도 게시본은 그대로).
- Genie Code: 실제 LLM이 아니다. core.GENIE_TEMPLATES 와 테이블 이름·열 이름 규칙으로만 SQL 초안을 만든다. 실행하지 않는다.
- Designer: 연산자 카드 → CTE 체인 SQL. 식별자는 정규식으로 검증하고 값은 인용 처리한다.
"""
from __future__ import annotations
import difflib, re, uuid
from typing import Optional

from fastapi import Header

from . import core
from .core import ApiError, exp, sqlglot

IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
TBL3 = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}\.[A-Za-z_][A-Za-z0-9_]{0,63}\.[A-Za-z_][A-Za-z0-9_]{0,63}$")
WID_TYPES = ("counter", "bar", "line", "table")
AGGS = ("sum", "count", "avg", "min", "max")
MAX_DS, MAX_W, MAX_F, MAX_P = 6, 16, 4, 6
LIMIT_NOTE = "교육용 시뮬레이션입니다. 데이터셋 결과는 최대 500행이며 위젯 집계는 이 행들만 대상으로 합니다(실제 AI/BI Dashboards와 다름)."


def _principal(a):
    return core.ADMIN if a["role"] == "admin" else core.TRAINEE


def _is_query(sql: str) -> bool:
    try:
        st = [s for s in sqlglot.parse(sql, read="databricks") if s is not None]
    except Exception:
        return False
    return len(st) == 1 and isinstance(st[0], exp.Query)


def _s(v, n, default=""):
    return str(v if v is not None else default).strip()[:n]


# ================================================================= Dashboards
def _sample_doc():
    C = core.CAT
    return {
        "name": "주문·재고 현황(샘플)",
        "pages": [{"id": "p1", "name": "주문"}, {"id": "p2", "name": "재고"}],
        "datasets": [
            {"id": "d1", "name": "orders", "sql": f"SELECT order_id, customer_id, status, total_boxes, supply_amount FROM {C}.gold.v_order_overview"},
            {"id": "d2", "name": "inventory", "sql": f"SELECT product_id, available_qty FROM {C}.gold.v_available_inventory"},
        ],
        "widgets": [
            {"id": "w1", "type": "counter", "dataset": "d1", "x": "", "y": "order_id", "agg": "count", "title": "주문 건수", "page": "p1"},
            {"id": "w2", "type": "counter", "dataset": "d1", "x": "", "y": "total_boxes", "agg": "sum", "title": "총 박스", "page": "p1"},
            {"id": "w3", "type": "bar", "dataset": "d1", "x": "status", "y": "order_id", "agg": "count", "title": "상태별 주문 건수", "page": "p1"},
            {"id": "w4", "type": "bar", "dataset": "d1", "x": "customer_id", "y": "supply_amount", "agg": "sum", "title": "거래처별 공급가 합계(상위)", "page": "p1"},
            {"id": "w5", "type": "table", "dataset": "d1", "x": "", "y": "", "agg": "sum", "title": "주문 목록", "page": "p1"},
            {"id": "w6", "type": "bar", "dataset": "d2", "x": "product_id", "y": "available_qty", "agg": "sum", "title": "상품별 가용재고", "page": "p2"},
            {"id": "w7", "type": "table", "dataset": "d2", "x": "", "y": "", "agg": "sum", "title": "재고 표", "page": "p2"},
        ],
        "filters": [{"id": "f1", "column": "status", "label": "상태"}],
        "refresh": {"strategy": "manual", "note": "수동 새로 고침(실제 대시보드의 예약 새로 고침은 표시만 하며 실행되지 않습니다)"},
    }


def _clean(doc: dict) -> dict:
    """클라이언트가 보낸 대시보드 정의를 검증·정리한다(결과 캐시는 건드리지 않는다)."""
    name = _s(doc.get("name"), 60) or "새 대시보드"
    pages = []
    for p in (doc.get("pages") or [])[:MAX_P]:
        pid = _s(p.get("id"), 12)
        if re.fullmatch(r"p[0-9a-z]{1,10}", pid) and pid not in [x["id"] for x in pages]:
            pages.append({"id": pid, "name": _s(p.get("name"), 30) or pid})
    if not pages:
        pages = [{"id": "p1", "name": "페이지 1"}]
    dss = []
    for d in (doc.get("datasets") or [])[:MAX_DS]:
        did = _s(d.get("id"), 12)
        sql = str(d.get("sql") or "").strip()[:4000]
        if not re.fullmatch(r"d[0-9a-z]{1,10}", did) or did in [x["id"] for x in dss]:
            raise ApiError(400, "INVALID_DATASET", "데이터셋 id 형식이 올바르지 않거나 중복입니다.")
        if sql and not _is_query(sql):
            raise ApiError(400, "DATASET_NOT_QUERY", f"데이터셋 `{_s(d.get('name'), 40) or did}`: SELECT/WITH 쿼리 한 문장만 쓸 수 있습니다(DDL·DML 불가).")
        dss.append({"id": did, "name": _s(d.get("name"), 40) or did, "sql": sql})
    ids = {d["id"] for d in dss}
    ws = []
    for w in (doc.get("widgets") or [])[:MAX_W]:
        t = _s(w.get("type"), 10)
        if t not in WID_TYPES:
            raise ApiError(400, "INVALID_WIDGET", f"위젯 종류는 {', '.join(WID_TYPES)} 중 하나입니다.")
        if w.get("dataset") not in ids:
            raise ApiError(400, "INVALID_WIDGET", "위젯의 데이터셋이 없습니다.")
        wid = _s(w.get("id"), 12)
        if not re.fullmatch(r"w[0-9a-z]{1,10}", wid) or wid in [x["id"] for x in ws]:
            wid = "w" + uuid.uuid4().hex[:6]
        agg = _s(w.get("agg"), 6) or "sum"
        if agg not in AGGS:
            raise ApiError(400, "INVALID_WIDGET", f"집계는 {', '.join(AGGS)} 중 하나입니다.")
        page = _s(w.get("page"), 12)
        ws.append({"id": wid, "type": t, "dataset": w["dataset"], "x": _s(w.get("x"), 64), "y": _s(w.get("y"), 64), "agg": agg, "title": _s(w.get("title"), 60) or t,
                   "page": page if page in [p["id"] for p in pages] else pages[0]["id"]})
    fs = []
    for f in (doc.get("filters") or [])[:MAX_F]:
        col = _s(f.get("column"), 64)
        if col and col not in [x["column"] for x in fs]:
            fs.append({"id": _s(f.get("id"), 12) or "f" + uuid.uuid4().hex[:5], "column": col, "label": _s(f.get("label"), 30) or col})
    r = doc.get("refresh") or {}
    refresh = {"strategy": "scheduled" if r.get("strategy") == "scheduled" else "manual", "note": _s(r.get("note"), 200)}
    return {"name": name, "pages": pages, "datasets": dss, "widgets": ws, "filters": fs, "refresh": refresh}


def _find(S, did):
    d = S.setdefault("dash", {}).get(did)
    if not d:
        raise ApiError(404, "DASHBOARD_NOT_FOUND", "대시보드를 찾을 수 없습니다.")
    return d


def _summary(d):
    pub = d.get("published")
    return {"id": d["id"], "name": d["name"], "widgets": len(d["widgets"]), "datasets": len(d["datasets"]), "status": "published" if pub else "draft", "published_at": pub["at"] if pub else None,
            "draft_ahead": bool(pub) and d["updated_at"] > pub["at"], "updated_at": d["updated_at"]}


def _run_dataset(S, a, d, ds):
    """데이터셋 한 개를 실행해 결과를 캐시한다. 결과 dict(status/columns/rows/error) 반환."""
    sql = ds["sql"].strip()
    if not sql:
        res = {"status": "failed", "columns": [], "rows": [], "error": {"code": "EMPTY_DATASET", "message": "SQL이 비어 있습니다."}}
    elif not _is_query(sql):
        res = {"status": "failed", "columns": [], "rows": [], "error": {"code": "DATASET_NOT_QUERY", "message": "SELECT/WITH 쿼리 한 문장만 실행할 수 있습니다."}}
    else:
        r = core.run_sql(S, sql, _principal(a), via="dashboard", need_warehouse=True, actor_id=a["user_id"])
        res = {"status": "ok" if r["status"] == "succeeded" else "failed", "columns": r.get("columns", []), "rows": r.get("rows", []), "error": r.get("error")}
    res.update(at=core.now_utc(), row_count=len(res["rows"]), sql_hash=core.sha(sql), truncated=len(res["rows"]) >= 500)
    d.setdefault("results", {})[ds["id"]] = res
    return res


def _num(v):
    if isinstance(v, bool) or v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _fmt_num(x):
    if isinstance(x, float) and (x != x or x in (float("inf"), float("-inf"))):
        return None
    return int(x) if isinstance(x, float) and x == int(x) and abs(x) < 1e15 else (round(x, 4) if isinstance(x, float) else x)


def _agg(rows, yi, agg):
    if agg == "count":
        return len(rows) if yi is None else sum(1 for r in rows if r[yi] is not None)
    vals = [_num(r[yi]) for r in rows] if yi is not None else []
    vals = [v for v in vals if v is not None]
    if not vals:
        return None
    return {"sum": sum(vals), "avg": sum(vals) / len(vals), "min": min(vals), "max": max(vals)}[agg]


def _filtered(res, filters):
    cols, rows = res["columns"], res["rows"]
    for col, val in (filters or {}).items():
        if val in (None, "", "__all__") or col not in cols:
            continue
        i = cols.index(col)
        rows = [r for r in rows if ("" if r[i] is None else str(r[i])) == str(val)]
    return cols, rows


def compute(defn: dict, results: dict, filters: dict) -> dict:
    """정의(widgets/filters/datasets)와 결과 캐시로 위젯별 표시 데이터를 계산한다(서버 단일 구현)."""
    out = []
    dsname = {d["id"]: d["name"] for d in defn["datasets"]}
    for w in defn["widgets"]:
        base = {"id": w["id"], "type": w["type"], "title": w["title"], "page": w["page"], "dataset": dsname.get(w["dataset"], "?")}
        res = results.get(w["dataset"])
        if not res or res.get("status") != "ok":
            out.append({**base, "status": "NO_DATA", "message": "데이터셋을 먼저 실행하세요." if not res else "데이터셋 실행이 실패했습니다. 편집 화면에서 오류를 확인하세요."})
            continue
        cols, rows = _filtered(res, filters)
        x, y, agg = w["x"], w["y"], w["agg"]
        bad = [c for c in ((x,) if w["type"] in ("bar", "line") else ()) + ((y,) if y else ()) if c and c not in cols]
        if bad or (w["type"] in ("bar", "line") and not x):
            out.append({**base, "status": "BAD_FIELD", "message": f"열을 찾을 수 없습니다: {', '.join(bad) or 'x(축) 열 필요'}. 사용 가능: {', '.join(cols)}"})
            continue
        if agg != "count" and w["type"] != "table" and not y:
            out.append({**base, "status": "BAD_FIELD", "message": "이 집계에는 y 열이 필요합니다."})
            continue
        yi = cols.index(y) if y else None
        ylab = f"{agg}({y})" if y else "count(*)"
        if w["type"] == "table":
            out.append({**base, "status": "OK", "columns": cols[:12], "rows": [r[:12] for r in rows[:50]], "total_rows": len(rows)})
        elif w["type"] == "counter":
            v = _agg(rows, yi, agg)
            out.append({**base, "status": "OK", "value": None if v is None else _fmt_num(v), "label": ylab, "rows_used": len(rows)})
        else:
            xi = cols.index(x)
            groups: dict = {}
            for r in rows:
                groups.setdefault("" if r[xi] is None else str(r[xi]), []).append(r)
            items = [(k, _agg(v, yi, agg)) for k, v in groups.items()]
            items = [(k, 0 if v is None else v) for k, v in items]
            trunc = 0
            if w["type"] == "bar":
                items.sort(key=lambda kv: (-kv[1], kv[0]))
                trunc = max(0, len(items) - 20)
                items = items[:20]
            else:
                nums = [_num(k) for k, _ in items]
                items.sort(key=(lambda kv: _num(kv[0])) if all(n is not None for n in nums) else (lambda kv: kv[0]))
                trunc = max(0, len(items) - 200)
                items = items[:200]
            out.append({**base, "status": "OK", "labels": [k for k, _ in items], "values": [_fmt_num(v) for _, v in items], "label": ylab, "x": x, "truncated": trunc})
    fopts = []
    for f in defn["filters"]:
        vals, applies = set(), []
        for d in defn["datasets"]:
            res = results.get(d["id"])
            if res and res.get("status") == "ok" and f["column"] in res["columns"]:
                i = res["columns"].index(f["column"])
                vals |= {"" if r[i] is None else str(r[i]) for r in res["rows"]}
                applies.append(d["name"])
        fopts.append({**f, "options": sorted(vals)[:100], "applies_to": applies})
    return {"widgets": out, "filters": fopts}


def _dash_register(app, actor_of, sess):
    base = "/api/sessions/{sid}/dash"

    @app.get(base)
    def dash_list(sid: str, authorization: Optional[str] = Header(None)):
        S = sess(sid, actor_of(authorization))
        with core.lock_for(sid):
            return {"items": [_summary(d) for d in S.setdefault("dash", {}).values()], "note": LIMIT_NOTE, "evidence_level": "LOCAL_EXECUTED"}

    @app.post(base + "/create")
    def dash_create(sid: str, b: dict, authorization: Optional[str] = Header(None)):
        a = actor_of(authorization)
        S = sess(sid, a)
        with core.lock_for(sid):
            D = S.setdefault("dash", {})
            if len(D) >= 10:
                raise ApiError(429, "DASHBOARD_LIMIT", "대시보드는 세션당 10개까지입니다.")
            doc = _sample_doc() if b.get("sample") else _clean({"name": b.get("name"), "pages": [{"id": "p1", "name": "페이지 1"}], "datasets": [], "widgets": [], "filters": []})
            did = "db_" + uuid.uuid4().hex[:8]
            now = core.now_utc()
            D[did] = {"id": did, "owner": a["user_id"], **_clean(doc), "results": {}, "published": None, "created_at": now, "updated_at": now}
            core.audit(S, a["user_id"], "DASH_CREATE", did, "succeeded", "LOCAL_EXECUTED", {"sample": bool(b.get("sample"))})
            core.save(S)
            return D[did]

    @app.get(base + "/{did}")
    def dash_get(did: str, sid: str, authorization: Optional[str] = Header(None)):
        S = sess(sid, actor_of(authorization))
        with core.lock_for(sid):
            d = _find(S, did)
            return {**d, "summary": _summary(d), "note": LIMIT_NOTE}

    @app.post(base + "/{did}/save")
    def dash_save(did: str, sid: str, b: dict, authorization: Optional[str] = Header(None)):
        a = actor_of(authorization)
        S = sess(sid, a)
        with core.lock_for(sid):
            d = _find(S, did)
            c = _clean(b)
            d.update(c)
            keep = {ds["id"]: core.sha(ds["sql"].strip()) for ds in d["datasets"]}
            d["results"] = {k: v for k, v in d.get("results", {}).items() if keep.get(k) == v.get("sql_hash")}      # SQL이 바뀐 데이터셋의 결과는 버린다
            d["updated_at"] = core.now_utc()
            core.save(S)
            return {**d, "summary": _summary(d)}

    @app.post(base + "/{did}/run")
    def dash_run(did: str, sid: str, b: dict, authorization: Optional[str] = Header(None)):
        a = actor_of(authorization)
        S = sess(sid, a)
        with core.lock_for(sid):
            d = _find(S, did)
            ds = next((x for x in d["datasets"] if x["id"] == b.get("dataset")), None)
            if not ds:
                raise ApiError(404, "DATASET_NOT_FOUND", "데이터셋을 찾을 수 없습니다.")
            res = _run_dataset(S, a, d, ds)
            core.save(S)
            return {"dataset": ds["id"], **res, "preview": res["rows"][:20]}

    @app.post(base + "/{did}/run-all")
    def dash_run_all(did: str, sid: str, authorization: Optional[str] = Header(None)):
        a = actor_of(authorization)
        S = sess(sid, a)
        with core.lock_for(sid):
            d = _find(S, did)
            out = {ds["id"]: {k: v for k, v in _run_dataset(S, a, d, ds).items() if k != "rows"} for ds in d["datasets"]}
            core.save(S)
            return {"results": out}

    @app.post(base + "/{did}/data")
    def dash_data(did: str, sid: str, b: dict, authorization: Optional[str] = Header(None)):
        S = sess(sid, actor_of(authorization))
        with core.lock_for(sid):
            d = _find(S, did)
            pub = d.get("published")
            if b.get("source") == "published":
                if not pub:
                    raise ApiError(409, "NOT_PUBLISHED", "게시된 버전이 없습니다.")
                defn, results = pub["definition"], pub["results"]
            else:
                defn, results = d, d.get("results", {})
            r = compute(defn, results, b.get("filters") or {})
            return {**r, "pages": defn["pages"], "source": "published" if b.get("source") == "published" else "draft", "published_at": pub["at"] if pub else None,
                    "datasets": [{"id": x["id"], "name": x["name"], "status": (results.get(x["id"]) or {}).get("status"), "row_count": (results.get(x["id"]) or {}).get("row_count"), "at": (results.get(x["id"]) or {}).get("at"),
                                  "truncated": (results.get(x["id"]) or {}).get("truncated"), "error": (results.get(x["id"]) or {}).get("error"), "columns": (results.get(x["id"]) or {}).get("columns", [])} for x in defn["datasets"]],
                    "note": LIMIT_NOTE}

    @app.post(base + "/{did}/publish")
    def dash_publish(did: str, sid: str, authorization: Optional[str] = Header(None)):
        a = actor_of(authorization)
        S = sess(sid, a)
        with core.lock_for(sid):
            d = _find(S, did)
            if not d["datasets"]:
                raise ApiError(409, "NOTHING_TO_PUBLISH", "데이터셋이 없습니다.")
            results = {}
            for ds in d["datasets"]:                                        # 게시 시점에 모든 데이터셋을 새로 실행해 스냅샷으로 얼린다
                res = _run_dataset(S, a, d, ds)
                if res["status"] != "ok":
                    core.save(S)
                    raise ApiError(409, "PUBLISH_BLOCKED", f"데이터셋 `{ds['name']}` 실행 실패: {(res['error'] or {}).get('message', '')}. 게시하지 않았습니다.")
                results[ds["id"]] = {k: res[k] for k in ("status", "columns", "rows", "at", "row_count", "truncated")}
            d["published"] = {"at": core.now_utc(), "by": a["user_id"], "results": results,
                              "definition": {"name": d["name"], "pages": d["pages"], "widgets": d["widgets"], "filters": d["filters"], "datasets": [{"id": x["id"], "name": x["name"]} for x in d["datasets"]]},
                              "sharing": "표시만(이 시뮬레이터는 다른 사용자와 공유하지 않습니다)", "refresh": d["refresh"]}
            core.audit(S, a["user_id"], "DASH_PUBLISH", did, "succeeded", "LOCAL_EXECUTED", {"datasets": len(results)})
            core.save(S)
            return _summary(d)

    @app.post(base + "/{did}/unpublish")
    def dash_unpublish(did: str, sid: str, authorization: Optional[str] = Header(None)):
        a = actor_of(authorization)
        S = sess(sid, a)
        with core.lock_for(sid):
            d = _find(S, did)
            d["published"] = None
            core.audit(S, a["user_id"], "DASH_UNPUBLISH", did, "succeeded", "LOCAL_EXECUTED", {})
            core.save(S)
            return _summary(d)

    @app.post(base + "/{did}/delete")
    def dash_delete(did: str, sid: str, authorization: Optional[str] = Header(None)):
        a = actor_of(authorization)
        S = sess(sid, a)
        with core.lock_for(sid):
            _find(S, did)
            del S["dash"][did]
            core.save(S)
            return {"deleted": did}


# ================================================================= Genie Code (규칙 기반)
GC_LIMITS = ("Genie Code는 이 시뮬레이터에서 규칙 기반 도우미입니다. 실제 LLM이 아니며 정해진 질문 형태·테이블/열 이름 일치로만 SQL 초안을 만듭니다. "
             "초안은 실행하지 않았으니 반드시 읽고 검토한 뒤 SQL Editor에서 실행하세요.")
GC_EXAMPLES = ["총 주문 박스는?", "상태별 주문 건수", "가용재고 상위 5개", "orders 테이블 몇 건이야?", "customers 테이블 region별 보여줘", "cdc_events 상위 5"]


def _tables(S, principal=None):
    """(virtual_fq, [columns]) 목록. 사용자가 만든 catalog 는 'catalog__schema' 물리 스키마를 가상 이름으로 되돌린다."""
    c = core._conns[S["id"]]
    cats = S.get("catalogs", {})
    out = []
    for sch, tbl in c.execute("select table_schema, table_name from information_schema.tables where table_catalog=? order by 1,2", [core.CAT]).fetchall():
        cat, db = core.CAT, sch
        if "__" in sch and sch.split("__", 1)[0] in cats:
            cat, db = sch.split("__", 1)
        fq = f"{cat}.{db}.{tbl}"
        try:
            cols = [(r[0], str(r[1])) for r in c.execute(f"DESCRIBE {core.CAT}.{sch}.{tbl}").fetchall()]
        except Exception:
            cols = []
        if principal is not None and not _can_select(S, principal, fq):
            cols = []                                                 # SELECT 권한이 없는 테이블은 이름만 알고 열 목록은 알려주지 않는다(열 추정·미리보기 금지)
        out.append((fq, cols))
    return out


def _can_select(S, principal, fq):
    cat, db, name = fq.split(".")
    return all(core.has_priv(S, principal, p, s) for p, s in [("USE CATALOG", f"catalog:{cat}"), ("USE SCHEMA", f"schema:{cat}.{db}"), ("SELECT", f"table:{fq}")])


def genie_code(S, text: str, principal: str) -> dict:
    q = (text or "").strip()
    ql = q.lower()
    base = {"mode": "generate", "question": q, "limits": GC_LIMITS, "examples": GC_EXAMPLES, "evidence_level": "SIMULATED", "engine": "rule-based"}
    if not q:
        return {**base, "status": "EMPTY", "message": "질문을 입력하세요."}
    cz = S["case"]
    fill = lambda x: x.replace("{ORDER}", cz["order"]).replace("{PRODUCT}", cz["product"]).replace("{CUST}", cz["cust"]).replace("{order}", cz["order"].lower()).replace("{product}", cz["product"].lower()).replace("{cust}", cz["cust"].lower())
    for name, keys, sql in core.GENIE_TEMPLATES:
        if all(fill(k) in ql for k in keys):
            fsql = fill(sql)
            ds = sorted(set(re.findall(r"food_dev\.\w+\.\w+", fsql)))
            warn = [f"{d}: 현재 권한으로 조회할 수 없습니다(권한 요청 필요)." for d in ds if not _can_select(S, principal, d)]
            return {**base, "status": "OK", "sql": fsql, "title": fill(name), "match": "질의 템플릿 일치", "datasets": ds, "warnings": warn,
                    "explanation": f"'{fill(name)}' 질문과 일치하는 정해진 템플릿입니다. 사용 데이터셋: {', '.join(ds)}."}
    tabs = _tables(S, principal)
    cand = []
    for fq, cols in tabs:
        nm = fq.split(".")[-1].lower()
        if re.search(r"(?<![a-z0-9_])" + re.escape(nm) + r"(?![a-z0-9_])", ql) or nm.replace("_", " ") in ql:
            cand.append((len(nm), fq, cols))
    if not cand:
        return {**base, "status": "UNSUPPORTED", "message": "이 질문으로는 SQL을 만들지 못했습니다. 정해진 질문 형태나 테이블 이름이 필요합니다."}
    cand.sort(reverse=True)
    _, fq, cols = cand[0]
    names = [c[0] for c in cols]
    nums = [c[0] for c in cols if re.search(r"INT|DECIMAL|DOUBLE|FLOAT|NUMERIC", c[1])]
    m = re.search(r"(\d+)\s*(?:개|건|행|rows?)?", ql)
    n = min(int(m.group(1)), 1000) if m and int(m.group(1)) > 0 else None
    by = next((c for c in names if re.search(r"(?<![a-z0-9_])" + re.escape(c.lower()) + r"\s*(?:별|by)", ql) or re.search(r"(?:by|group by)\s+" + re.escape(c.lower()), ql)), None)
    if re.search(r"몇\s*(?:건|개|행)|개수|행\s*수|건수|count|총\s*(?:건|행)", ql) and not by:
        sql, how = f"SELECT COUNT(*) AS row_count FROM {fq}", "행 수 질문 → COUNT(*)"
    elif by:
        sql, how = f"SELECT {by}, COUNT(*) AS cnt FROM {fq} GROUP BY {by} ORDER BY cnt DESC, {by}", f"'{by}별' → GROUP BY {by}"
    elif re.search(r"상위|top|큰|많은|높은", ql) and nums:
        sql, how = f"SELECT * FROM {fq} ORDER BY {nums[0]} DESC LIMIT {n or 5}", f"상위 N → 숫자 열 `{nums[0]}` 내림차순(첫 숫자 열을 추정함)"
    else:
        sql, how = f"SELECT * FROM {fq} LIMIT {n or 10}", "기본 → 처음 몇 행 보기"
    warn = [] if _can_select(S, principal, fq) else [f"{fq}: 현재 권한으로 조회할 수 없습니다(권한 요청 필요)."]
    return {**base, "status": "OK", "sql": sql, "title": how, "match": "테이블 이름 일치", "datasets": [fq], "warnings": warn,
            "explanation": f"질문에서 테이블 `{fq}` 이름을 찾았고 규칙으로 SQL을 만들었습니다({how}). 열 추정이 틀릴 수 있습니다."}


_KW = ["SELECT", "FROM", "WHERE", "GROUP", "ORDER", "LIMIT", "JOIN", "WITH", "HAVING", "INSERT", "UPDATE", "DELETE", "CREATE"]


def genie_debug(S, sql: str, error: dict, principal: str) -> dict:
    code = (error or {}).get("code") or ""
    msg = (error or {}).get("message") or ""
    base = {"mode": "debug", "code": code, "limits": GC_LIMITS, "evidence_level": "SIMULATED", "engine": "rule-based"}
    sug = []
    tabs = _tables(S, principal)
    fqs = [t[0] for t in tabs]
    if code == "TABLE_OR_VIEW_NOT_FOUND":
        m = re.search(r"`([^`]+)`", msg)
        miss = m.group(1) if m else ""
        short = miss.split(".")[-1].lower()
        same = [f for f in fqs if f.split(".")[-1].lower() == short]
        scored = sorted(((difflib.SequenceMatcher(None, short, f.split(".")[-1].lower()).ratio(), f) for f in fqs), reverse=True)
        close = same or [f for sc, f in scored if sc >= 0.7]       # 이름이 가장 비슷한 순
        for f in close[:3]:
            fixed = sql.replace(miss, f) if miss and miss in sql else re.sub(r"(?<![\w.])" + re.escape(short) + r"(?![\w.])", f, sql, count=1, flags=re.I)
            sug.append({"title": f"`{f}` 로 바꾸기", "why": "비슷한 이름의 테이블입니다. 3단계 이름(catalog.schema.table)으로 씁니다.", "sql": fixed})
        if not sug:
            sug.append({"title": "Catalog에서 이름 확인", "why": "비슷한 이름의 테이블을 찾지 못했습니다. Catalog Explorer에서 실제 이름과 내 권한을 확인하세요."})
    elif code == "PARSE_ERROR" or code == "UNSUPPORTED_SQL":
        s = sql
        first = (s.strip().split() or [""])[0]
        kw = difflib.get_close_matches(first.upper(), _KW, n=1, cutoff=0.7)
        if kw and first.upper() not in _KW:
            sug.append({"title": f"`{first}` → `{kw[0]}`", "why": "문장 첫 단어가 키워드 오타로 보입니다.", "sql": re.sub(r"^\s*" + re.escape(first), kw[0], s, count=1)})
        fixed = re.sub(r",\s*(FROM|WHERE|GROUP|ORDER|LIMIT)\b", r" \1", s, flags=re.I)
        if fixed != s:
            sug.append({"title": "FROM 앞의 쉼표 제거", "why": "마지막 열 뒤의 쉼표는 문법 오류입니다.", "sql": fixed})
        if s.count("(") > s.count(")"):
            sug.append({"title": "닫는 괄호 추가", "why": f"여는 괄호 {s.count('(')}개, 닫는 괄호 {s.count(')')}개입니다.", "sql": s.rstrip().rstrip(";") + ")" * (s.count("(") - s.count(")"))})
        if s.count("'") % 2:
            sug.append({"title": "작은따옴표 확인", "why": "작은따옴표 개수가 홀수입니다. 문자열을 닫았는지 확인하세요."})
        if not sug:
            sug.append({"title": "문법 확인", "why": "자동으로 고칠 수 있는 패턴을 찾지 못했습니다. 키워드 철자·괄호·쉼표를 확인하고 LIMIT 5 같은 작은 쿼리로 줄여 보세요."})
    elif code == "EXECUTION_ERROR":
        m = re.search(r'column\s+"?([A-Za-z0-9_]+)"?', msg, re.I) or re.search(r"[`'\"]([A-Za-z0-9_]+)[`'\"]", msg)
        bad = m.group(1) if m else ""
        used = [t for t in tabs if re.search(r"(?<![\w])" + re.escape(t[0].split(".")[-1]) + r"(?![\w])", sql, re.I)]
        allcols = sorted({c[0] for t in used for c in t[1]})
        close = difflib.get_close_matches(bad, allcols, n=2, cutoff=0.6) if bad else []
        for c in close:
            sug.append({"title": f"열 `{bad}` → `{c}`", "why": "사용 중인 테이블에 있는 비슷한 열 이름입니다.", "sql": re.sub(r"(?<![\w])" + re.escape(bad) + r"(?![\w])", c, sql)})
        if not sug:
            sug.append({"title": "열 이름 확인", "why": f"사용 가능한 열: {', '.join(allcols[:30]) or '(테이블을 찾지 못함)'}"})
    elif code == "INSUFFICIENT_PERMISSIONS":
        mm = (error or {}).get("missing") or {}
        sug.append({"title": "권한 요청", "why": f"{mm.get('securable', '대상')} 에 {mm.get('privilege', '필요한')} 권한이 필요합니다. 권한 화면에서 최소 권한을 요청하세요(ALL PRIVILEGES 요청은 반려)."})
    elif code in ("WAREHOUSE_NOT_RUNNING", "NO_CAN_USE", "NO_SQL_ENTITLEMENT"):
        sug.append({"title": "Warehouse 확인", "why": "Compute 화면에서 SQL Warehouse를 시작하고 CAN USE/entitlement를 확인하세요(Free Edition 프로필은 자동 시작)."})
    else:
        sug.append({"title": "원인 확인", "why": f"오류 코드 {code or '(없음)'}: 자동으로 제안할 수 있는 수정이 없습니다. Query History에서 오류 해결 안내를 확인하세요."})
    return {**base, "status": "OK", "suggestions": sug, "message": msg}


def _gc_register(app, actor_of, sess):
    @app.post("/api/sessions/{sid}/genie-code")
    def genie_code_ep(sid: str, b: dict, authorization: Optional[str] = Header(None)):
        a = actor_of(authorization)
        S = sess(sid, a)
        with core.lock_for(sid):
            if b.get("mode") == "debug":
                last = next((x["error"] for x in reversed(S.get("qh", [])) if x.get("status") == "FAILED" and x.get("error")), None)   # 클라이언트가 보낸 오류는 믿지 않고 서버 이력의 마지막 실패를 쓴다
                return genie_debug(S, str(b.get("sql") or "")[:4000], last or {}, _principal(a))
            return genie_code(S, str(b.get("text") or "")[:300], _principal(a))


# ================================================================= Lakeflow Designer (시각 ETL, 시뮬레이션)
OPS = ("source", "filter", "select", "join", "aggregate", "sort", "limit", "output")
CMPS = ("=", "<>", ">", ">=", "<", "<=", "contains", "is null", "is not null")
D_AGGS = ("sum", "count", "avg", "min", "max")
DES_NOTE = "교육용 시뮬레이션입니다. 연산자 카드는 SQL(CTE)로 변환되어 실행됩니다. 스케줄은 표시만 하며 실행되지 않습니다."


def _id(x, what, i=None):
    if not isinstance(x, str) or not IDENT.match(x):
        raise ApiError(400, "INVALID_IDENTIFIER", f"{'단계 %d: ' % (i + 1) if i is not None else ''}{what} 이름이 올바르지 않습니다(영문·숫자·_ 만, 숫자로 시작 불가).")
    return x


def _tbl(x, i=None):
    if not isinstance(x, str) or not TBL3.match(x):
        raise ApiError(400, "INVALID_TABLE", f"{'단계 %d: ' % (i + 1) if i is not None else ''}테이블은 catalog.schema.table 형식이어야 합니다.")
    return x


def _raw(v, i):
    s = str(v if v is not None else "")
    if len(s) > 100 or re.search(r"[\\\x00-\x1f]", s):
        raise ApiError(400, "INVALID_VALUE", f"단계 {i + 1}: 값이 너무 길거나 허용되지 않는 문자(역슬래시·제어문자)가 있습니다.")
    return s


def _lit(v, i):
    s = _raw(v, i)
    if re.fullmatch(r"-?\d+(\.\d+)?", s):
        return s
    return core.sql_str(s)


def _q(c):
    return f"`{c}`"


def _need(cols, c, i):
    if cols is not None and c not in cols:
        raise ApiError(400, "COLUMN_NOT_FOUND", f"단계 {i + 1}: 열 `{c}`이(가) 없습니다. 사용 가능: {', '.join(cols)}", step=i)


def build_sql(steps: list, cols_of=None) -> dict:
    """연산자 카드 → CTE 체인 SQL. cols_of(table)->열 목록(없으면 열 검증을 건너뜀)."""
    if not isinstance(steps, list) or not steps or steps[0].get("op") != "source":
        raise ApiError(400, "INVALID_FLOW", "첫 단계는 소스(source) 테이블이어야 합니다.", step=0)
    if len(steps) > 12:
        raise ApiError(400, "INVALID_FLOW", "연산자는 12개까지입니다.")
    ctes, cols, out, step_cols = [], None, None, []
    for i, s in enumerate(steps):
        op = s.get("op")
        if op not in OPS:
            raise ApiError(400, "INVALID_FLOW", f"단계 {i + 1}: 알 수 없는 연산자 `{op}`", step=i)
        if op == "source":
            if i:
                raise ApiError(400, "INVALID_FLOW", f"단계 {i + 1}: 소스는 첫 단계에만 둘 수 있습니다.", step=i)
            t = _tbl(s.get("table"), i)
            cols = cols_of(t) if cols_of else None
            ctes.append(f"s0 AS (SELECT * FROM {t})")
        elif op == "output":
            if i != len(steps) - 1:
                raise ApiError(400, "INVALID_FLOW", f"단계 {i + 1}: 출력은 마지막 단계여야 합니다.", step=i)
            out = _tbl(s.get("target"), i)
        else:
            prev, new = f"s{len(ctes) - 1}", f"s{len(ctes)}"
            if op == "filter":
                c, cmp_ = _id(s.get("column"), "열", i), s.get("cmp", "=")
                _need(cols, c, i)
                if cmp_ not in CMPS:
                    raise ApiError(400, "INVALID_FLOW", f"단계 {i + 1}: 비교 연산은 {', '.join(CMPS)} 중 하나입니다.", step=i)
                cond = f"{_q(c)} IS NULL" if cmp_ == "is null" else f"{_q(c)} IS NOT NULL" if cmp_ == "is not null" else \
                    f"{_q(c)} LIKE {core.sql_str('%' + _raw(s.get('value'), i) + '%')}" if cmp_ == "contains" else f"{_q(c)} {cmp_} {_lit(s.get('value'), i)}"
                ctes.append(f"{new} AS (SELECT * FROM {prev} WHERE {cond})")
            elif op == "select":
                items = s.get("columns") or []
                if not items:
                    raise ApiError(400, "INVALID_FLOW", f"단계 {i + 1}: 선택할 열이 없습니다.", step=i)
                parts, nc = [], []
                for it in items:
                    nm = _id(it.get("name") if isinstance(it, dict) else it, "열", i)
                    al = _id(it.get("alias") or nm, "별칭", i) if isinstance(it, dict) else nm
                    _need(cols, nm, i)
                    parts.append(f"{_q(nm)} AS {_q(al)}" if al != nm else _q(nm))
                    nc.append(al)
                ctes.append(f"{new} AS (SELECT {', '.join(parts)} FROM {prev})")
                cols = nc
            elif op == "join":
                t = _tbl(s.get("table"), i)
                lk, rk = _id(s.get("left_key"), "왼쪽 키", i), _id(s.get("right_key"), "오른쪽 키", i)
                jt = s.get("type", "inner")
                if jt not in ("inner", "left"):
                    raise ApiError(400, "INVALID_FLOW", f"단계 {i + 1}: 조인 종류는 inner, left 입니다.", step=i)
                _need(cols, lk, i)
                rcols = cols_of(t) if cols_of else [_id(c, "열", i) for c in (s.get("columns") or [])]
                if not rcols and not cols_of:
                    raise ApiError(400, "INVALID_FLOW", f"단계 {i + 1}: 가져올 오른쪽 열 목록(columns)이 필요합니다.", step=i)
                _need(rcols, rk, i)
                bring = [c for c in rcols if c != rk]
                al = {c: (c if cols is None or c not in cols else f"{c}_r") for c in bring}
                sel = ["l.*"] + [f"r.{_q(c)} AS {_q(al[c])}" for c in bring]
                ctes.append(f"{new} AS (SELECT {', '.join(sel)} FROM {prev} l {'LEFT ' if jt == 'left' else ''}JOIN {t} r ON l.{_q(lk)} = r.{_q(rk)})")
                cols = (cols + [al[c] for c in bring]) if cols is not None else None
            elif op == "aggregate":
                gb = [_id(g, "그룹 열", i) for g in (s.get("group_by") or [])]
                aggs = s.get("aggs") or []
                if not gb and not aggs:
                    raise ApiError(400, "INVALID_FLOW", f"단계 {i + 1}: 그룹 열이나 집계가 필요합니다.", step=i)
                parts, nc = [_q(g) for g in gb], list(gb)
                for g in gb:
                    _need(cols, g, i)
                for a in aggs:
                    fn = a.get("fn")
                    if fn not in D_AGGS:
                        raise ApiError(400, "INVALID_FLOW", f"단계 {i + 1}: 집계는 {', '.join(D_AGGS)} 중 하나입니다.", step=i)
                    c = a.get("column") or "*"
                    if c == "*":
                        if fn != "count":
                            raise ApiError(400, "INVALID_FLOW", f"단계 {i + 1}: `*` 는 count 에만 쓸 수 있습니다.", step=i)
                    else:
                        _id(c, "집계 열", i)
                        _need(cols, c, i)
                    alias = _id(a.get("alias") or f"{fn}_{'all' if c == '*' else c}", "별칭", i)
                    parts.append(f"{fn.upper()}({'*' if c == '*' else _q(c)}) AS {_q(alias)}")
                    nc.append(alias)
                ctes.append(f"{new} AS (SELECT {', '.join(parts)} FROM {prev}{' GROUP BY ' + ', '.join(_q(g) for g in gb) if gb else ''})")
                cols = nc
            elif op == "sort":
                c = _id(s.get("column"), "열", i)
                _need(cols, c, i)
                ctes.append(f"{new} AS (SELECT * FROM {prev} ORDER BY {_q(c)} {'DESC' if s.get('desc') else 'ASC'})")
            elif op == "limit":
                try:
                    n = int(s.get("n"))
                except (TypeError, ValueError):
                    n = 0
                if not 1 <= n <= 100000:
                    raise ApiError(400, "INVALID_FLOW", f"단계 {i + 1}: 행 수는 1~100000 입니다.", step=i)
                ctes.append(f"{new} AS (SELECT * FROM {prev} LIMIT {n})")
        step_cols.append(list(cols) if cols is not None else None)
    last = f"s{len(ctes) - 1}"
    body = "WITH " + ", ".join(ctes) + f" SELECT * FROM {last}"
    return {"sql": body, "preview_sql": body + " LIMIT 20", "run_sql": f"CREATE OR REPLACE TABLE {out} AS {body}" if out else None, "output": out, "columns": cols, "step_columns": step_cols}


def _sample_flow():
    C = core.CAT
    return {"name": "gold 요약(샘플)", "steps": [
        {"op": "source", "table": f"{C}.gold.v_order_overview"},
        {"op": "filter", "column": "status", "cmp": "<>", "value": "CANCELLED"},
        {"op": "aggregate", "group_by": ["customer_id"], "aggs": [{"fn": "sum", "column": "total_boxes", "alias": "total_boxes"}, {"fn": "sum", "column": "supply_amount", "alias": "amount"}]},
        {"op": "sort", "column": "amount", "desc": True},
        {"op": "limit", "n": 20},
        {"op": "output", "target": f"{C}.gold.designer_top_customers"}],
        "schedule": {"enabled": False, "cron": "", "note": "표시만(실행되지 않음)"},
        "tip": "silver 단계부터 만들려면 silver 권한을 요청한 뒤 소스를 silver 테이블로 바꾸세요."}


def _clean_flow(doc):
    steps = doc.get("steps") or []
    if not isinstance(steps, list) or len(steps) > 12:
        raise ApiError(400, "INVALID_FLOW", "연산자는 12개까지입니다.")
    clean = []
    for s in steps:
        if not isinstance(s, dict) or s.get("op") not in OPS:
            raise ApiError(400, "INVALID_FLOW", "알 수 없는 연산자가 있습니다.")
        clean.append({k: v for k, v in s.items() if k in ("op", "table", "column", "cmp", "value", "columns", "left_key", "right_key", "type", "group_by", "aggs", "desc", "n", "target")})
    sc = doc.get("schedule") or {}
    return {"name": _s(doc.get("name"), 60) or "새 흐름", "steps": clean, "schedule": {"enabled": bool(sc.get("enabled")), "cron": _s(sc.get("cron"), 40), "note": "표시만(실행되지 않음)"}}


def _fail(e: ApiError):
    return {"status": "failed", "error": {"code": e.code, "message": e.message, "step": e.extra.get("step")}}


def _designer_register(app, actor_of, sess):
    base = "/api/sessions/{sid}/designer"

    def find(S, fid):
        f = S.setdefault("designer", {}).get(fid)
        if not f:
            raise ApiError(404, "FLOW_NOT_FOUND", "흐름을 찾을 수 없습니다.")
        return f

    def resolver(S, principal):
        def cols_of(table):
            r = core.run_sql(S, f"SELECT * FROM {table} LIMIT 0", principal, via="designer", system=True, need_warehouse=False)
            if r["status"] != "succeeded":
                e = r["error"]
                raise ApiError(400, e["code"], e["message"])
            return list(r["columns"])
        return cols_of

    @app.get(base)
    def des_list(sid: str, authorization: Optional[str] = Header(None)):
        S = sess(sid, actor_of(authorization))
        with core.lock_for(sid):
            return {"items": [{"id": f["id"], "name": f["name"], "steps": len(f["steps"]), "last_run": f.get("last_run")} for f in S.setdefault("designer", {}).values()], "note": DES_NOTE, "evidence_level": "LOCAL_EXECUTED"}

    @app.post(base + "/create")
    def des_create(sid: str, b: dict, authorization: Optional[str] = Header(None)):
        a = actor_of(authorization)
        S = sess(sid, a)
        with core.lock_for(sid):
            D = S.setdefault("designer", {})
            if len(D) >= 10:
                raise ApiError(429, "FLOW_LIMIT", "흐름은 세션당 10개까지입니다.")
            doc = _sample_flow() if b.get("sample") else {"name": b.get("name"), "steps": [{"op": "source", "table": ""}]}
            fid = "fl_" + uuid.uuid4().hex[:8]
            c = _clean_flow(doc) if b.get("sample") else {"name": _s(doc["name"], 60) or "새 흐름", "steps": [{"op": "source", "table": ""}], "schedule": {"enabled": False, "cron": "", "note": "표시만(실행되지 않음)"}}
            D[fid] = {"id": fid, "owner": a["user_id"], **c, "tip": doc.get("tip", ""), "last_run": None}
            core.save(S)
            return D[fid]

    @app.get(base + "/columns")
    def des_columns(sid: str, table: str, authorization: Optional[str] = Header(None)):
        a = actor_of(authorization)
        S = sess(sid, a)
        with core.lock_for(sid):
            try:
                return {"status": "ok", "table": table, "columns": resolver(S, _principal(a))(_tbl(table))}
            except ApiError as e:
                return _fail(e)

    @app.get(base + "/{fid}")
    def des_get(fid: str, sid: str, authorization: Optional[str] = Header(None)):
        S = sess(sid, actor_of(authorization))
        with core.lock_for(sid):
            return {**find(S, fid), "note": DES_NOTE}

    @app.post(base + "/{fid}/save")
    def des_save(fid: str, sid: str, b: dict, authorization: Optional[str] = Header(None)):
        S = sess(sid, actor_of(authorization))
        with core.lock_for(sid):
            f = find(S, fid)
            f.update(_clean_flow(b))
            core.save(S)
            return f

    def _gen(S, a, f, steps=None):
        return build_sql(steps if steps is not None else f["steps"], resolver(S, _principal(a)))

    @app.post(base + "/{fid}/validate")
    def des_validate(fid: str, sid: str, authorization: Optional[str] = Header(None)):
        a = actor_of(authorization)
        S = sess(sid, a)
        with core.lock_for(sid):
            f = find(S, fid)
            try:
                g = _gen(S, a, f)
                chk = core.run_sql(S, g["preview_sql"], _principal(a), via="designer", system=True, need_warehouse=False)
                if chk["status"] != "succeeded":
                    return {"status": "failed", "error": chk["error"], "sql": g["sql"]}
                return {"status": "ok", "step_columns": g["step_columns"], "columns": g["columns"], "sql": g["sql"], "output": g["output"], "note": DES_NOTE}
            except ApiError as e:
                return _fail(e)

    @app.post(base + "/{fid}/preview")
    def des_preview(fid: str, sid: str, b: dict, authorization: Optional[str] = Header(None)):
        a = actor_of(authorization)
        S = sess(sid, a)
        with core.lock_for(sid):
            f = find(S, fid)
            try:
                upto = b.get("upto")
                steps = [s for s in f["steps"] if s.get("op") != "output"]
                if isinstance(upto, int) and 0 <= upto < len(steps):
                    steps = steps[:upto + 1]
                g = _gen(S, a, f, steps)
            except ApiError as e:
                return _fail(e)
            r = core.run_sql(S, g["preview_sql"], _principal(a), via="designer", need_warehouse=True, actor_id=a["user_id"])
            core.save(S)
            if r["status"] != "succeeded":
                return {"status": "failed", "error": r["error"], "sql": g["preview_sql"]}
            return {"status": "ok", "columns": r["columns"], "rows": r["rows"], "sql": g["preview_sql"]}

    @app.post(base + "/{fid}/run")
    def des_run(fid: str, sid: str, authorization: Optional[str] = Header(None)):
        a = actor_of(authorization)
        S = sess(sid, a)
        with core.lock_for(sid):
            f = find(S, fid)
            try:
                g = _gen(S, a, f)
            except ApiError as e:
                return _fail(e)
            if not g["run_sql"]:
                return {"status": "failed", "error": {"code": "NO_OUTPUT", "message": "출력(output) 연산자가 없습니다. 마지막에 대상 테이블을 추가하세요."}, "sql": g["sql"]}
            r = core.run_sql(S, g["run_sql"], _principal(a), via="designer", need_warehouse=True, actor_id=a["user_id"])
            if r["status"] == "succeeded":
                n = core._conns[sid].execute(f"SELECT count(*) FROM {core.pfq(S, g['output'])}").fetchone()[0]
                f["last_run"] = {"at": core.now_utc(), "table": g["output"], "rows": n}
                core.audit(S, a["user_id"], "DESIGNER_RUN", g["output"], "succeeded", "LOCAL_EXECUTED", {"steps": len(f["steps"]), "rows": n})
            core.save(S)
            if r["status"] != "succeeded":
                return {"status": "failed", "error": r["error"], "sql": g["run_sql"]}
            return {"status": "ok", "table": g["output"], "rows": f["last_run"]["rows"], "sql": g["run_sql"], "columns": g["columns"],
                    "note": "대상 테이블을 CREATE OR REPLACE 로 다시 만들었습니다. Catalog > History 탭에서 버전을 확인하세요."}

    @app.post(base + "/{fid}/delete")
    def des_delete(fid: str, sid: str, authorization: Optional[str] = Header(None)):
        S = sess(sid, actor_of(authorization))
        with core.lock_for(sid):
            find(S, fid)
            del S["designer"][fid]
            core.save(S)
            return {"deleted": fid}


def register(app, actor_of, sess):
    _dash_register(app, actor_of, sess)
    _gc_register(app, actor_of, sess)
    _designer_register(app, actor_of, sess)
