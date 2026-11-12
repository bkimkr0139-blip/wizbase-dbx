"""생성형 AI(AI Playground·AI Search 인덱스·RAG 에이전트·평가·배포) — 교육용 시뮬레이션.

중요한 한계(화면에도 표시):
- 실제 LLM·임베딩을 쓰지 않는다(외부 호출 없음). '모의 모델'은 컨텍스트에서 관련 문장을 골라 지시(한 문장/불릿/JSON)에 맞춰 늘어놓을 뿐이다.
- AI Search 인덱스는 임베딩이 아니라 BM25 키워드 검색(한글은 문자 bi-gram)이다. 의미 유사도 검색이 아니므로 동의어·바꿔 말하기는 못 찾는다.
- 목적은 '구조 연습'이다: 인덱스 동기화(STALE), 검색→프롬프트→생성의 trace, 인용, 평가 지표(hit@k·MRR·근거성), 배포 게이트.
- 근거: Academy 'Get started with Databricks for generative AI' 코스 개요(2026-11-12 관찰). 레슨 본문은 조회하지 않았다.

상태는 S["genai"] 에 JSON 으로 저장한다. 데이터 접근은 모두 core.run_sql(via="rag") 경유라 UC 권한·쿼리 이력이 적용된다.
"""
from __future__ import annotations

import math
import re
import time
import uuid
from typing import Optional

from fastapi import Header

from . import core, serving
from .core import ApiError

EVIDENCE = "SIMULATED"
LIMIT_NOTE = ("모의 모델(실제 LLM 아님)과 키워드(BM25) 검색으로 구조만 연습합니다. 의미 기반 임베딩 검색이 아니며, 답은 검색된 문서 문장을 골라 늘어놓은 것입니다.")
MAX_ROWS = 500
DOC_TABLE = "food_dev.gold.doc_chunks"
_UC3 = re.compile(r"^[a-z][a-z0-9_]{0,40}\.[a-z][a-z0-9_]{0,40}\.[a-z][a-z0-9_]{0,40}$")
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,40}$")
STYLES = {"sentence": "한 문장", "bullets": "불릿", "json": "JSON", "paragraph": "짧은 문단"}

