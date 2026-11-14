"""AX 업무 도구(결정적 도구): 매출처·매입처 1차 시나리오와 적극적 지원 신호.
각 도구는 JSON Schema 계약(입력·부작용 없음·tenant 범위)을 갖고, 읽기 전용 parameterized query 로만 원천을 조회한다.
수량·금액·정책·권한은 여기서 계산하며 LLM 이 결정하지 않는다. 변경(쓰기)은 ax.command_exec 만 수행한다."""
from __future__ import annotations
import math, re
from datetime import date, datetime, timedelta
from decimal import Decimal

from .core import ApiError

GRADE = {"A": 0.0, "B": 0.5, "C": 1.0}


def _py(v):
    return (int(v) if v == int(v) else float(v)) if isinstance(v, Decimal) else v


def _i(v):
    return int(_py(v))


def _d(s):
    return datetime.strptime(s, "%Y-%m-%d").date()


ID = {"type": "string", "pattern": r"^[A-Za-z0-9_\-]{1,40}$"}
DATE = {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}$"}
QTY = {"type": "integer", "minimum": 0, "maximum": 1000000}


def _contract(name, desc, props, required, scope, side="none"):
    return {"name": name, "description": desc, "input_schema": {"type": "object", "properties": props, "required": required, "additionalProperties": False},
            "side_effect": side, "scope": scope, "timeout_s": 10, "freshness": "원천 실시간 조회(응답에 조회 시각 표시)", "cost": "read-only query"}


CONTRACTS = {
    "order_increase": _contract("order_increase", "주문 증량 가능 여부", {"tenant_id": ID, "order_id": ID, "new_qty": QTY}, ["tenant_id", "order_id", "new_qty"], "sales"),
    "delay_alternatives": _contract("delay_alternatives", "납기 지연 대안(부분·분할·대기)", {"tenant_id": ID, "order_id": ID, "new_qty": QTY, "as_of": DATE}, ["tenant_id", "order_id"], "sales"),
    "price_diff_reason": _contract("price_diff_reason", "청구 단가와 계약 단가 차이 근거", {"tenant_id": ID, "order_id": ID}, ["tenant_id", "order_id"], "sales"),
    "receivable_summary": _contract("receivable_summary", "거래처 미수금·반품 내역(원장 기준)", {"tenant_id": ID, "customer_id": ID, "as_of": DATE}, ["tenant_id", "customer_id"], "sales"),
    "purchase_reorder": _contract("purchase_reorder", "부족품목 추가 발주 대안(MOQ·pack·리드타임·가중 비교)", {"tenant_id": ID, "product_id": ID, "needed_qty": QTY, "as_of": DATE}, ["tenant_id", "product_id", "needed_qty"], "purchase_internal"),
    "supplier_switch": _contract("supplier_switch", "공급처 변경 대안(품질 제약 통과분 비교)", {"tenant_id": ID, "product_id": ID, "current_supplier_id": ID, "needed_qty": QTY, "as_of": DATE}, ["tenant_id", "product_id", "current_supplier_id", "needed_qty"], "purchase_internal"),
    "price_spike": _contract("price_spike", "매입단가 급등 비교·협상 초안", {"tenant_id": ID, "supplier_id": ID, "product_id": ID, "as_of": DATE}, ["tenant_id", "supplier_id", "product_id"], "purchase_internal"),
    "receipt_variance": _contract("receipt_variance", "입고 차이·허용오차 판정", {"tenant_id": ID, "po_id": ID}, ["tenant_id", "po_id"], "purchase_supplier"),
}


_GENERIC = {"type": "object", "properties": {"entity": ID, "key": {"type": "object"}, "relation": ID}, "additionalProperties": False}
CONTRACTS["entity_lookup"] = {"name": "entity_lookup", "description": "승인된 엔터티를 키로 1건 조회(민감 이름 컬럼 가림)", "input_schema": dict(_GENERIC, required=["entity", "key"]), "side_effect": "none", "scope": "internal", "timeout_s": 10,
                              "freshness": "원천 실시간 조회", "cost": "read-only query"}
