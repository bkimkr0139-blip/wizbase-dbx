"""v1.1 professional-track modules (spec 27-40): exam profiles, objectives, item bank, exam center,
readiness / grade gates, labs evidence, credentials, learning plan, tutor. All gates are server-side."""
from __future__ import annotations
import copy, json, os, re, threading, time, uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import content as C
from . import labs as L
from .core import ApiError, sha

ROOT = Path(__file__).resolve().parent.parent
STORE = Path(os.environ.get("DBX_DATA_DIR", ROOT / "data")) / "v11.json"
LOCK = threading.RLock()
V: dict = {}
DISCLAIMER = "WIZBASE(Databricks 파트너)의 PoC 준비·인증 시험 준비 지원용 내부 평가이며 Databricks 공식 시험·자격·교육 이수를 대체하지 않습니다. 공식 합격선·합격 확률이 아닙니다."
STAFF = ("reviewer", "instructor", "admin")  # admin(수퍼유저)은 검토·강사 기능을 모두 수행


def now():  # patched in tests
    return time.time()


def _iso(t=None):
    return datetime.fromtimestamp(t or now(), tz=timezone.utc).isoformat()


def save():
    with LOCK:
        STORE.parent.mkdir(exist_ok=True)
        tmp = STORE.with_suffix(".tmp")
        tmp.write_text(json.dumps(V, ensure_ascii=False, default=str), encoding="utf-8")
        os.replace(tmp, STORE)


def audit(actor, kind, ref, outcome="ok", detail=None):
    V["audit"].append({"at": _iso(), "actor": actor["user_id"] if isinstance(actor, dict) else actor, "kind": kind, "ref": ref, "outcome": outcome, "detail": detail or {}})


def init(reset=False):
    global V
    if STORE.exists() and not reset:
        V = json.loads(STORE.read_text(encoding="utf-8"))
        if not any(o.get("granularity") == "OFFICIAL_BULLET" for o in V.get("objectives", [])) or any(i["item_id"] not in V["items"] for i in C.ITEMS):
            _sync_items(); _build_objectives(); refresh_objectives(); save()
        return
    V = {"items": {}, "objectives": [], "conflicts": copy.deepcopy(C.CONFLICTS), "attempts": {}, "lab_evidence": {}, "readiness": [], "grades": [], "credentials": [],
         "plans": {}, "practical": {}, "retests": {}, "seen_families": {}, "audit": [], "issues": [], "recalls": [], "source_revisions": [], "responses_log": [], "seq": 0}
    _sync_items()
    _build_objectives()
    refresh_objectives()
    save()


def _sync_items():
    for it in C.ITEMS:
        cur = V["items"].get(it["item_id"])
        if cur and cur["status"] != "DRAFT":
            continue  # 검수가 진행된 문항은 덮어쓰지 않음
        keep = {k: cur[k] for k in ("exposure_count", "trial") if cur} if cur else {}
        V["items"][it["item_id"]] = {**copy.deepcopy(it), "version": 1, "status": "DRAFT", "author": "AI-assisted draft (Claude) — 인간 검토 전", "ai_drafted": True,
                                     "technical_reviewer": None, "assessment_reviewer": None, "exposure_count": keep.get("exposure_count", 0), "trial": keep.get("trial", {"n": 0, "correct": 0, "options": {}})}


def _build_objectives():
    """공식 가이드 PDF에서 추출한 bullet 단위 objective(요약+원문 해시). DE-P 웹 프로필은 도메인 자리표시만 유지."""
    manual = [o for o in V.get("objectives", []) if o.get("granularity") == "BULLET"]
    off = json.loads((ROOT / "backend" / "official_objectives.json").read_text(encoding="utf-8"))
    objs = []
    for ex, d in off["exams"].items():
        p = C.EXAM_PROFILES[ex]
        for r in d["objectives"]:
            objs.append({"exam_id": ex, "objective_id_internal": r["oid"], "granularity": "OFFICIAL_BULLET", "objective_summary": r["summary"], "section_name": r["section_name"],
                         "domain_key": r["domain_key"], "domain_weight": r["weight"], "guide_revision": p["guide_revision"], "effective_date": p["effective_date"],
                         "source_url": d["source_url"], "source_hash": d["guide_sha256"], "source_text_sha256": r["source_text_sha256"], "source_page": None, "locale": "en",
                         "prerequisite_ids": [], "theory_lesson_ids": [], "question_ids": [], "lab_ids": [f"LAB-{x}" for x in r["packs"]], "evidence_mode": "DBX_REQUIRED",
                         "assessment_ids": [], "reviewer": None, "verified_at": None, "coverage_status": "MISSING", "conflict_status": "OPEN", "note": "internal id; 공식 코드 아님. 요약은 WIZBASE 작성, 원문은 해시로만 보관"})
    p = C.EXAM_PROFILES["DE-P-WEB"]
    for dm in p["domains"]:
        objs.append({"exam_id": "DE-P-WEB", "objective_id_internal": f"OBJ-DE-P-WEB-{dm['key']}", "granularity": "DOMAIN_PLACEHOLDER", "objective_summary": f"{dm['name']} (웹 프로필 도메인 — bullet 미적재, 학습 기준 아님)",
                     "domain_key": dm["key"], "domain_weight": dm["weight_pct"], "guide_revision": p["guide_revision"], "effective_date": None, "source_url": C.SOURCES["S06"][1], "source_hash": None,
                     "source_page": None, "locale": "en", "prerequisite_ids": [], "theory_lesson_ids": [], "question_ids": [], "lab_ids": [], "evidence_mode": "DBX_REQUIRED", "assessment_ids": [],
                     "reviewer": None, "coverage_status": "MISSING", "conflict_status": "OPEN", "note": "혼합 금지 보존용"})
    V["objectives"] = objs + manual


def nid(p):
    V["seq"] += 1
    return f"{p}-{V['seq']:05d}"


def need_staff(actor, roles=STAFF):
    if actor["role"] not in roles and actor["role"] != "admin":
        raise ApiError(403, "FORBIDDEN", f"{'/'.join(roles)} 권한이 필요합니다.")


# ------------------------------------------------------------ profiles / objectives / coverage
def profiles():
    out = []
    for pid, p in C.EXAM_PROFILES.items():
        out.append({**{k: v for k, v in p.items() if k != "domains"}, "domain_count": len(p["domains"]), "domains": p["domains"],
                    "sum_weight": sum(d["weight_pct"] for d in p["domains"]), "sum_internal_items": sum(d["internal_items"] for d in p["domains"]),
                    "open_conflicts": [c["conflict_id"] for c in V["conflicts"] if c["exam_id"] == ("DE-P" if pid == "DE-P-WEB" else pid) and c.get("status", "OPEN") == "OPEN"],
                    "sources": [{"id": s, "title": C.SOURCES[s][0], "url": C.SOURCES[s][1]} for s in p["sources"]], "public_facts": C.PUBLIC_FACTS.get(pid if pid != "DE-P-WEB" else "DE-P"), "disclaimer": DISCLAIMER})
    return out


