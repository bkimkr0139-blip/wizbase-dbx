"""피드백 관리·개발큐: 선택 삭제·수정·일괄 상태 변경은 admin 전용이며 흔적(이력·감사)이 남는다."""
from test_at import client, env, login  # noqa: F401
from backend import feedback

PNG = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="


def _submit(c, h, title="관리 테스트", img=False, kind="UI_BUG"):
    b = {"kind": kind, "title": title, "text": "관리 기능 확인용 피드백 내용입니다.", "view": "sql"}
    if img:
        b["images"] = [{"name": "a.png", "data": PNG}]
    r = c.post("/api/feedback", headers=h, json=b)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_admin_only(env):
    c = env["c"]
    fid = _submit(c, env["L"])
    for h in (env["L"], env["R"], env["I"]):
        assert c.post("/api/feedback/delete", headers=h, json={"ids": [fid]}).status_code == 403
        assert c.post(f"/api/feedback/{fid}/edit", headers=h, json={"title": "x"}).status_code == 403
        assert c.post("/api/feedback/bulk", headers=h, json={"ids": [fid], "to": "APPROVED"}).status_code == 403
    assert fid in [i["id"] for i in c.get("/api/feedback/mine", headers=env["L"]).json()["items"]]      # 거부되어 그대로


def test_delete_removes_record_and_images(env):
    c = env["c"]
    a, b = _submit(c, env["L"], "삭제1", img=True), _submit(c, env["L"], "삭제2")
    files = [feedback._dir() / i["file"] for i in feedback._F()[a]["images"]]
    assert files and all(p.exists() for p in files)
    r = c.post("/api/feedback/delete", headers=env["A"], json={"ids": [a, b, a, "FB-99999"]}).json()
    assert set(r["deleted"]) == {a, b} and r["missing"] == ["FB-99999"]                                # 중복 id는 한 번만
    assert not any(p.exists() for p in files)                                                          # 첨부 이미지까지 삭제
    assert c.get(f"/api/feedback/{a}", headers=env["A"]).status_code == 404
    mine = [i["id"] for i in c.get("/api/feedback/mine", headers=env["L"]).json()["items"]]
    assert a not in mine and b not in mine
    from backend import v11
    assert any(e["kind"] == "FEEDBACK_DELETE" and e["ref"] == a for e in v11.V["audit"])               # 감사 기록은 남는다


def test_edit_updates_history_and_regenerates_ticket(env):
    c, A = env["c"], env["A"]
    fid = _submit(c, env["L"], "수정 전 제목")
    for to in ("APPROVED", "QUEUED"):
        assert c.post(f"/api/feedback/{fid}/transition", headers=A, json={"to": to}).status_code == 200
    r = c.post(f"/api/feedback/{fid}/edit", headers=A, json={"title": "수정 후 제목", "text": "수정된 상세 내용을 길게 적었습니다.", "kind": "IMPROVE", "priority": "P1"})
    assert r.status_code == 200
    d = r.json()
    assert d["title"] == "수정 후 제목" and d["kind"] == "IMPROVE" and d["priority"] == "P1"
    assert "수정 후 제목" in d["ticket_md"] and "수정된 상세 내용" in d["ticket_md"]                    # 개발 지시서 재생성
    assert d["history"][-1]["note"].startswith("관리자 수정") and "제목" in d["history"][-1]["note"] and d["edited_at"]
    assert c.get(f"/api/feedback/{fid}", headers=A).json().get("history")
    assert c.post(f"/api/feedback/{fid}/edit", headers=A, json={"title": "  "}).status_code == 400
    assert c.post(f"/api/feedback/{fid}/edit", headers=A, json={"text": "짧"}).status_code == 400
    assert c.post(f"/api/feedback/{fid}/edit", headers=A, json={"priority": "P9"}).status_code == 400
    assert c.post(f"/api/feedback/{fid}/edit", headers=A, json={"kind": "DOMAIN_REQUEST"}).status_code == 400   # 도메인 신청으로 바꿀 수 없음
    assert c.get("/api/feedback/mine", headers=env["L"]).json()["items"][0]["title"] == "수정 후 제목"      # 제출자 화면에도 수정이 보임


def test_bulk_transition_skips_invalid_with_reasons(env):
    c, A = env["c"], env["A"]
    ids = [_submit(c, env["L"], f"일괄{i}") for i in range(3)]
    c.post(f"/api/feedback/{ids[2]}/transition", headers=A, json={"to": "APPROVED"})
    r = c.post("/api/feedback/bulk", headers=A, json={"ids": ids, "to": "APPROVED"}).json()
    assert set(r["ok"]) == set(ids[:2]) and r["failed"][0]["id"] == ids[2] and r["failed"][0]["code"] == "BAD_TRANSITION"   # 이미 승인된 건은 건너뜀
    r = c.post("/api/feedback/bulk", headers=A, json={"ids": ids[:2], "to": "REJECTED"}).json()
    assert len(r["failed"]) == 2 and r["failed"][0]["code"] == "REASON_REQUIRED"                          # 반려 사유 필수
    r = c.post("/api/feedback/bulk", headers=A, json={"ids": ids[:2], "to": "REJECTED", "note": "범위 밖 요청"}).json()
    assert len(r["ok"]) == 2
    assert all(c.get(f"/api/feedback/{i}", headers=A).json()["status"] == "REJECTED" for i in ids[:2])


def test_admin_list_search_and_pagination(env):
    c, A = env["c"], env["A"]
    tag = "검색키워드ZQX"
    ids = [_submit(c, env["L"], f"{tag} 항목{i}") for i in range(7)]
    _submit(c, env["L"], "무관한 다른 제목")
    r = c.get(f"/api/feedback/admin?q={tag}&size=5&page=0", headers=A).json()
    assert r["total"] == 7 and len(r["items"]) == 5 and r["pages"] == 2 and r["page"] == 0 and len(r["ids"]) == 7     # 5건씩 2쪽, 조건 전체 id
    r2 = c.get(f"/api/feedback/admin?q={tag}&size=5&page=1", headers=A).json()
    assert len(r2["items"]) == 2 and {i["id"] for i in r["items"]}.isdisjoint({i["id"] for i in r2["items"]})
    assert c.get(f"/api/feedback/admin?q={tag}&size=5&page=99", headers=A).json()["page"] == 1                       # 범위를 넘으면 마지막 쪽
    assert c.get("/api/feedback/admin?q=zqx", headers=A).json()["total"] >= 7                                           # 대소문자 무시
    assert c.get(f"/api/feedback/admin?q={ids[0]}", headers=A).json()["total"] == 1                                      # 번호로 검색
    assert sum(c.get("/api/feedback/admin?size=5", headers=A).json()["counts"].values()) >= 8                          # 상태별 건수는 검색과 무관
    assert c.get("/api/feedback/admin?size=1000", headers=A).json()["size"] == 100                                       # 쪽당 상한
    assert c.get("/api/feedback/admin?q=x", headers=env["L"]).status_code == 403
