"""실제 DBX 실습(C 경로) 콘텐츠와 서버 측 자동 대조. 기대 결과는 서버가 DuckDB로 계산해 보관하며 학습자 API로 내보내지 않는다.
이 서버는 Databricks 자격증명을 받지 않는다: 학습자 PC의 증거 수집기(adapter)가 실행하고 결과 체크섬만 제출한다."""
from __future__ import annotations
import re
import duckdb
from adapter import dbx_lab_common as common

STATUS_NOTE = "콘텐츠 작성 상태: 팩 일부만 작성됨. 미작성 팩은 '미작성'으로 표시되며 해당 실습이 필요한 준비 판정은 차단된다."


def _t(id_, sql, compare=True, note="", observe=False):
    return {"id": id_, "sql": sql, "compare": compare and not observe, "note": note, "observe": observe}


SEED_INV = ("INSERT INTO {S}.inventory VALUES ('W1','P-001',40,30,2),('W2','P-001',10,5,1),('W1','P-002',25,10,0),('W2','P-002',5,0,1),('W1','P-003',8,8,0)")
D2_DEDUPE = ("SELECT order_id, status, qty FROM {S}.raw_orders QUALIFY ROW_NUMBER() OVER (PARTITION BY order_id ORDER BY updated_at DESC) = 1")