CONTRACTS["entity_related"] = {"name": "entity_related", "description": "승인된 관계로 1 hop 연결 레코드(최대 20건)", "input_schema": dict(_GENERIC, required=["entity", "key", "relation"]), "side_effect": "none", "scope": "internal", "timeout_s": 10,
                               "freshness": "원천 실시간 조회", "cost": "read-only query"}


def validate(name, args):
    sc = CONTRACTS[name]["input_schema"]
    extra = set(args) - set(sc["properties"]) - {"question_type", "release_id"}
    if extra:
        raise ApiError(400, "BAD_PARAM", f"허용되지 않은 입력: {sorted(extra)}")
    out = {}
    for k in sc["required"]:
        if k not in args:
            raise ApiError(400, "BAD_PARAM", f"{k} 가 필요합니다.")
    for k, spec in sc["properties"].items():
        if k not in args or args[k] is None:
            continue
        v = args[k]
        if spec["type"] == "integer":
            if isinstance(v, bool) or not (isinstance(v, int) or (isinstance(v, str) and re.fullmatch(r"\d{1,7}", v.strip())) or (isinstance(v, float) and v == int(v))):
                raise ApiError(400, "BAD_QTY", f"{k} 는 정수여야 합니다.")
            v = int(v)
            if v < spec["minimum"] or v > spec["maximum"]:
                raise ApiError(400, "BAD_QTY", f"{k} 범위를 벗어났습니다.")
        else:
            if not isinstance(v, str) or not re.fullmatch(spec["pattern"], v):
                raise ApiError(400, "BAD_PARAM", f"{k} 형식이 올바르지 않습니다.")
            if spec is DATE:
                try:
                    _d(v)
                except ValueError:
                    raise ApiError(400, "BAD_PARAM", f"{k} 날짜가 올바르지 않습니다.")
        out[k] = v
    return out


def internal(m):
    return m.get("customers") is None and m.get("suppliers") is None


def check_scope(kind, m, args, owner=None):
    """kind=sales|purchase_internal|purchase_supplier. owner: 원천에서 확인한 거래처/공급처 ID(없으면 None)."""
    t = args["tenant_id"]
    if m.get("tenants") is not None and t not in m["tenants"]:
        raise ApiError(403, "TENANT_SCOPE_DENIED", "접근 범위(tenant) 밖입니다.")
    if kind == "sales":
        if m.get("suppliers") is not None:
            raise ApiError(403, "SUPPLIER_CANNOT_USE_SALES", "공급처 계정은 매출처 도구를 사용할 수 없습니다.")
        if m.get("customers") is not None and owner is not None and owner not in m["customers"]:
            raise ApiError(403, "CUSTOMER_SCOPE_DENIED", "접근 범위(거래처) 밖입니다.")
    elif kind == "purchase_internal":
        if not internal(m):
            raise ApiError(403, "INTERNAL_ONLY", "매입 비교·견적 도구는 내부 사용자 전용입니다(경쟁 공급처 정보 보호).")
    elif kind == "purchase_supplier":
        if m.get("customers") is not None:
            raise ApiError(403, "INTERNAL_ONLY", "거래처(매출처) 계정은 매입 도구를 사용할 수 없습니다.")
        if m.get("suppliers") is not None and owner is not None and owner not in m["suppliers"]:
            raise ApiError(403, "SUPPLIER_SCOPE_DENIED", "접근 범위(공급처) 밖입니다.")


def _order(cn, t, oid):
    return cn.execute("select * from sales_orders where tenant_id=? and order_id=?", (t, oid)).fetchone()


