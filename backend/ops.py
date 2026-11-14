"""서버 자원 모니터링(CPU·메모리·SSD/HDD·프로세스)과 작업 전 판단, 사용자 승인형 자원 정리.
- 관리자(admin) 전용. 프로세스 명령줄은 비밀 값을 가려서 표시한다.
- 정리는 '이 시스템이 만든 것'만 후보로 올린다(임시 시험 폴더·캐시·로그·시험용 컨테이너·이 저장소의 시험 프로세스).
  계획(plan) 생성 → 사용자가 후보를 골라 확인 문구와 함께 승인 → 실행 직전 재검증 → 감사 기록. 승인 없이 삭제·종료하지 않는다."""
from __future__ import annotations
import json, os, re, shutil, subprocess, sys, tempfile, threading, time, secrets
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

from .core import ApiError

try:
    import psutil
except Exception:  # pragma: no cover
    psutil = None

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get("DBX_DATA_DIR", ROOT / "data"))
LOCK = threading.RLock()
HIST = deque(maxlen=240)          # 15초 간격 약 1시간
_thread = None
_disk_cache = {"at": 0, "v": None}
PLANS: dict = {}
AUDIT_FILE = DATA / "ops_audit.json"
try:
    AUDIT: list = json.loads(AUDIT_FILE.read_text(encoding="utf-8")) if AUDIT_FILE.exists() else []
except Exception:
    AUDIT = []
CONFIRM = "정리 승인"
GB = 1024 ** 3

# 작업별 최소 여유(경험적 기준 — 환경에 맞게 조정). (가용 메모리 GB, CPU 사용률 상한 %, 데이터 디스크 여유 GB)
TASKS = {
    "ax_scan": ("DB 구조 수집·profile", 0.5, 90, 1),
    "pipeline": ("파이프라인 실행", 1.0, 85, 2),
    "embedding": ("문서 파싱·청킹·임베딩(해시)", 0.5, 90, 1),
    "embedding_neural": ("신경망 임베딩(Ollama)", 4.0, 80, 4),
    "auto_build": ("자동 구축(전체)", 1.5, 90, 3),
    "full_tests": ("전체 테스트", 2.0, 85, 2),
    "real_db_tests": ("실제 DB 컨테이너 시험(Oracle 포함)", 6.0, 80, 10),
}
MEM_CRITICAL = 92.0   # 시스템 메모리 사용률(%) — 이 이상이면 무거운 작업 차단
MEM_WARN = 85.0


def _iso():
    return datetime.now(timezone.utc).isoformat()


def _need():
    if psutil is None:
        raise ApiError(501, "PSUTIL_MISSING", "psutil 이 설치되어 있지 않아 자원 모니터링을 쓸 수 없습니다(pip install psutil).")


def _mask(cmd):
    s = " ".join(cmd or [])
    s = re.sub(r"(?i)(--?(?:password|passwd|pwd|token|secret|api[-_]?key|sim-token)[= ]+)\S+", r"\1***", s)
    s = re.sub(r"(?i)\b(password|passwd|pwd|token|secret|api[-_]?key)=\S+", r"\1=***", s)
    s = re.sub(r"(?i)(://[^:/@\s]+:)[^@\s]+@", r"\1***@", s)
    return s[:140]


