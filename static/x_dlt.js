"use strict";
/* x_dlt.js: 선언형 파이프라인(UI-09c) — 스트리밍 테이블·구체화 뷰·expectations·AUTO CDC(SCD1) 시뮬레이션. 공용 헬퍼는 app.js 전역을 쓴다. */
const DLT = { id: null, src: "", srcOf: null, name: "", schema: "gold", creating: false, msg: null, sampleSchema: "gold", busy: false };
const DLT_KIND = { STREAMING_TABLE: "스트리밍 테이블", MATERIALIZED_VIEW: "구체화 뷰", TEMP_VIEW: "임시 뷰", "STREAMING_TABLE(AUTO CDC)": "스트리밍 테이블(AUTO CDC)" };
const DLT_ACT = { WARN: "경고(행 유지)", DROP: "행 제외", FAIL: "업데이트 중단" };
const DLT_ST = { COMPLETED: ["성공", "ok"], FAILED: ["실패", "bad"], SKIPPED: ["건너뜀", "w"], RUNNING: ["실행 중", "w"], INLINE: ["펼침", ""] };

Object.assign(REMEDY, {
  UNSUPPORTED_DLT_SYNTAX: e => ({ why: "이 시뮬레이터가 지원하는 선언형 파이프라인 문법이 아닙니다(실제 Databricks에서는 될 수 있습니다). 메시지의 줄 번호 근처를 확인하세요.", steps: ["위 [예제 템플릿]을 불러와 형식을 비교합니다.", "스트리밍 테이블은 FROM STREAM(원본), 구체화 뷰는 일반 SELECT 입니다.", "컬럼 정의·PARTITIONED BY·SCD Type 2 등은 미지원입니다."], actions: [SCN("파이프라인 화면으로", "dpipe")] }),
  STREAMING_SOURCE_CHANGED: e => ({ why: "스트리밍 테이블은 원본이 append-only(행 추가만)일 때만 증분 처리할 수 있습니다. 원본에서 UPDATE/DELETE/덮어쓰기/RESTORE 가 일어나 안전하게 이어 갈 수 없습니다.", steps: ["원본 테이블의 History 탭(또는 DESCRIBE HISTORY)에서 어떤 변경이 있었는지 확인합니다.", "의도한 변경이면 [전체 새로고침]으로 스트리밍 테이블을 처음부터 다시 만듭니다.", "의도하지 않았다면 RESTORE 로 되돌린 뒤 전체 새로고침을 합니다(RESTORE 도 변경으로 간주됩니다)."], actions: [SCN("파이프라인 화면으로", "dpipe"), SCN("Catalog에서 History 보기", "cat")] }),
  EXPECTATION_FAILED: e => ({ why: "ON VIOLATION FAIL UPDATE 로 지정한 expectation 을 위반하는 행이 있어 업데이트를 중단했습니다. 해당 데이터셋은 갱신되지 않았습니다.", steps: ["이벤트 로그의 expectation 표에서 위반 행 수를 확인합니다.", "원본 데이터를 고치거나, 조치를 DROP ROW(제외)·기본(경고)으로 바꿉니다.", "다시 [업데이트 실행]합니다."], actions: [SCN("파이프라인 화면으로", "dpipe")] }),
  DLT_CYCLE: e => ({ why: "데이터셋끼리 서로를 참조해 실행 순서를 정할 수 없습니다.", steps: ["오류 메시지의 순환 경로(a → b → a)를 확인합니다.", "한 데이터셋이 다른 원본을 읽도록 바꿔 순환을 끊습니다."], actions: [SCN("파이프라인 화면으로", "dpipe")] }),
  DLT_DUPLICATE_DATASET: e => ({ why: "같은 이름의 데이터셋(또는 흐름)이 두 번 정의되었습니다.", steps: ["이름이 겹치는 두 문장 중 하나의 이름을 바꾸거나 지웁니다."], actions: [SCN("파이프라인 화면으로", "dpipe")] }),
  STREAM_FROM_MATERIALIZED_VIEW: e => ({ why: "구체화 뷰는 매번 전체를 다시 계산하므로 append-only 가 아니어서 스트리밍 원본이 될 수 없습니다.", steps: ["원본을 스트리밍 테이블로 바꾸거나, 아래 단계도 구체화 뷰로 만들어 STREAM()을 빼세요."], actions: [SCN("파이프라인 화면으로", "dpipe")] }),
  DLT_TARGET_OUTSIDE_SCHEMA: e => ({ why: "파이프라인은 자신의 대상 catalog.schema 안에만 데이터셋을 만듭니다.", steps: ["이름만 쓰거나, 대상 schema 와 같은 이름을 씁니다.", "다른 schema 에 만들려면 새 파이프라인을 그 schema 대상으로 만듭니다."], actions: [SCN("파이프라인 화면으로", "dpipe")] }),
  COLUMN_NOT_FOUND: e => ({ why: "KEYS/SEQUENCE BY/COLUMNS 에 쓴 컬럼이 원본에 없습니다.", steps: ["원본 테이블의 컬럼 이름을 Catalog 에서 확인합니다.", "철자와 대소문자를 고칩니다."], actions: [SCN("Catalog에서 컬럼 확인", "cat"), SCN("파이프라인 화면으로", "dpipe")] }),
  DLT_CDC_KEY_EXCLUDED: e => ({ why: "결과 테이블에는 키 컬럼이 있어야 행을 구분할 수 있습니다.", steps: ["COLUMNS * EXCEPT (…) 목록에서 키 컬럼을 뺍니다."], actions: [SCN("파이프라인 화면으로", "dpipe")] }),
  DLT_BATCH_TOO_LARGE: e => ({ why: "시뮬레이터는 한 번에 CDC 이벤트 500행까지만 처리합니다.", steps: ["원본에 넣는 이벤트를 나눠서 업데이트를 여러 번 실행합니다."], actions: [SCN("파이프라인 화면으로", "dpipe")] }),
  STREAMING_SOURCE_INVALID: e => ({ why: "스트리밍 원본은 뷰가 아니라 테이블이어야 합니다.", steps: ["뷰 대신 그 뷰의 기반 테이블을 STREAM()으로 읽습니다."], actions: [SCN("파이프라인 화면으로", "dpipe")] }),
  EMPTY_PIPELINE: e => ({ why: "파이프라인 SQL이 비어 있습니다.", steps: ["[예제 템플릿]을 불러와 시작합니다."], actions: [SCN("파이프라인 화면으로", "dpipe")] }),
  PIPELINE_LIMIT: e => ({ why: "세션당 파이프라인 수 한도에 도달했습니다.", steps: ["쓰지 않는 파이프라인을 삭제합니다(만들어진 테이블은 남습니다)."], actions: [SCN("파이프라인 화면으로", "dpipe")] }),
  TARGET_LOCKED: e => ({ why: "업데이트를 실행한 파이프라인은 대상 schema 를 바꿀 수 없습니다.", steps: ["새 파이프라인을 원하는 schema 대상으로 만듭니다."], actions: [SCN("파이프라인 화면으로", "dpipe")] }),
});