def pre_owner(cn, name, a):
    """권한 검사에 쓸 거래처/공급처 ID 를 원천에서 먼저 확인(응답에 데이터를 싣기 전)."""
    t = a["tenant_id"]
    if name in ("delay_alternatives", "price_diff_reason"):
        o = _order(cn, t, a["order_id"])
        return o["customer_id"] if o else None
    if name == "receivable_summary":
        return a["customer_id"]
    if name == "receipt_variance":
        r = cn.execute("select supplier_id from purchase_orders where tenant_id=? and po_id=?", (t, a["po_id"])).fetchone()
        return r["supplier_id"] if r else None
    return None


def _weights(pol):
    w = (pol or {}).get("weights") or {"total_cost": 0.5, "lead_days": 0.3, "quality": 0.2}
    if abs(sum(w.values()) - 1.0) > 0.001 or any(v < 0 for v in w.values()) or set(w) != {"total_cost", "lead_days", "quality"}:
        raise ApiError(409, "POLICY_WEIGHTS_INVALID", "승인된 가중치가 올바르지 않습니다(합계 1.0·세 항목).")
    return w


def _quotes(cn, t, product, as_of):
    rows = cn.execute("select supplier_id, moq, pack_size, lead_days, unit_cost, quality_grade, valid_from, valid_to from supplier_item where tenant_id=? and product_id=? and valid_from<=? and valid_to>=? order by supplier_id",
                      (t, product, as_of, as_of)).fetchall()
    return [{"supplier_id": r["supplier_id"], "moq": _i(r["moq"]), "pack_size": _i(r["pack_size"]), "lead_days": _i(r["lead_days"]), "unit_cost": _i(r["unit_cost"]), "grade": r["quality_grade"], "valid_to": r["valid_to"]} for r in rows]


def _option(q, need, as_of):
    pack = max(q["pack_size"], 1)
    qty = max(q["moq"], math.ceil(need / pack) * pack)
    return dict(q, order_qty=qty, surplus=qty - need, total_cost=qty * q["unit_cost"], arrival=str(_d(as_of) + timedelta(days=q["lead_days"])))


def _rank(opts, w):
    if not opts:
        return opts

    def norm(key):
        lo, hi = min(o[key] for o in opts), max(o[key] for o in opts)
        return {id(o): (0.0 if hi == lo else (o[key] - lo) / (hi - lo)) for o in opts}
    nc, nl = norm("total_cost"), norm("lead_days")
    for o in opts:
        qn = GRADE.get(o["grade"], 1.0)
        o["score_parts"] = {"total_cost": round(nc[id(o)], 3), "lead_days": round(nl[id(o)], 3), "quality": qn}
        o["score"] = round(w["total_cost"] * nc[id(o)] + w["lead_days"] * nl[id(o)] + w["quality"] * qn, 4)
    return sorted(opts, key=lambda o: (o["score"], o["total_cost"], o["supplier_id"]))


def _inbound(cn, t, product):
    return [{"po_id": r["po_id"], "qty": _i(r["qty"]), "expected_date": r["expected_date"], "supplier_id": r["supplier_id"]}
            for r in cn.execute("select po_id, qty, expected_date, supplier_id from purchase_orders where tenant_id=? and product_id=? and status='OPEN' order by expected_date, po_id", (t, product)).fetchall()]


