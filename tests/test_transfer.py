"""전이 산업 시드 · 협업 훈련 테스트."""
import csv, hashlib, io
from test_at import client, env, login  # noqa: F401
from backend import transfer

SHA = hashlib.sha256(b"artifact").hexdigest()


def rows(t):
    return list(csv.DictReader(io.StringIO(t)))


def test_seeds_deterministic_and_key_matches_data(env):
    c = env["c"]
    a = c.get("/api/transfer-seeds", headers=env["L"]).json()
    assert {s["seed_id"] for s in a} == set(transfer.SEEDS) and c.get("/api/transfer-seeds").status_code == 401
    assert a == c.get("/api/transfer-seeds", headers=env["L"]).json()                       # 결정적
    # IoT
    f = c.get("/api/transfer-seeds/mfg-iot-v1/files", headers=env["L"]).json()["files"]
    rs = rows(f["readings.csv"]); key = c.get("/api/transfer-seeds/mfg-iot-v1/answer-key", headers=env["R"]).json()["answer_key"]
    assert len(rs) == key["total_rows_in_file"] and len({r["reading_id"] for r in rs}) == key["distinct_readings"] and len(rs) - len({r["reading_id"] for r in rs}) == key["duplicate_rows"]
    # 클릭스트림
    ev = rows(c.get("/api/transfer-seeds/clickstream-v1/files", headers=env["L"]).json()["files"]["events.csv"]); k2 = c.get("/api/transfer-seeds/clickstream-v1/answer-key", headers=env["R"]).json()["answer_key"]
    assert len({e["event_id"] for e in ev}) == k2["distinct_events"] and len({e["user_id"] for e in ev if "bot" in e["user_agent"]}) == k2["bot_users"]
    # RAG
    g = c.get("/api/transfer-seeds/doc-rag-v1/files", headers=env["L"]).json()["files"]; k3 = c.get("/api/transfer-seeds/doc-rag-v1/answer-key", headers=env["R"]).json()["answer_key"]
    docs = {d["doc_id"]: d for d in rows(g["documents.csv"])}; ch = rows(g["chunks.csv"])
    assert len(ch) == k3["chunks"] and sum(docs[x["doc_id"]]["status"] == "SUPERSEDED" for x in ch) == k3["stale_chunks"] and sum("010-0000" in x["text"] for x in ch) == k3["chunks_with_synthetic_phone"]


def test_answer_key_staff_only_and_unknown(env):
    c = env["c"]
    assert c.get("/api/transfer-seeds/mfg-iot-v1/answer-key", headers=env["L"]).status_code == 403
    assert c.get("/api/transfer-seeds/nope/files", headers=env["L"]).status_code == 404


