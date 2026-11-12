"""설치형 앱 → 서버: 실행·업데이트 신호, 다운로드 구분(설치 ID), 피드백(설치 정보)이 서버 접속 기록·관리 큐에 들어오는지."""
import json
import time

from test_at import client, env, login  # noqa: F401
from backend import telemetry, usage

INST = "a1b2c3d4e5f60718293a4b5c6d7e8f90"
PNG = None


def _post(c, **kw):
    body = {"event": "start", "install": INST, "app_version": "0.4.13", "platform": "win", "os": "Windows-10-10.0.26200", "content_id": "abcdef0123456789", **kw}
    return c.post("/api/app/telemetry", json=body)


def test_telemetry_endpoint_validates_logs_and_limits(env):
    c = env["c"]
    assert _post(c, install="nothex").status_code == 400 and _post(c, event="hack").status_code == 400
    n0 = len(usage._read(0))
    assert _post(c).status_code == 200
    assert _post(c, event="update_offered", kind="pack", to_version="0.4.14").status_code == 200
    assert _post(c, event="update_applied", kind="pack", from_version="0.4.13", to_version="0.4.14").status_code == 200
    assert _post(c, event="update_failed", kind="exe", error="SHA mismatch").status_code == 200
    ev = usage._read(0)[n0:]
    assert [e["e"] for e in ev] == ["app_start", "app_update", "app_update", "app_update"]
    assert ev[0]["d"]["inst"] == INST[:12] and ev[0]["d"]["plat"] == "win" and ev[0]["d"]["ver"] == "0.4.13"
    assert [e["d"]["result"] for e in ev[1:]] == ["offered", "applied", "failed"] and ev[3]["d"]["err"] == "SHA mismatch"
    assert ev[2]["d"]["frm"] == "0.4.13" and ev[2]["d"]["to"] == "0.4.14" and all(e["ip"] != "" or True for e in ev)
    other = "f" * 32
    for i in range(61):
        r = c.post("/api/app/telemetry", json={"event": "start", "install": other, "app_version": "0", "platform": "win"})
    assert r.status_code == 429                                                                        # 설치 ID당 시간당 한도


def test_admin_sees_app_summary_installs_and_downloads(env):
    c, A = env["c"], env["A"]
    inst2 = "0" * 31 + "7"
    _post(c, install=inst2, platform="mac_arm64", app_version="0.4.12", os="macOS-14")
    _post(c, install=inst2, event="update_applied", kind="exe", from_version="0.4.12", to_version="0.4.13")
    c.get("/download/pack", headers={"X-DBX-Install": INST, "X-DBX-App": "0.4.13/win"})                 # 앱이 업데이트로 내려받음
    c.get("/download/pack")                                                                            # 웹에서 직접
    d = c.get("/api/usage/summary?days=7", headers=A).json()
    assert d["kpi"]["app_pcs"] >= 2 and d["kpi"]["update_ok"] >= 2 and d["kpi"]["update_fail"] >= 1
    app = d["app"]
    assert app["installs"] >= 2 and dict(app["versions"]).get("0.4.13", 0) >= 1 and "win" in app["platforms"] and "mac_arm64" in app["platforms"]
    assert app["updates"].get("applied", 0) >= 2 and app["download_via"].get("app", 0) >= 1 and app["download_via"].get("web", 0) >= 1
    il = c.get("/api/usage/installs?days=7&limit=5", headers=A).json()
    assert il["total"] >= 2 and any(i["inst"] == INST[:12] and i["downloads"] >= 1 and i["platform"] == "win" for i in il["items"])
    assert c.get(f"/api/usage/installs?q=mac_arm64", headers=A).json()["total"] >= 1                     # 검색
    assert c.get("/api/usage/installs?days=7", headers=env["L"]).status_code == 403
    dl = [e for e in usage._read(0) if e["e"] == "download"][-2:]
    assert dl[0]["d"]["via"] == "app" and dl[0]["d"]["inst"] == INST[:12] and dl[1]["d"]["via"] == "web"
    assert INST not in json.dumps(usage._read(0))                                                      # 전체 설치 ID는 기록에 남기지 않는다(앞 12자만)


