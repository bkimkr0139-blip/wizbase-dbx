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


def test_content_pack_build_verify_and_tamper(tmp_path):
    import io, json, zipfile
    from backend import pack
    root = tmp_path / "src"
    (root / "static").mkdir(parents=True); (root / "backend").mkdir()
    (root / "static" / "app.js").write_text("console.log(1)", encoding="utf-8")
    (root / "backend" / "x.py").write_text("A = 1\n", encoding="utf-8")
    (root / "backend" / "_tmp.py").write_text("junk", encoding="utf-8")            # 임시 파일 제외
    data, mf = pack.build("0.0.1", 1, root)
    assert mf["content_id"] == pack.content_id(root) and "backend/_tmp.py" not in mf["files"] and mf["size"] == len(data)
    assert pack.build("0.0.1", 1, root)[1]["sha256"] == mf["sha256"]                 # 결정적(같은 입력 → 같은 해시)
    z = tmp_path / "p.zip"; z.write_bytes(data)
    out = tmp_path / "out"
    got = pack.extract_verified(z, out, mf["content_id"], 1)
    assert (out / "static" / "app.js").read_text(encoding="utf-8") == "console.log(1)" and pack.verify_dir(out, 1)["content_id"] == got["content_id"]
    try:
        pack.extract_verified(z, tmp_path / "o2", mf["content_id"], 2); assert False            # compat 불일치 거부
    except ValueError:
        pass
    try:
        pack.extract_verified(z, tmp_path / "o3", "0" * 16, 1); assert False                    # content_id 불일치 거부
    except ValueError:
        pass
    (out / "backend" / "x.py").write_text("A = 2\n", encoding="utf-8")                          # 적용 후 변조 감지
    try:
        pack.verify_dir(out, 1); assert False
    except ValueError:
        pass
    bad = io.BytesIO()                                                                          # 경로 이탈(zip slip)·미등록 파일 거부
    with zipfile.ZipFile(bad, "w") as zz:
        zz.writestr("manifest.json", json.dumps({"content_id": "x", "compat": 1, "files": {}}))
        zz.writestr("../evil.py", "boom")
    (tmp_path / "bad.zip").write_bytes(bad.getvalue())
    try:
        pack.extract_verified(tmp_path / "bad.zip", tmp_path / "o4", "x", 1); assert False
    except ValueError:
        pass
    assert not (tmp_path / "evil.py").exists()


def test_pack_endpoint_manifest_and_update_kinds(env, monkeypatch):
    c = env["c"]
    m = c.get("/api/app/manifest").json()
    assert m["pack"]["available"] and m["standalone"]["compat"] == sysinfo.STANDALONE_COMPAT
    r = c.get("/download/pack"); assert r.status_code == 200 and len(r.content) == m["pack"]["size"]
    import hashlib; assert hashlib.sha256(r.content).hexdigest() == m["pack"]["sha256"]
    monkeypatch.setenv("DBX_STANDALONE", "1"); monkeypatch.setenv("DBX_EXE_COMPAT", "1"); monkeypatch.setenv("DBX_CONTENT_ID", "old")
    base = {"standalone": {"available": True, "version": "9", "sha256": "z", "compat": 1, "size": 9}, "pack": {"available": True, "content_id": "new", "version": "9", "size": 2048, "compat": 1}}
    monkeypatch.setattr(sysinfo, "central_manifest", lambda: base)
    a = c.get("/api/system/update-check?build=x", headers=env["L"]).json()["app"]; assert a["kind"] == "pack" and a["update_available"] and a["size"] == 2048    # 작은 팩 업데이트
    monkeypatch.setenv("DBX_CONTENT_ID", "new")
    assert not c.get("/api/system/update-check?build=x", headers=env["L"]).json()["app"]["update_available"]                                              # 같으면 없음
    base["standalone"]["compat"] = 2
    a = c.get("/api/system/update-check?build=x", headers=env["L"]).json()["app"]; assert a["kind"] == "exe" and a["update_available"]                    # 호환 변경 → exe 전체 교체


def test_mac_manifest_routes_and_platform_update(env, monkeypatch, tmp_path):
    c = env["c"]
    m = c.get("/api/app/manifest").json()
    assert m["mac_arm64"]["download"] == "/download/standalone-mac-arm64" and m["mac_x64"]["download"] == "/download/standalone-mac-x64" and m["mac_arm64"]["compat"] == sysinfo.STANDALONE_COMPAT
    if not m["mac_arm64"]["available"]:
        assert c.get("/download/standalone-mac-arm64").status_code == 404                     # 아직 빌드 전이면 숨기지 않고 404
    f = tmp_path / "mac.zip"; f.write_bytes(b"PK\x03\x04demo")
    monkeypatch.setitem(sysinfo.MAC_FILES, "mac_x64", f)
    assert c.get("/download/standalone-mac-x64").content == b"PK\x03\x04demo"
    assert c.get("/api/app/manifest").json()["mac_x64"]["available"]
    monkeypatch.setenv("DBX_STANDALONE", "1"); monkeypatch.setenv("DBX_EXE_COMPAT", "1"); monkeypatch.setenv("DBX_CONTENT_ID", "same"); monkeypatch.setenv("DBX_PLATFORM", "mac_arm64")
    rm = {"standalone": {"available": True, "compat": 1}, "mac_arm64": {"available": True, "version": "9.9.9", "size": 5, "compat": 2}, "pack": {"available": True, "content_id": "same", "compat": 1}}
    monkeypatch.setattr(sysinfo, "central_manifest", lambda: rm)
    a = c.get("/api/system/update-check?build=x", headers=env["L"]).json()["app"]
    assert a["kind"] == "exe" and a["latest_version"] == "9.9.9"                               # Mac은 자기 플랫폼 항목(mac_arm64)의 compat 기준으로 판단


def test_launcher_is_cross_platform_importable():
    import ast, pathlib
    src = pathlib.Path(__file__).resolve().parent.parent.joinpath("desktop", "dbx_standalone.py").read_text(encoding="utf-8")
    ast.parse(src)
    assert "IS_MAC" in src and "fcntl" in src and "osascript" in src                         # macOS 분기 존재
    import re
    for m in re.finditer(r"ctypes\.windll", src):                                            # windll 사용은 모두 IS_WIN 분기 안(함수 내부)에서만
        line_start = src.rfind("\n", 0, m.start()) + 1
        assert src[line_start:m.start()].startswith(("        ", "    ")), "windll at module level"
