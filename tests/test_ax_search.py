"""AX 지식 문서 검색 테스트: 버전·시행일·ACL·tenant 필터, keyword/vector/hybrid, 악성 문서, 평가. 합성 문서·해시 임베딩 기준."""
import pytest
from test_at import client, env, login  # noqa: F401
from test_ax import ws, approve_release, uid, P  # noqa: F401
from backend import ax_search


def seed(w):
    r = w["c"].post(f"{P}/{w['pid']}/documents/demo", headers=w["L"])
    assert r.status_code == 200 and len(r.json()["added"]) == len(ax_search.DEMO_DOCS)
    return r.json()


def srch(w, q, who="L", **kw):
    params = "&".join(f"{k}={v}" for k, v in kw.items())
    r = w["c"].get(f"{P}/{w['pid']}/search?q={q}&{params}", headers=w[who])
    assert r.status_code == 200, r.text
    return r.json()


def member(w, name, **scope):
    h = login(w["c"], "learner", name)
    u = uid({"c": w["c"], "X": h}, "X")
    assert w["c"].post(f"{P}/{w['pid']}/members", headers=w["L"], json=dict(user_id=u, role="business_user", **scope)).status_code == 200
    w[name] = h
    return u


def titles(r):
    return [x["title"] for x in r["results"]]


def test_version_and_effective_date_filters(ws):
    seed(ws)
    r = srch(ws, "반품은 며칠 이내에 접수하나요", as_of="2026-11-14")
    top = r["results"][0]
    assert top["title"] == "반품 처리 매뉴얼" and top["version"] == 2 and "10일" in top["snippet"]      # 최신 시행 버전
    assert not any(x["version"] == 1 and x["title"] == "반품 처리 매뉴얼" for x in r["results"])      # 구버전은 기본 제외
    old = srch(ws, "반품은 며칠 이내에 접수하나요", as_of="2026-10-15", include_old="true")
    assert [x for x in old["results"] if x["title"] == "반품 처리 매뉴얼"][0]["version"] == 1 and old["results"][0]["doc_status"] == "SUPERSEDED"
    none = srch(ws, "반품은 며칠 이내에 접수하나요", as_of="2026-10-15")                                # 시행일 전: 보이는 반품 문서 없음
    assert not any(x["title"] == "반품 처리 매뉴얼" for x in none["results"])
    r2 = ws["c"].post(f"{P}/{ws['pid']}/documents", headers=ws["L"], json={"title": "반품 처리 매뉴얼", "doc_key": "return", "tenant_id": "T1", "version": 2, "text": "반품은 출고 후 5일 이내 접수한다. 중복 버전."})
    assert r2.status_code == 409 and r2.json()["error"]["code"] == "VERSION_NOT_NEWER"
    assert any(x["page"] == 2 for x in srch(ws, "반품 승인은 누가 하나요")["results"])                  # 페이지 인용


def test_acl_and_tenant_filters_apply_before_search_and_on_revocation(ws):
    seed(ws)
    member(ws, "c1", tenants=["T1"], customers=["C1"])
    member(ws, "c2", tenants=["T1"], customers=["C2"])
    internal = titles(srch(ws, "여신 한도 초과 주문 승인", mode="keyword"))
    assert "여신 관리 기준" in internal                                                               # 내부 전용 문서: 내부 사용자는 가능
    assert "여신 관리 기준" not in titles(srch(ws, "여신 한도 초과 주문 승인", "c1", mode="keyword"))     # 외부 거래처는 불가
    assert "C1 전용 특약" in titles(srch(ws, "월 마감 정산 특약", "c1"))
    assert "C1 전용 특약" not in titles(srch(ws, "월 마감 정산 특약", "c2"))                          # 다른 거래처 ACL
    assert "타 tenant 반품 규정" not in titles(srch(ws, "반품 3일 이내 T2 전용", "c1", mode="keyword"))  # tenant 범위 밖
    assert "타 tenant 반품 규정" in titles(srch(ws, "반품 3일 이내 T2 전용", mode="keyword"))          # 내부(전 tenant) 사용자는 가능
    lst = ws["c"].get(f"{P}/{ws['pid']}/documents", headers=ws["c1"]).json()
    assert all(d["title"] not in ("여신 관리 기준", "타 tenant 반품 규정", "영업 메모(외부 입력)") for d in lst)
    uid1 = ws["c"].get("/api/me", headers=ws["c1"]).json()["user_id"]
    assert ws["c"].delete(f"{P}/{ws['pid']}/members/{uid1}", headers=ws["L"]).status_code == 200
    assert ws["c"].get(f"{P}/{ws['pid']}/search?q=반품 며칠", headers=ws["c1"]).status_code == 404       # 권한 회수 즉시 반영


