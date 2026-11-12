"""AI 지원: 전체 여정(절차)·진행 판정·대화형 안내. 모든 판정은 세션 상태(milestones/자원 상태)에서 계산한다.
LLM이 아니라 결정적 규칙 + 승인된 KB 검색이다(근거 없으면 '확인 필요')."""
from __future__ import annotations
import re
from . import core, content as C

CAT = core.CAT


def M(name):
    return lambda S: name in S["milestones"]


def nav(label, view, **kw):
    return {"type": "nav", "label": label, "view": view, **kw}


def run(label, ctype, payload=None, view=None):
    return {"type": "cmd", "label": label, "command_type": ctype, "payload": payload or {}, "view": view}


SQL_SILVER = f"SELECT * FROM {CAT}.silver.orders LIMIT 5"
SQL_FIX = ("CREATE OR REPLACE VIEW food_dev.gold.v_available_inventory AS\nSELECT product_id, SUM(on_hand_qty - reserved_qty - damaged_qty) AS available_qty\n"
           "FROM food_dev.silver.inventory GROUP BY product_id")
PL_FIX = ("SELECT order_id, customer_id, CAST(order_date AS DATE) AS order_date, status, CAST(version AS INTEGER) AS version\n"
          "FROM food_dev.bronze.raw_orders\nQUALIFY ROW_NUMBER() OVER (PARTITION BY order_id ORDER BY updated_at DESC) = 1")


CDC_SQL = ("CREATE OR REPLACE TABLE food_dev.silver.customers_cdc AS\n"
           "WITH d AS (SELECT DISTINCT event_id, customer_id, op, city, seq FROM food_dev.bronze.cdc_events),\n"
           "l AS (SELECT * FROM d QUALIFY ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY seq DESC) = 1)\n"
           "SELECT customer_id, city FROM l WHERE op <> 'D'")


def sql_fill(label, sql):
    return nav(label, "sql", prefill={"sqlbox": sql})


def ack(label, key, view=None):
    return run(label, "guide.ack", {"key": key}, view)


