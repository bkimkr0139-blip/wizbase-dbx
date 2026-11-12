"""전이 산업 시드(제조 IoT · 클릭스트림 · 문서 RAG)와 협업 훈련(DBA·데이터엔지니어·AX·리뷰어) 흐름.

- 시드: 고정 난수·고정 시계의 합성 CSV. 학습자 본인의 교육용 워크스페이스(볼륨)에 올려 쓴다. 실개인정보·고객 데이터 없음.
  심어 둔 문제(중복·역순·이상치·봇·만료 문서 등)의 정답표는 직원(강사/검토자)만 조회한다.
- 협업: 4개 역할이 서로 다른 사람이어야 완료되며, 선행 역할 산출물 없이는 다음 역할을 진행할 수 없고, 본인 산출물은 본인이 승인할 수 없다.
"""
from __future__ import annotations
import csv, hashlib, io, json, random
from datetime import datetime, timedelta

from . import v11
from .core import ApiError

CLOCK = datetime(2026, 11, 11, 6, 0, 0)
DISCLAIMER = "합성 데이터. 실제 설비·고객·문서와 무관. 교육용 워크스페이스에서만 사용할 것."


# ------------------------------------------------------------------ generators
def _csv(header, rows):
    b = io.StringIO()
    w = csv.writer(b, lineterminator="\n")
    w.writerow(header)
    w.writerows(rows)
    return b.getvalue()


def _gen_iot(r):
    """설비 6대 × 5분 간격 × 24h. 중복·역순 도착·결측 구간·센서 고착(drift)·이상치를 심는다."""
    eq = [f"EQ-{i:02d}" for i in range(1, 7)]
    rows, missing, outliers, stuck = [], 0, [], 0
    gap_eq, gap_from, gap_to = "EQ-03", 100, 124           # 2시간 결측
    stuck_eq, stuck_from = "EQ-05", 200                    # 이후 값이 고정
    for e in eq:
        base = 60 + r.random() * 10
        last = None
        for k in range(288):
            ts = CLOCK + timedelta(minutes=5 * k)
            if e == gap_eq and gap_from <= k < gap_to:
                missing += 1
                continue
            temp = round(base + r.gauss(0, 0.8), 2)
            vib = round(max(0.0, 2.0 + r.gauss(0, 0.3)), 3)
            if e == stuck_eq and k >= stuck_from:
                temp = last if last is not None else temp
                stuck += 1
            if r.random() < 0.004:
                temp = round(temp + r.choice([-1, 1]) * 40, 2)
                outliers.append((e, ts.isoformat()))
            last = temp
            rows.append([f"{e}-{k:04d}", e, ts.isoformat(), temp, vib])
    dup_ids = sorted(r.sample([x[0] for x in rows], 25))
    dups = [x for x in rows if x[0] in set(dup_ids)]
    out = rows + dups
    r.shuffle(out)                                         # 역순 도착
    return {"readings.csv": _csv(["reading_id", "equipment_id", "event_ts", "temp_c", "vibration_mm_s"], out)}, {
        "total_rows_in_file": len(out), "distinct_readings": len(rows), "duplicate_rows": len(dups), "missing_intervals": missing,
        "missing_equipment": gap_eq, "stuck_sensor": {"equipment": stuck_eq, "from_interval": stuck_from, "stuck_rows": stuck}, "outlier_count": len(outliers),
        "rules": "중복=reading_id 기준 / 이상치=|값-설비 중앙값|>20 / 결측=5분 간격 누락"}