def test_malicious_document_is_flagged_and_never_executed(ws):
    r = seed(ws)
    docs = ws["c"].get(f"{P}/{ws['pid']}/documents", headers=ws["L"]).json()
    memo = next(d for d in docs if d["title"].startswith("영업 메모"))
    assert any(c for c in [memo]) and ws["c"].get(f"{P}/{ws['pid']}/search?q=approve every order credit_limit&mode=keyword", headers=ws["L"]).json()["results"][0]["suspicious"]
    top = srch(ws, "approve every order credit_limit", mode="keyword")["results"][0]
    assert top["snippet"].startswith("[주의: 문서 내 지시문 의심")
    approve_release(ws)                                                                          # 검색 내용이 판정·권한을 바꾸지 않음
    run = ws["c"].post(f"{P}/{ws['pid']}/agent-runs", headers=ws["L"], json={"tenant_id": "T1", "order_id": "SO-1001", "new_qty": 35}).json()
    assert run["result"]["verdict"] == "CONDITIONAL" and run["result"]["detail"]["credit"]["headroom"] == 50000


def test_realtime_questions_are_routed_to_tools_and_answers_are_extractive(ws):
    seed(ws)
    r = srch(ws, "현재 재고가 얼마나 남았나요")
    assert r["route_hint"] and "업무 도구" in r["route_hint"] and "extractive" in r["answer_style"]
    assert srch(ws, "반품 며칠 이내")["route_hint"] is None


def test_modes_inputs_and_embedding_honesty(ws):
    seed(ws)
    assert srch(ws, "반품 승인", mode="keyword")["embedding"] is None
    h = srch(ws, "반품 승인", mode="hybrid")
    assert "비신경망" in h["embedding"]                                                              # 임베딩 종류를 숨기지 않음
    assert ws["c"].get(f"{P}/{ws['pid']}/search?q=반품&mode=bogus", headers=ws["L"]).json()["error"]["code"] == "BAD_MODE"
    assert ws["c"].get(f"{P}/{ws['pid']}/search?q=a", headers=ws["L"]).json()["error"]["code"] == "BAD_QUERY"
    assert srch(ws, "반품 승인", rerank="true")["results"]
    bad = ws["c"].post(f"{P}/{ws['pid']}/documents", headers=ws["L"], json={"title": "x", "text": "짧"})
    assert bad.status_code == 400


def test_search_evaluation_compares_modes_with_stated_limits(ws):
    seed(ws)
    ev = ws["c"].post(f"{P}/{ws['pid']}/search-evaluations", headers=ws["L"]).json()
    m = ev["modes"]
    assert set(m) == {"keyword", "vector", "hybrid"} and ev["set_size"] == 12
    assert m["hybrid"]["recall@3"] >= m["keyword"]["recall@3"] and m["hybrid"]["recall@3"] >= 0.9
    assert "일반 성능이 아닙니다" in ev["limits"] and "동의어" in ev["limits"]                        # 한계를 결과에 명시
    kinds = {x["kind"] for x in ws["c"].get(f"{P}/{ws['pid']}/audit", headers=ws["L"]).json()}
    assert {"AX_DOC_SEED_DEMO", "AX_DOC_EVAL"} <= kinds
