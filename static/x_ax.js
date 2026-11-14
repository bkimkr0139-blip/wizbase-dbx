"use strict";
/* x_ax.js: AX 프로젝트 스튜디오(AX-01~12 중 1차 범위). 합성 fixture 기준 — 실제 레거시 DB·DBX 배포는 미검증이라는 점을 화면에 항상 표시한다. */
let AX = { pid: "", tab: "proj", res: null, erdFocus: "sales_orders", hops: 1, snap: "", rel: "", plan: "", qt: "order_increase", ask: { tenant_id: "T1", order_id: "SO-1001", new_qty: "35", customer_id: "C1", product_id: "PRD1", needed_qty: "150", current_supplier_id: "S1", supplier_id: "S1", po_id: "PO-2", as_of: "" }, prop: null, key: "", sq: "반품은 며칠 이내에 접수하나요", smode: "hybrid", sres: null };
const QT = { order_increase: ["tenant_id", "order_id", "new_qty"], delay_alternatives: ["tenant_id", "order_id", "new_qty", "as_of"], price_diff_reason: ["tenant_id", "order_id"], receivable_summary: ["tenant_id", "customer_id", "as_of"], purchase_reorder: ["tenant_id", "product_id", "needed_qty", "as_of"], supplier_switch: ["tenant_id", "product_id", "current_supplier_id", "needed_qty"], price_spike: ["tenant_id", "supplier_id", "product_id", "as_of"], receipt_variance: ["tenant_id", "po_id"] };
const QT_KO = { order_increase: "주문 증량 가능?", delay_alternatives: "납기 지연 대안", price_diff_reason: "단가가 다른 이유", receivable_summary: "미수금·반품", purchase_reorder: "부족품목 추가 발주", supplier_switch: "공급처 변경", price_spike: "매입단가 급등", receipt_variance: "입고 차이·클레임" };
const AXP = "/api/ax/projects";
const axTabs = [["proj", "AX-01 프로젝트·권한"], ["conn", "AX-02/03 연결·인벤토리"], ["erd", "AX-04/05 ERD·관계 검토"], ["onto", "AX-06 온톨로지"], ["agent", "AX-08/09 파이프라인·에이전트"], ["biz", "승인·업무 명령"], ["auto", "자동 구축"], ["search", "AX-07 문서·검색"], ["sig", "신호 inbox"], ["ev", "AX-11/12 평가·배포"]];
const axTry = async f => { try { return await f() } catch (e) { AX.res = { error: e.data || { message: e.message } }; toast(e.message); render(true) } };

Object.assign(V, {
  async ax() {
    const L = await api("/api/ax/projects"); if (!AX.pid && L.length) AX.pid = L[0].project_id; if (AX.pid && !L.some(p => p.project_id === AX.pid)) AX.pid = L[0]?.project_id || "";
    const p = L.find(x => x.project_id === AX.pid);
    const tabs = `<div class="row">${axTabs.map(([k, l]) => `<button class="${AX.tab === k ? "" : "ghost"}" data-a="axtab" data-t="${k}">${esc(l)}</button>`).join("")}</div>`;
    const warn = `<div class="card" style="border-left:4px solid #d97706"><b>검증 범위</b> 합성 fixture(SQLite)와 Docker 시험 DB(PostgreSQL 16·MySQL 8.4·Oracle 26ai Free)에서 실제 실행한 결과입니다. 고객 개발 DB, DBX 실제 배포, 실제 LLM·신경망 임베딩, 부하 시험은 아직 하지 않았습니다(증거 수준 NATIVE_FIXTURE). 에이전트는 LLM 없이 결정적 도구로 답하고, 검색 임베딩은 비신경망 해시입니다.</div>`;
    const sel = `<div class="vfilters"><label>프로젝트 <select onchange="AX.pid=this.value;AX.snap='';AX.rel='';render(true)">${L.map(x => `<option value="${esc(x.project_id)}" ${x.project_id === AX.pid ? "selected" : ""}>${esc(x.name)} · ${esc(x.mode)}/${esc(x.engine)}</option>`).join("")}</select></label></div>`;
    let body = "";
    try { body = L.length || AX.tab === "proj" ? await AXV[AX.tab](p, L) : `<div class="mute">먼저 프로젝트를 만드세요.</div>`; } catch (e) { body = `<div class="card">${esc(e.message)}</div>` }
    const res = AX.res ? `<div class="card"><b>마지막 응답</b><pre style="white-space:pre-wrap;max-height:260px;overflow:auto">${esc(JSON.stringify(AX.res, null, 2))}</pre></div>` : "";
    return `<h2>AX 프로젝트 스튜디오</h2><div class="sub">레거시 DB 구조 수집 → ERD·관계 검토 → 온톨로지 승인 → 도구·에이전트 → 승인형 업무 명령 → 평가·배포. 거래 정본은 레거시 DB이며 온톨로지·인덱스는 파생 자산입니다.</div>${warn}${L.length ? sel : ""}${tabs}${body}${res}`;
  }
});