def refresh_objectives():
    for o in V["objectives"]:
        o["question_ids"] = [i["item_id"] for i in V["items"].values() if o["objective_id_internal"] in i.get("objective_ids", []) and i["status"] != "RETIRED"]
        active = [i for i in o["question_ids"] if V["items"][i]["status"] == "ACTIVE"]
        has_lab = False
        st = "MISSING"
        if o["theory_lesson_ids"]:
            st = "THEORY_ONLY"
        if len(active) >= 3:
            st = "QUESTION_READY"
            if o["lab_ids"] and all(_lab_ok(l) for l in o["lab_ids"]):
                st = "LAB_READY"
        if o.get("reviewer") and st == "LAB_READY":
            st = "VALIDATED"
        o["coverage_status"] = st


def _lab_ok(lab_id):
    return any(e["lab_id"] == lab_id and e["status"] == "APPROVED" for e in V["lab_evidence"].values())


def coverage(exam_id):
    refresh_objectives()
    if exam_id not in C.EXAM_PROFILES:
        raise ApiError(404, "UNKNOWN_EXAM", exam_id)
    objs = [o for o in V["objectives"] if o["exam_id"] == exam_id]
    counts = {}
    for o in objs:
        counts[o["coverage_status"]] = counts.get(o["coverage_status"], 0) + 1
    base = exam_id if exam_id != "DE-P-WEB" else "DE-P"
    open_c = [c for c in V["conflicts"] if c["exam_id"] == base and c.get("status", "OPEN") == "OPEN"]
    blockers = []
    if any(o["granularity"] == "DOMAIN_PLACEHOLDER" for o in objs):
        blockers.append("BULLET_OBJECTIVES_NOT_INGESTED: 이 프로필은 bullet 단위 목표가 적재되지 않음(자리표시)")
    unver = [o for o in objs if o["granularity"] != "DOMAIN_PLACEHOLDER" and not o.get("reviewer")]
    if unver:
        blockers.append(f"원문 대조 검토 미완료 {len(unver)}/{len(objs)}건 (검토자가 PDF와 대조해야 함)")
    if counts.get("MISSING"):
        blockers.append(f"MISSING objective {counts['MISSING']}건")
    if open_c:
        blockers.append(f"미해결 자료 상충 {len(open_c)}건")
    if exam_id == "DE-P-WEB":
        blockers.append("웹 프로필은 별도 보존용 — 학습 기준은 DE-P(10월 PDF)")
    return {"exam_id": exam_id, "objectives": objs, "counts": counts, "total": len(objs), "open_conflicts": open_c, "release_gate_ok": not blockers, "blockers": blockers,
            "ingested": sum(1 for o in objs if o["granularity"] == "OFFICIAL_BULLET"), "verified": sum(1 for o in objs if o.get("reviewer")),
            "items_per_objective_min": min([len(o["question_ids"]) for o in objs] or [0]), "objectives_with_no_item": sum(1 for o in objs if not o["question_ids"]),
            "note": "내부 objective ID는 공식 코드가 아닙니다. bullet은 공식 PDF에서 추출(원문 해시 보관), 요약은 WIZBASE 작성이며 검토자 원문 대조 전에는 VALIDATED가 될 수 없습니다."}


def add_objective(actor, exam_id, summary, domain_key, lab_ids=None):
    need_staff(actor)
    if exam_id not in C.EXAM_PROFILES:
        raise ApiError(404, "UNKNOWN_EXAM", exam_id)
    p = C.EXAM_PROFILES[exam_id]
    o = {"exam_id": exam_id, "objective_id_internal": nid(f"OBJ-{exam_id}"), "granularity": "BULLET", "objective_summary": summary, "domain_key": domain_key,
         "domain_weight": next((d["weight_pct"] for d in p["domains"] if d["key"] == domain_key), None), "guide_revision": p["guide_revision"], "effective_date": p["effective_date"],
         "source_url": C.SOURCES[p["sources"][-1]][1], "source_hash": None, "source_page": None, "locale": "en", "prerequisite_ids": [], "theory_lesson_ids": [], "question_ids": [],
         "lab_ids": lab_ids or [], "evidence_mode": "DBX_REQUIRED", "assessment_ids": [], "reviewer": None, "coverage_status": "MISSING", "conflict_status": "NONE", "note": "internal id; 공식 코드 아님"}
    V["objectives"].append(o)
    audit(actor, "OBJECTIVE_ADDED", o["objective_id_internal"])
    save()
    return o


def verify_objective(actor, oid, source_checked):
    need_staff(actor)
    o = next((x for x in V["objectives"] if x["objective_id_internal"] == oid), None)
    if not o:
        raise ApiError(404, "NO_OBJECTIVE", oid)
    if not source_checked:
        raise ApiError(400, "SOURCE_NOT_CHECKED", "공식 PDF 원문과 대조했음을 확인해야 합니다.")
    o["reviewer"], o["verified_at"] = actor["user_id"], _iso()
    audit(actor, "OBJECTIVE_VERIFIED", oid)
    refresh_objectives(); save()
    return o


def conflicts(exam_id=None):
    return [c for c in V["conflicts"] if not exam_id or c["exam_id"] == exam_id]


def resolve_conflict(actor, cid, resolution, refs):
    need_staff(actor)
    c = next((x for x in V["conflicts"] if x["conflict_id"] == cid), None)
    if not c:
        raise ApiError(404, "NO_CONFLICT", cid)
    if not refs or not resolution:
        raise ApiError(400, "EVIDENCE_REQUIRED", "공식 근거(refs)와 판정 내용이 필요합니다.")
    c.update(status="RESOLVED", resolution=resolution, evidence_refs=refs, resolved_by=actor["user_id"], resolved_at=_iso())
    audit(actor, "CONFLICT_RESOLVED", cid)
    save()
    return c


def ack_revision(actor, exam_id, idx):
    need_staff(actor)
    revs = [r for r in V["source_revisions"] if r["exam_id"] == exam_id]
    if idx >= len(revs):
        raise ApiError(404, "NO_REVISION", str(idx))
    revs[idx]["impact_reviewed"] = True; revs[idx]["reviewed_by"] = actor["user_id"]
    save()
    return revs[idx]


def new_revision(actor, exam_id, guide_revision, objectives):
    """AT-36: guide changed -> objective diff + impact analysis; old readiness decisions flagged."""
    need_staff(actor)
    old = {o["objective_summary"] for o in V["objectives"] if o["exam_id"] == exam_id}
    new = {o["summary"] for o in objectives}
    added, removed = sorted(new - old), sorted(old - new)
    flagged = 0
    for r in V["readiness"]:
        if r["exam_id"] == exam_id and r.get("status_flag") != "REREVIEW_REQUIRED":
            r["status_flag"] = "REREVIEW_REQUIRED"; flagged += 1
    rec = {"exam_id": exam_id, "guide_revision": guide_revision, "added": added, "removed": removed, "flagged_readiness": flagged, "impact_reviewed": False, "at": _iso(), "by": actor["user_id"]}
    V["source_revisions"].append(rec)
    for o in objectives:
        add_objective(actor, exam_id, o["summary"], o.get("domain_key", ""))
    audit(actor, "GUIDE_REVISION", exam_id, detail={"added": len(added), "removed": len(removed)})
    save()
    return rec