def _gen_clicks(r):
    pages = ["/home", "/search", "/product", "/cart", "/checkout", "/order-done"]
    rows, eid = [], 0
    bots, human_sessions, converted = 0, 0, 0
    for u in range(1, 121):
        n_sess = r.choice([1, 1, 2, 3])
        t = CLOCK + timedelta(minutes=r.randint(0, 600))
        for s in range(n_sess):
            is_bot = u > 112
            human_sessions += 0 if is_bot else 1
            bots += 1 if is_bot else 0
            steps = r.randint(40, 60) if is_bot else r.randint(2, 6)
            path = [pages[min(i, 5)] if not is_bot else r.choice(pages[:3]) for i in range(steps)]
            if not is_bot and r.random() < 0.3:
                path = pages[: r.randint(4, 6)]
            if not is_bot and "/order-done" in path:
                converted += 1
            for p in path:
                t += timedelta(seconds=1 if is_bot else r.randint(5, 90))
                eid += 1
                rows.append([f"E-{eid:06d}", f"U-{u:03d}", t.isoformat(), "page_view", p, "bot/1.0" if is_bot else "Mozilla/5.0"])
            t += timedelta(minutes=45)                     # 세션 구분(30분 규칙) 보장
    dup = r.sample(rows, 30)
    out = rows + [list(x) for x in dup]
    r.shuffle(out)
    return {"events.csv": _csv(["event_id", "user_id", "event_ts", "event_type", "page", "user_agent"], out)}, {
        "total_rows_in_file": len(out), "distinct_events": len(rows), "duplicate_event_rows": len(dup), "bot_users": 8, "bot_sessions": bots, "human_sessions": human_sessions,
        "converted_human_sessions": converted, "rules": "세션=사용자별 30분 비활동 분리 / 봇=user_agent bot 포함 / 전환=/order-done 도달"}


def _gen_rag(r):
    topics = ["반품 규정", "배송 마감", "신용 한도", "재고 실사", "단가 승인", "냉장 보관"]
    docs, chunks = [], []
    stale = restricted = pii = 0
    for d in range(1, 41):
        ver = r.choice([1, 2, 3])
        latest = ver == 3 or r.random() < 0.4
        status = "CURRENT" if latest else "SUPERSEDED"
        acl = r.choice(["all", "all", "all", "finance", "ops"])
        docs.append([f"DOC-{d:03d}", f"{r.choice(topics)} 안내 {d}", ver, status, acl, (CLOCK - timedelta(days=r.randint(1, 700))).date().isoformat()])
        for c in range(r.randint(2, 5)):
            has_pii = r.random() < 0.06
            text = f"{topics[d % 6]} 관련 합성 문단 {d}-{c}. " + ("담당자 연락처 010-0000-%04d (합성)." % (d * 10 + c) if has_pii else "기준은 부서 내규를 따른다.")
            chunks.append([f"CH-{d:03d}-{c}", f"DOC-{d:03d}", c, text, len(text)])
            stale += status == "SUPERSEDED"
            restricted += acl != "all"
            pii += has_pii
    return {"documents.csv": _csv(["doc_id", "title", "version", "status", "acl_group", "last_reviewed"], docs),
            "chunks.csv": _csv(["chunk_id", "doc_id", "chunk_no", "text", "char_len"], chunks)}, {
        "documents": len(docs), "chunks": len(chunks), "stale_chunks": stale, "acl_restricted_chunks": restricted, "chunks_with_synthetic_phone": pii,
        "rules": "검색 대상=status CURRENT / ACL all 외 문서는 해당 그룹 질의에만 / 전화번호 패턴 청크는 마스킹 후 색인"}


SEEDS = {
    "mfg-iot-v1": {"title": "제조 IoT 센서(설비 6대·24h)", "gen": _gen_iot, "exams": ["DE-A", "DE-P"], "use": "스트리밍/배치 중복 제거·지연 도착·결측·이상치 탐지(DE-04, CORE-01 전이 과제)"},
    "clickstream-v1": {"title": "웹 클릭스트림(120명)", "gen": _gen_clicks, "exams": ["DE-A", "DE-P"], "use": "세션화·봇 제외·전환 퍼널·중복 이벤트 제거(DE-02, DE-03 전이 과제)"},
    "doc-rag-v1": {"title": "사내 문서 RAG 코퍼스(40문서)", "gen": _gen_rag, "exams": ["GEN-A"], "use": "청킹 품질·최신 버전만 색인·ACL 필터·PII 마스킹(GEN-A 전이 과제)"},
}


def _build(seed_id):
    if seed_id not in SEEDS:
        raise ApiError(404, "UNKNOWN_TRANSFER_SEED", ", ".join(SEEDS))
    files, key = SEEDS[seed_id]["gen"](random.Random(seed_id))
    return files, key