# ------------------------------------------------------------------ 샘플 문서(직접 작성한 일반 설명, 공식 문서 복제 아님)
DOCS = [
    ("D01", "Unity Catalog 이름 체계", "Unity Catalog에서 데이터 이름은 catalog.schema.table 세 단계입니다. catalog는 가장 큰 묶음이고 schema는 그 안의 폴더 같은 단위입니다. 이름을 세 단계로 쓰면 어느 환경의 테이블인지 헷갈리지 않습니다.", "governance"),
    ("D02", "권한은 부모와 자식을 따로 본다", "테이블을 조회하려면 테이블에 SELECT 권한이 있어야 하고, 그 위의 schema에는 USE SCHEMA, catalog에는 USE CATALOG 권한이 필요합니다. 테이블 권한만 있고 부모 USE 권한이 없으면 조회가 거부됩니다.", "governance"),
    ("D03", "최소 권한 원칙", "업무에 필요한 만큼만 권한을 요청합니다. ALL PRIVILEGES 같은 넓은 권한 대신 필요한 SELECT나 MODIFY만 요청하면 사고가 났을 때 영향 범위가 작습니다. Grant least privilege and review it regularly.", "governance"),
    ("D04", "SQL Warehouse 시작과 종료", "SQL Warehouse는 SQL을 실행하는 전용 컴퓨트입니다. 서버리스는 쿼리를 실행하면 자동으로 켜지고 일정 시간 쓰지 않으면 꺼집니다. 꺼져 있는 클래식 웨어하우스는 먼저 시작해야 합니다.", "compute"),
    ("D05", "웨어하우스 사용 권한", "웨어하우스에서 쿼리를 돌리려면 CAN USE 권한이 있어야 합니다. Unity Catalog 권한이 있어도 웨어하우스 권한이 없으면 실행되지 않으며 두 권한은 서로 별개입니다.", "compute"),
    ("D06", "Delta 테이블 버전 이력", "Delta 테이블은 쓰기를 할 때마다 새 버전을 기록합니다. DESCRIBE HISTORY로 이력을 보고 VERSION AS OF로 과거 시점의 내용을 읽을 수 있습니다. 실수로 지운 데이터는 RESTORE로 이전 버전으로 되돌립니다.", "delta"),
    ("D07", "타임 트래블 주의점", "타임 트래블은 보관 기간 안의 버전만 읽을 수 있습니다. VACUUM으로 오래된 파일이 정리되면 그 버전은 더 이상 읽히지 않으므로 중요한 복구는 서둘러야 합니다.", "delta"),
    ("D08", "CTAS로 테이블 만들기", "CREATE TABLE AS SELECT, 줄여서 CTAS는 조회 결과로 새 테이블을 한 번에 만듭니다. 원본은 그대로 두고 가공한 사본이 필요할 때 씁니다. Use CTAS when you want a snapshot of a query result.", "ingestion"),
    ("D09", "COPY INTO 증분 적재", "COPY INTO는 파일의 새 데이터를 테이블에 추가합니다. 이미 읽은 파일은 다시 적재하지 않아서 같은 명령을 여러 번 실행해도 행이 중복되지 않습니다. 이 성질을 멱등성이라고 부릅니다.", "ingestion"),
    ("D10", "파일 업로드로 테이블 만들기", "CSV 같은 작은 파일은 업로드 화면에서 바로 테이블로 만들 수 있습니다. 첫 줄은 머리글이어야 하고 열 이름은 소문자와 밑줄로 정리됩니다. 숫자·날짜 열은 타입이 추론됩니다.", "ingestion"),
    ("D11", "Volume이란", "Volume은 Unity Catalog가 관리하는 파일 저장 공간입니다. 테이블이 아닌 원본 파일(CSV, JSON 등)을 두고 권한으로 접근을 통제합니다. 경로는 /Volumes/catalog/schema/volume 형태입니다.", "ingestion"),
    ("D12", "메달리온 아키텍처", "메달리온은 데이터를 bronze, silver, gold 세 층으로 나눕니다. bronze는 원본 그대로 쌓고, silver는 정제·중복 제거를 하고, gold는 업무 지표용으로 집계합니다. 층이 올라갈수록 품질이 높아집니다.", "pipeline"),
    ("D13", "스트리밍 테이블과 구체화 뷰", "스트리밍 테이블은 원본에 새로 들어온 행만 증분으로 처리해 추가합니다. 구체화 뷰는 쿼리 결과를 저장해 두었다가 갱신 때 다시 계산합니다. Streaming tables are append-oriented while materialized views are recomputed.", "pipeline"),
    ("D14", "데이터 품질 expectations", "expectation은 행이 지켜야 할 조건입니다. 위반 행을 경고만 하고 그대로 두거나, 그 행을 버리거나(DROP ROW), 업데이트 전체를 실패시킬 수(FAIL UPDATE) 있습니다. 잘못된 데이터가 gold로 번지는 것을 막습니다.", "pipeline"),
    ("D15", "변경 데이터 캡처 CDC", "CDC는 원본 시스템의 입력·수정·삭제 이벤트를 목적 테이블에 반영하는 방식입니다. 이벤트가 중복되거나 순서가 뒤바뀌어 도착할 수 있으므로 순서를 정하는 시퀀스 열과 키가 필요합니다.", "pipeline"),
    ("D16", "SCD Type 1과 Type 2", "SCD Type 1은 같은 키의 값을 새 값으로 덮어써서 최신 상태만 남깁니다. Type 2는 변경 이력을 행으로 남깁니다. 이력이 필요 없고 항상 현재 값만 필요하면 Type 1이 단순합니다.", "pipeline"),
    ("D17", "Job으로 파이프라인 자동화", "Job은 노트북이나 파이프라인을 일정에 맞춰 실행합니다. 실행 주체(run-as)의 권한으로 돌아가므로 서비스 주체에 필요한 권한만 줘야 합니다. 실패한 태스크는 repair로 그 부분만 다시 실행할 수 있습니다.", "jobs"),
    ("D18", "Genie와 의미 모델", "Genie는 자연어 질문을 SQL로 바꿔 답을 줍니다. 용어 정의와 예시 질의를 미리 등록해 두면 '가용재고' 같은 업무 용어를 올바른 계산식으로 해석합니다. 사용자의 UC 권한은 그대로 적용됩니다.", "analytics"),
    ("D19", "대시보드 필터와 게시", "대시보드는 SQL 데이터셋 위에 차트와 필터를 올립니다. 게시하면 읽기 전용 화면이 만들어지고 새로 고침 일정으로 데이터를 최신으로 유지합니다. 보는 사람의 권한과 자격 증명 방식을 확인해야 합니다.", "analytics"),
    ("D20", "벡터 검색과 RAG", "RAG는 질문과 관련된 문서를 먼저 검색해서 그 내용을 프롬프트에 넣고 답을 만드는 방식입니다. 모델이 모르는 사내 문서도 근거로 쓸 수 있고 답에 출처를 붙일 수 있습니다. 검색 품질이 답의 품질을 좌우합니다.", "genai"),
    ("D21", "프롬프트 작성 요령", "좋은 프롬프트는 역할, 해야 할 일, 참고할 컨텍스트, 출력 형식을 분명히 적습니다. 모르면 모른다고 답하게 하고 컨텍스트에 없는 내용은 만들지 않게 지시하면 환각이 줄어듭니다. Include one example when the format matters.", "genai"),
    ("D22", "모델 서빙 엔드포인트", "모델 서빙은 등록한 모델을 REST 엔드포인트로 배포해 실시간으로 질의합니다. 무료 환경에서는 동시에 만들 수 있는 엔드포인트 수가 제한되므로 쓰지 않는 것은 삭제합니다.", "genai"),
    ("D23", "에이전트 평가", "에이전트는 배포 전에 평가 세트로 점검합니다. 기대한 문서를 찾았는지(hit@k), 첫 정답의 순위(MRR), 답이 검색된 문서에 근거하는지를 보고 합격선을 넘을 때만 배포합니다.", "genai"),
    ("D24", "시뮬레이터 사용 순서", "이 학습 환경은 먼저 환경 점검에서 세션을 시작하고, 필요한 권한을 요청한 뒤, SQL Editor에서 쿼리를 실행합니다. 오류가 나면 화면 아래의 해결 방법 보기를 눌러 원인과 순서를 확인하세요.", "simulator"),
]