# ------------------------------------------------------------ items
def item_public(it, reveal=False):
    d = {k: it[k] for k in ("item_id", "exam", "domain", "type", "stem", "cog", "status", "family")}
    d["choices"] = [{"id": c["id"], "text": c["text"], **({"why": c["why"]} if reveal else {})} for c in it["choices"]]
    d["select_count"] = it.get("select_count", 1)
    d["scoring_rule"] = it.get("scoring", "exact") if it["type"] == "multi" else "single"
    if reveal:
        d["correct"] = it["correct"]; d["refs"] = it.get("refs", [])
    return d


def list_items(actor, exam=None):
    staff = actor["role"] in STAFF
    out = []
    for it in V["items"].values():
        if exam and it["exam"] != exam:
            continue
        if staff:
            out.append({**{k: v for k, v in it.items() if k != "choices"}, "choices": it["choices"]})
        else:
            if it["status"] == "ACTIVE":
                continue  # sealed bank is never exposed to learners
            out.append(item_public(it))
    return out


def item_review(actor, item_id, stage):
    need_staff(actor)
    it = V["items"].get(item_id)
    if not it:
        raise ApiError(404, "NO_ITEM", item_id)
    uid = actor["user_id"]
    if stage == "tech" and it["status"] == "DRAFT":
        it["status"], it["technical_reviewer"] = "TECH_REVIEWED", uid
    elif stage == "assessment" and it["status"] == "TECH_REVIEWED":
        if uid == it["technical_reviewer"]:
            raise ApiError(409, "REVIEWER_NOT_SEPARATED", "기술 검토자와 출제 검토자는 분리되어야 합니다.")
        it["status"], it["assessment_reviewer"] = "ASSESSMENT_REVIEWED", uid
    elif stage == "pilot" and it["status"] == "ASSESSMENT_REVIEWED":
        it["status"] = "PILOTED"
    elif stage == "activate" and it["status"] == "PILOTED":
        missing = [c["id"] for c in it["choices"] if not c.get("why")]
        if missing or len(it["correct"]) < 1:
            raise ApiError(409, "RATIONALE_INCOMPLETE", "모든 선택지에 해설이 필요합니다.")
        it["status"] = "ACTIVE"
    else:
        raise ApiError(409, "BAD_TRANSITION", f"{it['status']} → {stage} 불가")
    audit(actor, "ITEM_REVIEW", item_id, detail={"stage": stage, "now": it["status"]})
    refresh_objectives(); save()
    return {"item_id": item_id, "status": it["status"]}


def recall_item(actor, item_id, reason):
    """AT-35: retire defective item; recompute affected attempts and flag dependents."""
    need_staff(actor)
    it = V["items"].get(item_id)
    if not it:
        raise ApiError(404, "NO_ITEM", item_id)
    it["status"] = "RETIRED"
    affected = []
    for a in V["attempts"].values():
        if item_id in a["item_ids"] and a["status"] != "IN_PROGRESS":
            old = a["result"]["pct"] if a.get("result") else None
            a["result"] = _score_attempt(a, exclude={r["item_id"] for r in V["recalls"]} | {item_id})
            a["recomputed"] = True
            affected.append({"attempt_id": a["attempt_id"], "learner": a["learner"], "old_pct": old, "new_pct": a["result"]["pct"]})
    flagged = 0
    for r in V["readiness"]:
        if any(x["learner"] == r["learner"] for x in affected):
            r["status_flag"] = "REREVIEW_REQUIRED"; flagged += 1
    rec = {"item_id": item_id, "reason": reason, "by": actor["user_id"], "at": _iso(), "affected": affected, "readiness_flagged": flagged, "notified": [x["learner"] for x in affected]}
    V["recalls"].append(rec)
    audit(actor, "ITEM_RECALL", item_id, detail={"affected": len(affected)})
    refresh_objectives(); save()
    return rec


def item_quality():
    out = []
    for it in V["items"].values():
        t = it["trial"]
        flags = []
        if any(not c.get("why") for c in it["choices"]):
            flags.append("RATIONALE_MISSING")
        if it["type"] == "multi" and not it.get("select_count"):
            flags.append("SELECT_COUNT_MISSING")
        if t["n"] < 30:
            flags.append("SAMPLE_TOO_SMALL: 난이도 보정/통계 동등성 주장 불가")
        if it["status"] == "DRAFT":
            flags.append("AI_DRAFT_NOT_REVIEWED")
        out.append({"item_id": it["item_id"], "exam": it["exam"], "domain": it["domain"], "status": it["status"], "exposure": it["exposure_count"], "n": t["n"],
                    "p_correct": round(t["correct"] / t["n"], 2) if t["n"] else None, "option_dist": t["options"], "family": it["family"], "flags": flags})
    fam = {}
    for it in V["items"].values():
        fam.setdefault(it["family"], []).append(it["item_id"])
    return {"items": out, "families": fam, "note": "동일 family 변형은 독립 문항 수로 계산하지 않습니다.",
            "bank_size_by_status": _count([i["status"] for i in V["items"].values()])}


def _count(xs):
    d = {}
    for x in xs:
        d[x] = d.get(x, 0) + 1
    return d


# ------------------------------------------------------------ exam center
def _seen(learner):
    return set(V["seen_families"].get(learner, []))


def build_form(learner, exam_id, kind, max_items=None):
    p = C.EXAM_PROFILES.get(exam_id)
    if not p or not p["domains"]:
        raise ApiError(404, "UNKNOWN_EXAM", exam_id)
    items = []
    if kind == "sealed":
        short = []
        for d in p["domains"]:
            used = {iid for a in V["attempts"].values() if a["learner"] == learner and a["exam_id"] == exam_id and a["kind"] == "sealed" for iid in a["item_ids"]}
            pool = [i for i in V["items"].values() if i["exam"] == exam_id and i["domain"] == d["key"] and i["status"] == "ACTIVE" and i["family"] not in _seen(learner) and i["item_id"] not in used]
            fams, chosen = set(), []
            for i in sorted(pool, key=lambda x: x["item_id"]):
                if i["family"] in fams:
                    continue  # variants of one family are not independent items
                fams.add(i["family"]); chosen.append(i)
            need = d["internal_items"]
            if len(chosen) < need:
                short.append({"domain": d["name"], "need": need, "have_independent_active": len(chosen)})
            items += chosen[:need]
        if short and not max_items:
            raise ApiError(409, "FORM_NOT_BUILDABLE", "봉인 시험지를 구성할 ACTIVE(검수 완료) 독립 문항이 부족합니다.", shortfall=short)
        if max_items:
            items = items[:max_items]
        if not items:
            raise ApiError(409, "FORM_NOT_BUILDABLE", "ACTIVE 문항이 없습니다.", shortfall=short)
    else:
        items = sorted([i for i in V["items"].values() if i["exam"] == exam_id and i["status"] != "RETIRED"], key=lambda x: x["item_id"])
        if not items:
            raise ApiError(409, "NO_ITEMS", "해당 시험의 연습 문항이 없습니다.")
    return items