LABS = {
    "LAB-CORE-01": {
        "title": "Unity Catalog 3단계 이름과 SQL 조회", "exam": ["DE-A"], "pack": "CORE-01", "kind": "machine", "est_minutes": 20,
        "goal": "교육용 워크스페이스에 합성 재고 테이블을 만들고, 계약 산식(on_hand−reserved−damaged)으로 가용재고를 계산해 실제 결과를 증거로 남긴다.",
        "steps": ["본인 교육용 워크스페이스에서 쓰기 가능한 catalog 이름을 정한다(예: workspace, main 등 — 고객/운영 catalog 금지).", "adapter를 실행한다(아래 명령). 스키마 wz_lab_core01 만 생성·정리된다.", "출력된 evidence JSON을 UI-22에 붙여넣어 제출한다.", "검토자가 Query History의 statement_id로 원본을 확인한다."],
        "setup": ["CREATE SCHEMA IF NOT EXISTS {S}", "CREATE OR REPLACE TABLE {S}.inventory (warehouse_id STRING, product_id STRING, on_hand_qty INT, reserved_qty INT, damaged_qty INT)", SEED_INV],
        "tasks": [_t("count", "SELECT COUNT(*) AS n FROM {S}.inventory"),
                  _t("available", "SELECT product_id, SUM(on_hand_qty - reserved_qty - damaged_qty) AS available_qty FROM {S}.inventory GROUP BY product_id"),
                  _t("show_tables", "SHOW TABLES IN {S}", note="관찰용(검토자가 확인)", observe=True)],
        "cleanup": ["DROP SCHEMA IF EXISTS {S} CASCADE"], "schema": "wz_lab_core01"},
    "LAB-DE-02": {
        "title": "SQL 중복 제거·JOIN·window·NULL·decimal", "exam": ["DE-A", "DE-P"], "pack": "DE-02", "kind": "machine", "est_minutes": 30,
        "goal": "키 기준 최신 행 선택(QUALIFY), JOIN, 누적 window, NULL 처리, decimal 연산 결과를 실제 엔진에서 확인한다.",
        "steps": ["adapter 실행(스키마 wz_lab_de02).", "결과 체크섬이 기대값과 일치하는지 UI-22 자동 대조 결과를 확인한다.", "불일치 시 어느 task가 다른지만 표시된다 — SQL 의미(타이브레이크·NULL·decimal)를 점검한다."],
        "setup": ["CREATE SCHEMA IF NOT EXISTS {S}",
                  "CREATE OR REPLACE TABLE {S}.raw_orders (order_id STRING, customer_id STRING, status STRING, qty INT, updated_at STRING)",
                  "INSERT INTO {S}.raw_orders VALUES ('O-1','C-1','CONFIRMED',10,'2026-11-10 09:00:00'),('O-1','C-1','PENDING',8,'2026-11-09 09:00:00'),('O-2','C-2','CONFIRMED',5,'2026-11-10 10:00:00'),('O-3',NULL,'CONFIRMED',7,'2026-11-10 11:00:00'),('O-4','C-1','CANCELLED',NULL,'2026-11-10 12:00:00'),('O-5','C-3','CONFIRMED',12,'2026-11-10 13:00:00'),('O-5','C-3','CONFIRMED',12,'2026-11-10 13:00:00')",
                  "CREATE OR REPLACE TABLE {S}.customers (customer_id STRING, name STRING)",
                  "INSERT INTO {S}.customers VALUES ('C-1','Alpha'),('C-2','Beta'),('C-3','Gamma')"],
        "tasks": [_t("dedupe", D2_DEDUPE),
                  _t("join_total", "WITH d AS (SELECT order_id, customer_id, qty FROM {S}.raw_orders QUALIFY ROW_NUMBER() OVER (PARTITION BY order_id ORDER BY updated_at DESC) = 1) SELECT c.name, SUM(COALESCE(d.qty, 0)) AS total_qty FROM d JOIN {S}.customers c ON d.customer_id = c.customer_id GROUP BY c.name"),
                  _t("running", "WITH d AS (SELECT order_id, qty FROM {S}.raw_orders QUALIFY ROW_NUMBER() OVER (PARTITION BY order_id ORDER BY updated_at DESC) = 1) SELECT order_id, SUM(COALESCE(qty, 0)) OVER (ORDER BY order_id) AS running_qty FROM d"),
                  _t("decimal", "WITH d AS (SELECT qty FROM {S}.raw_orders QUALIFY ROW_NUMBER() OVER (PARTITION BY order_id ORDER BY updated_at DESC) = 1) SELECT CAST(SUM(qty) * 1.1 AS DECIMAL(10,2)) AS vat_incl FROM d")],
        "cleanup": ["DROP SCHEMA IF EXISTS {S} CASCADE"], "schema": "wz_lab_de02"},
    "LAB-DE-03": {
        "title": "Delta MERGE 변경 반영과 이력", "exam": ["DE-A", "DE-P"], "pack": "DE-03", "kind": "machine", "est_minutes": 30,
        "goal": "Delta 테이블에 MERGE로 insert/update/delete를 반영하고 결과와 DESCRIBE HISTORY를 확인한다. (복구 한계 설명은 검토자 면담에서 확인)",
        "steps": ["adapter 실행(스키마 wz_lab_de03). 이 실습은 Delta 테이블(USING DELTA)을 만든다.", "MERGE 후 테이블 내용이 기대값과 일치하는지 자동 대조된다.", "history task 출력(operation 목록)은 관찰용이며 검토자가 확인한다."],
        "setup": ["CREATE SCHEMA IF NOT EXISTS {S}",
                  "CREATE OR REPLACE TABLE {S}.stock (product_id STRING, qty INT) USING DELTA",
                  "INSERT INTO {S}.stock VALUES ('P-001',12),('P-002',19),('P-003',0)",
                  "CREATE OR REPLACE TABLE {S}.changes (product_id STRING, qty INT, op STRING)",
                  "INSERT INTO {S}.changes VALUES ('P-001',15,'U'),('P-003',0,'D'),('P-004',7,'I')"],
        "tasks": [_t("merge", "MERGE INTO {S}.stock USING {S}.changes c ON stock.product_id = c.product_id WHEN MATCHED AND c.op = 'D' THEN DELETE WHEN MATCHED THEN UPDATE SET qty = c.qty WHEN NOT MATCHED AND c.op <> 'D' THEN INSERT (product_id, qty) VALUES (c.product_id, c.qty)", compare=False, note="변경 실행(결과는 다음 task로 대조)"),
                  _t("after_merge", "SELECT product_id, qty FROM {S}.stock"),
                  _t("history", "DESCRIBE HISTORY {S}.stock", note="관찰용: operation 순서를 검토자가 확인", observe=True)],
        "cleanup": ["DROP SCHEMA IF EXISTS {S} CASCADE"], "schema": "wz_lab_de03"},
    "LAB-DE-12": {
        "title": "Bundle validate/deploy/run과 CLI 버전", "exam": ["DE-A", "DE-P"], "pack": "DE-12", "kind": "cli", "est_minutes": 40,
        "goal": "실제 CLI로 bundle validate·deploy·run을 수행하고 CLI 버전·검증 결과·run ID를 증거로 남긴다. (CLI ≥ 0.218.0)",
        "steps": ["bundle 디렉터리에서 `python dbx_lab_runner.py bundle-evidence --dir <bundle 경로> --cloud ... --region ...` 실행.", "deploy/run은 본인 교육용 target(dev)에서만 수행하고 job run URL/ID를 검토자에게 제시한다."],
        "setup": [], "tasks": [], "cleanup": [], "schema": None},
}
from .labs_manual import MANUAL as _MANUAL, DE05 as _DE05  # noqa: E402
import json as _json, hashlib as _hl  # noqa: E402
LABS.update(_MANUAL)
LABS["LAB-DE-05"] = dict(_DE05)
for _id, _l in LABS.items():
    _l["lab_id"] = _id
    if _l["kind"] in ("machine", "cli"):
        _l["pack_hash"] = common.pack_hash(_l["setup"], _l["tasks"], _l["cleanup"])
    else:
        _l["pack_hash"] = _hl.sha256(_json.dumps([_l["title"], _l["steps"], _l.get("required_artifacts"), _l.get("rubric")], sort_keys=True, ensure_ascii=False).encode()).hexdigest()