# ------------------------------------------------------------------ 도구 본체
def delay_alternatives(cn, a, pol, today):
    t = a["tenant_id"]
    o = _order(cn, t, a["order_id"])
    if not o:
        return {"verdict": "NOT_FOUND", "answer": "주문을 찾을 수 없습니다. 추정하지 않고 담당자에게 이관합니다."}
    stk = cn.execute("select on_hand from stock where tenant_id=? and product_id=?", (t, o["product_id"])).fetchone()
    res = _i(cn.execute("select coalesce(sum(requested_qty),0) from sales_orders where tenant_id=? and product_id=? and status in ('CONFIRMED','ALLOCATED')", (t, o["product_id"])).fetchone()[0])
    cur, on_hand = _i(o["requested_qty"]), _i(stk["on_hand"])
    q = a.get("new_qty", cur)
    shortage = max(res - cur + q - on_hand, 0)
    inb = _inbound(cn, t, o["product_id"])
    d = {"order": {"order_id": o["order_id"], "qty": cur, "what_if_qty": q, "due_date": o["due_date"]}, "stock": {"on_hand": on_hand, "reserved_total": res}, "shortage": shortage, "inbound": inb,
         "inbound_confirmation": "미확인(입고 확정도 필드가 원천에 없음 — OPEN 발주의 예정일만 사용)"}
    if shortage == 0:
        return {"verdict": "ON_TIME_FROM_STOCK", "detail": d, "alternatives": [], "answer": f"현재고로 {q}박스를 납기({o['due_date']})에 맞출 수 있습니다."}
    cum, arr = 0, None
    for p in inb:
        cum += p["qty"]
        if cum >= shortage:
            arr = p
            break
    if not arr:
        return {"verdict": "UNCONFIRMED_INBOUND", "detail": d, "alternatives": [{"option": "PARTIAL_NOW", "qty_now": max(q - shortage, 0), "desc": f"지금 {max(q - shortage, 0)}박스만 출고"}],
                "answer": f"부족 {shortage}박스를 메울 입고 예정이 없습니다. 부분 출고 또는 담당자 이관이 필요합니다."}
    delay = max((_d(arr["expected_date"]) - _d(o["due_date"])).days, 0)
    now = max(q - shortage, 0)
    alts = [{"option": "PARTIAL_NOW", "qty_now": now, "remaining": shortage, "desc": f"지금 {now}박스만 출고, 나머지 {shortage}박스는 재요청"},
            {"option": "SPLIT", "qty_now": now, "qty_later": shortage, "later_date": arr["expected_date"], "delay_days": delay, "desc": f"{now}박스 즉시 + {shortage}박스는 {arr['expected_date']}({arr['po_id']} 입고 후, 납기 대비 +{delay}일)"},
            {"option": "WAIT_ALL", "qty": q, "date": arr["expected_date"], "delay_days": delay, "desc": f"전량 {q}박스를 {arr['expected_date']}에 출고(납기 대비 +{delay}일)"}]
    return {"verdict": "DELAY_RISK", "detail": d, "alternatives": alts, "answer": f"{q}박스 중 {shortage}박스가 부족해 납기({o['due_date']})를 지키기 어렵습니다. 대안 {len(alts)}개를 비교하세요(입고 예정일은 미확정 정보)."}


def price_diff_reason(cn, a, pol, today):
    t = a["tenant_id"]
    o = _order(cn, t, a["order_id"])
    if not o:
        return {"verdict": "NOT_FOUND", "answer": "주문을 찾을 수 없습니다. 추정하지 않고 담당자에게 이관합니다."}
    cs = [{"contract_id": r["contract_id"], "unit_price": _i(r["unit_price"]), "valid_from": r["valid_from"], "valid_to": r["valid_to"]}
          for r in cn.execute("select contract_id, unit_price, valid_from, valid_to from contract where tenant_id=? and customer_id=? and product_id=? order by valid_from", (t, o["customer_id"], o["product_id"])).fetchall()]
    valid = [c for c in cs if c["valid_from"] <= o["order_date"] <= c["valid_to"]]
    billed = _i(o["billed_price"])
    d = {"order_id": o["order_id"], "order_date": o["order_date"], "billed_price": billed, "contracts": cs, "valid_contract": valid[0] if valid else None,
         "not_modeled": "세금·통화·할인·단위 변환은 이 원천에 없어 비교에 포함하지 못했습니다(미확인)"}
    if not valid:
        return {"verdict": "NO_VALID_CONTRACT", "detail": d, "answer": "주문일 기준 유효한 계약 단가가 없어 원인을 확정할 수 없습니다. 영업 담당자에게 이관합니다."}
    cp = valid[0]["unit_price"]
    diff = billed - cp
    pct = round(diff / cp * 100, 2)
    d.update(contract_price=cp, diff=diff, diff_pct=pct)
    if diff == 0:
        return {"verdict": "MATCHES_CONTRACT", "detail": d, "answer": f"청구 단가 {billed}원이 주문일({o['order_date']}) 유효 계약({valid[0]['contract_id']}) 단가와 같습니다."}
    v = "BILLED_ABOVE_CONTRACT" if diff > 0 else "BILLED_BELOW_CONTRACT"
    draft = f"[조정 요청 초안 — 발송되지 않음] 주문 {o['order_id']}: 청구 {billed}원 / 계약({valid[0]['contract_id']}, 주문일 {o['order_date']} 유효) {cp}원, 차이 {diff:+d}원({pct:+.2f}%). 확인 후 정정 처리를 요청드립니다."
    return {"verdict": v, "detail": d, "drafts": [draft], "answer": f"청구 단가 {billed}원이 계약 단가 {cp}원보다 {abs(diff)}원({abs(pct)}%) {'높' if diff > 0 else '낮'}습니다. 조정 요청 초안을 만들었습니다(승인 후 발송)."}


