"""시스템 업데이트가 HELP·AI 지원에 자동 반영되는지 확인한다(코드 수정 없이 변경 이력·메뉴·시스템 문서만 바꿔도 따라가야 함)."""
import re, subprocess, sys
import pytest
from test_at import client, env, login  # noqa: F401
from backend import assistant as A, sysinfo

HELP_JS = open("static/help.js", encoding="utf-8").read()


def test_whats_new_comes_from_changelog_automatically(monkeypatch):
    r = A.answer(None, {"role": "learner"}, "이번 버전 새 기능이 뭐야?")
    assert r["intent"] == "whatsnew" and f"v{sysinfo.VERSION}" in r["answer"] and sysinfo.CHANGELOG[0]["notes"][0][:20] in r["answer"]
    old = A.answer(None, {"role": "learner"}, "0.6.0 변경 내용 알려줘")
    assert "v0.6.0" in old["answer"] and "시도 ID" in old["answer"]
    fake = [{"version": "9.9.9", "date": "2099-01-01", "notes": ["쿼카 모듈 자동화 기능 추가"]}] + sysinfo.CHANGELOG
    monkeypatch.setattr(sysinfo, "CHANGELOG", fake)                       # 변경 이력에 항목만 추가하면
    monkeypatch.setattr(sysinfo, "VERSION", "9.9.9")
    r = A.answer(None, {"role": "learner"}, "최근 변경 사항이 뭐야")
    assert "v9.9.9" in r["answer"] and "쿼카 모듈 자동화" in r["answer"]   # AI 지원이 코드 수정 없이 답한다


def test_new_menu_screen_gets_ai_navigation_without_editing_assistant(monkeypatch):
    menu = list(sysinfo.MENU) + [("신규", "new", [("zzdemo", "쿼카 관리 화면", "쿼카 모듈을 관리하는 신규 화면")])]
    monkeypatch.setattr(sysinfo, "MENU", menu)
    assert "zzdemo" not in A.SCR
    try:
        r = A.answer(None, {"role": "learner"}, "쿼카 관리 화면은 뭐야?")
        assert "zzdemo" in A.SCR and "쿼카" in r["answer"] and "자동 생성" in r["answer"]
        assert any("쿼카" in (s.get("label") or "") for s in r["shortcuts"])
    finally:
        A.SCR.pop("zzdemo", None)
        A.ALIAS.pop("zzdemo", None)


def test_system_document_text_is_answered_automatically(env, monkeypatch):
    base = sysinfo.system_document
    monkeypatch.setattr(sysinfo, "system_document", lambda *a, **k: base(*a, **k) + "\n- 쿼카모듈 모듈은 새벽 3시에 자동 점검을 수행하며 실패하면 관리자에게 알림을 보낸다.\n")
    r = A.answer(None, {"role": "learner"}, "쿼카모듈 모듈 새벽 3시 알림 대상")
    assert r["intent"] == "doc" and "새벽 3시" in r["answer"] and "인용" in r["answer"]
    r = A.answer(None, {"role": "learner"}, "완전히무관한단어xyzqq 에 대해")
    assert r["intent"] == "fallback"                                           # 근거가 없으면 지어내지 않는다


def test_doc_search_does_not_hijack_existing_answers():
    for q, intent in (("다음에 뭐 해?", None), ("Unity Catalog가 뭐야?", "glossary"), ("온톨로지가 뭐야?", "glossary")):
        r = A.answer(None, {"role": "learner"}, q)
        assert r["intent"] not in ("doc", "whatsnew", "fallback"), (q, r["intent"])


def test_help_panel_auto_features_exist_in_static_js():
    assert "function autoHelp" in HELP_JS and "HELP[VIEW] || autoHelp(VIEW)" in HELP_JS      # HELP 항목이 없는 새 화면도 메뉴 정보로 자동 생성
    assert "function helpWhatsNew" in HELP_JS and "SYS.changelog[0]" in HELP_JS and "${helpWhatsNew()}" in HELP_JS   # 이번 버전 변경 자동 표시


def test_release_check_script_detects_stale_docs(tmp_path):
    src = open("tools/release_check.py", encoding="utf-8").read()
    assert "SKIP_RELEASE_CHECK" in src and "CHANGELOG" in src and "--install" in src
    hook = open(".githooks/pre-push", encoding="utf-8").read()
    assert "release_check.py" in hook
    r = subprocess.run([sys.executable, "-c", "import sys;sys.path.insert(0,'tools');import release_check as r;import re;"
                        "assert r.FEATURE.match('backend/ax.py') and r.FEATURE.match('static/app.js') and not r.FEATURE.match('backend/sysinfo.py') and not r.FEATURE.match('tests/test_x.py')"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
