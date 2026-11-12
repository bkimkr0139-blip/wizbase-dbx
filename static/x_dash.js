"use strict";
/* x_dash.js: Dashboards(UI-05d) · Lakeflow Designer(UI-09d) · Genie Code(SQL Editor 패널). 교육용 시뮬레이션.
   공용 헬퍼(api, esc, table, badge, scBtn, SCN, kvTable, pretty, nf, fmtIso, remedyHtml, val, log, toast, render, refresh, hbars, tableView, tipAttr, niceMax, SER, LAST, SID, ST, ME)는 app.js 전역. */
(function () {
  const st = document.createElement("style");
  st.textContent = `.dgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:12px;margin-top:8px}
.dcard{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px;min-width:0;overflow:hidden}
.dcard .dt{font-weight:600;margin-bottom:6px}.dkpi{font-size:34px;font-weight:700;line-height:1.1;margin:6px 0}
.dgrid .dw-table,.dgrid .dw-line{grid-column:1/-1}
.dcard .hb{grid-template-columns:minmax(80px,30%) 1fr 100px}.dcard .hbv{text-align:right;white-space:nowrap}
.dfil{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin:8px 0}.dfil label{font-size:13px}
.dedit{border:1px solid var(--line);border-radius:8px;padding:8px;margin:6px 0}.dedit textarea{width:100%;min-height:70px;font-family:ui-monospace,monospace;font-size:12px;box-sizing:border-box}
.drow{display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin:4px 0}.drow input,.drow select{max-width:190px}
.dchips span{display:inline-block;border:1px solid var(--line);border-radius:12px;padding:1px 8px;margin:2px;font-size:12px}
.dstep{border-left:4px solid var(--vs1);}.dsteph{display:flex;gap:6px;align-items:center;flex-wrap:wrap}
.gcbox textarea{width:100%;min-height:54px;box-sizing:border-box}.gcbox pre{white-space:pre-wrap}
@media (max-width:820px){.dgrid{grid-template-columns:1fr}.dcard .hb{grid-template-columns:minmax(64px,30%) 1fr 90px}.drow input,.drow select{max-width:100%;flex:1 1 140px}.dkpi{font-size:28px}}`;
  document.head.appendChild(st);
})();