# ------------------------------------------------------------------ 디스크 종류(SSD/HDD)
def _disk_kinds():
    now = time.time()
    if _disk_cache["v"] is not None and now - _disk_cache["at"] < 600:
        return _disk_cache["v"]
    out = {"physical": [], "map": {}}
    try:
        if sys.platform == "win32":
            ps = ("$d=Get-PhysicalDisk|Select-Object DeviceId,FriendlyName,MediaType,BusType,Size;"
                  "$p=Get-Partition|Where-Object DriveLetter|Select-Object DriveLetter,DiskNumber;"
                  "@{disks=@($d);parts=@($p)}|ConvertTo-Json -Depth 4 -Compress")
            r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], capture_output=True, text=True, timeout=20)
            j = json.loads(r.stdout or "{}")
            disks = j.get("disks") or []
            disks = [disks] if isinstance(disks, dict) else disks
            parts = j.get("parts") or []
            parts = [parts] if isinstance(parts, dict) else parts
            for d in disks:
                mt = str(d.get("MediaType") or "Unspecified")
                kind = "SSD" if mt.upper() == "SSD" else ("HDD" if mt.upper() == "HDD" else "미확인")
                out["physical"].append({"id": str(d.get("DeviceId")), "model": d.get("FriendlyName"), "kind": kind, "bus": str(d.get("BusType")), "size": d.get("Size")})
            kinds = {p["id"]: p for p in out["physical"]}
            for p in parts:
                dl = p.get("DriveLetter")
                if isinstance(dl, int):
                    dl = chr(dl)
                if dl:
                    out["map"][f"{str(dl).upper()}:\\"] = kinds.get(str(p.get("DiskNumber")), {})
        else:
            for blk in Path("/sys/block").glob("*"):
                rot = blk / "queue" / "rotational"
                if rot.exists() and not blk.name.startswith(("loop", "ram")):
                    out["physical"].append({"id": blk.name, "model": (blk / "device" / "model").read_text().strip() if (blk / "device" / "model").exists() else None,
                                            "kind": "HDD" if rot.read_text().strip() == "1" else "SSD", "bus": "", "size": None})
    except Exception:
        pass
    _disk_cache.update(at=now, v=out)
    return out


# ------------------------------------------------------------------ 스냅샷
def snapshot_light():
    _need()
    vm = psutil.virtual_memory()
    return {"cpu_percent": psutil.cpu_percent(interval=None), "mem_percent": vm.percent, "mem_available": vm.available}


_PC = {"at": 0.0, "data": None, "running": False, "wanted": 0.0}


def _proc_scan(top):
    """프로세스 전수 조회(이 PC처럼 백신이 있으면 10~25초 걸릴 수 있어 캐시해서 쓴다)."""
    procs = []
    for p in psutil.process_iter(["pid", "name", "memory_info"]):
        try:
            p.cpu_percent(None)
            procs.append(p)
        except Exception:
            pass
    time.sleep(0.5)
    rows, me = [], os.getpid()
    ncpu = psutil.cpu_count() or 1
    for p in procs:
        try:
            if p.pid == 0:                           # System Idle Process 는 점유가 아니라 유휴 시간
                continue
            mi = p.info["memory_info"]
            # cpu 는 전체 CPU 대비 %(코어 수로 나눔)
            rows.append({"pid": p.pid, "name": p.info["name"] or "", "cpu": round(p.cpu_percent(None) / ncpu, 1), "rss": mi.rss if mi else 0, "cmd": "", "role": "other", "_p": p})
        except Exception:
            continue
    chosen = {r["pid"] for r in sorted(rows, key=lambda r: -r["cpu"])[:top] + sorted(rows, key=lambda r: -r["rss"])[:top]}
    chosen |= {r["pid"] for r in rows if r["name"].lower().startswith(("python", "uvicorn", "node", "docker", "com.docker", "wizbase", "vmmem")) or r["pid"] == me}
    for r in rows:
        if r["pid"] in chosen:                       # 명령줄·사용자·시작 시각은 느려서 필요한 프로세스만
            try:
                cmd = r["_p"].cmdline()
            except Exception:
                cmd = []
            r["cmd"], r["role"] = _mask(cmd), _role_of(r["pid"], me, cmd)
            try:
                r["user"] = (r["_p"].username() or "").split("\\")[-1]
                r["started"] = datetime.fromtimestamp(r["_p"].create_time()).isoformat(timespec="seconds")
                r["threads"] = r["_p"].num_threads()
            except Exception:
                pass
    for r in rows:
        r.pop("_p", None)
    by_name = {}
    for r in rows:
        g = by_name.setdefault(r["name"], {"name": r["name"], "count": 0, "cpu": 0.0, "rss": 0})
        g["count"] += 1; g["cpu"] = round(g["cpu"] + r["cpu"], 1); g["rss"] += r["rss"]
    return {"process_count": len(rows), "top_cpu": sorted(rows, key=lambda r: -r["cpu"])[:top], "top_memory": sorted(rows, key=lambda r: -r["rss"])[:top],
            "by_name": sorted(by_name.values(), key=lambda g: -g["rss"])[:top], "app_processes": sorted([r for r in rows if r["role"] != "other"], key=lambda r: -r["rss"])[:20]}


