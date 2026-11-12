"""WIZBASE DBX Project Rehearsal — 단독 설치형(Windows · macOS).

서버(FastAPI+DuckDB)를 앱 안에 포함해 내 PC(127.0.0.1)에서만 실행한다. 학습 데이터는 %LOCALAPPDATA%\\WIZBASE\\DBXRehearsal-Standalone\\data 에 저장되며
운영자 PC가 꺼져 있어도 학습은 계속된다. 인터넷이 연결되면 (1) 새 설치 파일 유무 확인·선택 적용, (2) AXOS 피드백 전달이 이루어진다.
시스템 문서와 admin 기능은 포함되지 않는다(접근 코드는 이 PC에서 무작위 생성되며 운영자 코드와 무관).
"""
import ctypes
import hashlib
import platform
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

IS_WIN, IS_MAC = sys.platform == "win32", sys.platform == "darwin"
if IS_WIN:
    LOCAL = Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
    DATA_ROOT = LOCAL / "WIZBASE" / "DBXRehearsal-Standalone"
    INSTALL_DIR = LOCAL / "Programs" / "WIZBASE DBX Rehearsal Standalone"
elif IS_MAC:  # macOS: 앱(.app)은 응용 프로그램 폴더로 끌어다 놓아 설치, 데이터는 Application Support 에 저장
    DATA_ROOT = Path.home() / "Library" / "Application Support" / "WIZBASE" / "DBXRehearsal-Standalone"
    INSTALL_DIR = Path.home() / "Applications"
else:
    DATA_ROOT = Path.home() / ".local" / "share" / "wizbase" / "dbx-standalone"
    INSTALL_DIR = DATA_ROOT
PLATFORM_KEY = "win" if IS_WIN else ("mac_arm64" if platform.machine() == "arm64" else "mac_x64")  # 운영 서버 manifest 에서 내 설치 파일 항목
EXE_NAME = "WIZBASE-DBX-Standalone.exe"
APP_NAME = "WIZBASE DBX Rehearsal (단독형)"
CENTRAL = os.environ.get("DBX_CENTRAL_URL", "https://dbx.wizbase.ai.kr").rstrip("/")
PORT = int(os.environ.get("DBX_PORT", "18830"))
EXE_COMPAT = 1  # backend/sysinfo.py STANDALONE_COMPAT 와 같아야 팩(화면·서버 코드 업데이트)을 받을 수 있다. 새 라이브러리·껍데기 변경 시 함께 올리고 exe를 다시 빌드

# 백엔드는 import 시점에 환경변수로 데이터 경로를 정하므로 먼저 설정한다.
os.environ["DBX_DATA_DIR"] = str(DATA_ROOT / "data")
os.environ["DBX_STANDALONE"] = "1"
os.environ["DBX_EXE_COMPAT"] = str(EXE_COMPAT)
os.environ["DBX_PLATFORM"] = PLATFORM_KEY
OVERLAY = DATA_ROOT / "overlay"          # 내려받은 콘텐츠 팩(화면+서버 코드)이 놓이는 곳: current(적용 중) / prev(직전) / rejected(실패해 폐기)
OVERLAY_ACTIVE = False
(DATA_ROOT / "data").mkdir(parents=True, exist_ok=True)
if sys.stdout is None or sys.stderr is None:  # windowed exe에는 콘솔이 없다
    _log = open(DATA_ROOT / "app.log", "a", encoding="utf-8", buffering=1)
    sys.stdout = sys.stderr = _log

CLEAN_ENV = {**os.environ, "PYINSTALLER_RESET_ENVIRONMENT": "1"}  # 자기 자신/새 exe를 다시 띄울 때 부모의 압축 해제 폴더를 물려받지 않도록
STATE = {"state": "idle", "pct": 0, "msg": ""}


class OverlayFinder:
    """backend.<모듈> import 시 overlay/current/backend/<모듈>.py 가 있으면 exe에 내장된 것보다 먼저 사용한다."""

    def __init__(self, root):
        self.dir = Path(root) / "backend"

    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith("backend.") and fullname.count(".") == 1:
            f = self.dir / (fullname.split(".")[1] + ".py")
            if f.is_file():
                import importlib.util
                return importlib.util.spec_from_file_location(fullname, str(f))
        return None


def tel_headers():
    try:
        from backend import telemetry
        return telemetry.headers()
    except Exception:
        return {}


def baked_content_id():
    for base in (getattr(sys, "_MEIPASS", None), str(Path(__file__).parent)):
        if base and (Path(base) / "content_id.txt").is_file():
            return (Path(base) / "content_id.txt").read_text(encoding="utf-8").strip()
    return ""