# step: id, phase, title, why(왜 필요한가), view, subs[(key, text, done(S), shortcut)]
JOURNEY = [
    {"id": "env", "phase": "준비", "title": "환경·신원·프로필 확인", "view": "env",
     "why": "작업을 시작하기 전에 내가 어떤 클라우드·워크스페이스·신원·권한으로 접속했는지, 무엇이 확인되지 않았는지(unknown)를 구분합니다. 현장에서 가장 먼저 하는 일입니다.",
     "subs": [("env_check", "환경 점검 실행(프로필·실행 신원·미확인 항목)", M("env_checked"), run("환경 점검 실행", "env.check", {}, "env")),
              ("unverified", "미확인 기능(Oracle CDC)을 선택해 '확인 필요'를 확인", M("unverified_feature_blocked"), run("oracle_cdc 선택해보기", "feature.use", {"feature_id": "oracle_cdc"}, "env")),
              ("wh", "SQL Warehouse 시작", lambda S: core.wh_state(S) == "RUNNING", run("Warehouse 시작", "warehouse", {"action": "start"}, "comp"))]},
    {"id": "req", "phase": "준비", "title": "요구·데이터 계약 검토", "view": "req",
     "why": "무엇을 만들지 합의하는 단계입니다. 특히 '가용재고'의 정의가 이후 모든 판단(추가 부족량 3 vs 23)을 좌우합니다.",
     "subs": [("req_read", "인터뷰 카드와 데이터 계약(재고 산식·VAT·반품)을 읽고 확인", M("ack_req"), ack("계약을 확인했습니다", "req", "req"))]},
    {"id": "perm", "phase": "권한", "title": "권한 오류 진단과 최소권한 요청", "view": "sql",
     "why": "SELECT 권한이 있어도 부모 스키마의 USE SCHEMA가 없으면 실패합니다. 오류에서 누락 권한을 찾아 관리자에게 '필요한 최소 권한'만 요청합니다.",
     "subs": [("deny", "silver 테이블 조회가 권한 오류로 실패하는 것을 확인", M("sql_perm_denied"), sql_fill("조회 SQL 입력", SQL_SILVER)),
              ("ticket", "오류에 나온 누락 권한으로 티켓 제출", M("ticket_created"), nav("권한 요청서 열기(자동 입력)", "perm", prefill={"t_sec": "schema:food_dev.silver", "t_priv": "USE SCHEMA", "t_reason": "silver 테이블 조회 실습 — USE SCHEMA 최소권한 요청"})),
              ("approve", "관리자가 티켓 승인 (UC 관리자/강사 역할)", M("ticket_resolved"), nav("티켓 현황 보기", "perm")),
              ("retry", "같은 SQL을 다시 실행해 성공 확인", M("select_ok_silver"), sql_fill("다시 실행하러 가기", SQL_SILVER))]},
    {"id": "conn", "phase": "수집", "title": "원천 연결·Foreign catalog", "view": "conn",
     "why": "원천이 OCI의 Oracle일 때 Federation/배치/CDC 중 무엇을 택할지 근거를 정하고, 연결 실패가 네트워크·인증·권한·지원 범위 중 무엇인지 구분합니다.",
     "subs": [("mode", "수집 방식(Federation 또는 배치) 선택", lambda S: bool(S["connections"]["oracle_food_conn"]["mode"]), run("Federation 선택", "connection", {"action": "select_mode", "mode": "federation"}, "conn")),
              ("test", "연결 테스트(합성 .invalid 호스트)", lambda S: S["connections"]["oracle_food_conn"]["status"] == "OK" or "conn_fault_seen" in S["milestones"], run("연결 테스트", "connection", {"action": "test"}, "conn")),
              ("fcat_deny", "Foreign catalog 생성 시 UC 권한 오류 확인(DB 계정과 별개)", M("foreign_perm_denied"), run("생성 시도", "connection", {"action": "create_foreign_catalog"}, "conn")),
              ("fcat_ticket", "권한 2개(connection의 CREATE FOREIGN CATALOG + metastore의 CREATE CATALOG)를 요청 → 관리자 승인 후 생성", M("foreign_catalog_created"), nav("권한 요청서 열기(자동 입력)", "perm", prefill={"t_sec": "connection:oracle_food_conn", "t_priv": "CREATE FOREIGN CATALOG", "t_reason": "foreign catalog 생성 실습 — connection 최소권한 (이후 metastore CREATE CATALOG도 별도 요청)"}))]},
    {"id": "recon", "phase": "데이터", "title": "계약 산식으로 gold 재고 뷰 수정", "view": "sql",
     "why": "gold.v_available_inventory가 계약 산식과 다릅니다(damaged_qty 누락). 수정하면 대표 상품(P-001)의 가용재고가 {NAIVE} → {AVAIL}로 바뀌고, 이후 정책 입력도 함께 바뀝니다.",
     "subs": [("see", "현재 뷰가 계약과 다른 것을 확인(정합성 검사)", lambda S: "view_fixed" in S["milestones"] or any(e["event_type"] == "SQL_EXECUTED" for e in S["audit"]), run("계약 정합성 검사", "contract.check", {}, "agent")),
              ("fix", "계약 산식으로 CREATE OR REPLACE VIEW 실행", M("view_fixed"), sql_fill("수정 SQL 채우기", SQL_FIX)),
              ("recon", "정합성 검사 통과 (P-001 가용재고 {AVAIL})", M("recon_ok"), run("정합성 다시 검사", "contract.check", {}, "agent"))]},
    {"id": "pipe", "phase": "데이터", "title": "파이프라인 품질 차단과 복구", "view": "pipe",
     "why": "중복 키는 차단 규칙입니다. 실패를 성공으로 숨기지 않고 원인을 찾아 소스 정의를 고친 뒤, 원천 대비 건수로 정합성을 대조합니다.",
     "subs": [("val", "Validate (검증 성공 ≠ 실행 성공)", M("pipeline_validated"), run("Validate", "pipeline", {"action": "validate"}, "pipe")),
              ("fail", "Run → 중복키(pk_unique) 위반으로 FAILED 확인", M("pipeline_failed_dq"), run("Run", "pipeline", {"action": "run"}, "pipe")),
              ("fix", "소스를 최신 행 1건만 남기도록 수정 후 재검증·재실행", M("pipeline_ok"), nav("수정 SQL 채우기", "pipe", prefill={"plsql": PL_FIX})),
              ("recon", "원천 대비 건수 대조 일치(303행, 격리 4건)", M("pipeline_recon_ok"), nav("실행 이력 보기", "pipe"))]},
    {"id": "cdc", "phase": "데이터", "title": "CDC 이벤트 재생: 최신 상태 테이블과 재적용", "view": "cdc",
     "why": "변경 로그에는 중복·역순 도착·삭제·재삽입이 섞여 있습니다. 도착 순서가 아니라 seq 기준으로 멱등하게 적용하고, 새 배치가 와도 같은 로직으로 재적용되는지 확인합니다. (교육용 재생이며 실제 Lakeflow 커넥터 실행과 별개)",
     "subs": [("view", "bronze.cdc_events 를 조회해 중복·역순·삭제 이벤트를 확인", M("cdc_events_viewed"), sql_fill("이벤트 조회 SQL", "SELECT * FROM food_dev.bronze.cdc_events ORDER BY seq")),
              ("b1", "silver.customers_cdc 를 구축해 1차 정합성 통과", M("cdc_batch1_ok"), nav("CDC 화면 열기", "cdc", prefill={"cdcsql": CDC_SQL})),
              ("next", "새 배치 도착(중복·seq 누락 포함)", M("cdc_batch2_arrived"), run("다음 배치 도착", "cdc.next_batch", {}, "cdc")),
              ("b2", "같은 로직으로 재적용해 최종 정합성 통과", M("cdc_batch2_ok"), nav("CDC 화면 열기", "cdc", prefill={"cdcsql": CDC_SQL}))]},
    {"id": "job", "phase": "데이터", "title": "Job: 소유자 vs 실행 신원(run-as)", "view": "jobs",
     "why": "편집자(나)는 조회되지만 run-as 주체에 권한이 없으면 Job은 실패합니다. 누가 실행하는지에 따라 결과가 달라집니다.",
     "subs": [("fail", "run-as=svc-runner로 실행해 권한 실패와 후속 task 건너뜀 확인", M("job_runas_fail"), run("Job 실행", "job", {"action": "run"}, "jobs")),
              ("fix", "run-as를 본인으로 바꾸거나 권한을 요청해 재실행 성공", M("job_ok"), run("run-as를 나로 변경", "job", {"action": "set_run_as", "run_as": core.TRAINEE}, "jobs"))]},
    {"id": "genie", "phase": "의미·AI", "title": "Genie 질의와 사용자별 접근 차단", "view": "genie",
     "why": "자연어 질의도 사용자의 UC 권한을 넘을 수 없습니다. 생성된 SQL과 결과를 검수하고, 다른 사용자(analyst-b)로 물어 데이터 누출이 없는지 확인합니다.",
     "subs": [("cfg", "재고 뷰를 Genie 데이터셋에 등록", lambda S: f"{CAT}.gold.v_available_inventory" in S["genie"]["datasets"], run("재고 뷰 등록", "genie.config", {"datasets": [f"{CAT}.gold.v_order_overview", f"{CAT}.gold.v_available_inventory"]}, "genie")),
              ("ok", "질문하고 생성 SQL·결과 확인", M("genie_ok"), run("‘총 주문 박스’ 질의", "genie.ask", {"question": "총 주문 박스는?"}, "genie")),
              ("leak", "analyst-b로 질의 → 접근 차단 확인", M("genie_leak_blocked"), run("analyst-b로 재고 질의", "genie.ask", {"question": "P-001 가용재고는?", "as_persona": core.ANALYST}, "genie"))]},
    {"id": "order", "phase": "업무 AI", "title": "주문 변경: 계산 → 정책 → 제안 → 승인 → 실행", "view": "agent",
     "why": "O-10021은 {CUR}→{REQ}박스 요청이며 가용재고 {AVAIL}는 ‘추가 할당 가능 수량’입니다. 추가 부족량은 {GAP}(총량−가용이 아님). 마감 이후이므로 원안은 실행할 수 없고 승인된 대안만 실행됩니다.",
     "subs": [("gap", "추가 부족량 {GAP} 확인 ({REQ}−{CUR}−{AVAIL})", M("shortage_3_found"), nav("사실 조회·정책 평가 화면", "agent")),
              ("prop", "정책 평가로 제안 생성 (payload hash 발급)", M("proposal_made"), run("제안 생성(요청 {REQ})", "order.propose", {"order_id": "O-10021", "requested_total": "{REQ}"}, "agent")),
              ("appr", "리뷰어가 승인 (요청자≠승인자)", M("approved"), nav("승인 화면", "agent")),
              ("exec", "가상 AX API 실행·사후 대조", M("ax_executed"), nav("실행 화면", "agent"))]},
    {"id": "safety", "phase": "업무 AI", "title": "서버 통제: 무승인·변조·멱등·충돌", "view": "agent",
     "why": "클라이언트 입력은 신뢰하지 않습니다. 승인 없이 실행, payload 변조, 같은 요청 반복, 승인 후 버전 변경이 서버에서 어떻게 막히는지 직접 시험합니다.",
     "subs": [("noap", "승인 없이 실행 시도 → 차단", M("ax_no_approval_blocked"), nav("API 실행 칸에서 승인 선택을 비우고 실행", "agent")),
              ("tamper", "payload의 new_qty를 바꿔 실행 → 변조 차단", M("tamper_blocked"), nav("payload 편집 칸으로", "agent")),
              ("idem", "같은 멱등키로 재실행 → 결과 동일(주문 1회 변경)", M("idem_replayed"), nav("같은 키로 다시 실행", "agent")),
              ("conf", "강사가 버전 충돌을 주입 → 재조회·재제안·재승인", M("version_conflict_seen"), nav("강사 도구(장애 주입)", "inst"))]},
    {"id": "bundle", "phase": "배포", "title": "CLI·Bundle: validate ≠ deploy ≠ run", "view": "bundle",
     "why": "검증 성공은 배포·실행·정합성을 보증하지 않습니다. 수정한 파일을 배포하지 않으면 run은 이전 배포본을 실행합니다.",
     "subs": [("login", "가상 로그인 + validate", M("bundle_validate"), nav("터미널 열기", "bundle", prefill={"clibox": "databricks auth login --host https://training-workspace.invalid"})),
              ("deploy", "deploy", M("bundle_deploy"), nav("터미널 열기", "bundle", prefill={"clibox": "databricks bundle deploy -t dev"})),
              ("run", "run (배포된 버전 실행)", M("bundle_run"), nav("터미널 열기", "bundle", prefill={"clibox": "databricks bundle run -t dev training_job"})),
              ("drift", "파일 수정 후 미배포 상태로 run → drift 확인", M("drift_seen"), nav("파일 편집·재실행", "bundle"))]},
    {"id": "nb", "phase": "배포", "title": "Notebook: 오래된 결과와 재시작", "view": "nb",
     "why": "위 셀을 고치면 아래 셀의 결과는 오래된 상태입니다. 재시작하면 변수는 사라지고 저장된 테이블은 남습니다.",
     "subs": [("stale", "셀을 실행한 뒤 위 셀을 수정해 STALE 확인", M("notebook_stale_seen"), nav("Notebook 열기", "nb")),
              ("restart", "커널 재시작", M("notebook_restart"), run("재시작", "notebook", {"action": "restart"}, "nb"))]},
    {"id": "iso", "phase": "통제", "title": "실제 URL·자격증명 차단", "view": "bundle",
     "why": "A/B 모드는 실제 호스트에 연결하지 않으며 입력한 비밀값을 저장하지 않습니다.",
     "subs": [("host", "실제 호스트로 로그인 시도 → 차단", M("external_url_blocked"), nav("터미널 열기", "bundle", prefill={"clibox": "databricks auth login --host https://example.cloud.databricks.com"}))]},
    {"id": "eval", "phase": "평가", "title": "평가셋 40건 실행", "view": "trace",
     "why": "정상·마감·재고·단위·반품·권한·승인 변조 등을 정책 결정과 데이터 결과로 채점합니다(문장 유사도만으로 통과시키지 않음).",
     "subs": [("run", "평가셋 실행", M("eval_run"), run("평가셋 실행", "eval.run", {}, "trace"))]},
    {"id": "wrap", "phase": "인수", "title": "증거 보고서와 고객 설명", "view": "evid",
     "why": "모의에서 확인한 것과 실제 DBX에서 확인해야 할 것을 정확히 구분해 설명합니다. 평가자가 설명 점수를 입력하면 수료 판정이 완성됩니다.",
     "subs": [("evid", "증거 보고서 검토(모드·프로필·코드 해시·한계)", M("ack_wrap"), ack("검토했습니다", "wrap", "evid")),
              ("score", "강사/리뷰어의 설명 평가 점수 입력", lambda S: S["assessment"]["explain_score"] is not None, nav("수료 평가 보기", "inst"))]},
]


