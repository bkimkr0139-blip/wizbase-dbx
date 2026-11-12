"""웹 접속·사용 기록 — 로그인·화면 이동·명령 실행·오류·세션·피드백·다운로드를 JSONL 로 남기고 admin 용 집계를 만든다.

- 기록 항목: 시각, 사용자 표시명·역할·로그인별 ID, 이벤트 종류, 화면/명령 종류/결과, 접속 단말 구분, 마스킹한 IP.
- **기록하지 않는 것**: 접근 코드, 토큰, SQL·입력 본문, 피드백 내용, 파일 내용.
- 보관: 180일(오래된 기록은 자동 삭제). 열람은 admin 만.
"""
from __future__ import annotations
import json, re, threading, time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from . import v11

KST = timezone(timedelta(hours=9))
LOCK = threading.Lock()
RETENTION_DAYS = 180
_LAST_PURGE = [0.0]
KINDS = {"login_ok": "로그인 성공", "login_fail": "로그인 실패", "view": "화면 열기", "cmd": "명령 실행", "session_new": "세션 생성", "session_del": "세션 삭제", "chat": "AI 지원 질문",
         "feedback": "피드백 제출", "download": "앱 다운로드", "api_error": "API 오류", "real_conn": "실제 연결 설정", "real_sql": "실제 연결 SQL"}


def _path():
    return v11.STORE.parent / "usage.jsonl"


def mask_ip(ip: str) -> str:
    ip = (ip or "").strip()
    if re.fullmatch(r"\d+\.\d+\.\d+\.\d+", ip):
        a = ip.split(".")
        return f"{a[0]}.{a[1]}.{a[2]}.x"
    if ":" in ip:
        return ":".join(ip.split(":")[:3]) + "::x"
    return ip[:20]


def ip_of(request) -> str:
    try:
        h = request.headers
        raw = (h.get("x-forwarded-for") or h.get("x-real-ip") or (request.client.host if request.client else "")).split(",")[0]
        return mask_ip(raw)
    except Exception:
        return ""


def client_of(request) -> str:
    try:
        ua = request.headers.get("user-agent", "")
    except Exception:
        return "unknown"
    if "DBXDesktop" in ua:
        return "pc_app"
    if re.search(r"Mobi|Android|iPhone", ua):
        return "mobile"
    if re.search(r"bot|crawl|spider|curl|python-requests|httpx", ua, re.I):
        return "bot"
    return "web"


