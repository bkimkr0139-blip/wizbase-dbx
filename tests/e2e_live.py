"""전 여정 E2E (실서버 대상). 학습자/관리자/리뷰어/강사 4개 역할로 15단계를 끝까지 수행하고 단계별 판정을 출력한다.
사용: python tests/e2e_live.py http://127.0.0.1:8830"""
import sys, json, httpx, pathlib

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8830"
codes = json.loads((pathlib.Path(__file__).resolve().parent.parent / "data" / ".staff_codes.json").read_text())
c = httpx.Client(base_url=BASE, timeout=60)
res = []


def chk(name, cond, detail=""):
    res.append((name, bool(cond), detail))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail and not cond else ""))


def login(role, name, code=None):
    r = c.post("/api/auth/login", json={"name": name, "role": role, "code": code}); r.raise_for_status()
    return {"Authorization": "Bearer " + r.json()["token"]}


L, A, R, I = login("learner", "e2e"), login("admin", "adm", codes["admin"]), login("reviewer", "rev", codes["staff"]), login("instructor", "ins", codes["instructor"])
sid = c.post("/api/sessions", headers=L, json={"learning_mode": "guided"}).json()["session_id"]


def cmd(t, p=None, who=L):
    r = c.post(f"/api/sessions/{sid}/commands", headers=who, json={"command_type": t, "payload": p or {}})
    assert r.status_code == 200, r.text
    return r.json()


def api(method, path, who=L, **kw):
    return c.request(method, path.replace("{sid}", sid), headers=who, **kw)


def guide():
    return api("GET", "/api/sessions/{sid}/guide").json()


def step(id_):
    return next(s for s in guide()["steps"] if s["id"] == id_)