# ------------------------------------------------------------------ 토큰화 · BM25
_WORD = re.compile(r"[A-Za-z0-9]+|[가-힣]+")
_STOP = {"the", "a", "an", "of", "to", "is", "are", "in", "on", "and", "or", "for", "it", "be", "can", "you", "that", "this", "with", "as", "by"}


def tokenize(text: str) -> list[str]:
    """영문·숫자는 소문자 단어, 한글은 문자 bi-gram(한 글자 단어는 그대로)."""
    out: list[str] = []
    for w in _WORD.findall(text or ""):
        if "가" <= w[0] <= "힣":
            out += [w[i:i + 2] for i in range(len(w) - 1)] if len(w) > 1 else [w]
        else:
            w = w.lower()
            if w not in _STOP:
                out.append(w)
    return out


def _bm25(docs_tokens: list[list[str]], qtokens: list[str], k1: float = 1.5, b: float = 0.75) -> list[float]:
    n = len(docs_tokens)
    if not n:
        return []
    avgdl = sum(len(d) for d in docs_tokens) / n or 1.0
    df: dict[str, int] = {}
    for d in docs_tokens:
        for t in set(d):
            df[t] = df.get(t, 0) + 1
    scores = []
    for d in docs_tokens:
        tf: dict[str, int] = {}
        for t in d:
            tf[t] = tf.get(t, 0) + 1
        s = 0.0
        for t in set(qtokens):
            if t not in tf:
                continue
            idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
            s += idf * tf[t] * (k1 + 1) / (tf[t] + k1 * (1 - b + b * len(d) / avgdl))
        scores.append(s)
    return scores


# ------------------------------------------------------------------ 공통 보조
def _principal(a) -> str:
    return core.ADMIN if a["role"] == "admin" else core.TRAINEE


def _G(S) -> dict:
    g = S.setdefault("genai", {})
    for k, v in (("indexes", {}), ("agents", {}), ("traces", []), ("evals", [])):
        g.setdefault(k, v)
    return g


def _err(code, message, hint=None, **kw):
    return ApiError(400, code, message, hint=hint, **kw)


def _q(sql_err):
    """run_sql 실패(error dict)를 ApiError 로."""
    e = sql_err or {}
    return ApiError(400, e.get("code", "EXECUTION_ERROR"), e.get("message", "SQL 실행 실패"), hint=e.get("hint"), missing=e.get("missing"))


def _sqlq(s: str) -> str:
    return core.sql_str(s)


def _current_version(S, fq: str) -> int:
    c = core._conns[S["id"]]
    core._hist_ensure(S, c, fq)
    return core._thist(S)[fq][-1]["version"]


def _read_source(S, principal, fq, cols):
    for c in cols:
        if not _IDENT.match(c):
            raise _err("INVALID_NAME", f"열 이름이 올바르지 않습니다: {c}")
    r = core.run_sql(S, f"SELECT {', '.join(cols)} FROM {fq}", principal, via="rag", need_warehouse=False)
    if r["status"] != "succeeded":
        raise _q(r["error"])
    return r["rows"], r["columns"]


def _check_read(S, principal, fq):
    r = core.run_sql(S, f"SELECT * FROM {fq} LIMIT 0", principal, via="rag", need_warehouse=False)
    if r["status"] != "succeeded":
        raise _q(r["error"])


# ------------------------------------------------------------------ 샘플 문서 테이블
def create_sample_docs(S, principal, actor_id):
    c = core._conns[S["id"]]
    cat, db, name = DOC_TABLE.split(".")
    if core._exists(c, "table", [cat, db, name]):
        return {"table": DOC_TABLE, "created": False, "rows": len(DOCS), "note": "이미 있어 건너뛰었습니다."}
    sel = " UNION ALL ".join(f"SELECT {_sqlq(d[0])} AS doc_id, {_sqlq(d[1])} AS title, {_sqlq(d[2])} AS content, {_sqlq(d[3])} AS category" for d in DOCS)
    r = core.run_sql(S, f"CREATE TABLE {DOC_TABLE} AS {sel}", principal, via="rag", need_warehouse=False, actor_id=actor_id)
    if r["status"] != "succeeded":
        raise _q(r["error"])
    return {"table": DOC_TABLE, "created": True, "rows": len(DOCS), "note": "합성 학습용 문서입니다(공식 문서 복제 아님)."}