def create_attempt(actor, exam_id, kind="practice", max_items=None, duration_override_s=None):
    if kind not in ("practice", "sealed"):
        raise ApiError(400, "BAD_KIND", "practice|sealed")
    if exam_id == "DE-P-WEB":
        raise ApiError(409, "PROFILE_MIX_BLOCKED", "DE-P 웹/PDF 프로필 혼합 금지: 시험은 DE-P(10월 PDF 임시 기준)로만 구성합니다. 자료 상충이 해소되기 전 최종 준비 판정은 보류됩니다.")
    items = build_form(actor["user_id"], exam_id, kind, max_items)
    p = C.EXAM_PROFILES[exam_id]
    dur = (duration_override_s if (duration_override_s and actor["role"] in STAFF) else p["duration_min"] * 60)
    aid = nid("ATT")
    base = exam_id if exam_id != "DE-P-WEB" else "DE-P"
    a = {"attempt_id": aid, "learner": actor["user_id"], "exam_id": exam_id, "kind": kind, "item_ids": [i["item_id"] for i in items], "started_at": now(), "deadline": now() + dur,
         "duration_s": dur, "responses": {}, "status": "IN_PROGRESS", "result": None,
         "profile_lock": {"guide_revision": p["guide_revision"], "language": p["language"], "duration_min": p["duration_min"], "assist_tools": "BLOCKED" if kind == "sealed" else "ALLOWED(practice)"},
         "readiness_eligible": kind == "sealed" and all(V["items"][i]["status"] == "ACTIVE" for i in [x["item_id"] for x in items]) and not max_items,
         "partial_form": bool(max_items), "open_conflicts_at_start": [c["conflict_id"] for c in V["conflicts"] if c["exam_id"] == base and c.get("status", "OPEN") == "OPEN"]}
    V["attempts"][aid] = a
    for i in items:
        V["items"][i["item_id"]]["exposure_count"] += 1
    audit(actor, "ATTEMPT_CREATED", aid, detail={"exam": exam_id, "kind": kind, "n": len(items)})
    save()
    return attempt_view(actor, a)


def _get_attempt(actor, aid):
    a = V["attempts"].get(aid)
    if not a or (a["learner"] != actor["user_id"] and actor["role"] not in STAFF):
        raise ApiError(404, "ATTEMPT_NOT_FOUND", "시험 응시를 찾을 수 없거나 접근 권한이 없습니다.")
    _expire(a)
    return a


def _expire(a):
    if a["status"] == "IN_PROGRESS" and now() > a["deadline"]:
        a["status"] = "EXPIRED_SUBMITTED"
        a["seen_before"] = list(_seen(a["learner"]))
        a["result"] = _score_attempt(a)
        _post_submit(a)
        save()


def attempt_view(actor, a):
    reveal = a["status"] != "IN_PROGRESS" and a["kind"] == "practice"
    v = {k: a[k] for k in ("attempt_id", "exam_id", "kind", "status", "started_at", "deadline", "duration_s", "profile_lock", "readiness_eligible", "partial_form")}
    v["server_time"] = now(); v["remaining_s"] = max(0, int(a["deadline"] - now())) if a["status"] == "IN_PROGRESS" else 0
    v["items"] = [item_public(V["items"][i], reveal=reveal) for i in a["item_ids"]]
    v["responses"] = {k: {"answer": r["answer"], "version": r["version"]} for k, r in a["responses"].items()}
    if a["status"] != "IN_PROGRESS":
        r = dict(a["result"] or {})
        if a["kind"] == "sealed" and actor["role"] not in STAFF:
            r.pop("per_item", None)
        v["result"] = r
    v["disclaimer"] = DISCLAIMER
    return v


def respond(actor, aid, item_id, answer, client_version):
    a = _get_attempt(actor, aid)
    if a["status"] != "IN_PROGRESS":
        raise ApiError(409, "ATTEMPT_LOCKED", f"상태 {a['status']}: 제출 후 수정할 수 없습니다.")
    if item_id not in a["item_ids"]:
        raise ApiError(400, "ITEM_NOT_IN_FORM", item_id)
    cur = a["responses"].get(item_id)
    if cur and client_version <= cur["version"]:
        return {"saved": False, "duplicate_or_stale": True, "version": cur["version"]}
    it = V["items"][item_id]
    ans = sorted(set(answer or []))
    if any(x not in [c["id"] for c in it["choices"]] for x in ans):
        raise ApiError(400, "BAD_CHOICE", "선택지 ID 오류")
    if it["type"] == "single" and len(ans) > 1:
        raise ApiError(400, "TOO_MANY", "단일 선택 문항")
    if it["type"] == "multi" and len(ans) > it["select_count"]:
        raise ApiError(400, "TOO_MANY", f"{it['select_count']}개까지 선택")
    a["responses"][item_id] = {"answer": ans, "version": client_version, "saved_at": _iso()}
    save()
    return {"saved": True, "version": client_version}


def _score_item(it, ans):
    # internal rule (documented): multi-select = all-or-nothing exact set match; NOT the official hidden rule
    return sorted(ans) == sorted(it["correct"])


def _score_attempt(a, exclude=None):
    exclude = exclude or set()
    per, by_dom, total, ok = [], {}, 0, 0
    for iid in a["item_ids"]:
        if iid in exclude:
            continue
        it = V["items"][iid]
        r = a["responses"].get(iid)
        c = bool(r) and _score_item(it, r["answer"])
        # eligibility: first exposure of the family before this attempt and not a recalled item
        elig = a.get("readiness_eligible", False) and it["family"] not in set(a.get("seen_before", []))
        per.append({"item_id": iid, "domain": it["domain"], "correct": c, "answered": bool(r), "eligible": elig, "family": it["family"]})
        d = by_dom.setdefault(it["domain"], {"n": 0, "correct": 0})
        d["n"] += 1; d["correct"] += c
        total += 1; ok += c
    return {"total": total, "correct": ok, "pct": round(100 * ok / total, 1) if total else 0, "by_domain": by_dom, "per_item": per,
            "scoring_rule": "multi-select: all-or-nothing (WIZBASE 내부 규칙, 공식 채점 규칙 아님)", "disclaimer": DISCLAIMER}


def _post_submit(a):
    learner = a["learner"]
    if a["kind"] == "practice":
        V["seen_families"].setdefault(learner, [])
        for iid in a["item_ids"]:
            f = V["items"][iid]["family"]
            if f not in V["seen_families"][learner]:
                V["seen_families"][learner].append(f)  # explanations shown -> excluded from later independent evidence
    for p in (a["result"] or {}).get("per_item", []):
        it = V["items"][p["item_id"]]
        r = a["responses"].get(p["item_id"])
        it["trial"]["n"] += 1; it["trial"]["correct"] += p["correct"]
        for x in (r["answer"] if r else []):
            it["trial"]["options"][x] = it["trial"]["options"].get(x, 0) + 1
    V["responses_log"].append({"attempt": a["attempt_id"], "learner": learner})


def submit(actor, aid):
    a = _get_attempt(actor, aid)
    if a["status"] != "IN_PROGRESS":
        return attempt_view(actor, a)  # idempotent: no double submit effects
    a["seen_before"] = list(_seen(a["learner"]))
    a["status"] = "SUBMITTED"
    a["result"] = _score_attempt(a)
    _post_submit(a)
    audit(actor, "ATTEMPT_SUBMITTED", aid)
    save()
    return attempt_view(actor, a)


def tutor_blocked(learner):
    for a in V["attempts"].values():
        if a["learner"] == learner and a["kind"] == "sealed" and a["status"] == "IN_PROGRESS" and now() <= a["deadline"]:
            return True
    return False


# ------------------------------------------------------------ labs (real DBX evidence)
REQ_LAB_FIELDS = ["workspace_ref", "cloud", "region", "run_id", "source_hash", "result_checksum", "runtime_version", "observed_runtime_version"]


