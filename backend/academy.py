"""Databricks Academy 역할별 학습 경로 ↔ 이 시뮬레이터 대응표.

근거: 2026-11-12, 사용자의 Databricks Free Edition 워크스페이스 Learn 화면을 읽기 전용으로 조회(WORKSPACE_OBSERVED).
- 역할 경로 4개의 구성(온보딩/Associate/Professional 단계, 코스 이름·시간·수준·공개 예정 여부)과
  코스 개요 5개의 레슨 제목·소요 시간·선수 조건을 기록했다.
- 레슨 본문(노트북·실습 내용)은 수강을 시작해야 열려 조회하지 않았다. 따라서 대응은 '제목 단위'이며 실습 내용의 일치를 보증하지 않는다.
- Free Edition 화면이라 유료 워크스페이스와 다를 수 있다. 공식 콘텐츠를 복제하지 않고 제목·구성만 대응시킨다.

대응 상태(cov): full=이 시뮬레이터에서 같은 주제를 직접 연습, partial=일부만(근사), none=미지원, lecture=강의(연습 없음).
check: 세션 기록으로 자동 확인하는 연습 항목(없으면 None).
"""
from __future__ import annotations

OBSERVED = "2026-11-12"

# (종류, 제목, 화면, 대응, 확인키, 메모)
_DE1 = [
    ("Demo", "Databricks workspace walkthrough", "ws", "full", None, ""),
    ("Demo", "Find your data and create a table", "cat", "full", "select", ""),
    ("Lab", "Find and create tables", "sql", "full", "ctas", "CREATE TABLE AS SELECT"),
    ("Demo", "Modify data with INSERT, UPDATE, and DELETE", "sql", "full", None, ""),
    ("Lab", "Modify data in a UC table", "sql", "full", "dml", ""),
    ("Demo", "Explore version history and time travel", "cat", "partial", "history", "Catalog History 탭·DESCRIBE HISTORY(시뮬레이션, TIMESTAMP AS OF·VACUUM·CLONE 미지원)"),
    ("Lab", "Use version history and time travel", "sql", "partial", "timetravel", "VERSION AS OF·RESTORE(시뮬레이션, 같은 테이블의 현재·과거 동시 조인 불가)"),
    ("Demo", "Ingest data with CTAS and the upload UI", "adddata", "full", None, ""),
    ("Lab", "Ingest data with CTAS", "adddata", "full", "upload", ""),
    ("Demo", "Load data incrementally with COPY INTO", "adddata", "full", None, ""),
    ("Lab", "Load data incrementally", "adddata", "full", "copy_into", "같은 파일 재적재 시 건너뜀"),
    ("Demo", "Build a medallion architecture pipeline", "pipe", "partial", None, "silver→gold 시나리오 파이프라인으로 근사(bronze 적재부터 만드는 연습은 아님)"),
    ("Lab", "Build a complete medallion pipeline", "pipe", "partial", "pipeline_run", ""),
    ("Demo", "Automate your pipeline with a Lakeflow Job", "jobs", "full", None, ""),
    ("Lab", "Automate a pipeline job", "jobs", "full", "job_run", ""),
    ("Demo", "(bonus) Build a declarative pipeline with Spark Declarative Pipelines", "dpipe", "full", None, "선언형 파이프라인 화면(문법 일부 지원)"),
    ("Lab", "(bonus) Explore your declarative pipeline results", "dpipe", "full", "dlt_run", "이벤트 로그·데이터셋 지표"),
    ("Lecture", "Summary and next steps", None, "lecture", None, ""),
]
_DE2 = [
    ("Lecture", "Introduction to data engineering in Databricks", None, "lecture", None, ""),
    ("Demo", "Course setup and creating a pipeline", "dpipe", "partial", "catalog", "CREATE CATALOG 로 코스 전용 catalog 생성(시뮬레이션)"),
    ("Lecture", "Course project and dataset types overview", None, "lecture", None, ""),
    ("Lecture", "Simplified pipeline development and common pipeline settings", None, "lecture", None, ""),
    ("Demo", "Developing a simple pipeline", "dpipe", "partial", None, "스트리밍 테이블·구체화 뷰(파이프라인 설정·Python·에디터 미지원)"),
    ("Lecture", "Ensure data quality with expectations", None, "lecture", None, ""),
    ("Demo", "Adding data quality expectations", "dpipe", "full", "dlt_expect", "EXPECT … ON VIOLATION DROP ROW / FAIL UPDATE"),
    ("Lab", "Create a pipeline", "dpipe", "partial", "dlt_run", ""),
    ("Lecture", "Streaming joins and deploying pipelines to production", None, "lecture", None, ""),
    ("Demo", "Deploying a pipeline to production", "bundle", "partial", None, "Git/Bundle 배포 화면으로 근사"),
    ("Lecture", "Change data capture (CDC) overview", None, "lecture", None, ""),
    ("Demo", "Change data capture with AUTO CDC with SCD TYPE 1", "dpipe", "full", "dlt_cdc", "AUTO CDC INTO … SCD TYPE 1 (SCD2 미지원)"),
    ("Lecture", "Summary and next steps", None, "lecture", None, ""),
    ("Lab", "(bonus) AUTO CDC INTO with SCD type 1", "dpipe", "full", None, ""),
]
_DA1 = [
    ("Demo", "Databricks workspace walkthrough", "ws", "full", None, ""),
    ("Demo", "Writing queries in Databricks", "sql", "full", None, ""),
    ("Lab", "Query the sales table", "sql", "full", "select", ""),
    ("Demo", "Using Databricks Genie Code with lakehouse", "sql", "partial", None, "SQL Editor의 Genie Code 패널(규칙 기반, 실제 LLM 아님)"),
    ("Lab", "Generate and debug queries with Genie Code", "sql", "partial", None, "규칙 기반 SQL 초안·오류 수정 제안(실제 Genie Code 아님)"),
    ("Demo", "Working with Delta Lake", "cat", "full", "history", ""),
    ("Lab", "Manage a book inventory with Delta Lake", "sql", "full", "restore", "UPDATE/DELETE 후 RESTORE"),
    ("Demo", "Creating dashboards in Databricks", "dash", "partial", None, "데이터셋·위젯·필터·게시(위젯 4종, 실제 AI/BI Dashboards보다 단순)"),
    ("Lab", "Build a customer growth dashboard", "dash", "partial", "dashboard", ""),
    ("Demo", "Creating Genie agents", "genie", "partial", None, "질문 템플릿 기반 의미모델(실제 Genie는 LLM 기반)"),
    ("Lab", "Build your own Genie agent", "genie", "partial", "genie", "지표 정의·예시 질의 설정(템플릿 기반)"),
    ("Lab", "(bonus) Refining retail analytics", "genie", "partial", None, ""),
    ("Lecture", "Summary and next steps", None, "lecture", None, ""),
]
_DA2 = [
    ("Demo", "Data setup and exploration", "cat", "full", None, ""),
    ("Demo", "Lakeflow Designer overview and source layer", "designer", "partial", "designer", "연산자 카드 방식(드래그 캔버스·Genie Code 생성은 미지원)"),
    ("Demo", "Build the silver layer", "designer", "partial", None, ""),
    ("Demo", "Build the gold layer", "designer", "partial", None, ""),
    ("Demo", "Deliver insights with AI/BI and Genie", "dash", "partial", None, "대시보드·Genie 화면으로 근사(Genie One 미지원)"),
    ("Lecture", "Summary and next steps", None, "lecture", None, ""),
    ("Lab", "(bonus) Using AI functions", None, "none", None, "AI 함수 미지원"),
]
_ML1 = [
    ("Demo", "Databricks workspace walkthrough", "ws", "full", None, ""),
    ("Lecture", "Introduction to machine learning on Databricks", None, "lecture", None, ""),
    ("Demo", "Exploratory data analysis (EDA) and feature engineering", "ml", "partial", "feature", "SQL 탐색 + UC 특성 테이블 등록(Python 노트북 미지원)"),
    ("Demo", "MLflow for lifecycle management", "ml", "partial", "ml_register", "실험 추적·UC 모델 등록·별칭(순수 파이썬 모델 3종, 실제 MLflow 아님)"),
    ("Demo", "Genie Code for ML", None, "none", None, "Genie Code Agent Mode 미지원"),
    ("Demo", "Databricks Model Serving", "serve", "partial", "serve_model", "엔드포인트 슬롯 2개·별칭 이동 시 버전 교체(시뮬레이션)"),
    ("Lab", "Getting started with Databricks for machine learning", "ml", "partial", "ml_run", ""),
]
_GA1 = [
    ("Lecture", "The generative AI opportunity", None, "lecture", None, ""),
    ("Lecture", "Databricks AI platform", None, "lecture", None, ""),
    ("Demo", "Prompt engineering in AI Playground", "genai", "partial", None, "프롬프트 조립·점검표(모의 모델, 실제 LLM 아님)"),
    ("Lecture", "MLflow for GenAI", None, "lecture", None, ""),
    ("Demo", "Build and register a retrieval pipeline", "genai", "partial", "ai_search", "BM25 키워드 인덱스(임베딩 아님)·에이전트 버전 등록"),
    ("Demo", "End-to-end evaluation with MLflow", "genai", "partial", "genai_eval", "hit@k·MRR·근거성 평가(소형 세트)"),
    ("Demo", "Real-time deployment with Model Serving", "serve", "partial", "serve_agent", "에이전트 엔드포인트(시뮬레이션)"),
    ("Lecture", "Introduction to Agent Bricks", None, "lecture", None, ""),
    ("Lab", "End-to-end RAG pipeline", "genai", "partial", "rag_agent", "인덱스→에이전트→평가→배포 흐름(실제 LLM 아님)"),
]


