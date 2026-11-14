"""AX 매출처·매입처 시나리오 도구, 범위(tenant·거래처·공급처), 적극적 지원 신호, 도구 계약 테스트. 합성 fixture 기준."""
import sqlite3
import pytest
from test_at import client, env, login  # noqa: F401
from test_ax import ws, approve_release, uid, P  # noqa: F401
from backend import ax, ax_tools

AS = "2026-11-14"


def ask(w, who="L", **kw):
    return w["c"].post(f"{P}/{w['pid']}/agent-runs", headers=w[who], json=kw)


def result(w, qt, **kw):
    r = ask(w, question_type=qt, tenant_id="T1", **kw)
    assert r.status_code == 200, r.text
    return r.json()["result"]


def member(w, name, **scope):
    h = login(w["c"], "learner", name)
    u = uid({"c": w["c"], "X": h}, "X")
    r = w["c"].post(f"{P}/{w['pid']}/members", headers=w["L"], json=dict(user_id=u, role="business_user", **scope))
    assert r.status_code == 200
    w[name] = h
    return u


# ---- 매출처
def test_delay_alternatives_partial_split_wait(ws):
    approve_release(ws)
    r = result(ws, "delay_alternatives", order_id="SO-1001", new_qty=35, as_of=AS)
    assert r["verdict"] == "DELAY_RISK" and r["detail"]["shortage"] == 3
    o = {a["option"]: a for a in r["alternatives"]}
    assert o["PARTIAL_NOW"]["qty_now"] == 32 and o["SPLIT"]["delay_days"] == 4 and o["SPLIT"]["later_date"] == "2026-11-20" and o["WAIT_ALL"]["qty"] == 35
    assert "미확인" in r["detail"]["inbound_confirmation"]                                    # 입고 확정도는 단정하지 않음
    assert result(ws, "delay_alternatives", order_id="SO-1001", as_of=AS)["verdict"] == "ON_TIME_FROM_STOCK"
    assert result(ws, "delay_alternatives", order_id="SO-9999", as_of=AS)["verdict"] == "NOT_FOUND"


def test_price_diff_uses_contract_valid_on_order_date_and_drafts_not_sent(ws):
    approve_release(ws)
    r = result(ws, "price_diff_reason", order_id="SO-1002")
    assert r["verdict"] == "BILLED_ABOVE_CONTRACT" and r["detail"]["diff"] == 50 and r["detail"]["diff_pct"] == 5.26
    assert "발송되지 않음" in r["drafts"][0] and "미확인" in r["detail"]["not_modeled"]        # 세금·통화 등은 모른다고 표시
    assert result(ws, "price_diff_reason", order_id="SO-1001")["verdict"] == "MATCHES_CONTRACT"
    con = sqlite3.connect(ax._fixture_path(ws["pid"]))
    con.execute("update contract set valid_to='2026-10-31' where tenant_id='T1' and contract_id='K2'")        # 주문일(11-10)에 유효한 계약이 없게
    con.commit(); con.close()
    assert result(ws, "price_diff_reason", order_id="SO-1002")["verdict"] == "NO_VALID_CONTRACT"


def test_receivable_summary_asof_and_credit_reconcile(ws):
    approve_release(ws)
    r = result(ws, "receivable_summary", customer_id="C1")["detail"]
    assert (r["invoiced"], r["paid"], r["returned"], r["balance"]) == (100000, 45000, 5000, 50000) and r["matches_credit_used"]
    old = result(ws, "receivable_summary", customer_id="C1", as_of="2026-11-02")["detail"]
    assert old["balance"] == 100000 and old["paid"] == 0                                    # 기준일 이후 전표는 제외
    assert result(ws, "receivable_summary", customer_id="C9")["verdict"] == "NOT_FOUND"


# ---- 매입처
def test_purchase_reorder_moq_pack_inbound_and_weighted_rank(ws):
    approve_release(ws)
    assert result(ws, "purchase_reorder", product_id="PRD1", needed_qty=3, as_of=AS)["verdict"] == "COVERED_BY_INBOUND"
    r = result(ws, "purchase_reorder", product_id="PRD1", needed_qty=150, as_of=AS)
    assert r["verdict"] == "ORDER_OPTIONS" and r["detail"]["remaining_after_inbound"] == 50 and r["recommended"] == "S2"
    by = {o["supplier_id"]: o for o in r["alternatives"]}
    assert (by["S1"]["order_qty"], by["S1"]["total_cost"]) == (60, 46800)                   # pack 20 의 배수로 올림, MOQ 40 이상
    assert (by["S2"]["order_qty"], by["S2"]["surplus"]) == (50, 0)
    assert (by["S3"]["order_qty"], by["S3"]["surplus"]) == (100, 50)                        # MOQ 100 때문에 과발주
    assert r["detail"]["weights"] == {"total_cost": 0.5, "lead_days": 0.3, "quality": 0.2} and all("score_parts" in o for o in r["alternatives"])
    assert result(ws, "purchase_reorder", product_id="PRD1", needed_qty=150, as_of="2027-06-01")["verdict"] == "NO_VALID_QUOTE"   # 견적 유효기간 밖