def setup_overlay():
    """적용된 팩이 온전하면 import 경로에 끼워 넣고, 아니면 폐기한다. 항상 현재 content_id를 환경변수로 알린다."""
    global OVERLAY_ACTIVE
    cur = OVERLAY / "current"
    cid = baked_content_id()
    if getattr(sys, "frozen", False) and "--no-overlay" not in sys.argv and (cur / "manifest.json").is_file():
        try:
            from backend import pack
            mf = pack.verify_dir(cur, EXE_COMPAT)
            sys.meta_path.insert(0, OverlayFinder(cur))
            OVERLAY_ACTIVE, cid = True, mf["content_id"]
        except Exception as e:
            print("overlay rejected:", e)
            reject_overlay()
    os.environ["DBX_CONTENT_ID"] = cid


def reject_overlay():
    cur, rej = OVERLAY / "current", OVERLAY / "rejected"
    try:
        if rej.exists():
            shutil.rmtree(rej, ignore_errors=True)
        if cur.exists():
            cur.rename(rej)
    except OSError:
        shutil.rmtree(cur, ignore_errors=True)


def restart_self(extra=()):
    exe = sys.executable
    subprocess.Popen([exe, "--no-install", "--wait-pid", str(os.getpid()), *extra], cwd=str(Path(exe).parent), env=CLEAN_ENV)
    time.sleep(0.5)
    os._exit(0)


def msgbox(text, flags=0x40, title=APP_NAME):
    if IS_WIN:
        return ctypes.windll.user32.MessageBoxW(None, text, title, flags)
    if IS_MAC:
        subprocess.run(["osascript", "-e", f"display dialog {json.dumps(text)} with title {json.dumps(title)} buttons {{\"확인\"}} default button 1"], check=False)
    return 1


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
    if IS_WIN:
        h = ctypes.windll.kernel32.OpenProcess(0x00100000, False, int(pid))  # SYNCHRONIZE
        if h:
            ctypes.windll.kernel32.WaitForSingleObject(h, timeout_ms)
            ctypes.windll.kernel32.CloseHandle(h)
        return
    end = time.time() + timeout_ms / 1000
    while time.time() < end:
        try:
            os.kill(int(pid), 0)
        except OSError:
            return
        time.sleep(0.3)


def uninstall():
    for lnk in shortcut_paths():
        try:
            lnk.unlink()
        except OSError:
            pass
    subprocess.Popen(f'cmd /c ping 127.0.0.1 -n 3 >nul & rmdir /s /q "{INSTALL_DIR}"', creationflags=0x08000000, shell=True)
    msgbox(f"앱을 제거했습니다.\n\n내 학습 데이터는 남아 있습니다:\n{DATA_ROOT}\n완전히 지우려면 이 폴더를 삭제하세요.")


def first_run_install():
    if not IS_WIN or not getattr(sys, "frozen", False) or "--no-install" in sys.argv:  # Windows 전용(macOS는 .app 을 응용 프로그램 폴더로 이동)
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
    subprocess.Popen([str(dst), "--no-install"], cwd=str(dst.parent), env=CLEAN_ENV)
    return True