function dltExpText(ex) { return (ex || []).map(e => `${esc(e.name)}: 통과 ${nf(e.passed)}·실패 ${nf(e.failed)} <span class="mute">(${esc(DLT_ACT[e.action] || e.action)})</span>`).join("<br>") || '<span class="mute">-</span>' }
function dltStBadge(s) { const x = DLT_ST[s] || [s || "-", ""]; return badge(x[0], x[1]) }

// 의존 그래프(SVG): 왼쪽 원본 → 오른쪽 결과. 스트리밍 간선은 굵은 실선, 배치 간선은 가는 점선.
function dltGraph(plan, datasets) {
  const nodes = plan.nodes.filter(n => n.kind !== "TEMP_VIEW"), temps = plan.nodes.filter(n => n.kind === "TEMP_VIEW"), by = {};
  nodes.forEach(n => by[n.name] = n);
  const fqs = new Set(nodes.map(n => n.fq)), ext = [];
  nodes.forEach(n => (n.stream || []).forEach(s => { if (!fqs.has(s) && !ext.includes(s)) ext.push(s) }));
  const depth = {}, dep = n => depth[n] ?? (depth[n] = 1 + Math.max(-1, ...((by[n].deps || []).map(dep))));
  nodes.forEach(n => dep(n.name));
  const layers = {}; ext.forEach(e => (layers[0] = layers[0] || []).push({ id: "ext:" + e, label: e.split(".").slice(-1)[0], sub: "원본 테이블", ext: true }));
  nodes.forEach(n => (layers[depth[n.name] + 1] = layers[depth[n.name] + 1] || []).push({ id: n.name, label: n.name, sub: DLT_KIND[n.kind] || n.kind, kind: n.kind }));
  const W = 176, Hh = 46, GX = 70, GY = 16, cols = Object.keys(layers).map(Number).sort((a, b) => a - b), pos = {};
  let maxRows = 1; cols.forEach(c => { maxRows = Math.max(maxRows, layers[c].length); layers[c].forEach((n, i) => pos[n.id] = { x: 10 + c * (W + GX), y: 10 + i * (Hh + GY) }) });
  const width = 20 + cols.length * (W + GX) - GX, height = 20 + maxRows * (Hh + GY) - GY, rowCount = {};
  const rows = {}; (datasets || []).forEach(d => rows[d.name] = d.rows);
  let edges = "";
  nodes.forEach(n => {
    const to = pos[n.name], srcs = [];
    (n.deps || []).forEach(d => srcs.push([d, (n.stream || []).includes(by[d].fq)]));
    (n.stream || []).forEach(s => { if (!fqs.has(s)) srcs.push(["ext:" + s, true]) });
    srcs.forEach(([s, st]) => { const f = pos[s]; if (!f) return; const x1 = f.x + W, y1 = f.y + Hh / 2, x2 = to.x, y2 = to.y + Hh / 2, mx = (x1 + x2) / 2; edges += `<path d="M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2 - 4},${y2}" fill="none" stroke="currentColor" stroke-width="${st ? 2.2 : 1.4}" ${st ? "" : 'stroke-dasharray="4 3"'} opacity=".7" marker-end="url(#dltarr)"/>` });
  });
  const box = n => { const p = pos[n.id], rc = rows[n.id]; return `<g><rect x="${p.x}" y="${p.y}" width="${W}" height="${Hh}" rx="8" fill="var(--panel)" stroke="${n.ext ? "var(--mute)" : n.kind === "MATERIALIZED_VIEW" ? "#8a5cf6" : "#2f6fdb"}" stroke-width="2" ${n.ext ? 'stroke-dasharray="5 3"' : ""}/><text x="${p.x + 10}" y="${p.y + 19}" font-size="13" font-weight="600" fill="currentColor">${esc(n.label.length > 20 ? n.label.slice(0, 19) + "…" : n.label)}</text><text x="${p.x + 10}" y="${p.y + 36}" font-size="11" fill="currentColor" opacity=".65">${esc(n.sub)}${rc !== undefined && rc !== null ? " · " + nf(rc) + "행" : ""}</text></g>` };
  const all = cols.flatMap(c => layers[c]);
  return `<div class="tw"><svg viewBox="0 0 ${width} ${height}" width="${Math.max(width, 320)}" height="${height}" role="img" aria-label="파이프라인 의존 그래프: ${nodes.map(n => esc(n.name)).join(", ")}" style="color:var(--ink)"><defs><marker id="dltarr" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="currentColor" opacity=".7"/></marker></defs>${edges}${all.map(box).join("")}</svg></div>
  <div class="sub">굵은 선 = 스트리밍(STREAM) 읽기 · 점선 = 배치 읽기 · 점선 테두리 = 파이프라인 밖 원본 테이블 · 보라 테두리 = 구체화 뷰${temps.length ? ` · 임시 뷰(${temps.map(t => esc(t.name)).join(", ")})는 게시되지 않고 참조하는 데이터셋 안에 펼쳐집니다` : ""}</div>`;
}