# 1 env
cmd("env.check"); cmd("feature.use", {"feature_id": "oracle_cdc"}); cmd("warehouse", {"action": "start"}); cmd("env.check"); cmd("env.check")
chk("S1 환경 단계 완료", step("env")["status"] == "done")
cmd("guide.ack", {"key": "req"}); chk("S2 요구 단계 완료", step("req")["status"] == "done")
# 3 perm
r = cmd("sql.execute", {"sql": "SELECT * FROM food_dev.silver.orders LIMIT 3"}); chk("S3a 권한 오류(USE SCHEMA)", r["status"] == "failed" and r["result"]["error"]["missing"]["privilege"] == "USE SCHEMA")
cmd("sql.execute", {"sql": "GRANT USE SCHEMA ON SCHEMA food_dev.silver TO `data-engineers`"})
t = api("POST", "/api/permission-requests", json={"session_id": sid, "securable": "schema:food_dev.silver", "privilege": "USE SCHEMA", "reason": "silver 조회 최소권한"}).json()
chk("S3b 학습자는 티켓을 승인할 수 없음", api("POST", f"/api/sessions/{{sid}}/tickets/{t['ticket_id']}/resolve", json={"decision": "approve"}).status_code == 403)
chk("S3c 관리자 승인", api("POST", f"/api/sessions/{{sid}}/tickets/{t['ticket_id']}/resolve", A, json={"decision": "approve"}).status_code == 200)
r = cmd("sql.execute", {"sql": "SELECT * FROM food_dev.silver.orders LIMIT 3"}); chk("S3d 재실행 성공", r["status"] == "ok")
chk("S3 권한 단계 완료", step("perm")["status"] == "done")
# 4 conn
cmd("connection", {"action": "select_mode", "mode": "federation"}); cmd("connection", {"action": "test"}); cmd("connection", {"action": "create_foreign_catalog"})
t = api("POST", "/api/permission-requests", json={"session_id": sid, "securable": "connection:oracle_food_conn", "privilege": "CREATE FOREIGN CATALOG", "reason": "foreign catalog 실습 최소권한"}).json()
api("POST", f"/api/sessions/{{sid}}/tickets/{t['ticket_id']}/resolve", A, json={"decision": "approve"})
t2 = api("POST", "/api/permission-requests", json={"session_id": sid, "securable": "metastore:main", "privilege": "CREATE CATALOG", "reason": "foreign catalog 생성에 필요(공식 privileges reference)"}).json()
api("POST", f"/api/sessions/{{sid}}/tickets/{t2['ticket_id']}/resolve", A, json={"decision": "approve"})
r = cmd("connection", {"action": "create_foreign_catalog"}); chk("S4 foreign catalog 생성(권한 2개)", r["status"] == "ok")
q = cmd("sql.execute", {"sql": "SELECT COUNT(*) FROM oracle_food.public.orders"}); chk("S4b foreign catalog 3단계 이름 조회", q["status"] == "ok" and q["result"]["rows"][0][0] == 313, str(q["result"].get("error")))
chk("S4 연결 단계 완료", step("conn")["status"] == "done")
# 5 recon
chk("S5a 초기 뷰는 계약과 다름", cmd("contract.check")["status"] == "failed")
cmd("sql.execute", {"sql": "CREATE OR REPLACE VIEW food_dev.gold.v_available_inventory AS SELECT product_id, SUM(on_hand_qty - reserved_qty - damaged_qty) AS available_qty FROM food_dev.silver.inventory GROUP BY product_id"})
chk("S5b 수정 후 정합성 일치", cmd("contract.check")["status"] == "ok"); chk("S5 정합성 단계 완료", step("recon")["status"] == "done")
# 6 pipeline
cmd("pipeline", {"action": "validate"}); r = cmd("pipeline", {"action": "run"}); chk("S6a 중복키로 FAILED", r["status"] == "failed")
cmd("pipeline", {"action": "edit", "source_sql": "SELECT order_id, customer_id, CAST(order_date AS DATE) AS order_date, status, CAST(version AS INTEGER) AS version FROM food_dev.bronze.raw_orders QUALIFY ROW_NUMBER() OVER (PARTITION BY order_id ORDER BY updated_at DESC) = 1"})
cmd("pipeline", {"action": "validate"}); r = cmd("pipeline", {"action": "run"})
chk("S6b 수정 후 SUCCEEDED·303행·격리4", r["status"] == "ok" and r["result"]["reconciliation"]["rows"] == 303 and r["result"]["reconciliation"]["quarantined"] == 4)
chk("S6 파이프라인 단계 완료", step("pipe")["status"] == "done")
# 6b cdc
cmd("sql.execute", {"sql": "SELECT * FROM food_dev.bronze.cdc_events ORDER BY seq"})
cmd("sql.execute", {"sql": "CREATE OR REPLACE TABLE food_dev.silver.customers_cdc AS WITH d AS (SELECT DISTINCT event_id, customer_id, op, city, seq FROM food_dev.bronze.cdc_events), l AS (SELECT * FROM d QUALIFY ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY seq DESC) = 1) SELECT customer_id, city FROM l WHERE op <> 'D'"})
chk("S6c CDC 1차 정합성", cmd("cdc.check")["status"] == "ok")
cmd("cdc.next_batch"); chk("S6d 새 배치 후 재적용 필요", cmd("cdc.check")["status"] == "failed")
cmd("sql.execute", {"sql": "CREATE OR REPLACE TABLE food_dev.silver.customers_cdc AS WITH d AS (SELECT DISTINCT event_id, customer_id, op, city, seq FROM food_dev.bronze.cdc_events), l AS (SELECT * FROM d QUALIFY ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY seq DESC) = 1) SELECT customer_id, city FROM l WHERE op <> 'D'"})
chk("S6e CDC 최종 정합성", cmd("cdc.check")["status"] == "ok"); chk("S6 CDC 단계 완료", step("cdc")["status"] == "done")
# 7 job
r = cmd("job", {"action": "run"}); chk("S7a svc-runner run-as 실패+후속 건너뜀", r["status"] == "failed" and r["result"]["tasks"]["summarize"]["reason"] == "UPSTREAM_FAILED")
cmd("job", {"action": "set_run_as", "run_as": "trainee@wizbase.training"}); chk("S7b 본인 run-as 성공", cmd("job", {"action": "run"})["status"] == "ok")
# 8 genie
cmd("genie.config", {"datasets": ["food_dev.gold.v_order_overview", "food_dev.gold.v_available_inventory"]})
chk("S8a Genie 질의", cmd("genie.ask", {"question": "총 주문 박스는?"})["result"]["status"] == "OK")
chk("S8b analyst-b 접근 차단", cmd("genie.ask", {"question": "P-001 가용재고는?", "as_persona": "analyst-b@wizbase.training"})["result"]["status"] == "DENIED")
# 9 order
f = cmd("order.facts", {"order_id": "O-10021", "requested_total": 35})["result"]
chk("S9a 가용재고 12·추가부족 3 (23 아님)", f["facts"]["available_qty"] == 12 and f["shortage"] == 3 and f["wrong_if_total_minus_free"] == 23)
pr = cmd("order.propose", {"order_id": "O-10021", "requested_total": 35})["result"]; p = pr["proposal"]
chk("S9b 원안(35) 실행 불가·승인형 대안(32)", pr["policy"]["decision"] == "REQUIRES_APPROVAL" and p["payload"]["new_qty"] == 32)
body = {"payload": p["payload"], "idempotency_key": "e2e-1", "expected_version": 1}
chk("S10a 무승인 실행 차단", api("POST", "/api/sessions/{sid}/ax/orders/O-10021/change", json=body).status_code == 403)
chk("S9c 학습자 승인 불가", api("POST", "/api/approvals", json={"session_id": sid, "proposal_id": p["proposal_id"], "payload_hash": p["payload_hash"]}).status_code == 403)
chk("S10b 해시 불일치 승인 거부", api("POST", "/api/approvals", R, json={"session_id": sid, "proposal_id": p["proposal_id"], "payload_hash": "0" * 64}).status_code == 400)
ap = api("POST", "/api/approvals", R, json={"session_id": sid, "proposal_id": p["proposal_id"], "payload_hash": p["payload_hash"]}).json()
bad = dict(p["payload"]); bad["new_qty"] = 40
chk("S10c 변조 payload 차단", api("POST", "/api/sessions/{sid}/ax/orders/O-10021/change", json={**body, "approval_id": ap["approval_id"], "payload": bad, "idempotency_key": "e2e-bad"}).status_code == 400)
ok = api("POST", "/api/sessions/{sid}/ax/orders/O-10021/change", json={**body, "approval_id": ap["approval_id"]}); chk("S9d 가상 API 실행", ok.status_code == 200 and ok.json()["post_reconciliation"] == "OK")
again = api("POST", "/api/sessions/{sid}/ax/orders/O-10021/change", json={**body, "approval_id": ap["approval_id"]}).json()
chk("S10d 멱등 재실행(동일 결과·1회 변경)", again.get("replayed") and again["action_id"] == ok.json()["action_id"] and cmd("sql.execute", {"sql": "SELECT COUNT(*) FROM food_dev.silver.action_audit"})["result"]["rows"][0][0] == 1)
api("POST", "/api/instructor/faults", I, json={"session_id": sid, "fault_id": "order_version_conflict"})
pr2 = cmd("order.propose", {"order_id": "O-10021", "requested_total": 40})["result"]
chk("S10e 버전 충돌 후 재조회로 새 제안", pr2["facts"]["order_version"] == 3)
p2 = pr2["proposal"]
if p2:
    ap2 = api("POST", "/api/approvals", R, json={"session_id": sid, "proposal_id": p2["proposal_id"], "payload_hash": p2["payload_hash"]})
    api("POST", "/api/instructor/faults", I, json={"session_id": sid, "fault_id": "order_version_conflict"})
    cf = api("POST", "/api/sessions/{sid}/ax/orders/O-10021/change", json={"approval_id": ap2.json()["approval_id"], "payload": p2["payload"], "idempotency_key": "e2e-c", "expected_version": 3})
    chk("S10f 승인 후 버전 변경 → 409 충돌", cf.status_code == 409 and cf.json()["error"]["code"] == "VERSION_CONFLICT")
