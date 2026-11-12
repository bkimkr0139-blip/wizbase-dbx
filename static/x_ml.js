"use strict";
/* x_ml.js: ML·MLflow(UI-25) · Model Serving(UI-27). 교육용 시뮬레이션 — 순수 파이썬 계산(LOCAL_EXECUTED), 최대 500행. */
let ML = { tab: "train", data: null, err: null, last: null, mode: "single", metric: "", sel: [], regRun: "",
  f: { experiment: "default", run_name: "", table: "food_dev.gold.ml_demo_reg", features: "x1,x2", label: "y", algo: "linear", task: "regression", test_ratio: 0.25, seed: 42, l2: 0,
    label_table: "", ts_label: "y", feature_table: "", ts_features: "", reg_name: "food_dev.gold.my_model", ft_table: "", ft_pk: "id", ft_desc: "", ft_sql: "" },
  sv: { name: "", kind: "model", model: "", ref: "@champion", agent: "", ep: "", payload: "", out: null, err: null } };
const ML_LOWER = /rmse|mae|loss|error/i;
const mlTitle = '<div class="banner">교육용 시뮬레이션입니다. 실제 MLflow·Databricks Model Serving이 아니며 순수 파이썬으로 계산합니다(LOCAL_EXECUTED). UC 테이블에서 최대 500행만 읽고, 알고리즘은 선형(릿지)·로지스틱·기준선 3가지입니다. Genie Code Agent Mode·Lakeflow Jobs 자동화는 다루지 않습니다.</div>';
const mlIn = (k, w, ph) => `<input value="${esc(ML.f[k])}" ${ph ? `placeholder="${esc(ph)}"` : ""} style="width:${w}px" oninput="ML.f.${k}=this.value">`;
const mlNum = (k, w) => `<input type="number" step="any" value="${esc(ML.f[k])}" style="width:${w}px" oninput="ML.f.${k}=this.value">`;
const mlCsv = s => String(s || "").split(",").map(x => x.trim()).filter(Boolean);
const mlFmt = v => typeof v === "number" ? (Math.abs(v) >= 1000 ? v.toFixed(1) : v.toFixed(4)) : esc(v);
const mlErr = e => { ML.err = e.data || { code: "ERROR", message: e.message }; log("✗ " + e.message, true, e.data); render(true) };
const mlPost = async (path, body) => api(`/api/sessions/${SID}/ml/${path}`, { body });

function mlBars(runs, metric) {
  const rows = runs.filter(r => r.metrics[metric] !== undefined).map(r => ({ n: r.name, v: r.metrics[metric], id: r.run_id }));
  if (!rows.length) return '<div class="mute">선택한 지표가 있는 런이 없습니다.</div>';
  const lower = ML_LOWER.test(metric), best = rows.reduce((a, b) => (lower ? b.v < a.v : b.v > a.v) ? b : a);
  const lo = Math.min(0, ...rows.map(r => r.v)), hi = Math.max(1e-9, ...rows.map(r => r.v)), W = 720, L = 190, R = 70, rh = 26, H = rows.length * rh + 8, pw = W - L - R, x = v => L + (v - lo) / (hi - lo || 1) * pw, x0 = x(0);
  const bars = rows.map((r, i) => { const y = 4 + i * rh, x1 = Math.min(x0, x(r.v)), w = Math.max(2, Math.abs(x(r.v) - x0)), tip = `<b>${esc(r.n)}</b><br>${esc(metric)}: <b>${mlFmt(r.v)}</b>${r.id === best.id ? "<br>★ 최고" : ""}`;
    return `<g><text x="${L - 8}" y="${y + 13}" class="vax" text-anchor="end">${esc(r.n.length > 24 ? r.n.slice(0, 23) + "…" : r.n)}</text><rect x="${x1.toFixed(1)}" y="${y + 3}" width="${w.toFixed(1)}" height="14" rx="3" fill="var(--vs1)"/><text x="${(Math.max(x(r.v), x0) + 6).toFixed(1)}" y="${y + 14}" class="vax">${mlFmt(r.v)}${r.id === best.id ? " ★" : ""}</text><rect x="0" y="${y}" width="${W}" height="${rh}" fill="transparent" ${tipAttr(tip)}/></g>` }).join("");
  return `<svg viewBox="0 0 ${W} ${H}" class="vsvg" role="img" aria-label="런별 ${esc(metric)} 비교 막대 차트(${lower ? "낮을수록" : "높을수록"} 좋음, ★ 최고)"><line x1="${x0.toFixed(1)}" x2="${x0.toFixed(1)}" y1="0" y2="${H}" class="vgrid"/>${bars}</svg>
    <div class="sub">${esc(metric)}: ${lower ? "낮을수록" : "높을수록"} 좋음 · ★ = 최고 런(${esc(best.n)})</div>${tableView(["런", metric], rows.map(r => [r.n, mlFmt(r.v)]))}`;
}

