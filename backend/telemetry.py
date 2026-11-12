"""단독 설치형 앱 → 운영 서버 사용 신호(설치 ID·실행·업데이트 결과) 전달.

- 설치 ID: 설치마다 한 번 만드는 무작위 값(개인·기기 식별 정보 아님). 서버는 이 값과 IP 일부(마지막 자리 숨김)로 설치 PC를 구분한다.
- 보내는 것: 설치 ID, 앱 버전, 플랫폼·OS 이름, (업데이트 시) 이전/새 버전·방식·성공 여부. 학습 데이터·SQL·이름은 보내지 않는다(이름은 피드백 제출 때만).
- 인터넷이 없으면 로컬 큐(최대 100건)에 두었다가 연결될 때 보낸다. 사용자는 앱 정보에서 전송을 끌 수 있다(끄면 신호만 중단, 피드백 전달·업데이트는 그대로).
"""
from __future__ import annotations
import json, os, platform, threading, time, urllib.request, uuid
from pathlib import Path

CENTRAL = os.environ.get("DBX_CENTRAL_URL", "https://dbx.wizbase.ai.kr").rstrip("/")
_LOCK = threading.Lock()


def _dir() -> Path:
    d = Path(os.environ.get("DBX_DATA_DIR", "data"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def standalone() -> bool:
    return os.environ.get("DBX_STANDALONE") == "1"


def install_id() -> str:
    p = _dir() / "install_id.txt"
    try:
        v = p.read_text(encoding="utf-8").strip()
        if len(v) == 32:
            return v
    except OSError:
        pass
    v = uuid.uuid4().hex
    p.write_text(v, encoding="utf-8")
    return v


def enabled() -> bool:
    return standalone() and os.environ.get("DBX_TELEMETRY") != "0" and not (_dir() / "telemetry_off").exists()


def set_enabled(on: bool):
    f = _dir() / "telemetry_off"
    if on:
        try:
            f.unlink()
        except OSError:
            pass
    else:
        f.write_text("off", encoding="utf-8")


def set_user(name: str):
    """이 설치에서 마지막으로 로그인한 사용자(자기 입력 실명). 서버가 설치 ID ↔ 사용자를 연결하는 데 쓴다."""
    try:
        (_dir() / "last_user.txt").write_text(str(name).strip()[:40], encoding="utf-8")
    except OSError:
        pass


def get_user() -> str:
    try:
        return (_dir() / "last_user.txt").read_text(encoding="utf-8").strip()[:40]
    except OSError:
        return ""


def meta() -> dict:
    from . import sysinfo
    return {"install": install_id(), "app_version": sysinfo.VERSION, "platform": os.environ.get("DBX_PLATFORM", "win"), "os": platform.platform()[:60], "content_id": os.environ.get("DBX_CONTENT_ID", "")[:16], "user": get_user()}


def headers() -> dict:
    """중앙 서버로 가는 모든 요청에 붙이는 구분 헤더(다운로드·업데이트 확인 기록용). 전송을 끄면 비어 있다."""
    if not enabled():
        return {}
    m = meta()
    return {"X-DBX-Install": m["install"], "X-DBX-App": f"{m['app_version']}/{m['platform']}"}


def _post(path: str, body: dict, timeout: int = 6):
    req = urllib.request.Request(CENTRAL + path, method="POST", data=json.dumps(body).encode("utf-8"), headers={"Content-Type": "application/json", "User-Agent": "DBXDesktop-Standalone", **headers()})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _qpath() -> Path:
    return _dir() / "telemetry_queue.json"


def _load_q() -> list:
    try:
        return json.loads(_qpath().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def queue(event: str, **kw):
    if not enabled():
        return
    with _LOCK:
        q = _load_q()
        q.append({"event": event, "t": int(time.time()), **meta(), **{k: str(v)[:80] for k, v in kw.items() if v is not None}})
        _qpath().write_text(json.dumps(q[-100:], ensure_ascii=False), encoding="utf-8")


def flush() -> int:
    """큐의 이벤트를 순서대로 보낸다. 연결이 안 되면 멈추고 남겨 둔다. 보낸 건수를 돌려준다."""
    if not enabled():
        return 0
    sent = 0
    with _LOCK:
        q = _load_q()
        while q:
            try:
                _post("/api/app/telemetry", q[0])
            except Exception:
                break
            q.pop(0)
            sent += 1
        _qpath().write_text(json.dumps(q, ensure_ascii=False), encoding="utf-8")
    return sent


def report(event: str, **kw):
    """이벤트를 큐에 넣고 백그라운드에서 전송을 시도한다(서비스 동작을 막지 않는다)."""
    try:
        queue(event, **kw)
        threading.Thread(target=flush, daemon=True).start()
    except Exception:
        pass


def startup_report():
    """앱(서버) 시작 시: 실행 신호 + 지난 실행과 버전/내용/설치 파일이 달라졌으면 '업데이트 적용됨'."""
    try:
        from . import sysinfo
        p = _dir() / "last_run.json"
        cur = {"version": sysinfo.VERSION, "content_id": os.environ.get("DBX_CONTENT_ID", ""), "exe_sha": os.environ.get("DBX_EXE_SHA", "")}
        try:
            prev = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            prev = None
        report("start")
        if prev and (prev.get("version") != cur["version"] or prev.get("content_id") != cur["content_id"] or prev.get("exe_sha") != cur["exe_sha"]):
            kind = "exe" if prev.get("exe_sha") and prev.get("exe_sha") != cur["exe_sha"] else "pack"
            report("update_applied", kind=kind, from_version=prev.get("version"), to_version=cur["version"])
        p.write_text(json.dumps(cur), encoding="utf-8")
    except Exception:
        pass