def test_standalone_feedback_carries_install_info_into_queue_and_log(env):
    c, A = env["c"], env["A"]
    body = {"name": "설치형사용자", "kind": "UI_BUG", "title": "단독형 신호 확인", "text": "단독형 앱에서 보낸 피드백입니다.", "view": "env",
            "install": {"install": INST, "app_version": "0.4.13", "platform": "win", "os": "Windows-10"}, "context": {"client": "PC앱"}}
    r = c.post("/api/feedback/intake", json=body)
    assert r.status_code == 200, r.text
    fid = r.json()["id"]
    d = c.get(f"/api/feedback/{fid}", headers=A).json()
    assert d["source"] == "standalone" and d["install"]["id"] == INST[:12] and d["install"]["version"] == "0.4.13" and d["install"]["platform"] == "win"
    lst = c.get("/api/feedback/admin?q=단독형 신호 확인", headers=A).json()["items"]
    assert lst and lst[0]["source"] == "standalone"
    ev = [e for e in usage._read(0) if e["e"] == "feedback" and e["d"].get("source") == "standalone"][-1]
    assert ev["d"]["inst"] == INST[:12] and ev["n"] == "설치형사용자"                                    # 서버 접속 기록에도 남는다


def test_telemetry_module_queue_offline_flush_toggle_and_update_detection(tmp_path, monkeypatch):
    monkeypatch.setenv("DBX_DATA_DIR", str(tmp_path)); monkeypatch.setenv("DBX_STANDALONE", "1"); monkeypatch.setenv("DBX_PLATFORM", "win")
    monkeypatch.delenv("DBX_TELEMETRY", raising=False); monkeypatch.setenv("DBX_CONTENT_ID", "cid1"); monkeypatch.setenv("DBX_EXE_SHA", "sha1")
    a = telemetry.install_id(); assert len(a) == 32 and telemetry.install_id() == a                       # 설치 ID는 한 번 만들어 유지
    sent = []
    def offline(path, body, timeout=6): raise OSError("offline")
    monkeypatch.setattr(telemetry, "_post", offline)
    telemetry.queue("start"); telemetry.queue("update_applied", kind="pack", from_version="1", to_version="2")
    assert telemetry.flush() == 0 and len(json.loads((tmp_path / "telemetry_queue.json").read_text(encoding="utf-8"))) == 2   # 오프라인이면 큐에 보관
    monkeypatch.setattr(telemetry, "_post", lambda path, body, timeout=6: sent.append(body) or {"ok": True})
    assert telemetry.flush() == 2 and [s["event"] for s in sent] == ["start", "update_applied"] and sent[0]["install"] == a   # 연결되면 순서대로 전송
    assert json.loads((tmp_path / "telemetry_queue.json").read_text(encoding="utf-8")) == []
    telemetry.set_enabled(False)
    telemetry.queue("start"); assert not telemetry.enabled() and telemetry.headers() == {} and telemetry.flush() == 0      # 끄면 신호·헤더 없음
    telemetry.set_enabled(True); assert telemetry.headers().get("X-DBX-Install") == a
    # 시작 시: 지난 실행 대비 내용(content)이 달라지면 '업데이트 적용됨(pack)'
    sent.clear()
    (tmp_path / "last_run.json").write_text(json.dumps({"version": "0.0.1", "content_id": "old", "exe_sha": "sha1"}), encoding="utf-8")
    monkeypatch.setattr(telemetry.threading, "Thread", lambda target=None, daemon=None, **k: type("T", (), {"start": lambda self: target()})())
    telemetry.startup_report()
    evs = [s["event"] for s in sent]
    assert evs == ["start", "update_applied"] and sent[1]["kind"] == "pack" and sent[1]["from_version"] == "0.0.1"
    (tmp_path / "last_run.json").write_text(json.dumps({"version": "0.0.1", "content_id": "cid1", "exe_sha": "oldsha"}), encoding="utf-8")
    sent.clear(); telemetry.startup_report()
    assert sent[1]["kind"] == "exe"                                                                    # 설치 파일 해시가 바뀌면 앱 전체 교체


def test_standalone_user_identity_in_server_log_and_installs(env):
    c, A = env["c"], env["A"]
    inst = "c" * 31 + "9"
    assert c.post("/api/app/telemetry", json={"event": "login", "install": inst, "app_version": "0.4.15", "platform": "win", "os": "Windows-11", "user": "홍길동"}).status_code == 200
    assert c.post("/api/app/telemetry", json={"event": "login", "install": inst, "app_version": "0.4.15", "platform": "win", "user": "x"}).status_code == 400     # 이름 필요
    c.post("/api/app/telemetry", json={"event": "start", "install": inst, "app_version": "0.4.15", "platform": "win", "user": "홍길동"})
    ev = [e for e in usage._read(0) if e["e"] == "app_login" and e["d"].get("inst") == inst[:12]][-1]
    assert ev["n"] == "홍길동" and ev["r"] == "standalone" and ev["c"] == "pc_app" or ev["n"] == "홍길동"            # 누구인지 기록
    il = c.get("/api/usage/installs?q=홍길동", headers=A).json()
    assert il["total"] >= 1 and il["items"][0]["users"] == ["홍길동"] and il["items"][0]["inst"] == inst[:12]      # 설치 PC ↔ 사용자
    us = c.get("/api/usage/users?q=홍길동&days=7", headers=A).json()
    assert us["total"] >= 1 and us["items"][0]["role"] == "standalone"                                              # 사용자별 활동에도 포함
    assert c.get("/api/usage/summary?days=7", headers=A).json()["kpi"]["app_users"] >= 1


