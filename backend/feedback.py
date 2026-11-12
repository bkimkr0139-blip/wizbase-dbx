"""AXOS 피드백 폐루프 — 사용자 피드백(텍스트+이미지) 접수 → 검토·승인 → 개발큐 → 개발중 → 반영완료.
전이 산업 도메인 신청. 관리(검토·개발큐 전이·이미지 열람)는 admin(수퍼유저)만 한다.
제출자는 본인 피드백의 진행 상태만 조회한다(폐루프: 반영완료 시 제출자에게 알림 표시).
"""
from __future__ import annotations
import base64, binascii
from pathlib import Path

from . import v11
from .core import ApiError

KINDS = {"FEATURE": "기능 추가 요청", "UI_BUG": "화면 버그", "IMPROVE": "기능 개선", "DBX_MISMATCH": "DBX와 맞지 않는 오류", "CONTENT": "문항·자료 오류", "OTHER": "기타", "DOMAIN_REQUEST": "전이 도메인 신청", "CONNECT_REQUEST": "실제 환경 연결 신청"}
STATUS = {"RECEIVED": "접수", "APPROVED": "검토·승인", "QUEUED": "개발큐", "IN_DEV": "개발중", "DONE": "반영완료", "REJECTED": "반려", "ON_HOLD": "보류"}
FLOW = {"RECEIVED": ["APPROVED", "REJECTED", "ON_HOLD"], "APPROVED": ["QUEUED", "REJECTED", "ON_HOLD"], "QUEUED": ["IN_DEV", "ON_HOLD", "REJECTED"],
        "IN_DEV": ["DONE", "QUEUED"], "ON_HOLD": ["APPROVED", "QUEUED", "REJECTED"], "DONE": [], "REJECTED": []}
MAX_IMAGES, MAX_IMG_BYTES, MAX_TEXT, HOURLY = 5, 3 * 1024 * 1024, 4000, 20
VIEW_HINT = {"env": "static/app.js V.env · backend/core.py FEATURES", "sql": "static/app.js V.sql · backend/core.py(SQL 실행)", "xfer": "static/app.js V.xfer · backend/transfer.py",
             "rvw": "static/app.js V.rvw · backend/v11.py(검토)", "ko": "backend/ko_guide.py", "exam": "backend/items_bank.py · backend/v11.py(시험)"}


def _F():
    return v11.V.setdefault("feedback", {})


def _dir():
    d = v11.STORE.parent / "feedback"
    d.mkdir(parents=True, exist_ok=True)
    return d


def is_admin(actor):
    return actor.get("role") == "admin"


def need_admin(actor):
    if not is_admin(actor):
        raise ApiError(403, "FORBIDDEN", "admin(수퍼유저)만 피드백·개발큐를 관리할 수 있습니다.")