def test_collab_flow(env, client):
    c = client
    users = {r: login(c, name=r) for r in transfer.ROLES}
    t = c.post("/api/collab/teams", headers=users["DBA"], json={"name": "A팀"}).json(); tid = t["team_id"]
    for r, h in users.items():
        assert c.post(f"/api/collab/teams/{tid}/join", headers=h, json={"role": r}).status_code == 200
    # 한 사람 두 역할 · 역할 중복
    assert c.post(f"/api/collab/teams/{tid}/join", headers=users["DBA"], json={"role": "AX"}).status_code == 409
    sub = lambda r, tk, **kw: c.post(f"/api/collab/teams/{tid}/tasks/{tk}/submit", headers=users[r], json={"artifact_sha256": SHA, "handoff_note": "다음 역할에게 넘길 충분한 인계 메모", **kw})
    rev = lambda r, tk, ok=True, reason="": c.post(f"/api/collab/teams/{tid}/tasks/{tk}/review", headers=users[r], json={"approve": ok, "reason": reason})
    assert sub("DATA_ENGINEER", "T2").status_code == 409                                    # 선행 미완료
    assert sub("AX", "T1").status_code == 403                                                # 역할 불일치
    assert c.post(f"/api/collab/teams/{tid}/tasks/T1/submit", headers=users["DBA"], json={"artifact_sha256": "xx", "handoff_note": "충분히 긴 인계 메모입니다"}).status_code == 400
    assert c.post(f"/api/collab/teams/{tid}/tasks/T1/submit", headers=users["DBA"], json={"artifact_sha256": SHA, "handoff_note": "짧음"}).status_code == 400
    assert sub("DBA", "T1").status_code == 200
    assert rev("DBA", "T1").status_code == 403                                               # 자기 승인 금지
    assert rev("DATA_ENGINEER", "T1", False).status_code == 400                              # 사유 필수
    assert rev("DATA_ENGINEER", "T1", False, "권한 범위 불명확").status_code == 200
    assert sub("DBA", "T1").status_code == 200 and rev("DATA_ENGINEER", "T1").status_code == 200
    for r, tk, rv in (("DATA_ENGINEER", "T2", "AX"), ("AX", "T3", "REVIEWER")):
        assert sub(r, tk).status_code == 200 and rev(rv, tk).status_code == 200
    s = c.get(f"/api/collab/teams/{tid}", headers=users["DBA"]).json()
    assert not s["complete"] and s["tasks"]["T4"]["status"] == "READY"
    assert sub("REVIEWER", "T4").status_code == 200 and rev("DBA", "T4").status_code == 200
    s = c.get(f"/api/collab/teams/{tid}", headers=users["DBA"]).json()
    assert s["complete"] and not s["missing_roles"]
    assert c.get(f"/api/collab/teams/{tid}", headers=login(c, name="outsider")).status_code == 404


def test_system_info_document_manual_and_menu(env):
    import re, pathlib
    from backend import sysinfo
    c = env["c"]
    i = c.get("/api/system/info", headers=env["L"]).json()
    assert i["version"] == sysinfo.VERSION and i["build"] and i["menu"]
    assert c.get("/api/system/document", headers=env["L"]).status_code == 403 and c.get("/api/system/document", headers=env["R"]).status_code == 403   # admin 전용
    d = c.get("/api/system/document", headers=env["A"])
    assert d.status_code == 200 and "attachment" in d.headers["content-disposition"] and "시스템 문서" in d.text and sysinfo.VERSION in d.text
    assert c.get("/api/review/manual", headers=env["L"]).status_code == 403
    m = c.get("/api/review/manual", headers=env["R"]); assert m.status_code == 200 and "LAB-DE-01" in m.text and "WORKSPACE_CHECKED" in m.text
    u = c.get("/api/system/update-check?build=old", headers=env["L"]).json(); assert u["update_available"]
    assert not c.get(f"/api/system/update-check?build={i['build']}", headers=env["L"]).json()["update_available"]
    sd = pathlib.Path(__file__).resolve().parent.parent.joinpath("static")
    js = "\n".join(f.read_text(encoding="utf-8") for f in [sd.joinpath("app.js"), *sorted(sd.glob("x_*.js"))])       # 확장 화면(x_*.js) 포함
    for t in i["menu"]:                                                                       # 메뉴의 모든 view가 화면 구현을 가진다
        for it in t["items"]:
            assert re.search(r"\b" + it["view"] + r"\(\)", js), it["view"]
    k = c.get("/api/ko-guide", headers=env["L"]).json()["exams"]
    assert k["DE-A"]["status"] == "ALIGNED_HASH_LINKED" and k["DE-P"]["status"] == "OLDER_VERSION_REFERENCE"