function mlSample(kind) {   // 합성 데이터(결정적 의사난수) — 실제 고객 데이터 아님
  let s = 7; const rnd = () => (s = (s * 1103515245 + 12345) % 2147483648) / 2147483648, rows = [];
  if (kind === "reg") { rows.push("id,x1,x2,y"); for (let i = 1; i <= 60; i++) { const a = +(rnd() * 10).toFixed(2), b = +(rnd() * 10).toFixed(2); rows.push(`${i},${a},${b},${(2 * a + 3 * b + 1 + (rnd() - .5) * 2).toFixed(3)}`) } }
  else { rows.push("id,x1,x2,label"); for (let i = 1; i <= 80; i++) { const a = +(rnd() * 10).toFixed(2), b = +(rnd() * 10).toFixed(2); rows.push(`${i},${a},${b},${a + b + (rnd() - .5) * 4 > 10 ? 1 : 0}`) } }
  return rows.join("\n") + "\n";
}

async function mlLoad() { ML.data = await api(`/api/sessions/${SID}/ml/state`) }

Object.assign(V, {
  async ml() {
    await mlLoad();
    const d = ML.data, tabs = [["train", "실험·학습"], ["compare", "런 비교"], ["registry", "모델 레지스트리"], ["features", "특성 테이블"]], f = ML.f;
    const bar = `<div class="vfilters">${tabs.map(([k, l]) => `<button class="${ML.tab === k ? "primary" : "ghost"}" data-a="mltab" data-k="${k}">${l}</button>`).join("")}</div>`;
    let b = "";
    if (ML.tab === "train") {
      const single = ML.mode === "single", last = ML.last;
      b = `<div class="card"><b>1. 학습 데이터</b><div class="sub">실제 코스는 특성 엔지니어링 후 UC 테이블에 저장합니다. 아래 버튼은 합성 데이터를 gold schema 에 만듭니다(이미 있으면 덮어씀).</div>
        <div class="row"><button class="sec" data-a="mldemo" data-k="reg">샘플 회귀 데이터 만들기(ml_demo_reg)</button><button class="sec" data-a="mldemo" data-k="cls">샘플 분류 데이터 만들기(ml_demo_cls)</button><button class="sec" data-a="nav" data-v="adddata">Add data로 직접 올리기</button></div></div>
        <div class="card"><b>2. 학습 설정</b><div class="vfilters"><label>실험 ${mlIn("experiment", 130)}</label><label>런 이름 ${mlIn("run_name", 130, "자동")}</label>
          <label>방식 <select onchange="ML.mode=this.value;render(true)"><option value="single" ${single ? "selected" : ""}>단일 테이블</option><option value="ts" ${single ? "" : "selected"}>특성 테이블 조인(training set)</option></select></label></div>
        ${single ? `<div class="vfilters"><label>테이블 ${mlIn("table", 260)}</label><label>특성(쉼표) ${mlIn("features", 150)}</label><label>라벨 ${mlIn("label", 90)}</label></div>` :
          `<div class="vfilters"><label>라벨 테이블 ${mlIn("label_table", 240)}</label><label>라벨 열 ${mlIn("ts_label", 80)}</label></div><div class="vfilters"><label>특성 테이블 ${mlIn("feature_table", 240)}</label><label>가져올 특성(쉼표) ${mlIn("ts_features", 160)}</label></div><div class="sub">특성 테이블은 '특성 테이블' 탭에서 먼저 등록해야 하며 기본키로 라벨 테이블과 조인합니다.</div>`}
        <div class="vfilters"><label>알고리즘 <select onchange="ML.f.algo=this.value;render(true)">${Object.entries(d.algos).map(([k, v]) => `<option value="${k}" ${f.algo === k ? "selected" : ""}>${esc(v)}</option>`).join("")}</select></label>
          ${f.algo === "baseline" ? `<label>과제 <select onchange="ML.f.task=this.value"><option value="regression" ${f.task === "regression" ? "selected" : ""}>회귀(평균)</option><option value="classification" ${f.task === "classification" ? "selected" : ""}>분류(최빈값)</option></select></label>` : ""}
          <label>테스트 비율 ${mlNum("test_ratio", 70)}</label><label>시드 ${mlNum("seed", 70)}</label><label>l2(릿지) ${mlNum("l2", 70)}</label></div>
        <div class="row"><button data-a="mltrain">학습 실행(런 기록)</button></div><div class="sub">학습/테스트는 행 내용의 해시로 나눠 같은 시드에서는 항상 같은 결과입니다. 지표: 회귀 RMSE·MAE·R², 분류 accuracy·precision·recall·F1(임계값 0.5).</div></div>`;
      if (last) b += `<div class="card"><b>방금 학습한 런: ${esc(last.name)}</b> ${badge(last.status, "ok")} <span class="mute">${esc(last.run_id)}</span>${table(["지표", "값"], Object.entries(last.metrics).map(([k, v]) => [k, mlFmt(v)]))}
        <div class="sub">특성 ${esc(last.model_summary.features.join(", "))} · 계수 ${esc(last.model_summary.coef.join(", ") || "-")} · 절편 ${esc(last.model_summary.intercept)} · 사용 ${last.data.rows_used}행(학습 ${last.data.train_n}/테스트 ${last.data.test_n}${last.data.rows_dropped_null ? `, NULL 제외 ${last.data.rows_dropped_null}` : ""})${last.data.truncated ? " · 500행에서 잘렸을 수 있음" : ""}</div></div>`;
    } else if (ML.tab === "compare") {
      const metrics = [...new Set(d.runs.flatMap(r => Object.keys(r.metrics)))], m = ML.metric && metrics.includes(ML.metric) ? ML.metric : (metrics.find(x => x === "test_rmse") || metrics.find(x => x === "test_f1") || metrics[0] || "");
      b = !d.runs.length ? '<div class="card mute">아직 런이 없습니다. 「실험·학습」 탭에서 학습을 실행하세요.</div>' : `<div class="card"><div class="vfilters"><label>비교 지표 <select onchange="ML.metric=this.value;render(true)">${metrics.map(x => `<option ${x === m ? "selected" : ""}>${esc(x)}</option>`).join("")}</select></label></div>${mlBars(d.runs, m)}</div>
        <div class="card"><b>런 목록</b> <span class="mute">(실험 ${d.experiments.map(e => esc(e.name)).join(", ")})</span>${table(["런", "실험", "알고리즘", "시각", "test 지표", "등록", ""], d.runs.map(r => [T(r.name + " · " + r.run_id), r.experiment, r.params.algo, fmtIso(r.start), Object.entries(r.metrics).filter(([k]) => k.startsWith("test_")).map(([k, v]) => `${k.slice(5)} ${typeof v === "number" ? v.toFixed(4) : v}`).join(" · "), r.tags.registered_model ? badge(r.tags.registered_model, "ok") : `<a href="#" data-a="mlpickrun" data-id="${esc(r.run_id)}">등록하러 가기</a>`, r.tags.registered_model ? "" : `<a href="#" data-a="mldelrun" data-id="${esc(r.run_id)}">삭제</a>`]))}</div>`;
    } else if (ML.tab === "registry") {
      const free = d.runs.filter(r => !r.tags.registered_model);
      b = `<div class="card"><b>런에서 모델 등록</b><div class="sub">UC 모델 이름은 catalog.schema.model 3단계입니다. 시뮬레이터는 CREATE MODEL 권한 대신 schema 의 CREATE TABLE 권한(또는 소유자·관리자)으로 단순화했습니다. 같은 이름에 등록하면 버전이 1씩 늘어납니다.</div>
        <div class="vfilters"><label>런 <select onchange="ML.regRun=this.value">${["", ...d.runs.map(r => r.run_id)].map(id => { const r = d.runs.find(x => x.run_id === id); return `<option value="${esc(id)}" ${ML.regRun === id ? "selected" : ""}>${r ? esc(r.name + " (" + r.run_id + ")") : "— 선택 —"}</option>` }).join("")}</select></label><label>모델 이름 ${mlIn("reg_name", 260)}</label><button data-a="mlregister">등록</button></div>${free.length ? "" : '<div class="mute">등록 가능한(미등록) 런이 없어도 이미 등록한 런은 새 버전으로 다시 등록할 수 있습니다.</div>'}</div>
        ${d.models.map((m, mi) => `<div class="card"><b>${esc(m.name)}</b> <span class="mute">owner ${esc(m.owner)}</span> ${Object.entries(m.aliases).map(([a, v]) => badge("@" + a + " → v" + v, "ok")).join(" ")}
          ${table(["버전", "런", "알고리즘", "특성", "test 지표", "등록 시각"], m.versions.slice().reverse().map(v => ["v" + v.version, v.run_id, v.algo, v.features.join(", "), Object.entries(v.metrics).filter(([k]) => k.startsWith("test_")).map(([k, x]) => `${k.slice(5)} ${mlFmt(x)}`).join(" · "), fmtIso(v.created)]), true)}
          <div class="vfilters"><label>별칭 <input id="mla_${mi}" placeholder="champion" style="width:110px"></label><label>버전 <select id="mlv_${mi}">${m.versions.map(v => `<option value="${v.version}">v${v.version}</option>`).join("")}</select></label><button data-a="mlalias" data-i="${mi}">별칭 지정/이동</button><button class="ghost" data-a="mlunalias" data-i="${mi}">별칭 제거</button></div></div>`).join("") || '<div class="card mute">등록된 모델이 없습니다.</div>'}
        <div class="row"><button class="sec" data-a="nav" data-v="serve">Model Serving 으로 이동(별칭 @champion 으로 배포)</button></div>`;
    } else {
      b = `<div class="card"><b>특성 테이블 등록</b><div class="sub">UC 테이블에 기본키를 지정해 특성 테이블로 등록합니다(메타데이터 등록 + 키 유일성 검사). SQL 을 입력하면 그 결과로 테이블을 만든 뒤(특성 엔지니어링) 등록합니다. 특성 열은 숫자여야 합니다.</div>
        <div class="vfilters"><label>테이블 ${mlIn("ft_table", 260, "food_dev.gold.item_features")}</label><label>기본키(쉼표) ${mlIn("ft_pk", 110)}</label><label>설명 ${mlIn("ft_desc", 180)}</label></div>
        <textarea placeholder="(선택) 특성 SQL: SELECT product_id, SUM(on_hand_qty) AS on_hand FROM food_dev.silver.inventory GROUP BY product_id" style="min-height:70px" oninput="ML.f.ft_sql=this.value">${esc(f.ft_sql)}</textarea>
        <div class="row"><button data-a="mlfeat">등록</button></div></div>
        <div class="card"><b>등록된 특성 테이블</b>${d.features.length ? table(["테이블", "기본키", "열", "설명", ""], d.features.map(x => [T(x.table), T(x.pk.join(", ")), T(x.columns.join(", ")), T(x.description), `<a href="#" data-a="mlfeatdel" data-t="${esc(x.table)}">등록 해제</a>`])) : '<div class="mute">등록된 특성 테이블이 없습니다.</div>'}
        <div class="sub">서빙 시 특성 조회: 이 테이블로 학습한 모델(training set)은 엔드포인트에 키만 보내도 특성을 자동으로 채웁니다(모델을 등록한 주체의 권한으로 조회).</div></div>`;
    }
    return `<h2>UI-28 ML·MLflow</h2>${mlTitle}${ML.err ? `<div class="card">${remedyHtml(ML.err)}</div>` : ""}${bar}${b}`;
  },
  async serve() {
    const s = await api(`/api/sessions/${SID}/serving`), d = await api(`/api/sessions/${SID}/ml/state`), v = ML.sv, used = s.endpoints.length;
    if (!v.model && d.models.length) v.model = d.models[0].name;
    const feats = n => { const m = d.models.find(x => x.name === n); return m && m.versions.length ? m.versions[m.versions.length - 1].features : [] };
    const epSel = s.endpoints.find(e => e.name === v.ep) || s.endpoints[0];
    if (epSel && v.ep !== epSel.name) { v.ep = epSel.name; v.payload = "" }
    if (epSel && !v.payload) { const fs = epSel.kind === "model" ? feats(epSel.config.model) : []; v.payload = epSel.kind === "model" ? JSON.stringify({ dataframe_records: [Object.fromEntries((fs.length ? fs : ["x1", "x2"]).map(k => [k, 1]))] }, null, 1) : JSON.stringify({ question: "질문을 입력하세요" }, null, 1) }
    const gauge = `<div class="row" role="img" aria-label="엔드포인트 슬롯 ${used}/${s.max_slots} 사용">${Array.from({ length: s.max_slots }, (_, i) => `<span class="b ${i < used ? "ok" : ""}" style="min-width:64px;text-align:center">${i < used ? "사용 중" : "비어 있음"}</span>`).join("")}<span class="mute">슬롯 ${used}/${s.max_slots} (Free Edition처럼 동시에 ${s.max_slots}개)</span></div>`;
    return `<h2>UI-30 Model Serving</h2><div class="banner">${esc(s.note)}</div>${v.err ? `<div class="card">${remedyHtml(v.err)}</div>` : ""}
    <div class="card"><b>엔드포인트 슬롯</b>${gauge}</div>
    <div class="card"><b>엔드포인트 만들기</b><div class="vfilters"><label>이름 <input value="${esc(v.name)}" placeholder="price-ep" style="width:130px" oninput="ML.sv.name=this.value"></label>
      <label>종류 <select onchange="ML.sv.kind=this.value;render(true)">${s.kinds.map(k => `<option value="${k}" ${v.kind === k ? "selected" : ""}>${k === "model" ? "model(등록 모델)" : k === "agent" ? "agent(RAG 에이전트)" : esc(k)}</option>`).join("")}</select></label>
      ${v.kind === "model" ? `<label>모델 <select onchange="ML.sv.model=this.value">${d.models.map(m => `<option ${m.name === v.model ? "selected" : ""}>${esc(m.name)}</option>`).join("") || "<option value=''>(등록된 모델 없음)</option>"}</select></label><label>ref <input value="${esc(v.ref)}" style="width:100px" oninput="ML.sv.ref=this.value" title="@별칭 또는 버전 숫자"></label>` : `<label>에이전트 ID <input value="${esc(v.agent)}" style="width:170px" oninput="ML.sv.agent=this.value" placeholder="생성형 AI·RAG 화면의 에이전트 ID"></label>`}
      <button data-a="svcreate">만들기</button></div><div class="sub">모델 엔드포인트는 ref 로 별칭(@champion)을 쓰면 별칭을 다른 버전으로 옮기는 즉시 새 버전을 서빙합니다.${d.models.length ? "" : " 먼저 ML·MLflow 화면에서 모델을 등록하세요."}</div></div>
    <div class="card"><b>엔드포인트 목록</b>${s.endpoints.length ? table(["이름", "종류", "구성", "상태", "질의 수", "마지막 질의", ""], s.endpoints.map(e => [e.name, e.kind, kvText(e.config), badge(e.state, "ok"), e.queries, fmtIso(e.last_query_at), `<a href="#" data-a="svdelete" data-n="${esc(e.name)}">삭제</a>`])) : '<div class="mute">엔드포인트가 없습니다.</div>'}</div>
    ${epSel ? `<div class="card"><b>질의</b><div class="vfilters"><label>엔드포인트 <select onchange="ML.sv.ep=this.value;ML.sv.payload='';ML.sv.out=null;render(true)">${s.endpoints.map(e => `<option ${e.name === v.ep ? "selected" : ""}>${esc(e.name)}</option>`).join("")}</select></label></div>
      <textarea style="min-height:110px" oninput="ML.sv.payload=this.value">${esc(v.payload)}</textarea>
      <div class="sub">model: <code>dataframe_records</code>(객체 목록) 또는 <code>inputs</code>(숫자 배열 목록), 최대 20건.${epSel.kind === "model" && feats(epSel.config.model).length ? ` 필요한 특성: ${feats(epSel.config.model).map(esc).join(", ")}` : ""}</div>
      <div class="row"><button data-a="svquery">질의 실행</button></div>${v.out ? `<div class="card">${badge("응답", "ok")} <span class="mute">${v.out.latency_ms}ms · ${esc(v.out.evidence_level)}</span><pre>${esc(JSON.stringify(v.out.result, null, 2))}</pre></div>` : ""}</div>` : ""}`;
  },
});

