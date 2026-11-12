"""ML·MLflow(실험 추적)·UC 모델 레지스트리·특성 테이블·모델 서빙 처리기 — 교육용 시뮬레이션.

정직한 한계(화면에도 표시):
- 실제 MLflow·Databricks Model Serving·Feature Engineering 이 아니다. 순수 파이썬(표준 라이브러리) 계산이며 결과는 LOCAL_EXECUTED.
- 데이터는 UC 테이블 SELECT(권한 검사 포함)로 읽으며 run_sql 한계로 최대 500행이다.
- 알고리즘은 선형 회귀(릿지)·로지스틱 회귀·기준선 3가지뿐이다(scikit-learn 아님).
- 모델 등록 권한은 'CREATE MODEL' 대신 CREATE TABLE 권한(또는 소유자·관리자)으로 단순화했다.
- Academy 코스의 Genie Code Agent Mode·Lakeflow Jobs 자동화는 여기서 다루지 않는다(레슨 본문은 조회하지 못했다).
"""
from __future__ import annotations

import hashlib
import math
import re
import uuid
from typing import Optional

from fastapi import Header

from . import core, serving
from .core import ApiError

MAX_ROWS = 500
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_PART = re.compile(r"^[a-z][a-z0-9_]{0,40}$")
_ALIAS = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,30}$")
ALGOS = {"linear": "선형 회귀(릿지)", "logistic": "로지스틱 회귀", "baseline": "기준선(평균/최빈값)"}
LIMITS = ["교육용 시뮬레이션입니다. 실제 MLflow·Model Serving 이 아니며 순수 파이썬으로 계산합니다(LOCAL_EXECUTED).",
          f"UC 테이블에서 최대 {MAX_ROWS}행만 읽습니다. 알고리즘은 선형·로지스틱·기준선 3가지입니다.",
          "모델 등록은 CREATE TABLE 권한(또는 소유자·관리자)으로 단순화했습니다(실제는 CREATE MODEL).",
          "Genie Code Agent Mode·Lakeflow Jobs 자동화는 다루지 않습니다."]


def _ml(S) -> dict:
    m = S.setdefault("ml", {})
    m.setdefault("experiments", {})
    m.setdefault("runs", [])
    m.setdefault("models", {})
    m.setdefault("features", {})
    return m


def _now():
    return core.now_utc()


def _principal(a):
    return core.ADMIN if a["role"] == "admin" else core.TRAINEE


def _err(status, code, msg, **kw):
    return ApiError(status, code, msg, **kw)


# ---------------------------------------------------------------- 데이터 읽기
def _fetch(S, principal, actor, sql):
    r = core.run_sql(S, sql, principal, via="ml", need_warehouse=False, actor_id=actor["user_id"])
    if r["status"] != "succeeded":
        e = r["error"] or {}
        raise _err(400, e.get("code", "SQL_FAILED"), e.get("message", "SQL 실패"), hint=e.get("hint"))
    return r["columns"], r["rows"]


def _check_table(name: str):
    parts = (name or "").replace("`", "").split(".")
    if len(parts) != 3 or not all(_IDENT.match(p) for p in parts):
        raise _err(400, "INVALID_NAME", "테이블은 catalog.schema.table 3단계 이름으로 입력하세요.")
    return ".".join(parts)


def _cols(cols, label="열"):
    cols = [str(c) for c in (cols or [])]
    if not cols or not all(_IDENT.match(c) for c in cols):
        raise _err(400, "INVALID_COLUMNS", f"{label} 이름이 올바르지 않습니다(영문·숫자·_).")
    return cols


def _num(v):
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if isinstance(v, (int, float)):
        return float(v)
    raise ValueError


