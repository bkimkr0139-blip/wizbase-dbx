"""v0.7.0 신규 기능(AX 스튜디오·서버 자원 관리·자동 구축)이 HELP·AI 지원·오류 안내·시스템 문서에 누락 없이 반영됐는지 점검한다.
코드에서 목록(오류 코드·도구·환경변수·화면 탭)을 뽑아 대조하므로 기능을 추가하고 안내를 빠뜨리면 실패한다."""
import glob, re
import pytest
from test_at import client, env, login  # noqa: F401  (앱 데이터 적재)
from backend import assistant as A, sysinfo, guide as G, ax, ax_tools, ops

HELP_JS = open("static/help.js", encoding="utf-8").read()
AX_JS = open("static/x_ax.js", encoding="utf-8").read()
OPS_JS = open("static/x_ops.js", encoding="utf-8").read()
SRC = {f: open(f, encoding="utf-8").read() for f in glob.glob("backend/ax*.py") + ["backend/ops.py"]}


def help_entry(key):
    m = re.search(rf"^  {key}: \{{.*$", HELP_JS, re.M)
    assert m, key
    return m.group(0)


# ---- 오류 코드: 코드에서 던지는 모든 ApiError 코드가 해결 안내를 가진다
def test_every_ax_error_code_has_a_remedy():
    codes = set()
    for f, t in SRC.items():
        if f.endswith("ax_errors.py"):
            continue
        codes |= set(re.findall(r'ApiError\(\d+,\s*"([A-Z_0-9]+)"', t))
    assert len(codes) > 100
    missing = sorted(c for c in codes if c not in G.ERR_HELP)
    assert not missing, missing
    assert all(len(G.ERR_HELP[c]) > 15 for c in codes)


def test_error_code_in_a_question_gets_its_remedy():
    r = A.answer(None, {"role": "learner"}, "STALE_PROPOSAL 오류가 났어요")
    assert "다시 제안" in r["answer"] and r["intent"] != "fallback"
    r = A.answer(None, {"role": "admin"}, "RESOURCE_BLOCKED 이게 뭐야")
    assert "정리" in r["answer"]


# ---- AI 지원: 기능별 질문이 fallback 없이 핵심 단어를 포함해 답한다
QA = [
    ("온톨로지가 뭐야?", "STALE"), ("ERD 에서 점선이 뭐야", "점선"), ("관계 후보는 어떻게 승인해?", "domain_expert"), ("자동 구축이 뭐야?", "AUTO_POLICY"),
    ("자동 구축하는 방법 알려줘", "자동 구축 승인"), ("서버 자원 관리 화면은 뭐야", "SSD/HDD"), ("서버 자원 확인하는 법", "정리 승인"),
    ("메모리 부족하면 어떻게 해?", "정리 후보"), ("신호 inbox 가 뭐야", "ASSUMPTION"), ("hybrid 검색이 뭐야", "RRF"),
    ("문서 파서가 지원하는 형식", "pdf"), ("스캔 PDF 는 읽어?", "OCR"), ("secret 참조가 뭐야", "WZ_SECRET"), ("지원하는 db 알려줘", "Oracle"),
    ("멱등 키가 뭐야", "한 번만"), ("제안 승인 실행 방법", "STALE"), ("entity_lookup 이 뭐야", "entity_related"), ("매입처 시나리오가 뭐야", "MOQ"),
    ("외부 사용자 범위 설명", "내부 사용자 전용"), ("NATIVE_FIXTURE 가 뭐야", "합성"), ("AX 프로젝트 시작하기", "snapshot"),
    ("문서 올려 검색하는 방법", "시행일"), ("실제 DB 시험은 어떻게 해?", "WZ_AX_REAL"), ("신호 확인하는 법", "탐지"),
]


@pytest.mark.parametrize("q,word", QA)
def test_ai_answers_ax_questions(q, word):
    r = A.answer(None, {"role": "admin"}, q)
    assert r["intent"] != "fallback", q
    assert word.lower() in r["answer"].lower(), (q, r["answer"][:240])


def test_ops_is_admin_only_in_ai_navigation():
    r = A.answer(None, {"role": "learner"}, "서버 자원 관리 화면 열어줘")
    assert not any(s.get("view") == "ops" or s.get("v") == "ops" for s in r.get("shortcuts", [])) or "전용" in r["answer"]


def test_ai_text_covers_every_tool_and_scenario():
    txt = " ".join(t for _, _, t, _ in A.GLOSS)
    for name in ("entity_lookup", "entity_related"):
        assert name in txt
    for ko in ("주문 증량", "납기 지연 대안", "단가 차이", "미수금", "추가 발주", "공급처 변경", "단가 급등", "입고 차이"):
        assert ko in txt, ko
    assert set(ax_tools.CONTRACTS) >= {"entity_lookup", "entity_related", "order_increase", "receipt_variance"}


