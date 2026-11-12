"use strict";
/* x_genai.js: UI-29 생성형 AI·RAG 시뮬레이션(Playground · AI Search 인덱스 · RAG 에이전트 · 평가 · 배포).
   실제 LLM·임베딩이 아니다: 모의 모델 + 키워드(BM25) 검색으로 '구조'를 연습한다. app.js 전역 헬퍼를 그대로 쓴다. */
const GA = { tab: "playground", err: null, pg: { useB: false, res: null, A: {}, B: {} }, idx: { q: null }, agent: { run: null }, ev: { res: null }, srv: null, srvq: null };
const GA_TABS = [["playground", "Playground"], ["index", "AI Search 인덱스"], ["agent", "RAG 에이전트"], ["eval", "평가"], ["deploy", "배포·Agent Bricks"]];
const GA_PG_DEFAULT = { system: "당신은 문서 도우미입니다. 컨텍스트에 있는 내용만 근거로 설명하세요. 모르면 모른다고 답하세요.", template: "{{topic}}에 대해 한 문장으로 설명하세요.", vars: "topic=COPY INTO", context: "COPY INTO는 파일의 새 데이터를 테이블에 추가합니다. 이미 읽은 파일은 다시 적재하지 않아 같은 명령을 반복해도 중복되지 않습니다. 날씨는 오늘 맑습니다.", user: "COPY INTO는 중복을 만드나요?" };
const gaPct = x => x === null || x === undefined ? null : Math.round(x * 1000) / 10;

function gaSavePg() {
  for (const k of ["A", "B"]) {
    const o = {}; let any = false;
    for (const f of ["system", "template", "vars", "context", "user"]) { const el = document.getElementById(`pg${k}_${f}`); if (el) { o[f] = el.value; any = true } }
    if (any) GA.pg[k] = o;
  }
}
function gaVars(text) { const o = {}; String(text || "").split(/\n/).forEach(l => { const i = l.indexOf("="); if (i > 0) o[l.slice(0, i).trim()] = l.slice(i + 1).trim() }); return o }
async function gaCall(path, body) {
  try { GA.err = null; return await api(`/api/sessions/${SID}/genai${path}`, { body: body || {} }) }
  catch (e) { GA.err = e.data || { code: "ERROR", message: e.message }; log("✗ " + e.message, true, GA.err); return null }
}
function gaOpts(arr, cur, none) { return (none ? `<option value="">${esc(none)}</option>` : "") + arr.map(x => `<option value="${esc(x)}" ${x === cur ? "selected" : ""}>${esc(x)}</option>`).join("") }