def _load(S, principal, actor, spec):
    """학습 데이터를 읽어 (feature_names, X, y, info, lookups) 를 돌려준다."""
    ts = spec.get("training_set")
    label = _cols([(ts or spec).get("label")], "라벨")[0]
    feats = [] if ts else _cols(spec.get("features"), "특성")
    lookups = []
    if ts:   # 특성 테이블 조인(training set)
        lt = _check_table(ts.get("label_table"))
        cols, rows = _fetch(S, principal, actor, f"SELECT * FROM {lt} LIMIT {MAX_ROWS}")
        base = [dict(zip(cols, r)) for r in rows]
        feats = []
        for lk in ts.get("lookups") or []:
            ft = _check_table(lk.get("feature_table"))
            reg = _ml(S)["features"].get(ft)
            if not reg:
                raise _err(400, "NOT_A_FEATURE_TABLE", f"`{ft}`은(는) 특성 테이블로 등록되어 있지 않습니다.", hint="특성 테이블 탭에서 먼저 등록하세요.")
            fcols = _cols(lk.get("features"), "특성")
            for k in reg["pk"]:
                if k not in cols:
                    raise _err(400, "JOIN_KEY_MISSING", f"라벨 테이블에 키 열 `{k}`이(가) 없습니다.")
            fc, fr = _fetch(S, principal, actor, f"SELECT {', '.join(reg['pk'] + fcols)} FROM {ft} LIMIT {MAX_ROWS}")
            idx = {tuple(r[:len(reg['pk'])]): dict(zip(fc, r)) for r in fr}
            for b in base:
                hit = idx.get(tuple(b.get(k) for k in reg["pk"]))
                for c in fcols:
                    b[c] = hit[c] if hit else None
            feats += [c for c in fcols if c not in feats]
            lookups.append({"feature_table": ft, "pk": reg["pk"], "features": fcols})
        if not feats:
            raise _err(400, "NO_FEATURES", "조회할 특성을 지정하세요.")
        table_src = f"{lt} ⋈ " + ", ".join(l["feature_table"] for l in lookups)
        dicts = base
    else:
        tbl = _check_table(spec.get("table"))
        cols, rows = _fetch(S, principal, actor, f"SELECT {', '.join(feats + [label])} FROM {tbl} LIMIT {MAX_ROWS}")
        dicts = [dict(zip(cols, r)) for r in rows]
        table_src = tbl
    X, y, dropped, keys = [], [], 0, []
    for d in dicts:
        try:
            xr = [_num(d[c]) for c in feats]
            yr = d[label]
            if yr is None or any(v is None for v in xr):
                raise ValueError
            yr = _num(yr)
        except (ValueError, KeyError, TypeError):
            if any(d.get(c) is not None and not isinstance(d.get(c), (int, float, bool)) for c in feats + [label]):
                raise _err(400, "NON_NUMERIC", "특성과 라벨은 숫자(또는 불리언)여야 합니다. 문자열 열은 SQL로 숫자 코드로 바꿔 주세요.")
            dropped += 1
            continue
        if any(math.isnan(v) or math.isinf(v) for v in xr + [yr]):
            dropped += 1
            continue
        X.append(xr); y.append(yr); keys.append(repr(d))
    info = {"source": table_src, "rows_read": len(dicts), "rows_used": len(X), "rows_dropped_null": dropped, "truncated": len(dicts) >= MAX_ROWS}
    return feats, label, X, y, keys, info, lookups


def _split(X, y, keys, ratio, seed):
    """해시 기반 결정적 분할(행 순서가 바뀌어도 같은 행은 같은 쪽)."""
    tr, te = [], []
    for i, k in enumerate(keys):
        h = int(hashlib.sha256(f"{seed}:{k}".encode("utf-8")).hexdigest()[:8], 16) / 0xFFFFFFFF
        (te if h < ratio else tr).append(i)
    if len(te) == 0 and len(tr) > 2:
        te.append(tr.pop())
    if len(tr) == 0 and len(te) > 2:
        tr.append(te.pop())
    if len(tr) < 2 or len(te) < 1:
        raise _err(400, "DATA_TOO_SMALL", "학습/테스트로 나눌 행이 부족합니다(최소 4행 권장).")
    return tr, te


# ---------------------------------------------------------------- 알고리즘(순수 파이썬)
def _solve(A, b):
    n = len(A)
    M = [row[:] + [b[i]] for i, row in enumerate(A)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(M[r][c]))
        if abs(M[p][c]) < 1e-12:
            raise _err(400, "SINGULAR", "특성들이 서로 완전히 겹쳐(공선성) 풀 수 없습니다. 특성을 줄이거나 l2(릿지)를 키우세요.")
        M[c], M[p] = M[p], M[c]
        for r in range(c + 1, n):
            f = M[r][c] / M[c][c]
            if f:
                for k in range(c, n + 1):
                    M[r][k] -= f * M[c][k]
    x = [0.0] * n
    for r in range(n - 1, -1, -1):
        x[r] = (M[r][n] - sum(M[r][k] * x[k] for k in range(r + 1, n))) / M[r][r]
    return x