def receivable_summary(cn, a, pol, today):
    t, c = a["tenant_id"], a["customer_id"]
    as_of = a.get("as_of", today)
    cust = cn.execute("select credit_limit, credit_used from customer_role where tenant_id=? and customer_id=?", (t, c)).fetchone()
    if not cust:
        return {"verdict": "NOT_FOUND", "answer": "거래처를 찾을 수 없습니다. 추정하지 않고 담당자에게 이관합니다."}
    es = [{"entry_id": r["entry_id"], "kind": r["kind"], "amount": _i(r["amount"]), "date": r["entry_date"], "ref_order": r["ref_order"]}
          for r in cn.execute("select entry_id, kind, amount, entry_date, ref_order from ar_ledger where tenant_id=? and customer_id=? and entry_date<=? order by entry_date, entry_id", (t, c, as_of)).fetchall()]
    if not es:
        return {"verdict": "NO_ENTRIES", "detail": {"as_of": as_of}, "answer": "해당 기준일까지 원장 내역이 없어 미수금을 확정할 수 없습니다. 담당자에게 이관합니다."}
    s = {k: sum(e["amount"] for e in es if e["kind"] == k) for k in ("INVOICE", "PAYMENT", "RETURN")}
    bal = s["INVOICE"] - s["PAYMENT"] - s["RETURN"]
    return {"verdict": "OK", "detail": {"as_of": as_of, "invoiced": s["INVOICE"], "paid": s["PAYMENT"], "returned": s["RETURN"], "balance": bal, "entries": es,
                                        "credit_used_legacy": _i(cust["credit_used"]), "matches_credit_used": bal == _i(cust["credit_used"])},
            "answer": f"{as_of} 기준 미수금 {bal}원(청구 {s['INVOICE']} − 입금 {s['PAYMENT']} − 반품 {s['RETURN']}). 레거시 여신사용액과 {'일치' if bal == _i(cust['credit_used']) else '불일치 — 확인 필요'}."}


