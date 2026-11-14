"""AX 자동 구축(사용자 사전 승인 기반): DB 연결·질의·분석 → 비정형 문서 파싱·청킹·임베딩 → 지식 카드 → 온톨로지 → native 파이프라인 → 평가 → 도메인 에이전트.
원칙
- 사용자가 연결 정보·문서 소스·범위·확인 사항을 제출하고 '자동 구축 승인'을 해야만 시작한다. 승인 뒤 입력이 바뀌면 승인은 무효.
- '완전 자동'은 사용자가 미리 정한 정책(관계 자동 승인 기준·release 자동 승인·배포 허용)의 범위 안에서만 사람 승인을 대신한다. 모든 자동 승인은 AUTO_POLICY 로 표시되고 감사 기록에 남는다.
- 업무 명령(원천 변경)은 자동으로 실행하지 않는다. 자동 평가는 구조·접근·검색 검사이며 현업 정답 검증이 아니다.
- 단계마다 자원을 확인하고, 실패 단계에서 멈추며(재개 가능), 어떤 단계도 실패를 성공으로 표시하지 않는다."""
from __future__ import annotations
import base64, hashlib, json, re, threading, time
from datetime import datetime, timezone

from .core import ApiError
from . import ax, ax_parse, ax_search, ax_tools, ops

CONFIRM = "자동 구축 승인"
ACKS = {"egress_ack": "데이터를 외부 LLM·외부 서비스로 보내지 않고 이 서버 안에서만 처리함을 확인합니다.",
        "readonly_ack": "연결 계정은 조회 전용이며 이 자동 구축이 원천 DB를 변경하지 않음을 확인합니다.",
        "resource_ack": "자동 구축이 서버 자원(CPU·메모리·디스크)을 사용함을 알고 있으며 자원 부족 시 중단됨을 확인합니다.",
        "nonprod_ack": "연결 대상은 개발·비운영 DB이며 반출이 허가된 범위임을 확인합니다."}
STAGES = [("PREFLIGHT", "자원 확인"), ("CONNECT", "DB 연결 7단계 테스트"), ("SCAN", "구조 수집"), ("PROFILE", "표본 분석(profile)"), ("RELATIONS", "관계 추론·정책 승인"),
          ("DOCS", "비정형 문서 청킹·임베딩 색인"), ("CARDS", "지식 카드 생성"), ("ONTOLOGY", "온톨로지 생성·검증·승인"), ("PIPELINE", "컴파일·native 파이프라인"), ("EVAL", "자동 평가"), ("AGENT", "도메인 에이전트 준비")]
MASK = re.compile(r"(password|passwd|secret|token|ssn|jumin|rrn|card_?no|biz_no|주민)", re.I)
_RUN_LOCK = threading.Lock()
_CANCEL: set = set()


def _now():
    return datetime.now(timezone.utc).isoformat()


def _hash(o):
    return hashlib.sha256(json.dumps(o, sort_keys=True, default=str).encode()).hexdigest()[:16]


def _st(pid):
    return ax.S["auto"].setdefault(pid, {"brief": None, "approval": None})


# ------------------------------------------------------------------ 사전작업(정보 제공)
def brief_set(a, pid, b):
    p, _ = ax._proj(a, pid, ("architect",))
    if p["mode"] == "RELEASE_CANDIDATE":
        raise ApiError(400, "MODE_NOT_ALLOWED", "RELEASE_CANDIDATE 프로젝트에서는 자동 구축을 쓸 수 없습니다.")
    cid = b.get("metadata_connector_id")
    c = ax.S["connectors"].get(cid)
    if not c or c["project_id"] != pid or c["purpose"] != "metadata":
        raise ApiError(400, "BAD_CONNECTOR", "metadata 용도 연결(metadata_connector_id)이 필요합니다.")
    th = b.get("policy") or {}
    inc = float(th.get("rel_min_inclusion", 0.98))
    if not (0.9 <= inc <= 1.0):
        raise ApiError(400, "BAD_POLICY", "rel_min_inclusion 은 0.9~1.0")
    brief = {"domain_name": (b.get("domain_name") or "domain")[:60], "metadata_connector_id": cid, "tenant_id": b.get("tenant_id"), "no_documents": bool(b.get("no_documents")),
             "doc_acl_internal_only": bool(b.get("doc_acl_internal_only", True)), "dba_baseline_count": b.get("dba_baseline_count"),
             "policy": {"rel_min_inclusion": inc, "rel_min_sample": max(int(th.get("rel_min_sample", 2)), 1), "auto_approve_relations": bool(th.get("auto_approve_relations", False)),
                        "auto_approve_release": bool(th.get("auto_approve_release", False)), "allow_deploy": bool(th.get("allow_deploy", False))},
             "acks": {k: bool((b.get("acks") or {}).get(k)) for k in ACKS}}
    s = _st(pid)
    s["brief"], s["approval"] = brief, None
    ax.audit(a, "AX_AUTO_BRIEF", pid, detail={"policy": brief["policy"]})
    ax._save()
    return {"brief": brief, "ack_texts": ACKS, "note": "입력을 바꾸면 이전 승인은 무효가 됩니다."}


def _sources(pid):
    return [s for s in ax.S["sources"].values() if s["project_id"] == pid]