const axPost = (path, body) => api(`${AXP}/${AX.pid}${path}`, { body: body || {} });
const axGet = path => api(`${AXP}/${AX.pid}${path}`);
const AXV = {
  async proj(p, L) {
    return `<div class="card"><b>새 프로젝트</b><div class="vfilters"><label>이름 <input id="axname" placeholder="예: 유통 AX 시험" style="width:200px"></label><label>엔진 <select id="axeng"><option value="native">native(WIZBASE)</option><option value="databricks">databricks(컴파일만)</option></select></label><button data-a="axnew">만들기</button></div>
      <div class="sub">모드는 DEMO_SYNTHETIC(합성 fixture)로 시작합니다. RELEASE_CANDIDATE는 직접 만들 수 없습니다. 이름에 dev가 있다고 비운영으로 신뢰하지 않으며 DBA 확인값을 기록합니다.</div></div>
      ${table(["프로젝트", "모드", "엔진", "소유자", "구성원(역할)"], L.map(x => [x.name, x.mode, x.engine, x.owner, Object.entries(x.members).map(([u, m]) => `${u}:${m.role}${m.tenants ? "[" + m.tenants.join(",") + "]" : ""}`).join(" · ")]), true)}
      ${p ? `<div class="card"><b>구성원 추가</b> <span class="mute">(architect만)</span><div class="vfilters"><label>user_id <input id="axmu" style="width:170px"></label><label>역할 <select id="axmr">${["architect", "domain_expert", "developer", "reviewer", "business_user"].map(r => `<option>${r}</option>`).join("")}</select></label><label>tenant 범위 <input id="axmt" placeholder="T1,T2 (비우면 내부 전체)" style="width:150px"></label><label>거래처 범위 <input id="axmc" placeholder="C1 (외부 거래처)" style="width:110px"></label><button data-a="axmember">저장</button></div></div>` : ""}`;
  },
  async conn(p) {
    const cs = await axGet("/connections"), sn = await axGet("/snapshots"); const cur = sn[0];
    const inv = cur ? await axGet(`/inventory?snapshot_id=${cur.snapshot_id}`) : null;
    return `<div class="card"><b>연결</b>${table(["id", "엔진", "용도", "마지막 테스트", "비고"], cs.map(c => [c.connector_id, c.engine, c.purpose, c.last_test ? (c.last_test.all_pass ? badge("통과", "ok") : badge("일부 실패/미실행", "bad")) : "-", `<a href="#" data-a="axtest" data-c="${esc(c.connector_id)}">단계별 테스트</a> · <a href="#" data-a="axscan" data-c="${esc(c.connector_id)}">구조 수집</a>`]), true)}
      <div class="row"><button data-a="axconnfix">합성 fixture 연결 추가</button></div>
      <div class="sub">DNS → TCP → TLS → 인증 → DB 식별 → 메타데이터 가시성 → 한정 조회를 따로 보여줍니다. 비밀번호·토큰은 받지 않고 <code>secret://</code> 참조만 등록합니다. 이 빌드는 Oracle/PostgreSQL/MySQL 실제 구조 수집을 실행하지 않습니다(지원표: 딕셔너리 SQL만 준비).</div></div>
      ${cur ? `<div class="card"><b>DB 인벤토리</b> <span class="mute">${esc(cur.snapshot_id)} · 객체 ${cur.objects}개(테이블 ${cur.tables}, 뷰 ${cur.views})</span><div class="sub">전체성: <b>${esc(cur.coverage.completeness)}</b> ${esc(cur.coverage.warning || "")}</div>
      ${table(["객체", "종류", "컬럼", "PK", "FK", "행(추정)", "fingerprint"], inv.objects.map(o => [o.object_id, o.kind, o.columns, o.pk.join(","), o.fks, o.rows_est ?? "-", o.fingerprint]), true)}
      <div class="row"><button class="ghost" data-a="axprofile">표본 profile(party)</button></div></div>` : `<div class="mute">아직 수집된 snapshot이 없습니다. 연결을 추가하고 구조 수집을 실행하세요.</div>`}`;
  },
  async erd(p) {
    const g = await axGet(`/erd/subgraphs?focus=${encodeURIComponent(AX.erdFocus)}&hops=${AX.hops}`);
    const n = g.nodes.length, W = 190, H = 110, per = 3; const pos = {}; g.nodes.forEach((x, i) => pos[x.id] = [20 + (i % per) * (W + 60), 20 + Math.floor(i / per) * (H + 40)]);
    const svgH = 40 + Math.ceil(n / per) * (H + 40);
    const edges = g.edges.map(e => { const a = pos[e.from], b = pos[e.to]; if (!a || !b) return ""; const col = e.kind === "INFERRED" ? "#d97706" : "#334155"; return `<line x1="${a[0] + W / 2}" y1="${a[1] + H / 2}" x2="${b[0] + W / 2}" y2="${b[1] + H / 2}" stroke="${col}" stroke-width="${e.kind === "APPROVED_LOGICAL" ? 3 : 1.5}" ${e.style === "dashed" ? 'stroke-dasharray="6 4"' : ""}><title>${esc(e.from_columns.join(",") + " → " + e.to_table + " (" + e.kind + ")")}</title></line>` }).join("");
    const nodes = g.nodes.map(x => { const [px, py] = pos[x.id]; return `<g><rect x="${px}" y="${py}" width="${W}" height="${H}" rx="6" fill="#f8fafc" stroke="#64748b"/><text x="${px + 8}" y="${py + 16}" font-size="12" font-weight="700">${esc(x.id.replace("main.", ""))}${x.kind === "view" ? " (view)" : ""}</text>${x.columns.slice(0, 6).map((c, i) => `<text x="${px + 8}" y="${py + 32 + i * 13}" font-size="10">${c.pk ? "🔑" : c.fk ? "↗" : "·"} ${esc(c.name)} <tspan fill="#64748b">${esc(c.type)}</tspan></text>`).join("")}${x.columns.length > 6 ? `<text x="${px + 8}" y="${py + H - 4}" font-size="10" fill="#64748b">… 컬럼 ${x.column_count}개</text>` : ""}</g>` }).join("");
    const rels = await axGet("/relations"); const cand = rels.logical;
    return `<div class="card"><b>통합 ERD(부분모델)</b> <span class="mute">전체 ${g.total_tables}개 중 ${n}개</span><div class="vfilters"><label>중심 테이블 <input id="axfocus" value="${esc(AX.erdFocus)}" style="width:150px"></label><label>hop <select id="axhops">${[0, 1, 2, 3].map(h => `<option ${h === AX.hops ? "selected" : ""}>${h}</option>`).join("")}</select></label><button data-a="axerd">보기</button></div>
      <div class="tw"><svg width="${Math.max(760, per * (W + 60))}" height="${svgH}" role="img" aria-label="ERD">${edges}${nodes}</svg></div>
      <div class="sub">표기: 실선=선언 FK, 굵은 선=승인된 논리 관계, <b>점선(주황)=추론 후보 — 검토 전 사용 금지</b>. 🔑 PK, ↗ FK. ERD 화면에서 레거시 DDL을 실행하지 않습니다.</div></div>
      <div class="card"><b>관계 후보 검토</b> <button data-a="axinfer">후보 추론(표본)</button>
      ${table(["관계", "포함률(표본)", "heuristic 점수", "상태", "결정"], cand.map(r => [`${r.from_table}(${r.from_columns.join(",")}) → ${r.to_table}`, r.evidence ? r.evidence.inclusion_rate : "-", r.heuristic_score ?? "-", r.status, r.status === "CANDIDATE" ? `<input id="axrn_${r.relation_id}" placeholder="사유(4자+)" style="width:130px"> <a href="#" data-a="axrel" data-r="${esc(r.relation_id)}" data-d="approve">승인</a> · <a href="#" data-a="axrel" data-r="${esc(r.relation_id)}" data-d="reject">반려</a>` : (r.reviews || []).slice(-1).map(x => esc(x.note)).join("")]), true)}
      <div class="sub">점수는 초기 heuristic이며 검증된 확률이 아닙니다. 이름이 같거나 JOIN이 된다는 이유로 승인하지 않습니다. 승인은 domain_expert/reviewer만 가능합니다.</div></div>`;
  },
  async onto(p) {
    const rs = await axGet("/ontology-releases");
    return `<div class="card"><b>온톨로지 release</b> <button data-a="axrelcreate">distribution_ax 템플릿으로 초안 만들기</button>
      ${table(["release", "버전", "상태", "작성자", "엔터티/관계", "검증", "처리"], rs.map(r => [r.release_id, r.version, badge(r.status, r.status === "APPROVED" || r.status === "ACTIVE" ? "ok" : r.status === "STALE" ? "bad" : ""), r.author, `${r.entities}/${r.relations}`, r.validation ? (r.validation.ok ? badge("통과", "ok") : badge(`오류 ${r.validation.errors.length}`, "bad")) : "-",
        `<a href="#" data-a="axrelval" data-r="${esc(r.release_id)}">검증</a> · <input id="axnote_${r.release_id}" placeholder="결정 사유" style="width:120px"> <a href="#" data-a="axrelrev" data-r="${esc(r.release_id)}" data-d="approve">승인</a> · <a href="#" data-a="axrelrev" data-r="${esc(r.release_id)}" data-d="reject">반려</a>`]), true)}
      <div class="sub">검증기는 내부 shape 검사이며 <b>SHACL 준수가 아닙니다</b>. 선언 FK 또는 승인된 논리 관계만 사용할 수 있고, 지표·정책은 승인 registry 참조만 허용합니다. 작성자는 자기 release를 승인할 수 없고, 원천 구조가 바뀌면 STALE이 됩니다.</div></div>`;
  },
  async agent(p) {
    const rs = (await axGet("/ontology-releases")).filter(r => r.status === "APPROVED" || r.status === "ACTIVE");
    const a = AX.ask;
    return `<div class="card"><b>컴파일·네이티브 파이프라인</b><div class="vfilters"><label>승인 release <select id="axrsel">${rs.map(r => `<option value="${esc(r.release_id)}">${esc(r.model_id)}@${esc(r.version)} (${r.status})</option>`).join("")}</select></label><button data-a="axcompile" data-e="native">native 컴파일+실행</button><button class="ghost" data-a="axcompile" data-e="databricks">DBX 컴파일(실행 안 함)</button></div>
      <div class="sub">native는 원천에서 읽어 별도 저장소에 canonical·entity·relation projection을 실제로 만들고 golden gate를 통과해야 게시 대기가 됩니다. DBX 경로는 SQL 산출물 컴파일까지만 하며 미지원 stage는 가상 성공으로 대체하지 않고 실패로 표시합니다.</div></div>
      <div class="card"><b>매출처·매입처 질문</b> <span class="mute">LLM 없이 승인된 도구로 계산 · 근거 query ID·조회 시각·버전 표시 · 초안은 발송되지 않음</span>
      <div class="vfilters"><label>시나리오 <select onchange="AX.qt=this.value;render(true)">${Object.keys(QT).map(k => `<option value="${k}" ${AX.qt === k ? "selected" : ""}>${esc(QT_KO[k])}</option>`).join("")}</select></label>
      ${QT[AX.qt].map(f => `<label>${esc(f)} <input id="axq_${f}" value="${esc(a[f] ?? "")}" style="width:${f === "tenant_id" ? 60 : 100}px"></label>`).join("")}<button data-a="axask">질문</button></div>
      <div class="sub">매입 비교·견적 도구는 내부 사용자 전용입니다(외부 거래처·공급처는 접근 불가). 승인된 release에 해당 정책이 없으면 실행하지 않습니다.</div>
      ${AX.last ? axAnswer(AX.last) : ""}</div>`;
  },
  async biz(p) {
    const ps = await axGet("/proposals");
    return `<div class="card"><b>제안 → 승인 → 업무 명령</b><div class="vfilters"><label>tenant <input id="axp_t" value="T1" style="width:60px"></label><label>주문 <input id="axp_o" value="SO-1001" style="width:90px"></label><label>수량 <input id="axp_q" value="32" style="width:70px"></label><button data-a="axprop">제안 만들기</button></div>
      ${table(["제안", "내용", "상태", "제안자", "승인자", "처리"], ps.map(x => [x.proposal_id, `${x.payload.order_id}: ${x.payload.from_qty}→${x.payload.new_qty}`, badge(x.state, x.state === "EXECUTED" ? "ok" : x.state === "STALE" ? "bad" : ""), x.proposer, x.approver || "-",
        x.state === "PROPOSED" ? `<a href="#" data-a="axappr" data-p="${esc(x.proposal_id)}" data-h="${esc(x.payload_hash)}">승인(다른 사용자만)</a>` : x.state === "APPROVED" ? `<a href="#" data-a="axcmd" data-p="${esc(x.proposal_id)}" data-h="${esc(x.payload_hash)}">명령 실행</a>` : ""]), true)}
      <div class="sub">제안자는 자기 제안을 승인할 수 없습니다. 실행은 payload hash·유효시간·멱등 키를 검사하고, 원천 트랜잭션에서 재고·정책·row_version을 다시 확인합니다(승인 후 값이 바뀌면 STALE → 재승인). LLM은 수량·권한을 결정하지 않습니다. 이 빌드의 원천은 합성 fixture입니다.</div></div>`;
  },
  async auto(p) {
    const st = await axGet("/auto"), rd = await axGet("/auto/readiness"), srcs = await axGet("/auto/sources"), cons = (await axGet("/connections")).filter(c => c.purpose === "metadata");
    const b = st.brief || { domain_name: "domain", policy: { rel_min_inclusion: 0.98, rel_min_sample: 2 }, acks: {} }, pol = b.policy || {}, jobs = st.jobs || [], lj = jobs[jobs.length - 1];
    if (lj && lj.state === "RUNNING") { clearTimeout(AX.poll); AX.poll = setTimeout(() => { if (VIEW === "ax" && AX.tab === "auto") render(true) }, 3000) }
    const ck = (id, on, label) => `<label style="display:block"><input type="checkbox" id="${id}" ${on ? "checked" : ""}> ${esc(label)}</label>`;
    return `<div class="card" style="border-left:4px solid #2563eb"><b>자동 구축</b> — 연결 정보와 비정형 문서를 제공하고 사전작업을 마친 뒤 <b>승인</b>하면, 구조 수집·분석 → 문서 파싱·청킹·임베딩 → 지식 카드 → 온톨로지 → 파이프라인 → 평가 → 도메인 에이전트까지 자동으로 진행합니다.
      <div class="sub">승인 범위 안에서만 사람 승인을 대신하며(AUTO_POLICY로 표시·감사 기록) 원천 DB를 변경하는 업무 명령은 자동 실행하지 않습니다. 자동 평가는 구조·접근·검색 검사이며 현업 정답 검증이 아닙니다. 외부 LLM·외부 전송은 쓰지 않습니다.</div></div>
    <div class="card"><b>① 연결과 문서 제공</b>
      <div class="vfilters"><label>metadata 연결 <select id="aucon">${cons.map(c => `<option value="${esc(c.connector_id)}" ${b.metadata_connector_id === c.connector_id ? "selected" : ""}>${esc(c.engine)} · ${esc(c.connector_id)} ${c.last_test ? (c.last_test.all_pass ? "✓테스트 통과" : "✗테스트 미통과") : "(테스트 전)"}</option>`).join("")}</select></label>
        <label>도메인 이름 <input id="audom" value="${esc(b.domain_name)}" style="width:140px"></label><label>tenant(선택) <input id="autnt" value="${esc(b.tenant_id || "")}" style="width:70px"></label>
        <button class="ghost" data-a="autotest">연결 7단계 테스트</button></div>
      <div class="vfilters"><input type="file" id="aufile" multiple accept=".txt,.md,.csv,.json,.html,.htm,.docx,.pdf"><button data-a="auupload">문서 올려 파싱</button>
        <label>서버 폴더(허용 폴더만) <input id="aufolder" placeholder="WZ_AX_DOC_DIRS 안의 경로" style="width:220px"></label><button class="ghost" data-a="aufolderadd">폴더 가져오기</button></div>
      <textarea id="autext" placeholder="또는 문서 내용을 붙여 넣기" style="min-height:60px;width:100%"></textarea><div class="row"><input id="auname" placeholder="붙여넣은 문서 이름(예: 정책.md)" style="width:200px"><button class="ghost" data-a="autextadd">붙여넣기 추가</button></div>
      ${table(["소스", "형식", "파서", "글자 수", "경고", "삭제"], srcs.map(s => [s.name, s.report.ext, s.report.parser, s.chars, (s.report.warnings || []).join(" / ") || "-", `<a href="#" data-a="ausrcdel" data-s="${esc(s.source_id)}">삭제</a>`]), true)}
      <div class="sub">지원: txt·md·csv·json·html·docx·pdf(텍스트). 스캔 이미지 PDF의 글자는 OCR 미지원이라 경고합니다. 실행 파일·암호화 문서는 거부합니다.</div></div>
    <div class="card"><b>② 정책과 확인</b>
      ${ck("aup1", pol.auto_approve_relations, "관계 자동 승인: 표본 포함률·표본 수가 아래 기준 이상인 후보를 정책으로 승인")}
      <div class="vfilters"><label>최소 포함률 <input id="aupi" value="${esc(pol.rel_min_inclusion ?? 0.98)}" style="width:60px"></label><label>최소 표본 행 <input id="aups" value="${esc(pol.rel_min_sample ?? 2)}" style="width:50px"></label></div>
      ${ck("aup2", pol.auto_approve_release, "온톨로지 release 자동 승인(검증 통과 시, 독립 검토자 없이)")}
      ${ck("aup3", pol.allow_deploy, "평가 통과 시 native 배포까지 허용(끄면 '배포 대기'에서 멈춤)")}
      ${ck("aund", b.no_documents, "비정형 문서 없이 진행")}
      <hr>${Object.entries(st.ack_texts).map(([k, t]) => ck("auack_" + k, (b.acks || {})[k], t)).join("")}
      <div class="row"><button data-a="aubrief">사전작업 정보 저장</button></div></div>
    <div class="card"><b>③ 준비 점검</b>${table(["항목", "결과", "내용"], rd.checks.map(c => [c.id, c.ok ? badge("통과", "ok") : badge("미충족", "bad"), esc(c.msg)]), true)}${rd.policy_warning ? `<div class="sub"><b>${esc(rd.policy_warning)}</b></div>` : ""}</div>
    <div class="card"><b>④ 승인과 실행</b> ${st.approval ? badge("승인됨 " + esc(st.approval.by), "ok") : badge("미승인", "bad")}
      <div class="vfilters"><label>확인 문구 <input id="auconf" placeholder="자동 구축 승인" style="width:150px"></label><button data-a="auapprove">승인</button><button data-a="aurun" ${st.approval ? "" : "disabled"}>자동 구축 시작</button></div>
      <div class="sub">승인 뒤 연결·정책·문서를 바꾸면 승인이 무효가 됩니다. 실행 전 자원을 확인하고 단계마다 자원이 위험하면 중단합니다(정리 후 재개 가능).</div>
      ${lj ? auJob(lj) : ""}</div>`;
  },
  async search(p) {
    const docs = await axGet("/documents"), r = AX.sres;
    return `<div class="card"><b>지식 문서</b> <button data-a="axdocdemo">합성 데모 문서 넣기</button>
      ${table(["문서", "종류", "버전", "상태", "시행일", "tenant", "접근", "청크"], docs.map(d => [d.title, d.doc_type, d.version, badge(d.status, d.status === "ACTIVE" ? "ok" : ""), d.effective_from, d.tenant_id || "전체", d.acl.internal_only ? "내부 전용" : (d.acl.customers ? "거래처 " + d.acl.customers.join(",") : "공개"), d.chunks]), true)}
      <div class="sub">문서는 버전·시행일·tenant·접근 범위(ACL)를 갖고, 검색 전·응답 직전에 모두 필터합니다. 문서 안의 지시문은 데이터일 뿐 실행하지 않습니다.</div></div>
      <div class="card"><b>검색</b><div class="vfilters"><label>질문 <input id="axsq" value="${esc(AX.sq)}" style="width:320px"></label><label>모드 <select id="axsm">${["hybrid", "keyword", "vector"].map(m => `<option ${AX.smode === m ? "selected" : ""}>${m}</option>`).join("")}</select></label><button data-a="axsearch">검색</button><button class="ghost" data-a="axsearcheval">모드 비교 평가</button></div>
      ${r && r.results ? `<div class="sub">${esc(r.answer_style || "")} ${r.embedding ? "· 임베딩: " + esc(r.embedding) : ""} ${r.route_hint ? "<br><b>" + esc(r.route_hint) + "</b>" : ""}</div>` + table(["문서", "버전", "시행일", "페이지", "점수", "근거 구절"], r.results.map(x => [x.title, x.version, x.effective_from, x.page, x.score, x.snippet]), true) : ""}
      ${r && r.modes ? table(["모드", "recall@1", "recall@3", "nDCG@3"], Object.entries(r.modes).map(([k, v]) => [k, v["recall@1"], v["recall@3"], v["ndcg@3"]]), true) + `<div class="sub">${esc(r.limits)}</div>` : ""}</div>`;
  },
  async sig(p) {
    const sg = await axGet("/signals");
    return `<div class="card"><b>적극적 지원 신호</b> <button data-a="axsigscan">탐지 실행</button>
      ${table(["종류", "대상", "구분", "중요도", "내용", "상태", "유효기한", "처리"], sg.map(x => [x.kind, x.ref, badge(x.class, x.class === "FACT" ? "ok" : ""), x.severity, x.message, x.status, x.valid_until, x.status === "OPEN" ? `<a href="#" data-a="axsigack" data-s="${esc(x.signal_id)}" data-st="ACK">확인</a> · <a href="#" data-a="axsigack" data-s="${esc(x.signal_id)}" data-st="DISMISSED">무시(사유)</a>` : ""]), true)}
      <div class="sub">재고 부족·계약 만료·공급처 단가 편차·입고 차이·납기 위험을 탐지만 합니다. FACT(확정 사실)와 ASSUMPTION(가정·입고 예정 등)을 구분하고, 같은 대상은 중복 등록하지 않습니다. 외부 발송·주문·발주를 자동 실행하지 않습니다.</div></div>`;
  },
  async ev(p) {
    const au = await axGet("/audit");
    return `<div class="card"><b>평가·배포</b><div class="row"><button data-a="axeval">golden·보안 평가 실행</button><button data-a="axdeploy">승인 release 배포(native)</button><button class="ghost" data-a="axrollback">이전 release로 rollback</button><a href="#" data-a="axexport">프로젝트 내보내기(JSON, secret 제외)</a></div>
      <div class="sub">배포는 필수 gate(golden·보안 100%)를 통과한 평가가 있어야 합니다. 평가 세트는 초기 8+5건으로 지시서 목표(최소 120건·현업 정답·봉인 holdout)에 한참 못 미칩니다. 성능·부하·실제 LLM·실제 레거시 DB·DBX parity는 측정하지 않았습니다. rollback은 원천 거래를 건드리지 않습니다.</div></div>
      <div class="card"><b>감사 기록(최근)</b>${table(["시각", "행위자", "종류", "참조", "결과"], au.slice(-15).reverse().map(x => [fmtIso(x.at), x.actor, x.kind, x.ref, x.outcome]), true)}</div>`;
  }
};