def _c(cid, title, tier, minutes, level, lessons, desc="", lesson_count=None, lab_count=None, prereq=None, observed="overview"):
    return {"id": cid, "title": title, "tier": tier, "minutes": minutes, "level": level, "status": "available", "desc": desc, "lessons": lessons,
            "lesson_count": lesson_count, "lab_count": lab_count, "prereq": prereq or [], "observed": observed}


def _soon(cid, title, tier):
    return {"id": cid, "title": title, "tier": tier, "minutes": None, "level": None, "status": "coming_soon", "desc": "", "lessons": [], "lesson_count": None, "lab_count": None, "prereq": [], "observed": "list"}


FREE_PRE = "Free Edition 워크스페이스·서버리스 컴퓨트·코스 전용 catalog 생성 권한"
PATHS = [
    {"id": "data-engineers", "title": "Data engineers", "topics": ["Workspace", "Databricks Apps", "Jobs and pipelines"], "courses": [
        _c("de-1", "Get started with data engineering on Databricks", "onboarding", 235, "Beginner", _DE1, "Build your first data pipeline with Databricks.", 11, 8, [FREE_PRE, "기본 SQL(SELECT·GROUP BY·INSERT/UPDATE/DELETE)"]),
        _c("de-2", "Build data pipelines with Apache Spark Declarative Pipelines", "associate", 240, "Beginner", _DE2, "스트리밍 테이블·구체화 뷰, 품질 expectations, 운영, AUTO CDC(SCD Type 1).", 13, 2, ["Free Edition·Serverless V5·코스 전용 catalog 생성 권한", "중급 SQL"]),
        _soon("de-3", "Data ingestion with Lakeflow Connect", "associate"), _soon("de-4", "Deploy workloads with Lakeflow Jobs", "associate"), _soon("de-5", "DevOps essentials for data engineering", "associate"),
        _soon("de-6", "Automated deployment with Declarative Automation Bundles", "professional")]},
    {"id": "data-analysts", "title": "Data analysts", "topics": ["AI/BI Dashboards", "Visualizations", "Genie"], "courses": [
        _c("da-1", "Get started with SQL analytics and BI on Databricks", "onboarding", 230, "Beginner", _DA1, "워크스페이스 탐색, UC 테이블 쿼리, Delta Lake로 안전하게 변경, AI/BI Dashboards, Genie Agent.", 8, 6, [FREE_PRE + "·SQL 웨어하우스"]),
        _c("da-2", "No code ETL with Lakeflow Designer", "associate", 245, "Beginner", _DA2, "Lakeflow Designer로 메달리온 ETL을 시각적으로 구성.", 7, 1, ["Free Edition의 Lakeflow Designer·Genie Code 사용 가능"]),
        _c("da-3", "AI/BI for data analysts", "associate", 310, "Beginner", [], "다중 페이지 대시보드(SQL 데이터셋·KPI·차트·필터·게시·새로고침 전략). 개요 링크가 목록에 없어 레슨 목록은 조회하지 못함.", None, None, None, "list"),
        _soon("da-4", "SQL analytics on Databricks", "associate")]},
    {"id": "ml-practitioners", "title": "ML practitioners", "topics": ["Workspace", "Notebooks", "Unity Catalog"], "courses": [
        _c("ml-1", "Get started with Databricks for machine learning", "onboarding", 145, "Beginner", _ML1, "EDA·특성 엔지니어링, MLflow, Genie Code, Model Serving.", 7, 1, ["Python 초급", "Free Edition·서버리스·ML v5 환경·모델 서빙 엔드포인트 2개"])]},
    {"id": "generative-ai-engineers", "title": "Generative AI engineers", "topics": ["Generative AI", "RAG", "Model Serving"], "courses": [
        _c("ga-1", "Get started with Databricks for generative AI", "onboarding", 315, "Beginner", _GA1, "AI 플랫폼, 프롬프트 엔지니어링, RAG, MLflow 평가, Model Serving, Agent Bricks.", 9, 1, ["코스 catalog 생성 권한·서버리스(ML 환경 5)", "AI Search 엔드포인트·Model Serving 용량"]),
        _soon("ga-2", "Get started with AI agents on Databricks", "onboarding"), _soon("ga-3", "Agent evaluation on Databricks", "associate")]},
]