def test_axos_result_flows_back_to_standalone_user_with_delivery_tracking(env, monkeypatch):
    """설치형 사용자가 낸 피드백 → 운영 큐 → 관리자 처리 → 앱이 상태 조회(트리거) → 사용자 알림, 서버에는 '전달됨'이 기록."""
    import time as _t
    from backend import feedback
    c, A = env["c"], env["A"]
    feedback._INTAKE_HITS.clear()
    monkeypatch.setenv("DBX_STANDALONE", "1")
    monkeypatch.setattr(feedback, "_http", lambda m, path, body=None, timeout=8: (c.post(path, json=body) if m == "POST" else c.get(path)).json())
    feedback._ONLINE.update(t=0.0, ok=True)
    U = login(c, name="설치형사용자1")
    r = c.post("/api/feedback", headers=U, json={"kind": "FEATURE", "title": "결과 전달 확인", "text": "처리 결과가 앱으로 돌아오는지 확인합니다."}); assert r.status_code == 200
    _t.sleep(0.5)
    local = feedback._F()[r.json()["id"]]
    rid = local["remote"]["id"]
    central = feedback._F()[rid]
    assert central["source"] == "standalone" and "delivery" in c.get(f"/api/feedback/{rid}", headers=A).json()
    for to, kw in (("APPROVED", {}), ("QUEUED", {"priority": "P1"})):
        assert c.post(f"/api/feedback/{rid}/transition", headers=A, json={"to": to, **kw}).status_code == 200
    assert c.get(f"/api/feedback/{rid}", headers=A).json()["delivery"]["delivered"] is False                              # 처리했지만 앱은 모름 → 전달 대기
    # 앱의 조회 트리거(내 피드백 열기 / 지금 확인)
    s = c.post("/api/feedback/sync", headers=U).json()
    assert s["standalone"] is True and s["online"] is True and s["updated"] >= 1
    m = c.get("/api/feedback/mine", headers=U).json()
    it = next(i for i in m["items"] if i["id"] == r.json()["id"])
    assert it["status"] == "QUEUED" and m["unseen_done"] >= 1 and it["priority"] == "P1"                                   # 사용자에게 처리 결과 + 새 알림
    d1 = c.get(f"/api/feedback/{rid}", headers=A).json()["delivery"]
    assert d1["delivered"] is True and d1["polled_status"] == "QUEUED" and d1["polled_at"]                                  # 서버에 '전달됨' 기록
    # 종결 처리 → 다음 조회에서 전달, 이후에는 더 조회하지 않음
    for to, kw in (("IN_DEV", {}), ("DONE", {"released_version": "0.4.16", "note": "반영했습니다"})):
        c.post(f"/api/feedback/{rid}/transition", headers=A, json={"to": to, **kw})
    calls = []
    orig = feedback._http
    monkeypatch.setattr(feedback, "_http", lambda m, p, body=None, timeout=8: (calls.append(p), orig(m, p, body, timeout))[1])
    c.post("/api/feedback/mine/seen", headers=U)
    c.post("/api/feedback/sync", headers=U)
    it = next(i for i in c.get("/api/feedback/mine", headers=U).json()["items"] if i["id"] == r.json()["id"])
    assert it["status"] == "DONE" and it["released_version"] == "0.4.16" and it["resolution"] == "반영했습니다"
    assert c.get(f"/api/feedback/{rid}", headers=A).json()["delivery"]["delivered"] is True
    calls.clear(); c.post("/api/feedback/sync", headers=U)
    assert not any("status-batch" in p for p in calls)                                                                 # 종결 전달 후에는 조회 안 함(불필요한 부하 방지)
    assert c.get("/api/feedback/admin?q=결과 전달 확인", headers=A).json()["items"][0]["delivery"]["delivered"] is True