def _fill(obj, cz):
    """고정 문자열(O-10021 등)을 세션 시드의 사례 값으로 치환(결과를 외워서 푸는 것을 방지)."""
    import json as _j
    t = _j.dumps(obj, ensure_ascii=False)
    for k, v in (("O-10021", cz["order"]), ("P-001", cz["product"]), ("C-007", cz["cust"]), ("{REQ}", str(cz["requested"])), ("{CUR}", str(cz["current"])), ("{AVAIL}", str(cz["available"])), ("{GAP}", str(cz["gap"])), ("{NAIVE}", str(cz["naive_available"]))):
        t = t.replace(k, v)
    return _j.loads(t)


def journey(S):
    cz = S.get("case") or core.seedmod.case()
    steps, cur = [], None
    for i, st in enumerate(JOURNEY):
        subs = []
        for key, text, done, sc in st["subs"]:
            if key == "fix" and st["id"] == "job":   # run-as를 이미 나로 바꿨다면 다음은 '재실행'
                jb = next(iter(S["jobs"].values()), None)
                if jb and jb.get("run_as") == core.TRAINEE:
                    sc = run("Job 재실행(run-as 변경 후)", "job", {"action": "run"}, "jobs")
            if key == "fcat_ticket":   # 권한 2개가 필요한 단계: 이미 받은 권한은 건너뛰고 '아직 없는 권한'의 요청서를 안내한다
                have = {(g[1], g[2]) for g in S["grants"]}
                open_t = {(t["privilege"], t["securable"]) for t in S["tickets"] if t["status"] == "OPEN"}
                need = [(p_, sec_) for p_, sec_ in (("CREATE FOREIGN CATALOG", "connection:oracle_food_conn"), ("CREATE CATALOG", "metastore:main")) if (p_, sec_) not in have]
                pend = [x for x in need if x not in open_t]
                if not need:     # 권한 2개를 모두 받았으면 이제 foreign catalog를 만든다
                    sc = run("Foreign catalog 생성", "connection", {"action": "create_foreign_catalog"}, "conn")
                elif not pend:
                    sc = nav("관리자 승인 대기 중 — 권한·관리 화면에서 티켓 상태 확인", "perm")
                elif pend:
                    p_, sec_ = pend[0]
                    sc = nav(f"권한 요청서 열기(자동 입력): {p_}", "perm", prefill={"t_sec": sec_, "t_priv": p_, "t_reason": ("foreign catalog 생성 실습 — connection 최소권한" if p_ == "CREATE FOREIGN CATALOG" else "foreign catalog 생성에 필요한 metastore 권한(최소권한)")})
            subs.append({"key": key, "text": text, "done": bool(done(S)), "shortcut": sc})
        n_done = sum(s["done"] for s in subs)
        status = "done" if n_done == len(subs) else ("current" if cur is None else "pending")
        if status == "current":
            cur = i
        steps.append({"id": st["id"], "no": i + 1, "phase": st["phase"], "title": st["title"], "why": st["why"], "view": st["view"], "subs": subs, "done": n_done, "total": len(subs), "status": status})
    steps = _fill(steps, cz)
    total = sum(s["total"] for s in steps); done = sum(s["done"] for s in steps)
    nxt = None
    if cur is not None:
        s = steps[cur]
        sub = next(x for x in s["subs"] if not x["done"])
        nxt = {"step": s["id"], "step_no": s["no"], "title": s["title"], "sub": sub["text"], "shortcut": sub["shortcut"]}
    return {"steps": steps, "current": cur, "percent": round(100 * done / total), "done": done, "total": total, "next": nxt,
            "note": "단계를 열었다고 완료되지 않습니다. 실행 결과·권한·정합성 사건으로 판정합니다. 순서는 권장이며 건너뛸 수 있습니다."}