def source_add(a, pid, b):
    ax._proj(a, pid, ("architect", "developer", "domain_expert"))
    if len(_sources(pid)) >= 50:
        raise ApiError(409, "TOO_MANY_SOURCES", "프로젝트당 소스는 50개까지입니다.")
    name = (b.get("name") or b.get("filename") or "").strip()
    if not name:
        raise ApiError(400, "BAD_SOURCE", "name(파일 이름)이 필요합니다.")
    if b.get("content_b64"):
        try:
            data = base64.b64decode(b["content_b64"], validate=True)
        except Exception:
            raise ApiError(400, "BAD_BASE64", "content_b64 형식이 올바르지 않습니다.")
    else:
        data = (b.get("text") or "").encode("utf-8")
        if "." not in name:
            name += ".txt"
    text, rep = ax_parse.parse_bytes(name, data)
    sid = "src-" + hashlib.sha1((pid + name + hashlib.md5(data).hexdigest()).encode()).hexdigest()[:10]
    ax.S["sources"][sid] = {"source_id": sid, "project_id": pid, "name": name, "kind": "upload", "text": text, "report": rep, "by": a["user_id"], "at": _now(), "sha": hashlib.sha256(data).hexdigest()[:16]}
    _invalidate(pid)
    ax.audit(a, "AX_SOURCE_ADD", pid, sid, detail={"file": name, "chars": rep["chars"], "warnings": len(rep["warnings"])})
    ax._save()
    return {"source_id": sid, "report": rep, "preview": text[:300]}


def source_folder(a, pid, b):
    ax._proj(a, pid, ("architect", "developer", "domain_expert"))
    files = ax_parse.list_folder(b.get("path", ""))
    out = []
    for f in files:
        try:
            r = source_add(a, pid, {"name": f.name, "content_b64": base64.b64encode(f.read_bytes()).decode()})
            out.append({"file": f.name, "ok": True, "source_id": r["source_id"], "warnings": r["report"]["warnings"]})
        except ApiError as e:
            out.append({"file": f.name, "ok": False, "error": e.code})
    return {"files": out, "ok": sum(1 for x in out if x["ok"]), "failed": sum(1 for x in out if not x["ok"])}


def source_list(a, pid):
    ax._proj(a, pid)
    return [{k: v for k, v in s.items() if k != "text"} | {"chars": len(s["text"])} for s in _sources(pid)]


def source_delete(a, pid, sid):
    ax._proj(a, pid, ("architect",))
    s = ax.S["sources"].get(sid)
    if not s or s["project_id"] != pid:
        raise ApiError(404, "SOURCE_NOT_FOUND", "소스를 찾을 수 없습니다.")
    ax.S["sources"].pop(sid)
    _invalidate(pid)
    ax._save()
    return {"ok": True}


def _invalidate(pid):
    s = ax.S["auto"].get(pid)
    if s and s.get("approval"):
        s["approval"] = None


# ------------------------------------------------------------------ 준비 점검·승인
def readiness(a, pid):
    p, _ = ax._proj(a, pid)
    st = _st(pid)
    br = st["brief"]
    chk = []

    def add(i, ok, msg):
        chk.append({"id": i, "ok": bool(ok), "msg": msg})
    add("brief", br, "사전작업 정보(연결·정책·확인)를 제출했습니다." if br else "먼저 사전작업 정보를 제출하세요.")
    if not br:
        return {"ready": False, "checks": chk}
    c = ax.S["connectors"].get(br["metadata_connector_id"])
    add("connector", c, "metadata 연결이 있습니다." if c else "연결이 삭제되었습니다.")
    lt = (c or {}).get("last_test")
    add("connection_test", lt and lt["all_pass"], "연결 테스트 7단계를 통과했습니다." if lt and lt["all_pass"] else "연결 테스트를 먼저 통과해야 합니다(실패·미실행 단계가 있음).")
    add("scope", c and (c["engine"] == "sqlite_fixture" or c.get("schema_allowlist")), "허용 schema 범위가 지정되어 있습니다.")
    n = len(_sources(pid))
    add("documents", n > 0 or br["no_documents"], f"비정형 소스 {n}개를 제출했습니다." if n else ("문서 없이 진행하기로 했습니다." if br["no_documents"] else "비정형 문서를 제출하거나 '문서 없음'을 선택하세요."))
    miss = [k for k, v in br["acks"].items() if not v]
    add("acks", not miss, "확인 사항에 모두 동의했습니다." if not miss else f"동의하지 않은 확인 사항: {', '.join(miss)}")
    try:
        pf = ops.preflight("auto_build")
        add("resources", pf["verdict"] != "BLOCK", f"자원 판정 {pf['verdict']} — " + "; ".join(x["msg"] for x in pf["reasons"]))
    except ApiError as e:
        add("resources", False, e.message)
    add("mode", p["mode"] != "RELEASE_CANDIDATE", "프로젝트 모드가 자동 구축을 허용합니다.")
    return {"ready": all(x["ok"] for x in chk), "checks": chk, "policy": br["policy"], "approval": st.get("approval"),
            "policy_warning": "정책을 켜면 독립 검토자 없이 관계·release 가 승인됩니다(AUTO_POLICY로 표시·감사 기록). 현업 검토가 필요한 환경에서는 끄세요." if any(br["policy"][k] for k in ("auto_approve_relations", "auto_approve_release")) else None}


def _snapshot_of_inputs(pid):
    st = _st(pid)
    return {"brief": st["brief"], "sources": sorted(s["sha"] + s["name"] for s in _sources(pid))}


