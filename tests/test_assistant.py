"""AI 지원 전수 점검: 초보자가 실제로 던질 법한 자연어 질문 → 의도·답변 내용·바로가기가 맞는지 확인한다."""
import pytest
from test_at import client, env, login  # noqa: F401
from backend import assistant, sysinfo

# (질문, 현재 화면, 기대 의도, 답변에 들어가야 할 말(하나라도), 바로가기 화면(하나라도 있어야 함, None이면 검사 안 함))
CASES = [
    # --- 인사·사용법
    ("안녕하세요", "env", "greeting", ["AI 지원"], None),
    ("고마워요", "sql", "greeting", ["AI 지원"], None),
    ("뭘 물어볼 수 있어?", "env", "capabilities", ["다음에 뭐 해", "이 화면"], None),
    ("사용법 알려줘", "env", "capabilities", ["물어보세요"], None),
    # --- 처음/시작
    ("처음인데 어떻게 시작해요?", "env", "howto", ["환경 점검", "세션 시작"], ["env"]),
    ("세션은 어떻게 만들어?", "env", "howto", ["새 세션", "세션 시작"], ["env"]),
    ("시작", "env", "howto", ["환경 점검"], ["env"]),
    ("세션 지우는 방법", "env", "howto", ["선택 삭제"], ["env"]),
    ("세션을 삭제하고 싶어요", "env", "howto", ["선택 삭제"], ["env"]),
    # --- 다음 단계/진행
    ("다음에 뭐 해?", "env", "next", ["단계"], None),
    ("이제 뭘 해야 해요?", "sql", "next", ["단계"], None),
    ("뭐부터 하면 돼?", "env", "next", ["단계"], None),
    ("진행률 알려줘", "env", "progress", ["%"], None),
    ("지금 어디까지 했어?", "env", "progress", ["%"], None),
    ("전체 절차 보여줘", "env", "journey", ["1.", "단계"], None),
    ("전체 순서가 어떻게 돼?", "env", "journey", ["1."], None),
    # --- 현재 화면
    ("이 화면은 뭐야?", "sql", "this_screen", ["SQL Editor", "처음 할 일"], None),
    ("여기가 어디야?", "comp", "this_screen", ["Compute", "Warehouse"], None),
    ("지금 화면 설명해줘", "perm", "this_screen", ["권한"], None),
    ("이 메뉴는 뭐하는 거야", "pipe", "this_screen", ["Pipelines"], None),
    ("이 화면에서 뭘 해야 돼요?", "cat", "this_screen", ["Catalog"], None),
    # --- 화면 이동
    ("SQL 편집기 열어줘", "env", "navigate", ["이동"], ["sql"]),
    ("권한 화면으로 가줘", "sql", "navigate", ["이동"], ["perm"]),
    ("Pipelines 화면 열어줘", "env", "navigate", ["이동"], ["pipe"]),
    ("시험센터 어디야?", "env", "navigate", ["이동"], ["exam"]),
    ("노트북 화면 보여줘", "env", "navigate", ["이동"], ["nb"]),
    ("컴퓨트로 이동", "sql", "navigate", ["이동"], ["comp"]),
    ("카탈로그 탐색 화면 어디예요", "env", "navigate", ["이동"], ["cat"]),
    ("Jobs 어디서 봐요?", "env", "navigate", ["이동"], ["jobs"]),
    ("고객 시연 화면 열어줘", "env", "navigate", ["이동"], ["demo"]),
    ("공식 목표 지도 가줘", "env", "navigate", ["이동"], ["map"]),
    ("증거 보고서로 이동", "env", "navigate", ["이동"], ["evid"]),
    ("학습계획 화면 열어", "env", "navigate", ["이동"], ["plan"]),
    # --- 화면 설명
    ("SQL Editor가 뭐야?", "env", None, ["SQL"], None),
    ("Catalog Explorer는 뭐하는 화면이에요?", "env", "screen", ["catalog.schema.table", "Catalog"], None),
    ("Compute 화면 설명해줘", "env", None, ["Warehouse"], None),
    ("Agent 승인 화면은 무슨 기능이야?", "env", "screen", ["승인"], None),
    ("시험센터에서 뭘 할 수 있어?", "env", "screen", ["모의시험", "문항"], None),
    ("실습 증거함은 뭐야?", "env", "screen", ["증거"], None),
    ("전이 시드는 뭐예요?", "env", None, ["산업"], None),
    ("역량 등급 화면 설명", "env", None, ["내부 등급"], None),
    # --- 용어
    ("Databricks가 뭐야?", "env", "glossary", ["플랫폼"], None),
    ("Unity Catalog가 뭐야?", "env", "glossary", ["거버넌스", "권한"], None),
    ("유니티 카탈로그 설명해줘", "env", "glossary", ["거버넌스"], None),
    ("메달리온이 뭐예요?", "env", "glossary", ["bronze", "silver", "gold"], None),
    ("브론즈 실버 골드가 뭐야", "env", "glossary", ["bronze", "silver", "gold"], None),
    ("스키마가 뭐야?", "cat", "glossary", ["catalog.schema.table", "3단계"], None),
    ("Delta Lake가 뭐야", "env", "glossary", ["저장 형식", "Delta"], None),
    ("SQL Warehouse가 뭐예요?", "comp", "glossary", ["SQL", "컴퓨트"], None),
    ("서버리스가 뭐야?", "comp", "glossary", ["서버리스"], None),
    ("파이프라인이 뭐지?", "pipe", "glossary", ["정제", "파이프라인"], None),
    ("expectations가 뭐야?", "pipe", "glossary", ["품질 규칙", "Expectations"], None),
    ("Job이 뭐야?", "jobs", "glossary", ["자동 실행", "Job"], None),
    ("run-as가 뭐야", "jobs", "glossary", ["실행 신원", "run-as"], None),
    ("CDC가 뭐예요?", "cdc", "glossary", ["변경", "CDC"], None),
    ("Genie가 뭐야?", "genie", "glossary", ["자연어", "Genie"], None),
    ("번들이 뭐야?", "bundle", "glossary", ["validate", "Bundle"], None),
    ("증거 수준이 뭐야?", "evid", "glossary", ["SIMULATED", "LOCAL_EXECUTED"], None),
    ("모드 A와 B 차이가 뭐예요?", "env", "glossary", ["모의", "로컬"], None),
    ("안내형 실전형 차이?", "env", "glossary", ["안내형", "실전형"], None),
    ("합성 데이터가 뭐야", "env", "glossary", ["가짜", "개인정보"], None),
    ("PoC가 뭐야?", "env", "glossary", ["시범", "PoC"], None),
    ("AXOS가 뭐야?", "env", "glossary", ["탭", "피드백"], None),
    ("DE-A가 뭐예요?", "exam", "glossary", ["Associate", "Professional"], None),
    ("objective가 뭐야?", "map", "glossary", ["출제 목표", "objective"], None),
    ("가용재고가 뭐야?", "req", "glossary", ["현재고", "예약"], None),
    ("세션이 뭐야?", "env", "glossary", ["연습 공간", "세션"], None),
    ("권한 모델이 뭐야?", "perm", "glossary", ["USE", "SELECT"], None),
    # --- 작업 방법
    ("SQL은 어떻게 실행해?", "sql", "howto", ["Warehouse", "실행"], ["sql"]),
    ("쿼리 실행하려면 어떻게 해요?", "sql", "howto", ["SQL Editor", "실행"], ["sql"]),
    ("테이블 조회 방법 알려줘", "sql", "howto", ["SELECT", "실행"], ["sql"]),
    ("웨어하우스는 어떻게 시작해?", "comp", "howto", ["시작", "RUNNING"], ["comp"]),
    ("Warehouse 켜는 법", "comp", "howto", ["시작", "RUNNING"], ["comp"]),
    ("권한 오류는 어떻게 해결해?", "sql", "howto", ["권한 요청", "자동으로"], ["perm"]),
    ("권한 요청은 어떻게 해?", "perm", "howto", ["요청 제출"], ["perm"]),
    ("권한이 없대요 어떻게 해요", "sql", "howto", ["권한 요청"], ["perm"]),
    ("피드백은 어디서 보내?", "env", "howto", ["AXOS", "제출"], None),
    ("불편한 점을 알리고 싶어요", "env", "howto", ["AXOS"], None),
    ("기능 추가 요청하고 싶어요", "env", "howto", ["AXOS"], None),
    ("업데이트는 어떻게 해?", "env", "howto", ["업데이트"], None),
    ("새 버전 확인하는 방법", "env", "howto", ["업데이트"], None),
    ("앱은 어떻게 설치해요?", "env", "howto", ["다운로드", "설치"], None),
    ("exe 다운로드 어디서 해요", "env", "howto", ["다운로드"], None),
    ("로그인은 어떻게 해요?", "env", "howto", ["실명", "접근 코드"], None),
    ("접근 코드가 뭐예요?", "env", "howto", ["접근 코드"], None),
    ("시험 준비는 어떻게 해?", "env", "howto", ["학습계획", "시험센터"], ["plan", "exam"]),
    ("모의시험 보려면?", "exam", "howto", ["시험센터"], ["exam"]),
    ("실습 증거는 어떻게 제출해요?", "lab", "howto", ["해시", "승인"], ["lab"]),
    ("파이프라인 실행은 어떻게?", "pipe", "howto", ["Pipelines", "실행"], ["pipe"]),
    ("Job 실패했을 때 어떻게 해?", "jobs", "howto", ["repair", "run-as"], ["jobs"]),
    ("주문 변경 승인은 어떻게 해?", "agent", "howto", ["승인", "제안"], ["agent"]),
    ("단축키 알려줘", "env", "howto", ["F10", "Alt"], None),
    ("메뉴 구성 알려줘", "env", "howto", ["홈", "워크스페이스", "도움말"], None),
    ("전체 기능 목록 알려줘", "env", "howto", ["Catalog", "SQL Editor"], None),
    ("접속이 안 돼요", "env", "howto", ["운영자 PC", "단독 설치형"], None),
    ("너무 느려요", "env", "howto", ["동시 접속", "단독 설치형"], None),
    ("내 데이터는 어디에 저장돼요?", "env", "howto", ["내 PC", "저장"], None),
    # --- 오류
    ("왜 실패했어?", "sql", "error", ["최근", "실패"], None),
    ("에러가 났어요", "sql", "error", [], None),
    ("INSUFFICIENT_PERMISSIONS가 뭐야?", "sql", "error_code", ["권한 오류"], ["perm"]),
    ("WAREHOUSE_NOT_RUNNING 오류 해결", "sql", "error_code", ["Warehouse", "시작"], ["comp"]),
    ("TABLE_OR_VIEW_NOT_FOUND는 왜 나와?", "sql", "error_code", ["3단계", "철자"], None),
    # --- 공식 근거(KB)
    ("UC 권한 개념 설명해줘", "perm", "glossary", ["docs.databricks.com"], None),
    ("Auto Loader랑 COPY INTO 차이", "conn", None, ["Auto Loader"], None),
    ("Delta Live Tables 이름이 바뀌었어?", "pipe", None, ["Lakeflow"], None),
    # --- 모르는 질문은 지어내지 않는다
    ("양자 컴퓨팅 가격?", "env", "fallback", ["확인 필요"], None),
    ("오늘 날씨 어때?", "env", "fallback", ["확인 필요"], None),
    ("주식 추천해줘", "env", "fallback", ["확인 필요"], None),
]