SCREENS = {
    "cdc": ["cdc", "변경 로그", "이벤트 재생", "scd"], "env": ["환경", "프로필", "신원", "uc-01", "ui-01"], "req": ["요구", "계약", "인터뷰", "ui-02"], "ws": ["workspace", "워크스페이스", "ui-03"], "cat": ["catalog", "카탈로그", "계보", "lineage", "ui-04"],
    "sql": ["sql", "쿼리", "ui-05"], "nb": ["notebook", "노트북", "셀", "ui-06"], "comp": ["warehouse", "웨어하우스", "compute", "컴퓨트", "ui-07"], "conn": ["연결", "connection", "foreign", "수집", "cdc", "federation", "ui-08"],
    "pipe": ["pipeline", "파이프라인", "품질", "ui-09"], "jobs": ["job", "잡", "run-as", "스케줄", "ui-10"], "genie": ["genie", "지니", "온톨로지", "의미", "ui-11"], "agent": ["승인", "에이전트", "agent", "주문", "정책", "ui-12"],
    "trace": ["trace", "평가", "비용", "ui-13"], "bundle": ["bundle", "번들", "cli", "git", "터미널", "ui-14"], "perm": ["권한", "티켓", "grant", "ui-15"], "inst": ["강사", "수료", "장애", "ui-16"], "evid": ["증거", "보고서"],
    "prof": ["역량", "등급", "ui-17"], "plan": ["학습계획", "계획", "ui-18"], "map": ["목표 지도", "objective", "커버리지", "ui-19"], "tutor": ["튜터", "ui-20"], "exam": ["시험", "모의", "ui-21"], "lab": ["실습 증거", "증거함", "실제 실습", "adapter", "어댑터", "ui-22"],
    "qual": ["문항", "품질", "ui-23"], "partner": ["파트너", "인력", "ui-24"], "conf": ["충돌", "상충", "ui-25"],
}
SCREEN_NAME = {"cdc": "UI-09b CDC 재생", "env": "UI-01 환경 점검", "req": "UI-02 요구·계약", "ws": "UI-03 Workspace", "cat": "UI-04 Catalog Explorer", "sql": "UI-05 SQL Editor", "nb": "UI-06 Notebook", "comp": "UI-07 Compute", "conn": "UI-08 Connections",
               "pipe": "UI-09 Pipelines", "jobs": "UI-10 Jobs", "genie": "UI-11 의미모델·Genie", "agent": "UI-12 Agent·승인", "trace": "UI-13 Tracing/평가", "bundle": "UI-14 Git/Bundle/CLI", "perm": "UI-15 권한·관리", "inst": "UI-16 강사·수료",
               "evid": "증거 보고서", "prof": "UI-17 역량·등급", "plan": "UI-18 학습계획", "map": "UI-19 공식 목표 지도", "tutor": "UI-20 AI 튜터", "exam": "UI-21 시험센터", "lab": "UI-22 실습 증거함", "qual": "UI-23 콘텐츠 품질", "partner": "UI-24 파트너 인력", "conf": "UI-25 자료 충돌"}