def approve(a, pid, b):
    ax._proj(a, pid, ("architect",))
    r = readiness(a, pid)
    if b.get("confirm") != CONFIRM:
        raise ApiError(400, "CONFIRM_REQUIRED", f"확인 문구 '{CONFIRM}' 를 정확히 입력해야 합니다.")
    if not r["ready"]:
        raise ApiError(409, "NOT_READY", "준비 점검을 모두 통과해야 승인할 수 있습니다.", checks=[x for x in r["checks"] if not x["ok"]])
    st = _st(pid)
    st["approval"] = {"by": a["user_id"], "at": _now(), "inputs_hash": _hash(_snapshot_of_inputs(pid)), "policy": st["brief"]["policy"]}
    ax.audit(a, "AX_AUTO_APPROVE", pid, detail={"policy": st["brief"]["policy"], "hash": st["approval"]["inputs_hash"]})
    ax._save()
    return st["approval"]


def status(a, pid):
    ax._proj(a, pid)
    st = _st(pid)
    return {"brief": st["brief"], "approval": st.get("approval"), "ack_texts": ACKS, "sources": len(_sources(pid)), "stages": STAGES,
            "jobs": [{k: v for k, v in j.items() if k not in ("actor",)} for j in ax.S["jobs"].values() if j["project_id"] == pid][-5:]}


# ------------------------------------------------------------------ 실행
def run(a, pid, b):
    p, _ = ax._proj(a, pid, ("architect",))
    st = _st(pid)
    ap = st.get("approval")
    if not ap or not st["brief"]:
        raise ApiError(403, "NOT_APPROVED", "사용자 승인이 없는 자동 구축은 시작하지 않습니다.")
    if ap["inputs_hash"] != _hash(_snapshot_of_inputs(pid)):
        st["approval"] = None
        raise ApiError(409, "APPROVAL_STALE", "승인 이후 입력(연결·정책·문서)이 바뀌어 승인이 무효가 되었습니다. 다시 승인하세요.")
    if any(j["state"] in ("RUNNING",) and j["project_id"] == pid for j in ax.S["jobs"].values()):
        raise ApiError(409, "JOB_RUNNING", "이미 실행 중인 자동 구축이 있습니다.")
    jid = "axj-" + hashlib.sha1(f"{pid}{time.time()}".encode()).hexdigest()[:8]
    job = {"job_id": jid, "project_id": pid, "state": "RUNNING", "started_at": _now(), "by": a["user_id"], "stages": [{"id": i, "label": l, "state": "PENDING"} for i, l in STAGES], "summary": {}, "actor": a}
    ax.S["jobs"][jid] = job
    ax.audit(a, "AX_AUTO_RUN", pid, jid)
    ax._save()
    if b.get("sync"):
        _execute(jid)
    else:
        threading.Thread(target=_execute, args=(jid,), daemon=True, name=jid).start()
    return _pub(job)


def _pub(j):
    return {k: v for k, v in j.items() if k != "actor"}


def job_get(a, pid, jid):
    ax._proj(a, pid)
    j = ax.S["jobs"].get(jid)
    if not j or j["project_id"] != pid:
        raise ApiError(404, "JOB_NOT_FOUND", "작업을 찾을 수 없습니다.")
    return _pub(j)


def job_cancel(a, pid, jid):
    ax._proj(a, pid, ("architect",))
    j = ax.S["jobs"].get(jid)
    if not j or j["project_id"] != pid:
        raise ApiError(404, "JOB_NOT_FOUND", "작업을 찾을 수 없습니다.")
    _CANCEL.add(jid)
    return {"ok": True, "note": "현재 단계가 끝나면 중단됩니다."}


def job_resume(a, pid, jid, sync=False):
    ax._proj(a, pid, ("architect",))
    j = ax.S["jobs"].get(jid)
    if not j or j["project_id"] != pid:
        raise ApiError(404, "JOB_NOT_FOUND", "작업을 찾을 수 없습니다.")
    if j["state"] not in ("FAILED", "PAUSED_FOR_REVIEW", "CANCELED"):
        raise ApiError(409, "BAD_STATE", f"{j['state']} 상태에서는 재개할 수 없습니다.")
    ap = _st(pid).get("approval")
    if not ap or ap["inputs_hash"] != _hash(_snapshot_of_inputs(pid)):
        raise ApiError(409, "APPROVAL_STALE", "승인이 없거나 입력이 바뀌었습니다. 다시 승인하세요.")
    j["state"], j["actor"] = "RUNNING", a
    _CANCEL.discard(jid)
    if sync:
        _execute(jid)
    else:
        threading.Thread(target=_execute, args=(jid,), daemon=True, name=jid).start()
    return _pub(j)