def ask(env, q, view, session=True):
    sid = env["sid"] if session else None
    return env["c"].post("/api/guide/chat", headers=env["L"], json={"message": q, "session_id": sid, "view": view}).json()


@pytest.mark.parametrize("q,view,intent,words,navs", CASES)
def test_beginner_questions(env, q, view, intent, words, navs):
    r = ask(env, q, view)
    a = r["answer"]
    if intent:
        assert r["intent"] == intent, f"{q!r} -> {r['intent']}\n{a[:200]}"
    if words:
        assert any(w in a for w in words), f"{q!r}: 답변에 {words} 없음\n{a[:300]}"
    if navs:
        got = {s.get("view") for s in r["shortcuts"] if s.get("type") == "nav"}
        assert got & set(navs), f"{q!r}: 바로가기 {navs} 없음 (있는 것: {got})"
    assert r["answer"].strip() and r["shortcuts"] is not None


def test_no_session_general_questions_still_answered(env):
    for q, key in (("Unity Catalog가 뭐야?", "거버넌스"), ("처음 시작하려면?", "환경 점검"), ("이 화면은 뭐야?", "처음 할 일"), ("권한 화면 열어줘", "이동")):
        r = ask(env, q, "env" if "화면은" in q else "sql", session=False)
        assert key in r["answer"], (q, r["answer"][:120])
    r = ask(env, "다음에 뭐 해?", "env", session=False)
    assert "세션" in r["answer"] and any(s.get("view") == "env" for s in r["shortcuts"])