# ------------------------------------------------------------------ AI Search 인덱스
def _snapshot(S, principal, spec):
    meta = spec.get("meta_cols") or []
    cols = [spec["pk"], spec["text_col"]] + [m for m in meta if m not in (spec["pk"], spec["text_col"])]
    rows, rc = _read_source(S, principal, spec["source"], cols)
    if len(rows) >= MAX_ROWS:
        raise _err("INDEX_TOO_LARGE", f"시뮬레이터는 인덱스당 {MAX_ROWS}행 미만의 원본만 색인합니다.")
    docs = []
    for r in rows:
        d = dict(zip(rc, r))
        docs.append({"pk": str(d[spec["pk"]]), "text": str(d[spec["text_col"]] or ""), "meta": {m: d.get(m) for m in meta}})
    return docs


def create_index(S, principal, b):
    name, src = str(b.get("name", "")).strip(), str(b.get("source", "")).strip()
    pk, text = str(b.get("pk", "")).strip(), str(b.get("text_col", "")).strip()
    meta = [m.strip() for m in (b.get("meta_cols") or []) if str(m).strip()]
    if not _UC3.match(name):
        raise _err("INVALID_NAME", "인덱스 이름은 catalog.schema.name 세 단계(영문 소문자·숫자·_)여야 합니다.", "예: food_dev.gold.doc_index")
    if not _UC3.match(src):
        raise _err("INVALID_NAME", "원본 테이블은 catalog.schema.table 세 단계로 입력하세요.")
    if not pk or not text:
        raise _err("INVALID_ARGUMENT", "기본키 열과 텍스트 열을 입력하세요.")
    g = _G(S)
    if name in g["indexes"]:
        raise ApiError(409, "INDEX_EXISTS", f"인덱스 `{name}`이(가) 이미 있습니다.")
    spec = {"source": src, "pk": pk, "text_col": text, "meta_cols": meta}
    docs = _snapshot(S, principal, spec)
    ix = {"name": name, **spec, "docs": docs, "synced_version": _current_version(S, src), "synced_at": core.now_utc(), "sync_count": 1, "mode": "triggered"}
    g["indexes"][name] = ix
    return _index_view(S, ix)


def _index_view(S, ix, with_docs=False):
    try:
        cur = _current_version(S, ix["source"])
    except Exception:
        cur = None
    stale = cur is not None and cur != ix["synced_version"]
    v = {k: ix[k] for k in ("name", "source", "pk", "text_col", "meta_cols", "synced_version", "synced_at", "sync_count", "mode")}
    v.update(rows=len(ix["docs"]), source_version=cur, state="STALE" if stale else "ONLINE",
             hint="원본 테이블이 동기화 이후 바뀌었습니다. [동기화]를 눌러 다시 색인하세요." if stale else "원본과 같은 버전입니다.")
    if with_docs:
        v["docs"] = ix["docs"]
    return v


def sync_index(S, principal, name):
    ix = _G(S)["indexes"].get(name)
    if not ix:
        raise ApiError(404, "INDEX_NOT_FOUND", f"인덱스 `{name}`이(가) 없습니다.")
    ix["docs"] = _snapshot(S, principal, ix)
    ix["synced_version"], ix["synced_at"] = _current_version(S, ix["source"]), core.now_utc()
    ix["sync_count"] += 1
    return _index_view(S, ix)


def query_index(S, principal, name, query, k=3, filters=None):
    ix = _G(S)["indexes"].get(name)
    if not ix:
        raise ApiError(404, "INDEX_NOT_FOUND", f"인덱스 `{name}`이(가) 없습니다.")
    _check_read(S, principal, ix["source"])                       # 인덱스 읽기 = 원본 테이블 SELECT 권한
    k = max(1, min(20, int(k or 3)))
    docs = ix["docs"]
    for col, val in (filters or {}).items():
        if col not in ix["meta_cols"]:
            raise _err("INVALID_FILTER", f"필터 열 `{col}`은(는) 인덱스의 메타데이터 열이 아닙니다.", f"사용 가능: {', '.join(ix['meta_cols']) or '(없음)'}")
        docs = [d for d in docs if str(d["meta"].get(col)) == str(val)]
    qt = tokenize(query)
    scores = _bm25([tokenize(d["text"]) for d in docs], qt)
    ranked = sorted(((s, i) for i, s in enumerate(scores) if s > 0), key=lambda x: (-x[0], x[1]))[:k]
    hits = [{"rank": n + 1, "pk": docs[i]["pk"], "score": round(s, 4), "text": docs[i]["text"], "meta": docs[i]["meta"]} for n, (s, i) in enumerate(ranked)]
    return {"index": name, "query": query, "tokens": qt, "k": k, "filters": filters or {}, "hits": hits, "state": _index_view(S, ix)["state"],
            "evidence_level": EVIDENCE, "note": "키워드(BM25) 검색입니다. 임베딩 의미 검색이 아닙니다."}


# ------------------------------------------------------------------ AI Playground
_SENT = re.compile(r"(?<=[.!?。])\s+|\n+")


def sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENT.split(text or "") if s and s.strip()]


def render_template(template: str, variables: dict) -> tuple[str, list[str]]:
    missing = []

    def sub(m):
        k = m.group(1).strip()
        if k in (variables or {}):
            return str(variables[k])
        missing.append(k)
        return m.group(0)
    return re.sub(r"\{\{\s*([A-Za-z0-9_가-힣]+)\s*\}\}", sub, template or ""), missing


