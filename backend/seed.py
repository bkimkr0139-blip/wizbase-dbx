"""Deterministic synthetic seed (spec §8). Fixed seed, clock and timezone."""
import random

BASE_CLOCK = "2026-11-11T15:20:00+09:00"
SEED_NAME = "food-order-v1"
CATALOG = "food_dev"

# 시드별 대표 사례(암기 방지: 같은 규칙, 다른 숫자·거래처·상품). 가용재고 = Σ(on_hand − reserved − damaged)
CASES = {
    "food-order-v1": {"order": "O-10021", "cust": "C-007", "route": "R-02", "product": "P-001", "subs": ("P-002", "P-003"), "current": 20, "requested": 35, "inv": [("W1", 40, 30, 2), ("W2", 10, 5, 1)]},
    "food-order-v2": {"order": "O-10088", "cust": "C-014", "route": "R-04", "product": "P-017", "subs": ("P-018", "P-019"), "current": 14, "requested": 30, "inv": [("W1", 18, 10, 2), ("W2", 6, 3, 0)]},
    "food-order-v3": {"order": "O-10150", "cust": "C-021", "route": "R-01", "product": "P-044", "subs": ("P-045", "P-046"), "current": 8, "requested": 40, "inv": [("W1", 45, 30, 3), ("W2", 15, 6, 2)]},
}


def case(seed_name=SEED_NAME):
    c = dict(CASES[seed_name])
    c["available"] = sum(o - r - d for _, o, r, d in c["inv"])
    c["naive_available"] = sum(o - r for _, o, r, d in c["inv"])
    c["additional"] = max(c["requested"] - c["current"], 0)
    c["gap"] = max(c["additional"] - c["available"], 0)
    c["wrong_gap"] = c["requested"] - c["available"]
    c["seed"] = seed_name
    return c

REGIONS = ["서울", "경기", "인천", "부산", "대구", "광주"]