Object.assign(H, {
  mltab(d) { ML.tab = d.k; ML.err = null; render(true) },
  async mldemo(d) {
    const reg = d.k === "reg", t = reg ? "ml_demo_reg" : "ml_demo_cls";
    try { const r = await api(`/api/sessions/${SID}/add-data`, { body: { schema: "gold", table: t, csv: mlSample(d.k), mode: "replace", filename: t + ".csv" } });
      if (r.status !== "succeeded") { ML.err = r.error; log("✗ " + r.error.message, true, r.error) } else { ML.err = null; ML.f.table = "food_dev.gold." + t; ML.f.features = "x1,x2"; ML.f.label = reg ? "y" : "label"; ML.f.algo = reg ? "linear" : "logistic"; log(`${t} ${r.rows_total}행 생성`) } await refresh() } catch (e) { mlErr(e) }
  },
  async mltrain() {
    const f = ML.f, body = { experiment: f.experiment || "default", run_name: f.run_name, algo: f.algo, task: f.task, test_ratio: +f.test_ratio, seed: +f.seed, l2: +f.l2 };
    if (ML.mode === "single") Object.assign(body, { table: f.table, features: mlCsv(f.features), label: f.label });
    else Object.assign(body, { training_set: { label_table: f.label_table, label: f.ts_label, lookups: [{ feature_table: f.feature_table, features: mlCsv(f.ts_features) }] } });
    try { ML.last = await mlPost("train", body); ML.err = null; log(`런 ${ML.last.name} 완료 — ` + Object.entries(ML.last.metrics).filter(([k]) => k.startsWith("test_")).map(([k, v]) => k + "=" + mlFmt(v)).join(" ")); await refresh() } catch (e) { mlErr(e) }
  },
  mlpickrun(d) { ML.regRun = d.id; ML.tab = "registry"; render(true) },
  async mldelrun(d) { try { await mlPost(`runs/${d.id}/delete`, {}); ML.err = null; render(true) } catch (e) { mlErr(e) } },
  async mlregister() { try { const r = await mlPost("models/register", { run_id: ML.regRun, name: ML.f.reg_name }); ML.err = null; log(`모델 ${r.name} v${r.version} 등록`); render(true) } catch (e) { mlErr(e) } },
  async mlalias(d) { try { const r = await mlPost("models/alias", { name: ML.data.models[+d.i].name, alias: val("mla_" + d.i), version: +val("mlv_" + d.i) }); ML.err = null; log(`별칭 갱신: ${kvText(r.aliases)}`); render(true) } catch (e) { mlErr(e) } },
  async mlunalias(d) { try { await mlPost("models/alias", { name: ML.data.models[+d.i].name, alias: val("mla_" + d.i), version: null }); ML.err = null; render(true) } catch (e) { mlErr(e) } },
  async mlfeat() { const f = ML.f; try { await mlPost("features", { table: f.ft_table, pk: mlCsv(f.ft_pk), description: f.ft_desc, from_sql: f.ft_sql || undefined }); ML.err = null; log(`특성 테이블 ${f.ft_table} 등록`); await refresh() } catch (e) { mlErr(e) } },
  async mlfeatdel(d) { try { await mlPost("features/delete", { table: d.t }); ML.err = null; render(true) } catch (e) { mlErr(e) } },
  async svcreate() { const v = ML.sv, cfg = v.kind === "model" ? { model: v.model, ref: v.ref } : { agent: v.agent }; try { await api(`/api/sessions/${SID}/serving`, { body: { name: v.name, kind: v.kind, config: cfg } }); v.err = null; v.ep = v.name; v.payload = ""; v.out = null; log(`엔드포인트 ${v.name} 생성`); render(true) } catch (e) { v.err = e.data || { code: "ERROR", message: e.message }; log("✗ " + e.message, true, e.data); render(true) } },
  async svdelete(d) { try { await api(`/api/sessions/${SID}/serving/${d.n}/delete`, { body: {} }); ML.sv.err = null; ML.sv.out = null; ML.sv.ep = ""; render(true) } catch (e) { ML.sv.err = e.data; render(true) } },
  async svquery() { const v = ML.sv; let p; try { p = JSON.parse(v.payload) } catch { v.err = { code: "INVALID_JSON", message: "JSON 형식이 올바르지 않습니다." }; render(true); return } try { v.out = await api(`/api/sessions/${SID}/serving/${v.ep}/query`, { body: p }); v.err = null } catch (e) { v.out = null; v.err = e.data || { code: "ERROR", message: e.message } } render(true) },
});