ERR_HELP = {
    "INSUFFICIENT_PERMISSIONS": "권한 오류입니다. 로그인 성공과 권한은 별개이며, 오류 문구의 **누락 권한(어느 계층: catalog/schema/table)**을 찾는 것이 첫 단계입니다. 전체 관리자 권한이 아니라 그 권한만 최소로 요청하세요. 자기 자신에게 GRANT 하면 금지 이벤트로 기록됩니다.",
    "WAREHOUSE_NOT_RUNNING": "SQL Warehouse가 꺼져 있습니다. 시작 후 몇 번의 명령이 지나면 RUNNING이 됩니다(결정적 시뮬레이션).",
    "TABLE_OR_VIEW_NOT_FOUND": "객체를 찾지 못했습니다. 3단계 이름(catalog.schema.table)과 철자, 그리고 파이프라인이 먼저 실행되어 대상 테이블이 만들어졌는지 확인하세요.",
    "SIMULATOR_UNSUPPORTED": "시뮬레이터가 지원하지 않는 구문·함수입니다. Databricks가 지원하지 않는다는 뜻이 아니며, 공식 문서에서 확인해야 합니다(가짜 성공을 만들지 않습니다).",
    "PARSE_ERROR": "SQL 구문 오류입니다. 괄호·쉼표·키워드 철자를 확인하세요.",
    "NO_APPROVAL": "승인 없이 주문을 변경할 수 없습니다. 이것이 정상 통제입니다. 제안 → 리뷰어 승인 → 실행 순서로 진행하세요.",
    "PAYLOAD_TAMPERED": "요청 payload가 승인된 내용과 달라 서버가 차단했습니다(감사 이벤트 기록).",
    "VERSION_CONFLICT": "승인 이후 주문 버전이 바뀌었습니다. 재조회 → 새 제안 → 재승인이 필요합니다.",
    "INVENTORY_CHANGED": "승인 이후 가용재고가 바뀌어 재검증에 실패했습니다. 새 제안과 재승인이 필요합니다.",
    "APPROVAL_EXPIRED": "승인이 만료되었습니다(30분). 새 제안이 필요합니다.",
    "FEATURE_UNVERIFIED": "프로필에서 미확인(unverified)인 기능입니다. 성공을 모사하지 않으며 담당자 확인·증거 요청이 필요합니다.",
    "REAL_HOST_BLOCKED": "실제 호스트 입력은 저장·접속되지 않고 차단됩니다. 합성 .invalid 호스트만 사용하세요.",
    "PYTHON_ISOLATION_NOT_CONFIGURED": "이 배포에는 Python 격리 실행기가 없어 Python 셀은 실행하지 않습니다(흉내 내지 않음). SQL 셀을 사용하세요.",
    "GOLD_VIEW_BROKEN": "정책이 읽는 gold 재고 뷰가 깨졌습니다. 계약 산식으로 뷰를 복구하세요.",
}


