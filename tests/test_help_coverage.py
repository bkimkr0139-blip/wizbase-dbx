"""HELP(우측 탭)·AI 지원·시스템 문서가 v0.5.0 신규 기능을 빠짐없이 다루는지 확인한다."""
import re
import pytest
from test_at import client, env, login  # noqa: F401  (앱 데이터 적재)
from backend import assistant as A, sysinfo, guide as G

HELP_JS = open("static/help.js", encoding="utf-8").read()
MENU_VIEWS = [v for _, _, its in sysinfo.MENU for v, _, _ in its]
NEW_VIEWS = ["qh", "lib", "adddata", "vol", "dpipe", "designer", "dash", "acad", "ml", "genai", "serve"]

# (질문, 답변에 반드시 들어갈 단어)
QA = [
    ("CREATE CATALOG 어떻게 해?", "CREATE CATALOG"), ("카탈로그 만들기", "CREATE CATALOG"), ("볼륨이 뭐야?", "Volume"),
    ("Volume에 파일 올리고 COPY INTO 하는 법", "COPY INTO"), ("선언형 파이프라인이 뭐야?", "파이프라인"), ("스트리밍 테이블이 뭐야?", "스트리밍"),
    ("expectations가 뭐야?", "Expectations"), ("AUTO CDC 가 뭐야?", "SCD"), ("SCD2 지원해?", "지원하지 않"), ("이벤트 로그", "이벤트 로그"),
    ("대시보드 만드는 법", "Dashboards"), ("Genie Code 가 뭐야?", "규칙 기반"), ("Lakeflow Designer 가 뭐야?", "연산자"),
    ("쿼리 히스토리 보는 법", "Query History"), ("타임 트래블 VERSION AS OF", "VERSION AS OF"), ("RESTORE TABLE", "RESTORE"),
    ("무료 에디션과 차이", "Free Edition"), ("CSV 올려서 테이블 만들기", "CSV"), ("MLflow 가 뭐야?", "시뮬레이션"), ("실험 추적", "run"),
    ("모델 등록 UC 모델 별칭", "별칭"), ("feature table 특성 테이블", "특성"), ("Model Serving 이 뭐야?", "엔드포인트"),
    ("서빙 엔드포인트 만들기", "서빙"), ("RAG 가 뭐야?", "BM25"), ("AI Search 벡터 검색", "BM25"), ("Playground 사용법", "Playground"),
    ("에이전트 평가", "평가"), ("Academy 코스 대응", "Academy"), ("Data analysts 경로", "Academy"), ("ML practitioners 경로", "Academy"),
    ("Generative AI engineers", "Academy"), ("Ctrl+P 빠른 검색", "Ctrl+P"), ("데이터 품질 탭", "탭"), ("계보 lineage", "탭"),
    ("시뮬레이션이 실제와 뭐가 달라?", "시뮬레이션"), ("AI 함수 ai_query", "지원하지 않"), ("read_files 지원해?", "지원하지 않"),
    ("SQL_TOO_LONG", "20,000"), ("SQL이 너무 길어요", "20,000"),
    ("시도 ID 가 뭐야?", "wzA"), ("adapter doctor 어떻게 써?", "warehouse"), ("adapter 다운로드 어디서 해?", "adapter"),
    ("statement_id 로 증거 승인하는 법", "Query History"), ("사전훈련 후 실제 DBX 수행 흐름", "승인된 증거만"), ("증거 승인은 어떻게 해?", "statement_id"),
]


@pytest.mark.parametrize("q,word", QA)
def test_ai_answers_new_feature_questions(q, word):
    r = A.answer(None, {"role": "learner"}, q)
    assert r["intent"] != "fallback", q
    assert word.lower() in r["answer"].lower(), (q, r["answer"][:200])


def test_every_menu_view_has_help_scr_alias():
    hk = set(re.findall(r"^  (\w+): \{", HELP_JS, re.M))
    for v in MENU_VIEWS:
        assert v in hk and v in A.SCR and v in A.ALIAS, v
    for v in NEW_VIEWS:
        assert v in MENU_VIEWS


def test_no_stale_statements_about_new_features():
    txt = " ".join(x[2] for x in A.GLOSS if "genie code" in x[0] or "ai search" in x[0] or "lakeflow designer" in x[0])
    assert "제공하지 않으며" not in txt and "다루지 않습니다" not in txt
    assert "INSERT, GRANT/REVOKE(관리자)\"" not in HELP_JS          # SQL Editor 지원 목록 갱신 여부
    for w in ("UPDATE/DELETE/MERGE", "DESCRIBE HISTORY", "Genie Code", "CREATE CATALOG", "Free Edition"):
        assert w in HELP_JS, w


def test_new_error_codes_have_help():
    for c in ("SQL_TOO_LONG", "VOLUME_NOT_FOUND", "SCHEMA_NOT_FOUND", "PIPELINE_PARSE_ERROR", "DATASET_NOT_QUERY", "INDEX_TOO_LARGE", "TABLE_ALREADY_EXISTS"):
        assert c in G.ERR_HELP, c


def test_system_document_covers_v050(env):
    d = sysinfo.system_document()
    for w in ("Volumes", "선언형 파이프라인", "Lakeflow Designer", "Dashboards", "Model Serving", "Academy", "AUTO CDC", "Genie Code", "Free Edition", "28/29/30", "미지원"):
        assert w in d, w
    assert f"{sysinfo.VERSION}" in d


def test_start_keyword_still_opens_first_steps():
    r = A.answer(None, {"role": "learner"}, "시작")
    assert "환경 점검" in r["answer"]


def test_help_lab_and_review_describe_real_dbx_flow():
    h = open("static/help.js", encoding="utf-8").read()
    for w in ("시도 ID", "doctor", "statement_id", "사전훈련", "팩 변경", "보류"):
        assert w in h, w
    s = A.SCR["lab"][2] if A.SCR.get("lab") else []
    assert any("시도 ID" in x for x in s)