/* 묶음 막대: 지표(x) × 버전(시리즈). 0~100% 한 축, 막대 끝 둥글게, 막대 사이 2px, 마우스 올리면 값 */
function gaBars(labels, series) {
  const W = 720, H = 220, L = 40, R = 8, T = 14, B = 28, pw = W - L - R, ph = H - T - B, g = pw / labels.length, n = series.length, bw = Math.min(46, (g - 18) / n - 2);
  const y = v => T + ph - v / 100 * ph;
  const grid = [0, 25, 50, 75, 100].map(v => `<line x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}" class="vgrid"/><text x="${L - 6}" y="${y(v) + 4}" class="vax" text-anchor="end">${v}%</text>`).join("");
  const bars = labels.map((lb, i) => {
    const x0 = L + i * g + (g - (bw * n + 2 * (n - 1))) / 2;
    const bs = series.map((s, k) => { const v = s.values[i] ?? 0, x = x0 + k * (bw + 2), top = y(v), h = Math.max(1, T + ph - top), r = Math.min(4, bw / 2, h);
      const tip = `<b>${esc(lb)}</b><br>${esc(s.name)}: <b>${s.values[i] === null || s.values[i] === undefined ? "-" : v + "%"}</b>`;
      return `<path d="M${x.toFixed(1)},${(T + ph).toFixed(1)}V${(top + r).toFixed(1)}Q${x.toFixed(1)},${top.toFixed(1)} ${(x + r).toFixed(1)},${top.toFixed(1)}H${(x + bw - r).toFixed(1)}Q${(x + bw).toFixed(1)},${top.toFixed(1)} ${(x + bw).toFixed(1)},${(top + r).toFixed(1)}V${(T + ph).toFixed(1)}Z" fill="${s.color}"/>
        <text x="${(x + bw / 2).toFixed(1)}" y="${(top - 4).toFixed(1)}" class="vax" text-anchor="middle">${s.values[i] === null || s.values[i] === undefined ? "-" : v}</text>
        <rect x="${x.toFixed(1)}" y="${T}" width="${bw.toFixed(1)}" height="${ph}" fill="transparent" ${tipAttr(tip)}/>` }).join("");
    return `<g class="vbar">${bs}</g><text x="${(L + i * g + g / 2).toFixed(1)}" y="${H - 8}" class="vax" text-anchor="middle">${esc(lb)}</text>`;
  }).join("");
  return `<svg viewBox="0 0 ${W} ${H}" class="vsvg" role="img" aria-label="평가 지표 비교 막대 차트">${grid}${bars}</svg>${n > 1 ? legend(series.map((s, k) => [s.name, s.color, ["●", "■"][k]])) : ""}`;
}

function gaPgBox(k, v) {
  const d = Object.assign({}, GA_PG_DEFAULT, v || {});
  return `<div class="card"><b>${k === "A" ? "프롬프트 A" : "프롬프트 B"}</b>
    <label>시스템 프롬프트</label><textarea id="pg${k}_system" style="min-height:70px">${esc(d.system)}</textarea>
    <label>지시 템플릿 <span class="mute">({{변수}} 사용)</span></label><textarea id="pg${k}_template" style="min-height:50px">${esc(d.template)}</textarea>
    <label>변수 <span class="mute">(줄마다 이름=값)</span></label><textarea id="pg${k}_vars" style="min-height:40px">${esc(d.vars)}</textarea>
    <label>컨텍스트(참고 문서)</label><textarea id="pg${k}_context" style="min-height:90px">${esc(d.context)}</textarea>
    <label>사용자 입력</label><input id="pg${k}_user" value="${esc(d.user)}"></div>`;
}
function gaPgResult(r) {
  return `<div class="card"><b>프롬프트 ${esc(r.label)}</b> ${badge("점검 " + Math.round(r.checklist.score * 100) + "점", r.checklist.score >= 0.8 ? "ok" : r.checklist.score >= 0.5 ? "w" : "bad")} <span class="mute">토큰 추정 ${r.tokens_estimate}(글자수÷4) · 스타일 ${esc(r.style)}</span>
    ${r.missing_variables.length ? `<div class="warnc">값이 없는 변수: ${r.missing_variables.map(esc).join(", ")}</div>` : ""}
    <h3>모의 모델 답변 <span class="mute">(실제 LLM 아님)</span></h3><pre>${esc(r.answer)}</pre>
    <details><summary>최종 프롬프트 보기</summary><pre>${esc(r.prompt)}</pre></details>
    ${table(["점검", "결과", "개선 힌트"], r.checklist.items.map(i => [`<span style="white-space:nowrap">${esc(i.label)}</span>`, `<span style="white-space:nowrap">${i.ok ? "✓ 충족" : "✕ 미흡"}</span>`, esc(i.hint)]))}</div>`;
}