def _fit_linear(X, y, l2):
    n, d = len(X), len(X[0])
    A = [[0.0] * (d + 1) for _ in range(d + 1)]
    b = [0.0] * (d + 1)
    for xi, yi in zip(X, y):
        v = xi + [1.0]
        for i in range(d + 1):
            b[i] += v[i] * yi
            for j in range(d + 1):
                A[i][j] += v[i] * v[j]
    for i in range(d):          # 절편은 벌점 제외
        A[i][i] += l2
    w = _solve(A, b)
    return {"coef": w[:d], "intercept": w[d]}


def _sigmoid(z):
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-min(z, 500)))
    e = math.exp(max(z, -500))
    return e / (1.0 + e)


def _fit_logistic(X, y, l2, lr, epochs):
    d = len(X[0])
    mean = [sum(r[j] for r in X) / len(X) for j in range(d)]
    std = [math.sqrt(sum((r[j] - mean[j]) ** 2 for r in X) / len(X)) or 1.0 for j in range(d)]
    Z = [[(r[j] - mean[j]) / std[j] for j in range(d)] for r in X]
    w, b0 = [0.0] * d, 0.0
    n = len(Z)
    for _ in range(epochs):
        gw, gb = [0.0] * d, 0.0
        for zi, yi in zip(Z, y):
            p = _sigmoid(sum(wj * zj for wj, zj in zip(w, zi)) + b0) - yi
            for j in range(d):
                gw[j] += p * zi[j]
            gb += p
        for j in range(d):
            w[j] -= lr * (gw[j] / n + l2 * w[j])
        b0 -= lr * gb / n
    coef = [w[j] / std[j] for j in range(d)]
    return {"coef": coef, "intercept": b0 - sum(coef[j] * mean[j] for j in range(d))}


def _predict_raw(model, row):
    if model["algo"] == "baseline":
        return model["constant"]
    return sum(c * v for c, v in zip(model["coef"], row)) + model["intercept"]


def _predict(model, row):
    z = _predict_raw(model, row)
    if model["task"] == "classification":
        p = z if model["algo"] == "baseline" else _sigmoid(z)
        return (1 if p >= 0.5 else 0), p
    return z, None


def _reg_metrics(y, p):
    n = len(y)
    mse = sum((a - b) ** 2 for a, b in zip(y, p)) / n
    mean = sum(y) / n
    sst = sum((a - mean) ** 2 for a in y)
    return {"rmse": math.sqrt(mse), "mae": sum(abs(a - b) for a, b in zip(y, p)) / n, "r2": (1 - sum((a - b) ** 2 for a, b in zip(y, p)) / sst) if sst > 1e-12 else 0.0}


def _cls_metrics(y, pred):
    tp = sum(1 for a, b in zip(y, pred) if a == 1 and b == 1)
    fp = sum(1 for a, b in zip(y, pred) if a == 0 and b == 1)
    fn = sum(1 for a, b in zip(y, pred) if a == 1 and b == 0)
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    return {"accuracy": sum(1 for a, b in zip(y, pred) if a == b) / len(y), "precision": prec, "recall": rec, "f1": (2 * prec * rec / (prec + rec)) if prec + rec else 0.0}


