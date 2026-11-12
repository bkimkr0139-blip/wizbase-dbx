"""v1.1 확장: Academy 이력 · 투입 승인 · 개인정보(열람/삭제) · 현장 대조표(V1~V6) · 파일럿 보고. v11 저장소(V)를 공유한다."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone

from . import v11
from .core import ApiError

STAFF = v11.STAFF


def _V():
    return v11.V


def academy_add(actor, body):
    learner = body.get("learner", actor["user_id"]) if actor["role"] in STAFF else actor["user_id"]
    r = {"record_id": v11.nid("AC"), "learner": learner, "course": str(body.get("course", ""))[:120], "completed_on": body.get("completed_on"), "proof_ref": str(body.get("proof_ref", ""))[:300],
         "status": "PENDING_VERIFICATION", "verified_by": None, "note": "공식 Academy 이수 이력은 원본(배지·수강 증거) 확인 전에는 확인대기. 시뮬레이터 레슨 완료와 별개."}
    _V().setdefault("academy", []).append(r)
    v11.save()
    return r


def academy_verify(actor, rid, source_url):
    v11.need_staff(actor)
    r = next((x for x in _V().get("academy", []) if x["record_id"] == rid), None)
    if not r:
        raise ApiError(404, "NO_RECORD", rid)
    if not source_url:
        raise ApiError(400, "SOURCE_REQUIRED", "원본 확인 URL/참조가 필요합니다.")
    r.update(status="VERIFIED", verified_by=actor["user_id"], source_url=source_url, verified_at=v11._iso())
    v11.audit(actor, "ACADEMY_VERIFIED", rid)
    v11.save()
    return r


def academy_list(actor, learner):
    if learner != actor["user_id"] and actor["role"] not in STAFF:
        raise ApiError(403, "FORBIDDEN", "타인의 이력은 조회할 수 없습니다.")
    return [r for r in _V().get("academy", []) if r["learner"] == learner]


def assignment_grant(actor, body):
    """투입 승인: 내부 등급·공식 자격과 별개. 자동 부여 없음. 승인된 내부 등급(WZ-L2+, 미만료) 근거 필요."""
    v11.need_staff(actor)
    learner, role, scope = body.get("learner"), body.get("role"), body.get("scope")
    if not (learner and role and scope):
        raise ApiError(400, "FIELDS_REQUIRED", "learner, role, scope")
    if learner == actor["user_id"]:
        raise ApiError(403, "SELF_AUTHORIZATION", "본인 투입을 승인할 수 없습니다.")
    today = datetime.now(timezone.utc).date().isoformat()
    ok = [g for g in _V()["grades"] if g["learner"] == learner and g["status"] == "APPROVED" and g["grade"] >= "L2" and (g["valid_until"] or "") >= today]
    if not ok:
        raise ApiError(409, "NO_BASIS_GRADE", "유효한 내부 등급(WZ-L2 이상, 승인·미만료) 근거가 없어 투입 승인할 수 없습니다. (공식 자격 보유만으로 자동 승인되지 않음)")
    a = {"authorization_id": v11.nid("AA"), "learner": learner, "role": role, "scope": scope, "basis_grade_decision": ok[-1]["decision_id"], "granted_by": actor["user_id"], "granted_at": v11._iso(),
         "valid_until": body.get("valid_until") or (datetime.now(timezone.utc) + timedelta(days=180)).date().isoformat(), "status": "ACTIVE", "note": "고객 투입 판단은 팀 책임자의 별도 책임"}
    _V().setdefault("assignments", []).append(a)
    v11.audit(actor, "ASSIGNMENT_GRANTED", a["authorization_id"])
    v11.save()
    return a


def assignment_revoke(actor, aid, reason):
    v11.need_staff(actor)
    a = next((x for x in _V().get("assignments", []) if x["authorization_id"] == aid), None)
    if not a:
        raise ApiError(404, "NO_AUTH", aid)
    a.update(status="REVOKED", revoked_by=actor["user_id"], revoke_reason=reason or "", revoked_at=v11._iso())
    v11.audit(actor, "ASSIGNMENT_REVOKED", aid)
    v11.save()
    return a


def assignments_for(actor, learner):
    if learner != actor["user_id"] and actor["role"] not in STAFF:
        raise ApiError(403, "FORBIDDEN", "타인의 투입 승인은 조회할 수 없습니다.")
    today = datetime.now(timezone.utc).date().isoformat()
    return [{**a, "effective": a["status"] == "ACTIVE" and a["valid_until"] >= today} for a in _V().get("assignments", []) if a["learner"] == learner]


PRIVACY = {"retention": {"학습 활동(응시 답안·학습계획·자기 신고 credential·Academy 이력)": "삭제 요청 시 삭제, 요청이 없으면 마지막 활동 후 24개월 뒤 삭제(내부 기본값)",
                         "등급 결정·투입 승인·감사 이벤트": "품질·인사 감사 목적 보존(개인 학습 데이터와 분리)", "공식 자격 검증 기록": "발급기관 확인 URL·ID만 보관(비밀번호·토큰 수집 안 함)"},
           "rights": ["열람: GET /api/learners/me/export", "정정: 자기 신고 항목 수정 요청 → 검토자 확인", "삭제: POST /api/learners/me/delete (학습 활동 삭제, 승인된 증거·등급·투입 승인·감사는 보존)"],
           "note": "내부 기본값이며 법무·개인정보 담당 검토 전 초안입니다(검토 미수행)."}


def privacy_export(actor):
    V, me = _V(), actor["user_id"]
    atts = []
    for a in V["attempts"].values():
        if a["learner"] == me:
            atts.append({**{k: a[k] for k in ("attempt_id", "exam_id", "kind", "status", "started_at")}, "result": a.get("result") and {k: v for k, v in a["result"].items() if k != "per_item"}})
    return {"learner": me, "exported_at": v11._iso(), "attempts": atts, "plans": [p for p in V["plans"].values() if p["learner"] == me], "credentials": [c for c in V["credentials"] if c["learner"] == me],
            "academy": [r for r in V.get("academy", []) if r["learner"] == me], "lab_evidence": [e for e in V["lab_evidence"].values() if e["learner"] == me], "grades": [g for g in V["grades"] if g["learner"] == me],
            "assignments": [a for a in V.get("assignments", []) if a["learner"] == me], "readiness": [r for r in V["readiness"] if r["learner"] == me], "policy": PRIVACY}


def privacy_delete(actor):
    V, me = _V(), actor["user_id"]
    n = {"attempts": 0, "plans": 0, "credentials": 0, "academy": 0, "lab_evidence": 0}
    for k in [k for k, a in V["attempts"].items() if a["learner"] == me]:
        V["attempts"].pop(k); n["attempts"] += 1
    for k in [k for k, p in V["plans"].items() if p["learner"] == me]:
        V["plans"].pop(k); n["plans"] += 1
    c0 = len(V["credentials"]); V["credentials"] = [c for c in V["credentials"] if c["learner"] != me]; n["credentials"] = c0 - len(V["credentials"])
    a0 = len(V.get("academy", [])); V["academy"] = [r for r in V.get("academy", []) if r["learner"] != me]; n["academy"] = a0 - len(V["academy"])
    for k in [k for k, e in V["lab_evidence"].items() if e["learner"] == me and e["status"] != "APPROVED"]:
        V["lab_evidence"].pop(k); n["lab_evidence"] += 1
    V["seen_families"].pop(me, None); V["practical"].pop(me, None); V["retests"].pop(me, None)
    v11.audit(actor, "PRIVACY_DELETE", me, "ok", n)
    v11.save()
    return {"deleted": n, "retained": "승인된 실습 증거·등급 결정·투입 승인·감사 이벤트(보존 정책 참조)", "policy": PRIVACY["retention"]}


MATRIX_COLS = ["feature_id", "profile_version", "doc_path", "observed_menu_path", "input", "actor_runas", "expected", "actual", "simulated_result", "diff", "severity", "owner", "evidence", "recheck_date"]
STEPS = {"V1": "클라우드·리전·관리자 설정·기능·권한 수집", "V2": "핵심 화면 진입·생성·수정·실행 관찰", "V3": "합성 데이터로 SQL/Python/Bundle 실제 실행", "V4": "최소권한·run-as·미지원·실패 사례", "V5": "SA 범위·차이 목록 검토", "V6": "수정 후 회귀검증·프로필 릴리스"}


def matrix_add(actor, row):
    v11.need_staff(actor)
    miss = [c for c in MATRIX_COLS if c not in row or row[c] in (None, "")]
    if miss:
        raise ApiError(400, "COLUMNS_REQUIRED", f"대조표 필수 열 누락: {miss}")
    if row["severity"] not in ("none", "low", "medium", "high", "critical"):
        raise ApiError(400, "BAD_SEVERITY", "none|low|medium|high|critical")
    if row.get("step", "V2") not in STEPS:
        raise ApiError(400, "BAD_STEP", "V1..V6")
    r = {**{c: str(row[c])[:400] for c in MATRIX_COLS}, "row_id": v11.nid("VX"), "recorded_by": actor["user_id"], "recorded_at": v11._iso(), "semantic_match": bool(row.get("semantic_match", row["severity"] == "none")), "step": row.get("step", "V2")}
    _V().setdefault("matrix", []).append(r)
    v11.audit(actor, "MATRIX_ROW", r["row_id"])
    v11.save()
    return r


def matrix_summary(features):
    rows = _V().get("matrix", [])
    verified = {r["feature_id"] for r in rows}
    mism = [r for r in rows if not r["semantic_match"]]
    return {"rows": rows, "columns": MATRIX_COLS, "steps": STEPS, "verified_features": sorted(verified), "unverified_features": [f["feature_id"] for f in features if f["feature_id"] not in verified],
            "critical_or_high_mismatches": [r["row_id"] for r in mism if r["severity"] in ("high", "critical")], "match_rate": (round(100 * (len(rows) - len(mism)) / len(rows), 1) if rows else None),
            "note": "일치율은 실제로 대조한 행만 분모로 하며 미검증 기능은 별도 표시(분모에 넣어 부풀리지 않음). 접근하지 못한 클라우드·리전의 일치도는 보고하지 않음. 대조 행이 없으면 일치율 없음."}


def recheck_feature(actor, features, fid, workspace_checked):
    v11.need_staff(actor)
    f = next((x for x in features if x["feature_id"] == fid), None)
    if not f:
        raise ApiError(404, "NO_FEATURE", fid)
    today = datetime.now(timezone.utc).date().isoformat()
    f["doc_checked_at"] = today
    if workspace_checked:
        f["workspace_checked_at"] = today
        f["status"] = "WORKSPACE_CHECKED"
    v11.audit(actor, "FEATURE_RECHECK", fid)
    return f


def feature_view(features):
    today = datetime.now(timezone.utc).date()
    out = []
    for f in features:
        g = dict(f)
        d = g.get("doc_checked_at")
        age = (today - datetime.fromisoformat(d).date()).days if d else None
        g["age_days"] = age
        g["stale"] = bool(d) and age is not None and age > 35          # 월 1회 정기 대조 기준(35일 초과 시 재검증 필요)
        if g["stale"]:
            g["status_effective"] = "STALE"
        else:
            g["status_effective"] = g["status"]
        out.append(g)
    return out