def _execute(jid):
    j = ax.S["jobs"][jid]
    a, pid = j["actor"], j["project_id"]
    ctx = j["summary"].setdefault("ctx", {})
    for s in j["stages"]:
        if s["state"] == "SUCCEEDED":
            continue
        if jid in _CANCEL:
            j["state"] = "CANCELED"
            s["state"] = "CANCELED"
            break
        s.update(state="RUNNING", started=_now(), error=None)
        try:
            lt = ops.snapshot_light()
            if lt["mem_percent"] >= 95:
                raise ApiError(409, "RESOURCE_CRITICAL", f"시스템 메모리 사용률 {lt['mem_percent']}% — 자원 부족으로 중단합니다(정리 후 재개 가능).")
            res = STAGE_FN[s["id"]](a, pid, ctx, j)
            s["detail"] = res.get("detail", res)
            s["state"] = res.get("state", "SUCCEEDED")
            s["finished"] = _now()
            if s["state"] == "AWAITING_REVIEW":
                j["state"] = "PAUSED_FOR_REVIEW"
                break
        except ApiError as e:
            s.update(state="FAILED", error={"code": e.code, "message": e.message[:300]}, finished=_now())
            j["state"] = "FAILED"
            break
        except Exception as e:  # noqa
            s.update(state="FAILED", error={"code": type(e).__name__, "message": str(e)[:200]}, finished=_now())
            j["state"] = "FAILED"
            break
    else:
        j["state"] = "COMPLETED"
    if j["state"] in ("COMPLETED", "PAUSED_FOR_REVIEW"):
        j["summary"]["report"] = _report(pid, ctx, j)
    j["finished_at"] = _now()
    ax.audit(a, "AX_AUTO_FINISH", pid, jid, j["state"])
    ax._save()


# ------------------------------------------------------------------ 단계
def _brief(pid):
    return _st(pid)["brief"]


def st_preflight(a, pid, ctx, j):
    r = ops.guard("auto_build")
    return {"detail": {"verdict": r["verdict"], "measured": r["measured"]}}


def st_connect(a, pid, ctx, j):
    t = ax.connector_test(a, pid, _brief(pid)["metadata_connector_id"])
    if not t["all_pass"]:
        raise ApiError(409, "CONNECTION_TEST_FAILED", "연결 테스트가 통과하지 못했습니다: " + ", ".join(f"{s['stage']}={s['status']}" for s in t["stages"] if s["status"] not in ("PASS", "SKIPPED")))
    return {"detail": {"stages": [s["stage"] + ":" + s["status"] for s in t["stages"]]}}


def st_scan(a, pid, ctx, j):
    b = _brief(pid)
    r = ax.scan(a, pid, {"connector_id": b["metadata_connector_id"], "dba_baseline_count": b.get("dba_baseline_count")})
    ctx["snapshot_id"] = r["snapshot_id"]
    return {"detail": {"snapshot_id": r["snapshot_id"], "tables": r["tables"], "views": r["views"], "coverage": r["coverage"]["completeness"], "warning": r["coverage"].get("warning")}}


def st_profile(a, pid, ctx, j):
    s = ax._snap(pid, ctx["snapshot_id"])
    ok = fail = 0
    for oid, o in list(s["objects"].items())[:80]:
        if o["kind"] != "table":
            continue
        try:
            ax.profile(a, pid, {"object_id": oid, "snapshot_id": s["snapshot_id"], "sample_rows": 500})
            ok += 1
        except ApiError:
            fail += 1
    ctx["profiled"] = ok
    return {"detail": {"profiled_tables": ok, "failed": fail, "basis": "표본(최대 500행) — 정확한 통계 아님"}}


def st_relations(a, pid, ctx, j):
    br = _brief(pid)["policy"]
    cands = ax.relation_infer(a, pid, {"snapshot_id": ctx["snapshot_id"]})["candidates"]
    auto, review = [], []
    for c in cands:
        ev = c["evidence"]
        if br["auto_approve_relations"] and ev["inclusion_rate"] >= br["rel_min_inclusion"] and ev["sample_rows"] >= br["rel_min_sample"]:
            c["status"], c["kind"] = "APPROVED_LOGICAL", "APPROVED_LOGICAL"
            c["reviews"].append({"by": f"AUTO_POLICY({a['user_id']})", "decision": "approve", "note": f"사용자 사전 승인 정책: 표본 포함률 {ev['inclusion_rate']}≥{br['rel_min_inclusion']}, 표본 {ev['sample_rows']}행≥{br['rel_min_sample']}", "at": _now()})
            c["revision"] += 1
            auto.append(c["relation_id"])
            ax.audit(a, "AX_RELATION_AUTO_APPROVE", pid, c["relation_id"], detail={"inclusion": ev["inclusion_rate"], "sample": ev["sample_rows"]})
        else:
            review.append(c["relation_id"])
    ctx["rel_auto"], ctx["rel_review"] = auto, review
    return {"detail": {"candidates": len(cands), "auto_approved": len(auto), "left_for_human_review": len(review), "policy": br,
                       "caution": "작은 표본의 우연한 일치 위험이 있습니다. 자동 승인 목록을 사람이 사후 확인하세요."}}


def st_docs(a, pid, ctx, j):
    br = _brief(pid)
    srcs = _sources(pid)
    n_docs = n_chunks = susp = skipped = 0
    for s in srcs:
        key = "src:" + hashlib.sha1(s["name"].encode()).hexdigest()[:8]
        prev = [d for d in ax.S["documents"].values() if d["project_id"] == pid and d["doc_key"] == key and d["status"] == "ACTIVE"]
        if prev and prev[0].get("sha") == s["sha"]:
            skipped += 1
            continue
        ver = (prev[0]["version"] + 1) if prev else 1
        d = ax_search.ingest(ax.S, a, pid, {"title": s["name"], "text": s["text"], "doc_key": key, "version": ver, "doc_type": "source", "tenant_id": br.get("tenant_id"),
                                            "acl": {"internal_only": br["doc_acl_internal_only"]}, "effective_from": datetime.now().strftime("%Y-%m-%d")})
        ax.S["documents"][d["doc_id"]]["sha"] = s["sha"]
        n_docs += 1; n_chunks += d["chunk_count"]; susp += d["suspicious_chunks"]
    ctx["docs"] = n_docs
    return {"detail": {"sources": len(srcs), "indexed_docs": n_docs, "chunks": n_chunks, "unchanged_skipped": skipped, "suspicious_chunks_flagged": susp, "embedding": ax_search.embed_mode(),
                       "note": "의심 구절은 색인에 남되 '데이터로만' 취급·경고 표시"}}