Object.assign(V, {
  async genai() {
    const o = await api(`/api/sessions/${SID}/genai`), T = GA.tab;
    const tabs = `<div class="vfilters" role="tablist">${GA_TABS.map(([k, l]) => `<button class="${T === k ? "primary" : "ghost"}" role="tab" data-a="gatab" data-k="${k}">${l}</button>`).join("")}</div>`;
    const banner = `<div class="banner">${badge("SIMULATED", "w")} <b>모의 모델(실제 LLM 아님)</b> · 키워드(BM25) 검색(임베딩 의미 검색 아님). ${esc(o.note)} 근거: Academy 'Get started with Databricks for generative AI' 코스 개요(레슨 본문은 조회하지 않음).</div>`;
    const err = GA.err ? `<div class="card">${remedyHtml(GA.err)}</div>` : "";
    let b = "";
    const idxNames = o.indexes.map(i => i.name), agNames = o.agents.map(a => a.name);
    if (T === "playground") {
      const p = GA.pg, res = p.res;
      b = `<div class="sub">AI Playground처럼 시스템 프롬프트·템플릿·컨텍스트·입력을 조립해 최종 프롬프트를 보고, 모의 모델이 컨텍스트 문장을 골라 지시 형식(한 문장·불릿·JSON)에 맞춰 답하는 것을 확인합니다. 아래 점검표로 프롬프트를 개선해 보세요.</div>
        <div class="vfilters"><label><input type="checkbox" ${p.useB ? "checked" : ""} onchange="H.gatoggleb(this.checked)"> 프롬프트 B와 비교</label><button data-a="garun">실행</button></div>
        <div class="${p.useB ? "grid2" : ""}">${gaPgBox("A", p.A)}${p.useB ? gaPgBox("B", Object.keys(p.B).length ? p.B : Object.assign({}, GA_PG_DEFAULT, { system: "", template: "" })) : ""}</div>
        ${res ? `<div class="${res.variants.length > 1 ? "grid2" : ""}">${res.variants.map(gaPgResult).join("")}</div>` : ""}`;
    } else if (T === "index") {
      const q = GA.idx.q;
      b = `<div class="sub">AI Search(문서에 따라 Vector Search 로도 표기) 인덱스를 UC 테이블에서 만듭니다. Delta Sync <b>수동(triggered)</b> 방식이라 원본 테이블이 바뀌면 <b>STALE</b>이 되고 [동기화]로 다시 색인합니다. 원본 SELECT 권한이 없으면 만들거나 질의할 수 없습니다. 이 시뮬레이터의 검색은 키워드(BM25)이므로 동의어·바꿔 말하기는 찾지 못합니다.</div>
        <div class="card"><b>샘플 문서 테이블</b> <span class="mute">${esc(o.doc_table)} · ${o.doc_count}건(직접 작성한 합성 학습 문서)</span> ${o.doc_table_exists ? badge("있음", "ok") : badge("없음", "w")}<div class="row"><button data-a="gasample">샘플 문서 테이블 만들기</button></div></div>
        <div class="card"><b>인덱스 만들기</b><div class="vfilters">
          <label>이름 <input id="gx_name" value="food_dev.gold.doc_index" style="width:210px"></label><label>원본 테이블 <input id="gx_src" value="${esc(o.doc_table)}" style="width:210px"></label>
          <label>기본키 <input id="gx_pk" value="doc_id" style="width:90px"></label><label>텍스트 열 <input id="gx_text" value="content" style="width:100px"></label><label>메타데이터 열 <input id="gx_meta" value="category,title" style="width:150px"></label><button data-a="gaidxcreate">만들기</button></div></div>
        <div class="card"><b>인덱스</b>${o.indexes.length ? table(["이름", "원본", "행", "상태", "동기화 버전/원본 버전", "마지막 동기화", "동작"], o.indexes.map(i => [esc(i.name), esc(i.source), i.rows, badge(i.state === "STALE" ? "✕ STALE" : "✓ ONLINE", i.state === "STALE" ? "bad" : "ok"), `${i.synced_version} / ${i.source_version}`, fmtIso(i.synced_at), `<a href="#" data-a="gasync" data-n="${esc(i.name)}">동기화</a> · <a href="#" data-a="gaidxdel" data-n="${esc(i.name)}">삭제</a>`])) : '<div class="mute">인덱스가 없습니다.</div>'}
          ${o.indexes.some(i => i.state === "STALE") ? '<div class="warnc">원본 테이블이 바뀌었습니다. 동기화 전에는 새 데이터가 검색되지 않습니다.</div>' : ""}</div>
        <div class="card"><b>검색해 보기</b><div class="vfilters"><label>인덱스 <select id="gq_idx">${gaOpts(idxNames, (q || {}).index)}</select></label><input id="gq_q" value="${esc((q || {}).query || "COPY INTO를 반복 실행하면?")}" style="width:260px" onkeydown="if(event.key==='Enter')H.gaquery()"><label>k <input id="gq_k" type="number" min="1" max="20" value="${(q || {}).k || 3}" style="width:56px"></label><label>필터 <input id="gq_f" placeholder="열=값 (예: category=pipeline)" style="width:190px"></label><button data-a="gaquery">검색</button></div>
          ${q ? `<div class="sub">토큰: ${q.tokens.map(esc).join(" · ") || "(없음)"} · 상태 ${esc(q.state)}</div>${q.hits.length ? table(["순위", "문서", "점수", "내용"], q.hits.map(h => [h.rank, h.pk, h.score, h.text]), true) : '<div class="mute">일치하는 문서가 없습니다.</div>'}` : ""}</div>`;
    } else if (T === "agent") {
      const run = GA.agent.run;
      b = `<div class="sub">RAG 에이전트는 <b>검색(retrieve) → 프롬프트 조립(build_prompt) → 생성(generate)</b> 세 단계를 거치며, 단계마다 trace(span)를 남기고 답에 인용(문서 ID)을 붙입니다. 이름은 UC 3단계이며 등록할 때마다 버전이 올라갑니다.</div>
        <div class="card"><b>에이전트 등록(새 버전)</b><div class="vfilters"><label>이름 <input id="ga_name" value="${esc(agNames[0] || "food_dev.gold.doc_assistant")}" style="width:220px"></label>
          <label>인덱스 <select id="ga_idx">${gaOpts(idxNames, idxNames[0])}</select></label><label>k <input id="ga_k" type="number" min="1" max="10" value="3" style="width:56px"></label>
          <label>답변 스타일 <select id="ga_style">${Object.entries(o.styles).map(([k, l]) => `<option value="${k}">${esc(l)}</option>`).join("")}</select></label></div>
          <textarea id="ga_sys" style="min-height:60px">당신은 문서 도우미입니다. 컨텍스트에 있는 내용만 근거로 설명하세요.</textarea><div class="row"><input id="ga_note" placeholder="변경 메모(선택)" style="width:260px"><button data-a="gaagentreg">등록</button></div>
          ${idxNames.length ? "" : '<div class="warnc">먼저 AI Search 인덱스를 만드세요.</div>'}</div>
        <div class="card"><b>등록된 에이전트</b>${o.agents.length ? o.agents.map(a => `<div><b>${esc(a.name)}</b>${table(["버전", "인덱스", "k", "스타일", "메모", "등록"], a.versions.map(v => [v.version, v.index, v.k, o.styles[v.style] || v.style, v.note, fmtIso(v.created_at)]), true)}</div>`).join("") : '<div class="mute">등록된 에이전트가 없습니다.</div>'}</div>
        <div class="card"><b>질문하기</b><div class="vfilters"><label>에이전트 <select id="gr_name">${gaOpts(agNames, agNames[0])}</select></label><label>버전 <input id="gr_ver" placeholder="최신" style="width:60px"></label><input id="gr_q" value="서버리스 웨어하우스는 언제 켜지나요?" style="width:300px" onkeydown="if(event.key==='Enter')H.gaagentrun()"><button data-a="gaagentrun">실행</button></div>
          ${run ? `<div class="sub">trace ${esc(run.id)} · ${esc(run.agent)} v${run.version} · ${run.total_ms}ms</div><pre>${esc(run.answer)}</pre><div>인용: ${run.citations.length ? run.citations.map(c => badge(c, "ok")).join(" ") : '<span class="mute">없음</span>'}</div>
            ${table(["span", "ms", "입력", "출력"], run.spans.map(s => [s.name, s.ms, JSON.stringify(s.inputs), JSON.stringify(s.outputs)]), true)}<details><summary>최종 프롬프트 보기</summary><pre>${esc(run.prompt)}</pre></details>` : ""}</div>
        <div class="card"><b>최근 trace</b>${o.traces.length ? table(["시각", "에이전트", "버전", "구분", "질문", "인용", "ms"], o.traces.map(t => [fmtIso(t.at), t.agent, t.version, t.tag, t.question, t.citations.join(", "), t.total_ms]), true) : '<div class="mute">trace가 없습니다.</div>'}</div>`;
    } else if (T === "eval") {
      const res = GA.ev.res;
      b = `<div class="sub">평가 세트(질문 + 기대 문서 + 기대 키워드)로 에이전트를 점검합니다. 지표: <b>hit@k</b>(기대 문서를 상위 k개 안에서 찾은 비율), <b>MRR</b>(첫 정답 순위의 역수 평균), <b>근거성</b>(답 문장이 검색 문서와 겹치는 비율), <b>키워드 포함률</b>. 합격선(hit@k)을 넘는 버전만 배포한다는 <b>게이트</b>를 연습합니다. 두 버전을 골라 A/B로 비교할 수 있습니다.</div>
        <div class="card"><b>평가 실행</b><div class="vfilters"><label>에이전트 <select id="ge_name">${gaOpts(agNames, agNames[0])}</select></label><label>버전 A <input id="ge_va" placeholder="최신" style="width:60px"></label><label>버전 B(선택) <input id="ge_vb" style="width:60px"></label><label>합격선 hit@k ≥ <input id="ge_th" type="number" step="0.05" min="0" max="1" value="0.8" style="width:64px"></label><button data-a="gaeval">평가 실행(샘플 세트 ${o.sample_eval.length}문항)</button></div>
          <details><summary>샘플 평가 세트 보기</summary>${table(["질문", "기대 문서", "기대 키워드"], o.sample_eval.map(q => [q.question, q.expected_docs.join(", "), q.keywords.join(", ")]), true)}</details>
          ${agNames.length ? "" : '<div class="warnc">먼저 RAG 에이전트를 등록하세요.</div>'}</div>
        ${res ? gaEvalResult(res) : ""}
        <div class="card"><b>평가 기록</b>${o.evals.length ? table(["시각", "에이전트", "버전", "hit@k", "MRR", "근거성", "게이트"], o.evals.map(e => [fmtIso(e.at), e.agent, e.version, gaPct(e.metrics.hit_at_k) + "%", gaPct(e.metrics.mrr) + "%", gaPct(e.metrics.groundedness) + "%", e.passed ? "✓ 통과" : "✕ 미달"]), true) : '<div class="mute">평가 기록이 없습니다.</div>'}</div>`;
    } else {
      const sv = GA.srv || { endpoints: [], max_slots: o.max_slots };
      b = `<div class="sub">등록한 에이전트를 Model Serving 엔드포인트로 배포하고 질의합니다. 엔드포인트 슬롯은 모델·에이전트가 <b>${sv.max_slots}개를 함께</b> 씁니다(Free Edition처럼). 상세 관리는 Model Serving(UI-27) 화면에서도 할 수 있습니다.</div>
        <div class="card"><b>에이전트 엔드포인트 만들기</b> <span class="mute">슬롯 ${sv.endpoints.length}/${sv.max_slots} 사용</span><div class="vfilters"><label>이름 <input id="gs_name" value="doc-agent" style="width:150px"></label><label>에이전트 <select id="gs_agent">${gaOpts(agNames, agNames[0])}</select></label><label>버전 <input id="gs_ver" placeholder="최신" style="width:60px"></label><button data-a="gaserve">만들기</button></div></div>
        <div class="card"><b>엔드포인트</b>${sv.endpoints.length ? table(["이름", "종류", "상태", "질의 수", "동작"], sv.endpoints.map(e => [esc(e.name), esc(e.kind), esc(e.state), e.queries, `<a href="#" data-a="gaservedel" data-n="${esc(e.name)}">삭제</a>`])) : '<div class="mute">엔드포인트가 없습니다.</div>'}
          ${sv.endpoints.some(e => e.kind === "agent") ? `<div class="vfilters"><label>질의 <select id="gs_q_ep">${gaOpts(sv.endpoints.filter(e => e.kind === "agent").map(e => e.name))}</select></label><input id="gs_q" value="COPY INTO를 반복 실행하면 중복되나요?" style="width:300px"><button data-a="gaserveq">질의</button></div>` : ""}
          ${GA.srvq ? `<div class="sub">지연 ${GA.srvq.latency_ms}ms · ${esc(GA.srvq.evidence_level)}</div><pre>${esc(JSON.stringify(GA.srvq.result, null, 2))}</pre>` : ""}</div>
        <div class="card"><b>Agent Bricks</b> ${badge("존재만 확인", "w")}<div class="sub">${esc(o.agent_bricks.known)} ${esc(o.agent_bricks.unknown)}</div></div>`;
    }
    return `<h2>UI-29 생성형 AI·RAG</h2>${banner}${tabs}${err}${b}`;
  },
});