(function () {
const rid = p => p + Math.random().toString(36).slice(2, 6);
const WT = { counter: "카운터(KPI)", bar: "막대", line: "선", table: "표" }, AGL = { sum: "합계", count: "개수", avg: "평균", min: "최소", max: "최대" };
let DSH = { cur: null, mode: "view", src: "draft", page: "", filters: {}, data: null, doc: null, list: null, runs: {} };
let DES = { cur: null, doc: null, list: null, val: null, prev: null, run: null, cols: {} };
const GC = window.GC = { open: false, text: "", res: null };
const dp = p => `/api/sessions/${SID}/dash${p}`, ep = p => `/api/sessions/${SID}/designer${p}`;

/* ------------------------------------------------------------------ Dashboards: 차트 */
function dLine(w) {
  const labels = w.labels, vals = w.values, W = 720, H = 220, L = 46, R = 12, T = 12, B = 26, pw = W - L - R, ph = H - T - B, n = labels.length;
  const max = niceMax(Math.max(1, ...vals)), x = i => L + (n <= 1 ? pw / 2 : i * pw / (n - 1)), y = v => T + ph - v / max * ph, f2 = v => nf(+Number(v).toFixed(2));
  const grid = [0, 1, 2, 3, 4].map(k => { const v = max * k / 4, yy = y(v); return `<line x1="${L}" x2="${W - R}" y1="${yy}" y2="${yy}" class="vgrid"/><text x="${L - 6}" y="${yy + 4}" class="vax" text-anchor="end">${f2(v)}</text>` }).join("");
  const step = Math.max(1, Math.ceil(n / 8)), xl = labels.map((d, i) => i % step === 0 ? `<text x="${x(i)}" y="${H - 8}" class="vax" text-anchor="middle">${esc(String(d).slice(0, 10))}</text>` : "").join("");
  const path = `<path d="${vals.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join("")}" fill="none" stroke="var(--vs1)" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>`;
  const hits = labels.map((d, i) => { const ww = n <= 1 ? pw : pw / (n - 1), tip = `<b>${esc(d)}</b><br>${esc(w.label)}: <b>${f2(vals[i])}</b>`;
    return `<g class="hx"><rect x="${(x(i) - ww / 2).toFixed(1)}" y="${T}" width="${ww.toFixed(1)}" height="${ph}" fill="transparent" ${tipAttr(tip)}/><line x1="${x(i).toFixed(1)}" x2="${x(i).toFixed(1)}" y1="${T}" y2="${T + ph}" class="vcross"/><circle cx="${x(i).toFixed(1)}" cy="${y(vals[i]).toFixed(1)}" r="4" fill="var(--vs1)" class="vdot"/></g>` }).join("");
  return `<svg viewBox="0 0 ${W} ${H}" class="vsvg" role="img" aria-label="${esc(w.title)} 선 차트">${grid}${path}${hits}${xl}</svg>`;
}
function dWidget(w) {
  const head = `<div class="dcard dw-${w.type}"><div class="dt">${esc(w.title)}</div>`;
  if (w.status !== "OK") return `${head}<div class="mute">${esc(w.message || w.status)}</div></div>`;
  if (w.type === "counter") return `${head}<div class="dkpi" ${tipAttr(`<b>${esc(w.label)}</b><br>${nf(w.value)}`)}>${w.value === null ? "–" : nf(w.value)}</div><div class="mute">${esc(w.label)} · ${nf(w.rows_used)}행 기준</div></div>`;
  if (w.type === "table") return `${head}${table(w.columns, w.rows, true)}<div class="mute">총 ${nf(w.total_rows)}행 중 ${w.rows.length}행 표시(열은 12개까지)</div></div>`;
  const tv = tableView([w.x, w.label], w.labels.map((l, i) => [l, w.values[i]]));
  if (w.type === "bar") return `${head}${hbars(w.labels.map((l, i) => [l === "" ? "(빈 값)" : l, Math.abs(w.values[i]) >= 1000 ? Math.round(w.values[i]) : +Number(w.values[i]).toFixed(2)]))}${w.truncated ? `<div class="mute">상위 20개만 표시(${w.truncated}개 생략)</div>` : ""}${tv}</div>`;
  return `${head}${w.labels.length ? dLine(w) : '<div class="mute">행이 없습니다.</div>'}${w.truncated ? `<div class="mute">200개 초과 ${w.truncated}개 생략</div>` : ""}${tv}</div>`;
}

/* ------------------------------------------------------------------ Dashboards: 상태/수집 */
function dashCollect() {
  const d = DSH.doc; if (!d || DSH.mode !== "edit") return;
  d.name = val("dname") ?? d.name;
  d.pages.forEach((p, i) => { p.name = val("pgn_" + i) ?? p.name });
  d.datasets.forEach((s, i) => { s.name = val("dsn_" + i) ?? s.name; s.sql = val("dss_" + i) ?? s.sql });
  d.widgets.forEach((w, i) => { w.type = val("wt_" + i) ?? w.type; w.dataset = val("wd_" + i) ?? w.dataset; w.x = val("wx_" + i) ?? w.x; w.y = val("wy_" + i) ?? w.y; w.agg = val("wa_" + i) ?? w.agg; w.title = val("wn_" + i) ?? w.title; w.page = val("wp_" + i) ?? w.page });
  d.filters.forEach((f, i) => { f.column = val("fc_" + i) ?? f.column; f.label = val("fl_" + i) ?? f.label });
  d.refresh = { strategy: val("rfs") ?? d.refresh.strategy, note: val("rfn") ?? d.refresh.note };
}
async function dashSave() {
  dashCollect(); const d = DSH.doc;
  const r = await api(dp(`/${DSH.cur}/save`), { body: { name: d.name, pages: d.pages, datasets: d.datasets, widgets: d.widgets, filters: d.filters, refresh: d.refresh } });
  DSH.doc = r;
}
async function dashData() {
  if (DSH.src === "published" && !(DSH.doc && DSH.doc.published)) DSH.src = "draft";
  DSH.data = await api(dp(`/${DSH.cur}/data`), { body: { source: DSH.src, filters: DSH.filters } });
  const pages = DSH.data.pages; if (!pages.some(p => p.id === DSH.page)) DSH.page = pages[0]?.id || "";
}
async function dashReload() { DSH.doc = await api(dp("/" + DSH.cur)); await dashData(); }
const dsCols = (d, id) => ((d.results || {})[id] || {}).columns || [];

/* ------------------------------------------------------------------ Dashboards: 화면 */
function dashEditHtml(d) {
  const opts = (arr, cur) => arr.map(([v, l]) => `<option value="${esc(v)}" ${cur === v ? "selected" : ""}>${esc(l)}</option>`).join("");
  const dsOpt = d.datasets.map(s => [s.id, s.name]), pgOpt = d.pages.map(p => [p.id, p.name]);
  return `<div class="card"><b>이름</b> <input id="dname" value="${esc(d.name)}" maxlength="60">
    <h3>페이지</h3>${d.pages.map((p, i) => `<div class="drow"><input id="pgn_${i}" value="${esc(p.name)}" maxlength="30">${d.pages.length > 1 ? `<button class="ghost" data-a="dashdelpage" data-i="${i}">삭제</button>` : ""}</div>`).join("")}<button class="ghost" data-a="dashaddpage">+ 페이지</button>
    <h3>데이터셋(SQL)</h3><div class="sub">SELECT/WITH 한 문장만 가능. 결과는 최대 500행이 저장되고 위젯 집계는 이 행들만 대상으로 합니다.</div>
    ${d.datasets.map((s, i) => { const r = (d.results || {})[s.id], run = DSH.runs[s.id]; return `<div class="dedit"><div class="drow"><input id="dsn_${i}" value="${esc(s.name)}" maxlength="40" placeholder="이름"><button data-a="dashrun" data-i="${i}">▶ 실행</button><button class="ghost" data-a="dashdelds" data-i="${i}">삭제</button>
        ${r ? (r.status === "ok" ? badge(`성공 ${nf(r.row_count)}행${r.truncated ? " (500행 한도)" : ""}`, "ok") : badge("실패", "bad")) : badge("미실행", "w")}</div>
      <textarea id="dss_${i}" spellcheck="false" placeholder="SELECT ... FROM food_dev.gold.v_order_overview">${esc(s.sql)}</textarea>
      ${r && r.status !== "ok" && r.error ? remedyHtml(r.error) : ""}${r && r.status === "ok" ? `<div class="mute">열: ${r.columns.map(esc).join(", ")}</div>${run ? table(r.columns, run, true) : ""}` : ""}</div>` }).join("")}
    <button class="ghost" data-a="dashaddds" ${d.datasets.length >= 6 ? "disabled" : ""}>+ 데이터셋</button>
    <h3>위젯</h3>${d.widgets.map((w, i) => `<div class="dedit"><div class="drow"><select id="wt_${i}">${opts(Object.entries(WT), w.type)}</select><select id="wd_${i}">${opts(dsOpt, w.dataset)}</select>
      <input id="wx_${i}" value="${esc(w.x)}" placeholder="x(그룹) 열" list="cl_${i}"><input id="wy_${i}" value="${esc(w.y)}" placeholder="y(값) 열" list="cl_${i}"><datalist id="cl_${i}">${dsCols(d, w.dataset).map(c => `<option value="${esc(c)}">`).join("")}</datalist>
      <select id="wa_${i}">${opts(Object.entries(AGL), w.agg)}</select><input id="wn_${i}" value="${esc(w.title)}" placeholder="제목" maxlength="60"><select id="wp_${i}">${opts(pgOpt, w.page)}</select><button class="ghost" data-a="dashdelw" data-i="${i}">삭제</button></div></div>`).join("")}
    <button class="ghost" data-a="dashaddw" ${!d.datasets.length || d.widgets.length >= 16 ? "disabled" : ""}>+ 위젯</button>
    <h3>필터</h3><div class="sub">드롭다운 값 목록은 열 이름이 같은 모든 데이터셋에 적용됩니다.</div>
    ${d.filters.map((f, i) => `<div class="drow"><input id="fc_${i}" value="${esc(f.column)}" placeholder="열 이름"><input id="fl_${i}" value="${esc(f.label)}" placeholder="표시 이름"><button class="ghost" data-a="dashdelf" data-i="${i}">삭제</button></div>`).join("")}<button class="ghost" data-a="dashaddf" ${d.filters.length >= 4 ? "disabled" : ""}>+ 필터</button>
    <h3>새로 고침 전략(표시만)</h3><div class="drow"><select id="rfs">${opts([["manual", "수동"], ["scheduled", "예약(표시만)"]], d.refresh.strategy)}</select><input id="rfn" value="${esc(d.refresh.note)}" placeholder="메모" style="min-width:260px"></div>
    <div class="sub">예약 새로 고침은 기록만 하며 실행되지 않습니다. 게시 시점과 [모든 데이터셋 실행] 때만 데이터를 새로 읽습니다.</div>
    <div class="row"><button data-a="dashsave">저장</button><button class="sec" data-a="dashmode" data-m="view">보기로</button></div></div>`;
}
function dashViewHtml(d) {
  const D = DSH.data; if (!D) return "";
  const pub = !!d.published, ws = D.widgets.filter(w => w.page === DSH.page);
  const fil = D.filters.length ? `<div class="dfil">${D.filters.map(f => `<label>${esc(f.label)} <select data-col="${esc(f.column)}" onchange="H.dashfilter(this)"><option value="">전체</option>${f.options.map(o => `<option value="${esc(o)}" ${DSH.filters[f.column] === o ? "selected" : ""}>${esc(o === "" ? "(빈 값)" : o)}</option>`).join("")}</select>${f.applies_to.length ? "" : ' <span class="mute">(적용 대상 없음 — 데이터셋 실행 필요)</span>'}</label>`).join("")}</div>` : "";
  const dsl = D.datasets.map(x => `${esc(x.name)}: ${x.status === "ok" ? `${nf(x.row_count)}행${x.truncated ? "(500행 한도)" : ""} · ${esc(fmtIso(x.at))}` : x.status ? "실패" : "미실행"}`).join(" · ");
  return `<div class="vfilters">${D.pages.map(p => `<button class="${p.id === DSH.page ? "primary" : "ghost"}" data-a="dashpage" data-k="${esc(p.id)}">${esc(p.name)}</button>`).join("")}</div>${fil}
    <div class="sub">${D.source === "published" ? `게시본(${esc(fmtIso(D.published_at))} 시점 스냅샷 — 초안을 고쳐도 바뀌지 않음)` : "초안(저장된 정의 + 마지막 실행 결과)"} · ${dsl || "데이터셋 없음"}</div>
    <div class="dgrid">${ws.length ? ws.map(dWidget).join("") : '<div class="mute">이 페이지에 위젯이 없습니다. 편집에서 추가하세요.</div>'}</div>
    ${D.datasets.some(x => x.status === "failed") ? `<div class="card">${D.datasets.filter(x => x.status === "failed" && x.error).map(x => `<b>${esc(x.name)}</b>${remedyHtml(x.error)}`).join("")}</div>` : ""}
    <div class="sub">${esc(D.note)}${pub ? ` · 공유: 표시만(이 시뮬레이터는 다른 사용자와 공유하지 않음)` : ""}</div>`;
}
Object.assign(V, {
  async dash() {
    if (!DSH.cur) {
      DSH.list = await api(dp(""));
      const L = DSH.list.items;
      return `<h2>UI-05d Dashboards</h2><div class="sub">AI/BI Dashboards를 본뜬 시뮬레이션입니다. SQL 데이터셋 → 위젯(카운터·막대·선·표) → 필터 → 게시 순서로 만듭니다. 데이터셋은 SQL Editor와 같은 권한·웨어하우스 규칙으로 실행됩니다.</div>
      <div class="card"><div class="drow"><input id="dnew" placeholder="새 대시보드 이름" maxlength="60"><button data-a="dashnew">만들기</button><button class="sec" data-a="dashsample">샘플 대시보드 만들기</button></div><div class="sub">${esc(DSH.list.note)}</div></div>
      <div class="card">${L.length ? table(["이름", "상태", "데이터셋", "위젯", "수정", "열기"], L.map(x => [T(x.name), x.status === "published" ? badge("게시됨" + (x.draft_ahead ? " · 초안이 더 최신" : ""), "ok") : badge("초안", "w"), x.datasets, x.widgets, fmtIso(x.updated_at), `<button data-a="dashopen" data-id="${esc(x.id)}">열기</button> <button class="ghost" data-a="dashdel" data-id="${esc(x.id)}">삭제</button>`])) : '<div class="mute">대시보드가 없습니다. 샘플로 시작해 보세요.</div>'}</div>`;
    }
    if (!DSH.doc || DSH.doc.id !== DSH.cur) await dashReload();
    const d = DSH.doc, pub = d.published, draftAhead = pub && d.updated_at > pub.at;
    const bar = `<div class="vfilters"><button class="ghost" data-a="dashback">← 목록</button><button class="${DSH.mode === "view" && DSH.src === "draft" ? "primary" : "ghost"}" data-a="dashmode" data-m="view">초안 보기</button><button class="${DSH.mode === "edit" ? "primary" : "ghost"}" data-a="dashmode" data-m="edit">편집</button>
      <button class="${DSH.mode === "view" && DSH.src === "published" ? "primary" : "ghost"}" data-a="dashmode" data-m="pub" ${pub ? "" : "disabled"}>게시본 보기</button><button class="sec" data-a="dashrunall">모든 데이터셋 실행</button>
      <button data-a="dashpublish">${pub ? "다시 게시" : "게시"}</button>${pub ? '<button class="ghost" data-a="dashunpublish">게시 취소</button>' : ""}</div>`;
    return `<h2>UI-05d Dashboards</h2><div><b>${esc(d.name)}</b> ${pub ? badge("게시됨 " + fmtIso(pub.at), "ok") : badge("초안", "w")}${draftAhead ? " " + badge("초안이 게시본보다 최신", "w") : ""}</div>${bar}
      ${DSH.mode === "edit" ? dashEditHtml(d) : dashViewHtml(d)}`;
  },
});
Object.assign(H, {
  async dashnew() { const r = await api(dp("/create"), { body: { name: val("dnew") } }); DSH.cur = r.id; DSH.doc = null; DSH.mode = "edit"; DSH.filters = {}; DSH.runs = {}; render(true) },
  async dashsample() { const r = await api(dp("/create"), { body: { sample: true } }); DSH.cur = r.id; DSH.doc = null; DSH.mode = "view"; DSH.src = "draft"; DSH.filters = {}; DSH.runs = {}; log("샘플 대시보드를 만들었습니다. [모든 데이터셋 실행]으로 데이터를 채우세요."); render(true) },
  async dashopen(d) { DSH.cur = d.id; DSH.doc = null; DSH.mode = "view"; DSH.src = "draft"; DSH.filters = {}; DSH.runs = {}; render(true) },
  async dashdel(d) { if (!confirm("이 대시보드를 삭제할까요? 되돌릴 수 없습니다.")) return; await api(dp(`/${d.id}/delete`), { body: {} }); render(true) },
  dashback() { DSH.cur = null; DSH.doc = null; render(true) },
  async dashmode(d) {
    dashCollect(); if (DSH.mode === "edit") await dashSave();
    if (d.m === "pub") { DSH.mode = "view"; DSH.src = "published" } else { DSH.mode = d.m; DSH.src = "draft" }
    if (DSH.mode === "view") await dashData(); render(true)
  },
  dashpage(d) { DSH.page = d.k; render(true) },
  async dashfilter(el) { DSH.filters[el.dataset.col] = el.value; await dashData(); render(true) },
  async dashsave() { await dashSave(); log("대시보드를 저장했습니다."); render(true) },
  dashaddpage() { dashCollect(); DSH.doc.pages.push({ id: rid("p"), name: "페이지 " + (DSH.doc.pages.length + 1) }); render(true) },
  dashdelpage(d) { dashCollect(); const p = DSH.doc.pages.splice(+d.i, 1)[0]; DSH.doc.widgets.forEach(w => { if (w.page === p.id) w.page = DSH.doc.pages[0].id }); render(true) },
  dashaddds() { dashCollect(); DSH.doc.datasets.push({ id: rid("d"), name: "dataset" + (DSH.doc.datasets.length + 1), sql: "" }); render(true) },
  dashdelds(d) { dashCollect(); const s = DSH.doc.datasets.splice(+d.i, 1)[0]; DSH.doc.widgets = DSH.doc.widgets.filter(w => w.dataset !== s.id); render(true) },
  dashaddw() { dashCollect(); const D = DSH.doc; D.widgets.push({ id: rid("w"), type: "bar", dataset: D.datasets[0].id, x: "", y: "", agg: "count", title: "새 위젯", page: D.pages[0].id }); render(true) },
  dashdelw(d) { dashCollect(); DSH.doc.widgets.splice(+d.i, 1); render(true) },
  dashaddf() { dashCollect(); DSH.doc.filters.push({ id: rid("f"), column: "", label: "" }); render(true) },
  dashdelf(d) { dashCollect(); DSH.doc.filters.splice(+d.i, 1); render(true) },
  async dashrun(d) {
    await dashSave(); const s = DSH.doc.datasets[+d.i], r = await api(dp(`/${DSH.cur}/run`), { body: { dataset: s.id } });
    DSH.runs[s.id] = r.status === "ok" ? r.preview : null; log(r.status === "ok" ? `${s.name}: ${r.row_count}행${r.truncated ? " (500행 한도)" : ""}` : "✗ " + (r.error?.message || "실패"), r.status !== "ok", r.error);
    DSH.doc = await api(dp("/" + DSH.cur)); render(true)
  },
  async dashrunall() {
    if (DSH.mode === "edit") await dashSave();
    const r = await api(dp(`/${DSH.cur}/run-all`), { body: {} }), bad = Object.values(r.results).filter(x => x.status !== "ok").length;
    log(bad ? `데이터셋 ${bad}개 실행 실패` : "모든 데이터셋을 실행했습니다.", !!bad); await dashReload(); render(true)
  },
  async dashpublish() {
    if (DSH.mode === "edit") await dashSave();
    try { await api(dp(`/${DSH.cur}/publish`), { body: {} }); log("게시했습니다(게시 시점의 데이터 스냅샷). 초안을 고쳐도 게시본은 바뀌지 않습니다."); DSH.mode = "view"; DSH.src = "published"; await dashReload() }
    catch (e) { log("✗ " + e.message, true, e.data) } render(true)
  },
  async dashunpublish() { await api(dp(`/${DSH.cur}/unpublish`), { body: {} }); DSH.src = "draft"; await dashReload(); render(true) },
});

/* ------------------------------------------------------------------ Genie Code (규칙 기반) — SQL Editor 패널 */
function gcBody() {
  const r = GC.res;
  let out = "";
  if (r) {
    if (r.status === "OK" && r.mode === "generate") out = `<div class="card"><b>${esc(r.title)}</b> ${badge(r.match, "w")}<pre>${esc(r.sql)}</pre><div class="sub">${esc(r.explanation)}</div>${(r.warnings || []).map(w => `<div class="warnc">${esc(w)}</div>`).join("")}<div class="row"><button data-a="gcuse" data-i="-1">SQL Editor에 채우기</button></div></div>`;
    else if (r.mode === "debug") out = `<div class="card"><b>오류 ${esc(r.code || "")}</b> <span class="mute">${esc(r.message || "")}</span>${r.suggestions.map((s, i) => `<div class="dedit"><b>${esc(s.title)}</b><div class="sub">${esc(s.why)}</div>${s.sql ? `<pre>${esc(s.sql)}</pre><button data-a="gcuse" data-i="${i}">SQL Editor에 채우기</button>` : ""}</div>`).join("")}</div>`;
    else out = `<div class="card"><b>${r.status === "EMPTY" ? "질문을 입력하세요" : "SQL을 만들지 못했습니다"}</b><div class="sub">${esc(r.message || "")}</div>${r.examples ? `<div class="dchips">${r.examples.map(x => `<span>${esc(x)}</span>`).join("")}</div>` : ""}</div>`;
    out += `<div class="sub">${esc(r.limits)}</div>`;
  }
  return `<div class="gcbox"><textarea id="gctext" placeholder="예: 상태별 주문 건수 / 가용재고 상위 5개 / orders 테이블 몇 건이야?">${esc(GC.text)}</textarea><div class="row"><button data-a="gcask">SQL 만들기</button><button class="sec" data-a="gcdebug">마지막 오류 고치기</button><span class="mute">실행은 하지 않습니다. 초안을 읽고 직접 실행하세요.</span></div>${out}</div>`;
}
function gcPanel() { return `<details class="card" id="gcp" ${GC.open ? "open" : ""} ontoggle="GC.open=this.open"><summary><b>Genie Code</b> <span class="mute">규칙 기반 도우미(실제 LLM 아님) — 자연어 → SQL 초안, 오류 SQL 수정 제안</span></summary><div id="gcbody">${gcBody()}</div></details>` }
function gcShow() { const el = $("#gcbody"); if (el) el.innerHTML = gcBody() }
Object.assign(H, {
  async gcask() { GC.text = val("gctext") || ""; GC.res = await api(`/api/sessions/${SID}/genie-code`, { body: { text: GC.text } }); gcShow() },
  async gcdebug() {
    const h0 = HIST.sql[0], failed = h0 && h0.err ? h0 : null;          // 가장 최근 실행이 실패했으면 그 SQL·오류를 쓴다(편집기 내용은 다시 그려지며 바뀔 수 있음)
    const err = failed ? failed.err : (LAST.sql?.result?.error || LASTERR); GC.text = val("gctext") || GC.text;
    if (!err) { GC.res = { mode: "generate", status: "EMPTY", message: "고칠 최근 오류가 없습니다. SQL을 실행해 오류가 난 뒤 다시 눌러 보세요.", limits: "" }; gcShow(); return }
    GC.res = await api(`/api/sessions/${SID}/genie-code`, { body: { mode: "debug", sql: failed ? failed.q : (val("sqlbox") || ""), error: err } }); gcShow()
  },
  gcuse(d) { const r = GC.res, i = +d.i, sql = i < 0 ? r.sql : r.suggestions[i].sql; if (!sql) return; const b = $("#sqlbox"); if (b) b.value = sql; LAST.sqlq = sql; log("제안 SQL을 편집기에 채웠습니다. 검토 후 [실행]을 누르세요.") },
});

/* ------------------------------------------------------------------ Lakeflow Designer */
const OPL = { source: "소스(테이블)", filter: "필터", select: "열 선택", join: "조인", aggregate: "집계", sort: "정렬", limit: "행 수 제한", output: "출력(테이블)" };
const csv = s => String(s || "").split(",").map(x => x.trim()).filter(Boolean);
function parseAggs(t) { return csv(t).map(x => { const m = /^(sum|count|avg|min|max)\s*\(\s*([A-Za-z0-9_*]+)\s*\)(?:\s+as\s+([A-Za-z0-9_]+))?$/i.exec(x); return m ? { fn: m[1].toLowerCase(), column: m[2], alias: m[3] || "" } : { fn: x, column: "", alias: "" } }) }
const showAggs = a => (a || []).map(x => `${x.fn}(${x.column || "*"})${x.alias ? " as " + x.alias : ""}`).join(", ");
const showSel = c => (c || []).map(x => typeof x === "string" ? x : (x.alias && x.alias !== x.name ? `${x.name} as ${x.alias}` : x.name)).join(", ");
function parseSel(t) { return csv(t).map(x => { const m = /^([A-Za-z0-9_]+)\s+as\s+([A-Za-z0-9_]+)$/i.exec(x); return m ? { name: m[1], alias: m[2] } : { name: x } }) }
function desCollect() {
  const d = DES.doc; if (!d) return; d.name = val("fname") ?? d.name;
  d.steps = d.steps.map((s, i) => { const g = k => val(`st${i}_${k}`), o = { op: s.op };
    if (s.op === "source") o.table = g("table") ?? s.table;
    if (s.op === "filter") { o.column = g("column"); o.cmp = g("cmp"); o.value = g("value") }
    if (s.op === "select") o.columns = parseSel(g("columns"));
    if (s.op === "join") { o.table = g("table"); o.left_key = g("left_key"); o.right_key = g("right_key"); o.type = g("type") }
    if (s.op === "aggregate") { o.group_by = csv(g("group_by")); o.aggs = parseAggs(g("aggs")) }
    if (s.op === "sort") { o.column = g("column"); o.desc = !!$(`#st${i}_desc`)?.checked }
    if (s.op === "limit") o.n = +g("n");
    if (s.op === "output") o.target = g("target");
    return o });
  const sc = { enabled: !!$("#fsch")?.checked, cron: val("fcron") ?? "" }; d.schedule = sc;
}
async function desSave() { desCollect(); const d = DES.doc; DES.doc = await api(ep(`/${DES.cur}/save`), { body: { name: d.name, steps: d.steps, schedule: d.schedule } }) }
function stepForm(s, i, cols) {
  const dl = cols ? `<datalist id="sc_${i}">${cols.map(c => `<option value="${esc(c)}">`).join("")}</datalist>` : "", L = cols ? ` list="sc_${i}"` : "";
  const inp = (k, ph, v, w) => `<input id="st${i}_${k}" value="${esc(v ?? "")}" placeholder="${ph}"${w ? ` style="width:${w}px;max-width:100%"` : ""}${L}>`;
  const sel = (k, arr, cur) => `<select id="st${i}_${k}">${arr.map(a => `<option ${a === cur ? "selected" : ""}>${esc(a)}</option>`).join("")}</select>`;
  const f = { source: () => inp("table", "catalog.schema.table", s.table, 300), filter: () => inp("column", "열", s.column) + sel("cmp", ["=", "<>", ">", ">=", "<", "<=", "contains", "is null", "is not null"], s.cmp || "=") + inp("value", "값", s.value),
    select: () => inp("columns", "열1, 열2 as 별칭", showSel(s.columns), 320), join: () => inp("table", "조인할 테이블", s.table, 260) + inp("left_key", "왼쪽 키", s.left_key) + inp("right_key", "오른쪽 키", s.right_key) + sel("type", ["inner", "left"], s.type || "inner"),
    aggregate: () => inp("group_by", "그룹 열(쉼표)", (s.group_by || []).join(", "), 220) + inp("aggs", "sum(열) as 별칭, count(*) as n", showAggs(s.aggs), 340), sort: () => inp("column", "열", s.column) + `<label><input type="checkbox" id="st${i}_desc" ${s.desc ? "checked" : ""}> 내림차순</label>`,
    limit: () => `<input id="st${i}_n" type="number" min="1" value="${esc(s.n ?? 20)}" style="width:100px">`, output: () => inp("target", "대상 catalog.schema.table(없으면 새로 만듦·있으면 덮어씀)", s.target, 360) }[s.op]();
  return dl + f;
}
Object.assign(V, {
  async designer() {
    if (!DES.cur) {
      DES.list = await api(ep(""));
      return `<h2>UI-09d Lakeflow Designer</h2><div class="sub">코드 없이 연산자 카드를 쌓아 ETL 흐름을 만드는 시뮬레이션입니다. 카드는 SQL(CTE)로 변환되어 실행되며 결과는 UC 테이블(Delta 이력 포함)로 저장됩니다. 실제 Designer의 시각 캔버스와 Genie Code 생성은 제공하지 않습니다.</div>
      <div class="card"><div class="drow"><input id="fnew" placeholder="새 흐름 이름" maxlength="60"><button data-a="desnew">만들기</button><button class="sec" data-a="dessample">메달리온 샘플 흐름(gold 요약)</button></div><div class="sub">${esc(DES.list.note)}</div></div>
      <div class="card">${DES.list.items.length ? table(["이름", "단계", "마지막 실행", "열기"], DES.list.items.map(x => [T(x.name), x.steps, x.last_run ? `${fmtIso(x.last_run.at)} → ${x.last_run.table} (${nf(x.last_run.rows)}행)` : "-", `<button data-a="desopen" data-id="${esc(x.id)}">열기</button> <button class="ghost" data-a="desdel" data-id="${esc(x.id)}">삭제</button>`])) : '<div class="mute">흐름이 없습니다. 샘플로 시작해 보세요.</div>'}</div>`;
    }
    if (!DES.doc || DES.doc.id !== DES.cur) DES.doc = await api(ep("/" + DES.cur));
    const d = DES.doc, sc = DES.val && DES.val.step_columns;
    const cards = d.steps.map((s, i) => `<div class="dedit dstep"><div class="dsteph"><b>${i + 1}. ${OPL[s.op]}</b>${i > 0 ? `<button class="ghost" data-a="desmove" data-i="${i}" data-d="-1" ${i < 2 ? "disabled" : ""}>↑</button><button class="ghost" data-a="desmove" data-i="${i}" data-d="1" ${i >= d.steps.length - 1 ? "disabled" : ""}>↓</button><button class="ghost" data-a="desdelstep" data-i="${i}">삭제</button><button class="ghost" data-a="despreview" data-i="${i}">여기까지 미리보기</button>` : ""}</div>
      <div class="drow">${stepForm(s, i, sc && i > 0 ? sc[i - 1] : null)}</div>${sc && sc[i] ? `<div class="dchips mute">이 단계의 열: ${sc[i].map(c => `<span>${esc(c)}</span>`).join("")}</div>` : ""}</div>`).join("");
    const e = x => x && x.error ? `<div class="card">${remedyHtml(x.error)}${x.error.step !== null && x.error.step !== undefined ? `<div class="sub">문제가 있는 단계: ${x.error.step + 1}</div>` : ""}</div>` : "";
    return `<h2>UI-09d Lakeflow Designer</h2><div class="vfilters"><button class="ghost" data-a="desback">← 목록</button></div>
      <div class="card"><b>이름</b> <input id="fname" value="${esc(d.name)}" maxlength="60">${d.tip ? `<div class="sub">${esc(d.tip)}</div>` : ""}
      <h3>연산자 카드</h3>${cards}
      <div class="drow"><select id="newop">${["filter", "select", "join", "aggregate", "sort", "limit", "output"].map(o => `<option value="${o}">${OPL[o]}</option>`).join("")}</select><button class="ghost" data-a="desadd">+ 카드 추가</button></div>
      <h3>스케줄(표시만)</h3><div class="drow"><label><input type="checkbox" id="fsch" ${d.schedule.enabled ? "checked" : ""}> 사용</label><input id="fcron" value="${esc(d.schedule.cron)}" placeholder="예: 0 6 * * *"> ${badge("실행되지 않음", "w")}</div>
      <div class="row"><button data-a="dessave">저장</button><button class="sec" data-a="desvalidate">검증</button><button class="sec" data-a="despreview" data-i="-1">미리보기(20행)</button><button data-a="desrun">실행(출력 테이블 생성)</button></div></div>
      ${e(DES.val)}${DES.val && DES.val.status === "ok" ? `<div class="card"><b>검증 통과</b> — 결과 열: ${DES.val.columns.map(esc).join(", ")}<h3>생성된 SQL</h3><pre>${esc(DES.val.sql)}</pre></div>` : ""}
      ${e(DES.prev)}${DES.prev && DES.prev.status === "ok" ? `<div class="card"><b>미리보기</b>${table(DES.prev.columns, DES.prev.rows, true)}<pre>${esc(DES.prev.sql)}</pre></div>` : ""}
      ${e(DES.run)}${DES.run && DES.run.status === "ok" ? `<div class="card">${badge("성공", "ok")} <b>${esc(DES.run.table)}</b> ${nf(DES.run.rows)}행 — ${esc(DES.run.note)}<div class="row">${scBtn(SCN("Catalog에서 보기", "cat"))}${scBtn(SCN("DESCRIBE HISTORY", "sql", { sqlbox: `DESCRIBE HISTORY ${DES.run.table}` }))}</div></div>` : ""}`;
  },
});
Object.assign(H, {
  async desnew() { const r = await api(ep("/create"), { body: { name: val("fnew") } }); DES.cur = r.id; DES.doc = null; DES.val = DES.prev = DES.run = null; render(true) },
  async dessample() { const r = await api(ep("/create"), { body: { sample: true } }); DES.cur = r.id; DES.doc = null; DES.val = DES.prev = DES.run = null; render(true) },
  async desopen(d) { DES.cur = d.id; DES.doc = null; DES.val = DES.prev = DES.run = null; render(true) },
  async desdel(d) { if (!confirm("이 흐름을 삭제할까요?")) return; await api(ep(`/${d.id}/delete`), { body: {} }); render(true) },
  desback() { DES.cur = null; DES.doc = null; render(true) },
  desadd() { desCollect(); const op = val("newop"), base = { filter: { column: "", cmp: "=", value: "" }, select: { columns: [] }, join: { table: "", left_key: "", right_key: "", type: "inner" }, aggregate: { group_by: [], aggs: [] }, sort: { column: "", desc: false }, limit: { n: 20 }, output: { target: "" } }[op];
    const st = DES.doc.steps; const o = { op, ...base }; if (op === "output") st.push(o); else { const k = st.findIndex(s => s.op === "output"); st.splice(k < 0 ? st.length : k, 0, o) } render(true) },
  desdelstep(d) { desCollect(); DES.doc.steps.splice(+d.i, 1); DES.val = null; render(true) },
  desmove(d) { desCollect(); const i = +d.i, j = i + +d.d, st = DES.doc.steps; if (j < 1 || j >= st.length || st[i].op === "output" || st[j].op === "output") return; [st[i], st[j]] = [st[j], st[i]]; render(true) },
  async dessave() { await desSave(); log("흐름을 저장했습니다."); render(true) },
  async desvalidate() { await desSave(); DES.val = await api(ep(`/${DES.cur}/validate`), { body: {} }); if (DES.val.status !== "ok") log("✗ " + DES.val.error.message, true, DES.val.error); render(true) },
  async despreview(d) { await desSave(); DES.prev = await api(ep(`/${DES.cur}/preview`), { body: { upto: +d.i >= 0 ? +d.i : undefined } }); if (DES.prev.status !== "ok") log("✗ " + DES.prev.error.message, true, DES.prev.error); render(true) },
  async desrun() { await desSave(); DES.run = await api(ep(`/${DES.cur}/run`), { body: {} }); log(DES.run.status === "ok" ? `${DES.run.table}: ${DES.run.rows}행 저장` : "✗ " + DES.run.error.message, DES.run.status !== "ok", DES.run.error); DES.doc = null; render(true) },
});
window.gcPanel = gcPanel;
})();