_EXPECTED: dict = {}


def _duck_sql(sql, S="lab"):
    return re.sub(r"\s+USING\s+DELTA", "", sql.replace("{S}", S), flags=re.I)


def expected(lab_id):
    """DuckDB로 setup/tasks를 실행해 compare task의 (checksum, row_count) 계산. 서버 내부 전용."""
    if lab_id in _EXPECTED:
        return _EXPECTED[lab_id]
    lab = LABS[lab_id]
    out = {}
    if lab["tasks"]:
        c = duckdb.connect()
        for s in lab["setup"]:
            c.execute(_duck_sql(s))
        for t in lab["tasks"]:
            if t.get("observe"):
                continue  # 서버(DuckDB)에서 실행 불가한 관찰용 task: 검토자가 원본 확인
            cur = c.execute(_duck_sql(t["sql"]))
            if t["compare"]:
                rows = cur.fetchall()
                out[t["id"]] = common.checksum_rows(rows)
        c.close()
    _EXPECTED[lab_id] = out
    return out


def catalog():
    """학습자에게 공개: 기대값·체크섬 제외."""
    return [{"lab_id": l["lab_id"], "title": l["title"], "exam": l["exam"], "pack": l["pack"], "kind": l["kind"], "est_minutes": l["est_minutes"], "goal": l["goal"], "steps": l["steps"],
             "pack_hash": l["pack_hash"], "machine_checked_tasks": [t["id"] for t in l["tasks"] if t["compare"]], "schema": l["schema"],
             "required_artifacts": l.get("required_artifacts", []), "rubric": l.get("rubric", []), "pass_score": l.get("pass_score")} for l in sorted(LABS.values(), key=lambda x: x["lab_id"])]


def pack(lab_id):
    l = LABS.get(lab_id)
    if not l:
        return None
    if l["kind"] != "machine":
        return {"lab_id": lab_id, "kind": l["kind"], "title": l["title"], "goal": l["goal"], "steps": l["steps"], "pack_hash": l["pack_hash"], "required_artifacts": l.get("required_artifacts", []),
                "rubric": l.get("rubric", []), "pass_score": l.get("pass_score"), "caution": l.get("caution", ""),
                "note": "SQL 자동 대조 팩이 아님. 산출물을 만든 뒤 `python dbx_lab_runner.py hash-artifacts --files ...` 로 해시를 만들어 제출하고, 검토자가 원본·루브릭으로 채점한다."}
    return {"lab_id": lab_id, "kind": "machine", "title": l["title"], "goal": l["goal"], "schema": l["schema"], "placeholder": "{S} = <catalog>.<schema>", "setup": l["setup"],
            "tasks": [{"id": t["id"], "sql": t["sql"], "compare": t["compare"], "note": t["note"], "observe": t.get("observe", False)} for t in l["tasks"]], "cleanup": l["cleanup"], "pack_hash": l["pack_hash"],
            "safety": "adapter는 {S} 스키마 외 객체를 건드리는 SQL, GRANT/REVOKE/ALTER, 비허용 host를 거부한다."}


def verify(lab_id, pack_hash, task_results):
    """task_results: {task_id: {"checksum","row_count","statement_id"}} -> 자동 대조. 기대값은 반환하지 않는다."""
    lab = LABS[lab_id]
    if pack_hash != lab["pack_hash"]:
        return {"state": "PACK_STALE", "per_task": {}, "reason": "제출한 증거의 pack_hash가 현재 팩과 다름 — 최신 팩으로 다시 실행"}
    exp = expected(lab_id)
    per, ok, missing_sid = {}, True, []
    for tid, (chk, n) in exp.items():
        r = (task_results or {}).get(tid)
        if not r:
            per[tid] = "MISSING"; ok = False; continue
        if not r.get("statement_id"):
            missing_sid.append(tid)
        match = r.get("checksum") == chk and r.get("row_count") == n
        per[tid] = "MATCH" if match else "MISMATCH"
        ok = ok and match
    state = "MATCHED" if ok else ("INCOMPLETE" if any(v == "MISSING" for v in per.values()) and not any(v == "MISMATCH" for v in per.values()) else "MISMATCH")
    return {"state": state, "per_task": per, "missing_statement_ids": missing_sid}