def _proc_refresh(top, wait):
    def work():
        try:
            d = _proc_scan(top)
            _PC.update(at=time.time(), data=d)
        finally:
            _PC["running"] = False
    with LOCK:
        if _PC["running"]:
            started = False
        else:
            _PC["running"] = True
            started = True
    if not started:
        t0 = time.time()
        while wait and _PC["running"] and time.time() - t0 < 120:
            time.sleep(0.3)
        return
    t = threading.Thread(target=work, daemon=True, name="ops-proc-scan")
    t.start()
    if wait:
        t.join(120)


def live():
    """빠른 지표(CPU·메모리·디스크). 5초 간격 갱신용."""
    _need()
    per = psutil.cpu_percent(interval=0.2, percpu=True)
    vm, sw = psutil.virtual_memory(), psutil.swap_memory()
    kinds = _disk_kinds()
    disks = []
    for d in psutil.disk_partitions(all=False):
        if "cdrom" in (d.opts or "") or not d.fstype:
            continue
        try:
            u = psutil.disk_usage(d.mountpoint)
        except Exception:
            continue
        k = kinds["map"].get(d.mountpoint.upper() if sys.platform == "win32" else d.mountpoint) or {}
        disks.append({"mount": d.mountpoint, "fs": d.fstype, "total": u.total, "used": u.used, "free": u.free, "percent": u.percent, "kind": k.get("kind", "미확인"), "model": k.get("model")})
    try:
        io = psutil.disk_io_counters()
        dio = {"read_bytes": io.read_bytes, "write_bytes": io.write_bytes} if io else None
    except Exception:
        dio = None
    freq = None
    try:
        f = psutil.cpu_freq()
        freq = round(f.current) if f else None
    except Exception:
        pass
    cpu = round(sum(per) / len(per), 1) if per else 0
    return {"at": _iso(), "cpu": {"percent": cpu, "per_core": per, "logical": psutil.cpu_count(), "physical": psutil.cpu_count(logical=False), "mhz": freq},
            "memory": {"total": vm.total, "available": vm.available, "used": vm.used, "percent": vm.percent, "swap_total": sw.total, "swap_used": sw.used, "swap_percent": sw.percent},
            "disks": disks, "physical_disks": kinds["physical"], "disk_io_total": dio, "level": _level(vm.percent, cpu)}


def snapshot(top=12, fresh=False):
    """빠른 지표 + 프로세스 표(캐시). fresh=True 면 프로세스 표를 새로 조회(느릴 수 있음)."""
    _need()
    _PC["wanted"] = time.time()
    if fresh or _PC["data"] is None:
        _proc_refresh(top, True)
    elif time.time() - _PC["at"] > 60:
        _proc_refresh(top, False)         # 오래되면 뒤에서 갱신하고 이번에는 이전 표를 보여 줌
    s = live()
    d = _PC["data"] or {"process_count": 0, "top_cpu": [], "top_memory": [], "by_name": [], "app_processes": []}
    d = dict(d, top_cpu=d["top_cpu"][:top], top_memory=d["top_memory"][:top], by_name=d["by_name"][:top])
    s.update(d)
    s["processes_age_s"] = int(time.time() - _PC["at"]) if _PC["at"] else None
    s["processes_note"] = "프로세스 표는 조회가 느려 최대 60초 전 값일 수 있습니다(processes_age_s)."
    s["app"] = app_usage()
    return s


def _role_of(pid, me, cmd):
    c = " ".join(cmd or []).lower()
    if pid == me:
        return "this_server"
    if "backend.main:app" in c:
        return "wizbase_server"
    if str(ROOT).lower() in c:
        return "wizbase_related"
    if "docker" in c or "com.docker" in c or "vmmem" in c:
        return "docker"
    return "other"


def _level(mem, cpu):
    return "CRITICAL" if mem >= MEM_CRITICAL or cpu >= 97 else ("WARN" if mem >= MEM_WARN or cpu >= 90 else "OK")


def dir_size(p, limit=50000):
    t = n = 0
    try:
        for r, ds, fs in os.walk(p):
            for f in fs:
                try:
                    t += os.path.getsize(os.path.join(r, f))
                except OSError:
                    pass
                n += 1
                if n >= limit:
                    return t
    except OSError:
        pass
    return t


def app_usage():
    me = psutil.Process()
    ax = DATA / "ax"
    return {"pid": me.pid, "rss": me.memory_info().rss, "threads": me.num_threads(), "data_dir": str(DATA), "data_size": dir_size(DATA), "ax_size": dir_size(ax) if ax.exists() else 0,
            "uptime_s": int(time.time() - me.create_time())}