def _card(o, rels, prof, hit):
    fk = {c.lower(): f"{f['ref_table']}" for f in o["fks"] for c in f["columns"]}
    pr = {c["column"].lower(): c for c in (prof or {}).get("columns", [])}
    lines = [f"[자동 생성 초안 — 미검토] {o['kind']} {o['name']}", "", f"행 수(추정): {o['row_count'] if o['row_count'] is not None else '미확인'} ({o.get('row_count_basis') or '기준 없음'})", f"기본키: {', '.join(o['pk']) or '없음'}", ""]
    for c in o["columns"]:
        extra = []
        if c["name"] in o["pk"]:
            extra.append("PK")
        if c["name"].lower() in fk:
            extra.append("FK→" + fk[c["name"].lower()])
        p = pr.get(c["name"].lower())
        if p and p["null_ratio"]:
            extra.append(f"null {int(p['null_ratio'] * 100)}%")
        lines.append(f"- {c['name']} {c['type']}{' · ' + ' · '.join(extra) if extra else ''}{' — ' + c['comment'] if c.get('comment') else ''}")
    if rels:
        lines += ["", "관계: " + "; ".join(rels)]
    if hit:
        lines += ["", f"관련 문서(검색 1위): {hit}"]
    lines += ["", "주의: 이 설명은 이름·주석·표본으로 만든 추정입니다. 업무 의미는 현업 확인이 필요합니다."]
    return "\n".join(lines)


def st_cards(a, pid, ctx, j):
    s = ax._snap(pid, ctx["snapshot_id"])
    profs = {}
    for pr in ax.S["profiles"].values():
        if pr["project_id"] == pid and pr["snapshot_id"] == s["snapshot_id"]:
            profs[pr["object_id"]] = pr
    rel = ax.relations(a, pid, s["snapshot_id"])
    allr = [r for r in rel["declared"]] + [r for r in rel["logical"] if r["status"] == "APPROVED_LOGICAL"]
    m = ax._proj(a, pid)[1]
    made = 0
    for oid, o in list(s["objects"].items())[:60]:
        rs = [f"{r['from_table'].split('.')[-1]}({','.join(r['from_columns'])})→{r['to_table'].split('.')[-1]}" for r in allr if oid in (r["from_table"], r["to_table"])]
        hit = None
        try:
            h = ax_search.search(ax.S, pid, {"tenants": None, "customers": None, "suppliers": None}, o["name"].replace("_", " "), "hybrid", 1, datetime.now().strftime("%Y-%m-%d"))["results"]
            hit = f"{h[0]['title']} v{h[0]['version']}" if h and h[0]["doc_status"] == "ACTIVE" else None
        except ApiError:
            pass
        key = "kc:" + hashlib.sha1(oid.encode()).hexdigest()[:8]
        text = _card(o, rs, profs.get(oid), hit)
        sha = hashlib.sha256(text.encode()).hexdigest()[:16]
        prev = [d for d in ax.S["documents"].values() if d["project_id"] == pid and d["doc_key"] == key and d["status"] == "ACTIVE"]
        if prev and prev[0].get("sha") == sha:
            continue
        d = ax_search.ingest(ax.S, a, pid, {"title": f"지식 카드: {o['name']}", "text": text, "doc_key": key, "version": (prev[0]["version"] + 1) if prev else 1, "doc_type": "auto-knowledge", "acl": {"internal_only": True},
                                            "effective_from": datetime.now().strftime("%Y-%m-%d")})
        ax.S["documents"][d["doc_id"]]["sha"] = sha
        made += 1
    ctx["cards"] = made
    return {"detail": {"cards_created_or_updated": made, "note": "규칙 기반 초안이며 LLM 요약이 아닙니다. 색인되어 검색에 쓰이지만 '미검토' 표시를 유지합니다."}}


def _camel(n):
    return "".join(w.capitalize() for w in re.split(r"[^0-9A-Za-z]+", n) if w) or "Entity"


def gen_spec(s, rels):
    names = {o["name"].lower() for o in s["objects"].values() if o["kind"] == "table"}
    dist = {"party", "customer_role", "supplier_role", "product", "stock", "sales_orders", "contract", "supplier_item", "purchase_orders", "ar_ledger"}
    if dist <= names:
        return ax._template(s), "distribution 표준 템플릿(정책 8종 포함)"
    ents, used = [], set()
    for o in s["objects"].values():
        if o["kind"] != "table" or not o["pk"]:
            continue
        i = _camel(o["name"])
        while i in used:
            i += "2"
        used.add(i)
        ents.append({"id": i, "source_binding": o["object_id"], "key": list(o["pk"])})
    byb = {e["source_binding"].lower(): e for e in ents}
    out, seen = [], set()
    for r in rels:
        f, t = byb.get(r["from_table"].lower()), byb.get(r["to_table"].lower())
        if not f or not t or {c.lower() for c in r["from_columns"]} != {c.lower() for c in r["to_columns"]}:
            continue
        rid = f"{f['id']}_to_{t['id']}"
        if rid in seen:
            continue
        seen.add(rid)
        out.append({"id": rid, "from": f["id"], "to": t["id"], "join_keys": list(r["from_columns"])})
    return {"model_id": "auto_model", "entities": ents, "relations": out, "metrics": [], "policies": [],
            "competency_questions": [f"{e['id']} 한 건을 키로 조회하면 무엇이 나오는가?" for e in ents[:5]]}, "자동 생성 일반 모델(엔터티·관계만, 지표·정책 없음)"


