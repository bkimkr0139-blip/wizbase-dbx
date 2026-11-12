"""단독 설치형 앱: 중앙 서버 연계(피드백 접수·상태 반영)와 업데이트 판정."""
import time
from test_at import client, env, login  # noqa: F401
from backend import feedback, sysinfo

PNG = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="


def test_central_intake_and_receipt(env):
    c = env["c"]
    feedback._INTAKE_HITS.clear()
    body = {"name": "김단독", "kind": "UI_BUG", "title": "단독형 오류", "text": "단독형 앱에서 발생한 오류입니다.", "view": "env", "context": {"client": "PC앱"}, "images": [{"name": "a.png", "data": PNG}]}
    r = c.post("/api/feedback/intake", json=body); assert r.status_code == 200, r.text
    fid, rc = r.json()["id"], r.json()["receipt"]
    assert c.post("/api/feedback/intake", json={**body, "name": "a"}).status_code == 400              # 실명 필요
    assert c.get(f"/api/feedback/intake/{fid}?receipt=bad").status_code == 404                        # 영수증 없이 조회 불가
    assert c.get(f"/api/feedback/intake/{fid}?receipt={rc}").json()["status"] == "RECEIVED"
    g = c.get(f"/api/feedback/{fid}", headers=env["A"]).json(); assert g["source"] == "standalone" and g["images"]   # admin 개발큐에 표시
    assert c.get(f"/api/feedback/{fid}", headers=env["L"]).status_code == 404
    for _ in range(12):
        last = c.post("/api/feedback/intake", json=body).status_code
    assert last == 429                                                                                # IP 한도
    feedback._INTAKE_HITS.clear()


def test_standalone_forward_and_status_sync(env, monkeypatch):
    c = env["c"]
    L = login(c, name="홍길동")
    feedback._INTAKE_HITS.clear()
    monkeypatch.setenv("DBX_STANDALONE", "1")
    monkeypatch.setattr(feedback, "_http", lambda m, path, body=None, timeout=8: (c.post(path, json=body) if m == "POST" else c.get(path)).json())
    feedback._ONLINE.update(t=0.0, ok=True)
    r = c.post("/api/feedback", headers=L, json={"kind": "FEATURE", "title": "단독 요청", "text": "기능을 추가해 주세요.", "view": "sql", "images": [{"name": "a.png", "data": PNG}]}); assert r.status_code == 200
    time.sleep(0.5)
    m = c.get("/api/feedback/mine", headers=L).json()["items"]
    mine = next(i for i in m if i["id"] == r.json()["id"]); assert mine["remote_state"] == "SENT", feedback._F()[mine["id"]].get("remote_error")
    local = feedback._F()[mine["id"]]; rid = local["remote"]["id"]
    central = feedback._F()[rid]; assert central["source"] == "standalone" and len(central["images"]) == 1          # 이미지까지 중앙 접수
    T = lambda to, **k: c.post(f"/api/feedback/{rid}/transition", headers=env["A"], json={"to": to, **k})
    assert T("APPROVED").status_code == 200 and T("QUEUED").status_code == 200 and T("IN_DEV").status_code == 200
    assert T("DONE", released_version="0.4.3", note="반영됨").status_code == 200
    m = c.get("/api/feedback/mine", headers=L).json()
    it = next(i for i in m["items"] if i["id"] == mine["id"])
    assert it["status"] == "DONE" and it["released_version"] == "0.4.3" and it["resolution"] == "반영됨"           # 중앙 처리 결과가 내 피드백에 반영
    # 오프라인이면 보류 후 재전송
    feedback._ONLINE.update(t=0.0, ok=True)
    def boom(*a, **k): raise OSError("offline")
    monkeypatch.setattr(feedback, "_http", boom)
    r2 = c.post("/api/feedback", headers=L, json={"kind": "OTHER", "title": "오프라인", "text": "오프라인에서 제출"}); time.sleep(0.3)
    assert feedback._F()[r2.json()["id"]].get("remote") is None
    monkeypatch.setattr(feedback, "_http", lambda m, path, body=None, timeout=8: (c.post(path, json=body) if m == "POST" else c.get(path)).json())
    feedback._ONLINE.update(t=0.0, ok=True)
    c.get("/api/feedback/mine", headers=L)
    assert feedback._F()[r2.json()["id"]].get("remote")


def test_standalone_update_check(env, monkeypatch):
    c = env["c"]
    monkeypatch.setenv("DBX_STANDALONE", "1"); monkeypatch.setenv("DBX_EXE_SHA", "aaa")
    monkeypatch.setattr(sysinfo, "central_manifest", lambda: {"standalone": {"available": True, "version": "9.9.9", "sha256": "bbb", "size": 5}})
    a = c.get("/api/system/update-check?build=x", headers=env["L"]).json()["app"]
    assert a["update_available"] and a["latest_version"] == "9.9.9" and not a["offline"]
    monkeypatch.setenv("DBX_EXE_SHA", "bbb")
    assert not c.get("/api/system/update-check?build=x", headers=env["L"]).json()["app"]["update_available"]
    monkeypatch.setattr(sysinfo, "central_manifest", lambda: None)
    a = c.get("/api/system/update-check?build=x", headers=env["L"]).json()["app"]; assert a["offline"] and not a["update_available"]