def test_supplier_weights_come_from_approved_release_and_must_sum_to_one(ws):
    c, pid = ws["c"], ws["pid"]
    base = c.post(f"{P}/{pid}/ontology-releases", headers=ws["L"], json={"template": "distribution_ax"}).json()
    spec = c.get(f"{P}/{pid}/ontology-releases/{base['release_id']}", headers=ws["L"]).json()["spec"]
    for po in spec["policies"]:
        if po["id"] == "purchase_reorder":
            po["weights"] = {"total_cost": 0.9, "lead_days": 0.3, "quality": 0.2}
    bad = c.post(f"{P}/{pid}/ontology-releases", headers=ws["L"], json={"spec": spec, "version": "9.0.0"}).json()
    v = c.post(f"{P}/{pid}/ontology-releases/{bad['release_id']}/validate", headers=ws["L"]).json()
    assert "POLICY_WEIGHTS_INVALID" in {e["code"] for e in v["errors"]}
    for po in spec["policies"]:
        if po["id"] == "purchase_reorder":
            po["weights"] = {"total_cost": 0.1, "lead_days": 0.1, "quality": 0.8}         # 품질 우선 정책
    good = c.post(f"{P}/{pid}/ontology-releases", headers=ws["L"], json={"spec": spec, "version": "2.0.0"}).json()
    assert c.post(f"{P}/{pid}/ontology-releases/{good['release_id']}/validate", headers=ws["L"]).json()["ok"]
    assert c.post(f"{P}/{pid}/ontology-releases/{good['release_id']}/review", headers=ws["R"], json={"decision": "approve", "note": "품질 우선 가중치 승인"}).status_code == 200
    r = ask(ws, question_type="purchase_reorder", tenant_id="T1", product_id="PRD1", needed_qty=150, as_of=AS, release_id=good["release_id"]).json()["result"]
    assert r["detail"]["weights"]["quality"] == 0.8 and r["recommended"] in ("S1", "S2")  # 품질 A 인 공급처가 우선(S3=B 불리)
    assert r["alternatives"][-1]["supplier_id"] == "S3"


def test_supplier_switch_quality_constraint_and_policy_missing_in_release(ws):
    c, pid = ws["c"], ws["pid"]
    approve_release(ws)
    r = result(ws, "supplier_switch", product_id="PRD1", current_supplier_id="S1", needed_qty=50, as_of=AS)
    assert r["verdict"] == "ALTERNATIVES_AVAILABLE" and r["alternatives"][0]["supplier_id"] == "S2" and r["alternatives"][0]["vs_current"]["cost_diff"] == -11800
    cn = sqlite3.connect(ax._fixture_path(pid))
    out = ax_tools.supplier_switch(ax.ax_db.SqliteConn(cn), {"tenant_id": "T1", "product_id": "PRD1", "current_supplier_id": "S1", "needed_qty": 50}, {"min_quality_grade": "A"}, AS)
    assert [o["supplier_id"] for o in out["alternatives"]] == ["S2"] and out["detail"]["excluded"][0]["supplier_id"] == "S3" and "등급 B" in out["detail"]["excluded"][0]["reason"]
    cn.close()
    # 승인된 release 에 정책이 없으면 도구를 실행하지 않는다
    base = c.post(f"{P}/{pid}/ontology-releases", headers=ws["L"], json={"template": "distribution_ax", "version": "3.0.0"}).json()
    spec = c.get(f"{P}/{pid}/ontology-releases/{base['release_id']}", headers=ws["L"]).json()["spec"]
    spec["policies"] = [p for p in spec["policies"] if p["id"] == "change_order_increase"]
    old = c.post(f"{P}/{pid}/ontology-releases", headers=ws["L"], json={"spec": spec, "version": "3.0.1"}).json()
    c.post(f"{P}/{pid}/ontology-releases/{old['release_id']}/validate", headers=ws["L"])
    c.post(f"{P}/{pid}/ontology-releases/{old['release_id']}/review", headers=ws["R"], json={"decision": "approve", "note": "구형 정책만 포함"})
    r = ask(ws, question_type="price_spike", tenant_id="T1", supplier_id="S1", product_id="PRD1", release_id=old["release_id"])
    assert r.status_code == 409 and r.json()["error"]["code"] == "POLICY_NOT_IN_RELEASE"