chk("S9 주문 단계 완료", step("order")["status"] == "done"); chk("S10 서버 통제 단계 완료", step("safety")["status"] == "done", json.dumps([s["done"] for s in guide()["steps"] if s["id"] == "safety"]))
# 11 bundle
for l in ["databricks auth login --host https://training-workspace.invalid", "databricks bundle validate -t dev", "databricks bundle deploy -t dev"]:
    cmd("cli", {"line": l})
r = cmd("cli", {"line": "databricks bundle run -t dev training_job"}); chk("S11a 배포본 실행 성공", r["status"] == "ok")
cmd("bundle.edit", {"path": "src/check_data.sql", "content": "SELECT 999 AS changed"})
r = cmd("cli", {"line": "databricks bundle run -t dev training_job"}); chk("S11b 미배포 수정 → drift, 이전 코드 실행", r["result"]["run"]["drift"] and r["result"]["run"]["tasks"]["check_data"]["rows"][0][0] == 303)
cmd("cli", {"line": "databricks auth login --host https://example.cloud.databricks.com"})
chk("S11 Bundle 단계 완료", step("bundle")["status"] == "done"); chk("S14 통제 단계 완료", step("iso")["status"] == "done")
# 12 notebook
cmd("notebook", {"action": "add_cell", "lang": "sql", "code": "SELECT 1"}); cmd("notebook", {"action": "run", "cell_id": "c1"}); cmd("notebook", {"action": "run", "cell_id": "c2"})
cmd("notebook", {"action": "edit", "cell_id": "c1", "code": "SELECT 2"}); cmd("notebook", {"action": "restart"})
chk("S12 Notebook 단계 완료", step("nb")["status"] == "done")
# 13 eval
r = cmd("eval.run"); chk("S13 평가셋 40/40", r["result"]["passed"] == 40); cmd("guide.ack", {"key": "wrap"})
# 15 score
g = guide(); sc = api("GET", "/api/sessions/{sid}/score").json()
chk("S15a 설명 점수 전에는 수료 판정 불가", sc["core_completion"] is False and sc["explain_pending"])
api("POST", "/api/instructor/evaluate", I, json={"session_id": sid, "explain_score": 12})
sc = api("GET", "/api/sessions/{sid}/score").json(); print("점수", sc["areas"], "자동합계", sc["auto_total"], "수료", sc["core_completion"])
chk("S15b 전 단계 완료율 100%", guide()["percent"] == 100, f"{guide()['percent']}% next={guide()['next']}")
chk("S15c 필수 안전 항목 전부 통과", all(s["passed"] for s in sc["safety"]), str([s for s in sc["safety"] if not s["passed"]]))
ev = api("GET", "/api/sessions/{sid}/evidence").json(); chk("S15d 증거 보고서 필드", all(k in ev for k in ("mode", "profile", "seed", "data_digest_current", "sql_evidence", "limitations")))
rp = api("POST", "/api/instructor/replay", I, json={"session_id": sid}).json(); chk("S15e 결정적 재생 일치", rp["match"], json.dumps(rp)[:200])
fails = [r for r in res if not r[1]]
print(f"\n== E2E {len(res) - len(fails)}/{len(res)} PASS ==")
sys.exit(1 if fails else 0)