function dltEventsHtml(u) {
  const ev = u.events || [];
  return `<details ${u === DLT.firstUpd ? "open" : ""} class="qhrow"><summary>${dltStBadge(u.state)} <b>${u.mode === "full_refresh" ? "전체 새로고침" : "업데이트"}</b> <span class="mute">${esc(fmtIso(u.at))} · ${u.duration_ms ?? 0}ms · ${esc(u.principal || "")}</span>${u.error ? `<br><span class="bad">${esc(u.error.code)}</span> ${esc(u.error.message)}` : ""}</summary>
    ${ev.length ? table(["데이터셋", "종류", "상태", "입력 행", "기록 후 행", "expectations", "설명"], ev.map(e => [esc(e.dataset), esc(DLT_KIND[e.kind] || e.kind), dltStBadge(e.state), e.rows_in ?? "-", e.rows_out ?? "-", dltExpText(e.expectations), esc((e.note || "") + (e.cdc ? ` [이벤트 ${e.cdc.events}·업서트 ${e.cdc.upserts}·삭제 ${e.cdc.deletes}·무시 ${e.cdc.ignored_old}]` : "") + (e.dropped ? ` [제외 ${e.dropped}행]` : ""))])) : '<div class="mute">이벤트 없음(계획 단계에서 실패)</div>'}
    ${u.error ? remedyHtml(u.error) : ""}</details>`;
}