def _last_failure(S):
    for e in reversed(S["audit"]):
        if e["outcome"] in ("failed", "blocked", "conflict"):
            return e
    return None


def _kb(q):
    ql = q.lower()
    return [k for k in C.KB if any(t in ql for t in k["tags"])]


def _next_answer(S, J):
    n = J["next"]
    if not n:
        return "모든 단계의 증거가 확보되었습니다. **증거 보고서**를 검토하고 강사/리뷰어의 설명 평가를 받으세요.", [nav("증거 보고서 열기", "evid")]
    st = J["steps"][J["current"]]
    done = [s for s in st["subs"] if s["done"]]
    txt = (f"지금은 **{n['step_no']}단계 · {n['title']}** 입니다.\n\n{st['why']}\n\n"
           + (f"완료한 항목 {len(done)}/{st['total']}. " if done else "") + f"다음 할 일: **{n['sub']}**")
    return txt, [n["shortcut"]] + [s["shortcut"] for s in st["subs"] if not s["done"]][1:3]


def chat(S, actor, message, mode_real=False, view=None):
    """자연어 질문 응답 — 의도 분류 엔진(assistant.py)에 위임한다. 이전 단순 키워드 방식은 _legacy_chat 으로 보존."""
    from . import assistant
    return assistant.answer(S, actor, message, mode_real, view)