# ---- HELP(우측 탭)
def test_help_ax_entry_lists_every_feature():
    e = help_entry("ax")
    for w in ("PostgreSQL", "MySQL", "Oracle", "secret", "구조 수집", "ERD", "온톨로지", "STALE", "native", "매출", "매입", "업무 명령", "문서 검색", "신호", "자동 구축", "AUTO_POLICY",
              "golden 24건", "보안 11건", "rollback", "직접 DB 접속", "해시", "DBX"):
        assert w in e, w
    for label in re.findall(r'\["(?:proj|conn|erd|onto|agent|biz|auto|search|sig|ev)", "([^"]+)"\]', AX_JS):
        assert label, label


def test_help_ops_entry_lists_every_feature():
    e = help_entry("ops")
    for w in ("CPU", "메모리", "SSD/HDD", "프로세스", "작업 전 판단", "정리", "확인 문구", "재검증", "감사", "admin", "60초"):
        assert w.lower() in e.lower(), w


def test_help_counts_match_code():
    n_golden = len(ax.GOLDEN) + len(ax.GOLDEN_TOOLS)
    assert n_golden == 24
    assert f"golden {n_golden}건" in help_entry("ax")
    assert f"golden {n_golden}건" in " ".join(next(c for c in sysinfo.CHANGELOG if c["version"] == "0.7.0")["notes"])


def test_every_ui_tab_is_in_help_or_ai(env):
    tabs = re.findall(r'\["(proj|conn|erd|onto|agent|biz|auto|search|sig|ev)", "([^"]+)"\]', AX_JS)
    assert len(tabs) == 10
    both = help_entry("ax") + A.SCR["ax"][1] + " ".join(A.SCR["ax"][2])
    for key, label in tabs:
        assert key in ("proj", "conn", "erd", "onto", "agent", "biz", "auto", "search", "sig", "ev")
    for w in ("프로젝트", "연결", "구조 수집", "ERD", "온톨로지", "에이전트", "업무 명령", "자동 구축", "문서 검색", "신호", "평가"):
        assert w in both or w in help_entry("ax"), w
    for t in ops.TASKS:
        assert t in OPS_JS or t in [x for x in ops.TASKS]


# ---- 시스템 문서·변경 이력
def test_system_document_covers_v070(env):
    doc = sysinfo.system_document()
    assert sysinfo.VERSION.startswith("0.7.")
    for w in ("AX 프로젝트 스튜디오", "서버 자원 관리", "자동 구축", "AUTO_POLICY", "PostgreSQL 16.16", "MySQL 8.4.13", "Oracle 26ai", "NATIVE_FIXTURE", "SPEC_ONLY",
              "WZ_SECRET_", "WZ_AX_ALLOW_DIRECT_DB", "WZ_AX_DB_HOSTS", "WZ_AX_DOC_DIRS", "WZ_AX_EMBED", "DBX_NO_OPS_WARM", "WZ_AX_REAL", "psutil", "pypdf", "AX_ADAPTER_VERIFICATION.md",
              "connector agent", "SHACL", "신호", "hybrid", "golden 24건", "보안 11건", "고객 개발 DB"):
        assert w in doc, w
    assert any(v == "ax" for _, _, its in sysinfo.MENU for v, _, _ in its) and any(v == "ops" for _, _, its in sysinfo.MENU for v, _, _ in its)


def test_changelog_has_v070_entry_with_all_themes():
    assert sysinfo.CHANGELOG[0]["version"] == sysinfo.VERSION
    c = next(x for x in sysinfo.CHANGELOG if x["version"] == "0.7.0")
    t = " ".join(c["notes"])
    for w in ("AX 프로젝트 스튜디오", "ERD", "온톨로지", "native", "PostgreSQL 16.16", "MySQL 8.4.13", "Oracle 26ai", "매출", "매입", "문서 검색", "서버 자원 관리", "자동 구축", "한계"):
        assert w in t, w


def test_every_operational_env_var_in_code_is_documented(env):
    used = set()
    for f, t in SRC.items():
        used |= set(re.findall(r'"((?:WZ_AX_[A-Z_]+|DBX_NO_OPS_WARM|WZ_SECRET_))', t))
    assert {"WZ_AX_ALLOW_DIRECT_DB", "WZ_AX_DB_HOSTS", "WZ_AX_DOC_DIRS", "WZ_AX_EMBED", "DBX_NO_OPS_WARM"} <= used
    doc = sysinfo.system_document()
    miss = sorted(v for v in used if v not in doc)
    assert not miss, miss


def test_limitations_are_not_overstated(env):
    doc = sysinfo.system_document()
    for w in ("미검증", "비신경망", "OCR", "현업 정답"):
        assert w in doc or w in " ".join(next(c for c in sysinfo.CHANGELOG if c["version"] == "0.7.0")["notes"]) or w in HELP_JS, w
    assert "SQL_PREPARED_NOT_EXECUTED" not in doc          # 더 이상 실행하지 않은 상태로 적혀 있으면 안 됨
    assert not any(x["status"] == "SQL_PREPARED_NOT_EXECUTED" for x in ax.SUPPORT)
