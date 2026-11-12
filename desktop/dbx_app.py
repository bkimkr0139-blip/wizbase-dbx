"""WIZBASE DBX Project Rehearsal — Windows PC 앱(데스크톱 셸).

https://dbx.wizbase.ai.kr 을 전용 창(WebView2)으로 연다. 화면·기능은 사이트와 동일하며 사이트가 갱신되면
사이트 쪽 업데이트 알림(적용 여부 확인)이 이 창에 표시된다. 앱 자체(exe) 신버전은 사이트가 알려 준다.
시스템 문서(.md)는 이 앱에 포함되지 않는다(서버도 앱 User-Agent 요청에는 문서를 내주지 않음).
"""
import ctypes
import os
import shutil
import subprocess
import sys
import urllib.request
import webbrowser
from pathlib import Path

APP_VERSION = "0.1.1"
APP_NAME = "WIZBASE DBX Rehearsal"
EXE_NAME = "WIZBASE-DBX-Rehearsal.exe"
URL = os.environ.get("DBX_URL", "https://dbx.wizbase.ai.kr/")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      f"Chrome/130.0 Safari/537.36 Edg/130.0 DBXDesktop/{APP_VERSION}")
INSTALL_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Programs" / "WIZBASE DBX Rehearsal"
DATA_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "WIZBASE" / "DBXRehearsal"


def msgbox(text, title=APP_NAME, flags=0x24):  # 0x24 = 예/아니오 + 물음표
    return ctypes.windll.user32.MessageBoxW(None, text, title, flags)


def shortcut(path: Path, target: Path):
    ps = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut('%s');$s.TargetPath='%s';$s.WorkingDirectory='%s';"
          "$s.IconLocation='%s,0';$s.Description='%s';$s.Save()" % (path, target, target.parent, target, APP_NAME))
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], creationflags=0x08000000, check=False)


def shortcut_paths():
    start = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / f"{APP_NAME}.lnk"
    desk = Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Desktop" / f"{APP_NAME}.lnk"
    return start, desk


def install_self():
    """실행 중인 exe를 사용자 폴더에 복사하고 바로가기를 만든다(관리자 권한 불필요)."""
    INSTALL_DIR.mkdir(parents=True, exist_ok=True)
    dst = INSTALL_DIR / EXE_NAME
    shutil.copy2(sys.executable, dst)
    for lnk in shortcut_paths():
        lnk.parent.mkdir(parents=True, exist_ok=True)
        shortcut(lnk, dst)
    return dst


def uninstall():
    for lnk in shortcut_paths():
        try:
            lnk.unlink()
        except OSError:
            pass
    # 실행 중 파일은 지울 수 없으므로 종료 후 삭제하도록 예약
    subprocess.Popen(f'cmd /c ping 127.0.0.1 -n 3 >nul & rmdir /s /q "{INSTALL_DIR}"', creationflags=0x08000000, shell=True)
    msgbox("제거되었습니다. 저장된 로그인 정보는 %LOCALAPPDATA%\\WIZBASE 에 남아 있어 필요하면 삭제하세요.", flags=0x40)


def first_run_install():
    """다운로드한 exe를 처음 실행하면 설치 여부를 묻는다. 설치 위치에서 실행 중이면 건너뜀."""
    if not getattr(sys, "frozen", False):
        return False
    here = Path(sys.executable).resolve()
    if here.parent == INSTALL_DIR.resolve() or "--no-install" in sys.argv:
        return False
    if msgbox(f"{APP_NAME} {APP_VERSION}\n\n이 PC에 설치할까요?\n(사용자 폴더에 복사하고 시작 메뉴·바탕화면 바로가기를 만듭니다. 관리자 권한 불필요)\n\n[아니오]를 누르면 설치 없이 이번만 실행합니다.") != 6:
        return False
    try:
        dst = install_self()
    except Exception as e:  # 설치 실패 시에도 앱은 실행
        msgbox(f"설치하지 못했습니다: {e}\n이번만 설치 없이 실행합니다.", flags=0x30)
        return False
    subprocess.Popen([str(dst), "--no-install"], cwd=str(dst.parent))
    return True


class Api:
    def open_external(self, url):
        if str(url).startswith(("https://", "http://")):
            webbrowser.open(url)
        return True


OFFLINE = """<!doctype html><meta charset=utf-8><body style="font-family:Segoe UI,Malgun Gothic,sans-serif;background:#0b1220;color:#e5e7eb;display:grid;place-items:center;height:100vh;margin:0">
<div style="max-width:460px;text-align:center"><h2>서버에 연결할 수 없습니다</h2><p style="color:#94a3b8">%s<br>네트워크를 확인한 뒤 다시 시도하세요.</p>
<button style="padding:10px 22px;font-size:15px;border:0;border-radius:8px;background:#3b82f6;color:#fff;cursor:pointer" onclick="location.href='%s'">다시 시도</button></div>"""


def reachable():
    try:
        urllib.request.urlopen(urllib.request.Request(URL, headers={"User-Agent": UA}), timeout=6).close()
        return True
    except Exception:
        return False


def main():
    if "--uninstall" in sys.argv:
        uninstall()
        return
    if first_run_install():
        return
    import webview
    webview.settings["ALLOW_DOWNLOADS"] = True
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if reachable():
        webview.create_window(f"{APP_NAME} v{APP_VERSION}", URL, width=1360, height=860, min_size=(900, 600), js_api=Api())
    else:
        webview.create_window(f"{APP_NAME} v{APP_VERSION}", html=OFFLINE % (URL, URL), width=900, height=600, js_api=Api())
    webview.start(user_agent=UA, private_mode=False, storage_path=str(DATA_DIR / "webview"))


if __name__ == "__main__":
    main()