def train_model(S, actor, spec: dict) -> dict:
    principal = _principal(actor)
    algo = spec.get("algo", "linear")
    if algo not in ALGOS:
        raise _err(400, "UNKNOWN_ALGO", f"알고리즘: {', '.join(ALGOS)}")
    task = "classification" if algo == "logistic" else ("regression" if algo == "linear" else (spec.get("task") or "regression"))
    if task not in ("regression", "classification"):
        raise _err(400, "UNKNOWN_TASK", "task 는 regression 또는 classification 입니다.")
    ratio = float(spec.get("test_ratio", 0.25))
    if not 0.05 <= ratio <= 0.6:
        raise _err(400, "BAD_SPLIT", "test_ratio 는 0.05~0.6 입니다.")
    seed = int(spec.get("seed", 42))
    l2 = float(spec.get("l2", 0.0))
    lr, epochs = float(spec.get("lr", 0.2)), int(spec.get("epochs", 400))
    if not (0 < lr <= 5 and 10 <= epochs <= 3000 and l2 >= 0):
        raise _err(400, "BAD_PARAM", "lr(0~5], epochs 10~3000, l2 ≥ 0 범위를 확인하세요.")
    exp = str(spec.get("experiment") or "default")[:60]
    feats, label, X, y, keys, info, lookups = _load(S, principal, actor, spec)
    if task == "classification" and any(v not in (0.0, 1.0) for v in y):
        raise _err(400, "LABEL_NOT_BINARY", "분류 라벨은 0/1(또는 불리언)이어야 합니다.", hint="SQL에서 CASE WHEN 으로 0/1 열을 만드세요.")
    tr, te = _split(X, y, keys, ratio, seed)
    Xtr, ytr = [X[i] for i in tr], [y[i] for i in tr]
    Xte, yte = [X[i] for i in te], [y[i] for i in te]
    if len(feats) > 30 or (algo == "logistic" and epochs * max(1, len(Xtr)) * max(1, len(feats)) > 8_000_000):
        raise _err(400, "TRAIN_BUDGET", "학습 비용이 너무 큽니다(특성 30개 이하, epochs×행×특성 ≤ 800만). epochs 나 특성 수를 줄이세요.")
    started = _now()
    if algo == "linear":
        m = _fit_linear(Xtr, ytr, l2)
    elif algo == "logistic":
        m = _fit_logistic(Xtr, ytr, l2, lr, epochs)
    else:
        m = {"constant": (sum(ytr) / len(ytr)) if task == "regression" else float(1 if sum(ytr) * 2 >= len(ytr) else 0)}
    model = {"algo": algo, "task": task, "features": feats, "label": label, **m, "lookups": lookups}
    metrics = {}
    for nm, XX, yy in (("train", Xtr, ytr), ("test", Xte, yte)):
        pr = [_predict(model, r) for r in XX]
        mm = _reg_metrics(yy, [p[0] for p in pr]) if task == "regression" else _cls_metrics(yy, [p[0] for p in pr])
        metrics.update({f"{nm}_{k}": round(v, 6) for k, v in mm.items()})
    mlx = _ml(S)
    mlx["experiments"].setdefault(exp, {"name": exp, "created": started, "created_by": actor["user_id"]})
    run = {"run_id": "r_" + uuid.uuid4().hex[:10], "experiment": exp, "name": str(spec.get("run_name") or f"{algo}-{len(mlx['runs']) + 1}")[:60], "status": "FINISHED", "start": started, "end": _now(),
           "user": actor["user_id"], "principal": principal, "params": {"algo": algo, "task": task, "features": feats, "label": label, "test_ratio": ratio, "seed": seed, "l2": l2, **({"lr": lr, "epochs": epochs} if algo == "logistic" else {})},
           "metrics": metrics, "tags": {"source": "ml-sim", "logging": "자동 기록(시뮬레이션)"}, "data": {**info, "train_n": len(tr), "test_n": len(te)},
           "artifacts": {"model": model}, "evidence_level": "LOCAL_EXECUTED"}
    mlx["runs"].append(run)
    if len(mlx["runs"]) > 200:
        del mlx["runs"][:len(mlx["runs"]) - 200]
    core.audit(S, actor["user_id"], "ML_RUN", run["run_id"], "succeeded", "LOCAL_EXECUTED", {"algo": algo, "experiment": exp}, effective=principal)
    return run


def _run_view(r, full=False):
    v = {k: r[k] for k in ("run_id", "experiment", "name", "status", "start", "end", "user", "params", "metrics", "tags", "data", "evidence_level")}
    m = r["artifacts"]["model"]
    v["model_summary"] = {"algo": m["algo"], "task": m["task"], "features": m["features"], "coef": [round(c, 6) for c in m.get("coef", [])], "intercept": round(m.get("intercept", m.get("constant", 0.0)), 6), "lookups": m.get("lookups", [])}
    return v


def _find_run(S, run_id):
    for r in _ml(S)["runs"]:
        if r["run_id"] == run_id:
            return r
    raise _err(404, "RUN_NOT_FOUND", f"런 `{run_id}`을(를) 찾을 수 없습니다.")


# ---------------------------------------------------------------- 레지스트리
def _model_name(S, name):
    parts = (name or "").split(".")
    if len(parts) != 3 or not all(_PART.match(p) for p in parts):
        raise _err(400, "INVALID_NAME", "모델 이름은 catalog.schema.model 3단계(영문 소문자·숫자·_)입니다.")
    return ".".join(parts), parts