def test_desktop_app_manifest_download_and_doc_exclusion(env):
    import re, pathlib
    from backend import sysinfo
    c = env["c"]
    root = pathlib.Path(__file__).resolve().parent.parent
    ver = re.search(r'APP_VERSION = "([\d.]+)"', root.joinpath("desktop", "dbx_app.py").read_text(encoding="utf-8")).group(1)
    assert ver == sysinfo.SHELL_VERSION                                                      # 앱 버전과 서버가 알리는 최신 앱 버전이 일치
    m = c.get("/api/app/manifest").json()                                                    # 로그인 전(시작 화면)에도 조회 가능
    assert m["shell_version"] == ver and m["download"] == "/download/app" and "sha256" in m
    if m["available"]:
        r = c.get("/download/app"); assert r.status_code == 200 and len(r.content) == m["size"] and r.content[:2] == b"MZ"
    else:
        assert c.get("/download/app").status_code == 404
    assert c.get("/api/system/document", headers=env["A"]).status_code == 200               # 웹에서는 admin에게 시스템 문서 제공
    d = c.get("/api/system/document", headers={**env["A"], "User-Agent": "Mozilla/5.0 DBXDesktop/1.0.0"})
    assert d.status_code == 403 and "## 1. 한눈에 보기" not in d.text                            # PC 앱에는 제외
    assert c.get("/api/system/update-check?build=x", headers=env["L"]).json()["app"]["shell_version"] == ver


PNG = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="


def test_feedback_loop_admin_only_with_images_and_domain_request(env):
    c = env["c"]
    body = {"kind": "UI_BUG", "title": "표가 깨짐", "text": "환경 점검 표에서 링크가 글자로 보입니다.", "view": "env", "context": {"view": "env", "version": "1.4.0", "client": "웹"}, "images": [{"name": "a.png", "data": PNG}]}
    r = c.post("/api/feedback", headers=env["L"], json=body); assert r.status_code == 200, r.text
    fid = r.json()["id"]; assert r.json()["images"] == 1
    assert c.post("/api/feedback", headers=env["L"], json={**body, "title": ""}).status_code == 400
    assert c.post("/api/feedback", headers=env["L"], json={**body, "images": [{"name": "x.svg", "data": "data:image/svg+xml;base64,PHN2Zz48L3N2Zz4="}]}).status_code == 400   # SVG·위장 파일 거부
    assert c.post("/api/feedback", headers=env["L"], json={**body, "images": [{"name": "x", "data": "!!!"}]}).status_code == 400
    # 관리는 admin만
    for h in (env["L"], env["R"]):
        assert c.get("/api/feedback/admin", headers=h).status_code == 403
        assert c.post(f"/api/feedback/{fid}/transition", headers=h, json={"to": "APPROVED"}).status_code == 403
        assert c.get("/api/feedback/queue.md", headers=h).status_code == 403
    assert c.get(f"/api/feedback/{fid}", headers=env["R"]).status_code == 404            # 타인 건 열람 불가
    assert c.get(f"/api/feedback/{fid}/image/1", headers=env["R"]).status_code == 404
    mine = c.get("/api/feedback/mine", headers=env["L"]).json(); assert any(i["id"] == fid for i in mine["items"])
    img = c.get(f"/api/feedback/{fid}/image/1", headers=env["L"]); assert img.status_code == 200 and img.headers["content-type"] == "image/png"
    A = env["A"]; T = lambda to, **k: c.post(f"/api/feedback/{fid}/transition", headers=A, json={"to": to, **k})
    assert T("DONE", released_version="1.4.0").status_code == 409                          # 단계 건너뛰기 금지
    assert T("REJECTED").status_code == 400                                                # 반려 사유 필수
    assert T("APPROVED").status_code == 200
    q = T("QUEUED", priority="P1").json(); assert "개발 지시서" in q["ticket_md"] and "표가 깨짐" in q["ticket_md"] and q["priority"] == "P1"
    assert fid in c.get("/api/feedback/queue.md", headers=A).text
    assert T("IN_DEV").status_code == 200
    assert T("DONE").status_code == 400                                                    # 반영 버전 필수
    assert T("DONE", released_version="1.4.0", note="수정 반영").status_code == 200
    assert T("QUEUED").status_code == 409                                                  # 종결 후 전이 불가
    m = c.get("/api/feedback/mine", headers=env["L"]).json(); assert m["unseen_done"] == 1 and m["items"][0]["released_version"] == "1.4.0"
    assert "ticket_md" not in c.get(f"/api/feedback/{fid}", headers=env["L"]).json()       # 제출자에겐 개발 지시서 비공개
    c.post("/api/feedback/mine/seen", headers=env["L"]); assert c.get("/api/feedback/mine", headers=env["L"]).json()["unseen_done"] == 0
    # 도메인 신청도 동일한 AXOS 폐루프로 관리(이메일 전송 없음)
    d = {"kind": "DOMAIN_REQUEST", "title": "도메인 신청: 물류", "text": "창고 입출고", "domain": {"domain": "물류·창고", "purpose": "재고 정합성", "data": "입출고", "issues": "중복", "when": "12월"}}
    r = c.post("/api/feedback", headers=env["L"], json=d); assert r.status_code == 200
    did = r.json()["id"]
    g = c.get(f"/api/feedback/{did}", headers=A).json(); assert g["domain"]["domain"] == "물류·창고" and "mail" not in g and g["status"] == "RECEIVED"
    assert c.post(f"/api/feedback/{did}/transition", headers=A, json={"to": "APPROVED"}).status_code == 200
    q = c.post(f"/api/feedback/{did}/transition", headers=A, json={"to": "QUEUED"}).json(); assert "재고 정합성" in q["ticket_md"] and "transfer.py" in q["ticket_md"]
    assert c.get(f"/api/feedback/{did}", headers=env["R"]).status_code == 404
    assert c.post("/api/feedback", headers=env["L"], json={**d, "domain": {"domain": ""}}).status_code == 400