def build(conn, seed_name: str = SEED_NAME) -> dict:
    """Create schemas/tables in attached catalog `food_dev`. Returns the answer key."""
    r = random.Random(seed_name)
    cs = CASES[seed_name]
    for s in ("bronze", "silver", "gold", "src_oracle"):
        conn.execute(f"CREATE SCHEMA IF NOT EXISTS {CATALOG}.{s}")

    # ---- reference data (silver) ----
    conn.execute(f"CREATE TABLE {CATALOG}.silver.customers(customer_id VARCHAR, name VARCHAR, region VARCHAR, credit_blocked BOOLEAN)")
    cust = []
    for i in range(1, 31):
        cust.append((f"C-{i:03d}", f"거래처{i:02d}", REGIONS[i % len(REGIONS)], i == 29))
    conn.executemany(f"INSERT INTO {CATALOG}.silver.customers VALUES (?,?,?,?)", cust)

    conn.execute(f"CREATE TABLE {CATALOG}.silver.customer_contracts(customer_id VARCHAR, exception_cutoff BOOLEAN, cutoff_hhmm VARCHAR)")
    conn.executemany(f"INSERT INTO {CATALOG}.silver.customer_contracts VALUES (?,?,?)",
                     [(c[0], c[0] in (cs["cust"], "C-007", "C-011", "C-029"), "15:00") for c in cust])

    conn.execute(f"CREATE TABLE {CATALOG}.silver.products(product_id VARCHAR, name VARCHAR, unit VARCHAR, units_per_box INTEGER)")
    conn.executemany(f"INSERT INTO {CATALOG}.silver.products VALUES (?,?,?,?)",
                     [(f"P-{i:03d}", f"상품{i:03d}", "BOX", r.choice([6, 10, 12, 24])) for i in range(1, 101)])

    conn.execute(f"CREATE TABLE {CATALOG}.silver.delivery_routes(route_id VARCHAR, is_open BOOLEAN, cutoff_hhmm VARCHAR)")
    conn.executemany(f"INSERT INTO {CATALOG}.silver.delivery_routes VALUES (?,?,?)",
                     [(f"R-{i:02d}", True, "17:00") for i in range(1, 6)])

    # ---- orders / lines ----
    conn.execute(f"CREATE TABLE {CATALOG}.silver.orders(order_id VARCHAR, customer_id VARCHAR, order_date DATE, status VARCHAR, version INTEGER, route_id VARCHAR)")
    conn.execute(f"CREATE TABLE {CATALOG}.silver.order_lines(order_id VARCHAR, line_no INTEGER, product_id VARCHAR, qty_boxes INTEGER, line_type VARCHAR, supply_amount DECIMAL(18,2), vat_amount DECIMAL(18,2))")
    orders, lines = [], []
    for i in range(1, 301):
        oid = f"O-{10000 + i}"
        c = cs["cust"] if oid == cs["order"] else f"C-{r.randint(1, 30):03d}"
        st = "CONFIRMED" if oid == cs["order"] else r.choice(["CONFIRMED", "CONFIRMED", "SHIPPED", "CANCELLED"])
        route = cs["route"] if oid == cs["order"] else f"R-{r.randint(1, 5):02d}"
        orders.append((oid, c, f"2026-11-{r.randint(1, 11):02d}", st, 1, route))
        for ln in range(1, 4):
            if oid == cs["order"] and ln == 1:
                pid, qty, lt = cs["product"], cs["current"], "SALE"
            else:
                pid = f"P-{r.randint(2, 100):03d}"
                qty = r.randint(1, 30)
                lt = "SALE"
                if r.random() < 0.04:
                    lt, qty = "RETURN", -r.randint(1, 5)
            price = r.choice([10000, 12000, 15000, 22000])
            sup = round(qty * price, 2)
            lines.append((oid, ln, pid, qty, lt, sup, round(sup * 0.1, 2)))
    conn.executemany(f"INSERT INTO {CATALOG}.silver.orders VALUES (?,?,?,?,?,?)", orders)
    conn.executemany(f"INSERT INTO {CATALOG}.silver.order_lines VALUES (?,?,?,?,?,?,?)", lines)

    # ---- inventory: P-001 on_hand 50, reserved 35, damaged 3 => available 12 ----
    conn.execute(f"CREATE TABLE {CATALOG}.silver.inventory(warehouse_id VARCHAR, product_id VARCHAR, on_hand_qty INTEGER, reserved_qty INTEGER, damaged_qty INTEGER)")
    inv = [(w, cs["product"], o, rs, dm) for (w, o, rs, dm) in cs["inv"]]
    for i in range(1, 101):
        if f"P-{i:03d}" == cs["product"]:
            continue
        for w in ("W1", "W2"):
            oh = r.randint(10, 80)
            rs = r.randint(0, oh // 2)
            dm = r.randint(0, 3)
            inv.append((w, f"P-{i:03d}", oh, rs, dm))
    conn.executemany(f"INSERT INTO {CATALOG}.silver.inventory VALUES (?,?,?,?,?)", inv)

    conn.execute(f"CREATE TABLE {CATALOG}.silver.product_substitutes(product_id VARCHAR, substitute_id VARCHAR, unit_match BOOLEAN)")
    conn.executemany(f"INSERT INTO {CATALOG}.silver.product_substitutes VALUES (?,?,?)",
                     [(cs["product"], cs["subs"][0], True), (cs["product"], cs["subs"][1], False)])
    conn.execute(f"CREATE TABLE {CATALOG}.silver.receivables(customer_id VARCHAR, balance DECIMAL(18,2), credit_limit DECIMAL(18,2))")
    conn.executemany(f"INSERT INTO {CATALOG}.silver.receivables VALUES (?,?,?)",
                     [(c[0], r.randint(0, 5_000_000), 10_000_000) for c in cust])
    conn.execute(f"CREATE TABLE {CATALOG}.silver.approvals(approval_id VARCHAR, proposal_id VARCHAR, approver VARCHAR, payload_hash VARCHAR, status VARCHAR)")
    conn.execute(f"CREATE TABLE {CATALOG}.silver.action_audit(action_id VARCHAR, order_id VARCHAR, old_qty INTEGER, new_qty INTEGER, approval_id VARCHAR, idempotency_key VARCHAR, result VARCHAR)")

    # ---- bronze raw: all strings, dirty on purpose ----
    conn.execute(f"CREATE TABLE {CATALOG}.bronze.raw_orders(order_id VARCHAR, customer_id VARCHAR, order_date VARCHAR, status VARCHAR, version VARCHAR, updated_at VARCHAR)")
    raw = [(o[0], o[1], str(o[2]), o[3], str(o[4]), "2026-11-11 09:00:00") for o in orders]
    dup_ids = [orders[i][0] for i in (3, 10, 25, 40, 77, 120)]
    for d in dup_ids:  # older duplicate with stale status
        base = next(x for x in raw if x[0] == d)
        raw.append((d, base[1], base[2], "PENDING", "0", "2026-11-10 08:00:00"))
    for k in range(4):  # null customer
        raw.append((f"O-2000{k + 1}", None, "2026-11-11", "CONFIRMED", "1", "2026-11-11 09:00:00"))
    for k in range(3):  # invalid status code
        raw.append((f"O-2000{k + 5}", f"C-{k + 1:03d}", "2026-11-11", "XX", "1", "2026-11-11 09:00:00"))
    conn.executemany(f"INSERT INTO {CATALOG}.bronze.raw_orders VALUES (?,?,?,?,?,?)", raw)
    conn.execute(f"CREATE TABLE {CATALOG}.bronze.raw_inventory AS SELECT * FROM {CATALOG}.silver.inventory")
    conn.execute(f"CREATE TABLE {CATALOG}.src_oracle.orders_src AS SELECT * FROM {CATALOG}.bronze.raw_orders")

    # ---- CDC 교육용 이벤트 재생 (실제 Lakeflow 커넥터 실행과 별개): 중복·역순·삭제·재삽입·seq 누락 포함 ----
    conn.execute(f"CREATE TABLE {CATALOG}.bronze.cdc_events(event_id VARCHAR, customer_id VARCHAR, op VARCHAR, city VARCHAR, seq INTEGER)")
    conn.execute(f"CREATE TABLE {CATALOG}.bronze.cdc_events_next(event_id VARCHAR, customer_id VARCHAR, op VARCHAR, city VARCHAR, seq INTEGER)")
    conn.executemany(f"INSERT INTO {CATALOG}.bronze.cdc_events VALUES (?,?,?,?,?)",
                     [("E1", "C-001", "I", "Seoul", 1), ("E2", "C-002", "I", "Busan", 2), ("E3", "C-001", "U", "Incheon", 4), ("E4", "C-003", "I", "Daegu", 3),
                      ("E3", "C-001", "U", "Incheon", 4), ("E5", "C-002", "D", None, 6), ("E6", "C-001", "U", "Gwangju", 5), ("E7", "C-004", "I", "Ulsan", 7)])
    conn.executemany(f"INSERT INTO {CATALOG}.bronze.cdc_events_next VALUES (?,?,?,?,?)",
                     [("E9", "C-002", "I", "Busan2", 10), ("E8", "C-003", "U", "Jeju", 9), ("E10", "C-005", "I", "Sejong", 11), ("E8", "C-003", "U", "Jeju", 9)])

    # ---- gold: intentionally naive (omits damaged_qty) -> learner must fix against contract ----
    conn.execute(f"""CREATE VIEW {CATALOG}.gold.v_available_inventory AS
        SELECT product_id, SUM(on_hand_qty - reserved_qty) AS available_qty
        FROM {CATALOG}.silver.inventory GROUP BY product_id""")
    conn.execute(f"""CREATE VIEW {CATALOG}.gold.v_order_overview AS
        SELECT o.order_id, o.customer_id, o.status, o.version, SUM(l.qty_boxes) AS total_boxes,
               SUM(l.supply_amount) AS supply_amount, SUM(l.vat_amount) AS vat_amount
        FROM {CATALOG}.silver.orders o JOIN {CATALOG}.silver.order_lines l USING(order_id)
        GROUP BY o.order_id, o.customer_id, o.status, o.version""")

    return answer_key(len(orders), len(lines), raw, dup_ids, seed_name)


def answer_key(n_orders=300, n_lines=900, raw=None, dup_ids=None, seed_name=SEED_NAME) -> dict:
    cz = case(seed_name)
    return {
        "seed": seed_name, "case": cz,
        "clock": BASE_CLOCK,
        "counts": {"customers": 30, "products": 100, "orders": n_orders, "order_lines": n_lines},
        "bronze_raw_orders": 313,
        "bronze_duplicates": 6,
        "bronze_null_customer": 4,
        "bronze_bad_status": 3,
        "pipeline_expected_rows": 303,   # 313 - 6 dup - 4 null-customer (quarantined); 3 bad status kept + warned
        "pipeline_expected_quarantine": 4,
        "available_P001": cz["available"],
        "naive_available_P001": cz["naive_available"],
        "extra_gap_O10021": cz["gap"],
        "wrong_gap_if_total_minus_free": cz["wrong_gap"],
        "vat_rule": "supply_amount excludes VAT; vat_amount = 10% of supply; returns are negative qty lines (line_type=RETURN)",
        "cdc_expected_batch1": {"C-001": "Gwangju", "C-003": "Daegu", "C-004": "Ulsan"},
        "cdc_expected_final": {"C-001": "Gwangju", "C-002": "Busan2", "C-003": "Jeju", "C-004": "Ulsan", "C-005": "Sejong"},
        "contract_formula": "available_qty = SUM(on_hand_qty - reserved_qty - damaged_qty) per product_id",
    }