def required_labs(exam_id):
    p = C.EXAM_PROFILES[exam_id]
    return sorted({f"LAB-{x}" for d in p["domains"] for x in d["packs"]})


def lab_submit(actor, body):
    for k in body:
        if re.search(r"(token|password|secret|credential)", k, re.I):
            raise ApiError(400, "SECRET_FIELD_REJECTED", "토큰/비밀번호는 수집하지 않습니다. 해당 필드는 저장되지 않았습니다.")
    lab_id = body.get("lab_id")
    if not lab_id:
        raise ApiError(400, "LAB_ID_REQUIRED", "lab_id")
    e = {"evidence_id": nid("EV"), "learner": actor["user_id"], "lab_id": lab_id, "exam_id": body.get("exam_id"), "submitted_at": _iso(),
         **{k: body.get(k) for k in REQ_LAB_FIELDS}, "claimed_runtime_version": body.get("claimed_runtime_version"), "logs_ref": body.get("logs_ref"), "reviewer": None, "evidence_level": "SELF_SUBMITTED"}
    lab = L.LABS.get(lab_id)
    e["lab_defined"] = bool(lab)
    e["lab_kind"] = lab["kind"] if lab else "undefined"
    e["task_results"] = body.get("task_results") if isinstance(body.get("task_results"), dict) else None
    e["statement_ids"] = [str(x)[:64] for x in (body.get("statement_ids") or [])][:50]
    e["cli_version"] = body.get("cli_version"); e["validate_exit"] = body.get("validate_exit"); e["auto_check"] = None
    missing = [k for k in REQ_LAB_FIELDS if not body.get(k)]
    if missing:
        e["status"] = "NEEDS_ORIGINAL"; e["reason"] = f"자기 신고만으로 통과 불가. 누락 필드: {missing}"
    elif body.get("claimed_runtime_version") and body["claimed_runtime_version"] != body["observed_runtime_version"]:
        e["status"] = "REJECTED_INCONSISTENT"; e["reason"] = "주장한 버전과 실행 증거의 버전이 불일치 — 실제 검증 증거 불인정, 재확인 필요"
    elif lab and lab["kind"] == "machine":
        _auto_check_machine(e, lab_id, body)
    elif lab and lab["kind"] == "cli":
        _auto_check_cli(e, body)
    elif lab and lab["kind"] == "manual":
        arts = body.get("artifacts") if isinstance(body.get("artifacts"), dict) else {}
        e["artifacts"] = {str(k)[:80]: str(v)[:64] for k, v in arts.items()}
        miss = [a for a in lab["required_artifacts"] if not re.fullmatch(r"[0-9a-f]{64}", str(arts.get(a, "")))]
        if miss:
            e["status"] = "NEEDS_ORIGINAL"; e["reason"] = f"필수 산출물 해시 누락/형식 오류: {miss}"; e["auto_check"] = {"state": "ARTIFACTS_MISSING", "missing": miss}
        else:
            e["status"] = "SUBMITTED"; e["auto_check"] = {"state": "ARTIFACTS_COMPLETE"}; e["reason"] = "필수 산출물 해시 완비. 검토자가 원본을 확인하고 루브릭으로 채점"
    else:
        e["status"] = "SUBMITTED"; e["reason"] = "검토자의 원본 확인 대기" + ("" if lab else " (해당 실습 팩 미작성: 자동 대조 없음)")
    V["lab_evidence"][e["evidence_id"]] = e
    audit(actor, "LAB_SUBMITTED", e["evidence_id"], e["status"])
    save()
    return e


def _ver_tuple(v):
    m = re.match(r"(\d+)\.(\d+)\.(\d+)", str(v or ""))
    return tuple(int(x) for x in m.groups()) if m else None


def _auto_check_cli(e, body):
    v = _ver_tuple(body.get("cli_version"))
    if not v or v < (0, 218, 0):
        e["status"] = "REJECTED_CLI_CHECK"; e["reason"] = "CLI 버전이 문서상 최소(0.218.0) 미만이거나 확인 불가"; e["auto_check"] = {"state": "CLI_FAIL"}
    elif body.get("validate_exit") != 0:
        e["status"] = "REJECTED_CLI_CHECK"; e["reason"] = "bundle validate 종료 코드가 0이 아님"; e["auto_check"] = {"state": "CLI_FAIL"}
    else:
        e["status"] = "SUBMITTED"; e["auto_check"] = {"state": "CLI_OK"}; e["reason"] = "CLI 버전·validate 통과(자동). deploy/run은 검토자가 run ID로 원본 확인"


def _auto_check_machine(e, lab_id, body):
    res = L.verify(lab_id, body.get("pack_hash"), e["task_results"])
    e["auto_check"] = res
    sids = {s for s in e["statement_ids"]}
    for x in (e["task_results"] or {}).values():
        if isinstance(x, dict) and x.get("statement_id"):
            sids.add(str(x["statement_id"]))
    dup = [o["evidence_id"] for o in V["lab_evidence"].values() if o["learner"] != e["learner"] and sids & set(o.get("statement_ids", []))]
    if res["state"] == "PACK_STALE":
        e["status"] = "REJECTED_PACK_STALE"; e["reason"] = res["reason"]
    elif dup:
        e["status"] = "REJECTED_DUPLICATE"; e["reason"] = "다른 학습자의 증거와 동일한 statement_id — 재사용 증거는 인정되지 않음"
    elif res["state"] == "MISMATCH":
        bad = [k for k, v in res["per_task"].items() if v != "MATCH"]
        e["status"] = "REJECTED_RESULT_MISMATCH"; e["reason"] = f"결과 체크섬이 기대와 다름: {bad} (기대값은 공개되지 않음 — SQL 의미를 점검해 다시 실행)"
    elif res["state"] == "INCOMPLETE" or res["missing_statement_ids"]:
        e["status"] = "NEEDS_ORIGINAL"; e["reason"] = "누락된 task 결과 또는 statement_id (Query History 확인용) 필요"
    else:
        e["status"] = "SUBMITTED"; e["reason"] = "자동 대조 일치(MATCHED). 검토자의 원본(Query History statement_id) 확인 대기"


def lab_review(actor, eid, decision, original_checked=False, note="", rubric_scores=None):
    need_staff(actor)
    e = V["lab_evidence"].get(eid)
    if not e:
        raise ApiError(404, "NO_EVIDENCE", eid)
    if e["learner"] == actor["user_id"]:
        raise ApiError(403, "SELF_REVIEW", "본인 증거를 승인할 수 없습니다.")
    if decision == "approve":
        if e["status"] != "SUBMITTED":
            raise ApiError(409, "NOT_APPROVABLE", f"상태 {e['status']}: 승인 불가")
        if not original_checked:
            raise ApiError(400, "ORIGINAL_NOT_CHECKED", "원본(실행 내보내기·코드·결과) 확인 없이 승인할 수 없습니다.")
        lab = L.LABS.get(e["lab_id"])
        if lab and lab["kind"] == "manual":
            rs = rubric_scores or {}
            items = {r["item"]: r["max"] for r in lab["rubric"]}
            if set(rs) != set(items) or any(not isinstance(rs[k], int) or rs[k] < 0 or rs[k] > items[k] for k in items):
                raise ApiError(400, "RUBRIC_INCOMPLETE", f"루브릭 전 항목(0~최대)을 채점해야 합니다: {list(items)}")
            total = sum(rs.values())
            e["rubric_scores"], e["rubric_total"] = rs, total
            if total < lab["pass_score"]:
                e["status"] = "ON_HOLD"; e["reviewer"], e["note"] = actor["user_id"], note or f"루브릭 {total} < {lab['pass_score']}"
                audit(actor, "LAB_REVIEW", eid, "ON_HOLD"); save()
                return e
        e["status"] = "APPROVED"; e["evidence_level"] = "DBX_VERIFIED_REVIEWED"
    else:
        e["status"] = "ON_HOLD"
    e["reviewer"], e["note"] = actor["user_id"], note
    audit(actor, "LAB_REVIEW", eid, e["status"])
    refresh_objectives(); save()
    return e