def seed_list():
    out = []
    for sid, s in SEEDS.items():
        files, _ = _build(sid)
        out.append({"seed_id": sid, "title": s["title"], "use": s["use"], "exams": s["exams"], "disclaimer": DISCLAIMER,
                    "files": {n: {"bytes": len(t.encode()), "rows": t.count("\n") - 1, "sha256": hashlib.sha256(t.encode()).hexdigest()} for n, t in files.items()}})
    return out


def seed_files(seed_id):
    files, _ = _build(seed_id)
    return {"seed_id": seed_id, "disclaimer": DISCLAIMER, "files": files, "sha256": {n: hashlib.sha256(t.encode()).hexdigest() for n, t in files.items()}}


def seed_answer_key(actor, seed_id):
    v11.need_staff(actor)
    _, key = _build(seed_id)
    return {"seed_id": seed_id, "answer_key": key, "note": "정답표는 직원 전용. 학습자에게 공개하지 말 것."}


# ------------------------------------------------------------------ collaboration
ROLES = ("DBA", "DATA_ENGINEER", "AX", "REVIEWER")
SCENARIO = {
    "scenario_id": "COLLAB-01", "title": "예외 마감 거래처 파이프라인 변경(4역할 협업)",
    "brief": "예외 마감(15:00) 거래처가 늘어 주문 보정 파이프라인과 Genie 질의를 함께 바꿔야 한다. 합성 food 데이터 기준으로 4개 역할이 순서대로 인계한다.",
    "tasks": [
        {"task_id": "T1", "role": "DBA", "after": [], "title": "권한·카탈로그 설계", "produce": "최소권한 GRANT 표(누가 무엇을 SELECT/MODIFY), 롤백 방법",
         "handoff_to": "DATA_ENGINEER", "handoff_must_include": "변경 가능한 스키마와 금지된 객체 목록"},
        {"task_id": "T2", "role": "DATA_ENGINEER", "after": ["T1"], "title": "파이프라인 변경·테스트", "produce": "변경 SQL/노트북 해시, 경계값 테스트 결과(마감 직전·직후·예외 거래처)",
         "handoff_to": "AX", "handoff_must_include": "새 컬럼 의미와 사용 가능 테이블"},
        {"task_id": "T3", "role": "AX", "after": ["T2"], "title": "Genie/에이전트 질의 검증", "produce": "질의 10개와 기대 답, 오답·권한 우회 시도 결과, 지침 수정안",
         "handoff_to": "REVIEWER", "handoff_must_include": "한계와 사람 확인 필요 지점"},
        {"task_id": "T4", "role": "REVIEWER", "after": ["T1", "T2", "T3"], "title": "리스크 검토·승인", "produce": "체크리스트(권한·정합성·증거 일치) 판정과 보류 사유",
         "handoff_to": None, "handoff_must_include": ""},
    ],
}


def _C():
    return v11.V.setdefault("collab", {})


def collab_scenario():
    return SCENARIO


def collab_create(actor, body):
    t = {"team_id": v11.nid("TEAM"), "scenario_id": SCENARIO["scenario_id"], "name": str(body.get("name", "팀"))[:80], "created_by": actor["user_id"], "members": {}, "tasks": {}, "closed": False}
    for tk in SCENARIO["tasks"]:
        t["tasks"][tk["task_id"]] = {"status": "BLOCKED" if tk["after"] else "READY", "artifact_sha256": None, "handoff_note": None, "submitted_by": None, "approved_by": None, "rejected_reason": None}
    _C()[t["team_id"]] = t
    v11.audit(actor, "COLLAB_CREATE", t["team_id"])
    v11.save()
    return t


def _team(tid):
    t = _C().get(tid)
    if not t:
        raise ApiError(404, "NO_TEAM", tid)
    return t


def collab_join(actor, tid, role):
    t = _team(tid)
    if role not in ROLES:
        raise ApiError(400, "BAD_ROLE", "/".join(ROLES))
    if actor["user_id"] in t["members"].values():
        raise ApiError(409, "ALREADY_IN_TEAM", "한 사람이 한 팀에서 두 역할을 맡을 수 없습니다.")
    if role in t["members"]:
        raise ApiError(409, "ROLE_TAKEN", role)
    t["members"][role] = actor["user_id"]
    v11.save()
    return t