def assemble_prompt(system, template, variables, context, user) -> dict:
    body, missing = render_template(template, variables)
    parts = []
    if system.strip():
        parts.append("[SYSTEM]\n" + system.strip())
    if body.strip():
        parts.append("[INSTRUCTION]\n" + body.strip())
    if context.strip():
        parts.append("[CONTEXT]\n" + context.strip())
    parts.append("[USER]\n" + user.strip())
    final = "\n\n".join(parts)
    return {"prompt": final, "tokens_estimate": max(1, math.ceil(len(final) / 4)), "missing_variables": missing}


def detect_style(instruction: str) -> str:
    t = (instruction or "").lower()
    if "json" in t:
        return "json"
    if re.search(r"불릿|bullet|목록|항목별|list", t):
        return "bullets"
    if re.search(r"한 문장|1문장|한문장|one sentence|single sentence", t):
        return "sentence"
    return "paragraph"


def pick_sentences(context: str, question: str, n: int) -> list[str]:
    qt = set(tokenize(question))
    sents = sentences(context)
    scored = [(len(qt & set(tokenize(s))), i, s) for i, s in enumerate(sents)]
    best = sorted([x for x in scored if x[0] > 0], key=lambda x: (-x[0], x[1]))[:n]
    return [s for _, _, s in sorted(best, key=lambda x: x[1])]


def mock_generate(instruction: str, context: str, question: str, style: Optional[str] = None) -> dict:
    style = style or detect_style(instruction)
    n = {"sentence": 1, "bullets": 3, "json": 2, "paragraph": 3}[style]
    if not context.strip():
        return {"style": style, "text": "컨텍스트가 없어 답할 수 없습니다. (모의 모델은 컨텍스트에 없는 내용을 만들어내지 않습니다.)", "used": []}
    used = pick_sentences(context, question, n)
    if not used:
        return {"style": style, "text": "제공된 컨텍스트에서 질문과 관련된 내용을 찾지 못했습니다.", "used": []}
    if style == "bullets":
        text = "\n".join("- " + s for s in used)
    elif style == "json":
        import json as _j
        text = _j.dumps({"answer": used[0], "evidence": used}, ensure_ascii=False)
    elif style == "sentence":
        text = used[0]
    else:
        text = " ".join(used)
    return {"style": style, "text": text, "used": used}


CHECKS = [
    ("role", "역할 지정", r"당신은|you are|역할|act as|담당", "‘당신은 ○○ 도우미입니다’처럼 역할을 정해 주세요."),
    ("task", "명확한 지시", r"요약|설명|답하|답변|알려|정리|summarize|explain|answer|list|extract|추출|하세요|해 주세요|해줘", "무엇을 해야 하는지 동사로 분명히 쓰세요(예: ‘세 줄로 요약하세요’)."),
    ("context", "컨텍스트 제공", None, "참고할 문서·데이터를 컨텍스트에 넣으세요. 없으면 모델이 추측하게 됩니다."),
    ("format", "출력 형식 지정", r"json|불릿|bullet|표|table|문장|sentence|형식|format|목록", "‘한 문장으로’, ‘불릿으로’, ‘JSON으로’처럼 출력 형식을 정하세요."),
    ("grounding", "근거 제한", r"컨텍스트|context|제공된|문서에 없|모르면|모른다|don'?t know|only|근거", "‘컨텍스트에 없으면 모른다고 답하세요’처럼 근거 범위를 제한하세요."),
    ("example", "예시(few-shot)", r"예시|example|예:|e\.g|q:|입력:", "형식이 중요하면 입력·출력 예시를 한두 개 넣으세요."),
]


def checklist(system, template, context) -> dict:
    text = f"{system}\n{template}"
    items = []
    for key, label, pat, hint in CHECKS:
        ok = bool(context.strip()) if key == "context" else bool(re.search(pat, text, re.I))
        items.append({"key": key, "label": label, "ok": ok, "hint": "" if ok else hint})
    return {"items": items, "score": round(sum(i["ok"] for i in items) / len(items), 2), "note": "정규식 휴리스틱입니다. 실제 모델 품질을 보증하지 않습니다."}


def playground(b) -> dict:
    variants = b.get("variants") or [b]
    if len(variants) > 2:
        raise _err("TOO_MANY_VARIANTS", "프롬프트 비교는 최대 2개입니다.")
    out = []
    for i, v in enumerate(variants):
        system, template, context, user = (str(v.get(k, "")) for k in ("system", "template", "context", "user"))
        if not user.strip():
            raise _err("INVALID_ARGUMENT", "사용자 입력(질문)을 입력하세요.")
        asm = assemble_prompt(system, template, v.get("variables") or {}, context, user)
        gen = mock_generate(f"{system}\n{template}", context, user, v.get("style") or None)
        out.append({"label": v.get("label") or "ABCD"[i], **asm, "answer": gen["text"], "style": gen["style"], "used_sentences": gen["used"], "checklist": checklist(system, template, context)})
    return {"variants": out, "evidence_level": EVIDENCE, "note": LIMIT_NOTE}