def purchase_reorder(cn, a, pol, today):
    t, p, need = a["tenant_id"], a["product_id"], a["needed_qty"]
    as_of = a.get("as_of", today)
    w = _weights(pol)
    inb = _inbound(cn, t, p)
    inq = sum(x["qty"] for x in inb)
    d = {"needed_qty": need, "inbound_open": inb, "inbound_qty": inq, "weights": w, "weights_note": "가중치는 승인된 release 정책의 값(현업 승인)"}
    if inq >= need:
        first = inb[0]["expected_date"] if inb else None
        return {"verdict": "COVERED_BY_INBOUND", "detail": d, "alternatives": [], "answer": f"입고 예정 {inq}박스(최초 {first})로 필요 {need}박스를 충당할 수 있어 추가 발주가 필요 없습니다(입고 확정도는 미확인)."}
    rem = need - inq
    opts = _rank([_option(q, rem, as_of) for q in _quotes(cn, t, p, as_of)], w)
    d["remaining_after_inbound"] = rem
    if not opts:
        return {"verdict": "NO_VALID_QUOTE", "detail": d, "alternatives": [], "answer": "기준일에 유효한 공급 견적이 없습니다. 구매 담당자에게 이관합니다."}
    return {"verdict": "ORDER_OPTIONS", "detail": d, "alternatives": opts, "recommended": opts[0]["supplier_id"],
            "answer": f"입고 예정 {inq}박스를 반영해 추가 {rem}박스가 필요합니다. 최소 발주(MOQ)·포장 단위를 맞춘 대안 {len(opts)}개 중 가중 점수 1위는 {opts[0]['supplier_id']}(발주 {opts[0]['order_qty']}박스, 총 {opts[0]['total_cost']}원, 도착 {opts[0]['arrival']})입니다."}


def supplier_switch(cn, a, pol, today):
    t, p, need, cur = a["tenant_id"], a["product_id"], a["needed_qty"], a["current_supplier_id"]
    as_of = a.get("as_of", today)
    ming = (pol or {}).get("min_quality_grade", "B")
    allq = _quotes(cn, t, p, as_of)
    curq = next((q for q in allq if q["supplier_id"] == cur), None)
    ok, excluded = [], []
    for q in allq:
        if q["supplier_id"] == cur:
            continue
        if GRADE.get(q["grade"], 1.0) > GRADE[ming]:
            excluded.append({"supplier_id": q["supplier_id"], "reason": f"품질 등급 {q['grade']} < 최소 {ming}"})
        else:
            ok.append(_option(q, need, as_of))
    w = _weights({"weights": {"total_cost": 0.5, "lead_days": 0.3, "quality": 0.2}})
    ranked = _rank(ok, w)
    base = _option(curq, need, as_of) if curq else None
    d = {"current": base, "excluded": excluded, "min_quality_grade": ming}
    if not ranked:
        return {"verdict": "NONE_PASS_CONSTRAINTS", "detail": d, "alternatives": [], "answer": "품질·유효 견적 제약을 통과하는 대체 공급처가 없습니다."}
    for o in ranked:
        o["vs_current"] = None if not base else {"cost_diff": o["total_cost"] - base["total_cost"], "lead_diff_days": o["lead_days"] - base["lead_days"]}
    return {"verdict": "ALTERNATIVES_AVAILABLE", "detail": d, "alternatives": ranked, "answer": f"현재 {cur} 대비 제약을 통과한 대체 공급처 {len(ranked)}곳을 비교했습니다. 제외 {len(excluded)}곳(사유 표시)."}