def st_ontology(a, pid, ctx, j):
    br = _brief(pid)
    prev = ax.S["releases"].get(ctx.get("release_id", ""))
    if prev:                                   # 재개: 이미 만든 release 를 다시 만들지 않고 사람의 승인 여부만 확인
        if prev["status"] in ("APPROVED", "ACTIVE"):
            return {"detail": {"release_id": prev["release_id"], "approval": "사람 검토 승인(재개)" if prev.get("approval_mode") != "AUTO_BY_USER_POLICY" else "AUTO_BY_USER_POLICY"}}
        if prev["status"] == "VALIDATED":
            return {"state": "AWAITING_REVIEW", "detail": {"release_id": prev["release_id"], "approval": "아직 사람 검토 대기"}}
    s = ax._snap(pid, ctx["snapshot_id"])
    rel = ax.relations(a, pid, s["snapshot_id"])
    usable = rel["declared"] + [r for r in rel["logical"] if r["status"] == "APPROVED_LOGICAL"]
    spec, how = gen_spec(s, usable)
    if not spec["entities"]:
        raise ApiError(409, "NO_ENTITIES", "기본키가 있는 테이블이 없어 온톨로지를 만들 수 없습니다.")
    n = sum(1 for r in ax.S["releases"].values() if r["project_id"] == pid) + 1
    r = ax.release_create(a, pid, {"spec": spec, "snapshot_id": s["snapshot_id"], "version": f"0.{n}.0"})
    r["author"] = f"AUTO({a['user_id']})"
    ctx["release_id"] = r["release_id"]
    v = ax.release_validate(a, pid, r["release_id"])
    d = {"release_id": r["release_id"], "how": how, "entities": len(spec["entities"]), "relations": len(spec["relations"]), "validation_ok": v["ok"], "warnings": v["warnings"][:5]}
    if not v["ok"]:
        raise ApiError(409, "ONTOLOGY_INVALID", "생성한 온톨로지가 검증을 통과하지 못했습니다(강제 승인하지 않음): " + "; ".join(f"{e['code']}({e['target']})" for e in v["errors"][:5]))
    rr = ax.S["releases"][r["release_id"]]
    if br["policy"]["auto_approve_release"]:
        rr["status"], rr["approval_mode"] = "APPROVED", "AUTO_BY_USER_POLICY"
        rr["reviews"].append({"by": f"AUTO_POLICY({a['user_id']})", "decision": "approve", "note": "사용자 사전 승인 정책에 따른 자동 승인(독립 검토자 승인이 아님)", "at": _now()})
        rr["revision"] += 1
        ax.audit(a, "AX_ONTOLOGY_AUTO_APPROVE", pid, r["release_id"])
        d["approval"] = "AUTO_BY_USER_POLICY"
        return {"detail": d}
    d["approval"] = "사람 검토 대기(자동 승인 정책이 꺼져 있음)"
    return {"state": "AWAITING_REVIEW", "detail": d}


def st_pipeline(a, pid, ctx, j):
    plan = ax.compile_plan(a, pid, {"release_id": ctx["release_id"], "engine": "native"})
    run = ax.pipeline_run(a, pid, {"plan_id": plan["plan_id"]})
    if run["state"] != "SUCCEEDED":
        raise ApiError(409, "PIPELINE_FAILED", f"파이프라인 실패: {run.get('error') or [x for x in run['stages'] if x['state'] == 'FAILED']}")
    return {"detail": {"run_id": run["run_id"], "stages": {x["id"]: x["state"] for x in run["stages"]}, "elapsed_ms": run["elapsed_ms"]}}


def st_eval(a, pid, ctx, j):
    ev = ax.evaluate(a, pid, {})
    ctx["eval_id"] = ev["eval_id"]
    if not ev["gates_passed"]:
        raise ApiError(409, "EVAL_FAILED", "자동 평가 gate 를 통과하지 못했습니다: " + json.dumps([c for c in (ev.get("golden") or ev.get("generic"))["cases"] if not c["pass"]][:3], ensure_ascii=False)[:300])
    return {"detail": {"kind": ev.get("kind", "DISTRIBUTION_GOLDEN"), "gates_passed": True, "scope_note": ev["scope_note"]}}


def st_agent(a, pid, ctx, j):
    br = _brief(pid)
    rel = ax.S["releases"][ctx["release_id"]]
    e = rel["spec"]["entities"][0]
    smoke = {}
    cn = ax._src(pid)
    try:
        o = next(x for x in ax._snap(pid, ctx["snapshot_id"])["objects"].values() if x["object_id"].lower() == e["source_binding"].lower())
        row = cn.execute(f"SELECT {','.join(cn.q(k) for k in e['key'])} FROM {cn.qual(o['schema'], o['name'])} " + ("FETCH FIRST 1 ROWS ONLY" if cn.kind == "oracle" else "LIMIT 1")).fetchone()
    finally:
        cn.close()
    if row:
        r = ax.agent_run(a, pid, {"question_type": "entity_lookup", "entity": e["id"], "key": {k: (str(row[i]) if not isinstance(row[i], int) else row[i]) for i, k in enumerate(e["key"])}, "release_id": ctx["release_id"]})
        smoke = {"entity": e["id"], "verdict": r["result"]["verdict"]}
    d = {"smoke": smoke, "tools": ["entity_lookup", "entity_related"] + (["distribution 도구 8종"] if ax._policy(rel, "change_order_increase") else []), "llm": "없음(결정적 도구)"}
    if br["policy"]["allow_deploy"]:
        dep = ax.deploy(a, pid, {"release_id": ctx["release_id"]})
        d["deployed"] = dep["deployment_id"]
    else:
        d["deployed"] = "아니오 — 사용자가 '배포 허용'을 선택하지 않아 대기(수동 배포 가능)"
    return {"detail": d}