# ------------------------------------------------------------------ 이력
def _sampler():
    while True:
        try:
            s = snapshot_light()
            HIST.append({"t": _iso(), "cpu": s["cpu_percent"], "mem": s["mem_percent"]})
        except Exception:
            pass
        time.sleep(15)


def history():
    global _thread
    _need()
    with LOCK:
        if _thread is None:
            threading.Thread(target=_disk_kinds, daemon=True).start()     # SSD/HDD 판별(느림)을 미리 데움
            psutil.cpu_percent(None)
            HIST.append({"t": _iso(), "cpu": psutil.cpu_percent(None), "mem": psutil.virtual_memory().percent})
            _thread = threading.Thread(target=_sampler, daemon=True, name="ops-sampler")
            _thread.start()
    return list(HIST)


# ------------------------------------------------------------------ 작업 전 판단
def preflight(task):
    _need()
    if task not in TASKS:
        raise ApiError(400, "BAD_TASK", "task=" + "|".join(TASKS))
    label, need_mem, cpu_max, need_disk = TASKS[task]
    vm = psutil.virtual_memory()
    cpu = psutil.cpu_percent(interval=0.3)
    du = shutil.disk_usage(DATA if DATA.exists() else ROOT)
    avail, free = vm.available / GB, du.free / GB
    reasons, verdict = [], "OK"

    def bad(level, msg):
        nonlocal verdict
        reasons.append({"level": level, "msg": msg})
        if level == "BLOCK" or (level == "CAUTION" and verdict == "OK"):
            verdict = level
    if vm.percent >= MEM_CRITICAL:
        bad("BLOCK", f"시스템 메모리 사용률 {vm.percent}% — 위험 수준({MEM_CRITICAL}% 이상)")
    elif vm.percent >= MEM_WARN:
        bad("CAUTION", f"시스템 메모리 사용률 {vm.percent}% — 높음({MEM_WARN}% 이상)")
    if avail < need_mem:
        bad("BLOCK" if avail < need_mem * 0.6 else "CAUTION", f"가용 메모리 {avail:.1f}GB < 권장 {need_mem}GB")
    if cpu >= cpu_max:
        bad("CAUTION", f"CPU 사용률 {cpu}% ≥ 기준 {cpu_max}%")
    if free < need_disk:
        bad("BLOCK" if free < need_disk * 0.5 else "CAUTION", f"데이터 디스크 여유 {free:.1f}GB < 권장 {need_disk}GB")
    if not reasons:
        reasons.append({"level": "OK", "msg": "자원이 충분합니다."})
    sug = []
    if verdict != "OK":
        plan = cleanup_candidates()
        rec = sum(c["bytes"] for c in plan)
        if plan:
            sug.append(f"정리 후보 {len(plan)}건(약 {rec / GB:.2f}GB 확보 가능) — 관리 화면에서 확인 후 승인하세요.")
        sug.append("무거운 작업은 자원이 확보된 뒤 실행하거나, 다른 프로세스를 직접 정리하세요(이 시스템은 다른 앱을 종료하지 않습니다).")
    return {"task": task, "label": label, "verdict": verdict, "reasons": reasons, "suggestions": sug, "at": _iso(),
            "measured": {"mem_available_gb": round(avail, 2), "mem_percent": vm.percent, "cpu_percent": cpu, "disk_free_gb": round(free, 2)},
            "thresholds": {"mem_gb": need_mem, "cpu_max": cpu_max, "disk_gb": need_disk, "mem_warn": MEM_WARN, "mem_critical": MEM_CRITICAL}, "note": "경험적 기준이며 환경에 따라 조정이 필요합니다."}


def guard(task):
    """자동 파이프라인용: BLOCK 이면 예외."""
    r = preflight(task)
    if r["verdict"] == "BLOCK":
        raise ApiError(409, "RESOURCE_BLOCKED", "자원이 부족해 작업을 시작하지 않습니다: " + "; ".join(x["msg"] for x in r["reasons"]), preflight=r)
    return r


# ------------------------------------------------------------------ 정리 후보(이 시스템이 만든 것만)
TMP_RE = re.compile(r"^(dbxtest_\w+|dbx_uiax_\w+|dbx_ui_\w+|dbx_smoke_\w+|dbx_real_[a-z0-9_]{8})$")