def _legacy_chat(S, actor, message, mode_real=False):
    q = (message or "").strip()
    ql = q.lower()
    if S is None:
        return {"answer": "먼저 세션을 만들어야 단계를 안내할 수 있습니다. **UI-01 환경 점검**에서 ‘세션 시작’을 누르세요. 교육 모드(안내형·실습형·실전형·고객 시연형)는 힌트 노출 정도를 정합니다.",
                "shortcuts": [nav("환경 점검으로 이동", "env")], "context": None}
    J = journey(S)
    sc, ans = [], ""
    if any(k in ql for k in ("전체", "절차", "로드맵", "단계 목록", "순서")):
        ans = "전체 절차입니다(순서는 권장, 건너뛸 수 있음).\n" + "\n".join(f"{s['no']}. {s['title']} — {s['done']}/{s['total']}" + (" ✅" if s["status"] == "done" else "") for s in J["steps"])
        sc = [nav("현재 단계로 이동", J["steps"][J["current"]]["view"])] if J["current"] is not None else []
    elif any(k in ql for k in ("진행", "현황", "얼마나", "몇 %", "완료율")):
        ans = f"전체 진행률 **{J['percent']}%** ({J['done']}/{J['total']} 항목). " + (f"현재 {J['next']['step_no']}단계 ‘{J['next']['title']}’ 진행 중입니다." if J["next"] else "모든 항목 완료.")
    elif any(k in ql for k in ("오류", "에러", "실패", "안돼", "안 돼", "왜 ", "error", "failed", "막혔", "막혀")):
        f = _last_failure(S)
        if not f:
            ans = "최근 실패·차단 이벤트가 없습니다. 오류가 나면 하단 로그의 error code를 알려주세요."
        else:
            code = f["detail"].get("code") or ""
            ans = f"최근 이벤트: **{f['event_type']}** ({f['outcome']})" + (f" · `{code}`" if code else "") + "\n\n" + ERR_HELP.get(code, "로그의 error code와 메시지를 먼저 읽고, 어느 계층(권한/데이터/코드/배포/승인)의 문제인지 분류해 보세요. 단순 재시도로는 해결되지 않습니다.")
            if f["detail"].get("missing"):
                m = f["detail"]["missing"]
                ans += f"\n\n누락 권한: **{m['privilege']}** on `{m['securable']}`"
                sc.append(nav("이 권한 요청서 열기(자동 입력)", "perm", prefill={"t_sec": m["securable"], "t_priv": m["privilege"], "t_reason": f"{m['securable']} 조회 업무 — {m['privilege']} 최소권한 요청"}))
            if code == "WAREHOUSE_NOT_RUNNING":
                sc.append(run("Warehouse 시작", "warehouse", {"action": "start"}, "comp"))
    elif any(k in ql for k in ("다음", "next", "뭐", "무엇", "시작", "어떻게", "이제", "계속", "도와")):
        if mode_real:
            ans = "실전형에서는 정답 위치를 안내하지 않습니다. 현재 단계는 **" + (J["next"]["title"] if J["next"] else "완료") + "** 입니다."
            sc = [nav("전체 절차 보기", "env")]
        else:
            ans, sc = _next_answer(S, J)
    else:
        scr = [k for k, kws in SCREENS.items() if any(w in ql for w in kws)]
        hit = _kb(q)
        if scr and any(w in ql for w in ("어디", "화면", "메뉴", "열어", "이동", "가줘", "가고", "바로", "보여")):
            ans = "해당 화면으로 바로 이동할 수 있습니다."
            sc = [nav(SCREEN_NAME[k], k) for k in scr[:4]]
        elif hit:
            ans = "\n\n".join(f"**{k['title']}** — {k['text']}" for k in hit[:2]) + "\n\n" + "\n".join(f"근거: {k['url']} (확인일 {C.BASIS})" for k in hit[:2])
            sc = [J["next"]["shortcut"]] if J["next"] and not mode_real else []
        elif scr:
            ans = "관련 화면입니다."
            sc = [nav(SCREEN_NAME[k], k) for k in scr[:4]]
        else:
            ans = ("승인된 근거에서 정확한 답을 찾지 못했습니다 — **확인 필요**로 두고 임의로 확정하지 않겠습니다. 다음과 같이 물어보시면 도와드릴 수 있어요: ‘다음에 뭐 해?’, ‘왜 실패했어?’, ‘전체 절차 보여줘’, ‘권한 개념 설명’, ‘Pipelines 화면 열어줘’.")
            sc = [J["next"]["shortcut"]] if J["next"] and not mode_real else []
    return {"answer": ans, "shortcuts": sc, "context": {"percent": J["percent"], "next": J["next"] and {"step_no": J["next"]["step_no"], "title": J["next"]["title"]}}}


# ---------------------------------------------------------------- 전 과정 프로젝트 트랙(8주 모듈) · 고객 시연 20분
TRACK = [("W1", "요구·데이터 계약", ["env", "req"]), ("W2", "접근(권한·연결)", ["perm", "conn"]), ("W3", "수집·모델(정합성·파이프라인·CDC)", ["recon", "pipe", "cdc"]), ("W4", "실행 신원·운영(Job·Notebook)", ["job", "nb"]),
         ("W5", "의미(Genie·온톨로지)", ["genie"]), ("W6", "승인형 에이전트(제안·승인·서버 통제)", ["order", "safety"]), ("W7", "평가", ["eval"]), ("W8", "배포·인수(Bundle·통제·증거 보고)", ["bundle", "iso", "wrap"])]


def track(S):
    J = journey(S)
    by = {s["id"]: s for s in J["steps"]}
    mods = []
    for wk, name, ids in TRACK:
        ss = [by[i] for i in ids if i in by]
        done, total = sum(s["done"] for s in ss), sum(s["total"] for s in ss)
        mods.append({"week": wk, "module": name, "steps": [{"id": s["id"], "no": s["no"], "title": s["title"], "status": s["status"]} for s in ss], "done": done, "total": total, "percent": round(100 * done / total) if total else 0})
    return {"modules": mods, "note": "주차는 실제 고객 일정의 약속이 아니라 훈련 모듈 구분입니다. 진행은 세션의 실제 사건으로 계산됩니다.", "percent": J["percent"]}


def _ev(S, *types):
    return [e for e in S["audit"] if e["event_type"] in types]