function gaEvalResult(res) {
  const rs = res.results, labels = ["hit@k", "MRR", "근거성", "키워드 포함률"];
  const series = rs.map((r, k) => ({ name: `버전 ${r.version}`, color: SER[k], values: [gaPct(r.metrics.hit_at_k), gaPct(r.metrics.mrr), gaPct(r.metrics.groundedness), gaPct(r.metrics.keyword_rate)] }));
  return `<div class="card"><b>평가 결과</b> <span class="mute">${esc(res.note)}</span>
    <div class="vfilters">${rs.map(r => `<span>버전 ${r.version}(k=${r.k}): ${r.passed ? badge("✓ 게이트 통과", "ok") : badge("✕ 게이트 미달", "bad")} <span class="mute">hit@k ${gaPct(r.metrics.hit_at_k)}% / 합격선 ${gaPct(r.threshold)}%</span></span>`).join(" ")}</div>
    <div class="vc">${gaBars(labels, series)}</div>${tableView(["지표"].concat(series.map(s => s.name)), labels.map((l, i) => [l].concat(series.map(s => s.values[i] === null ? "-" : s.values[i] + "%"))))}
    ${rs.map(r => `<details><summary>버전 ${r.version} 문항별 결과(${r.questions}개)</summary>${table(["질문", "기대", "검색 결과(상위)", "순위", "근거성", "키워드", "답변"], r.per_question.map(p => [p.question, p.expected_docs.join(", "), p.retrieved.join(", "), p.rank ?? "미검색", gaPct(p.grounded) + "%", p.keywords_total ? `${p.keywords_hit}/${p.keywords_total}` : "-", p.answer]), true)}</details>`).join("")}
    <div class="sub">${esc(res.gate)}</div></div>`;
}