# ------------------------------------------------------------------ RAG 에이전트
def register_agent(S, actor, b):
    name = str(b.get("name", "")).strip()
    if not _UC3.match(name):
        raise _err("INVALID_NAME", "에이전트 이름은 catalog.schema.name 세 단계(영문 소문자·숫자·_)여야 합니다.", "예: food_dev.gold.doc_assistant")
    idx = str(b.get("index", "")).strip()
    if idx not in _G(S)["indexes"]:
        raise ApiError(404, "INDEX_NOT_FOUND", f"인덱스 `{idx}`이(가) 없습니다. 먼저 AI Search 인덱스를 만드세요.")
    style = b.get("style") or "paragraph"
    if style not in STYLES:
        raise _err("INVALID_ARGUMENT", f"답변 스타일은 {', '.join(STYLES)} 중 하나입니다.")
    k = max(1, min(10, int(b.get("k") or 3)))
    ag = _G(S)["agents"].setdefault(name, {"name": name, "versions": []})
    ver = {"version": len(ag["versions"]) + 1, "index": idx, "k": k, "system": str(b.get("system", "")), "style": style, "note": str(b.get("note", ""))[:200],
           "created_by": actor["user_id"], "created_at": core.now_utc()}
    ag["versions"].append(ver)
    core.audit(S, actor["user_id"], "GENAI_AGENT_REGISTER", name, "succeeded", EVIDENCE, {"version": ver["version"], "index": idx, "k": k})
    return {"name": name, **ver}


def _agent_version(S, name, version=None):
    ag = _G(S)["agents"].get(name)
    if not ag or not ag["versions"]:
        raise ApiError(404, "AGENT_NOT_FOUND", f"에이전트 `{name}`이(가) 없습니다.")
    if version in (None, "", 0):
        return ag["versions"][-1]
    v = next((x for x in ag["versions"] if x["version"] == int(version)), None)
    if not v:
        raise ApiError(404, "AGENT_VERSION_NOT_FOUND", f"에이전트 `{name}`에 버전 {version}이(가) 없습니다.")
    return v


def run_agent(S, principal, actor_id, name, version, question, tag="chat") -> dict:
    ver = _agent_version(S, name, version)
    t0 = time.time()
    spans = []
    t = time.time()
    res = query_index(S, principal, ver["index"], question, ver["k"])
    spans.append({"name": "retrieve", "ms": int((time.time() - t) * 1000), "inputs": {"query": question, "k": ver["k"], "index": ver["index"]},
                  "outputs": {"hits": [{"pk": h["pk"], "score": h["score"]} for h in res["hits"]]}})
    context = "\n".join(f"[{h['pk']}] {h['text']}" for h in res["hits"])
    t = time.time()
    asm = assemble_prompt(ver["system"], "", {}, context, question)
    spans.append({"name": "build_prompt", "ms": int((time.time() - t) * 1000), "inputs": {"system": ver["system"][:120], "chunks": len(res["hits"])}, "outputs": {"tokens_estimate": asm["tokens_estimate"]}})
    t = time.time()
    # 문장 선택은 [doc_id] 표기를 뺀 본문으로 하고, 사용한 문장이 어느 문서에서 왔는지로 인용을 만든다
    pieces = []
    for h in res["hits"]:
        for s in sentences(h["text"]):
            pieces.append((h["pk"], s))
    ctx_text = "\n".join(s for _, s in pieces)
    gen = mock_generate(ver["system"], ctx_text, question, ver["style"])
    if not res["hits"]:
        gen = {"style": ver["style"], "text": "인덱스에서 관련 문서를 찾지 못했습니다. (키워드 검색이라 표현이 다르면 찾지 못할 수 있습니다.)", "used": []}
    cites = []
    for u in gen["used"]:
        for pk, s in pieces:
            if s == u and pk not in cites:
                cites.append(pk)
    spans.append({"name": "generate", "ms": int((time.time() - t) * 1000), "inputs": {"style": gen["style"], "model": "mock-extractive (실제 LLM 아님)"}, "outputs": {"sentences_used": len(gen["used"])}})
    trace = {"id": "tr_" + uuid.uuid4().hex[:10], "at": core.now_utc(), "agent": name, "version": ver["version"], "tag": tag, "question": question, "answer": gen["text"],
             "citations": cites, "retrieved": [h["pk"] for h in res["hits"]], "spans": spans, "total_ms": int((time.time() - t0) * 1000), "prompt": asm["prompt"], "state": res["state"]}
    tr = _G(S)["traces"]
    tr.append({k: v for k, v in trace.items()})
    del tr[:-100]
    core.audit(S, actor_id, "GENAI_AGENT_RUN", name, "succeeded", EVIDENCE, {"version": ver["version"], "tag": tag, "cites": cites})
    return trace