def _sniff(b: bytes):
    if b[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if b[:3] == b"\xff\xd8\xff":
        return "jpg"
    if b[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if b[:4] == b"RIFF" and b[8:12] == b"WEBP":
        return "webp"
    return None


def _save_images(fid, images):
    out = []
    for n, im in enumerate((images or [])[:MAX_IMAGES], 1):
        raw = str(im.get("data", ""))
        raw = raw.split(",", 1)[1] if raw.startswith("data:") else raw
        try:
            b = base64.b64decode(raw, validate=True)
        except (binascii.Error, ValueError):
            raise ApiError(400, "BAD_IMAGE", f"{n}번째 이미지를 읽을 수 없습니다.")
        if len(b) > MAX_IMG_BYTES:
            raise ApiError(413, "IMAGE_TOO_LARGE", f"{n}번째 이미지가 3MB를 넘습니다.")
        ext = _sniff(b)
        if not ext:
            raise ApiError(400, "BAD_IMAGE_TYPE", "PNG·JPEG·GIF·WEBP 이미지만 첨부할 수 있습니다.")
        name = f"{fid}-{n}.{ext}"
        (_dir() / name).write_bytes(b)
        out.append({"n": n, "file": name, "ext": ext, "bytes": len(b), "orig": str(im.get("name", ""))[:80]})
    return out


def _brief(f, full=False):
    d = {k: f[k] for k in ("id", "kind", "kind_label", "title", "view", "status", "status_label", "submitted_by_name", "submitted_by", "role", "created", "version", "priority", "released_version", "resolution", "images_n", "unseen_done")}
    d["source"] = f.get("source", "local")
    if f.get("edited_at"):
        d["edited_at"] = f["edited_at"]
    if f.get("install") and full:
        d["install"] = f["install"]
    if standalone():
        d["remote_state"] = "SENT" if f.get("remote") else "PENDING"
    if full:
        d.update({"text": f["text"], "context": f["context"], "history": f["history"], "images": [{"n": i["n"], "bytes": i["bytes"], "orig": i["orig"]} for i in f["images"]], "ticket_md": f.get("ticket_md", ""), "domain": f.get("domain")})
    return d


def _rate(actor):
    now = v11.now()
    n = sum(1 for f in _F().values() if f["submitted_by"] == actor["user_id"] and now - f["_t"] < 3600)
    if n >= HOURLY:
        raise ApiError(429, "TOO_MANY_FEEDBACK", "한 시간에 제출할 수 있는 피드백 수를 넘었습니다.")


def submit(actor, b):
    kind = b.get("kind", "OTHER")
    if kind not in KINDS:
        raise ApiError(400, "BAD_KIND", "/".join(KINDS))
    title = str(b.get("title", "")).strip()[:120]
    text = str(b.get("text", "")).strip()[:MAX_TEXT]
    if not title or len(text) < 5:
        raise ApiError(400, "EMPTY_FEEDBACK", "제목과 내용(5자 이상)을 입력하세요.")
    _rate(actor)
    fid = v11.nid("FB")
    ctx = {k: str(v)[:120] for k, v in (b.get("context") or {}).items() if k in ("view", "view_label", "version", "build", "client", "viewport")}
    f = {"id": fid, "kind": kind, "kind_label": KINDS[kind], "title": title, "text": text, "view": str(b.get("view", ""))[:30], "context": ctx, "status": "RECEIVED", "status_label": STATUS["RECEIVED"],
         "submitted_by": actor["user_id"], "submitted_by_name": actor["name"], "role": actor["role"], "created": v11._iso(), "_t": v11.now(), "version": ctx.get("version", ""),
         "priority": None, "released_version": None, "resolution": "", "history": [{"at": v11._iso(), "by": actor["user_id"], "to": "RECEIVED", "note": ""}], "unseen_done": False}
    f["images"] = _save_images(fid, b.get("images"))
    f["images_n"] = len(f["images"])
    if kind == "DOMAIN_REQUEST":
        d = b.get("domain") or {}
        dom = str(d.get("domain", "")).strip()[:80]
        if not dom:
            raise ApiError(400, "EMPTY_DOMAIN", "신청할 도메인(산업)을 입력하세요.")
        f["domain"] = {k: str(d.get(k, "")).strip()[:500] or "(미기재)" for k in ("purpose", "data", "issues", "when")}
        f["domain"]["domain"] = dom
    _F()[fid] = f
    v11.audit(actor, "FEEDBACK_SUBMIT", fid, detail={"kind": kind})
    v11.save()
    if standalone() and actor.get("role") != "standalone":
        import threading
        threading.Thread(target=forward, args=(fid,), daemon=True).start()
    return {"id": fid, "status": "RECEIVED", "images": f["images_n"]}


def mine(actor):
    sync(actor)
    L = [f for f in _F().values() if f["submitted_by"] == actor["user_id"]]
    L.sort(key=lambda f: f["_t"], reverse=True)
    return {"items": [_brief(f) for f in L], "unseen_done": sum(1 for f in L if f.get("unseen_done"))}


def mark_seen(actor):
    for f in _F().values():
        if f["submitted_by"] == actor["user_id"]:
            f["unseen_done"] = False
    v11.save()
    return {"ok": True}


def _get(fid):
    f = _F().get(fid)
    if not f:
        raise ApiError(404, "NO_FEEDBACK", fid)
    return f


def get(actor, fid):
    f = _get(fid)
    if not is_admin(actor) and f["submitted_by"] != actor["user_id"]:
        raise ApiError(404, "NO_FEEDBACK", fid)
    d = _brief(f, full=True)
    if not is_admin(actor):
        d.pop("ticket_md", None)
        d["history"] = [{"at": h["at"], "to": h["to"], "note": h["note"] if h["to"] in ("REJECTED", "DONE", "ON_HOLD") else ""} for h in f["history"]]
    return d


def image(actor, fid, n):
    f = _get(fid)
    if not is_admin(actor) and f["submitted_by"] != actor["user_id"]:
        raise ApiError(404, "NO_FEEDBACK", fid)
    im = next((i for i in f["images"] if i["n"] == n), None)
    if not im:
        raise ApiError(404, "NO_IMAGE", str(n))
    return _dir() / im["file"], im["ext"]


def admin_list(actor, status="", q="", page=0, size=25):
    """관리 목록: 상태 필터 + 검색(번호·제목·내용·제출자·유형·화면·우선순위) + 쪽 나누기. counts 는 검색과 무관한 전체 상태별 건수."""
    need_admin(actor)
    size = max(5, min(int(size or 25), 100))
    q = (q or "").strip().lower()
    L = [f for f in _F().values() if not status or f["status"] == status]
    if q:
        def hit(f):
            hay = " ".join([f["id"], f["title"], f["text"], f["submitted_by_name"], f["kind_label"], f.get("view", ""), f.get("priority") or "", STATUS.get(f["status"], "")]).lower()
            return q in hay
        L = [f for f in L if hit(f)]
    L.sort(key=lambda f: f["_t"], reverse=True)
    total = len(L)
    pages = max(1, -(-total // size))
    page = max(0, min(int(page or 0), pages - 1))
    cnt = {}
    for f in _F().values():
        cnt[f["status"]] = cnt.get(f["status"], 0) + 1
    return {"items": [_brief(f) for f in L[page * size:(page + 1) * size]], "counts": cnt, "flow": FLOW, "status_labels": STATUS, "total": total, "page": page, "size": size, "pages": pages,
            "ids": [f["id"] for f in L[:500]]}


def _ticket(f):
    ctx = f["context"]
    L = [f"# 개발 지시서 {f['id']} — {f['title']}", "", f"- 유형: {f['kind_label']} / 우선순위: {f.get('priority') or 'P2'}", f"- 대상 화면: `{f['view'] or '(미지정)'}` ({ctx.get('view_label', '')}) — 후보 파일: {VIEW_HINT.get(f['view'], 'static/app.js · backend/')}",
         f"- 제출: {f['submitted_by_name']} ({f['role']}) · {f['created']} · 버전 {ctx.get('version', '?')} · 빌드 {ctx.get('build', '?')} · 클라이언트 {ctx.get('client', '?')}", "", "## 내용", "", f["text"], ""]
    if f.get("domain"):
        d = f["domain"]
        L += ["## 도메인 신청 내용", "", f"- 도메인: {d['domain']}", f"- 목적: {d['purpose']}", f"- 데이터·테이블: {d['data']}", f"- 심어 둘 문제: {d['issues']}", f"- 희망 시기: {d['when']}", "",
              "구현 지침: `backend/transfer.py` SEEDS에 시드 추가(고정 난수), 정답표는 직원 전용, 합성 데이터만.", ""]
    if f["images"]:
        L += ["## 첨부 이미지", ""] + [f"- {i['file']} ({i['bytes']} bytes, 원본명 {i['orig'] or '-'}) → `data/feedback/{i['file']}`" for i in f["images"]] + [""]
    L += ["## 완료 기준", "", "- 재현 절차가 더 이상 재현되지 않거나 요청 기능이 화면에 나타난다.", "- 모의 결과와 실제 DBX 검증 결과의 구분 표기(증거 수준)를 유지한다. DBX와 다른 동작이면 DOC_CHECKED/WORKSPACE_CHECKED 상태를 함께 수정한다.",
          "- 회귀 테스트 추가, `backend/sysinfo.py` VERSION·CHANGELOG 갱신, 시스템 문서 갱신.", "- 완료 후 관리 화면에서 `반영완료`로 전이하고 반영 버전을 기록한다(제출자에게 알림)."]
    return "\n".join(L)


def transition(actor, fid, to, note="", priority=None, released_version=None):
    need_admin(actor)
    f = _get(fid)
    if to not in FLOW.get(f["status"], []):
        raise ApiError(409, "BAD_TRANSITION", f"{STATUS[f['status']]} → {STATUS.get(to, to)} 전이는 허용되지 않습니다. 가능: {', '.join(STATUS[x] for x in FLOW[f['status']]) or '없음'}")
    note = (note or "").strip()[:500]
    if to in ("REJECTED", "ON_HOLD") and len(note) < 3:
        raise ApiError(400, "REASON_REQUIRED", "반려·보류 사유를 입력하세요(제출자에게 표시됩니다).")
    if priority in ("P1", "P2", "P3"):
        f["priority"] = priority
    if to == "DONE":
        if not released_version:
            raise ApiError(400, "RELEASE_REQUIRED", "반영 버전(예: 1.4.0)을 입력하세요.")
        f["released_version"] = str(released_version)[:20]
        f["resolution"] = note
        f["unseen_done"] = True
    if to in ("REJECTED", "ON_HOLD"):
        f["resolution"] = note
    f["status"], f["status_label"] = to, STATUS[to]
    f["history"].append({"at": v11._iso(), "by": actor["user_id"], "to": to, "note": note})
    if to == "QUEUED":
        f["priority"] = f.get("priority") or "P2"
        f["ticket_md"] = _ticket(f)
    v11.audit(actor, "FEEDBACK_" + to, fid, detail={"note": note})
    v11.save()
    return _brief(f, full=True)


def delete(actor, ids):
    """선택한 피드백(첨부 이미지 포함)을 영구 삭제한다. 되돌릴 수 없으며 감사 기록만 남는다."""
    need_admin(actor)
    done, missing = [], []
    for fid in dict.fromkeys(list(ids or [])[:100]):
        f = _F().pop(fid, None)
        if not f:
            missing.append(fid)
            continue
        for im in f.get("images", []):
            try:
                (_dir() / im["file"]).unlink()
            except OSError:
                pass
        v11.audit(actor, "FEEDBACK_DELETE", fid, detail={"title": f["title"][:40], "status": f["status"], "by": f["submitted_by_name"]})
        done.append(fid)
    if done:
        v11.save()
    return {"deleted": done, "missing": missing}


def edit(actor, fid, b):
    """관리자 수정: 제목·내용·유형·우선순위. 수정 이력이 남고 개발큐/개발중이면 개발 지시서가 다시 만들어진다."""
    need_admin(actor)
    f = _get(fid)
    ch = []
    if "title" in b:
        t = str(b["title"]).strip()[:120]
        if not t:
            raise ApiError(400, "EMPTY_FEEDBACK", "제목을 입력하세요.")
        if t != f["title"]:
            ch.append("제목")
            f["title"] = t
    if "text" in b:
        t = str(b["text"]).strip()[:MAX_TEXT]
        if len(t) < 5:
            raise ApiError(400, "EMPTY_FEEDBACK", "내용은 5자 이상이어야 합니다.")
        if t != f["text"]:
            ch.append("내용")
            f["text"] = t
    if "kind" in b and b["kind"] != f["kind"]:
        k = b["kind"]
        if k not in KINDS or "DOMAIN_REQUEST" in (k, f["kind"]):
            raise ApiError(400, "BAD_KIND", "도메인 신청과 다른 유형 사이의 변경은 할 수 없습니다.")
        f["kind"], f["kind_label"] = k, KINDS[k]
        ch.append("유형")
    if "priority" in b and b["priority"] != f.get("priority"):
        if b["priority"] not in (None, "", "P1", "P2", "P3"):
            raise ApiError(400, "BAD_PRIORITY", "P1·P2·P3 중에서 고르세요.")
        f["priority"] = b["priority"] or None
        ch.append("우선순위")
    if not ch:
        return _brief(f, full=True)
    f["history"].append({"at": v11._iso(), "by": actor["user_id"], "to": f["status"], "note": "관리자 수정: " + ", ".join(ch)})
    f["edited_at"] = v11._iso()
    if f["status"] in ("QUEUED", "IN_DEV"):
        f["ticket_md"] = _ticket(f)
    v11.audit(actor, "FEEDBACK_EDIT", fid, detail={"changed": ch})
    v11.save()
    return _brief(f, full=True)


def bulk_transition(actor, ids, to, note="", priority=None, released_version=None):
    """선택한 여러 건을 같은 상태로 옮긴다. 흐름에 맞지 않는 건은 건너뛰고 이유를 돌려준다."""
    need_admin(actor)
    ok, failed = [], []
    for fid in dict.fromkeys(list(ids or [])[:100]):
        try:
            transition(actor, fid, to, note, priority, released_version)
            ok.append(fid)
        except ApiError as e:
            failed.append({"id": fid, "code": e.code, "message": e.message})
    return {"ok": ok, "failed": failed}


def queue_md(actor):
    need_admin(actor)
    L = [f"# 개발큐 ({v11._iso()[:10]})", "", "AXOS 폐루프: 접수 → 검토·승인 → **개발큐** → 개발중 → 반영완료. 아래는 개발 대기·진행 중인 지시서입니다.", ""]
    q = [f for f in _F().values() if f["status"] in ("QUEUED", "IN_DEV")]
    q.sort(key=lambda f: (f.get("priority") or "P2", f["_t"]))
    if not q:
        L.append("(대기 중인 항목 없음)")
    for f in q:
        L += [f"---\n\n상태: **{STATUS[f['status']]}**\n", f.get("ticket_md") or _ticket(f), ""]
    return "\n".join(L)


# ---------------------------------------------------------------- 단독형(PC 설치) ↔ 중앙 서버 연계
# 단독형 앱의 AXOS 피드백은 본인 PC에 접수한 뒤 운영자 서버(중앙 개발큐)로 전달된다. 오프라인이면 보류했다가 나중에 자동 재전송하고,
# 처리 상태(승인·개발큐·반영완료·반려 사유)는 접수 영수증(receipt)으로 중앙에서 읽어 와 '내 피드백'에 반영한다.
import hashlib, json as _json, os, secrets, time, urllib.request

CENTRAL_URL = os.environ.get("DBX_CENTRAL_URL", "https://dbx.wizbase.ai.kr")
TERMINAL = ("DONE", "REJECTED")
_INTAKE_HITS: dict = {}
_ONLINE = {"t": 0.0, "ok": True}


def standalone():
    return os.environ.get("DBX_STANDALONE") == "1"


def _hdrs():
    try:
        from . import telemetry
        return telemetry.headers()
    except Exception:
        return {}


def _http(method, path, body=None, timeout=8):
    """중앙 서버 호출(테스트에서 이 함수를 교체한다)."""
    req = urllib.request.Request(CENTRAL_URL.rstrip("/") + path, method=method, data=_json.dumps(body).encode("utf-8") if body is not None else None,
                                 headers={"Content-Type": "application/json", "User-Agent": "DBXDesktop-Standalone", **_hdrs()})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return _json.loads(r.read().decode("utf-8"))


def _online():
    if time.time() - _ONLINE["t"] < 60:
        return _ONLINE["ok"]
    try:
        _http("GET", "/api/app/manifest", timeout=4)
        ok = True
    except Exception:
        ok = False
    _ONLINE.update(t=time.time(), ok=ok)
    return ok


def intake(ip, b):
    """중앙 서버: 단독형 앱에서 온 피드백 접수(비로그인). IP·전체 시간당 한도로 남용을 막는다."""
    now = time.time()
    hits = [t for t in _INTAKE_HITS.get(ip, []) if now - t < 3600]
    allh = [t for t in _INTAKE_HITS.get("*", []) if now - t < 3600]
    if len(hits) >= 10 or len(allh) >= 60:
        raise ApiError(429, "TOO_MANY_FEEDBACK", "접수 한도를 넘었습니다. 잠시 후 다시 시도하세요.")
    name = str(b.get("name", "")).strip()[:40]
    if len(name) < 2:
        raise ApiError(400, "NAME_REQUIRED", "이름(실명)이 필요합니다.")
    actor = {"user_id": "ext_" + hashlib.sha256((ip + name).encode()).hexdigest()[:8], "name": name, "role": "standalone"}
    r = submit(actor, b)
    receipt = secrets.token_urlsafe(16)
    f = _F()[r["id"]]
    f["source"], f["receipt_hash"] = "standalone", hashlib.sha256(receipt.encode()).hexdigest()
    ins = b.get("install") or {}
    if isinstance(ins, dict) and ins.get("install"):
        f["install"] = {"id": str(ins.get("install"))[:12], "version": str(ins.get("app_version", ""))[:20], "platform": str(ins.get("platform", ""))[:20], "os": str(ins.get("os", ""))[:60]}
    _INTAKE_HITS[ip] = hits + [now]
    _INTAKE_HITS["*"] = allh + [now]
    v11.save()
    return {"id": r["id"], "receipt": receipt}


def intake_status(fid, receipt):
    f = _F().get(fid)
    if not f or not f.get("receipt_hash") or not secrets.compare_digest(f["receipt_hash"], hashlib.sha256(str(receipt).encode()).hexdigest()):
        raise ApiError(404, "NO_FEEDBACK", fid)
    show = f["status"] in ("DONE", "REJECTED", "ON_HOLD")
    return {"status": f["status"], "released_version": f.get("released_version"), "resolution": f.get("resolution", "") if show else "", "priority": f.get("priority")}


def _payload(f):
    imgs = []
    for im in f["images"]:
        p = _dir() / im["file"]
        if p.exists():
            imgs.append({"name": im["orig"], "data": base64.b64encode(p.read_bytes()).decode()})
    from . import telemetry
    d = {"install": telemetry.meta() if telemetry.enabled() else {}, "name": f["submitted_by_name"], "kind": f["kind"], "title": f["title"], "text": f["text"], "view": f["view"], "context": f["context"], "images": imgs}
    if f.get("domain"):
        d["domain"] = f["domain"]
    return d


import threading as _th
_FWD = _th.Lock()


def forward(fid):
    with _FWD:
        _forward(fid)


def _forward(fid):
    f = _F().get(fid)
    if not f or f.get("remote") or not standalone():
        return
    try:
        r = _http("POST", "/api/feedback/intake", _payload(f), timeout=30)
        f["remote"] = {"id": r["id"], "receipt": r["receipt"], "at": v11._iso()}
    except Exception as e:
        f["remote_error"] = str(e)[:120]
    v11.save()


def sync(actor):
    """내 피드백 조회 시: 미전송분 재전송 + 중앙 처리 상태 반영(오프라인이면 건너뜀)."""
    if not standalone() or not _online():
        return
    for f in [x for x in _F().values() if x["submitted_by"] == actor["user_id"]][:30]:
        if not f.get("remote"):
            forward(f["id"])
        elif f["status"] not in TERMINAL:
            try:
                s = _http("GET", f"/api/feedback/intake/{f['remote']['id']}?receipt={f['remote']['receipt']}", timeout=5)
            except Exception:
                continue
            if s["status"] != f["status"]:
                f["status"], f["status_label"] = s["status"], STATUS.get(s["status"], s["status"])
                f["history"].append({"at": v11._iso(), "by": "central", "to": s["status"], "note": s.get("resolution", "")})
                if s["status"] == "DONE":
                    f["unseen_done"] = True
            f["priority"], f["released_version"] = s.get("priority"), s.get("released_version")
            if s.get("resolution"):
                f["resolution"] = s["resolution"]
    v11.save()