def test_session_delete_own_only_admin_all(env):
    c = env["c"]
    mk = lambda h: c.post("/api/sessions", headers=h, json={}).json()["session_id"]
    mine, other = mk(env["L"]), mk(env["R"])
    r = c.post("/api/sessions/delete", headers=env["L"], json={"ids": [mine, other, "s_nope"]}).json()
    assert r["deleted"] == [mine] and set(r["denied"]) == {other, "s_nope"}              # 타인·없는 세션은 삭제 안 됨
    assert c.get(f"/api/sessions/{mine}/state", headers=env["L"]).status_code == 404
    assert c.get(f"/api/sessions/{other}/state", headers=env["R"]).status_code == 200
    assert c.post("/api/sessions/delete", headers=env["R"], json={"ids": [mine]}).json()["denied"] == [mine]
    a = c.post("/api/sessions/delete", headers=env["A"], json={"ids": [other]}).json(); assert a["deleted"] == [other]   # admin은 전체
    import glob, os
    from backend import core
    assert not glob.glob(str(core.DATA / f"{other}*"))


def test_admin_code_separate_and_admin_scope_exclusive(env):
    c = env["c"]
    lg = lambda role, code: c.post("/api/auth/login", json={"name": "x", "role": role, "code": code}).status_code
    assert lg("admin", "A-test-code") == 200
    assert lg("admin", "S-test-code") == 403 and lg("admin", "I-test-code") == 403 and lg("admin", None) == 403   # staff·instructor 코드로는 admin 불가
    assert lg("reviewer", "A-test-code") == 403 and lg("instructor", "A-test-code") == 403                         # admin 코드로 다른 직원 역할도 불가(역할별 코드)
    ins = c.post("/api/auth/login", json={"name": "i", "role": "instructor", "code": "I-test-code"}).json()["token"]
    H = {"Authorization": "Bearer " + ins}
    for path in ("/api/feedback/admin", "/api/system/document", "/api/feedback/queue.md"):
        assert c.get(path, headers=H).status_code == 403, path                                                     # admin 고유 범위
        assert c.get(path, headers=env["R"]).status_code == 403, path
        assert c.get(path, headers=env["A"]).status_code == 200, path
    assert c.get("/api/review/queue", headers=env["A"]).status_code == 200                                         # admin은 모든 기능
    s = c.post("/api/sessions", headers=env["L"], json={}).json()["session_id"]
    assert c.post("/api/sessions/delete", headers=H, json={"ids": [s]}).json()["denied"] == [s]                    # 타인 세션 삭제는 admin만