def price_spike(cn, a, pol, today):
    t, s, p = a["tenant_id"], a["supplier_id"], a["product_id"]
    as_of = a.get("as_of", today)
    th = (pol or {}).get("threshold_pct", 10)
    rows = cn.execute("select valid_from, valid_to, unit_cost from supplier_item where tenant_id=? and supplier_id=? and product_id=? order by valid_from", (t, s, p)).fetchall()
    qs = [{"valid_from": r["valid_from"], "valid_to": r["valid_to"], "unit_cost": _i(r["unit_cost"])} for r in rows]
    cur = next((q for q in qs if q["valid_from"] <= as_of <= q["valid_to"]), None)
    if not cur:
        return {"verdict": "NO_VALID_QUOTE", "detail": {"quotes": qs}, "answer": "기준일에 유효한 견적이 없습니다."}
    prev = [q for q in qs if q["valid_to"] < cur["valid_from"]]
    if not prev:
        return {"verdict": "NO_PREVIOUS_QUOTE", "detail": {"current": cur}, "answer": "비교할 이전 견적이 없습니다."}
    pv = prev[-1]
    pct = round((cur["unit_cost"] - pv["unit_cost"]) / pv["unit_cost"] * 100, 2)
    others = [{"supplier_id": q["supplier_id"], "unit_cost": q["unit_cost"], "grade": q["grade"]} for q in _quotes(cn, t, p, as_of) if q["supplier_id"] != s]
    d = {"current": cur, "previous": pv, "change_pct": pct, "threshold_pct": th, "alternatives_current_cost": others, "not_modeled": "세금·부대비·통화·단위는 원천에 없어 비교에 포함하지 못했습니다(미확인)"}
    if pct <= th:
        return {"verdict": "WITHIN_THRESHOLD", "detail": d, "answer": f"단가 변동 {pct:+.2f}%로 기준({th}%) 이내입니다."}
    draft = f"[협상 초안 — 발송되지 않음] {s} 님, {p} 단가가 {pv['unit_cost']}원에서 {cur['unit_cost']}원으로 {pct:+.2f}% 변경되었습니다. 타 공급 견적과 비교 시 조정 가능 여부를 협의 요청드립니다."
    return {"verdict": "SPIKE", "detail": d, "drafts": [draft], "answer": f"단가가 {pv['unit_cost']}→{cur['unit_cost']}원({pct:+.2f}%)으로 기준 {th}%를 넘었습니다. 대체 견적 {len(others)}건과 협상 초안을 준비했습니다."}


def receipt_variance(cn, a, pol, today):
    t = a["tenant_id"]
    r = cn.execute("select * from purchase_orders where tenant_id=? and po_id=?", (t, a["po_id"])).fetchone()
    if not r:
        return {"verdict": "NOT_FOUND", "answer": "발주를 찾을 수 없습니다. 추정하지 않고 담당자에게 이관합니다."}
    qty, got, tol = _i(r["qty"]), _i(r["received_qty"]), _i(r["tolerance_pct"])
    d = {"po_id": r["po_id"], "supplier_id": r["supplier_id"], "ordered": qty, "received": got, "tolerance_pct": tol, "status": r["status"]}
    if r["status"] == "OPEN":
        return {"verdict": "NOT_RECEIVED_YET", "detail": d, "answer": "아직 입고 완료되지 않은 발주입니다."}
    var = round((qty - got) / qty * 100, 2)
    d["variance_pct"] = var
    if got > qty * (1 + tol / 100):
        return {"verdict": "OVER_RECEIPT", "detail": d, "answer": f"과입고({-var:.2f}%)입니다. 허용오차 {tol}% 초과 — 검수 확인이 필요합니다."}
    if var <= tol:
        return {"verdict": "WITHIN_TOLERANCE", "detail": d, "answer": f"입고 차이 {var:.2f}%로 허용오차({tol}%) 이내입니다."}
    return {"verdict": "OUT_OF_TOLERANCE", "detail": d, "drafts": [f"[클레임 초안 — 발송되지 않음] 발주 {r['po_id']}: 발주 {qty}박스 / 입고 {got}박스, 부족 {qty - got}박스({var:.2f}%)가 허용오차 {tol}%를 초과했습니다. 증빙 확인 후 처리를 요청합니다."],
            "answer": f"입고 차이 {var:.2f}%로 허용오차({tol}%)를 초과했습니다. 클레임 초안을 준비했습니다(승인 후 발송)."}


FUNCS = {"delay_alternatives": delay_alternatives, "price_diff_reason": price_diff_reason, "receivable_summary": receivable_summary, "purchase_reorder": purchase_reorder,
         "supplier_switch": supplier_switch, "price_spike": price_spike, "receipt_variance": receipt_variance}