GAPS = [
    {"p": "구현됨", "title": "코스 전용 catalog(CREATE CATALOG)·Volumes·COPY INTO(볼륨)", "why": "관찰한 코스 5개 중 4개의 선수 조건이었던 항목을 시뮬레이션했습니다(food_dev 안에 가상 catalog로 저장).", "scope": "CSV만, 정규식 구문, 파일 200KB·볼륨당 30개"},
    {"p": "구현됨", "title": "선언형 파이프라인(스트리밍 테이블·구체화 뷰·expectations·AUTO CDC SCD1)", "why": "화면 UI-09c. 증분·원본 변경 실패·full refresh·이벤트 로그까지 연습합니다.", "scope": "SCD Type 2·IGNORE NULL UPDATES·read_files·PARTITIONED BY 미지원, 레슨 본문 미조회로 문법은 일반 지식 기준"},
    {"p": "구현됨(근사)", "title": "Dashboards·Genie Code·Lakeflow Designer", "why": "위젯 4종·필터·게시, 규칙 기반 SQL 초안, 연산자 카드 ETL.", "scope": "Genie Code는 LLM이 아님, Designer는 드래그 캔버스·AI 함수 없음, 공유·예약 새로 고침은 표시만"},
    {"p": "구현됨(근사)", "title": "ML·MLflow·모델 레지스트리·특성 테이블·Model Serving", "why": "순수 파이썬 모델 3종, 실험·런 비교, UC 모델 버전·별칭, 서빙 슬롯 2개.", "scope": "실제 MLflow·서빙 아님, Genie Code Agent Mode·Lakeflow Jobs 노트북 자동화 미구현"},
    {"p": "구현됨(근사)", "title": "생성형 AI(Playground·AI Search·RAG 에이전트·평가·배포)", "why": "BM25 키워드 검색, 추출형 모의 모델, trace·평가 지표·A/B.", "scope": "실제 LLM·임베딩·벡터 의미 검색 없음(바꿔 말하기 검색 불가), Agent Bricks 유형 상세 미조회"},
    {"p": "남은 격차", "title": "실제 LLM·모델 서빙 품질, Genie One, AI 함수, SCD2, 드래그 캔버스", "why": "외부 서비스나 대형 모델이 필요해 시뮬레이터 범위 밖입니다. 실제 워크스페이스에서 연습하세요.", "scope": "범위 밖(또는 별도 결정 필요)"},
    {"p": "참고", "title": "공개 예정 코스 7개·AI/BI for data analysts 레슨 목록", "why": "목록에 'Coming soon'으로만 보이거나 개요 링크가 없습니다. 공개·확인되면 다시 조회해 반영합니다.", "scope": "-"},
]