def apply_update_mode():
    """새로 내려받은 exe가 --apply-update 로 실행되면: 기존 앱 종료를 기다린 뒤 설치 폴더의 앱을 교체하고 다시 시작한다."""
    if "--wait-pid" in sys.argv:
        wait_pid(sys.argv[sys.argv.index("--wait-pid") + 1])
    time.sleep(1)
    shutil.rmtree(OVERLAY, ignore_errors=True)  # 새 exe가 더 최신 — 이전 팩 제거
    dst = install_self()
    subprocess.Popen([str(dst), "--no-install"], cwd=str(dst.parent), env=CLEAN_ENV)


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
            m = json.loads(urllib.request.urlopen(urllib.request.Request(CENTRAL + "/api/app/manifest", headers={"User-Agent": "DBXDesktop-Standalone", **tel_headers()}), timeout=10).read())
            self._m = m
            sa, pk = m["standalone"], m.get("pack") or {}
            if int(sa.get("compat", 0)) != EXE_COMPAT:
                self._kind = "exe"
                self._download_exe(sa)
            elif pk.get("available"):
                self._kind = "pack"
                self._download_pack(pk)
            else:
                raise RuntimeError("운영자 서버에 업데이트 파일이 아직 없습니다.")
        except Exception as e:
            STATE.update(state="error", msg=f"업데이트 실패: {e}")
            try:
                from backend import telemetry
                telemetry.report("update_failed", kind=getattr(self, "_kind", ""), error=str(e)[:80])      # 실패도 서버 기록에 남긴다(인터넷 연결 시)
            except Exception:
                pass

    def _fetch(self, url, dest, size, sha, label):
        h = hashlib.sha256()
        with urllib.request.urlopen(urllib.request.Request(CENTRAL + url, headers={"User-Agent": "DBXDesktop-Standalone", **tel_headers()}), timeout=30) as r, open(dest, "wb") as f:
            got = 0
            while True:
                b = r.read(1 << 18)
                if not b:
                    break
                f.write(b)
                h.update(b)
                got += len(b)
                STATE.update(pct=int(got * 100 / max(1, size)), msg=f"{label} 내려받는 중… {got // 1024}KB / {size // 1024}KB")
        if h.hexdigest() != sha:
            raise RuntimeError("내려받은 파일의 무결성 검사(SHA-256)가 일치하지 않습니다. 다시 시도하세요.")

    def _download_pack(self, pk):
        from backend import pack
        tmp = Path(tempfile.mkdtemp(prefix="dbx_pack_"))
        self._fetch(pk["download"], tmp / "pack.zip", pk["size"], pk["sha256"], "기능 업데이트")
        inc = OVERLAY / "incoming"
        shutil.rmtree(inc, ignore_errors=True)
        pack.extract_verified(tmp / "pack.zip", inc, pk["content_id"], EXE_COMPAT)
        prev, cur = OVERLAY / "prev", OVERLAY / "current"
        shutil.rmtree(prev, ignore_errors=True)
        if cur.exists():
            cur.rename(prev)
        inc.rename(cur)
        STATE.update(state="ready", pct=100, msg="업데이트 적용 완료 — 앱을 다시 시작합니다. (학습 데이터는 유지됩니다)")
        if getattr(sys, "frozen", False):
            time.sleep(1.2)
            restart_self()

    def _download_exe(self, sa):
        if IS_MAC:  # macOS: 앱 번들 교체는 사용자가 직접(내려받은 새 앱으로 기존 앱을 덮어쓰기). 데이터는 별도 폴더라 유지된다.
            info = self._m.get(PLATFORM_KEY) or {}
            if not info.get("available"):
                raise RuntimeError("운영자 서버에 Mac용 설치 파일이 아직 없습니다.")
            webbrowser.open(CENTRAL + info["download"])
            STATE.update(state="ready", pct=100, msg="새 버전 다운로드를 열었습니다. 내려받은 앱으로 기존 앱을 교체하세요. (학습 데이터는 유지됩니다)")
            return
        if not sa["available"]:
            raise RuntimeError("운영자 서버에 설치 파일이 아직 없습니다.")
        tmp = Path(tempfile.mkdtemp(prefix="dbx_upd_")) / EXE_NAME
        self._fetch(sa["download"], tmp, sa["size"], sa["sha256"], "새 버전")
        STATE.update(state="ready", pct=100, msg="내려받기 완료 — 앱을 다시 시작합니다. (학습 데이터는 유지됩니다)")
        subprocess.Popen([str(tmp), "--apply-update", "--wait-pid", str(os.getpid())], cwd=str(tmp.parent), env=CLEAN_ENV)
        time.sleep(1.5)
        os._exit(0)


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
    if "--wait-pid" in sys.argv:
        wait_pid(sys.argv[sys.argv.index("--wait-pid") + 1])
    if IS_WIN:
        mutex = ctypes.windll.kernel32.CreateMutexW(None, False, "Local\\WIZBASE_DBX_STANDALONE")
        if ctypes.windll.kernel32.GetLastError() == 183:
            msgbox("이미 실행 중입니다. 열려 있는 창을 확인하세요.", 0x30)
            return
    else:
        import fcntl
        mutex = open(DATA_ROOT / ".lock", "w")
        try:
            fcntl.flock(mutex, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            msgbox("이미 실행 중입니다. 열려 있는 창을 확인하세요.")
            return
    if getattr(sys, "frozen", False):
        os.environ["DBX_EXE_SHA"] = exe_sha(sys.executable)
    setup_overlay()
    import webview
    try:
        from backend import sysinfo
    except Exception as e:  # 적용된 팩이 import 단계에서 깨진 경우: 폐기하고 내장 버전으로 다시 시작
        print("backend import failed:", e)
        if OVERLAY_ACTIVE:
            reject_overlay()
            restart_self(("--no-overlay",))
        raise
    ua = (("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36 Edg/130.0 " if IS_WIN else "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15 ")
          + f"DBXDesktop/{sysinfo.VERSION} Standalone")
    webview.settings["ALLOW_DOWNLOADS"] = True
    win = webview.create_window(f"{APP_NAME} v{sysinfo.VERSION}", html=LOADING, width=1360, height=860, min_size=(900, 600), js_api=Api())

    def boot():
        try:
            start_server()
            ok = wait_ready(60 if OVERLAY_ACTIVE else 120)
        except Exception as e:
            print("server start failed:", e)
            ok = False
        if not ok and OVERLAY_ACTIVE:  # 새 팩이 문제를 일으키면 폐기하고 내장 버전으로 자동 복구
            reject_overlay()
            restart_self(("--no-overlay",))
        if ok:
            win.load_url(f"http://127.0.0.1:{PORT}/")
        else:
            win.load_html("<body style='font-family:sans-serif'><h3>서버를 시작하지 못했습니다.</h3><p>로그: " + str(DATA_ROOT / "app.log") + "</p>")

    webview.start(boot, user_agent=ua, private_mode=False, storage_path=str(DATA_ROOT / "webview"))
    del mutex


if __name__ == "__main__":
    main()
