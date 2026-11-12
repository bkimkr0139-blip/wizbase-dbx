"""WIZBASE DBX Project Rehearsal — 단독 설치형(Windows).

서버(FastAPI+DuckDB)를 앱 안에 포함해 내 PC(127.0.0.1)에서만 실행한다. 학습 데이터는 %LOCALAPPDATA%\\WIZBASE\\DBXRehearsal-Standalone\\data 에 저장되며
운영자 PC가 꺼져 있어도 학습은 계속된다. 인터넷이 연결되면 (1) 새 설치 파일 유무 확인·선택 적용, (2) AXOS 피드백 전달이 이루어진다.
시스템 문서와 admin 기능은 포함되지 않는다(접근 코드는 이 PC에서 무작위 생성되며 운영자 코드와 무관).
"""
import ctypes
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

LOCAL = Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
DATA_ROOT = LOCAL / "WIZBASE" / "DBXRehearsal-Standalone"
INSTALL_DIR = LOCAL / "Programs" / "WIZBASE DBX Rehearsal Standalone"
EXE_NAME = "WIZBASE-DBX-Standalone.exe"
APP_NAME = "WIZBASE DBX Rehearsal (단독형)"
CENTRAL = os.environ.get("DBX_CENTRAL_URL", "https://dbx.wizbase.ai.kr").rstrip("/")
PORT = int(os.environ.get("DBX_PORT", "18830"))

# 백엔드는 import 시점에 환경변수로 데이터 경로를 정하므로 먼저 설정한다.
os.environ["DBX_DATA_DIR"] = str(DATA_ROOT / "data")
os.environ["DBX_STANDALONE"] = "1"
(DATA_ROOT / "data").mkdir(parents=True, exist_ok=True)
if sys.stdout is None or sys.stderr is None:  # windowed exe에는 콘솔이 없다
    _log = open(DATA_ROOT / "app.log", "a", encoding="utf-8", buffering=1)
    sys.stdout = sys.stderr = _log

STATE = {"state": "idle", "pct": 0, "msg": ""}


def msgbox(text, flags=0x40, title=APP_NAME):
    return ctypes.windll.user32.MessageBoxW(None, text, title, flags)


def exe_sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def shortcut(path: Path, target: Path):
    ps = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut('%s');$s.TargetPath='%s';$s.WorkingDirectory='%s';$s.IconLocation='%s,0';$s.Description='%s';$s.Save()"
          % (path, target, target.parent, target, APP_NAME))
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], creationflags=0x08000000, check=False)


def shortcut_paths():
    start = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / f"{APP_NAME}.lnk"
    desk = Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Desktop" / f"{APP_NAME}.lnk"
    return start, desk


def install_self():
    INSTALL_DIR.mkdir(parents=True, exist_ok=True)
    dst = INSTALL_DIR / EXE_NAME
    shutil.copy2(sys.executable, dst)
    for lnk in shortcut_paths():
        lnk.parent.mkdir(parents=True, exist_ok=True)
        shortcut(lnk, dst)
    return dst


def wait_pid(pid, timeout_ms=60000):
    h = ctypes.windll.kernel32.OpenProcess(0x00100000, False, int(pid))  # SYNCHRONIZE
    if h:
        ctypes.windll.kernel32.WaitForSingleObject(h, timeout_ms)
        ctypes.windll.kernel32.CloseHandle(h)


def uninstall():
    for lnk in shortcut_paths():
        try:
            lnk.unlink()
        except OSError:
            pass
    subprocess.Popen(f'cmd /c ping 127.0.0.1 -n 3 >nul & rmdir /s /q "{INSTALL_DIR}"', creationflags=0x08000000, shell=True)
    msgbox(f"앱을 제거했습니다.\n\n내 학습 데이터는 남아 있습니다:\n{DATA_ROOT}\n완전히 지우려면 이 폴더를 삭제하세요.")


def first_run_install():
    if not getattr(sys, "frozen", False) or "--no-install" in sys.argv:
        return False
    if Path(sys.executable).resolve().parent == INSTALL_DIR.resolve():
        return False
    if msgbox(f"{APP_NAME}\n\n이 PC에 설치할까요?\n(사용자 폴더에 복사하고 시작 메뉴·바탕화면 바로가기를 만듭니다. 관리자 권한 불필요)\n"
              f"학습 데이터는 {DATA_ROOT} 에 저장됩니다.\n\n[아니오]를 누르면 설치 없이 이번만 실행합니다.", 0x24) != 6:
        return False
    try:
        dst = install_self()
    except Exception as e:
        msgbox(f"설치하지 못했습니다: {e}\n이번만 설치 없이 실행합니다.", 0x30)
        return False
    subprocess.Popen([str(dst), "--no-install"], cwd=str(dst.parent))
    return True