Object.assign(H, {
  gatab(d) { gaSavePg(); GA.tab = d.k; GA.err = null; if (d.k === "deploy") { gaLoadSrv().then(() => render(true)) } else render(true) },
  gatoggleb(on) { gaSavePg(); GA.pg.useB = !!on; render(true) },
  async garun() {
    gaSavePg(); const mk = k => { const o = Object.assign({}, GA_PG_DEFAULT, GA.pg[k] || {}); return { label: k, system: o.system, template: o.template, variables: gaVars(o.vars), context: o.context, user: o.user } };
    const r = await gaCall("/playground", { variants: GA.pg.useB ? [mk("A"), mk("B")] : [mk("A")] }); if (r) GA.pg.res = r; render(true)
  },
  async gasample() { const r = await gaCall("/docs/sample"); if (r) log(r.created ? `${r.table} ${r.rows}건을 만들었습니다` : "샘플 문서 테이블이 이미 있습니다"); await refresh() },
  async gaidxcreate() {
    const r = await gaCall("/index", { name: val("gx_name"), source: val("gx_src"), pk: val("gx_pk"), text_col: val("gx_text"), meta_cols: (val("gx_meta") || "").split(",").map(x => x.trim()).filter(Boolean) });
    if (r) log(`인덱스 ${r.name} 생성(${r.rows}행)`); await refresh()
  },
  async gasync(d) { const r = await gaCall("/index/sync", { name: d.n }); if (r) log(`인덱스 ${r.name} 동기화(원본 버전 ${r.synced_version})`); await refresh() },
  async gaidxdel(d) { const r = await gaCall("/index/delete", { name: d.n }); if (r) log(`인덱스 ${r.deleted} 삭제`); await refresh() },
  async gaquery() {
    const f = (val("gq_f") || "").trim(), filters = {}; if (f.includes("=")) { const i = f.indexOf("="); filters[f.slice(0, i).trim()] = f.slice(i + 1).trim() }
    const r = await gaCall("/index/query", { name: val("gq_idx"), query: val("gq_q"), k: +val("gq_k") || 3, filters }); if (r) { GA.idx.q = r } render(true)
  },
  async gaagentreg() {
    const r = await gaCall("/agent/register", { name: val("ga_name"), index: val("ga_idx"), k: +val("ga_k") || 3, style: val("ga_style"), system: val("ga_sys"), note: val("ga_note") });
    if (r) log(`에이전트 ${r.name} 버전 ${r.version} 등록`); await refresh()
  },
  async gaagentrun() { const r = await gaCall("/agent/run", { name: val("gr_name"), version: val("gr_ver") || null, question: val("gr_q") }); if (r) GA.agent.run = r; await refresh() },
  async gaeval() {
    const vs = [val("ge_va") || null]; if (val("ge_vb")) vs.push(val("ge_vb"));
    const r = await gaCall("/eval", { agent: val("ge_name"), versions: vs, threshold: +val("ge_th") || 0.8 }); if (r) { GA.ev.res = r; log(`평가 완료(${r.results.length}개 버전)`) } await refresh()
  },
  async gaserve() {
    try { GA.err = null; const v = val("gs_ver"); const r = await api(`/api/sessions/${SID}/serving`, { body: { name: val("gs_name"), kind: "agent", config: { agent: val("gs_agent"), version: v ? +v : null } } }); log(`엔드포인트 ${r.name} 생성`) }
    catch (e) { GA.err = e.data || { code: "ERROR", message: e.message }; log("✗ " + e.message, true, GA.err) }
    await gaLoadSrv(); render(true)
  },
  async gaservedel(d) { try { await api(`/api/sessions/${SID}/serving/${encodeURIComponent(d.n)}/delete`, { body: {} }); log(`엔드포인트 ${d.n} 삭제`) } catch (e) { toast(e.message) } await gaLoadSrv(); render(true) },
  async gaserveq() {
    try { GA.err = null; GA.srvq = await api(`/api/sessions/${SID}/serving/${encodeURIComponent(val("gs_q_ep"))}/query`, { body: { messages: [{ role: "user", content: val("gs_q") }] } }) }
    catch (e) { GA.err = e.data || { code: "ERROR", message: e.message }; log("✗ " + e.message, true, GA.err) }
    await gaLoadSrv(); render(true)
  },
});
async function gaLoadSrv() { try { GA.srv = await api(`/api/sessions/${SID}/serving`) } catch { GA.srv = null } }