# ------------------------------------------------------------------ 평가
SAMPLE_EVAL = [
    {"question": "테이블을 조회하려면 어떤 권한이 필요한가요?", "expected_docs": ["D02"], "keywords": ["SELECT", "USE SCHEMA"]},
    {"question": "COPY INTO를 반복 실행하면 행이 중복되나요?", "expected_docs": ["D09"], "keywords": ["중복되지"]},
    {"question": "실수로 지운 데이터를 되돌리려면?", "expected_docs": ["D06"], "keywords": ["RESTORE"]},
    {"question": "expectation 위반 행을 버리는 방법은?", "expected_docs": ["D14"], "keywords": ["DROP ROW"]},
    {"question": "서버리스 웨어하우스는 언제 켜지나요?", "expected_docs": ["D04"], "keywords": ["자동"]},
    {"question": "에이전트를 배포하기 전에 무엇을 확인하나요?", "expected_docs": ["D23"], "keywords": ["hit@k"]},
]


def _grounded(answer: str, retrieved_text: str) -> float:
    sents = [s.lstrip("- ").strip() for s in sentences(answer)]
    sents = [s for s in sents if tokenize(s)]
    if not sents:
        return 0.0
    ref = set(tokenize(retrieved_text))
    ok = 0
    for s in sents:
        st = tokenize(s)
        if st and sum(1 for t in st if t in ref) / len(st) >= 0.5:
            ok += 1
    return ok / len(sents)


def metrics_for(rows: list[dict]) -> dict:
    n = len(rows) or 1
    kw_rows = [r for r in rows if r["keywords_total"]]
    return {"hit_at_k": round(sum(r["hit"] for r in rows) / n, 4), "mrr": round(sum(r["rr"] for r in rows) / n, 4), "groundedness": round(sum(r["grounded"] for r in rows) / n, 4),
            "keyword_rate": round(sum(r["keywords_hit"] / r["keywords_total"] for r in kw_rows) / (len(kw_rows) or 1), 4) if kw_rows else None}


def evaluate(S, principal, actor_id, name, versions, eval_set=None, threshold=0.8):
    evs = eval_set or SAMPLE_EVAL
    if not evs or len(evs) > 50:
        raise _err("INVALID_ARGUMENT", "평가 세트는 1~50문항이어야 합니다.")
    versions = versions or [None]
    if len(versions) > 2:
        raise _err("TOO_MANY_VERSIONS", "A/B 비교는 버전 2개까지입니다.")
    out = []
    for v in versions:
        ver = _agent_version(S, name, v)
        per = []
        for q in evs:
            tr = run_agent(S, principal, actor_id, name, ver["version"], q["question"], tag="eval")
            exp = [str(x) for x in q.get("expected_docs") or []]
            rank = next((i + 1 for i, pk in enumerate(tr["retrieved"]) if pk in exp), None)
            ref_text = " ".join(h["text"] for h in query_index(S, principal, ver["index"], q["question"], ver["k"])["hits"])
            kws = [str(x) for x in q.get("keywords") or []]
            per.append({"question": q["question"], "expected_docs": exp, "retrieved": tr["retrieved"], "rank": rank, "hit": 1 if rank else 0, "rr": round(1 / rank, 4) if rank else 0.0,
                        "grounded": round(_grounded(tr["answer"], ref_text), 4), "keywords_total": len(kws), "keywords_hit": sum(1 for x in kws if x.lower() in tr["answer"].lower()),
                        "answer": tr["answer"], "citations": tr["citations"], "trace_id": tr["id"]})
        m = metrics_for(per)
        rec = {"id": "ev_" + uuid.uuid4().hex[:8], "at": core.now_utc(), "agent": name, "version": ver["version"], "k": ver["k"], "threshold": threshold, "metric": "hit_at_k",
               "metrics": m, "passed": m["hit_at_k"] >= threshold, "per_question": per, "questions": len(per)}
        _G(S)["evals"].append(rec)
        out.append(rec)
    del _G(S)["evals"][:-30]
    return {"results": out, "evidence_level": EVIDENCE, "note": "모의 모델·키워드 검색 기준의 구조 연습용 지표입니다. 실제 LLM 평가(MLflow 평가)와 값이 다릅니다.",
            "gate": "합격선(hit@k ≥ %s) 통과한 버전만 배포하는 흐름을 연습합니다." % threshold}


# ------------------------------------------------------------------ 서빙 처리기
def _serve_handler(S, ep, payload):
    cfg = ep["config"]
    msgs = payload.get("messages") or []
    q = next((m.get("content", "") for m in reversed(msgs) if m.get("role") == "user"), "")
    if not str(q).strip():
        raise _err("INVALID_ARGUMENT", "messages 에 role=user 메시지가 필요합니다.")
    tr = run_agent(S, payload.get("__principal", core.TRAINEE), ep["created_by"], cfg["agent"], cfg.get("version"), str(q), tag="serving")
    return {"choices": [{"message": {"role": "assistant", "content": tr["answer"]}}], "citations": tr["citations"], "trace_id": tr["id"], "notice": "모의 모델 응답(실제 LLM 아님)"}


serving.register_handler("agent", _serve_handler)