STAGE_FN = {"PREFLIGHT": st_preflight, "CONNECT": st_connect, "SCAN": st_scan, "PROFILE": st_profile, "RELATIONS": st_relations, "DOCS": st_docs, "CARDS": st_cards, "ONTOLOGY": st_ontology,
            "PIPELINE": st_pipeline, "EVAL": st_eval, "AGENT": st_agent}


def _report(pid, ctx, j):
    rel = ax.S["releases"].get(ctx.get("release_id", ""), {})
    return {"release": {"id": rel.get("release_id"), "status": rel.get("status"), "approval_mode": rel.get("approval_mode", "사람 검토 필요" if rel else None)},
            "auto_approved_relations": ctx.get("rel_auto", []), "relations_need_human_review": ctx.get("rel_review", []), "documents_indexed": ctx.get("docs", 0), "knowledge_cards": ctx.get("cards", 0),
            "what_is_not_verified": ["업무 정답(현업 golden)은 검증되지 않음 — 자동 평가는 구조·접근·검색 검사", "자동 승인된 관계·release 는 사람이 사후 확인해야 함", "지식 카드는 규칙 기반 추정 초안", "실제 LLM 없음(결정적 도구)", "원천 변경 업무 명령은 자동 실행하지 않음"],
            "next": "관계 후보 검토 → 현업 golden 세트 작성 → 필요 시 업무 도구(정책) 추가 → 배포"}


# ------------------------------------------------------------------ 일반 도메인 도구(승인된 엔터티·관계만)
def _ents(rel, snap):
    byo = {o["object_id"].lower(): o for o in snap["objects"].values()}
    return {e["id"].lower(): (e, byo.get(e["source_binding"].lower())) for e in rel["spec"]["entities"]}


def _keyvals(e, key):
    if not isinstance(key, dict) or {k.lower() for k in key} != {k.lower() for k in e["key"]}:
        raise ApiError(400, "BAD_KEY", f"key 는 정확히 {e['key']} 컬럼을 모두 가져야 합니다.")
    out = {}
    for k in e["key"]:
        v = next(val for kk, val in key.items() if kk.lower() == k.lower())
        if isinstance(v, bool) or not (isinstance(v, int) or (isinstance(v, str) and re.fullmatch(r"[A-Za-z0-9_\-\.가-힣 ]{1,60}", v))):
            raise ApiError(400, "BAD_KEY", "키 값 형식이 올바르지 않습니다.")
        out[k] = v
    return out


def _mask_row(o, row, names):
    out, masked = {}, []
    for c, v in zip(names, row):
        if MASK.search(c):
            out[c] = "***"
            masked.append(c)
        else:
            out[c] = ax._py(v)
    return out, masked