def test_price_spike_threshold_and_negotiation_draft(ws):
    approve_release(ws)
    r = result(ws, "price_spike", supplier_id="S1", product_id="PRD1", as_of=AS)
    assert r["verdict"] == "SPIKE" and r["detail"]["change_pct"] == 30.0 and "발송되지 않음" in r["drafts"][0]
    assert {x["supplier_id"] for x in r["detail"]["alternatives_current_cost"]} == {"S2", "S3"}
    assert result(ws, "price_spike", supplier_id="S1", product_id="PRD1", as_of="2026-06-01")["verdict"] == "NO_PREVIOUS_QUOTE"
    assert result(ws, "price_spike", supplier_id="S2", product_id="PRD1", as_of=AS)["verdict"] == "NO_PREVIOUS_QUOTE"


def test_receipt_variance_tolerance(ws):
    approve_release(ws)
    r = result(ws, "receipt_variance", po_id="PO-2")
    assert r["verdict"] == "OUT_OF_TOLERANCE" and r["detail"]["variance_pct"] == 4.0 and "발송되지 않음" in r["drafts"][0]
    assert result(ws, "receipt_variance", po_id="PO-3")["verdict"] == "WITHIN_TOLERANCE"
    assert result(ws, "receipt_variance", po_id="PO-1")["verdict"] == "NOT_RECEIVED_YET"
    assert result(ws, "receipt_variance", po_id="PO-9")["verdict"] == "NOT_FOUND"


# ---- 범위·입력 검증
def test_external_scopes_for_customers_and_suppliers(ws):
    approve_release(ws)
    member(ws, "cust1", tenants=["T1"], customers=["C1"])
    member(ws, "sup2", tenants=["T1"], suppliers=["S2"])
    ok = ask(ws, "cust1", question_type="receivable_summary", tenant_id="T1", customer_id="C1")
    assert ok.status_code == 200
    for qt, kw, code in (("receivable_summary", dict(customer_id="C2"), "CUSTOMER_SCOPE_DENIED"), ("price_diff_reason", dict(order_id="SO-1002"), "CUSTOMER_SCOPE_DENIED"),
                         ("purchase_reorder", dict(product_id="PRD1", needed_qty=10), "INTERNAL_ONLY"), ("price_spike", dict(supplier_id="S1", product_id="PRD1"), "INTERNAL_ONLY"),
                         ("receipt_variance", dict(po_id="PO-3"), "INTERNAL_ONLY")):
        r = ask(ws, "cust1", question_type=qt, tenant_id="T1", **kw)
        assert r.status_code == 403 and r.json()["error"]["code"] == code, (qt, r.text)
    assert ask(ws, "sup2", question_type="receipt_variance", tenant_id="T1", po_id="PO-3").status_code == 200       # 본인 공급처 발주
    for qt, kw, code in (("receipt_variance", dict(po_id="PO-2"), "SUPPLIER_SCOPE_DENIED"), ("price_spike", dict(supplier_id="S2", product_id="PRD1"), "INTERNAL_ONLY"),
                         ("supplier_switch", dict(product_id="PRD1", current_supplier_id="S2", needed_qty=5), "INTERNAL_ONLY"), ("delay_alternatives", dict(order_id="SO-1001"), "SUPPLIER_CANNOT_USE_SALES")):
        r = ask(ws, "sup2", question_type=qt, tenant_id="T1", **kw)
        assert r.status_code == 403 and r.json()["error"]["code"] == code, (qt, r.text)
    assert ask(ws, "sup2", tenant_id="T1", order_id="SO-1001", new_qty=30).json()["error"]["code"] == "SUPPLIER_CANNOT_USE_SALES"   # 기존 증량 도구도 동일
    r = ask(ws, "cust1", question_type="receivable_summary", tenant_id="T2", customer_id="C1")
    assert r.status_code == 403 and r.json()["error"]["code"] == "TENANT_SCOPE_DENIED"