# ------------------------------------------------------------------ 라우트
def _overview(S):
    g = _G(S)
    c = core._conns[S["id"]]
    cat, db, name = DOC_TABLE.split(".")
    return {"evidence_level": EVIDENCE, "note": LIMIT_NOTE, "doc_table": DOC_TABLE, "doc_table_exists": core._exists(c, "table", [cat, db, name]), "doc_count": len(DOCS),
            "indexes": [_index_view(S, ix) for ix in g["indexes"].values()],
            "agents": [{"name": a["name"], "versions": a["versions"]} for a in g["agents"].values()],
            "traces": [{k: v for k, v in t.items() if k != "prompt"} for t in g["traces"][-20:][::-1]], "evals": g["evals"][-10:][::-1],
            "sample_eval": SAMPLE_EVAL, "styles": STYLES, "max_slots": serving.MAX_SLOTS,
            "agent_bricks": {"known": "Databricks에 'Agent Bricks'라는 에이전트 구성 기능이 있다는 것만 코스 개요에서 확인했습니다.", "unknown": "에이전트 유형과 선택 기준은 조회하지 못했습니다. 이 시뮬레이터는 제공하지 않으며, 실제 사용은 워크스페이스에서 확인하세요."}}


def register(app, actor_of, sess):
    def ctx(sid, authorization):
        a = actor_of(authorization)
        return a, sess(sid, a)

    @app.get("/api/sessions/{sid}/genai")
    def genai_overview(sid: str, authorization: Optional[str] = Header(None)):
        a, S = ctx(sid, authorization)
        with core.lock_for(sid):
            return _overview(S)

    @app.post("/api/sessions/{sid}/genai/docs/sample")
    def genai_docs(sid: str, authorization: Optional[str] = Header(None)):
        a, S = ctx(sid, authorization)
        with core.lock_for(sid):
            r = create_sample_docs(S, _principal(a), a["user_id"])
            core.save(S)
            return r

    @app.post("/api/sessions/{sid}/genai/index")
    def genai_index_create(sid: str, b: dict, authorization: Optional[str] = Header(None)):
        a, S = ctx(sid, authorization)
        with core.lock_for(sid):
            r = create_index(S, _principal(a), b)
            core.save(S)
            return r

    @app.post("/api/sessions/{sid}/genai/index/sync")
    def genai_index_sync(sid: str, b: dict, authorization: Optional[str] = Header(None)):
        a, S = ctx(sid, authorization)
        with core.lock_for(sid):
            r = sync_index(S, _principal(a), str(b.get("name", "")))
            core.save(S)
            return r

    @app.post("/api/sessions/{sid}/genai/index/delete")
    def genai_index_delete(sid: str, b: dict, authorization: Optional[str] = Header(None)):
        a, S = ctx(sid, authorization)
        with core.lock_for(sid):
            name = str(b.get("name", ""))
            if name not in _G(S)["indexes"]:
                raise ApiError(404, "INDEX_NOT_FOUND", f"인덱스 `{name}`이(가) 없습니다.")
            users = [n for n, ag in _G(S)["agents"].items() if any(v["index"] == name for v in ag["versions"])]
            if users:
                raise ApiError(409, "INDEX_IN_USE", f"에이전트 {', '.join(users)} 이(가) 이 인덱스를 사용 중입니다.")
            del _G(S)["indexes"][name]
            core.save(S)
            return {"deleted": name}

    @app.post("/api/sessions/{sid}/genai/index/query")
    def genai_index_query(sid: str, b: dict, authorization: Optional[str] = Header(None)):
        a, S = ctx(sid, authorization)
        with core.lock_for(sid):
            r = query_index(S, _principal(a), str(b.get("name", "")), str(b.get("query", "")), b.get("k", 3), b.get("filters") or {})
            core.save(S)
            return r

    @app.post("/api/sessions/{sid}/genai/playground")
    def genai_playground(sid: str, b: dict, authorization: Optional[str] = Header(None)):
        ctx(sid, authorization)
        return playground(b)

    @app.post("/api/sessions/{sid}/genai/agent/register")
    def genai_agent_register(sid: str, b: dict, authorization: Optional[str] = Header(None)):
        a, S = ctx(sid, authorization)
        with core.lock_for(sid):
            r = register_agent(S, a, b)
            core.save(S)
            return r

    @app.post("/api/sessions/{sid}/genai/agent/run")
    def genai_agent_run(sid: str, b: dict, authorization: Optional[str] = Header(None)):
        a, S = ctx(sid, authorization)
        with core.lock_for(sid):
            q = str(b.get("question", "")).strip()
            if not q:
                raise _err("INVALID_ARGUMENT", "질문을 입력하세요.")
            r = run_agent(S, _principal(a), a["user_id"], str(b.get("name", "")), b.get("version"), q)
            core.save(S)
            return r

    @app.post("/api/sessions/{sid}/genai/eval")
    def genai_eval(sid: str, b: dict, authorization: Optional[str] = Header(None)):
        a, S = ctx(sid, authorization)
        with core.lock_for(sid):
            r = evaluate(S, _principal(a), a["user_id"], str(b.get("agent", "")), b.get("versions") or [None], b.get("eval_set"), float(b.get("threshold") or 0.8))
            core.save(S)
            return r