def _safe_dir(p):
    t = Path(tempfile.gettempdir()).resolve()
    try:
        rp = Path(p).resolve()
        return rp.parent == t and not Path(p).is_symlink() and TMP_RE.match(rp.name) is not None
    except Exception:
        return False


def _docker(args, timeout=15):
    try:
        r = subprocess.run(["docker"] + args, capture_output=True, text=True, timeout=timeout)
        return r.stdout if r.returncode == 0 else None
    except Exception:
        return None


def cleanup_candidates():
    _need()
    out = []
    t = Path(tempfile.gettempdir())
    cur = DATA.resolve()
    for d in sorted(t.glob("*")):
        try:
            if d.is_dir() and TMP_RE.match(d.name) and _safe_dir(d) and d.resolve() != cur and time.time() - d.stat().st_mtime > 600:
                out.append({"id": "tmp:" + d.name, "kind": "temp_dir", "label": f"임시 시험 폴더 {d.name}", "path": str(d), "bytes": dir_size(d), "risk": "낮음", "why": "시험·점검 스크립트가 만든 임시 폴더(10분 이상 미사용)"})
        except OSError:
            continue
    for lg in sorted(DATA.glob("server_*.log")):
        try:
            sz = lg.stat().st_size
            if sz > 20 * 1024 * 1024:
                out.append({"id": "log:" + lg.name, "kind": "log_truncate", "label": f"서버 로그 비우기 {lg.name}", "path": str(lg), "bytes": sz, "risk": "낮음", "why": "20MB 초과 로그(비우면 이전 로그는 사라짐)"})
        except OSError:
            continue
    axd = DATA / "ax"
    if axd.exists():
        for pdir in axd.glob("axp-*"):
            f = pdir / "native.sqlite"
            if f.exists():
                out.append({"id": "axcache:" + pdir.name, "kind": "ax_native_cache", "label": f"AX 파생 저장소 {pdir.name}/native.sqlite", "path": str(f), "bytes": f.stat().st_size, "risk": "낮음",
                            "why": "파이프라인이 다시 만들 수 있는 파생 자산(원천 DB·승인 기록은 지우지 않음)"})
    names = _docker(["ps", "-a", "--filter", "name=wzax-", "--format", "{{.Names}}|{{.Status}}"])
    for ln in (names or "").splitlines():
        n = ln.split("|")[0]
        if n.startswith("wzax-"):
            out.append({"id": "docker:" + n, "kind": "docker_container", "label": f"시험용 DB 컨테이너 {n}", "path": n, "bytes": 0, "risk": "중간", "why": "AX 실제 DB 시험용(wzax-*). 삭제하면 시험 데이터는 다시 적재해야 함"})
    me = os.getpid()
    for p in psutil.process_iter(["pid", "name", "memory_info", "create_time"]):
        try:
            if p.pid == me or not str(p.info.get("name") or "").lower().startswith(("python", "pytest")):
                continue
            cmd = " ".join(p.cmdline()).lower()
            if p.pid != me and "pytest" in cmd and str(ROOT).lower() in (cmd + " " + (p.cwd() or "").lower()):
                out.append({"id": f"proc:{p.pid}:{int(p.info['create_time'])}", "kind": "process", "label": f"이 저장소의 시험(pytest) 프로세스 PID {p.pid}", "path": str(p.pid), "bytes": p.info["memory_info"].rss,
                            "risk": "중간", "why": "실행 중인 시험이 메모리를 점유(종료하면 시험은 중단됨)"})
        except Exception:
            continue
    return out


def plan_create(actor):
    cands = cleanup_candidates()
    pid = "pl-" + secrets.token_hex(5)
    PLANS[pid] = {"plan_id": pid, "by": actor["user_id"], "at": time.time(), "candidates": {c["id"]: c for c in cands}}
    for k in [k for k, v in PLANS.items() if time.time() - v["at"] > 600]:
        PLANS.pop(k, None)
    return {"plan_id": pid, "expires_in_s": 600, "confirm_phrase": CONFIRM, "reclaim_bytes": sum(c["bytes"] for c in cands), "candidates": cands,
            "never_touched": ["실행 중인 이 서버(backend.main:app)", "다른 앱의 프로세스·컨테이너", "원천 DB 데이터·승인 기록·증거 파일(dbx_real_run 등)", "사용자 홈·저장소 파일"],
            "note": "후보를 고르고 확인 문구를 입력해 승인해야 실행됩니다. 실행 직전에 각 후보를 다시 검증합니다."}