def test_tool_inputs_are_validated_against_contract(ws):
    approve_release(ws)
    bad = lambda **kw: ask(ws, tenant_id="T1", **kw)
    assert bad(question_type="price_spike", supplier_id="S1", product_id="PRD1", as_of="2026-11-14'; DROP TABLE x").json()["error"]["code"] == "BAD_PARAM"
    assert bad(question_type="price_spike", supplier_id="S1", product_id="PRD1", as_of="2026-13-45").json()["error"]["code"] == "BAD_PARAM"
    assert bad(question_type="purchase_reorder", product_id="PRD1", needed_qty="10; DROP").json()["error"]["code"] == "BAD_QTY"
    assert bad(question_type="purchase_reorder", product_id="PRD1", needed_qty=-5).json()["error"]["code"] == "BAD_QTY"
    assert bad(question_type="receipt_variance", po_id="PO-1", extra="x").json()["error"]["code"] == "BAD_PARAM"        # 계약에 없는 입력 거부
    assert bad(question_type="receipt_variance").json()["error"]["code"] == "BAD_PARAM"
    assert bad(question_type="unknown_tool").json()["error"]["code"] == "UNSUPPORTED_QUESTION"
    t = ws["c"].get(f"{P}/{ws['pid']}/tools", headers=ws["L"]).json()
    assert {x["name"] for x in t} == {"order_increase", "delay_alternatives", "price_diff_reason", "receivable_summary", "purchase_reorder", "supplier_switch", "price_spike", "receipt_variance", "entity_lookup", "entity_related"}
    assert all(x["side_effect"] == "none" and x["input_schema"]["additionalProperties"] is False and x["timeout_s"] for x in t)


# ---- 적극적 지원 신호
def test_signals_detect_dedupe_ack_resolve_and_internal_only(ws):
    c, pid = ws["c"], ws["pid"]
    scan = lambda **kw: c.post(f"{P}/{pid}/signals/scan", headers=ws["L"], json=dict(as_of="2026-12-01", **kw)).json()
    first = scan()
    sig = c.get(f"{P}/{pid}/signals", headers=ws["L"]).json()
    kinds = {x["kind"] for x in sig}
    assert {"CONTRACT_EXPIRING", "RECEIPT_OUT_OF_TOLERANCE"} <= kinds and "STOCK_SHORT" not in kinds and first["new"] == len(sig)
    assert scan()["new"] == 0                                                                # 중복 억제
    con = sqlite3.connect(ax._fixture_path(pid))
    con.execute("update sales_orders set requested_qty=90, row_version=row_version+1 where tenant_id='T1' and order_id='SO-1002'")      # 예약 > 재고
    con.commit()
    r = scan()
    sig = {x["kind"] + x["ref"]: x for x in c.get(f"{P}/{pid}/signals", headers=ws["L"]).json()}
    assert r["new"] >= 3 and sig["STOCK_SHORTT1:PRD1"]["class"] == "FACT" and sig["DELIVERY_RISKT1:SO-1001"]["class"] == "ASSUMPTION"   # 입고 예정은 가정
    assert "제안/탐지만" in sig["STOCK_SHORTT1:PRD1"]["proposal_note"] and sig["STOCK_SHORTT1:PRD1"]["valid_until"] == "2026-12-08"
    sid = "STOCK_SHORTT1:PRD1"
    full = f"{pid}:STOCK_SHORT:T1:PRD1"
    assert c.post(f"{P}/{pid}/signals/{full}/ack", headers=ws["L"], json={"status": "DISMISSED"}).json()["error"]["code"] == "NOTE_REQUIRED"
    assert c.post(f"{P}/{pid}/signals/{full}/ack", headers=ws["L"], json={"status": "ACK"}).json()["status"] == "ACK"
    con.execute("update sales_orders set requested_qty=68, row_version=row_version+1 where tenant_id='T1' and order_id='SO-1002'")      # 해소
    con.commit(); con.close()
    r = scan()
    after = {x["kind"] + x["ref"]: x["status"] for x in c.get(f"{P}/{pid}/signals", headers=ws["L"]).json()}
    assert r["resolved"] >= 3 and after["STOCK_SHORTT1:PRD1"] == "RESOLVED"
    member(ws, "cust1", tenants=["T1"], customers=["C1"])
    assert c.get(f"{P}/{pid}/signals", headers=ws["cust1"]).status_code == 403                # 외부 사용자는 inbox 접근 불가
    assert not any(x for x in ax.audit_list({"user_id": "x", "role": "admin"}, pid) if x["kind"] == "AX_COMMAND_EXEC")        # 탐지는 어떤 업무 명령도 실행하지 않음