def apply_update_mode():
    """새로 내려받은 exe가 --apply-update 로 실행되면: 기존 앱 종료를 기다린 뒤 설치 폴더의 앱을 교체하고 다시 시작한다."""
    if "--wait-pid" in sys.argv:
        wait_pid(sys.argv[sys.argv.index("--wait-pid") + 1])
    time.sleep(1)
    dst = install_self()
    subprocess.Popen([str(dst), "--no-install"], cwd=str(dst.parent))


class Api:
    def open_external(self, url):
        if str(url).startswith(("https://", "http://")):
            webbrowser.open(url)
        return True

    def update_state(self):
        return dict(STATE)

    def apply_update(self):
        if STATE["state"] == "running":
            return STATE
        STATE.update(state="running", pct=0, msg="새 버전 정보를 확인하는 중…")
        threading.Thread(target=self._download, daemon=True).start()
        return STATE

    def _download(self):
        try:
            m = json.loads(urllib.request.urlopen(urllib.request.Request(CENTRAL + "/api/app/manifest", headers={"User-Agent": "DBXDesktop-Standalone"}), timeout=10).read())
            sa = m["standalone"]
            if not sa["available"]:
                raise RuntimeError("운영자 서버에 설치 파일이 아직 없습니다.")
            tmp = Path(tempfile.mkdtemp(prefix="dbx_upd_")) / EXE_NAME
            h = hashlib.sha256()
            with urllib.request.urlopen(urllib.request.Request(CENTRAL + sa["download"], headers={"User-Agent": "DBXDesktop-Standalone"}), timeout=30) as r, open(tmp, "wb") as f:
                got = 0
                while True:
                    b = r.read(1 << 20)
                    if not b:
                        break
                    f.write(b)
                    h.update(b)
                    got += len(b)
                    STATE.update(pct=int(got * 100 / max(1, sa["size"])), msg=f"내려받는 중… {got // 1048576}MB / {sa['size'] // 1048576}MB")
            if h.hexdigest() != sa["sha256"]:
                raise RuntimeError("내려받은 파일의 무결성 검사(SHA-256)가 일치하지 않습니다. 다시 시도하세요.")
            STATE.update(state="ready", pct=100, msg="내려받기 완료 — 앱을 다시 시작합니다. (학습 데이터는 유지됩니다)")
            subprocess.Popen([str(tmp), "--apply-update", "--wait-pid", str(os.getpid())], cwd=str(tmp.parent))
            time.sleep(1.5)
            os._exit(0)
        except Exception as e:
            STATE.update(state="error", msg=f"업데이트 실패: {e}")


LOADING = """<!doctype html><meta charset=utf-8><body style="font-family:Segoe UI,Malgun Gothic,sans-serif;background:#0b1220;color:#e5e7eb;display:grid;place-items:center;height:100vh;margin:0">
<div style="text-align:center"><h2>WIZBASE DBX Project Rehearsal</h2><p style="color:#94a3b8">단독형 서버를 시작하는 중입니다… (처음 실행 시 데이터 준비로 수십 초 걸릴 수 있습니다)</p></div>"""


def start_server():
    import uvicorn
    from backend.main import app
    cfg = uvicorn.Config(app, host="127.0.0.1", port=PORT, log_config=None, access_log=False)
    srv = uvicorn.Server(cfg)
    threading.Thread(target=srv.run, daemon=True).start()
    return srv


def wait_ready(timeout=120):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/app/manifest", timeout=2).close()
            return True
        except Exception:
            time.sleep(0.5)
    return False


def main():
    if "--uninstall" in sys.argv:
        return uninstall()
    if "--apply-update" in sys.argv:
        return apply_update_mode()
    if first_run_install():
        return
    mutex = ctypes.windll.kernel32.CreateMutexW(None, False, "Local\\WIZBASE_DBX_STANDALONE")
    if ctypes.windll.kernel32.GetLastError() == 183:
        msgbox("이미 실행 중입니다. 열려 있는 창을 확인하세요.", 0x30)
        return
    if getattr(sys, "frozen", False):
        os.environ["DBX_EXE_SHA"] = exe_sha(sys.executable)
    import webview
    from backend import sysinfo
    ua = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36 Edg/130.0 "
          f"DBXDesktop/{sysinfo.VERSION} Standalone")
    webview.settings["ALLOW_DOWNLOADS"] = True
    win = webview.create_window(f"{APP_NAME} v{sysinfo.VERSION}", html=LOADING, width=1360, height=860, min_size=(900, 600), js_api=Api())

    def boot():
        start_server()
        if wait_ready():
            win.load_url(f"http://127.0.0.1:{PORT}/")
        else:
            win.load_html("<body style='font-family:sans-serif'><h3>서버를 시작하지 못했습니다.</h3><p>로그: " + str(DATA_ROOT / "app.log") + "</p>")

    webview.start(boot, user_agent=ua, private_mode=False, storage_path=str(DATA_ROOT / "webview"))
    del mutex


if __name__ == "__main__":
    main()