def log(etype: str, actor: dict | None = None, request=None, **detail):
    """기록 실패가 서비스에 영향을 주지 않도록 모든 예외를 삼킨다."""
    try:
        ev = {"t": round(time.time(), 3), "e": etype, "u": (actor or {}).get("user_id", ""), "n": (actor or {}).get("name", ""), "r": (actor or {}).get("role", ""),
              "d": {k: (str(v)[:80] if not isinstance(v, (int, float, bool)) else v) for k, v in detail.items() if v is not None}, "ip": ip_of(request) if request is not None else "", "c": client_of(request) if request is not None else ""}
        line = json.dumps(ev, ensure_ascii=False)
        with LOCK:
            p = _path()
            p.parent.mkdir(parents=True, exist_ok=True)
            with open(p, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        if time.time() - _LAST_PURGE[0] > 86400:
            threading.Thread(target=purge, daemon=True).start()
    except Exception:
        pass


def _read(since: float = 0.0):
    p = _path()
    if not p.exists():
        return []
    out = []
    with LOCK:
        with open(p, encoding="utf-8") as f:
            for line in f:
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                if e.get("t", 0) >= since:
                    out.append(e)
    return out


def purge(days: int = RETENTION_DAYS):
    _LAST_PURGE[0] = time.time()
    cutoff = time.time() - days * 86400
    p = _path()
    if not p.exists():
        return 0
    with LOCK:
        keep, dropped = [], 0
        with open(p, encoding="utf-8") as f:
            for line in f:
                try:
                    t = json.loads(line).get("t", 0)
                except ValueError:
                    dropped += 1
                    continue
                if t >= cutoff:
                    keep.append(line)
                else:
                    dropped += 1
        if dropped:
            tmp = p.with_suffix(".tmp")
            tmp.write_text("".join(keep), encoding="utf-8")
            tmp.replace(p)
    return dropped


def _day(t):
    return datetime.fromtimestamp(t, KST).strftime("%Y-%m-%d")


def _kpi(evs):
    users = {e["n"].strip().lower() for e in evs if e["e"] == "login_ok" and e["n"]}
    cmds = [e for e in evs if e["e"] == "cmd"]
    return {"logins": sum(1 for e in evs if e["e"] == "login_ok"), "users": len(users), "login_fail": sum(1 for e in evs if e["e"] == "login_fail"), "sessions": sum(1 for e in evs if e["e"] == "session_new"),
            "cmds": len(cmds), "cmd_fail": sum(1 for e in cmds if e["d"].get("status") != "ok"), "views": sum(1 for e in evs if e["e"] == "view"), "chats": sum(1 for e in evs if e["e"] == "chat"),
            "feedback": sum(1 for e in evs if e["e"] == "feedback"), "downloads": sum(1 for e in evs if e["e"] == "download"), "errors": sum(1 for e in evs if e["e"] == "api_error")}


def fingerprint() -> str:
    """기록 파일의 크기·수정 시각만 본다(파일을 읽지 않으므로 매우 가볍다). 값이 같으면 새 기록이 없다."""
    try:
        st = _path().stat()
        return f"{st.st_size}-{int(st.st_mtime)}"
    except OSError:
        return "0-0"


_SUM_CACHE: dict = {}


def summary(days: int = 30):
    days = max(1, min(int(days or 30), RETENTION_DAYS))
    key = (days, fingerprint())
    hit = _SUM_CACHE.get(days)
    if hit and hit[0] == key and time.time() - hit[2] < 300:     # 새 기록이 없고 5분 안이면 이전 집계를 그대로 쓴다
        return hit[1]
    out = _summary(days)
    _SUM_CACHE[days] = (key, out, time.time())
    return out


def _summary(days: int):
    now = time.time()
    since = now - days * 86400
    evs = _read(now - 2 * days * 86400)
    cur = [e for e in evs if e["t"] >= since]
    prev = [e for e in evs if e["t"] < since]
    # 일별(KST)
    today = datetime.fromtimestamp(now, KST).date()
    labels = [(today - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(days - 1, -1, -1)]
    daily = {d: {"date": d, "logins": 0, "users": set(), "cmds": 0, "cmd_fail": 0, "views": 0, "errors": 0} for d in labels}
    hourly = [0] * 24
    heat = [[0] * 24 for _ in range(7)]
    roles, clients = Counter(), Counter()
    views, cmds, chat, dl = Counter(), defaultdict(lambda: [0, 0]), Counter(), Counter()
    users = {}
    err_codes = Counter()
    for e in cur:
        d = _day(e["t"])
        dt = datetime.fromtimestamp(e["t"], KST)
        if e["e"] != "download":
            hourly[dt.hour] += 1
            heat[dt.weekday()][dt.hour] += 1
        row = daily.get(d)
        k = e["e"]
        if k == "login_ok":
            roles[e["r"] or "?"] += 1
            clients[e["c"] or "unknown"] += 1
            if row:
                row["logins"] += 1
                if e["n"]:
                    row["users"].add(e["n"].strip().lower())
        elif k == "view":
            views[e["d"].get("view", "?")] += 1
            if row:
                row["views"] += 1
        elif k == "cmd":
            ok = e["d"].get("status") == "ok"
            c = cmds[e["d"].get("type", "?")]
            c[0 if ok else 1] += 1
            if row:
                row["cmds"] += 1
                row["cmd_fail"] += 0 if ok else 1
        elif k == "chat":
            chat[e["d"].get("intent", "?")] += 1
        elif k == "download":
            dl[e["d"].get("what", "?")] += 1
        elif k == "api_error":
            err_codes[e["d"].get("code", "?")] += 1
            if row:
                row["errors"] += 1
        if e["u"] or e["n"]:
            key = (e["n"] or e["u"]).strip().lower()
            u = users.setdefault(key, {"name": e["n"] or e["u"], "role": e["r"], "events": 0, "logins": 0, "cmds": 0, "last": 0, "client": e["c"]})
            u["events"] += 1
            u["logins"] += 1 if k == "login_ok" else 0
            u["cmds"] += 1 if k == "cmd" else 0
            if e["t"] >= u["last"]:
                u["last"], u["role"], u["client"] = e["t"], e["r"] or u["role"], e["c"] or u["client"]
    series = [{**r, "users": len(r["users"])} for r in daily.values()]
    top_users = sorted(users.values(), key=lambda u: -u["events"])[:15]
    for u in top_users:
        u["last"] = datetime.fromtimestamp(u["last"], KST).strftime("%m-%d %H:%M")
    fails = [e for e in cur if e["e"] == "login_fail"]
    return {"days": days, "generated": datetime.fromtimestamp(now, KST).strftime("%Y-%m-%d %H:%M"), "kpi": _kpi(cur), "prev": _kpi(prev), "daily": series, "hourly": hourly, "heat": heat,
            "roles": dict(roles), "clients": dict(clients), "views": views.most_common(12), "cmds": sorted(([k, v[0], v[1]] for k, v in cmds.items()), key=lambda x: -(x[1] + x[2]))[:12],
            "chat": chat.most_common(10), "downloads": dict(dl), "errors": err_codes.most_common(8), "top_users": top_users,
            "login_fail_ips": Counter(e["ip"] for e in fails if e["ip"]).most_common(5), "total_events": len(cur), "kinds": KINDS, "retention_days": RETENTION_DAYS}


def events(limit: int = 100, offset: int = 0, kind: str = "", q: str = ""):
    evs = _read(time.time() - RETENTION_DAYS * 86400)
    evs.reverse()
    q = (q or "").strip().lower()
    if kind:
        evs = [e for e in evs if e["e"] == kind]
    if q:
        evs = [e for e in evs if q in (e["n"] or "").lower() or q in json.dumps(e["d"], ensure_ascii=False).lower() or q in (e["ip"] or "")]
    total = len(evs)
    out = [{"time": datetime.fromtimestamp(e["t"], KST).strftime("%Y-%m-%d %H:%M:%S"), "kind": e["e"], "kind_label": KINDS.get(e["e"], e["e"]), "name": e["n"], "role": e["r"], "uid": e["u"], "detail": e["d"], "ip": e["ip"], "client": e["c"]}
           for e in evs[offset:offset + max(1, min(int(limit), 500))]]
    return {"total": total, "items": out}
