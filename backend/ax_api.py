"""AX 프로젝트 스튜디오 API (/api/ax/...). 모든 조회·변경에 서버 권한 검사(ax._proj)."""
from __future__ import annotations
from typing import Optional

from fastapi import Body, Header

from . import ax, ax_auto, ops


def register(app, A):
    import os
    if os.environ.get("DBX_NO_OPS_WARM") != "1":
        ops.warm()
    def ep(method, path):
        return getattr(app, method)("/api/ax" + path)

    @ep("get", "/support")
    def support(authorization: Optional[str] = Header(None)):
        A(authorization)
        return ax.capabilities(None)

    @ep("get", "/projects")
    def plist(authorization: Optional[str] = Header(None)):
        return ax.project_list(A(authorization))

    @ep("post", "/projects")
    def pcreate(b: dict = Body(...), authorization: Optional[str] = Header(None)):
        return ax.project_create(A(authorization), b)

    @ep("post", "/projects/{pid}/members")
    def pmember(pid: str, b: dict = Body(...), authorization: Optional[str] = Header(None)):
        return ax.member_set(A(authorization), pid, b)

    @ep("delete", "/projects/{pid}/members/{uid}")
    def pmember_del(pid: str, uid: str, authorization: Optional[str] = Header(None)):
        return ax.member_remove(A(authorization), pid, uid)

    @ep("post", "/projects/{pid}/connections")
    def conn_create(pid: str, b: dict = Body(...), authorization: Optional[str] = Header(None)):
        return ax.connector_create(A(authorization), pid, b)

    @ep("get", "/projects/{pid}/connections")
    def conn_list(pid: str, authorization: Optional[str] = Header(None)):
        a = A(authorization)
        ax._proj(a, pid)
        return [c for c in ax.S["connectors"].values() if c["project_id"] == pid]

    @ep("post", "/projects/{pid}/connections/{cid}/test")
    def conn_test(pid: str, cid: str, authorization: Optional[str] = Header(None)):
        return ax.connector_test(A(authorization), pid, cid)

    @ep("post", "/projects/{pid}/scans")
    def scan(pid: str, b: dict = Body(...), authorization: Optional[str] = Header(None)):
        return ax.scan(A(authorization), pid, b)

    @ep("get", "/projects/{pid}/snapshots")
    def snaps(pid: str, authorization: Optional[str] = Header(None)):
        return ax.snapshots(A(authorization), pid)

    @ep("get", "/projects/{pid}/inventory")
    def inv(pid: str, snapshot_id: Optional[str] = None, q: str = "", authorization: Optional[str] = Header(None)):
        return ax.inventory(A(authorization), pid, snapshot_id, q)

    @ep("get", "/projects/{pid}/diff")
    def diff(pid: str, old: str, new: str, authorization: Optional[str] = Header(None)):
        return ax.diff(A(authorization), pid, old, new)

    @ep("get", "/projects/{pid}/erd/subgraphs")
    def erd(pid: str, snapshot_id: Optional[str] = None, focus: str = "", hops: int = 1, q: str = "", collapse: bool = False, authorization: Optional[str] = Header(None)):
        return ax.erd(A(authorization), pid, snapshot_id, focus, hops, q, collapse)

    @ep("get", "/projects/{pid}/relations")
    def rels(pid: str, snapshot_id: Optional[str] = None, authorization: Optional[str] = Header(None)):
        return ax.relations(A(authorization), pid, snapshot_id)

    @ep("post", "/projects/{pid}/relation-candidates")
    def rel_infer(pid: str, b: dict = Body({}), authorization: Optional[str] = Header(None)):
        return ax.relation_infer(A(authorization), pid, b)

    @ep("post", "/projects/{pid}/relation-reviews")
    def rel_review(pid: str, b: dict = Body(...), authorization: Optional[str] = Header(None)):
        return ax.relation_review(A(authorization), pid, b)

    @ep("post", "/projects/{pid}/profiles")
    def prof(pid: str, b: dict = Body(...), authorization: Optional[str] = Header(None)):
        return ax.profile(A(authorization), pid, b)

    @ep("post", "/projects/{pid}/issues")
    def issue(pid: str, b: dict = Body(...), authorization: Optional[str] = Header(None)):
        return ax.issue_add(A(authorization), pid, b)

    @ep("get", "/projects/{pid}/ontology-releases")
    def rel_list(pid: str, authorization: Optional[str] = Header(None)):
        return ax.release_list(A(authorization), pid)

    @ep("post", "/projects/{pid}/ontology-releases")
    def rel_create(pid: str, b: dict = Body(...), authorization: Optional[str] = Header(None)):
        return ax.release_create(A(authorization), pid, b)

    @ep("get", "/projects/{pid}/ontology-releases/{rid}")
    def rel_get(pid: str, rid: str, authorization: Optional[str] = Header(None)):
        return ax.release_get(A(authorization), pid, rid)

    @ep("post", "/projects/{pid}/ontology-releases/{rid}/validate")
    def rel_validate(pid: str, rid: str, authorization: Optional[str] = Header(None)):
        return ax.release_validate(A(authorization), pid, rid)

    @ep("post", "/projects/{pid}/ontology-releases/{rid}/review")
    def rel_review2(pid: str, rid: str, b: dict = Body(...), authorization: Optional[str] = Header(None)):
        return ax.release_review(A(authorization), pid, rid, b)

    @ep("post", "/projects/{pid}/compilations")
    def comp(pid: str, b: dict = Body(...), authorization: Optional[str] = Header(None)):
        return ax.compile_plan(A(authorization), pid, b)

    @ep("post", "/projects/{pid}/pipeline-runs")
    def prun(pid: str, b: dict = Body(...), authorization: Optional[str] = Header(None)):
        return ax.pipeline_run(A(authorization), pid, b)

    @ep("post", "/projects/{pid}/agent-runs")
    def arun(pid: str, b: dict = Body(...), authorization: Optional[str] = Header(None)):
        return ax.agent_run(A(authorization), pid, b)

    @ep("get", "/projects/{pid}/proposals")
    def props(pid: str, authorization: Optional[str] = Header(None)):
        return ax.proposals(A(authorization), pid)

    @ep("post", "/projects/{pid}/proposals")
    def prop(pid: str, b: dict = Body(...), authorization: Optional[str] = Header(None)):
        return ax.proposal_create(A(authorization), pid, b)

    @ep("post", "/projects/{pid}/approvals")
    def appr(pid: str, b: dict = Body(...), authorization: Optional[str] = Header(None)):
        return ax.approval_create(A(authorization), pid, b)

    @ep("post", "/projects/{pid}/commands")
    def cmd(pid: str, b: dict = Body(...), authorization: Optional[str] = Header(None)):
        return ax.command_exec(A(authorization), pid, b)

    @ep("get", "/projects/{pid}/commands/{key}")
    def cmd_status(pid: str, key: str, authorization: Optional[str] = Header(None)):
        return ax.command_status(A(authorization), pid, key)

    @ep("post", "/projects/{pid}/evaluations")
    def evalr(pid: str, b: dict = Body({}), authorization: Optional[str] = Header(None)):
        return ax.evaluate(A(authorization), pid, b)

    @ep("post", "/projects/{pid}/deployments")
    def dep(pid: str, b: dict = Body(...), authorization: Optional[str] = Header(None)):
        return ax.deploy(A(authorization), pid, b)

    @ep("post", "/projects/{pid}/rollback")
    def rb(pid: str, authorization: Optional[str] = Header(None)):
        return ax.rollback(A(authorization), pid)

    @ep("get", "/projects/{pid}/export")
    def exp(pid: str, authorization: Optional[str] = Header(None)):
        return ax.export_project(A(authorization), pid)

    @ep("get", "/projects/{pid}/audit")
    def aud(pid: str, authorization: Optional[str] = Header(None)):
        return ax.audit_list(A(authorization), pid)

    @ep("get", "/projects/{pid}/tools")
    def tools(pid: str, authorization: Optional[str] = Header(None)):
        return ax.tool_contracts(A(authorization), pid)

    @ep("post", "/projects/{pid}/documents")
    def doc_add(pid: str, b: dict = Body(...), authorization: Optional[str] = Header(None)):
        return ax.doc_add(A(authorization), pid, b)

    @ep("post", "/projects/{pid}/documents/demo")
    def doc_demo(pid: str, authorization: Optional[str] = Header(None)):
        return ax.doc_seed_demo(A(authorization), pid)

    @ep("get", "/projects/{pid}/documents")
    def doc_list(pid: str, authorization: Optional[str] = Header(None)):
        return ax.doc_list(A(authorization), pid)

    @ep("get", "/projects/{pid}/search")
    def search(pid: str, q: str, mode: str = "hybrid", k: int = 5, as_of: Optional[str] = None, rerank: bool = False, include_old: bool = False, authorization: Optional[str] = Header(None)):
        return ax.doc_search(A(authorization), pid, q, mode, k, as_of, rerank, include_old)

    @ep("post", "/projects/{pid}/search-evaluations")
    def search_eval(pid: str, authorization: Optional[str] = Header(None)):
        return ax.doc_eval(A(authorization), pid)

    @ep("post", "/projects/{pid}/signals/scan")
    def sig_scan(pid: str, b: dict = Body({}), authorization: Optional[str] = Header(None)):
        return ax.signals_scan(A(authorization), pid, b)

    @ep("get", "/projects/{pid}/signals")
    def sig_list(pid: str, authorization: Optional[str] = Header(None)):
        return ax.signals_list(A(authorization), pid)

    @ep("post", "/projects/{pid}/signals/{sid}/ack")
    def sig_ack(pid: str, sid: str, b: dict = Body(...), authorization: Optional[str] = Header(None)):
        return ax.signal_ack(A(authorization), pid, sid, b)


    # ---- 자동 구축(사용자 사전 승인 기반)
    @ep("get", "/projects/{pid}/auto")
    def auto_status(pid: str, authorization: Optional[str] = Header(None)):
        return ax_auto.status(A(authorization), pid)

    @ep("post", "/projects/{pid}/auto/brief")
    def auto_brief(pid: str, b: dict = Body(...), authorization: Optional[str] = Header(None)):
        return ax_auto.brief_set(A(authorization), pid, b)

    @ep("get", "/projects/{pid}/auto/readiness")
    def auto_ready(pid: str, authorization: Optional[str] = Header(None)):
        return ax_auto.readiness(A(authorization), pid)

    @ep("post", "/projects/{pid}/auto/approve")
    def auto_approve(pid: str, b: dict = Body(...), authorization: Optional[str] = Header(None)):
        return ax_auto.approve(A(authorization), pid, b)

    @ep("post", "/projects/{pid}/auto/run")
    def auto_run(pid: str, b: dict = Body({}), authorization: Optional[str] = Header(None)):
        return ax_auto.run(A(authorization), pid, b)

    @ep("get", "/projects/{pid}/auto/jobs/{jid}")
    def auto_job(pid: str, jid: str, authorization: Optional[str] = Header(None)):
        return ax_auto.job_get(A(authorization), pid, jid)

    @ep("post", "/projects/{pid}/auto/jobs/{jid}/cancel")
    def auto_cancel(pid: str, jid: str, authorization: Optional[str] = Header(None)):
        return ax_auto.job_cancel(A(authorization), pid, jid)

    @ep("post", "/projects/{pid}/auto/jobs/{jid}/resume")
    def auto_resume(pid: str, jid: str, b: dict = Body({}), authorization: Optional[str] = Header(None)):
        return ax_auto.job_resume(A(authorization), pid, jid, bool(b.get("sync")))

    @ep("get", "/projects/{pid}/auto/sources")
    def src_list(pid: str, authorization: Optional[str] = Header(None)):
        return ax_auto.source_list(A(authorization), pid)

    @ep("post", "/projects/{pid}/auto/sources")
    def src_add(pid: str, b: dict = Body(...), authorization: Optional[str] = Header(None)):
        return ax_auto.source_add(A(authorization), pid, b)

    @ep("post", "/projects/{pid}/auto/sources/folder")
    def src_folder(pid: str, b: dict = Body(...), authorization: Optional[str] = Header(None)):
        return ax_auto.source_folder(A(authorization), pid, b)

    @ep("delete", "/projects/{pid}/auto/sources/{sid}")
    def src_del(pid: str, sid: str, authorization: Optional[str] = Header(None)):
        return ax_auto.source_delete(A(authorization), pid, sid)

    # ---- 서버 자원(관리자 전용)
    def adm(a):
        if a["role"] != "admin":
            from .core import ApiError
            raise ApiError(403, "ADMIN_ONLY", "서버 자원 관리는 관리자(admin) 전용입니다.")
        return a

    @app.get("/api/ops/resources")
    def ops_res(top: int = 12, fresh: bool = False, authorization: Optional[str] = Header(None)):
        adm(A(authorization))
        return ops.snapshot(max(3, min(top, 30)), fresh)

    @app.get("/api/ops/live")
    def ops_live(authorization: Optional[str] = Header(None)):
        adm(A(authorization))
        return ops.live()

    @app.get("/api/ops/history")
    def ops_hist(authorization: Optional[str] = Header(None)):
        adm(A(authorization))
        return ops.history()

    @app.get("/api/ops/preflight/{task}")
    def ops_pre(task: str, authorization: Optional[str] = Header(None)):
        adm(A(authorization))
        return ops.preflight(task)

    @app.get("/api/ops/tasks")
    def ops_tasks(authorization: Optional[str] = Header(None)):
        adm(A(authorization))
        return {k: {"label": v[0], "mem_gb": v[1], "cpu_max": v[2], "disk_gb": v[3]} for k, v in ops.TASKS.items()}

    @app.post("/api/ops/cleanup/plan")
    def ops_plan(authorization: Optional[str] = Header(None)):
        return ops.plan_create(adm(A(authorization)))

    @app.post("/api/ops/cleanup/execute")
    def ops_exec(b: dict = Body(...), authorization: Optional[str] = Header(None)):
        return ops.plan_execute(adm(A(authorization)), b.get("plan_id", ""), b.get("ids") or [], b.get("confirm", ""))

    @app.get("/api/ops/cleanup/audit")
    def ops_audit(authorization: Optional[str] = Header(None)):
        adm(A(authorization))
        return ops.audit_list()