function auJob(j) {
  const rep = j.summary && j.summary.report;
  return `<div class="card"><b>작업 ${esc(j.job_id)}</b> ${badge(j.state, j.state === "COMPLETED" ? "ok" : (j.state === "RUNNING" ? "" : "bad"))} <span class="mute">${esc(j.started_at || "")}</span>
    ${table(["단계", "상태", "결과"], j.stages.map(s => [esc(s.label), badge(s.state, s.state === "SUCCEEDED" ? "ok" : (s.state === "FAILED" ? "bad" : "")), s.error ? `<span style="color:#dc2626">${esc(s.error.code)}: ${esc(s.error.message)}</span>` : (s.detail ? esc(JSON.stringify(s.detail)).slice(0, 220) : "")]), true)}
    ${(j.state === "FAILED" || j.state === "PAUSED_FOR_REVIEW") ? `<div class="row"><button data-a="aujobresume" data-j="${esc(j.job_id)}">재개</button>${j.state === "PAUSED_FOR_REVIEW" ? '<span class="mute">온톨로지 탭에서 다른 사용자가 release를 승인한 뒤 재개하세요.</span>' : ""}</div>` : ""}
    ${j.state === "RUNNING" ? `<button class="ghost" data-a="aujobcancel" data-j="${esc(j.job_id)}">취소</button>` : ""}
    ${rep ? `<div class="sub"><b>결과 보고</b> release ${esc(rep.release.id || "-")} (${esc(rep.release.status || "-")}, ${esc(rep.release.approval_mode || "-")}) · 자동 승인 관계 ${rep.auto_approved_relations.length}건 · 사람 검토 필요 관계 ${rep.relations_need_human_review.length}건 · 색인 문서 ${rep.documents_indexed} · 지식 카드 ${rep.knowledge_cards}<br>
      <b>검증되지 않은 것</b>: ${rep.what_is_not_verified.map(esc).join(" / ")}<br>다음: ${esc(rep.next)}</div>` : ""}</div>`;
}
function axAnswer(r) {
  const x = r.result, d = x.detail; let extra = "";
  if (d && d.order && d.stock && d.request) extra = table(["항목", "값"], [["현재→요청", `${d.order.current_qty} → ${d.request.new_qty}`], ["추가 필요", d.request.extra_needed], ["재고/예약합계", `${d.stock.on_hand} / ${d.stock.reserved_total}`], ["추가 가용", d.stock.additional_available], ["부족", d.shortage], ["최대 가능 수량", d.max_feasible_qty], ["여신 여유/단가", `${d.credit.headroom} / ${d.credit.unit_price}`]], true);
  else if (d) extra = `<details><summary>상세 보기</summary><pre style="white-space:pre-wrap;max-height:220px;overflow:auto">${esc(JSON.stringify(d, null, 1))}</pre></details>`;
  const alts = (x.alternatives || []).map(a => `<div>대안 · ${esc(a.desc || (a.supplier_id ? `${a.supplier_id}: 발주 ${a.order_qty}박스, 총 ${a.total_cost}원, 도착 ${a.arrival}, 점수 ${a.score}` : JSON.stringify(a)))}</div>`).join("");
  const drafts = (x.drafts || []).map(t => `<div class="mute">✎ ${esc(t)}</div>`).join("");
  return `<div class="card"><b>${esc(x.verdict)}</b> — ${esc(x.answer)}${extra}${alts}${drafts}<div class="mute">근거: query ${esc((r.query_ids || []).join(","))} · 조회 ${esc(r.observed_at)} · ${esc(r.ontology)} · ${esc(r.policy)} · ${esc(r.tool)} · LLM ${esc(r.llm)} · 증거 ${esc(r.evidence_level)}</div></div>`
}

