"""생성형 AI·RAG 시뮬레이션: 토큰화·BM25·인덱스 STALE/동기화·Playground·RAG 에이전트·평가·서빙."""
from test_at import client, env, sql, start_wh, fix_perm  # noqa: F401
from backend import ext_genai as G

IDX = "food_dev.gold.doc_index"
AGENT = "food_dev.gold.doc_assistant"


def post(e, path, body=None, who="L"):
    return e["c"].post(f"/api/sessions/{e['sid']}/genai{path}", headers=e[who], json=body or {})


def ok(r):
    assert r.status_code == 200, r.text
    return r.json()


def setup_index(e):
    start_wh(e)
    fix_perm(e)
    ok(post(e, "/docs/sample"))
    return ok(post(e, "/index", {"name": IDX, "source": G.DOC_TABLE, "pk": "doc_id", "text_col": "content", "meta_cols": ["category", "title"]}))


def setup_agent(e, **kw):
    cfg = {"name": AGENT, "index": IDX, "k": 3, "system": "당신은 문서 도우미입니다. 컨텍스트에 있는 내용만 설명하세요.", "style": "paragraph", **kw}
    return ok(post(e, "/agent/register", cfg))


# ---------------------------------------------------------------- 순수 함수
def test_tokenize_and_bm25_order():
    assert G.tokenize("권한 SELECT the") == ["권한", "select"]                     # 한글 bi-gram, 영문 소문자, 불용어 제거
    assert G.tokenize("서버리스") == ["서버", "버리", "리스"]
    assert G.tokenize("가") == ["가"]
    docs = [G.tokenize(d[2]) for d in G.DOCS]
    sc = G._bm25(docs, G.tokenize("COPY INTO 중복"))
    assert G.DOCS[max(range(len(sc)), key=lambda i: sc[i])][0] == "D09"
    assert G._bm25([], ["x"]) == []