def register_model(S, actor, run_id, name):
    principal = _principal(actor)
    fq, (cat, db, _m) = _model_name(S, name)
    run = _find_run(S, run_id)
    if run["status"] != "FINISHED":
        raise _err(400, "RUN_NOT_FINISHED", "완료된 런만 등록할 수 있습니다.")
    c = core._conns[S["id"]]
    phys_db = db if cat == core.CAT else f"{cat}__{db}"
    if cat != core.CAT and cat not in S.get("catalogs", {}):
        raise _err(404, "CATALOG_NOT_FOUND", f"catalog `{cat}`을(를) 찾을 수 없습니다.")
    if not core._exists(c, "schema", [core.CAT, phys_db]):
        raise _err(404, "SCHEMA_NOT_FOUND", f"schema `{cat}.{db}`을(를) 찾을 수 없습니다.")
    sec_s = f"schema:{cat}.{db}"
    for priv, sec in (("USE CATALOG", f"catalog:{cat}"), ("USE SCHEMA", sec_s)):
        if not core.has_priv(S, principal, priv, sec):
            raise _err(403, "INSUFFICIENT_PERMISSIONS", f"{principal}: {sec} 에 {priv} 권한이 없습니다.", missing={"privilege": priv, "securable": sec})
    models = _ml(S)["models"]
    mod = models.get(fq)
    if mod is None:
        if not (core.has_priv(S, principal, "CREATE MODEL", sec_s) or core.has_priv(S, principal, "CREATE TABLE", sec_s)):
            raise _err(403, "INSUFFICIENT_PERMISSIONS", f"{sec_s} 에 CREATE MODEL(시뮬레이터는 CREATE TABLE로 단순화) 권한이 없습니다.", missing={"privilege": "CREATE MODEL", "securable": sec_s})
        mod = models[fq] = {"name": fq, "owner": principal, "created": _now(), "versions": [], "aliases": {}}
    elif not (mod["owner"] == principal or core.is_admin(S, principal) or core.has_priv(S, principal, "CREATE TABLE", sec_s)):
        raise _err(403, "INSUFFICIENT_PERMISSIONS", f"모델 `{fq}`의 새 버전을 만들 권한이 없습니다(소유자·관리자·CREATE 권한 필요).")
    ver = (mod["versions"][-1]["version"] + 1) if mod["versions"] else 1
    mod["versions"].append({"version": ver, "run_id": run_id, "created": _now(), "by": actor["user_id"], "registered_principal": principal, "metrics": run["metrics"], "params": run["params"],
                            "model": run["artifacts"]["model"], "data": run["data"]})
    run["tags"]["registered_model"] = f"{fq}/v{ver}"
    core.audit(S, actor["user_id"], "ML_REGISTER", fq, "succeeded", "LOCAL_EXECUTED", {"version": ver, "run": run_id}, effective=principal)
    return {"name": fq, "version": ver}


def set_alias(S, actor, name, alias, version):
    principal = _principal(actor)
    mod = _ml(S)["models"].get(name)
    if not mod:
        raise _err(404, "MODEL_NOT_FOUND", f"모델 `{name}`을(를) 찾을 수 없습니다.")
    if not (mod["owner"] == principal or core.is_admin(S, principal)):
        raise _err(403, "INSUFFICIENT_PERMISSIONS", "별칭은 모델 소유자·관리자만 바꿀 수 있습니다.")
    if not _ALIAS.match(alias or ""):
        raise _err(400, "INVALID_ALIAS", "별칭은 영문으로 시작하는 영문·숫자·_-(31자 이하)입니다.")
    if version in (None, "", 0):
        mod["aliases"].pop(alias, None)
        core.audit(S, actor["user_id"], "ML_ALIAS", name, "removed", "LOCAL_EXECUTED", {"alias": alias}, effective=principal)
        return {"name": name, "aliases": mod["aliases"]}
    if not str(version).isascii() or not str(version).isdigit():
        raise _err(400, "BAD_VERSION", "버전은 숫자여야 합니다.")
    v = int(version)
    if not any(x["version"] == v for x in mod["versions"]):
        raise _err(404, "VERSION_NOT_FOUND", f"버전 {v}이(가) 없습니다.")
    mod["aliases"][alias] = v
    core.audit(S, actor["user_id"], "ML_ALIAS", name, "set", "LOCAL_EXECUTED", {"alias": alias, "version": v}, effective=principal)
    return {"name": name, "aliases": mod["aliases"]}