def test_all_menu_views_have_screen_guides_and_aliases():
    views = [i["view"] for t in sysinfo.info()["menu"] for i in t["items"]]
    missing = [v for v in views if v not in assistant.SCR]
    assert not missing, f"화면 안내가 없는 메뉴: {missing}"
    for v in views:
        name, why, steps, nxt, tip = assistant.SCR[v]
        assert name and why and steps and tip and (nxt is None or nxt in assistant.SCR)


def test_every_screen_answer_and_role_gating(env):
    for v in assistant.SCR:
        r = ask(env, f"{assistant.SCR[v][0]} 화면 설명해줘", "env")
        assert assistant.SCR[v][0] in r["answer"] or v in ("env",), (v, r["answer"][:80])
    # 학습자에게 admin 전용 화면 이동 버튼을 주지 않는다
    r = ask(env, "피드백 관리 화면 열어줘", "env")
    assert not any(s.get("view") == "fbq" for s in r["shortcuts"])


def test_real_mode_does_not_leak_next_hint(env):
    s = env["c"].post("/api/sessions", headers=env["L"], json={"learning_mode": "real"}).json()["session_id"]
    r = env["c"].post("/api/guide/chat", headers=env["L"], json={"message": "다음에 뭐 해?", "session_id": s, "view": "env"}).json()
    assert "정답 위치를 안내하지 않습니다" in r["answer"]


def test_answers_always_offer_a_next_step(env):
    for q, view, *_ in CASES[:60]:
        r = ask(env, q, view)
        assert r["shortcuts"], f"{q!r}: 바로가기·후속 질문이 없음(막다른 답변)"
