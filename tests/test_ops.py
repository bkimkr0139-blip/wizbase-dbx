"""서버 자원 모니터링·작업 전 판단·승인형 정리 테스트."""
import os, tempfile, time, types
import pytest
from test_at import client, env, login  # noqa: F401
from backend import ops


def hi_mem(pct=97.0):
    gb = 1024 ** 3
    return lambda: types.SimpleNamespace(total=16 * gb, available=int(16 * gb * (100 - pct) / 100), used=int(16 * gb * pct / 100), percent=pct)


def test_resources_admin_only_and_complete(env):
    c = env["c"]
    for who in ("L", "R", "I"):
        assert c.get("/api/ops/resources", headers=env[who]).status_code == 403
    r = c.get("/api/ops/resources?top=5", headers=env["A"]).json()
    assert r["cpu"]["logical"] and len(r["cpu"]["per_core"]) == r["cpu"]["logical"] and 0 <= r["cpu"]["percent"] <= 100
    assert r["memory"]["total"] > r["memory"]["available"] > 0 and "swap_total" in r["memory"]
    assert r["disks"] and all(d["kind"] in ("SSD", "HDD", "미확인") and d["total"] >= d["used"] for d in r["disks"])
    assert r["physical_disks"] is not None and r["level"] in ("OK", "WARN", "CRITICAL")
    assert len(r["top_cpu"]) <= 5 and len(r["top_memory"]) <= 5 and r["top_memory"][0]["rss"] >= r["top_memory"][-1]["rss"]
    assert {"pid", "name", "cpu", "rss", "cmd", "role"} <= set(r["top_memory"][0])
    assert any(p["role"] == "this_server" for p in r["app_processes"]) and r["app"]["data_dir"] and r["by_name"]


def test_command_lines_are_masked():
    m = ops._mask(["python", "x.py", "--password", "hunter2", "--sim-token", "abc123", "api_key=zzz", "postgres://u:pw1234@host/db"])
    for secret in ("hunter2", "abc123", "zzz", "pw1234"):
        assert secret not in m
    assert "***" in m


def test_history_collects_samples(env):
    h = env["c"].get("/api/ops/history", headers=env["A"]).json()
    assert h and {"t", "cpu", "mem"} <= set(h[0])


def test_preflight_verdicts_and_guard(env, monkeypatch):
    c = env["c"]
    tasks = c.get("/api/ops/tasks", headers=env["A"]).json()
    assert {"auto_build", "pipeline", "real_db_tests", "full_tests", "embedding_neural"} <= set(tasks)
    ok = c.get("/api/ops/preflight/ax_scan", headers=env["A"]).json()
    assert ok["verdict"] in ("OK", "CAUTION", "BLOCK") and ok["thresholds"] and "경험적" in ok["note"]
    assert c.get("/api/ops/preflight/bogus", headers=env["A"]).status_code == 400
    assert c.get("/api/ops/preflight/ax_scan", headers=env["L"]).status_code == 403
    monkeypatch.setattr(ops.psutil, "virtual_memory", hi_mem(97.0))
    r = c.get("/api/ops/preflight/auto_build", headers=env["A"]).json()
    assert r["verdict"] == "BLOCK" and any("위험" in x["msg"] for x in r["reasons"]) and r["suggestions"]
    with pytest.raises(Exception) as e:
        ops.guard("auto_build")
    assert getattr(e.value, "code", "") == "RESOURCE_BLOCKED"
    monkeypatch.setattr(ops.psutil, "virtual_memory", hi_mem(88.0))
    assert c.get("/api/ops/preflight/ax_scan", headers=env["A"]).json()["verdict"] in ("CAUTION", "BLOCK")


def _old_dir(name):
    d = os.path.join(tempfile.gettempdir(), name)
    os.makedirs(d, exist_ok=True)
    open(os.path.join(d, "x.bin"), "wb").write(b"0" * 5000)
    old = time.time() - 3600
    os.utime(d, (old, old))
    return d