def practice(S) -> set[str]:
    """세션 기록으로 연습 항목 달성 여부를 자동 확인한다."""
    q = [x for x in S.get("qh", []) if x.get("status") == "FINISHED"]
    got = set()
    has = lambda f: any(f(x) for x in q)
    import re as _re
    if has(lambda x: x["statement"] == "SELECT" and x["via"] == "sql_editor" and " FROM " in (" " + _re.sub(r"\s+", " ", x["sql"].upper()) + " ")):
        got.add("select")                                    # SELECT 1 같은 테이블 없는 쿼리는 제외
    if has(lambda x: x["statement"] == "CREATE" and x["via"] == "sql_editor" and _re.search(r"CREATE\s+(OR\s+REPLACE\s+)?TABLE[\s\S]*\bAS\b[\s\S]*\bSELECT\b", x["sql"], _re.I)):
        got.add("ctas")                                      # 열 정의만 하는 CREATE TABLE 은 제외
    if has(lambda x: x["statement"] in ("INSERT", "UPDATE", "DELETE", "MERGE") and x["via"] == "sql_editor"):
        got.add("dml")
    if has(lambda x: x["statement"] == "DESCRIBE HISTORY"):
        got.add("history")
    if has(lambda x: "VERSION AS OF" in x["sql"].upper() and x["statement"] == "SELECT"):
        got.add("timetravel")
    if has(lambda x: x["statement"] == "RESTORE"):
        got.add("restore")
    if has(lambda x: x["via"] == "add_data" and x["statement"] == "CREATE TABLE"):
        got.add("upload")
    if has(lambda x: x["via"] == "add_data" and x["statement"] == "COPY INTO"):
        got.add("copy_into")
    if any(any(h.get("state") == "SUCCEEDED" for h in p.get("history", [])) for p in S.get("pipelines", {}).values()):
        got.add("pipeline_run")
    if any(j.get("runs") for j in S.get("jobs", {}).values()):
        got.add("job_run")
    if S.get("genie", {}).get("history"):
        got.add("genie")
    if S.get("eval_runs"):
        got.add("trace")
    if "cdc_events_viewed" in S.get("milestones", {}):
        got.add("cdc")
    if S.get("catalogs"):
        got.add("catalog")
    dp = S.get("dpipes", {})
    evs = [e for p in dp.values() for u in p.get("updates", []) if u.get("state") == "COMPLETED" for e in u.get("events", [])]
    if evs:
        got.add("dlt_run")
    if any(e.get("expectations") for e in evs):
        got.add("dlt_expect")
    if any(e.get("cdc") for e in evs):
        got.add("dlt_cdc")
    if any(d.get("published") for d in S.get("dash", {}).values()):
        got.add("dashboard")
    if has(lambda x: x["via"] == "designer" and x["statement"] in ("CREATE", "SELECT")):
        got.add("designer")
    ml = S.get("ml", {})
    if ml.get("runs"):
        got.add("ml_run")
    if ml.get("models"):
        got.add("ml_register")
    if ml.get("features"):
        got.add("feature")
    g = S.get("genai", {})
    if g.get("indexes"):
        got.add("ai_search")
    if g.get("evals"):
        got.add("genai_eval")
    if g.get("agents"):
        got.add("rag_agent")
    for e in S.get("audit", []):
        if e.get("event_type") == "SERVING_CREATE":
            got.add("serve_agent" if (e.get("detail") or {}).get("kind") == "agent" else "serve_model")
    return got