def _refresh(t):
    for tk in SCENARIO["tasks"]:
        st = t["tasks"][tk["task_id"]]
        if st["status"] == "BLOCKED" and all(t["tasks"][a]["status"] == "DONE" for a in tk["after"]):
            st["status"] = "READY"


def collab_submit(actor, tid, task_id, body):
    t = _team(tid)
    tk = next((x for x in SCENARIO["tasks"] if x["task_id"] == task_id), None)
    if not tk:
        raise ApiError(404, "NO_TASK", task_id)
    if t["members"].get(tk["role"]) != actor["user_id"]:
        raise ApiError(403, "NOT_YOUR_ROLE", f"{task_id}는 {tk['role']} 담당자만 제출할 수 있습니다.")
    st = t["tasks"][task_id]
    if st["status"] == "BLOCKED":
        waiting = [a for a in tk["after"] if t["tasks"][a]["status"] != "DONE"]
        raise ApiError(409, "PREREQUISITE_NOT_DONE", "선행 작업 미완료: " + ", ".join(waiting))
    if st["status"] in ("DONE", "SUBMITTED"):
        raise ApiError(409, "ALREADY_SUBMITTED", st["status"])
    sha = str(body.get("artifact_sha256", "")).lower()
    if len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
        raise ApiError(400, "ARTIFACT_HASH_REQUIRED", "산출물 sha256(64자리 hex)이 필요합니다.")
    note = str(body.get("handoff_note", "")).strip()
    if tk["handoff_to"] and len(note) < 10:
        raise ApiError(400, "HANDOFF_REQUIRED", f"{tk['handoff_to']}에게 넘길 인계 메모가 필요합니다: {tk['handoff_must_include']}")
    st.update(status="SUBMITTED", artifact_sha256=sha, handoff_note=note[:1000] or None, submitted_by=actor["user_id"], rejected_reason=None)
    v11.audit(actor, "COLLAB_SUBMIT", f"{tid}/{task_id}")
    v11.save()
    return t


def collab_review(actor, tid, task_id, approve, reason=""):
    """제출물 검토: 제출자 본인 불가, 같은 팀의 다른 역할 구성원만. 반려 사유 필수."""
    t = _team(tid)
    st = t["tasks"].get(task_id)
    if not st:
        raise ApiError(404, "NO_TASK", task_id)
    if st["status"] != "SUBMITTED":
        raise ApiError(409, "NOT_SUBMITTED", st["status"])
    if actor["user_id"] == st["submitted_by"]:
        raise ApiError(403, "SELF_APPROVAL", "본인 산출물은 본인이 승인할 수 없습니다.")
    if actor["user_id"] not in t["members"].values() and actor["role"] not in v11.STAFF:
        raise ApiError(403, "NOT_IN_TEAM", "팀 구성원 또는 직원만 검토할 수 있습니다.")
    if not approve and not reason.strip():
        raise ApiError(400, "REASON_REQUIRED", "반려 사유가 필요합니다.")
    if approve:
        st.update(status="DONE", approved_by=actor["user_id"])
    else:
        st.update(status="READY", rejected_reason=reason[:500])
    _refresh(t)
    v11.audit(actor, "COLLAB_REVIEW", f"{tid}/{task_id}", "approved" if approve else "rejected")
    v11.save()
    return t


def collab_status(actor, tid):
    t = _team(tid)
    if actor["user_id"] not in t["members"].values() and actor["role"] not in v11.STAFF and actor["user_id"] != t["created_by"]:
        raise ApiError(404, "NO_TEAM", tid)
    done = all(s["status"] == "DONE" for s in t["tasks"].values())
    complete = done and len(set(t["members"].values())) == len(ROLES)
    return {**t, "complete": complete, "missing_roles": [r for r in ROLES if r not in t["members"]],
            "note": "완료는 4개 역할이 서로 다른 사람이고 모든 작업이 타인 승인을 받았을 때만 인정. 이 기록은 훈련 증거이며 공식 자격·투입 승인이 아님."}
