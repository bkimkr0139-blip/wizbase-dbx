"use strict";
/* HELP: 현재 화면의 기능 개요 · 현재 상태 · 해야 할 일 · 이전/다음 화면. 상태는 세션 데이터에서 실시간 계산. */
const ms = n => !!(ST && ST.milestones.includes(n));
const FLOW_CORE = ["env", "req", "comp", "cat", "sql", "perm", "conn", "pipe", "jobs", "nb", "genie", "agent", "trace", "bundle", "inst", "evid"];
const FLOW_PRO = ["prof", "plan", "map", "tutor", "exam", "lab", "qual", "partner", "conf"];
const N = (label, view, prefill) => ({ type: "nav", label, view, ...(prefill ? { prefill } : {}) });
const C = (label, command_type, payload, view) => ({ type: "cmd", label, command_type, payload: payload || {}, view });
const S_ = (label, value, tone) => [label, value, tone || ""];
const noSess = () => ST ? null : S_("세션", "없음 — UI-01에서 시작", "w");
const when = (x, a, b) => x ? a : b;

const HELP = {
  env: {
    t: "UI-01 환경 점검", step: ["env"],
    overview: "작업을 시작하기 전에 어떤 클라우드·리전·프로필·실행 신원으로 접속했는지, 무엇이 아직 확인되지 않았는지(unknown)를 구분하는 출발 화면입니다. 세션도 여기서 만듭니다.",
    features: ["세션 시작: 모드(A 완전 모의 / B 로컬 실행)와 학습 모드(안내·실습·실전·시연) 선택", "환경 점검: 프로필·실행 신원·entitlement·미확인 항목 기록", "기능 매니페스트: 기능별 검증 상태(DRAFT/DOC_CHECKED…)와 ‘확인 필요’ 구분", "기준 프로필: 클라우드·리전·버전 분리 표기 (모든 기능 가능하다는 보증 아님)"],
    status: () => [noSess() || S_("세션", ST.session.id, "ok"), ST && S_("모드", `${ST.session.mode} · ${ST.session.learning_mode}`), ST && S_("환경 점검", when(ms("env_checked"), "완료", "미실행"), when(ms("env_checked"), "ok", "w")), ST && S_("Warehouse", ST.warehouse.state, ST.warehouse.state === "RUNNING" ? "ok" : "w"), ST && S_("미확인 기능 시험", when(ms("unverified_feature_blocked"), "완료", "미실행"), when(ms("unverified_feature_blocked"), "ok", "w"))],
    todo: () => [["세션 시작", !!ST, N("세션 만들기", "env")], ["환경 점검 실행", ms("env_checked"), C("점검 실행", "env.check", {}, "env")], ["미확인 기능(oracle_cdc) 선택해 ‘확인 필요’ 확인", ms("unverified_feature_blocked"), C("선택해보기", "feature.use", { feature_id: "oracle_cdc" }, "env")], ["Warehouse 시작", ST && ST.warehouse.state === "RUNNING", C("시작", "warehouse", { action: "start" }, "comp")]],
    caution: "모드는 세션 중간에 바꿀 수 없습니다. C 모드(실제 DBX)는 이 배포에서 사용할 수 없습니다."
  },
  req: {
    t: "UI-02 착수·요구·데이터 계약", step: ["req"],
    overview: "고객 인터뷰로 요구를 확인하고 데이터 계약(산식·단위·VAT·반품 규칙)을 검토하는 화면입니다. 이후 모든 계산의 기준이 됩니다.",
    features: ["인터뷰 카드: 마감·승인·가용재고 정의 확인과 누락 질문 후보", "데이터 계약: available_qty = on_hand − reserved − damaged", "공급가/VAT/반품 음수 규칙 명시"],
    status: () => [noSess() || S_("계약 확인", when(ms("ack_req"), "확인함", "미확인"), when(ms("ack_req"), "ok", "w"))],
    todo: () => [["계약을 읽고 ‘확인했습니다’ 기록", ms("ack_req"), C("계약 확인", "guide.ack", { key: "req" }, "req")]],
    caution: "가용재고 12는 ‘기존 20박스 예약 이후 추가 할당 가능 수량’입니다. 총량 35에서 12를 빼 23이라 하면 오답입니다."
  },
  ws: {
    t: "UI-03 Workspace", step: [],
    overview: "세션에 있는 Notebook·파일·Pipeline·Job 리소스를 한눈에 보고, 최근 변경 이력(감사 이벤트)을 확인하는 화면입니다.",
    features: ["리소스 목록과 이름 검색", "변경 이력: 시나리오 시각·유형·실행 주체·결과·증거 수준"],
    status: () => [noSess() || S_("Notebook 셀", ST.notebook.cells.length), ST && S_("Bundle 파일", Object.keys(ST.bundle.files).length), ST && S_("Pipeline / Job", `${Object.keys(ST.pipelines).length} / ${Object.keys(ST.jobs).length}`)],
    todo: () => [["필요한 리소스를 찾아 해당 화면으로 이동", false, N("Notebook", "nb")]], caution: "이 화면은 조회 전용입니다."
  },
  cat: {
    t: "UI-04 Catalog Explorer", step: [],
    overview: "catalog.schema.table 3단계 구조와 내 권한으로 보이는 범위를 탐색합니다. 테이블 미리보기·컬럼·계보도 확인합니다.",
    features: ["스키마 잠금 표시: USE SCHEMA/CATALOG 없으면 🔒", "SELECT 불가 테이블 구분 표시", "테이블 선택 시 컬럼·미리보기·계보(lineage)", "강사/관리자는 다른 주체(analyst-b, svc-runner) 시점으로 전환"],
    status: () => [noSess() || S_("조회 주체", ST.principal.split("@")[0]), ST && S_("silver USE SCHEMA", when(ST.grants.some(g => g[1] === "USE SCHEMA" && g[2].endsWith("silver")) || ST.tickets.some(t => t.status === "APPROVED" && t.privilege === "USE SCHEMA"), "부여됨", "없음(기본)"), when(ST.tickets.some(t => t.status === "APPROVED"), "ok", "w"))],
    todo: () => [["silver 스키마가 잠겨 있는지 확인", false, N("카탈로그 보기", "cat")], ["권한을 받은 뒤 테이블 미리보기", ms("select_ok_silver"), N("권한 요청서", "perm", { t_sec: "schema:food_dev.silver", t_priv: "USE SCHEMA", t_reason: "silver 조회 업무 — USE SCHEMA 최소권한 요청" })]],
    caution: "부모(USE) 권한과 SELECT는 별개입니다."
  },
  sql: {
    t: "UI-05 SQL Editor", step: ["perm", "recon"],
    overview: "SQL을 실행하는 화면입니다. 구문 분석 → 지원 범위 → UC 권한 → Warehouse 상태 → 격리 실행 → 감사 순서로 처리되며 결과는 입력에 따라 달라집니다.",
    features: ["지원: SELECT/JOIN/GROUP BY/CTE/CASE, CREATE SCHEMA/TABLE/VIEW, INSERT, GRANT/REVOKE(관리자)", "미지원 구문은 ‘시뮬레이터 미지원’으로 표시(가짜 성공 없음)", "오류 코드·누락 권한 표시, 실행 이력", "DuckDB 로컬 실행(Spark와 의미가 다를 수 있음)"],
    status: () => [noSess() || S_("Warehouse", ST.warehouse.state, ST.warehouse.state === "RUNNING" ? "ok" : "bad"), ST && S_("실행 신원", ST.principal.split("@")[0]), ST && S_("최근 실행", HIST.sql[0] ? `${HIST.sql[0].s} — ${HIST.sql[0].q.slice(0, 28)}…` : "없음"), ST && S_("gold 재고 뷰", when(ms("view_fixed"), "계약 일치", "계약과 다름(기본)"), when(ms("view_fixed"), "ok", "w"))],
    todo: () => [["Warehouse가 RUNNING인지 확인", ST && ST.warehouse.state === "RUNNING", C("Warehouse 시작", "warehouse", { action: "start" }, "sql")], ["silver 조회 → 권한 오류 확인", ms("sql_perm_denied"), N("SQL 채우기", "sql", { sqlbox: "SELECT * FROM food_dev.silver.orders LIMIT 5" })], ["권한 승인 후 같은 SQL 성공", ms("select_ok_silver"), N("다시 실행", "sql", { sqlbox: "SELECT * FROM food_dev.silver.orders LIMIT 5" })], ["gold 재고 뷰를 계약 산식으로 수정", ms("view_fixed"), N("수정 SQL 채우기", "sql", { sqlbox: "CREATE OR REPLACE VIEW food_dev.gold.v_available_inventory AS\nSELECT product_id, SUM(on_hand_qty - reserved_qty - damaged_qty) AS available_qty\nFROM food_dev.silver.inventory GROUP BY product_id" })]],
    caution: "자기 자신에게 GRANT 하면 금지 이벤트로 기록됩니다. 권한 요청 티켓을 사용하세요."
  },
  nb: {
    t: "UI-06 Notebook", step: ["nb"],
    overview: "셀 단위로 SQL을 실행하며 실행 순서·상태·변수를 관리합니다. 위 셀을 고치면 아래 셀 결과가 ‘오래됨(STALE)’으로 표시됩니다.",
    features: ["SQL 셀 실행 · -- as: 이름 으로 변수 저장", "STALE 표시와 커널 재시작(변수 초기화, 테이블 유지)", "Python 셀은 격리 실행기 미구성으로 차단(흉내 내지 않음)"],
    status: () => [noSess() || S_("셀 수", ST.notebook.cells.length), ST && S_("실행 횟수", ST.notebook.exec_counter), ST && S_("STALE 확인", when(ms("notebook_stale_seen"), "완료", "미확인"), when(ms("notebook_stale_seen"), "ok", "w")), ST && S_("재시작", `${ST.notebook.restarts}회`, when(ms("notebook_restart"), "ok", "w"))],
    todo: () => [["셀 실행 후 위 셀을 수정해 STALE 확인", ms("notebook_stale_seen"), N("Notebook", "nb")], ["커널 재시작", ms("notebook_restart"), C("재시작", "notebook", { action: "restart" }, "nb")]],
    caution: "Warehouse가 꺼져 있으면 셀 실행이 실패합니다."
  },
  comp: {
    t: "UI-07 Compute / SQL Warehouses", step: ["env"],
    overview: "SQL Warehouse의 상태와 접근 권한을 관리합니다. UC 권한이 있어도 Warehouse CAN USE/entitlement가 없으면 실행되지 않습니다.",
    features: ["시작/중지 (시작 후 몇 번의 명령 뒤 RUNNING)", "CAN USE 대상과 내 entitlement 표시", "모의 사용량 지수 (실제 청구액 아님)"],
    status: () => [noSess() || S_("상태", ST.warehouse.state, ST.warehouse.state === "RUNNING" ? "ok" : ST.warehouse.state === "FAILED" ? "bad" : "w"), ST && S_("CAN USE", ST.warehouse.acl.join(", ")), ST && S_("사용량 지수", `${ST.usage_index.sql_runs} SQL`)],
    todo: () => [["Warehouse 시작", ST && ST.warehouse.state === "RUNNING", C("시작", "warehouse", { action: "start" }, "comp")]], caution: "STARTING 상태에서는 SQL이 실패합니다. 다른 명령을 한두 번 실행하면 RUNNING으로 바뀝니다."
  },
  conn: {
    t: "UI-08 Connections / 수집", step: ["conn"],
    overview: "원천 DB(OCI의 Oracle, 합성) 연결 방식을 선택하고 연결 테스트·Foreign catalog 생성을 훈련합니다. 연결 실패의 원인(네트워크/인증/권한/지원 범위)을 구분하는 것이 핵심입니다.",
    features: ["수집 방식: Federation / 배치 / CDC(프로필상 unverified → 성공 모사 안 함)", "연결 테스트: 합성 .invalid 호스트만, 실제 호스트·비밀번호는 저장/접속하지 않음", "장애 진단: 8가지 원인 분류 제출", "Foreign catalog: connection의 CREATE FOREIGN CATALOG + metastore의 CREATE CATALOG 필요(공식 privileges reference 기준, DB 계정 권한과 별개)"],
    status: () => { const c = ST && ST.connections.oracle_food_conn; return [noSess() || S_("수집 방식", c.mode || "미선택", c.mode ? "ok" : "w"), c && S_("연결 상태", c.status, c.status === "OK" ? "ok" : c.status === "FAILED" ? "bad" : "w"), ST && S_("Foreign catalog", Object.keys(ST.foreign_catalogs).join(", ") || "없음")] },
    todo: () => [["Federation 선택", ST && !!ST.connections.oracle_food_conn.mode, C("Federation", "connection", { action: "select_mode", mode: "federation" }, "conn")], ["연결 테스트", ST && ST.connections.oracle_food_conn.status === "OK", C("테스트", "connection", { action: "test" }, "conn")], ["Foreign catalog 생성 시 권한 오류 확인", ms("foreign_perm_denied"), C("생성 시도", "connection", { action: "create_foreign_catalog" }, "conn")], ["권한 2개 요청·승인 후 생성 (CREATE FOREIGN CATALOG → CREATE CATALOG)", ms("foreign_catalog_created"), N("요청서 1 (connection)", "perm", { t_sec: "connection:oracle_food_conn", t_priv: "CREATE FOREIGN CATALOG", t_reason: "foreign catalog 생성 실습 — connection 최소권한" })]],
    caution: "단순 재시도로는 해결되지 않는 장애가 주입될 수 있습니다. 오류 문구로 원인을 분류하세요."
  },
  pipe: {
    t: "UI-09 Pipelines (Spark Declarative Pipelines on Lakeflow)", step: ["pipe"],
    overview: "Bronze→Silver 변환을 선언적 SELECT로 정의하고 Validate/Run 합니다. 품질 규칙(차단·격리·경고)이 적용되며 실패를 성공으로 숨기지 않습니다.",
    features: ["소스 SQL 편집 · run_as 지정", "Validate: 구조·권한 검사 (검증 성공 ≠ 실행 성공)", "Run: 품질 결과표. block≈EXPECT…FAIL UPDATE, warn≈EXPECT, drop≈DROP ROW. quarantine은 공식 내장 기능이 아닌 WIZBASE 패턴(별도 격리 테이블)", "실행 이력과 원천 대비 정합성 대조(303행/격리 4건)"],
    status: () => { const p = ST && ST.pipelines.orders_pipeline; return [noSess() || S_("상태", p.state, p.state === "SUCCEEDED" ? "ok" : p.state === "FAILED" ? "bad" : "w"), p && S_("run_as", p.run_as.split("@")[0]), p && S_("품질 차단 확인", when(ms("pipeline_failed_dq"), "완료", "미실행"), when(ms("pipeline_failed_dq"), "ok", "w")), p && S_("정합성 대조", when(ms("pipeline_recon_ok"), "일치", "미일치/미실행"), when(ms("pipeline_recon_ok"), "ok", "w"))] },
    todo: () => [["Validate", ms("pipeline_validated"), C("Validate", "pipeline", { action: "validate" }, "pipe")], ["Run → 중복키 위반으로 FAILED 확인", ms("pipeline_failed_dq"), C("Run", "pipeline", { action: "run" }, "pipe")], ["소스를 최신 1행만 남기도록 수정 후 재실행", ms("pipeline_ok"), N("수정 SQL", "pipe", { plsql: "SELECT order_id, customer_id, CAST(order_date AS DATE) AS order_date, status, CAST(version AS INTEGER) AS version\nFROM food_dev.bronze.raw_orders\nQUALIFY ROW_NUMBER() OVER (PARTITION BY order_id ORDER BY updated_at DESC) = 1" })]],
    caution: "대상 스키마의 USE SCHEMA/CREATE 권한이 run_as에 없으면 실행이 실패합니다."
  },
  cdc: { t: "UI-09b CDC 이벤트 재생", step: ["cdc"], overview: "변경 로그(중복·역순 도착·삭제·재삽입)에서 최신 상태 테이블을 멱등하게 만들고, 새 배치가 와도 같은 로직으로 재적용되는지 확인합니다. 교육용 재생이며 실제 Lakeflow 커넥터와 별개입니다.", features: ["bronze.cdc_events 조회", "silver.customers_cdc 구축(SQL)", "정합성 검사: 틀린 키만 알려주고 기대 행은 비공개", "다음 배치 도착(중복·seq 누락 포함) 후 재적용"], status: () => [noSess() || S_("1차 정합성", when(ms("cdc_batch1_ok"), "통과", "미통과"), when(ms("cdc_batch1_ok"), "ok", "w")), ST && S_("새 배치", when(ms("cdc_batch2_arrived"), "도착", "대기")), ST && S_("최종 정합성", when(ms("cdc_batch2_ok"), "통과", "미통과"), when(ms("cdc_batch2_ok"), "ok", "w"))], todo: () => [["이벤트를 조회해 중복·역순·삭제 확인", ms("cdc_events_viewed"), C("이벤트 보기", "sql.execute", { sql: "SELECT * FROM food_dev.bronze.cdc_events ORDER BY seq" }, "cdc")], ["최신 상태 테이블 구축 후 1차 검사", ms("cdc_batch1_ok"), N("CDC 화면", "cdc")], ["다음 배치 도착", ms("cdc_batch2_arrived"), C("도착시키기", "cdc.next_batch", {}, "cdc")], ["같은 로직으로 재적용 후 최종 검사", ms("cdc_batch2_ok"), N("CDC 화면", "cdc")]], caution: "도착 순서가 아니라 seq 기준입니다. 같은 event_id는 한 번만 적용합니다." },
  jobs: {
    t: "UI-10 Jobs", step: ["job"],
    overview: "task 의존 관계(DAG)와 실행 신원(run-as)으로 Job을 실행합니다. 편집자의 조회 성공과 실행자의 실패가 다를 수 있음을 훈련합니다.",
    features: ["task SQL 편집·의존성", "run-as 변경, 재시도·스케줄 설정", "편집자 vs run-as 비교", "선행 실패 시 후속 task 건너뜀(UPSTREAM_FAILED)"],
    status: () => { const j = ST && ST.jobs.orders_job; return [noSess() || S_("run-as", j.run_as.split("@")[0], j.run_as === "svc-runner" ? "w" : ""), j && S_("실행 이력", `${j.runs.length}회`), j && S_("run-as 실패 확인", when(ms("job_runas_fail"), "완료", "미확인"), when(ms("job_runas_fail"), "ok", "w")), j && S_("성공 실행", when(ms("job_ok"), "있음", "없음"), when(ms("job_ok"), "ok", "w"))] },
    todo: () => [["파이프라인이 먼저 성공해 대상 테이블이 있는지 확인", ms("pipeline_ok"), N("Pipelines", "pipe")], ["run-as=svc-runner로 실행 → 권한 실패 확인", ms("job_runas_fail"), C("실행", "job", { action: "run" }, "jobs")], ["run-as를 나로 바꿔 재실행 성공", ms("job_ok"), C("run-as 변경", "job", { action: "set_run_as", run_as: "trainee@wizbase.training" }, "jobs")]],
    caution: "대상 테이블이 없으면 권한이 아니라 ‘테이블 없음’ 오류가 납니다. 오류 코드를 구분하세요."
  },
  genie: {
    t: "UI-11 의미모델 · Genie", step: ["genie"],
    overview: "온톨로지가 어느 계층(UC 메타데이터·Genie 설정·정책 엔진)에 반영되는지 확인하고, 자연어 질의의 생성 SQL·결과·접근 통제를 검수합니다.",
    features: ["온톨로지→반영 위치 매핑(자동 적용 버튼 없음)", "Genie 데이터셋 등록", "결정적 질의 템플릿 + 로컬 SQL 결과", "다른 사용자(analyst-b)로 질의해 누출 차단 확인"],
    status: () => [noSess() || S_("등록 데이터셋", ST.genie.datasets.length), ST && S_("재고 뷰 등록", when(ST.genie.datasets.some(d => d.endsWith("v_available_inventory")), "예", "아니오"), when(ST.genie.datasets.some(d => d.endsWith("v_available_inventory")), "ok", "w")), ST && S_("질의 성공", when(ms("genie_ok"), "있음", "없음"), when(ms("genie_ok"), "ok", "w")), ST && S_("누출 차단 확인", when(ms("genie_leak_blocked"), "완료", "미확인"), when(ms("genie_leak_blocked"), "ok", "w"))],
    todo: () => [["재고 뷰를 데이터셋에 등록", ST && ST.genie.datasets.some(d => d.endsWith("v_available_inventory")), C("등록", "genie.config", { datasets: ["food_dev.gold.v_order_overview", "food_dev.gold.v_available_inventory"] }, "genie")], ["질문하고 생성 SQL 확인", ms("genie_ok"), C("총 주문 박스", "genie.ask", { question: "총 주문 박스는?" }, "genie")], ["analyst-b로 재고 질의 → 차단", ms("genie_leak_blocked"), C("analyst-b 질의", "genie.ask", { question: (ST ? ST.case.product : "") + " 가용재고는?", as_persona: "analyst-b@wizbase.training" }, "genie")]],
    caution: "실제 Genie의 모델 품질·추론을 재현하지 않으며 템플릿 밖 질문은 ‘범위 밖’입니다."
  },
  agent: {
    t: "UI-12 Agent · 승인", step: ["order", "safety"],
    overview: "주문 변경을 조회 → 정책 → 제안 → 승인 → 가상 API 실행 → 사후 대조로 처리합니다. 서버가 승인·payload·버전·재고를 검증합니다.",
    features: ["사실 조회와 추가 부족량 계산", "정책 평가: 금지/이관/승인 필요, 대안 제시", "승인(리뷰어) · payload hash · 만료 30분", "가상 AX API: 멱등키·expected_version, 변조 시험", "정책 편집→테스트→통과 시 활성화"],
    status: () => [noSess() || S_("정책 버전", `v${ST.policy.active}`), ST && S_("제안", Object.keys(ST.proposals).length), ST && S_("승인", Object.keys(ST.approvals).length), ST && S_("가상 API 실행", when(ms("ax_executed"), "완료", "미실행"), when(ms("ax_executed"), "ok", "w")), ST && S_("gold 재고 뷰", when(ms("view_fixed"), "계약 일치", "계약과 다름 → 부족량이 틀림"), when(ms("view_fixed"), "ok", "bad"))],
    todo: () => [["먼저 gold 재고 뷰를 계약대로 수정", ms("view_fixed"), N("SQL Editor", "sql")], ["정책 평가·제안 생성 (추가 부족 3)", ms("proposal_made"), C("제안 생성", "order.propose", { order_id: ST ? ST.case.order : "", requested_total: ST ? ST.case.requested : 0 }, "agent")], ["리뷰어 승인 (다른 로그인)", ms("approved"), N("승인 영역", "agent")], ["가상 API 실행", ms("ax_executed"), N("실행 영역", "agent")], ["무승인·변조·멱등 시험", ms("tamper_blocked") && ms("ax_no_approval_blocked") && ms("idem_replayed"), N("시험하기", "agent")]],
    caution: "승인은 요청자와 다른 리뷰어/강사가 합니다. 승인 후 재고·버전이 바뀌면 재검증 실패 → 새 제안·재승인이 필요합니다."
  },
  trace: {
    t: "UI-13 Tracing / 평가", step: ["eval"],
    overview: "사용자 요청·SQL·정책·승인·API를 trace ID로 연결해 보고, 평가셋 40건으로 정책 결정과 데이터 결과를 채점합니다.",
    features: ["평가셋 40건(정상·마감·재고·단위·반품·복합 등) 실행", "정책 버전별 결과 비교", "trace 타임라인", "가상 사용량 지수(실제 청구액 아님)"],
    status: () => [noSess() || S_("평가 실행", `${ST.eval_runs.length}회`, ST.eval_runs.length ? "ok" : "w"), ST && ST.eval_runs.length && S_("최근 결과", `${ST.eval_runs.slice(-1)[0].passed}/${ST.eval_runs.slice(-1)[0].total}`)],
    todo: () => [["평가셋 실행", ms("eval_run"), C("실행", "eval.run", {}, "trace")]], caution: "문장 유사도만으로 통과시키지 않습니다. 정책 결정·데이터 결과로 채점합니다."
  },
  bundle: {
    t: "UI-14 Git / Bundle / CLI", step: ["bundle", "iso"],
    overview: "가상 터미널로 CLI·Bundle·Git 흐름을 훈련합니다. validate·deploy·run이 서로 다른 사건이며, 미배포 수정은 이전 배포본이 실행됨을 확인합니다.",
    features: ["databricks auth login / bundle validate·deploy·run·summary / catalogs·tables", "git status·diff·commit·log (내부 가상 저장소)", "파일 편집과 로컬/배포 해시 비교(drift)", "실제 호스트·자격증명 옵션은 차단·미저장"],
    status: () => { const b = ST && ST.bundle; return [noSess() || S_("CLI 로그인", b.cli_logged_in ? "예(가상)" : "아니오", b.cli_logged_in ? "ok" : "w"), b && S_("배포", b.deployed_hash ? b.deployed_hash.slice(0, 10) : "없음", b.deployed_hash ? "ok" : "w"), b && S_("drift", b.drift ? "로컬≠배포" : "없음", b.drift ? "bad" : ""), b && S_("배포 검수", b.deploy_review || "-", b.deploy_review === "PASS" ? "ok" : "w")] },
    todo: () => [["가상 로그인 → validate", ms("bundle_validate"), N("터미널", "bundle", { clibox: "databricks auth login --host https://training-workspace.invalid" })], ["deploy", ms("bundle_deploy"), N("터미널", "bundle", { clibox: "databricks bundle deploy -t dev" })], ["run (배포본 실행)", ms("bundle_run"), N("터미널", "bundle", { clibox: "databricks bundle run -t dev training_job" })], ["파일 수정 후 미배포 run → drift", ms("drift_seen"), N("파일 편집", "bundle")], ["실제 호스트 로그인 시도 → 차단", ms("external_url_blocked"), N("터미널", "bundle", { clibox: "databricks auth login --host https://example.cloud.databricks.com" })]],
    caution: "파이프·명령 치환·임의 shell은 지원하지 않는 명령 파서입니다. bundle run 전에 파이프라인 대상 테이블이 있어야 성공합니다."
  },
  perm: {
    t: "UI-15 권한 · 관리", step: ["perm"],
    overview: "principal·그룹·entitlement·UC 권한·소유자를 조회하고, 권한 요청 티켓을 제출/처리합니다. 로그인 성공과 권한은 별개입니다.",
    features: ["Principal·Grant 표", "권한 요청서(최소권한·사유 필수, ALL PRIVILEGES는 반려)", "관리자/강사가 티켓 승인·반려", "다른 브라우저 탭에서 관리자로 로그인해 처리하는 협업 모델"],
    status: () => [noSess() || S_("열린 티켓", ST.tickets.filter(t => t.status === "OPEN").length, ST.tickets.some(t => t.status === "OPEN") ? "w" : ""), ST && S_("승인된 티켓", ST.tickets.filter(t => t.status === "APPROVED").length), ST && S_("내 역할", ME.role)],
    todo: () => [["오류에 나온 누락 권한으로 티켓 제출", ms("ticket_created"), N("요청서(자동 입력)", "perm", { t_sec: "schema:food_dev.silver", t_priv: "USE SCHEMA", t_reason: "silver 조회 업무 — USE SCHEMA 최소권한 요청" })], ["관리자가 승인", ms("ticket_resolved"), N("티켓 보기", "perm")]],
    caution: "전체 관리자 권한을 달라고 요청하면 반려되고 평가에 기록됩니다."
  },
  inst: {
    t: "UI-16 강사 · 수료", step: ["wrap"],
    overview: "강사가 장애를 주입하고 진행을 관찰하며 평가·수료를 판정하는 화면입니다(학습자는 내 점수만 열람).",
    features: ["장애 주입/해제, 일시정지, 체크포인트·복원, 초기화(증거 보존)", "결정적 재생 검증", "설명 점수 입력 → 수료 판정(80점+필수 통과 항목)"],
    status: () => [S_("내 역할", ME ? ME.role : "-"), ST && S_("대리 처리", `${ST.session.admin_assisted}회`), ST && S_("활성 장애", (ST.faults || []).join(", ") || "없음")],
    todo: () => [["버전 충돌 등 장애 주입으로 재승인 시험", ms("version_conflict_seen"), N("장애 주입", "inst")], ["설명·인수 평가 점수 입력", ST && ST.score_explain_done, N("평가", "inst")]],
    caution: "강사 대리 처리는 독립 수행 점수와 구분되어 표시됩니다."
  },
  evid: {
    t: "증거 보고서", step: ["wrap"],
    overview: "세션의 모드·프로필·시드·데이터 digest·SQL 코드 해시·승인·가상 API 결과·한계를 하나로 묶은 보고서입니다. 고객·SA 설명의 근거가 됩니다.",
    features: ["검증 수준 구분: SIMULATED / LOCAL_EXECUTED (DBX_VERIFIED 없음)", "점수·필수 통과 항목", "타임라인과 SQL 증거(코드 해시)", "제한 사항 명시"],
    status: () => [noSess() || S_("이벤트", "타임라인 참조"), ST && S_("진행", GUIDE ? `${GUIDE.percent}%` : "-")],
    todo: () => [["보고서를 검토하고 ‘검토했습니다’ 기록", ms("ack_wrap"), C("검토 완료", "guide.ack", { key: "wrap" }, "evid")]],
    caution: "모의에서 확인한 것과 실제 DBX에서 확인해야 할 것을 구분해 설명하세요."
  },
  track: { t: "프로젝트 트랙 (8주 모듈)", step: [], overview: "전체 여정을 요구·접근·수집/모델·운영·의미·승인형 에이전트·평가·배포/인수의 8개 훈련 모듈로 묶어 진행을 보여줍니다. 실제 고객 일정이 아니라 훈련 모듈 구분입니다.", features: ["모듈별 진행률(세션의 실제 사건으로 계산)", "모듈에 속한 단계와 상태"], status: () => [noSess() || S_("전체 진행", GUIDE ? GUIDE.percent + "%" : "-")], todo: () => [["현재 단계로 이동", false, N("단계 보기", "env")]], caution: "주차는 일정 약속이 아닙니다." },
  demo: { t: "고객 시연 20분", step: ["wrap"], overview: "20분 표준 시연의 6개 구간 준비 상태와 예상 질문 6개의 답안을 보여줍니다. 답안은 이 세션의 실제 증거로 만들어집니다.", features: ["구간별 준비 여부와 부족한 증거", "예상 질문: 권한·run-as·연결 선택·검증/배포·승인 후 변경·실제와의 차이", "증거 이벤트 ID 연결"], status: () => [noSess() || S_("세션", ST.session.id)], todo: () => [["부족한 증거가 있는 구간의 화면에서 먼저 재현", false, N("현재 단계", "env")]], caution: "재현하지 않은 항목은 ‘아직 재현하지 않음’으로 표시되며 숙련된 인상을 만들지 않습니다." },
  vmx: { t: "UI-26 현장 대조표 (V1~V6)", step: [], overview: "실제 워크스페이스와의 대조 결과를 14개 필수 열로 기록하고, 문서 확인 만료(35일)·미검증 기능·일치율을 관리합니다.", features: ["기능 매니페스트와 STALE 판정", "대조 행 기록(리뷰어/강사)", "일치율은 대조한 행만 분모, 미검증은 별도 표시", "V1~V6 절차 안내"], status: () => [S_("접근", staff() && ME.role !== "admin" ? "기록 가능" : "열람만", staff() ? "ok" : "w")], todo: () => [["미검증 기능을 실제 워크스페이스에서 대조", false, N("대조표", "vmx")]], caution: "접근하지 못한 클라우드·리전의 일치도는 보고하지 않습니다." },
  prof: { t: "UI-17 역량 · 등급 프로필", step: [], overview: "내부 등급(WZ-L0~L5)·공식 자격·응시준비·실제 실습·투입 승인을 서로 다른 필드로 보여줍니다.", features: ["objective 차원별 숙련도(지식/실기/복구/설명)", "응시준비 판정(보수적 내부 기준)과 미충족 사유", "공식 자격 자기 신고(확인대기)"], status: () => [S_("내 역할", ME ? ME.role : "-")], todo: () => [["응시준비 판정으로 미충족 기준 확인", false, N("프로필", "prof")]], caution: "내부 점수는 공식 자격·합격과 무관합니다." },
  plan: { t: "UI-18 목표 · 학습계획", step: [], overview: "사전 진단 점수로 약한 영역부터 배정되는 개인 학습 경로를 만듭니다.", features: ["시험 트랙 선택(DE-A/DE-P/GEN-A)", "영역별 진단 입력", "개념→연습→실제 실습→평가→보완→지연확인 사이클"], status: () => [S_("계획", LAST.plan ? "생성됨" : "없음", LAST.plan ? "ok" : "w")], todo: () => [["진단 점수 입력 후 계획 생성", !!LAST.plan, N("학습계획", "plan")]], caution: "시간 이수만으로 승급하지 않습니다." },
  map: { t: "UI-19 공식 목표 지도", step: [], overview: "시험 프로필별 영역·가이드 버전·objective 커버리지와 출시 게이트를 보여줍니다.", features: ["영역 비중·내부 모의 문항 배분", "coverage 상태 MISSING→VALIDATED", "차단 사유(bullet 미적재, 상충 미해소)"], status: () => [S_("현재 보기", LAST.cov || "DE-A")], todo: () => [["차단 사유 확인", false, N("목표 지도", "map")]], caution: "현재는 도메인 단위 자리표시이며 공식 bullet 전수 적재는 미수행입니다." },
  tutor: { t: "UI-20 AI 튜터", step: [], overview: "승인된 공식 문서·검토 콘텐츠만 근거로 답하고 점진 힌트를 제공합니다. 근거가 없으면 ‘확인 필요’ 이슈를 만듭니다.", features: ["근거 URL·기준일 표시", "힌트 1~5단계", "봉인 시험 중 차단"], status: () => [S_("마지막 응답", LAST.tutor ? LAST.tutor.status : "없음")], todo: () => [["개념 질문하기", !!LAST.tutor, N("튜터", "tutor")]], caution: "튜터는 실행 권한이 없습니다." },
  exam: { t: "UI-21 시험센터", step: [], overview: "연습/봉인 모의시험을 서버 타이머로 진행합니다. 프로필·언어·시간이 시작 시 고정됩니다.", features: ["단일/복수 선택, 자동 저장, 제출 후 수정 불가", "봉인 시험은 제출 전 정답·설명 비공개", "문항 family 재노출 제외"], status: () => [S_("진행 중 응시", LAST.att ? LAST.att.status : "없음")], todo: () => [["연습 모의시험 시작", !!LAST.att, N("시험센터", "exam")]], caution: "현재 문항은 AI 초안(DRAFT)이라 봉인 시험은 구성되지 않습니다." },
  lab: { t: "UI-22 실제 실습 증거함", step: [], overview: "실제 교육용 Databricks에서 실습을 수행하고 증거를 제출하는 화면입니다. 내 PC의 adapter가 내 워크스페이스에서 실행하고, 결과 체크섬만 제출하면 서버가 자동 대조하며 검토자가 원본을 확인합니다.", features: ["실습 카탈로그: 자동 대조(SQL) · CLI 증거 · 수동 실습", "팩 내려받기 → 내 PC에서 adapter 실행 → evidence JSON 제출", "자동 대조: 결과 체크섬·pack 버전·statement ID·재사용 여부", "검토자가 Query History 원본 확인 후 승인", "미작성 실습은 ‘미작성’으로 표시되고 준비 판정을 차단"], status: () => [S_("내 역할", ME ? ME.role : "-"), S_("자격증명", "서버가 받지 않음", "ok")], todo: () => [["실습 팩 내려받기", false, N("증거함", "lab")], ["내 PC에서 adapter 실행 후 evidence 제출", false, N("제출 영역", "lab")]], caution: "adapter는 현재 가짜 Statement API로만 검증되었습니다. 실제 워크스페이스 첫 실행은 검토자와 함께 확인하세요. 고객 운영 데이터·catalog는 사용 금지." },
  qual: { t: "UI-23 콘텐츠 품질관리", step: [], overview: "문항 검수 단계·통계·회수·영향 재계산을 관리합니다(리뷰어/강사).", features: ["DRAFT→…→ACTIVE→RETIRED 상태기계", "기술·출제 검토자 분리", "표본 부족 경고"], status: () => [S_("접근", staff() && ME.role !== "admin" ? "가능" : "리뷰어/강사 전용", staff() && ME.role !== "admin" ? "ok" : "w")], todo: () => [["문항 검수 진행", false, N("품질관리", "qual")]], caution: "AI 초안 문항은 인간 검수 전에는 평가에 사용되지 않습니다." },
  partner: { t: "UI-24 전문인력 · 파트너 운영", step: [], overview: "인력별 내부 등급·공식 credential·승인 실습을 집계합니다. 회사 파트너 tier는 가정하지 않습니다.", features: ["인력 현황표", "회사 프로그램 값은 ‘미확인’ 표기", "공식 KB 링크"], status: () => [S_("접근", staff() && ME.role !== "admin" ? "가능" : "리뷰어/강사 전용")], todo: () => [["현황 확인", false, N("파트너", "partner")]], caution: "인증 인원만으로 tier 충족을 계산하지 않습니다." },
  conf: { t: "UI-25 공식 자료 충돌 검토", step: [], overview: "웹/PDF/한국어 공식 자료의 차이를 기록하고 검토자가 근거와 함께 해소합니다.", features: ["상충 6건과 처리 방침", "해소 시 근거 URL 필수", "미해결 시 응시준비 판정 보류"], status: () => [S_("역할", ME ? ME.role : "-")], todo: () => [["상충 항목 검토", false, N("자료 충돌", "conf")]], caution: "특정 PDF가 항상 웹보다 우선한다는 규칙은 없습니다." }
};