def demo(S):
    m = S["milestones"]
    cz = S.get("case") or core.seedmod.case()
    j = list(S["jobs"].values())[0]
    last_run = j["runs"][-1] if j["runs"] else None
    cn = S["connections"]["oracle_food_conn"]
    b = S["bundle"]
    dep = b["deployed"]
    seg = [("1", 2, "환경·권한·합성 데이터·검증 범위 설명", ["env_checked"], "env"), ("2", 4, "Catalog와 SQL로 원천·Gold 정합성 설명", ["recon_ok", "pipeline_recon_ok"], "sql"),
           ("3", 4, "Pipeline/Job 실행 및 주입된 권한·품질 오류 진단", ["pipeline_failed_dq", "job_runas_fail", "job_ok"], "pipe"), ("4", 4, "Genie 답변의 SQL·업무 의미 검수, 주문 변경 제안과 승인", ["genie_ok", "proposal_made", "approved"], "genie"),
           ("5", 3, "Bundle 수정·배포·실행 버전 구분, 감사 trace 제시", ["bundle_deploy", "drift_seen"], "bundle"), ("6", 3, "실제 현장 미확인 사항과 담당자별 요청·후속 검증 설명", ["ticket_created"], "evid")]
    segments = [{"no": n, "minutes": mi, "title": t, "ready": all(x in m for x in req), "missing_evidence": [x for x in req if x not in m], "view": v} for n, mi, t, req, v in seg]
    qa = []
    f = _ev(S, "SQL_FAILED", "SQL_PERMISSION_DENIED")
    perm = next((e for e in f if (e["detail"] or {}).get("code") == "INSUFFICIENT_PERMISSIONS"), None)
    qa.append({"q": "SELECT 권한이 있는데 왜 실패하나?", "answer": ("이 세션에서 재현했습니다: " + (perm["detail"].get("msg", "")[:160]) + " — 부모 USE 권한과 SELECT는 별개이며, 최소권한만 요청해 해결했습니다.") if perm else "부모(catalog/schema)의 USE 권한이 없으면 SELECT가 있어도 실패합니다. (이 세션에서는 아직 재현하지 않음 — UI-05에서 먼저 재현하세요.)", "evidence": [perm["event_id"]] if perm else [], "demonstrated": bool(perm)})
    qa.append({"q": "Job을 누른 사람과 run-as가 다른 이유는?", "answer": (f"실행은 run-as 신원({last_run['run_as']})의 권한으로 이뤄지고 트리거한 사람({last_run['triggered_by']})은 별개입니다. 이 세션의 최근 run은 {last_run['status']}였습니다.") if last_run else "데이터·컴퓨트 접근은 run-as 신원 기준이고, 실행 시작에는 별도 권한(CAN MANAGE RUN)이 필요합니다. (이 세션에서는 아직 Job을 실행하지 않음)", "evidence": [], "demonstrated": bool(last_run)})
    qa.append({"q": "원천이 OCI면 어떤 연결을 선택하나?", "answer": f"선택 방식: {cn['mode'] or '미선택'}, 연결 상태 {cn['status']}. CDC는 프로필에서 unverified이므로 DBA 증거·승인 요청이 먼저이고, 네트워크·인증·원천 권한·UC 권한을 구분해 진단합니다.", "evidence": [], "demonstrated": cn["status"] == "OK"})
    qa.append({"q": "검증 통과와 배포 성공이 무엇을 보장하나?", "answer": ("validate는 구성 검증, deploy는 배포, run은 배포본 실행입니다. " + (f"이 세션: 배포 해시 {dep['hash'][:10]}, 로컬과 {'다름(drift)' if dep['hash'] != core.bundle_hash(b['files']) else '같음'}." if dep else "아직 배포하지 않았습니다.")), "evidence": [], "demonstrated": bool(dep)})
    inv = _ev(S, "AX_REVALIDATION_FAILED", "AX_VERSION_CONFLICT")
    qa.append({"q": "재고가 승인 이후 바뀌면?", "answer": ("서버가 재검증에서 차단했습니다(" + inv[-1]["event_type"] + "). 재조회 → 새 제안 → 재승인이 필요합니다.") if inv else "승인 payload에 재고 스냅샷이 있어 실행 직전 재검증하고, 다르면 409로 차단해 새 제안·재승인을 요구합니다. (이 세션에서는 아직 재현하지 않음)", "evidence": [inv[-1]["event_id"]] if inv else [], "demonstrated": bool(inv)})
    qa.append({"q": "이 화면과 실제 Workspace의 차이를 어떻게 관리하나?", "answer": f"프로필 {S['profile_id']}는 {core.PROFILE['evidence_status']}(문서 확인)이며 워크스페이스 실측·SA 검토는 없습니다. 기능별 검증 상태와 현장 대조표로 차이를 관리하고, 미확인 기능은 '확인 필요'로 표시합니다.", "evidence": [], "demonstrated": True})
    return {"minutes_total": sum(s["minutes"] for s in segments), "segments": segments, "qa": qa, "case": {k: cz[k] for k in ("order", "product", "current", "requested", "available", "gap")},
            "note": "답변은 세션의 실제 실행 증거에서 만들어집니다. 증거가 없으면 '아직 재현하지 않음'으로 표시하며 숙련된 인상을 만드는 문구를 쓰지 않습니다."}