def labs_status(learner, exam_id):
    req = required_labs(exam_id)
    ok = {e["lab_id"] for e in V["lab_evidence"].values() if e["learner"] == learner and e["status"] == "APPROVED"}
    return {"required": req, "approved": sorted(ok & set(req)), "missing": sorted(set(req) - ok),
            "authored": sorted(set(req) & set(L.LABS)), "not_authored": sorted(set(req) - set(L.LABS)),
            "note": "미작성 실습은 팩 콘텐츠가 아직 없어 수행할 수 없으며 해당 준비 판정은 차단된다."}


# ------------------------------------------------------------ practical / retest records (reviewer-entered)
def record_practical(actor, learner, exam_id, practical, explain, capstone_hintless=True, kind="practical"):
    need_staff(actor)
    if learner == actor["user_id"]:
        raise ApiError(403, "SELF_REVIEW", "본인 실기 평가를 입력할 수 없습니다.")
    V["practical"].setdefault(learner, {})[exam_id] = {"practical": practical, "explain": explain, "capstone_hintless": capstone_hintless, "by": actor["user_id"], "at": _iso()}
    audit(actor, "PRACTICAL_RECORDED", learner)
    save()
    return V["practical"][learner][exam_id]


def record_retest(actor, learner, exam_id, passed):
    need_staff(actor)
    V["retests"].setdefault(learner, {})[exam_id] = {"passed": bool(passed), "by": actor["user_id"], "at": _iso()}
    save()
    return V["retests"][learner][exam_id]


# ------------------------------------------------------------ skills / readiness
def skills(actor, learner):
    if learner != actor["user_id"] and actor["role"] not in STAFF:
        raise ApiError(403, "FORBIDDEN", "타인의 성적·역량 정보는 조회할 수 없습니다.")
    out = {}
    for a in V["attempts"].values():
        if a["learner"] != learner or a["status"] == "IN_PROGRESS":
            continue
        ex = out.setdefault(a["exam_id"], {})
        for p in a["result"]["per_item"]:
            d = ex.setdefault(p["domain"], {"knowledge": {"n": 0, "correct": 0, "eligible_n": 0, "eligible_correct": 0}, "lab": None, "recovery": None, "explain": None})
            k = d["knowledge"]; k["n"] += 1; k["correct"] += p["correct"]
            if p["eligible"]:
                k["eligible_n"] += 1; k["eligible_correct"] += p["correct"]
    for exam_id, ex in out.items():
        pr = V["practical"].get(learner, {}).get(exam_id)
        for d in ex.values():
            d["explain"] = pr["explain"] if pr else None
            d["lab"] = labs_status(learner, exam_id)
    return {"learner": learner, "dimensions": out, "note": "지식·실기·복구·설명을 평균으로 합치지 않고 차원별로 표시합니다.", "disclaimer": DISCLAIMER}


def readiness(actor, learner, exam_id):
    if learner != actor["user_id"] and actor["role"] not in STAFF:
        raise ApiError(403, "FORBIDDEN", "타인의 판정은 조회할 수 없습니다.")
    if exam_id not in C.EXAM_PROFILES or exam_id == "DE-P-WEB":
        raise ApiError(400, "BAD_EXAM", "DE-A | DE-P | GEN-A")
    p = C.EXAM_PROFILES[exam_id]
    cov = coverage(exam_id)
    crit, reasons = [], []

    def c(name, ok, detail=""):
        crit.append({"criterion": name, "met": bool(ok), "detail": detail})
        if not ok:
            reasons.append(name)

    c("공식 목표 전수 매핑·MISSING 0·중대 결함 0", cov["release_gate_ok"], "; ".join(cov["blockers"]) or "충족")
    c("공식 자료 상충 해소", not cov["open_conflicts"], f"미해결 {len(cov['open_conflicts'])}건")
    atts = [a for a in V["attempts"].values() if a["learner"] == learner and a["exam_id"] == exam_id and a["kind"] == "sealed" and a["status"] in ("SUBMITTED", "EXPIRED_SUBMITTED") and a["readiness_eligible"] and not a.get("recomputed_invalid")]
    atts.sort(key=lambda a: a["started_at"])
    last3 = atts[-3:]
    c("서로 다른 봉인 모의시험 3회, 회차별 85% 이상", len(last3) == 3 and all(a["result"]["pct"] >= 85 for a in last3), f"유효 회차 {len(atts)}회, 최근: {[a['result']['pct'] for a in last3]}")
    dom_stats = {}
    seen_items = {}
    for a in atts:
        for pi in a["result"]["per_item"]:
            if pi["eligible"]:
                seen_items.setdefault(pi["domain"], {})[pi["item_id"]] = pi["correct"]
    low = []
    for d in p["domains"]:
        m = seen_items.get(d["key"], {})
        n, ok = len(m), sum(m.values())
        dom_stats[d["key"]] = {"n_distinct": n, "pct": round(100 * ok / n, 1) if n else None}
        if n < 10:
            low.append(f"{d['name']}: 유효 문항 {n}/10 (표본 미달 → 보완 평가)")
        elif 100 * ok / n < 80:
            low.append(f"{d['name']}: 숙련도 {round(100 * ok / n)}% < 80%")
    c("도메인별 숙련도 80%+ (도메인당 서로 다른 유효 문항 10개 이상)", not low, "; ".join(low) or "충족")
    ls = labs_status(learner, exam_id)
    c("필수 실제 DBX 실습 전부 통과(검토자 원본 확인)", not ls["missing"], f"미통과 {len(ls['missing'])}/{len(ls['required'])}")
    pr = V["practical"].get(learner, {}).get(exam_id)
    c("실기 85점+ · 힌트 없는 capstone · 설명 80점+", bool(pr) and pr["practical"] >= 85 and pr["explain"] >= 80 and pr["capstone_hintless"], "미입력" if not pr else f"실기 {pr['practical']} / 설명 {pr['explain']}")
    c("지연 재평가 통과", bool(V["retests"].get(learner, {}).get(exam_id, {}).get("passed")), "")
    pending_rev = [r for r in V["source_revisions"] if r["exam_id"] == exam_id and not r.get("impact_reviewed")]
    c("가이드/시험 버전 변경 영향 확인 완료", not pending_rev, f"미확인 변경 {len(pending_rev)}건")
    if not atts and not ls["approved"] and not pr:
        label = "미진단"
    elif not reasons:
        label = "내부 응시준비 충족"
    elif atts:
        label = "보완필요"
    else:
        label = "학습중"
    rec = {"decision_id": nid("RD"), "learner": learner, "exam_id": exam_id, "label": label, "criteria": crit, "blocked_by": reasons, "domain_stats": dom_stats, "labs": ls,
           "basis": {"guide_revision": p["guide_revision"], "criteria_version": "WZ-READY-v1.1"}, "at": _iso(), "decided_by": actor["user_id"], "disclaimer": DISCLAIMER,
           "note": "WIZBASE 보수적 내부 기준이며 공식 합격선·합격 확률이 아닙니다. 합격 보장·공식 과정 이수 동등성·실무경력 인정 의미가 아닙니다."}
    V["readiness"].append(rec)
    audit(actor, "READINESS_DECIDED", rec["decision_id"], label)
    save()
    return rec