Object.assign(V, {
  async dpipe() {
    const L = await api(`/api/sessions/${SID}/dpipes`);
    if (DLT.id && !L.pipelines.some(p => p.id === DLT.id)) DLT.id = null;
    if (!DLT.id && L.pipelines.length) DLT.id = L.pipelines[0].id;
    const d = DLT.id ? await api(`/api/sessions/${SID}/dpipes/${DLT.id}`) : null;
    if (d && DLT.srcOf !== d.pipeline.id) { DLT.src = d.pipeline.source; DLT.srcOf = d.pipeline.id }
    if (!d) DLT.srcOf = null;
    DLT.firstUpd = d && d.updates[0];
    const sel = `<select id="dltsel" onchange="H.dltpick({id:this.value})">${L.pipelines.map(p => `<option value="${esc(p.id)}" ${p.id === DLT.id ? "selected" : ""}>${esc(p.name)} (${esc(p.catalog)}.${esc(p.schema)})${p.last_state ? " · " + (DLT_ST[p.last_state] || [p.last_state])[0] : ""}</option>`).join("")}</select>`;
    const tplBtns = Object.entries(L.templates).map(([k, t]) => `<button class="ghost" data-a="dlttpl" data-k="${k}">${esc(t.title)}</button>`).join("");
    const msg = DLT.msg ? `<div class="card">${DLT.msg.error ? remedyHtml(DLT.msg.error) : `${badge("성공", "ok")} ${esc(DLT.msg.table)} · 배치 ${DLT.msg.batch} · ${DLT.msg.rows}행 <span class="mute">${esc(DLT.msg.note || "")}</span>`}</div>` : "";
    const plan = d && d.plan;
    return `<h2>UI-09c 선언형 파이프라인</h2>
    <div class="sub">Spark Declarative Pipelines 문법(스트리밍 테이블·구체화 뷰·expectations·AUTO CDC)을 SQL로 작성해 업데이트를 실행합니다. ${lv(L.evidence_level)} 근거: Academy 코스 개요 조회(2026-11-12, 레슨 본문 미조회). <b>시뮬레이션이며 문법은 일부만 지원합니다.</b>
      <details><summary>지원 범위와 한계</summary><ul>${L.limits.map(x => `<li>${esc(x)}</li>`).join("")}</ul></details></div>
    <div class="card"><b>파이프라인</b>
      <div class="vfilters">${L.pipelines.length ? sel : '<span class="mute">아직 없습니다. [새 파이프라인]을 눌러 만드세요.</span>'}<button class="ghost" data-a="dltnewtoggle">새 파이프라인</button>${d ? '<button class="ghost" data-a="dltdel">삭제</button>' : ""}</div>
      ${DLT.creating ? `<div class="vfilters"><label>이름 <input id="dltname" value="${esc(DLT.name)}" placeholder="예: orders_pipeline" style="width:170px"></label><label>대상 schema <input id="dltschema" value="${esc(DLT.schema)}" style="width:110px"></label><button data-a="dltcreate">만들기</button><span class="mute">대상: ${esc(L.default.catalog)}.&lt;schema&gt; — 데이터셋이 이 schema의 일반 UC 테이블로 만들어집니다.</span></div>` : ""}
      ${d ? `<div class="sub">대상 <code>${esc(d.pipeline.catalog)}.${esc(d.pipeline.schema)}</code> · 업데이트 ${d.updates.length}회 기록</div>` : ""}</div>
    <div class="card"><b>샘플 원본(합성 데이터)</b> <span class="mute">연습할 원본 테이블을 만들고, 새 행을 넣어 증분 처리를 확인합니다.</span>
      <div class="vfilters"><label>schema <input id="dltss" value="${esc(DLT.sampleSchema)}" style="width:100px" oninput="DLT.sampleSchema=this.value"></label>
      <button data-a="dltsample" data-kind="orders">주문 원본 만들기</button><button class="ghost" data-a="dltsample" data-kind="orders" data-append="1">주문 추가 배치 넣기</button>
      <button data-a="dltsample" data-kind="cdc">CDC 이벤트 원본 만들기</button><button class="ghost" data-a="dltsample" data-kind="cdc" data-append="1">CDC 추가 배치 넣기</button></div>
      <div class="sub">주문 원본에는 NULL id·음수 금액 행이, CDC 추가 배치에는 오래된 이벤트가 일부러 섞여 있습니다(expectations·역순 도착 연습).</div></div>
    ${msg}
    ${d ? `<div class="card"><b>파이프라인 SQL</b><div class="vfilters">${tplBtns}</div>
      <textarea id="dltsrc" spellcheck="false" oninput="DLT.src=this.value" style="min-height:240px;font-family:monospace">${esc(DLT.src)}</textarea>
      <div class="vfilters"><button data-a="dltsave" class="ghost">저장</button><button data-a="dltrun">▶ 업데이트 실행</button><button data-a="dltfull" class="ghost" title="오프셋·CDC 상태를 지우고 처음부터 다시 만듭니다">⟳ 전체 새로고침</button></div>
      ${plan && !plan.ok ? remedyHtml(plan.error) : ""}</div>
      ${plan && plan.ok ? `<div class="card"><b>의존 그래프</b> <span class="mute">실행 순서: ${plan.order.map(esc).join(" → ")}</span>${dltGraph(plan, d.datasets)}</div>
      <div class="card"><b>데이터셋</b>${table(["이름", "종류", "행 수", "최근 상태", "expectations(최근)", "설명"], d.datasets.map(x => [x.fq ? `<a href="#" data-a="dltopen" data-n="${esc(x.fq)}">${esc(x.name)}</a>` : esc(x.name), esc(DLT_KIND[x.kind] || x.kind), x.rows ?? "-", dltStBadge(x.state), dltExpText(x.expectations), esc(x.note || "")]))}</div>` : ""}
      <div class="card"><b>업데이트 이력·이벤트 로그</b> <span class="mute">최근 ${d.updates.length}회</span>${d.updates.length ? d.updates.map(dltEventsHtml).join("") : '<div class="mute">아직 업데이트를 실행하지 않았습니다.</div>'}</div>` : ""}
    <div class="row">${scBtn(SCN("Catalog에서 결과 보기", "cat"))}${scBtn(SCN("Query History 열기", "qh"))}${scBtn(SCN("Jobs로 자동화", "jobs"))}</div>`;
  },
});