def plan_execute(actor, plan_id, ids, confirm):
    pl = PLANS.get(plan_id)
    if not pl or time.time() - pl["at"] > 600:
        raise ApiError(404, "PLAN_NOT_FOUND", "정리 계획이 없거나 만료되었습니다(10분). 다시 계획을 만드세요.")
    if pl["by"] != actor["user_id"]:
        raise ApiError(403, "PLAN_OWNER_ONLY", "계획을 만든 관리자만 승인할 수 있습니다.")
    if confirm != CONFIRM:
        raise ApiError(400, "CONFIRM_REQUIRED", f"확인 문구 '{CONFIRM}' 를 정확히 입력해야 합니다.")
    if not ids:
        raise ApiError(400, "NOTHING_SELECTED", "정리할 항목을 선택하세요.")
    results, freed = [], 0
    for i in ids:
        c = pl["candidates"].get(i)
        if not c:
            results.append({"id": i, "ok": False, "msg": "계획에 없는 항목(거부)"})
            continue
        try:
            results.append(dict(_do(c), id=i))
            freed += results[-1].get("freed", 0)
        except Exception as e:
            results.append({"id": i, "ok": False, "msg": f"{type(e).__name__}"})
    AUDIT.append({"at": _iso(), "actor": actor["user_id"], "plan": plan_id, "selected": list(ids), "ok": sum(1 for r in results if r["ok"]), "freed": freed})
    PLANS.pop(plan_id, None)
    try:
        AUDIT_FILE.write_text(json.dumps(AUDIT[-500:], ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass
    return {"results": results, "freed_bytes": freed, "ok": sum(1 for r in results if r["ok"]), "failed": sum(1 for r in results if not r["ok"])}


def _do(c):
    k = c["kind"]
    if k == "temp_dir":
        if not _safe_dir(c["path"]):
            return {"ok": False, "msg": "재검증 실패(허용된 임시 폴더가 아님)"}
        sz = dir_size(c["path"])
        shutil.rmtree(c["path"], ignore_errors=True)
        return {"ok": not Path(c["path"]).exists(), "freed": sz, "msg": "삭제함"}
    if k == "log_truncate":
        p = Path(c["path"])
        if p.parent.resolve() != DATA.resolve() or not re.fullmatch(r"server_[\w\.]+\.log", p.name):
            return {"ok": False, "msg": "재검증 실패"}
        sz = p.stat().st_size
        open(p, "w").close()
        return {"ok": True, "freed": sz, "msg": "비움"}
    if k == "ax_native_cache":
        p = Path(c["path"])
        if p.name != "native.sqlite" or (DATA / "ax").resolve() not in p.resolve().parents:
            return {"ok": False, "msg": "재검증 실패"}
        sz = p.stat().st_size
        p.unlink()
        return {"ok": True, "freed": sz, "msg": "삭제함(파이프라인 재실행 시 다시 생성)"}
    if k == "docker_container":
        n = c["path"]
        if not n.startswith("wzax-"):
            return {"ok": False, "msg": "재검증 실패"}
        r = _docker(["rm", "-f", n], 60)
        return {"ok": r is not None, "msg": "컨테이너 삭제" if r is not None else "docker 실행 실패"}
    if k == "process":
        _, pid, ct = c["id"].split(":")
        p = psutil.Process(int(pid))
        if int(p.create_time()) != int(ct) or "pytest" not in " ".join(p.cmdline()).lower() or p.pid == os.getpid():
            return {"ok": False, "msg": "재검증 실패(다른 프로세스로 바뀜)"}
        rss = p.memory_info().rss
        p.terminate()
        try:
            p.wait(5)
        except Exception:
            p.kill()
        return {"ok": True, "freed": rss, "msg": "종료함"}
    return {"ok": False, "msg": "알 수 없는 종류"}


def audit_list():
    return AUDIT[-100:]


def warm():
    """서버 시작 직후 백그라운드로 프로세스 표·디스크 종류를 미리 조회해 첫 화면을 빠르게 한다."""
    if psutil is None:
        return
    threading.Thread(target=_disk_kinds, daemon=True).start()
    _proc_refresh(12, False)