# ------------------------------------------------------------ grades
LEVELS = {"L0": "준비", "L1": "입문 수행", "L2": "독립 수행", "L3": "직무 개발", "L4": "선임", "L5": "기술 리드"}


def grade_decide(actor, body):
    lvl = body.get("grade")
    if lvl not in LEVELS:
        raise ApiError(400, "BAD_GRADE", "L0..L5")
    learner, track = body.get("learner"), body.get("track")
    if body.get("evaluator_type") == "ai" or actor.get("is_ai"):
        if lvl >= "L3" or lvl == "L2":
            audit(actor, "AI_PROMOTION_BLOCKED", learner, "blocked", {"grade": lvl})
            raise ApiError(403, "AI_CANNOT_APPROVE", "L2 이상 승급은 AI 튜터가 승인할 수 없습니다. 별도 검토자 승인이 필요합니다.")
    need_staff(actor)
    if learner == actor["user_id"]:
        raise ApiError(403, "SELF_EVALUATION", "본인 승급을 승인할 수 없습니다.")
    sc = body.get("scores", {})
    reasons, status = [], "APPROVED"
    t = (track or "")
    exam = body.get("exam_id") or ("GEN-A" if t.startswith("GEN") else "DE-P" if t.startswith("DE-P") else "DE-A")
    ls = labs_status(learner, exam) if exam in C.EXAM_PROFILES and C.EXAM_PROFILES[exam]["domains"] else {"approved": [], "missing": ["?"]}
    any_lab = bool(ls["approved"])
    fatal = body.get("fatal_failures") or []
    if fatal:
        status = "HOLD"; reasons.append(f"치명적 실패: {fatal}")
    if lvl == "L1":
        if not body.get("core_completion"):
            status = "HOLD"; reasons.append("입문 코어 80점+·필수 통제 통과 증거 없음")
    if lvl in ("L2", "L3", "L4", "L5"):
        need = {"L2": (80, 75), "L3": (85, 80), "L4": (85, 85), "L5": (85, 85)}[lvl]
        if sc.get("practical", 0) < need[0] or sc.get("explain" if lvl != "L4" else "design", 0) < need[1]:
            status = "HOLD"; reasons.append(f"점수 기준 미달(실기≥{need[0]}, 설명/설계≥{need[1]})")
    if lvl in ("L2", "L3", "L4", "L5") and not any_lab:
        status = "HOLD_REAL_VERIFICATION_PENDING"; reasons.append("실제 DBX 실습 증거 없음 — '모의 역량 충족·실제 검증 대기'로 표시, 정식 승급 불가")
    if lvl in ("L3", "L4", "L5") and ls["missing"]:
        status = "HOLD" if status == "APPROVED" else status; reasons.append(f"해당 트랙 필수 실제 실습 미통과 {len(ls['missing'])}건")
    if lvl == "L4" and body.get("faults_recovered", 0) < 3:
        status = "HOLD" if status == "APPROVED" else status; reasons.append("장애 3종 복구 증거 부족")
    if lvl == "L5" and (body.get("panel_size", 0) < 2 or not body.get("delivery_evidence")):
        status = "HOLD" if status == "APPROVED" else status; reasons.append("패널 검토(2인+)·전달 증거 필요")
    g = {"decision_id": nid("GD"), "learner": learner, "track": track, "grade": lvl, "status": status, "reasons": reasons, "evaluator": actor["user_id"], "scores": sc,
         "label": f"WZ-{lvl} {LEVELS[lvl]} ({track}) — WIZBASE 내부 등급, Databricks 공식 자격 아님", "at": _iso(),
         "valid_until": (datetime.now(timezone.utc) + timedelta(days=365)).date().isoformat() if status == "APPROVED" else None, "official_credential_status": "별도 관리(미확인)"}
    V["grades"].append(g)
    audit(actor, "GRADE_DECISION", g["decision_id"], status, {"grade": lvl})
    save()
    return g


# ------------------------------------------------------------ credentials
def cred_add(actor, body):
    cr = {"credential_ref": nid("CR"), "learner": actor["user_id"] if actor["role"] not in STAFF else body.get("learner", actor["user_id"]), "name": body.get("name", ""), "self_reported": True,
          "status": "PENDING_VERIFICATION", "issuer": None, "credential_id": None, "verification_url": None, "obtained": None, "expires": None, "verified_by": None, "verified_at": None, "company_link": "미확인"}
    for k in ("name", "claimed_obtained", "claimed_expires"):
        if body.get(k):
            cr[k] = body[k]
    V["credentials"].append(cr)
    save()
    return cr


def cred_verify(actor, ref, body):
    need_staff(actor)
    cr = next((c for c in V["credentials"] if c["credential_ref"] == ref), None)
    if not cr:
        raise ApiError(404, "NO_CRED", ref)
    for k in ("issuer", "credential_id", "verification_url", "obtained", "expires"):
        if not body.get(k):
            raise ApiError(400, "VERIFICATION_FIELD_REQUIRED", f"{k} 필요(발급기관 확인 URL·credential ID)")
    cr.update(issuer=body["issuer"], credential_id=body["credential_id"], verification_url=body["verification_url"], obtained=body["obtained"], expires=body["expires"],
              verified_by=actor["user_id"], verified_at=_iso(), self_reported=False, company_link=body.get("company_link", "미확인"))
    audit(actor, "CRED_VERIFIED", ref)
    save()
    return cred_status(cr)


def cred_status(cr):
    cr = dict(cr)
    if cr.get("verified_by"):
        cr["status"] = "VALID" if cr["expires"] >= datetime.now(timezone.utc).date().isoformat() else "EXPIRED"
    else:
        cr["status"] = "PENDING_VERIFICATION"
    return cr


def learner_profile(actor, learner):
    if learner != actor["user_id"] and actor["role"] not in STAFF:
        raise ApiError(403, "FORBIDDEN", "타인의 프로필은 조회할 수 없습니다.")
    grades = [g for g in V["grades"] if g["learner"] == learner]
    creds = [cred_status(c) for c in V["credentials"] if c["learner"] == learner]
    ready = [r for r in V["readiness"] if r["learner"] == learner]
    latest = {}
    for g in grades:
        if g["status"] == "APPROVED":
            latest[g["track"]] = g
    recert = {t: ("재평가 필요(12개월 경과)" if g["valid_until"] < datetime.now(timezone.utc).date().isoformat() else "유효") for t, g in latest.items()}
    return {"learner": learner, "internal_grades": latest, "internal_reassessment": recert, "official_credentials": creds or [{"status": "NONE_RECORDED"}],
            "readiness": {r["exam_id"]: r["label"] for r in ready}, "labs_approved": [e["lab_id"] for e in V["lab_evidence"].values() if e["learner"] == learner and e["status"] == "APPROVED"],
            "assignment_authorization": "별도 승인(자동 부여 없음)", "separation_note": "내부 등급·공식 자격·응시준비·실제 검증·투입 승인은 서로 다른 필드입니다.", "disclaimer": DISCLAIMER}