function helpFlow(view) {
  const f = FLOW_CORE.includes(view) ? FLOW_CORE : FLOW_PRO.includes(view) ? FLOW_PRO : null; if (!f) return [null, null];
  const i = f.indexOf(view); return [i > 0 ? f[i - 1] : null, i < f.length - 1 ? f[i + 1] : null];
}
function helpHtml() {
  const h = HELP[VIEW] || HELP.env;
  const [prev, next] = helpFlow(VIEW);
  const st = (h.status() || []).filter(Boolean);
  const todo = h.todo();
  const first = todo.findIndex(x => !x[1]);
  const steps = (h.step || []).map(id => GUIDE && GUIDE.steps.find(s => s.id === id)).filter(Boolean);
  const tone = t => t === "ok" ? "ok" : t === "bad" ? "bad" : t === "w" ? "w" : "";
  const nm = v => (NAV.flatMap(g => g[1]).find(n => n[0] === v) || [v, v])[1];
  return `<div class="aih"><div class="aiti">${ICON.help}<div><b>도움말</b><small>${esc(h.t)}</small></div></div><button class="ghost ic" data-a="aitoggle" aria-label="닫기">${ICON.close}</button></div>
  <div class="aibody help">
    <section><h4>이 화면은?</h4><p>${esc(h.overview)}</p></section>
    <section><h4>주요 기능</h4><ul class="feat">${h.features.map(f => `<li>${esc(f)}</li>`).join("")}</ul></section>
    <section><h4>현재 상태</h4><div class="kv">${st.map(x => `<div><span>${esc(x[0])}</span><b class="${tone(x[2])}">${esc(x[1])}</b></div>`).join("") || '<div class="mute">표시할 상태가 없습니다.</div>'}</div></section>
    <section><h4>지금 할 일</h4><div class="todo">${todo.map((x, i) => `<div class="ti ${x[1] ? "d" : i === first ? "cur" : ""}"><span class="cb">${x[1] ? ICON.check : i + 1}</span><div><span>${esc(x[0])}</span>${x[1] || !x[2] ? "" : scBtn(x[2], i === first)}</div></div>`).join("")}</div>
      ${first === -1 ? '<div class="note ok">이 화면의 항목을 모두 마쳤습니다. 아래 ‘다음 화면’으로 이동하세요.</div>' : ""}</section>
    ${steps.length ? `<section><h4>연관 진행 단계</h4>${steps.map(s => `<div class="rel ${s.status}"><b>${s.no}단계 · ${esc(s.title)}</b><small>${s.done}/${s.total} 항목 · ${s.status === "done" ? "완료" : s.status === "current" ? "진행 중" : "대기"}</small></div>`).join("")}</section>` : ""}
    <section><h4>이전 · 다음</h4><div class="pn"><button class="sec" ${prev ? `data-a="nav" data-v="${prev}"` : "disabled"}><small>이전 화면</small>${prev ? esc(nm(prev)) : "—"}</button><button class="sec" ${next ? `data-a="nav" data-v="${next}"` : "disabled"}><small>다음 화면</small>${next ? esc(nm(next)) : "—"}</button></div>
      ${GUIDE && GUIDE.next ? `<div class="sub" style="margin-top:8px">전체 절차상 현재 위치: <b>${GUIDE.next.step_no}단계 ${esc(GUIDE.next.title)}</b></div>` : ""}</section>
    <section><div class="note w">${esc(h.caution)}</div></section>
  </div>`;
}
