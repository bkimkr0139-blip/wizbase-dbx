"""화면·내비게이션 무결성: 모든 버튼에 동작이 있고, 모든 이동 대상 화면과 도움말이 존재하는지 정적으로 점검한다."""
import re
import pathlib

from backend import assistant, guide, sysinfo

ROOT = pathlib.Path(__file__).resolve().parent.parent
APP = ROOT.joinpath("static", "app.js").read_text(encoding="utf-8")
HELP = ROOT.joinpath("static", "help.js").read_text(encoding="utf-8")
MENU_VIEWS = [v for _, _, its in sysinfo.MENU for v, _, _ in its]


def _block(src, start_pat):
    i = src.index(start_pat)
    return src[i:]


def handlers():
    blk = _block(APP, "window.H = {")
    names = set(re.findall(r"(?:async )?([A-Za-z_][A-Za-z0-9_]*)\([A-Za-z_, ]*\)\s*\{", blk))
    names |= set(re.findall(r"^  ([A-Za-z_][A-Za-z0-9_]*): ", blk, re.M))
    return names


def views():
    blk = _block(APP, "const V = {")
    return set(re.findall(r"^  (?:async )?([A-Za-z0-9_]+)\(\) \{", blk, re.M))


def test_every_button_action_has_a_handler():
    used = set(re.findall(r'data-a="([A-Za-z0-9_]+)"', APP + HELP))
    missing = sorted(used - handlers())
    assert not missing, f"동작(H.*)이 없는 버튼: {missing}"


def test_every_navigation_target_is_a_real_view():
    v = views()
    targets = set(re.findall(r'data-v="([a-z0-9]+)"', APP)) | set(re.findall(r'\b(?:SCN|N)\(\s*"[^"]*",\s*"([a-z0-9]+)"', APP + HELP))
    targets |= set(re.findall(r'nav\("[^"]*",\s*"([a-z0-9]+)"', ROOT.joinpath("backend", "guide.py").read_text(encoding="utf-8") + ROOT.joinpath("backend", "assistant.py").read_text(encoding="utf-8")))
    bad = sorted(t for t in targets if t not in v)
    assert not bad, f"존재하지 않는 화면으로 이동하는 링크: {bad}"
    assert not [m for m in MENU_VIEWS if m not in v], "메뉴에 있으나 화면이 없음"


def test_every_menu_screen_has_help_and_ai_guide():
    help_keys = set(re.findall(r"\n  ([a-z0-9]+): \{\s*t: ", HELP))
    missing = [m for m in MENU_VIEWS if m not in help_keys]
    assert not missing, f"HELP(F1) 설명이 없는 메뉴 화면: {missing}"
    assert not [m for m in MENU_VIEWS if m not in assistant.SCR]


def test_journey_shortcuts_point_to_real_views():
    v = views()
    bad = []
    for st in guide.JOURNEY:
        for sub in st.get("subs", []) if isinstance(st, dict) else []:
            pass
    src = ROOT.joinpath("backend", "guide.py").read_text(encoding="utf-8")
    for m in re.finditer(r'(?:nav|run)\([^)]*?,\s*"([a-z0-9]+)"\s*(?:,|\))', src):
        pass
    views_in_guide = set(re.findall(r'"view":\s*"([a-z0-9]+)"', src)) | set(re.findall(r'nav\("[^"]*",\s*"([a-z0-9]+)"', src))
    bad = sorted(x for x in views_in_guide if x not in v)
    assert not bad, f"AI 지원 여정이 가리키는 화면이 없음: {bad}"