Object.assign(H, {
  axtab(d) { AX.tab = d.t; AX.res = null; render(true) },
  axnew() { axTry(async () => { const r = await api(AXP, { body: { name: val("axname"), engine: val("axeng") } }); AX.pid = r.project_id; AX.res = null; toast("프로젝트를 만들었습니다"); render(true) }) },
  axmember() { axTry(async () => { const sp = s => (s || "").split(",").map(x => x.trim()).filter(Boolean); const t = sp(val("axmt")), c = sp(val("axmc")); AX.res = await axPost("/members", { user_id: val("axmu"), role: val("axmr"), tenants: t.length ? t : null, customers: c.length ? c : null }); render(true) }) },
  axconnfix() { axTry(async () => { AX.res = await axPost("/connections", { engine: "sqlite_fixture", purpose: "metadata" }); render(true) }) },
  axtest(d) { axTry(async () => { AX.res = await axPost(`/connections/${d.c}/test`); render(true) }) },
  axscan(d) { axTry(async () => { AX.res = await axPost("/scans", { connector_id: d.c }); render(true) }) },
  axprofile() { axTry(async () => { AX.res = await axPost("/profiles", { object_id: "main.party", sample_rows: 100 }); render(true) }) },
  axerd() { AX.erdFocus = val("axfocus") || "sales_orders"; AX.hops = +val("axhops"); axTry(async () => { render(true) }) },
  axinfer() { axTry(async () => { AX.res = await axPost("/relation-candidates", {}); render(true) }) },
  axrel(d) { axTry(async () => { AX.res = await axPost("/relation-reviews", { relation_id: d.r, decision: d.d, note: val("axrn_" + d.r) || "" }); render(true) }) },
  axrelcreate() { axTry(async () => { AX.res = await axPost("/ontology-releases", { template: "distribution_ax" }); render(true) }) },
  axrelval(d) { axTry(async () => { AX.res = await axPost(`/ontology-releases/${d.r}/validate`); render(true) }) },
  axrelrev(d) { axTry(async () => { AX.res = await axPost(`/ontology-releases/${d.r}/review`, { decision: d.d, note: val("axnote_" + d.r) || "" }); render(true) }) },
  axcompile(d) { axTry(async () => { const pl = await axPost("/compilations", { release_id: val("axrsel"), engine: d.e }); AX.res = pl; if (d.e === "native" && pl.status === "COMPILED") AX.res = await axPost("/pipeline-runs", { plan_id: pl.plan_id }); render(true) }) },
  axask() { const body = { question_type: AX.qt }; QT[AX.qt].forEach(f => { const v = val("axq_" + f); AX.ask[f] = v; if (v !== "" && v != null) body[f] = v }); axTry(async () => { AX.last = await axPost("/agent-runs", body); AX.res = null; render(true) }) },
  autotest() { axTry(async () => { AX.res = await axPost(`/connections/${val("aucon")}/test`); render(true) }) },
  aubrief() { axTry(async () => { const ack = {}; ["egress_ack", "readonly_ack", "resource_ack", "nonprod_ack"].forEach(k => ack[k] = !!$("#auack_" + k)?.checked);
    AX.res = await axPost("/auto/brief", { metadata_connector_id: val("aucon"), domain_name: val("audom"), tenant_id: val("autnt") || null, no_documents: !!$("#aund").checked, acks: ack,
      policy: { auto_approve_relations: !!$("#aup1").checked, auto_approve_release: !!$("#aup2").checked, allow_deploy: !!$("#aup3").checked, rel_min_inclusion: parseFloat(val("aupi")), rel_min_sample: parseInt(val("aups")) } }); render(true) }) },
  auupload() { axTry(async () => { const fs = [...($("#aufile").files || [])]; const out = []; for (const f of fs) { const buf = new Uint8Array(await f.arrayBuffer()); let bin = ""; buf.forEach(c => bin += String.fromCharCode(c)); try { out.push(await axPost("/auto/sources", { name: f.name, content_b64: btoa(bin) })) } catch (e) { out.push({ file: f.name, error: e.data || e.message }) } } AX.res = out; render(true) }) },
  autextadd() { axTry(async () => { AX.res = await axPost("/auto/sources", { name: val("auname") || "붙여넣기.txt", text: val("autext") }); render(true) }) },
  aufolderadd() { axTry(async () => { AX.res = await axPost("/auto/sources/folder", { path: val("aufolder") }); render(true) }) },
  ausrcdel(d) { axTry(async () => { AX.res = await api(`${AXP}/${AX.pid}/auto/sources/${d.s}`, { method: "DELETE" }); render(true) }) },
  auapprove() { axTry(async () => { AX.res = await axPost("/auto/approve", { confirm: val("auconf") || "" }); render(true) }) },
  aurun() { axTry(async () => { AX.res = await axPost("/auto/run", {}); render(true) }) },
  aujobresume(d) { axTry(async () => { AX.res = await axPost(`/auto/jobs/${d.j}/resume`, {}); render(true) }) },
  aujobcancel(d) { axTry(async () => { AX.res = await axPost(`/auto/jobs/${d.j}/cancel`, {}); render(true) }) },
  axdocdemo() { axTry(async () => { AX.res = await axPost("/documents/demo"); render(true) }) },
  axsearch() { AX.sq = val("axsq"); AX.smode = val("axsm"); axTry(async () => { AX.sres = await axGet(`/search?q=${encodeURIComponent(AX.sq)}&mode=${AX.smode}`); AX.res = null; render(true) }) },
  axsearcheval() { axTry(async () => { AX.sres = await axPost("/search-evaluations"); AX.res = null; render(true) }) },
  axsigscan() { axTry(async () => { AX.res = await axPost("/signals/scan", {}); render(true) }) },
  axsigack(d) { axTry(async () => { const note = d.st === "DISMISSED" ? ("사용자가 UI에서 무시 처리" || "") : ""; AX.res = await axPost(`/signals/${encodeURIComponent(d.s)}/ack`, { status: d.st, note }); render(true) }) },
  axprop() { axTry(async () => { AX.res = await axPost("/proposals", { tenant_id: val("axp_t"), order_id: val("axp_o"), new_qty: val("axp_q") }); render(true) }) },
  axappr(d) { axTry(async () => { AX.res = await axPost("/approvals", { proposal_id: d.p, payload_hash: d.h }); render(true) }) },
  axcmd(d) { axTry(async () => { AX.res = await axPost("/commands", { proposal_id: d.p, payload_hash: d.h, idempotency_key: "ui-" + d.p }); render(true) }) },
  axeval() { axTry(async () => { AX.res = await axPost("/evaluations", {}); render(true) }) },
  axdeploy() { axTry(async () => { const rs = (await axGet("/ontology-releases")).filter(r => r.status === "APPROVED"); AX.res = await axPost("/deployments", { release_id: (rs[0] || {}).release_id }); render(true) }) },
  axrollback() { axTry(async () => { AX.res = await axPost("/rollback"); render(true) }) },
  axexport() { axTry(async () => { AX.res = await axGet("/export"); render(true) }) },
});