def view(S) -> dict:
    done = practice(S) | set(S.get("acad_done", []))      # 한 번 달성한 실습은 쿼리 이력(최근 300건)이 밀려도 유지
    S["acad_done"] = sorted(done)
    out = {"observed_at": OBSERVED, "evidence": "WORKSPACE_OBSERVED", "paths": [], "gaps": GAPS,
           "limits": ["Free Edition 계정 화면에서 본 범위이며 유료 워크스페이스·이후 업데이트와 다를 수 있습니다.",
                      "레슨 본문(노트북·실습 내용)은 수강을 시작해야 열려 조회하지 않았습니다. 대응은 제목 단위이며 실습 내용의 일치를 보증하지 않습니다.",
                      "공식 콘텐츠를 복제하지 않고 이름·구성만 대응시킵니다. 실제 코스는 Databricks Academy에서 본인 계정으로 진행하세요."]}
    for p in PATHS:
        cs = []
        for c in p["courses"]:
            n = {"full": 0, "partial": 0, "none": 0, "lecture": 0}
            ls = []
            for kind, title, v, cov, chk, note in c["lessons"]:
                n[cov] += 1
                ls.append({"kind": kind, "title": title, "view": v, "cov": cov, "note": note, "check": chk, "done": bool(chk and chk in done)})
            practice_total = sum(1 for x in ls if x["check"])
            cs.append({**{k: v for k, v in c.items() if k != "lessons"}, "lessons": ls, "coverage": n, "practice_total": practice_total, "practice_done": sum(1 for x in ls if x["done"])})
        out["paths"].append({"id": p["id"], "title": p["title"], "topics": p["topics"], "courses": cs})
    return out