def test_cleanup_requires_plan_confirmation_and_only_touches_owned_items(env):
    c = env["c"]
    mine = _old_dir("dbxtest_ops_case1")
    decoy = _old_dir("dbx_real_run")                        # 증거 폴더(절대 후보가 되면 안 됨)
    fresh = os.path.join(tempfile.gettempdir(), "dbxtest_ops_fresh")
    os.makedirs(fresh, exist_ok=True)                      # 방금 만든 폴더(10분 미만)는 후보 제외
    try:
        assert c.post("/api/ops/cleanup/plan", headers=env["L"]).status_code == 403
        pl = c.post("/api/ops/cleanup/plan", headers=env["A"]).json()
        ids = {x["id"] for x in pl["candidates"].values()} if isinstance(pl["candidates"], dict) else {x["id"] for x in pl["candidates"]}
        assert "tmp:dbxtest_ops_case1" in ids and "tmp:dbx_real_run" not in ids and "tmp:dbxtest_ops_fresh" not in ids
        assert pl["confirm_phrase"] == "정리 승인" and any("증거" in n for n in pl["never_touched"])
        run = lambda body, who="A": c.post("/api/ops/cleanup/execute", headers=env[who], json=body)
        assert run({"plan_id": pl["plan_id"], "ids": ["tmp:dbxtest_ops_case1"], "confirm": "그냥 해"}).json()["error"]["code"] == "CONFIRM_REQUIRED"
        assert os.path.exists(mine)                                                       # 승인 문구 없으면 삭제하지 않음
        assert run({"plan_id": pl["plan_id"], "ids": [], "confirm": "정리 승인"}).json()["error"]["code"] == "NOTHING_SELECTED"
        A2 = login(c, "admin", "adm2", "A-test-code")
        env["A2"] = A2
        assert run({"plan_id": pl["plan_id"], "ids": ["tmp:dbxtest_ops_case1"], "confirm": "정리 승인"}, "A2").status_code in (403,)   # 계획을 만든 관리자만 승인
        out = run({"plan_id": pl["plan_id"], "ids": ["tmp:dbxtest_ops_case1", "tmp:dbx_real_run", "docker:wzax-nothing"], "confirm": "정리 승인"}).json()
        res = {r["id"]: r for r in out["results"]}
        assert res["tmp:dbxtest_ops_case1"]["ok"] and not os.path.exists(mine) and out["freed_bytes"] >= 5000
        assert not res["tmp:dbx_real_run"]["ok"] and os.path.exists(decoy)                # 계획에 없는 항목은 거부, 증거 폴더 보존
        assert not res["docker:wzax-nothing"]["ok"]
        assert run({"plan_id": pl["plan_id"], "ids": ["tmp:x"], "confirm": "정리 승인"}).status_code == 404   # 계획은 1회용
        au = c.get("/api/ops/cleanup/audit", headers=env["A"]).json()
        assert au and au[-1]["selected"] and au[-1]["freed"] >= 5000
    finally:
        import shutil
        for d in (mine, decoy, fresh):
            shutil.rmtree(d, ignore_errors=True)


def test_cleanup_revalidates_before_acting(env):
    d = _old_dir("dbxtest_ops_case2")
    try:
        pl = ops.plan_create({"user_id": "adm-test"})
        cand = pl["candidates"] if isinstance(pl["candidates"], dict) else {x["id"]: x for x in pl["candidates"]}
        assert "tmp:dbxtest_ops_case2" in cand
        other = os.path.join(tempfile.gettempdir(), "keepme_ops_case2")      # 패턴에 맞지 않는 무해한 폴더(시험이 직접 만든 것)
        os.makedirs(other, exist_ok=True)
        open(os.path.join(other, "keep.txt"), "w").write("keep")
        ops.PLANS[pl["plan_id"]]["candidates"]["tmp:dbxtest_ops_case2"]["path"] = other   # 계획이 변조돼 다른 폴더를 가리켜도
        r = ops.plan_execute({"user_id": "adm-test"}, pl["plan_id"], ["tmp:dbxtest_ops_case2"], "정리 승인")
        assert r["results"][0]["ok"] is False and os.path.exists(os.path.join(other, "keep.txt"))      # 재검증에서 거부
    finally:
        import shutil
        shutil.rmtree(d, ignore_errors=True)
        shutil.rmtree(os.path.join(tempfile.gettempdir(), "keepme_ops_case2"), ignore_errors=True)