def resolve(S, name, ref):
    mod = _ml(S)["models"].get(name)
    if not mod:
        raise _err(404, "MODEL_NOT_FOUND", f"모델 `{name}`을(를) 찾을 수 없습니다.")
    ref = str(ref or "").strip()
    if ref.startswith("@"):
        v = mod["aliases"].get(ref[1:])
        if v is None:
            raise _err(404, "ALIAS_NOT_FOUND", f"별칭 `{ref}`이(가) 없습니다(모델 {name}).", hint="모델 레지스트리 탭에서 별칭을 지정하세요.")
    elif ref.isascii() and ref.isdigit():
        v = int(ref)
    else:
        raise _err(400, "BAD_REF", "ref 는 '@별칭' 또는 버전 숫자입니다. 예: @champion, 3")
    ent = next((x for x in mod["versions"] if x["version"] == v), None)
    if not ent:
        raise _err(404, "VERSION_NOT_FOUND", f"모델 `{name}` 에 버전 {v}이(가) 없습니다.")
    return mod, ent


# ---------------------------------------------------------------- 특성 테이블
def register_feature_table(S, actor, table, pk, description="", from_sql=None):
    principal = _principal(actor)
    tbl = _check_table(table)
    pk = _cols(pk, "기본키")
    if from_sql:   # 특성 엔지니어링 결과를 UC 테이블로 저장
        s = str(from_sql).strip().rstrip(";")
        if not re.match(r"(?is)^\s*(with|select)\b", s):
            raise _err(400, "BAD_SQL", "특성 SQL 은 SELECT(또는 WITH)로 시작해야 합니다.")
        _fetch(S, principal, actor, f"CREATE OR REPLACE TABLE {tbl} AS {s}")
    cols, _ = _fetch(S, principal, actor, f"SELECT * FROM {tbl} LIMIT 1")
    for k in pk:
        if k not in cols:
            raise _err(400, "PK_NOT_FOUND", f"기본키 열 `{k}`이(가) 테이블에 없습니다.")
    _, dup = _fetch(S, principal, actor, f"SELECT {', '.join(pk)}, count(*) AS n FROM {tbl} GROUP BY {', '.join(pk)} HAVING count(*) > 1 LIMIT 1")
    if dup:
        raise _err(400, "PK_NOT_UNIQUE", f"기본키 {pk} 가 유일하지 않습니다(중복 예: {dup[0][:-1]}).", hint="특성 테이블의 키는 행마다 유일해야 합니다.")
    ft = {"table": tbl, "pk": pk, "columns": cols, "description": str(description)[:200], "created": _now(), "by": actor["user_id"], "numeric_note": "학습·서빙에 쓸 특성은 숫자 열이어야 합니다."}
    _ml(S)["features"][tbl] = ft
    core.audit(S, actor["user_id"], "ML_FEATURE", tbl, "registered", "LOCAL_EXECUTED", {"pk": pk}, effective=principal)
    return ft


# ---------------------------------------------------------------- 서빙 처리기
def _serve_validate(S, config):
    if not config.get("model"):
        raise _err(400, "CONFIG_MODEL_REQUIRED", "config.model(catalog.schema.model)이 필요합니다.")
    resolve(S, str(config["model"]), config.get("ref") or "@champion")