def test_session_list_shows_owner_name(env):
    c = env["c"]
    sid = c.post("/api/sessions", headers=env["L"], json={}).json()["session_id"]
    row = next(s for s in c.get("/api/sessions", headers=env["A"]).json() if s["session_id"] == sid)
    assert row["owner_name"] and row["owner"]


def test_session_list_has_created_and_last_activity(env):
    c = env["c"]
    row = next(s for s in c.get("/api/sessions", headers=env["L"]).json() if s["session_id"] == env["sid"])
    assert row["created_at"] > 0 and row["last_activity_at"] >= row["created_at"]


def test_login_requires_real_name(env):
    c = env["c"]
    for n in ("", "  ", "학습자", None):
        r = c.post("/api/auth/login", json={"name": n, "role": "learner"})
        assert r.status_code in (400, 422), n
    assert c.post("/api/auth/login", json={"name": "홍길동", "role": "learner"}).status_code == 200


def test_version_policy_pre_release(env):
    from backend import sysinfo
    assert sysinfo.VERSION.startswith("0.") and sysinfo.SHELL_VERSION.startswith("0.")           # 정식 전환 전에는 MAJOR=0
    assert sysinfo.CHANGELOG[0]["version"] == sysinfo.VERSION and all(r["version"].startswith("0.") for r in sysinfo.CHANGELOG)
    assert "version_policy" in env["c"].get("/api/system/info", headers=env["L"]).json()


def test_every_sql_error_code_has_a_remedy_in_ui():
    """실패 → 해결 안내: 서버가 내는 모든 SQL 오류 코드는 화면에 해결 안내(REMEDY)가 있어야 한다."""
    import re, pathlib
    root = pathlib.Path(__file__).resolve().parent.parent
    core = root.joinpath("backend", "core.py").read_text(encoding="utf-8")
    js = root.joinpath("static", "app.js").read_text(encoding="utf-8")
    codes = set(re.findall(r'sql_error\(\s*"([A-Z_]+)"', core)) | {"WAREHOUSE_START_FAILED"}
    have = set(re.findall(r"^\s{2}([A-Z_]+): e =>", js, re.M))
    assert codes - have == set(), f"해결 안내 없는 오류 코드: {sorted(codes - have)}"


def test_sessions_page_search_pagination_and_scope(env):
    c = env["c"]
    Adm = env["A"]
    mine = [c.post("/api/sessions", headers=Adm, json={}).json()["session_id"] for _ in range(7)]
    r = c.get("/api/sessions/page?size=5&page=0", headers=Adm).json()
    assert r["scope"] == "all" and r["total"] >= 7 and len(r["items"]) == 5 and r["pages"] >= 2 and len(r["ids"]) == min(r["total"], 500)
    r2 = c.get("/api/sessions/page?size=5&page=1", headers=Adm).json()
    assert {i["session_id"] for i in r["items"]}.isdisjoint({i["session_id"] for i in r2["items"]})
    assert c.get("/api/sessions/page?size=5&page=999", headers=Adm).json()["page"] == r["pages"] - 1                       # 범위 초과 → 마지막 쪽
    sid = mine[3]
    q = c.get(f"/api/sessions/page?q={sid}", headers=Adm).json(); assert q["total"] == 1 and q["items"][0]["session_id"] == sid   # 세션 ID 검색
    assert all("adm" in i["owner_name"].lower() for i in c.get("/api/sessions/page?q=adm&size=100", headers=Adm).json()["items"])  # 사용자 이름 검색
    # 학습자는 admin이 만든 세션이 보이지 않고 본인 것만(검색해도)
    L = env["L"]
    lr = c.get("/api/sessions/page?size=100", headers=L).json()
    assert lr["scope"] == "own" and all(i["owner_name"] != "adm" for i in lr["items"]) and sid not in lr["ids"]
    assert c.get(f"/api/sessions/page?q={sid}", headers=L).json()["total"] == 0