def generic_tool(a, pid, p, m, rel, qt, b):
    if not ax_tools.internal(m):
        raise ApiError(403, "INTERNAL_ONLY", "일반 도메인 도구는 내부 사용자 전용입니다.")
    snap = S_snap(pid, rel)
    ents = _ents(rel, snap)
    ent = ents.get(str(b.get("entity", "")).lower())
    if not ent or not ent[1]:
        raise ApiError(404, "ENTITY_NOT_IN_RELEASE", "승인된 release 에 없는 엔터티입니다(승인되지 않은 개념은 도구로 쓰지 않음).")
    e, o = ent
    extra = set(b) - {"question_type", "entity", "key", "relation", "release_id"}
    if extra:
        raise ApiError(400, "BAD_PARAM", f"허용되지 않은 입력: {sorted(extra)}")
    kv = _keyvals(e, b.get("key"))
    tcol = next((k for k in e["key"] if k.lower() == "tenant_id"), None)
    if tcol and m.get("tenants") is not None and kv[tcol] not in m["tenants"]:
        raise ApiError(403, "TENANT_SCOPE_DENIED", "접근 범위(tenant) 밖입니다.")
    cn = ax._src(pid)
    try:
        where = " AND ".join(f"{cn.q(k)}=?" for k in e["key"])
        params = tuple(kv[k] for k in e["key"])
        if qt == "entity_lookup":
            cols = [c["name"] for c in o["columns"]]
            cur = cn.execute(f"SELECT {','.join(cn.q(c) for c in cols)} FROM {cn.qual(o['schema'], o['name'])} WHERE {where}", params)
            r = cur.fetchone()
            if not r:
                out = {"verdict": "NOT_FOUND", "answer": "해당 키의 레코드가 없습니다. 추정하지 않고 담당자에게 이관합니다."}
            else:
                row, masked = _mask_row(o, list(r), cols)
                out = {"verdict": "FOUND", "detail": {"entity": e["id"], "key": kv, "row": row, "masked_columns": masked}, "answer": f"{e['id']} {kv} 레코드를 찾았습니다(민감 이름 컬럼은 가림)."}
        else:
            relid = b.get("relation")
            rl = next((x for x in rel["spec"]["relations"] if x["id"] == relid and x["from"].lower() == e["id"].lower()), None)
            if not rl:
                raise ApiError(404, "RELATION_NOT_IN_RELEASE", "승인된 release 에 없는 관계입니다.")
            te, to = ents[rl["to"].lower()]
            cols = [c["name"] for c in to["columns"]]
            on = " AND ".join(f"t.{cn.q(k)}=f.{cn.q(k)}" for k in rl["join_keys"])
            sql = f"SELECT {','.join('t.' + cn.q(c) for c in cols)} FROM {cn.qual(o['schema'], o['name'])} f JOIN {cn.qual(to['schema'], to['name'])} t ON {on} WHERE {' AND '.join('f.' + cn.q(k) + '=?' for k in e['key'])}"
            rows = cn.execute(cn.limit(sql, 20), params).fetchall()
            out = {"verdict": "FOUND" if rows else "NOT_FOUND", "detail": {"from": e["id"], "relation": relid, "to": rl["to"], "rows": [_mask_row(to, list(x), cols)[0] for x in rows], "limit": 20},
                   "answer": f"{relid}: {len(rows)}건(최대 20건, 1 hop)."}
    finally:
        cn.close()
    run = {"run_id": ax._id("axa"), "project_id": pid, "engine": p["engine"], "evidence_level": ax.EVIDENCE, "llm": "none(결정적 도구)", "ontology": f"{rel['model_id']}@{rel['version']}", "policy": "approved_entities_only@1",
           "tool": f"{qt}@1", "observed_at": _now(), "query_ids": [ax._qid(qt, (e["id"], str(sorted(kv.items()))))], "freshness": "실시간 원천 조회", "result": out, "by": a["user_id"], "tenant_id": kv.get(tcol)}
    ax.S["runs"][run["run_id"]] = run
    ax.audit(a, "AX_AGENT_RUN", pid, run["run_id"], out["verdict"], {"tool": qt})
    ax._save()
    return run


def S_snap(pid, rel):
    return ax.S["snapshots"][rel["snapshot_id"]]


def generic_eval(a, pid, rel, m):
    """구조·접근·검색 자동 평가(업무 정답 검증 아님)."""
    snap = S_snap(pid, rel)
    ents = _ents(rel, snap)
    cases, cn = [], ax._src(pid)
    try:
        for e, o in list(ents.values())[:30]:
            cid = f"L:{e['id']}"
            try:
                row = cn.execute(f"SELECT {','.join(cn.q(k) for k in e['key'])} FROM {cn.qual(o['schema'], o['name'])} " + ("FETCH FIRST 1 ROWS ONLY" if cn.kind == "oracle" else "LIMIT 1")).fetchone()
                if not row:
                    cases.append({"id": cid, "axis": "조회", "pass": True, "mismatch": {}, "note": "빈 테이블(조회 대상 없음)"})
                    continue
                key = {k: ax._py(row[i]) for i, k in enumerate(e["key"])}
                key = {k: (v if isinstance(v, int) else str(v)) for k, v in key.items()}
                r = generic_tool(a, pid, ax.S["projects"][pid], m, rel, "entity_lookup", {"entity": e["id"], "key": key})
                cases.append({"id": cid, "axis": "조회", "pass": r["result"]["verdict"] == "FOUND", "mismatch": {} if r["result"]["verdict"] == "FOUND" else {"verdict": r["result"]["verdict"]}})
                tc = next((k for k in e["key"] if k.lower() == "tenant_id"), None)
                if tc:
                    bad = dict(key); bad[tc] = "__none__"
                    rr = generic_tool(a, pid, ax.S["projects"][pid], m, rel, "entity_lookup", {"entity": e["id"], "key": bad})
                    cases.append({"id": f"T:{e['id']}", "axis": "tenant 분리", "pass": rr["result"]["verdict"] == "NOT_FOUND", "mismatch": {}})
                for rl in [x for x in rel["spec"]["relations"] if x["from"] == e["id"]][:3]:
                    rr = generic_tool(a, pid, ax.S["projects"][pid], m, rel, "entity_related", {"entity": e["id"], "key": key, "relation": rl["id"]})
                    cases.append({"id": f"R:{rl['id']}", "axis": "관계 탐색", "pass": rr["result"]["verdict"] in ("FOUND", "NOT_FOUND"), "mismatch": {}})
            except ApiError as ex:
                cases.append({"id": cid, "axis": "조회", "pass": False, "mismatch": {"error": ex.code}})
    finally:
        cn.close()
    docs = [d for d in ax.S["documents"].values() if d["project_id"] == pid and d["status"] == "ACTIVE" and d["doc_type"] == "source"]
    for d in docs[:5]:
        words = " ".join(d["chunks"][0]["text"].split()[:8])
        hit = ax_search.search(ax.S, pid, {"tenants": None, "customers": None, "suppliers": None}, words, "hybrid", 3, "9999-12-30")["results"] if len(words) >= 2 else []
        cases.append({"id": f"D:{d['title']}", "axis": "검색 자기 회수", "pass": any(h["doc_id"] == d["doc_id"] for h in hit), "mismatch": {}})
    p = sum(1 for c in cases if c["pass"])
    return {"cases": cases, "passed": p, "total": len(cases), "gates_passed": bool(cases) and p == len(cases)}