def _serve_handler(S, ep, payload):
    cfg = ep["config"]
    mod, ent = resolve(S, cfg["model"], cfg.get("ref") or "@champion")
    m = ent["model"]
    feats = m["features"]
    recs = payload.get("dataframe_records")
    inputs = payload.get("inputs")
    if recs is None and inputs is None:
        raise _err(400, "INVALID_INPUT", "payload 에 dataframe_records(객체 목록) 또는 inputs(숫자 배열 목록)가 필요합니다.")
    rows = []
    if recs is not None:
        if not isinstance(recs, list) or not recs or len(recs) > 20:
            raise _err(400, "INVALID_INPUT", "dataframe_records 는 1~20개의 객체 목록입니다.")
        rows = [dict(r) if isinstance(r, dict) else None for r in recs]
        if any(r is None for r in rows):
            raise _err(400, "INVALID_INPUT", "dataframe_records 의 각 항목은 객체여야 합니다.")
        # 특성 조회(feature lookup): 키만 오면 특성 테이블에서 채운다(모델을 등록한 주체의 권한으로 읽음)
        for lk in m.get("lookups", []):
            need = [c for c in lk["features"] if any(c not in r for r in rows)]
            if need:
                principal = payload.get("__principal", core.TRAINEE)        # 질의한 사람의 권한으로 특성 조회(모델 등록자 권한 아님)
                for r in rows:
                    if any(c not in r for c in lk["features"]):
                        if any(k not in r for k in lk["pk"]):
                            raise _err(400, "INVALID_INPUT", f"특성 조회에 필요한 키 {lk['pk']} 가 없습니다.")
                        cond = " AND ".join(f"{k} = {_lit(r[k])}" for k in lk["pk"])
                        res = core.run_sql(S, f"SELECT {', '.join(lk['features'])} FROM {lk['feature_table']} WHERE {cond} LIMIT 1", principal, via="ml", need_warehouse=False)
                        if res["status"] != "succeeded":
                            raise _err(400, (res["error"] or {}).get("code", "LOOKUP_FAILED"), (res["error"] or {}).get("message", "특성 조회 실패"))
                        if not res["rows"]:
                            raise _err(404, "FEATURE_ROW_NOT_FOUND", f"특성 테이블 `{lk['feature_table']}`에 키 {[r[k] for k in lk['pk']]} 행이 없습니다.")
                        r.update(dict(zip(lk["features"], res["rows"][0])))
        try:
            X = [[_num(r[f]) for f in feats] for r in rows]
        except KeyError as e:
            raise _err(400, "INVALID_INPUT", f"특성 {e.args[0]} 가 입력에 없습니다. 필요한 특성: {feats}")
        except (ValueError, TypeError):
            raise _err(400, "INVALID_INPUT", "특성 값은 숫자여야 합니다.")
    else:
        if not isinstance(inputs, list) or not inputs or len(inputs) > 20 or any(not isinstance(r, list) or len(r) != len(feats) for r in inputs):
            raise _err(400, "INVALID_INPUT", f"inputs 는 길이 {len(feats)}(특성 순서 {feats})의 숫자 배열 목록(최대 20)입니다.")
        try:
            X = [[_num(v) for v in r] for r in inputs]
        except (ValueError, TypeError):
            raise _err(400, "INVALID_INPUT", "특성 값은 숫자여야 합니다.")
    pr = [_predict(m, r) for r in X]
    out = {"predictions": [round(p[0], 6) if isinstance(p[0], float) else p[0] for p in pr], "model": cfg["model"], "model_version": ent["version"], "ref": cfg.get("ref") or "@champion", "task": m["task"]}
    if m["task"] == "classification":
        out["probabilities"] = [round(p[1], 6) for p in pr]
    return out


def _lit(v):
    """특성 조회 키 값을 SQL 리터럴로: 숫자(유한)·짧은 문자열만 허용하고 databricks 방언 이스케이프를 쓴다."""
    if isinstance(v, bool) or v is None or isinstance(v, (dict, list)):
        raise _err(400, "INVALID_INPUT", "특성 조회 키는 숫자나 문자열이어야 합니다.")
    if isinstance(v, (int, float)):
        if isinstance(v, float) and v != v or v in (float("inf"), float("-inf")):
            raise _err(400, "INVALID_INPUT", "특성 조회 키에 NaN/Inf 는 쓸 수 없습니다.")
        return repr(v)
    if len(str(v)) > 64:
        raise _err(400, "INVALID_INPUT", "특성 조회 키 문자열은 64자 이하여야 합니다.")
    return core.sql_str(v)


serving.register_handler("model", _serve_handler, _serve_validate)