def test_prompt_assembly_and_checklist():
    a = G.assemble_prompt("당신은 도우미입니다.", "{{topic}}을 한 문장으로 설명하세요. {{missing}}", {"topic": "Delta"}, "Delta는 버전을 기록합니다.", "무엇인가요?")
    assert "Delta을 한 문장으로" in a["prompt"] and a["missing_variables"] == ["missing"] and a["tokens_estimate"] == -(-len(a["prompt"]) // 4)
    assert a["prompt"].index("[SYSTEM]") < a["prompt"].index("[CONTEXT]") < a["prompt"].index("[USER]")
    good = G.checklist("당신은 도우미입니다. 컨텍스트에 없으면 모른다고 답하세요. 한 문장으로 요약하세요. 예시: Q: a", "", "ctx")
    assert all(i["ok"] for i in good["items"]) and good["score"] == 1.0
    bad = G.checklist("", "", "")
    assert bad["score"] == 0 and all(i["hint"] for i in bad["items"])
    assert G.detect_style("JSON으로 답하세요") == "json" and G.detect_style("불릿으로") == "bullets" and G.detect_style("한 문장으로") == "sentence"


def test_mock_model_does_not_invent():
    assert "답할 수 없습니다" in G.mock_generate("", "", "질문")["text"]
    r = G.mock_generate("한 문장으로", "COPY INTO는 멱등합니다. 날씨는 맑습니다.", "COPY INTO 멱등")
    assert r["text"] == "COPY INTO는 멱등합니다." and r["style"] == "sentence"


# ---------------------------------------------------------------- 인덱스
def test_sample_docs_idempotent(env):
    start_wh(env); fix_perm(env)
    a = ok(post(env, "/docs/sample"))
    b = ok(post(env, "/docs/sample"))
    assert a["created"] is True and b["created"] is False and a["rows"] == len(G.DOCS) >= 20
    assert sql(env, f"SELECT count(*) FROM {G.DOC_TABLE}")["result"]["rows"][0][0] == len(G.DOCS)


def test_index_query_ranking_and_meta_filter(env):
    ix = setup_index(env)
    assert ix["state"] == "ONLINE" and ix["rows"] == len(G.DOCS)
    r = ok(post(env, "/index/query", {"name": IDX, "query": "테이블을 조회하려면 USE SCHEMA 권한이 필요한가요", "k": 3}))
    assert r["hits"][0]["pk"] == "D02" and [h["rank"] for h in r["hits"]] == [1, 2, 3] and r["hits"][0]["score"] >= r["hits"][1]["score"]
    f = ok(post(env, "/index/query", {"name": IDX, "query": "권한 테이블", "k": 10, "filters": {"category": "pipeline"}}))
    assert f["hits"] and all(h["meta"]["category"] == "pipeline" for h in f["hits"])
    bad = post(env, "/index/query", {"name": IDX, "query": "x", "filters": {"nope": 1}})
    assert bad.status_code == 400 and bad.json()["error"]["code"] == "INVALID_FILTER"
    assert post(env, "/index/query", {"name": "food_dev.gold.none", "query": "x"}).status_code == 404


def test_index_stale_then_sync(env):
    setup_index(env)
    assert ok(env["c"].get(f"/api/sessions/{env['sid']}/genai", headers=env["L"]))["indexes"][0]["state"] == "ONLINE"
    assert sql(env, f"INSERT INTO {G.DOC_TABLE} VALUES ('D99', '새 문서', '쿼카 프로토콜은 새로 추가된 문서입니다.', 'misc')")["status"] == "ok"
    ov = ok(env["c"].get(f"/api/sessions/{env['sid']}/genai", headers=env["L"]))
    assert ov["indexes"][0]["state"] == "STALE" and "동기화" in ov["indexes"][0]["hint"]
    miss = ok(post(env, "/index/query", {"name": IDX, "query": "쿼카 프로토콜", "k": 3}))
    assert not miss["hits"] and miss["state"] == "STALE"                           # 동기화 전에는 새 문서를 못 찾는다
    s = ok(post(env, "/index/sync", {"name": IDX}))
    assert s["state"] == "ONLINE" and s["rows"] == len(G.DOCS) + 1 and s["sync_count"] == 2
    assert ok(post(env, "/index/query", {"name": IDX, "query": "쿼카 프로토콜", "k": 3}))["hits"][0]["pk"] == "D99"


def test_index_permission_denied(env):
    r = post(env, "/index", {"name": "food_dev.gold.bad_idx", "source": "food_dev.silver.orders", "pk": "order_id", "text_col": "status"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "INSUFFICIENT_PERMISSIONS"
    r = post(env, "/index", {"name": "bad name", "source": G.DOC_TABLE, "pk": "doc_id", "text_col": "content"})
    assert r.json()["error"]["code"] == "INVALID_NAME"


def test_index_delete_blocked_when_used(env):
    setup_index(env); setup_agent(env)
    r = post(env, "/index/delete", {"name": IDX})
    assert r.status_code == 409 and r.json()["error"]["code"] == "INDEX_IN_USE"


# ---------------------------------------------------------------- Playground
def test_playground_endpoint_and_compare(env):
    v1 = {"system": "", "template": "", "context": "Delta는 쓰기마다 버전을 기록합니다. 날씨는 맑습니다.", "user": "Delta 버전"}
    v2 = {"system": "당신은 도우미입니다. 컨텍스트에 있는 내용만 한 문장으로 설명하세요.", "template": "{{topic}}를 설명하세요.", "variables": {"topic": "Delta"}, "context": v1["context"], "user": "Delta 버전"}
    r = ok(post(env, "/playground", {"variants": [v1, v2]}))
    a, b = r["variants"]
    assert b["checklist"]["score"] > a["checklist"]["score"] and b["style"] == "sentence" and "모의" in r["note"]
    assert post(env, "/playground", {"variants": [v1, v1, v1]}).status_code == 400
    assert post(env, "/playground", {"user": ""}).status_code == 400


# ---------------------------------------------------------------- 에이전트 · trace
def test_agent_run_trace_and_citations(env):
    setup_index(env)
    v = setup_agent(env)
    assert v["version"] == 1 and setup_agent(env, k=2)["version"] == 2
    t = ok(post(env, "/agent/run", {"name": AGENT, "version": 1, "question": "COPY INTO를 반복 실행하면 중복되나요?"}))
    assert [s["name"] for s in t["spans"]] == ["retrieve", "build_prompt", "generate"] and t["retrieved"][0] == "D09" and "D09" in t["citations"]
    assert "중복되지" in t["answer"] and t["spans"][2]["inputs"]["model"].startswith("mock")
    none = ok(post(env, "/agent/run", {"name": AGENT, "question": "ㅋㅋㅋ zzzqqq"}))
    assert none["citations"] == [] and "찾지 못" in none["answer"]
    ov = ok(env["c"].get(f"/api/sessions/{env['sid']}/genai", headers=env["L"]))
    assert len(ov["traces"]) == 2 and ov["agents"][0]["versions"][1]["k"] == 2
    assert post(env, "/agent/run", {"name": "food_dev.gold.nope", "question": "x"}).status_code == 404
    assert post(env, "/agent/register", {"name": AGENT, "index": "food_dev.gold.nope"}).status_code == 404


# ---------------------------------------------------------------- 평가
def test_eval_metrics_hand_checked(env):
    setup_index(env); setup_agent(env)
    es = [{"question": "COPY INTO를 반복 실행하면 중복되나요?", "expected_docs": ["D09"], "keywords": ["중복되지", "없는단어"]},
          {"question": "COPY INTO를 반복 실행하면 중복되나요?", "expected_docs": ["NOPE"], "keywords": []}]
    r = ok(post(env, "/eval", {"agent": AGENT, "versions": [1], "eval_set": es, "threshold": 0.8}))["results"][0]
    p = r["per_question"]
    assert p[0]["rank"] == 1 and p[0]["hit"] == 1 and p[0]["rr"] == 1.0 and p[1]["rank"] is None and p[1]["rr"] == 0.0
    assert r["metrics"]["hit_at_k"] == 0.5 and r["metrics"]["mrr"] == 0.5 and r["metrics"]["keyword_rate"] == 0.5     # 키워드: 2개 중 1개
    assert r["passed"] is False and 0 <= r["metrics"]["groundedness"] <= 1 and p[0]["grounded"] == 1.0
    full = ok(post(env, "/eval", {"agent": AGENT, "versions": [1]}))["results"][0]
    assert full["questions"] == len(G.SAMPLE_EVAL) and full["metrics"]["hit_at_k"] >= 0.8 and full["passed"] is True


def test_eval_ab_versions_and_limits(env):
    setup_index(env); setup_agent(env, k=1); setup_agent(env, k=5)
    r = ok(post(env, "/eval", {"agent": AGENT, "versions": [1, 2]}))["results"]
    assert [x["version"] for x in r] == [1, 2] and r[1]["metrics"]["hit_at_k"] >= r[0]["metrics"]["hit_at_k"]
    assert post(env, "/eval", {"agent": AGENT, "versions": [1, 2, 1]}).status_code == 400
    assert post(env, "/eval", {"agent": AGENT, "versions": [9]}).status_code == 404
    assert len(ok(env["c"].get(f"/api/sessions/{env['sid']}/genai", headers=env["L"]))["evals"]) == 2


# ---------------------------------------------------------------- 서빙(공용 계층)
def test_agent_serving_lifecycle(env):
    setup_index(env); setup_agent(env)
    c, sid, L = env["c"], env["sid"], env["L"]
    base = f"/api/sessions/{sid}/serving"
    mk = lambda n: c.post(base, headers=L, json={"name": n, "kind": "agent", "config": {"agent": AGENT, "version": 1}})
    assert mk("doc-agent").status_code == 200 and mk("doc-agent2").status_code == 200
    over = mk("doc-agent3")
    assert over.status_code == 429 and over.json()["error"]["code"] == "SERVING_QUOTA"
    q = c.post(f"{base}/doc-agent/query", headers=L, json={"messages": [{"role": "user", "content": "서버리스 웨어하우스는 언제 켜지나요?"}]}).json()
    assert q["kind"] == "agent" and "자동" in q["result"]["choices"][0]["message"]["content"] and q["result"]["citations"][0] == "D04" and q["evidence_level"] == "SIMULATED"
    assert c.post(f"{base}/doc-agent/query", headers=L, json={"messages": []}).status_code == 400
    assert c.post(f"{base}/doc-agent/delete", headers=L).status_code == 200
    assert mk("doc-agent3").status_code == 200                                   # 삭제하면 슬롯이 돌아온다
    assert [e["queries"] for e in c.get(base, headers=L).json()["endpoints"] if e["name"] == "doc-agent2"] == [0]