Object.assign(H, {
  dltpick(d) { DLT.id = d.id; DLT.srcOf = null; render(true) },
  dltnewtoggle() { DLT.creating = !DLT.creating; render(true) },
  async dltcreate() {
    DLT.name = val("dltname") || ""; DLT.schema = val("dltschema") || "gold";
    try {
      const L = await api(`/api/sessions/${SID}/dpipes`);
      const src = L.templates.bronze_mv.sql;
      const r = await api(`/api/sessions/${SID}/dpipes`, { body: { name: DLT.name, schema: DLT.schema, source: src } });
      DLT.id = r.id; DLT.srcOf = null; DLT.creating = false; DLT.name = ""; log(`파이프라인 ${r.name} 을(를) 만들었습니다.`); render(true);
    } catch (e) { toast(e.message) }
  },
  async dltdel() {
    if (!DLT.id || !confirm("이 파이프라인 정의를 삭제할까요? 만들어진 테이블은 남습니다.")) return;
    try { await api(`/api/sessions/${SID}/dpipes/${DLT.id}/delete`, { body: {} }); DLT.id = null; DLT.srcOf = null; log("파이프라인을 삭제했습니다(테이블은 남음)."); render(true) } catch (e) { toast(e.message) }
  },
  dlttpl(d) {
    api(`/api/sessions/${SID}/dpipes`).then(L => { const t = L.templates[d.k]; DLT.src = t.sql; const ta = document.getElementById("dltsrc"); if (ta) ta.value = t.sql; log(`템플릿을 불러왔습니다: ${t.title} — 먼저 '${t.needs === "orders" ? "주문" : "CDC 이벤트"} 원본 만들기'를 눌러 원본을 준비하세요.`); render(true) }).catch(e => toast(e.message));
  },
  async dltsave() {
    if (!DLT.id) return;
    try { const r = await api(`/api/sessions/${SID}/dpipes/${DLT.id}/save`, { body: { source: val("dltsrc") ?? DLT.src } }); DLT.src = val("dltsrc") ?? DLT.src; log(r.plan.ok ? "저장했습니다." : `저장했습니다(문법 오류: ${r.plan.error.message})`, !r.plan.ok, r.plan.ok ? null : r.plan.error); render(true) } catch (e) { toast(e.message) }
  },
  async dltrun(mode) {
    if (!DLT.id || DLT.busy) return; DLT.busy = true;
    try {
      await api(`/api/sessions/${SID}/dpipes/${DLT.id}/save`, { body: { source: val("dltsrc") ?? DLT.src } });
      const r = await api(`/api/sessions/${SID}/dpipes/${DLT.id}/run`, { body: { mode: typeof mode === "string" ? mode : "update" } }), u = r.update;
      log(u.state === "COMPLETED" ? `업데이트 성공(${u.events.length}개 데이터셋, ${u.duration_ms}ms)` : `✗ 업데이트 실패: ${u.error.message}`, u.state !== "COMPLETED", u.state !== "COMPLETED" ? u.error : null);
      await refresh();
    } catch (e) { toast(e.message) } finally { DLT.busy = false }
  },
  dltfull() { return H.dltrun("full_refresh") },
  async dltsample(d) {
    try {
      const r = await api(`/api/sessions/${SID}/dpipes/sample`, { body: { kind: d.kind, append: !!d.append, schema: val("dltss") || DLT.sampleSchema } });
      DLT.msg = r.status === "succeeded" ? r : { error: r.error };
      if (r.status !== "succeeded") log("✗ " + r.error.message, true, r.error); else log(`${r.table} 배치 ${r.batch}: ${r.rows}행`);
      render(true);
    } catch (e) { toast(e.message) }
  },
  async dltopen(d) { VIEW = "cat"; ls.set("view", "cat"); await H.ctable({ n: d.n }) },
});