def partner_dashboard():
    learners = sorted({g["learner"] for g in V["grades"]} | {c["learner"] for c in V["credentials"]} | {a["learner"] for a in V["attempts"].values()})
    rows = []
    for l in learners:
        creds = [c for c in V["credentials"] if c["learner"] == l]
        rows.append({"learner": l, "grades": sorted({g["grade"] for g in V["grades"] if g["learner"] == l and g["status"] == "APPROVED"}),
                     "official_credentials": [cred_status(c)["status"] for c in creds] or ["NONE_RECORDED"], "labs_approved": len([e for e in V["lab_evidence"].values() if e["learner"] == l and e["status"] == "APPROVED"])})
    return {"company_program": {"partner_status": "Databricks 파트너(위즈베이스 제공 정보 — Partner Portal 원본 확인은 회사가 수행)", "poc": "실제 PoC 준비 중", "purpose": "파트너 레벨 상향을 위한 인증 시험 준비 지원 환경", "tier": "현재 레벨 미기재(상향 목표)", "academy_access": "회사 계정 기준 — 시스템이 확인하지 않음", "portal_confirmed_at": None},
            "note": "이 환경은 위즈베이스(Databricks 파트너)가 실제 PoC를 준비하며 파트너 레벨 상향을 위한 인증 시험 준비를 지원하는 내부 훈련 환경이며, Databricks 공식 제품·교육·시험이 아닙니다. 현재 파트너 tier·인증 인원은 이 시스템이 가정하지 않습니다. 인증 인원만으로 tier가 충족된다고 계산하지 않습니다. KB: Partner Portal 인증 연결은 회사 이메일·Academy 계정 연결 확인 필요.",
            "learners": rows, "kb_url": "https://kb.databricks.com/training/why-isn%E2%80%99t-my-certification-showing-in-the-partner-portal"}


# ------------------------------------------------------------ learning plan / tutor
BASE_HOURS = {"DE-A": "60~100", "DE-P": "추가 80~140", "GEN-A": "60~100", "FOUNDATION": "10~20"}


def make_plan(actor, exam_id, diagnostic, weekly_hours=6):
    if exam_id not in C.EXAM_PROFILES or not C.EXAM_PROFILES[exam_id]["domains"]:
        raise ApiError(400, "BAD_EXAM", "DE-A | DE-P | GEN-A")
    p = C.EXAM_PROFILES[exam_id]
    steps = []
    base = diagnostic.get("foundation_sql_python", 100)
    if base < 60:
        steps.append({"phase": "선행", "task": "SQL/Python·데이터 기초 보강(WZ-L0)", "reason": f"기초 진단 {base}% < 60%", "hours": BASE_HOURS["FOUNDATION"]})
    doms = sorted(p["domains"], key=lambda d: diagnostic.get(d["key"], 0))
    for d in doms:
        sc = diagnostic.get(d["key"])
        steps.append({"phase": "개념→연습→실습→평가→보완→지연확인", "domain": d["name"], "domain_key": d["key"], "diagnostic_pct": sc, "packs": d["packs"],
                      "real_dbx_labs": [f"LAB-{x}" for x in d["packs"]], "priority": "높음" if (sc if sc is not None else 0) < 60 else "보통",
                      "cycle": ["진단", "개념", "연습", "실제 실습(C)", "독립 평가(힌트 없음)", "보완", "지연 재평가(7일·21일)"]})
    plan = {"plan_id": nid("PL"), "learner": actor["user_id"], "exam_id": exam_id, "weekly_hours": weekly_hours, "steps": steps,
            "estimate": f"내부 초깃값 {BASE_HOURS.get(exam_id, '-')}시간 (개인 사전역량에 따라 조정, 공식 권장시간 아님)",
            "note": "시간 이수만으로 승급하지 않습니다.", "disclaimer": DISCLAIMER}
    V["plans"][plan["plan_id"]] = plan
    save()
    return plan


HINT_LADDER = ["1) 오류 맥락 확인: 어떤 계층(권한/데이터/코드)에서 실패했는지 말해보세요.", "2) 개념: 관련 개념과 공식 문서 위치를 확인하세요.", "3) 디버깅 순서: 오류→원인 가설→최소 재현 순으로 검증하세요.", "4) 부분 코드: 핵심 한 줄의 골격만 제시.", "5) 해설: 정답과 이유(학습 모드에서만)."]


def tutor_ask(actor, question, hint_level=None):
    if tutor_blocked(actor["user_id"]):
        audit(actor, "TUTOR_BLOCKED_SEALED", "tutor", "blocked")
        save()
        raise ApiError(403, "SEALED_EXAM_ACTIVE", "봉인 시험 진행 중에는 튜터·힌트·API 도움이 차단됩니다(감사 기록).")
    q = (question or "").lower()
    if re.search(r"\bdeny\b", q):
        iss = {"issue_id": nid("ISS"), "question": question, "reason": "가이드 표현(DENY)과 UC 실제 지원 구문의 상충 가능 — 제품 문서/실측 미확인", "status": "OPEN"}
        V["issues"].append(iss); save()
        return {"status": "NEEDS_VERIFICATION", "answer": "확인 필요: 시험 가이드의 표현만으로 UC `DENY` 구문 등을 구현·채점하지 않습니다. 제품 문서/실측 확인 전까지 보류하며 이슈를 생성했습니다.", "issue": iss, "sources": []}
    hits = [k for k in C.KB if any(t in q for t in k["tags"])]
    out = {"profile": "aws-seoul-training-baseline-20261111"}
    if hint_level:
        out["hint"] = HINT_LADDER[min(max(int(hint_level), 1), 5) - 1]
    if not hits:
        iss = {"issue_id": nid("ISS"), "question": question, "reason": "승인된 근거 없음", "status": "OPEN"}
        V["issues"].append(iss); save()
        return {**out, "status": "NEEDS_VERIFICATION", "answer": "승인된 공식 문서·검토 콘텐츠에서 근거를 찾지 못했습니다. 확인 필요 — 임의로 확정하지 않고 이슈를 생성했습니다.", "issue": iss, "sources": []}
    return {**out, "status": "ANSWERED", "answer": "\n\n".join(f"[{k['title']}] {k['text']}" for k in hits),
            "sources": [{"url": k["url"], "basis_date": C.BASIS, "title": k["title"]} for k in hits],
            "alias_note": "Genie Agents(현재) = Genie Spaces(과거 명칭); Declarative Automation Bundles = 이전 명칭 Asset Bundles — 이름 대응이며 다른 기능을 동일시하지 않음." if any("genie" in k["tags"] or "bundle" in k["tags"] for k in hits) else None,
            "disclaimer": DISCLAIMER}


def list_issues():
    return V["issues"]