# ---------------------------------------------------------------- 라우트
def register(app, actor_of, sess):
    def ctx(sid, authorization):
        a = actor_of(authorization)
        return a, sess(sid, a)

    @app.get("/api/sessions/{sid}/ml/state")
    def ml_state(sid: str, authorization: Optional[str] = Header(None)):
        a, S = ctx(sid, authorization)
        with core.lock_for(sid):
            m = _ml(S)
            runs = [_run_view(r) for r in reversed(m["runs"])]
            models = [{"name": x["name"], "owner": x["owner"], "created": x["created"], "aliases": x["aliases"],
                       "versions": [{"version": v["version"], "run_id": v["run_id"], "created": v["created"], "metrics": v["metrics"], "task": v["model"]["task"], "algo": v["model"]["algo"], "features": v["model"]["features"]} for v in x["versions"]]} for x in m["models"].values()]
            return {"experiments": list(m["experiments"].values()), "runs": runs, "models": models, "features": list(m["features"].values()), "algos": ALGOS, "max_rows": MAX_ROWS,
                    "limits": LIMITS, "evidence_level": "LOCAL_EXECUTED"}

    @app.post("/api/sessions/{sid}/ml/experiments")
    def ml_exp(sid: str, b: dict, authorization: Optional[str] = Header(None)):
        a, S = ctx(sid, authorization)
        with core.lock_for(sid):
            name = str(b.get("name", "")).strip()[:60]
            if not name:
                raise _err(400, "INVALID_NAME", "실험 이름이 필요합니다.")
            e = _ml(S)["experiments"].setdefault(name, {"name": name, "created": _now(), "created_by": a["user_id"]})
            core.save(S)
            return e

    @app.post("/api/sessions/{sid}/ml/train")
    def ml_train(sid: str, b: dict, authorization: Optional[str] = Header(None)):
        a, S = ctx(sid, authorization)
        with core.lock_for(sid):
            try:
                run = train_model(S, a, b)
            except ValueError as e:
                raise _err(400, "BAD_PARAM", f"입력 값 형식이 올바르지 않습니다: {e}")
            core.save(S)
            return _run_view(run)

    @app.post("/api/sessions/{sid}/ml/runs/{run_id}/delete")
    def ml_run_delete(sid: str, run_id: str, authorization: Optional[str] = Header(None)):
        a, S = ctx(sid, authorization)
        with core.lock_for(sid):
            r = _find_run(S, run_id)
            if r["tags"].get("registered_model"):
                raise _err(409, "RUN_REGISTERED", "모델로 등록된 런은 삭제할 수 없습니다.")
            _ml(S)["runs"].remove(r)
            core.save(S)
            return {"deleted": run_id}

    @app.post("/api/sessions/{sid}/ml/models/register")
    def ml_register(sid: str, b: dict, authorization: Optional[str] = Header(None)):
        a, S = ctx(sid, authorization)
        with core.lock_for(sid):
            r = register_model(S, a, str(b.get("run_id", "")), str(b.get("name", "")))
            core.save(S)
            return r

    @app.post("/api/sessions/{sid}/ml/models/alias")
    def ml_alias(sid: str, b: dict, authorization: Optional[str] = Header(None)):
        a, S = ctx(sid, authorization)
        with core.lock_for(sid):
            r = set_alias(S, a, str(b.get("name", "")), str(b.get("alias", "")), b.get("version"))
            core.save(S)
            return r

    @app.post("/api/sessions/{sid}/ml/models/get")
    def ml_get(sid: str, b: dict, authorization: Optional[str] = Header(None)):
        a, S = ctx(sid, authorization)
        with core.lock_for(sid):
            mod, ent = resolve(S, str(b.get("name", "")), b.get("ref"))
            m = ent["model"]
            return {"name": mod["name"], "version": ent["version"], "aliases": mod["aliases"], "metrics": ent["metrics"], "params": ent["params"], "features": m["features"], "task": m["task"],
                    "coef": [round(c, 6) for c in m.get("coef", [])], "intercept": round(m.get("intercept", m.get("constant", 0.0)), 6), "lookups": m.get("lookups", [])}

    @app.post("/api/sessions/{sid}/ml/features")
    def ml_feature(sid: str, b: dict, authorization: Optional[str] = Header(None)):
        a, S = ctx(sid, authorization)
        with core.lock_for(sid):
            ft = register_feature_table(S, a, str(b.get("table", "")), b.get("pk") or [], str(b.get("description", "")), b.get("from_sql"))
            core.save(S)
            return ft

    @app.post("/api/sessions/{sid}/ml/features/delete")
    def ml_feature_del(sid: str, b: dict, authorization: Optional[str] = Header(None)):
        a, S = ctx(sid, authorization)
        with core.lock_for(sid):
            t = str(b.get("table", ""))
            if t not in _ml(S)["features"]:
                raise _err(404, "FEATURE_TABLE_NOT_FOUND", "등록되지 않은 특성 테이블입니다.")
            del _ml(S)["features"][t]
            core.save(S)
            return {"deleted": t}