# ------------------------------------------------------------------ 적극적 지원 신호(탐지만 — 실행하지 않음)
def detect_signals(cn, today):
    out = []
    for r in cn.execute("select s.tenant_id, s.product_id, s.on_hand, (select coalesce(sum(o.requested_qty),0) from sales_orders o where o.tenant_id=s.tenant_id and o.product_id=s.product_id and o.status in ('CONFIRMED','ALLOCATED')) res from stock s").fetchall():
        oh, rs = _i(r["on_hand"]), _i(r["res"])
        if rs > oh:
            out.append({"kind": "STOCK_SHORT", "ref": f"{r['tenant_id']}:{r['product_id']}", "class": "FACT", "severity": "high", "message": f"예약 {rs} > 현재고 {oh} (부족 {rs - oh}박스)", "data": {"on_hand": oh, "reserved": rs}})
    horizon = str(_d(today) + timedelta(days=45))
    for r in cn.execute("select tenant_id, contract_id, customer_id, valid_to from contract where valid_to>=? and valid_to<=? order by contract_id", (today, horizon)).fetchall():
        out.append({"kind": "CONTRACT_EXPIRING", "ref": f"{r['tenant_id']}:{r['contract_id']}", "class": "FACT", "severity": "mid", "message": f"계약 {r['contract_id']}({r['customer_id']}) {r['valid_to']} 만료 예정", "data": {}})
    for r in cn.execute("select tenant_id, product_id, min(unit_cost) lo, max(unit_cost) hi from supplier_item where valid_from<=? and valid_to>=? group by tenant_id, product_id", (today, today)).fetchall():
        lo, hi = _i(r["lo"]), _i(r["hi"])
        if lo and (hi - lo) / lo * 100 > 20:
            out.append({"kind": "SUPPLIER_PRICE_GAP", "ref": f"{r['tenant_id']}:{r['product_id']}", "class": "FACT", "severity": "mid", "message": f"공급처 견적 편차 {round((hi - lo) / lo * 100, 1)}% (최저 {lo}, 최고 {hi})", "data": {"low": lo, "high": hi}})
    for r in cn.execute("select tenant_id, po_id, qty, received_qty, tolerance_pct from purchase_orders where status='RECEIVED'").fetchall():
        q, g, tol = _i(r["qty"]), _i(r["received_qty"]), _i(r["tolerance_pct"])
        if q and (q - g) / q * 100 > tol:
            out.append({"kind": "RECEIPT_OUT_OF_TOLERANCE", "ref": f"{r['tenant_id']}:{r['po_id']}", "class": "FACT", "severity": "mid", "message": f"발주 {r['po_id']} 입고 차이 {round((q - g) / q * 100, 2)}% > 허용 {tol}%", "data": {}})
    for r in cn.execute("select o.tenant_id, o.order_id, o.due_date, o.product_id from sales_orders o where o.status in ('CONFIRMED','ALLOCATED') order by o.order_id").fetchall():
        st = cn.execute("select on_hand from stock where tenant_id=? and product_id=?", (r["tenant_id"], r["product_id"])).fetchone()
        rs = _i(cn.execute("select coalesce(sum(requested_qty),0) from sales_orders where tenant_id=? and product_id=? and status in ('CONFIRMED','ALLOCATED')", (r["tenant_id"], r["product_id"])).fetchone()[0])
        if st and rs > _i(st["on_hand"]):
            inb = _inbound(cn, r["tenant_id"], r["product_id"])
            late = inb and inb[0]["expected_date"] > r["due_date"]
            out.append({"kind": "DELIVERY_RISK", "ref": f"{r['tenant_id']}:{r['order_id']}", "class": "ASSUMPTION" if inb else "FACT", "severity": "high",
                        "message": f"주문 {r['order_id']} 납기 {r['due_date']} — 재고 부족 상태" + (f", 최초 입고 예정 {inb[0]['expected_date']}{'(납기 이후)' if late else ''}" if inb else ", 입고 예정 없음"), "data": {}})
    return out
