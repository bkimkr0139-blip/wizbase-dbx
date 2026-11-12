"use strict";
const $ = (s, r = document) => r.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const J = o => esc(JSON.stringify(o, null, 1));
const ls = { get(k) { try { return localStorage.getItem(k) } catch { return null } }, set(k, v) { try { localStorage.setItem(k, v) } catch { } }, del(k) { try { localStorage.removeItem(k) } catch { } } };
let TOKEN = ls.get("tok"), ME = null, SID = ls.get("sid"), ST = null, VIEW = ls.get("view") || "env", META = null, LASTLOG = "", PRINCIPAL = "", SIDE = true;
let AI_SCROLL = "top", AI_KEEP = 0, SESSQ = { q: "", page: 0, size: 25, checked: new Set(), ids: [] }, REAL = null, LASTVIEW = "", PENDING_DEL = [], SYS = null, CLIENT_BUILD = null, RTAB = ls.get("rtab") || "", SYSPOP = "";
const NAV = [
  ["학습 환경", [["env", "UI-01 환경 점검"], ["req", "UI-02 착수·요구·계약"], ["ws", "UI-03 Workspace"], ["cat", "UI-04 Catalog Explorer"], ["sql", "UI-05 SQL Editor"], ["nb", "UI-06 Notebook"], ["comp", "UI-07 Compute/Warehouses"], ["track", "프로젝트 트랙(8주)"], ["demo", "고객 시연 20분"]]],
  ["데이터 구축", [["conn", "UI-08 Connections/수집"], ["pipe", "UI-09 Pipelines"], ["cdc", "UI-09b CDC 재생"], ["jobs", "UI-10 Jobs"], ["genie", "UI-11 의미모델·Genie"], ["agent", "UI-12 Agent·승인"], ["trace", "UI-13 Tracing/평가"], ["bundle", "UI-14 Git/Bundle/CLI"], ["perm", "UI-15 권한·관리"]]],
  ["운영", [["rvw", "검토 센터"], ["fbq", "피드백·개발큐"], ["usage", "접속·사용 기록"], ["ko", "한국어 가이드"], ["xfer", "전이 시드·협업"], ["real", "실제 환경 연결"], ["inst", "UI-16 강사·수료"], ["evid", "증거 보고서"]]],
  ["전문과정 v1.1", [["prof", "UI-17 역량·등급"], ["plan", "UI-18 목표·학습계획"], ["map", "UI-19 공식 목표 지도"], ["tutor", "UI-20 AI 튜터"], ["exam", "UI-21 시험센터"], ["lab", "UI-22 실제 실습 증거함"], ["qual", "UI-23 콘텐츠 품질"], ["partner", "UI-24 파트너 인력"], ["conf", "UI-25 자료 충돌"], ["vmx", "UI-26 현장 대조표"]]]
];

async function api(path, o = {}) {
  const r = await fetch(path, { method: o.body ? "POST" : (o.method || "GET"), headers: { "Content-Type": "application/json", ...(TOKEN ? { Authorization: "Bearer " + TOKEN } : {}) }, body: o.body ? JSON.stringify(o.body) : undefined });
  let j = null; try { j = await r.json() } catch { }
  if (r.status === 401 && TOKEN) { TOKEN = null; ls.del("tok"); render(); throw new Error("로그인 필요") }
  if (!r.ok) { const e = new Error(j?.error?.message || r.statusText); e.data = j?.error; e.status = r.status; throw e }
  return j;
}
const fixBtn = () => LASTERR ? `<button class="logfix" data-a="remedyopen">해결 방법 보기 ▸ ${esc(LASTERR.code || "")}</button>` : "";
function log(t, bad, err) { if (bad && err && err.code) LASTERR = err; else if (!bad) LASTERR = null; LASTLOG = (new Date().toLocaleTimeString()) + " " + t + "\n" + LASTLOG.slice(0, 2500); const l = $("#log"); if (l) { l.innerHTML = fixBtn() + `<span>${esc(LASTLOG)}</span>`; l.style.color = bad ? "#fca5a5" : "#cbd5e1" } }
async function cmd(type, payload = {}, quiet) {
  try {
    const ex = await api(`/api/sessions/${SID}/commands`, { body: { command_type: type, payload } });
    const bad = ex.status !== "ok";
    log(`${type} → ${ex.status} [${ex.evidence_level}] ${bad ? summarize(ex.result) : ""}`, bad, ex.result?.error || ex.result?.result?.error);
    await refresh(); return ex;
  } catch (e) { log(`${type} ✗ ${e.message}`, true, e.data); if (!quiet) toast(e.message); return null }
}
function summarize(r) { const e = r?.error || r?.result?.error; return e ? `${e.code}: ${e.message}` : (r?.stderr || "") }
function toast(m) { log("⚠ " + m, true) }
const fmtIso = t => { if (!t) return "-"; const d = new Date(t); return isNaN(d) ? String(t).slice(0, 16).replace("T", " ") : d.toLocaleString("sv-SE", { timeZone: "Asia/Seoul" }).slice(0, 16) };
const fmtKst = t => t ? new Date(t * 1000).toLocaleString("sv-SE", { timeZone: "Asia/Seoul" }).slice(0, 16) : "-";
const badge = (t, c) => `<span class="b ${c || ""}">${esc(t)}</span>`;
const lv = l => badge(l, l === "LOCAL_EXECUTED" ? "ok" : "w");
function table(cols, rows, untrusted) { if (!rows || !rows.length) return `<div class="mute">(없음)</div>`; return `<div class="tw"><table><tr>${cols.map(c => `<th>${esc(c)}</th>`).join("")}</tr>${rows.map(r => `<tr>${r.map(c => `<td>${typeof c === "object" && c !== null ? pretty(c, 2) : (!untrusted && typeof c === "string" && /^<(a|button|input|span)\b/.test(c) ? c : ((!untrusted && autoLink(c)) || esc(c)))}</td>`).join("")}</tr>`).join("")}</table></div>` }
const val = id => $("#" + id)?.value;
const PV = v => ({ unknown: "미확인", to_be_pinned: "미지정(확정 전)", to_be_recorded: "미기록", not_applicable: "해당 없음", serverless: "서버리스", training: "교육용", aws: "AWS", en: "영어(en)", DOC_CHECKED: "문서 확인만 완료" })[v] ?? (v === null || v === undefined ? "기록 없음" : v === true ? "예" : v === false ? "아니오" : String(v));
function profileHtml(p) {
  const c = p.compute || {}, row = (k, v, hint) => [k, `${esc(PV(v))}${hint ? ` <span class="mute">${esc(hint)}</span>` : ""}`];
  const rows = [row("프로필 ID", p.profile_id), row("클라우드 / 리전", `${PV(p.cloud)} / ${p.region}`, "서울"), row("워크스페이스 종류", p.workspace_kind), row("Unity Catalog", p.unity_catalog_enabled, "데이터 거버넌스 기능"),
    row("컴퓨트 방식", c.mode), row("DBR 버전", c.dbr_version, c.dbr_version === "not_applicable" ? "서버리스는 런타임 버전을 직접 고르지 않음" : ""), row("서버리스 환경", c.serverless_environment, "실제 워크스페이스에서 확인 전"), row("SQL Warehouse 채널", c.sql_warehouse_channel, "실제 워크스페이스에서 확인 전"),
    row("CLI 버전", p.cli_version, p.cli_min_documented), row("화면 언어", p.ui_locale), row("화면 확인 일시", p.ui_observed_at, "실제 화면을 본 기록이 아직 없음"), row("화면 릴리스", p.ui_release_id), row("SA 검토 일시", p.sa_reviewed_at, "검토 전"), row("확인 상태", p.evidence_status, "문서 기준이며 실제 워크스페이스 검증 전")];
  const names = Object.entries(p.official_names_checked || {});
  return `<div class="tw"><table>${rows.map(([k, v]) => `<tr><th style="width:170px;text-align:left">${esc(k)}</th><td>${v}</td></tr>`).join("")}</table></div>
    ${names.length ? `<div class="sub" style="margin-top:8px"><b>공식 명칭 변경 확인</b> (옛 이름 → 현재 공식 이름)</div>${table(["옛 이름", "현재 공식 이름"], names.map(([a, b]) => [a, b]))}` : ""}
    <div class="sub">${esc(p.note || "")}</div>
    <details><summary class="mute">원본 데이터(JSON) 보기</summary><pre>${J(p)}</pre></details>`;
}
const staff = () => ["instructor", "admin", "reviewer"].includes(ME?.role);
const err = e => `<div class="bad">${esc(e.message || e)}</div>`;

/* ------------------------------------------------------------ shell */
let GUIDE = null, AI_OPEN = ls.get("ai") !== "0" && !(typeof matchMedia === "function" && matchMedia("(max-width: 820px)").matches), PANEL = ls.get("panel") || "help", AI_TAB = "chat", PREFILL = null, CHAT = [], BUSY = false;
const VIEW_STEPS = { env: ["env"], req: ["req"], sql: ["perm", "recon"], conn: ["conn"], pipe: ["pipe"], jobs: ["job"], genie: ["genie"], agent: ["order", "safety"], bundle: ["bundle", "iso"], nb: ["nb"], trace: ["eval"], evid: ["wrap"] };
const ICON = {
  help: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9.5"/><path d="M9.2 9.3a2.9 2.9 0 1 1 4.3 2.5c-.9.5-1.5 1-1.5 2"/><circle cx="12" cy="17.2" r=".6" fill="currentColor"/></svg>',
  logo: '<svg width="26" height="26" viewBox="0 0 32 32" fill="none"><path d="M16 2l12 7v14l-12 7L4 23V9z" fill="currentColor" opacity=".12"/><path d="M16 2l12 7v14l-12 7L4 23V9z" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/><path d="M10 12l3 9 3-6 3 6 3-9" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  spark: '<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2l1.8 5.7L19.5 9.5l-5.7 1.8L12 17l-1.8-5.7L4.5 9.5l5.7-1.8z"/><path d="M19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z" opacity=".7"/></svg>',
  send: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 2L11 13"/><path d="M22 2l-7 20-4-9-9-4z"/></svg>',
  check: '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3.4" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12l5 5L20 7"/></svg>',
  arrow: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14M13 6l6 6-6 6"/></svg>',
  axos: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a8 8 0 0 1-11.6 7.1L3 21l1.9-5.4A8 8 0 1 1 21 12z"/><path d="M8.5 12h7M12 8.5v7"/></svg>',
  close: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18"/></svg>'
};
const md = t => esc(t).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/`([^`]+)`/g, "<code>$1</code>").replace(/\n/g, "<br>");
function navState(view) {
  const ids = VIEW_STEPS[view]; if (!ids || !GUIDE) return "";
  const ss = GUIDE.steps.filter(x => ids.includes(x.id)); const d = ss.filter(x => x.status === "done").length;
  return d === ss.length ? "done" : (ss.some(x => x.done > 0) || ss.some(x => x.status === "current")) ? "part" : "";
}
async function loadGuide() { if (!SID) { GUIDE = null; return } try { GUIDE = await api(`/api/sessions/${SID}/guide`) } catch { GUIDE = null } }
function loadChat() {
  try { CHAT = JSON.parse(ls.get("chat_" + (SID || "none")) || "[]") } catch { CHAT = [] }
  if (!CHAT.length) CHAT = [{ r: "ai", t: SID ? "안녕하세요. **AI 지원**입니다. 전체 절차를 단계별로 안내하고, 막히면 원인과 다음 행동을 바로가기로 알려드립니다.\n\"다음에 뭐 해?\"라고 물어보거나 아래 버튼을 눌러보세요." : "안녕하세요. 먼저 **UI-01 환경 점검**에서 세션을 시작하면 전체 절차를 안내해 드립니다.", s: SID ? [] : [{ type: "nav", label: "환경 점검으로 이동", view: "env" }] }];
}
function saveChat() { ls.set("chat_" + (SID || "none"), JSON.stringify(CHAT.slice(-40))) }
async function refresh() {
  if (!SID) { render(true); return }
  try { ST = await api(`/api/sessions/${SID}/state` + (PRINCIPAL ? `?principal=${encodeURIComponent(PRINCIPAL)}` : "")); await loadGuide() }
  catch (e) { if (e.status === 404) { SID = null; ls.del("sid"); ST = null; GUIDE = null } }
  render(true)
}
async function render(soft) {
  const app = $("#app");
  if (!TOKEN) return renderLogin(app);
  if (!ME) { try { ME = await api("/api/me"); META = META || await api("/api/meta") } catch { TOKEN = null; return render() } }
  if (!viewAllowed(VIEW)) { VIEW = "env"; ls.set("view", VIEW) }          // 역할이 볼 수 없는 화면(예: 이전에 admin이 열어 둔 화면)은 시작 화면으로
  META = META || await api("/api/meta");
  if (!SYS) {
    try {
      SYS = await api("/api/system/info"); CLIENT_BUILD = CLIENT_BUILD || SYS.build;
      const sv = ls.get("seen_ver"); ls.set("seen_ver", SYS.version);
      if (sv && sv !== SYS.version) SYSPOP = `<h3 style="margin-top:0">새 버전으로 업데이트되었습니다</h3><div class="sub">v${esc(sv)} → <b>v${esc(SYS.version)}</b></div>${SYS.changelog.slice(0, 1).map(r => `<ul>${r.notes.map(n => `<li>${esc(n)}</li>`).join("")}</ul>`).join("")}`;
      loadMine().then(() => { if (FB_UNSEEN) { log(`제출한 피드백 ${FB_UNSEEN}건이 처리되었습니다. AXOS > 내 피드백에서 확인하세요.`); render(true) } });
      if (!POLL) { POLL = setInterval(() => pollUpdate(false), 300000); window.addEventListener("focus", () => pollUpdate(false)); setTimeout(() => pollUpdate(false), 4000) }
    } catch { }
  }
  if (SID && !ST && !soft) { await refresh(); return }
  if (SID && !GUIDE) await loadGuide();
  SCS.length = 0;
  const keepScroll = $("#main")?.scrollTop || 0;
  AI_KEEP = $("#chatlog")?.scrollTop || 0;
  const mode = ST ? ST.session.mode : null;
  const title = (NAV.flatMap(g => g[1]).find(n => n[0] === VIEW) || ["", ""])[1];
  app.className = AI_OPEN ? "ai-open" : "";
  app.innerHTML = `<header class="top"><div class="brand"><span class="logochip"><img class="logo-w" src="/static/logo-white.png" alt="wizbase"></span><div><span>DBX Project Rehearsal</span></div></div>
    <div class="crumb">${esc(title)}</div>
    <div class="chips">${GUIDE ? `<span class="chip" title="전체 진행"><i></i>진행 ${GUIDE.percent}%</span>` : ""}${mode ? `<span class="chip ${mode === "B" ? "ok" : "w"}"><i></i>모드 ${mode} · ${mode === "A" ? "SIMULATED" : "LOCAL_EXECUTED"}</span>` : ""}<span class="chip" title="${esc(META.profile.profile_id)}">${esc(META.profile.cloud.toUpperCase())} · ${esc(META.profile.region)}</span><span class="chip w" title="문서 확인만 완료, 워크스페이스 실측·SA 검토 없음">${esc(META.profile.evidence_status)}</span>${ST ? `<span class="chip" title="실행 신원">${esc(ST.principal.split("@")[0])}</span><span class="chip mono">${esc(ST.clock.slice(0, 16).replace("T", " "))}</span>` : ""}</div>
    <div class="user"><span class="av">${esc(ME.name.slice(0, 1))}</span><div><b>${esc(ME.name)}</b><small>${ME.role === "admin" ? "admin · 수퍼유저" : ME.role}</small></div><button class="ghost" data-a="logout">로그아웃</button></div></header>
    <div class="strip">WIZBASE(Databricks 파트너)의 실제 PoC 준비와 파트너 레벨 상향을 위한 인증 시험 준비를 지원하는 교육·훈련 환경입니다. Databricks 공식 제품·인증·교육과정이 아니며 합성 데이터만 사용합니다. 모의 결과와 실제 DBX 검증 결과는 구분해 표시됩니다.</div>
    ${menubarHtml()}${mobileBar()}${nextBar()}${sysPop()}
    <div class="wrap">
    <main id="main"></main></div>
    <button class="aitab helptab ${AI_OPEN && PANEL === "help" ? "on" : ""}" data-a="helptoggle" aria-label="도움말 열기">${ICON.help}<span>HELP</span></button>
    <button class="aitab ${AI_OPEN && PANEL === "ai" ? "on" : ""}" data-a="aitoggle" aria-label="AI 지원 열기">${ICON.spark}<span>AI 지원</span>${GUIDE && GUIDE.next ? '<i class="pulse"></i>' : ""}</button>
    <button class="aitab axostab ${AI_OPEN && PANEL === "axos" ? "on" : ""}" data-a="axostoggle" aria-label="AXOS 피드백 열기">${ICON.axos}<span>AXOS</span>${FB_UNSEEN ? '<i class="pulse"></i>' : ""}</button>
    <aside id="ai" class="${AI_OPEN ? "open" : ""}">${aiHtml()}</aside>
    <div class="log" id="log">${fixBtn()}<span>${esc(LASTLOG) || "실행 로그 · 오류 · 증거 수준이 여기에 표시됩니다."}</span></div>`;
  if (VIEW !== LASTVIEW) { LASTVIEW = VIEW; api("/api/usage/view", { body: { view: VIEW } }).catch(() => { }) }
  if (ME && VIEW === LASTVIEW) ls.set("lv_" + ME.name.toLowerCase(), VIEW);
  const needSess = !["env", "exam", "prof", "plan", "map", "tutor", "lab", "qual", "partner", "conf", "vmx", "inst", "rvw", "ko", "xfer", "fbq", "usage", "real"].includes(VIEW);
  const main = $("#main");
  if (needSess && !SID) { main.innerHTML = `<div class="empty"><h2>세션이 필요합니다</h2><p>먼저 <a href="#" data-a="nav" data-v="env">환경 점검</a>에서 세션을 시작하세요.</p></div>`; }
  else { try { main.innerHTML = (await (V[VIEW] || V.env)()) + viewFooter(VIEW) } catch (e) { main.innerHTML = err(e) } }
  if (PREFILL) { for (const [id, v] of Object.entries(PREFILL)) { const el = $("#" + id); if (el) { el.value = v; el.classList.add("flash") } } PREFILL = null }
  else if (soft) main.scrollTop = keepScroll;
  try { const mb = document.querySelector(".menubar"); if (mb) document.documentElement.style.setProperty("--aitop", Math.round(mb.getBoundingClientRect().bottom) + "px") } catch { }
  const cl = $("#chatlog");
  if (cl) { if (AI_SCROLL === "bottom") cl.scrollTop = cl.scrollHeight; else if (AI_SCROLL === "top" || !soft) cl.scrollTop = 0; else cl.scrollTop = AI_KEEP; AI_SCROLL = "" }
}

/* ------------------------------------------------------------ 메뉴 바 (Windows 표준 앱 스타일: 드롭다운 목록 + 단축키) */
const UA_APP = /DBXDesktop\/([\d.]+)/.exec(navigator.userAgent || "");
const IS_APP = !!UA_APP, APP_VER = UA_APP ? UA_APP[1] : "", IS_PHONE = /Android|iPhone|iPad|iPod|Mobile/i.test(navigator.userAgent || ""), IS_MACOS = /Mac/.test(navigator.platform || "") && !/iPhone|iPad/.test(navigator.userAgent || ""), IS_SA = /DBXDesktop\/[\d.]+ Standalone/.test(navigator.userAgent || "");
let MENUOPEN = -1, UPD_SHOWN = "", POLL = null;
function menuModel() {
  const stf = staff(), adm = ME?.role === "admin";
  const ms = SYS.menu.map(t => ({ title: t.tab, items: t.items.filter(i => (stf || adm || i.view !== "rvw") && (adm || (i.view !== "fbq" && i.view !== "usage"))).map(i => ({ label: i.label, tip: i.desc, a: "nav", v: i.view })) }));
  ms.push({
    title: "도움말", items: [
      { label: "사용 안내", key: "F1", a: "helptoggle" },
      { label: "AI 지원", key: "Alt+Shift+A", a: "aitoggle" },
      { label: "피드백 보내기 (AXOS)", key: "Alt+Shift+F", a: "axos" },
      { label: "단축키 안내", key: "Alt+Shift+K", a: "keyhelp" },
      { sep: 1 },
      { label: "업데이트 확인", key: "Alt+Shift+U", a: "sysupdate" },
      { label: "시스템 정보", key: "Alt+Shift+I", a: "sysinfo" },
      ...(IS_APP || ME?.role !== "admin" ? [] : [{ label: "시스템문서.md 다운로드", key: "Alt+Shift+D", a: "sysdoc" }]),
      { sep: 1 },
      ...(IS_APP ? [{ label: "이 앱 정보", a: "appinfo" }] : [{ label: IS_MACOS ? "Mac 설치형 앱 다운로드" : "Windows 설치형 앱 다운로드", a: "appdl" }])
    ]
  });
  ms.forEach(m => { let n = 0; m.items.forEach(i => { if (!i.sep) i.no = ++n }) });
  return ms;
}
function menubarHtml() {
  if (!SYS) return "";
  const ms = menuModel(), cur = ms.findIndex(m => m.items.some(i => i.v === VIEW));
  return `<div class="menubar" role="menubar" aria-label="전역 메뉴">${ms.map((m, n) => `<div class="mn ${n === cur ? "cur" : ""}" data-m="${n}">
    <button class="mt" role="menuitem" aria-haspopup="true" aria-expanded="false" data-a="mopen" data-n="${n}" title="Alt+${n + 1}">${esc(m.title)}<u>${n + 1}</u></button>
    <div class="mdrop" role="menu">${m.items.map((i, k) => i.sep ? `<div class="msep"></div>` : `<button class="mi ${i.v && VIEW === i.v ? "on" : ""}" role="menuitem" data-a="mpick" data-n="${n}" data-k="${k}" title="${esc(i.tip || "")}"><span class="mnum">${i.no <= 9 ? i.no : ""}</span><span class="ml">${esc(i.label)}</span><span class="mk">${esc(i.key || "")}</span></button>`).join("")}</div></div>`).join("")}
    <span class="rsp"></span><span class="rver" title="빌드 ${esc(SYS.build)}">v${esc(SYS.version)}${IS_APP ? " · PC 앱 " + esc(APP_VER) : ""}</span></div>`;
}
function mobileBar() {
  if (!SYS) return "";
  const t = viewLabel(VIEW).replace(/^.*> /, "");
  return `<div class="mobbar"><button class="mb-menu" data-a="mnavopen" aria-label="메뉴 열기">☰ <span>메뉴</span></button><span class="mb-title">${esc(t)}</span><button class="mb-ic" data-a="helptoggle" aria-label="도움말">${ICON.help}</button><button class="mb-ic" data-a="aitoggle" aria-label="AI 지원">${ICON.spark}${GUIDE && GUIDE.next ? '<i class="pulse"></i>' : ""}</button><button class="mb-ic" data-a="axostoggle" aria-label="피드백(AXOS)">${ICON.axos}${FB_UNSEEN ? '<i class="pulse"></i>' : ""}</button></div>
  <div class="mnav" id="mnav" role="dialog" aria-label="전체 메뉴"><div class="mnh"><b>전체 메뉴</b><button class="ghost" data-a="mnavclose">닫기 ✕</button></div><div class="mnb">${menuModel().map((m, n) => `<details ${m.items.some(i => i.v === VIEW) ? "open" : ""}><summary>${esc(m.title)}</summary>${m.items.map((i, k) => i.sep ? "" : `<button class="mnitem ${i.v && VIEW === i.v ? "on" : ""}" data-a="mnavpick" data-n="${n}" data-k="${k}">${esc(i.label)}</button>`).join("")}</details>`).join("")}</div></div>`;
}
function menuSet(n) {
  MENUOPEN = n;
  document.querySelectorAll(".menubar .mn").forEach((el, i) => { el.classList.toggle("open", i === n); const b = el.querySelector(".mt"); if (b) b.setAttribute("aria-expanded", String(i === n)) });
}
function menuFocus(n, k) { const l = [...document.querySelectorAll(`.menubar .mn[data-m="${n}"] .mi`)]; if (l.length) l[(k + l.length) % l.length].focus() }
function menuPick(n, k) {
  const it = menuModel()[n]?.items[k]; if (!it || it.sep) return;
  menuSet(-1); const h = H[it.a]; if (h) h(it.v ? { v: it.v } : {});
}
const HOTKEYS = { KeyA: "aitoggle", KeyU: "sysupdate", KeyI: "sysinfo", KeyK: "keyhelp", KeyD: "sysdoc", KeyF: "axos" };
document.addEventListener("keydown", ev => {
  if (!TOKEN || !SYS) return;
  const code = ev.code || "";
  if (ev.key === "F1") { ev.preventDefault(); H.helptoggle(); return }
  if (ev.key === "F10" || (ev.altKey && !ev.ctrlKey && !ev.shiftKey && /^Digit[1-9]$/.test(code))) {
    ev.preventDefault(); const nm = SYS.menu.length + 1;
    const n = ev.key === "F10" ? (MENUOPEN >= 0 ? -1 : 0) : (+code.slice(5) - 1 === MENUOPEN ? -1 : +code.slice(5) - 1);
    if (n >= nm) return; menuSet(n); if (n >= 0) menuFocus(n, 0); return;
  }
  if (ev.altKey && ev.shiftKey && !ev.ctrlKey && HOTKEYS[code]) { const a = HOTKEYS[code]; if (a === "sysdoc" && (IS_APP || ME?.role !== "admin")) return; ev.preventDefault(); H[a]({}); return }
  if (MENUOPEN < 0) { if (ev.key === "Escape" && (SYSPOP || REMEDY_POP)) { SYSPOP = ""; REMEDY_POP = null; render(true) } return }
  const nm = SYS.menu.length + 1;
  if (ev.key === "Escape") { ev.preventDefault(); menuSet(-1); return }
  if (ev.key === "ArrowRight") { ev.preventDefault(); const n = (MENUOPEN + 1) % nm; menuSet(n); menuFocus(n, 0); return }
  if (ev.key === "ArrowLeft") { ev.preventDefault(); const n = (MENUOPEN + nm - 1) % nm; menuSet(n); menuFocus(n, 0); return }
  if (ev.key === "ArrowDown" || ev.key === "ArrowUp") {
    ev.preventDefault(); const l = [...document.querySelectorAll(`.menubar .mn[data-m="${MENUOPEN}"] .mi`)]; if (!l.length) return;
    const i = l.indexOf(document.activeElement); l[(i + (ev.key === "ArrowDown" ? 1 : -1) + l.length) % l.length].focus(); return
  }
  if (/^Digit[1-9]$/.test(code) && !ev.altKey && !ev.ctrlKey) { const no = +code.slice(5), m = menuModel()[MENUOPEN]; const k = m.items.findIndex(i => i.no === no); if (k >= 0) { ev.preventDefault(); menuPick(MENUOPEN, k) } }
});
document.addEventListener("mouseover", ev => { if (MENUOPEN < 0) return; const m = ev.target.closest && ev.target.closest(".menubar .mn"); if (m) { const n = +m.dataset.m; if (n !== MENUOPEN) menuSet(n) } });
const verCmp = (a, b) => { const x = String(a).split(".").map(Number), y = String(b).split(".").map(Number); for (let i = 0; i < 3; i++) { if ((x[i] || 0) !== (y[i] || 0)) return (x[i] || 0) - (y[i] || 0) } return 0 };
async function pollUpdate(manual) {
  if (!TOKEN || !SYS) return null;
  try {
    const u = await api("/api/system/update-check?build=" + encodeURIComponent(CLIENT_BUILD || ""));
    const shell = IS_APP && u.app && (u.app.update_available !== undefined ? u.app.update_available : verCmp(u.app.shell_version, APP_VER) > 0);
    if (!manual) {
      const key = (u.update_available ? u.server_build : "") + "|" + (shell ? u.app.shell_version : "");
      if (key === "|" || key === UPD_SHOWN) return u; UPD_SHOWN = key;
      SYSPOP = updateCardHtml(u, shell); render(true);
    }
    return u;
  } catch { return null }
}
function updateCardHtml(u, shell) {
  const parts = [];
  if (u.update_available) parts.push(`<div class="updbox"><b>사이트가 업데이트되었습니다</b> (서버 v${esc(u.server_version)} · 빌드 <code>${esc(u.server_build)}</code>)<div class="sub">지금 적용하면 화면을 새로 불러와 최신 기능을 사용합니다. 진행 중 입력은 저장 후 적용하세요.</div><p><button class="primary" data-a="sysreload">지금 적용</button> <button data-a="syspopclose">나중에</button></p></div>`);
  if (shell && IS_SA) parts.push(`<div class="updbox"><b>${u.app.kind === "pack" ? "기능 업데이트" : "새 버전"} ${esc(u.app.latest_version || "")}이(가) 있습니다</b> (현재 ${esc(APP_VER)})<div class="sub">${u.app.kind === "pack" ? `필요한 부분만 내려받아(약 ${Math.max(1, Math.round((u.app.size || 0) / 1024))}KB) 적용하고 앱을 자동으로 다시 시작합니다.` : "운영자 서버에서 새 설치 파일을 내려받아 교체합니다."} <b>내 학습 데이터는 유지</b>됩니다.</div><p><button class="primary" data-a="appupdate">지금 업데이트</button> <button data-a="syspopclose">나중에</button></p></div>`);
  else if (shell) parts.push(`<div class="updbox"><b>PC 앱 새 버전 ${esc(u.app.shell_version)}</b> (현재 ${esc(APP_VER)})<div class="sub">앱 자체(실행 파일)가 갱신되었습니다. 내려받아 실행하면 기존 앱을 교체 설치합니다.</div><p><button class="primary" data-a="appdl">새 버전 내려받기</button> <button data-a="syspopclose">나중에</button></p></div>`);
  return `<h3 style="margin-top:0">업데이트 알림</h3>${parts.join("")}`;
}
function nextBar() {
  if (!GUIDE || !GUIDE.next) return "";
  const n = GUIDE.next;
  return `<div class="nextbar"><span class="nbk">다음 단계 ${n.step_no}/${GUIDE.steps.length}</span><b>${esc(n.title)}</b><span class="mute">${esc(n.sub)}</span>${scBtn(n.shortcut, true)}<a href="#" data-a="stepsopen">전체 단계 보기</a><span class="nbsp"></span><span class="mute">F1 도움말 · Alt+Shift+A AI 지원</span></div>`;
}
function sysPop() {
  if (REMEDY_POP) return `<div class="syspop"><div class="syscard"><h3 style="margin-top:0">오류 해결 안내</h3>${remedyHtml(REMEDY_POP)}<div style="text-align:right;margin-top:12px"><button data-a="syspopclose">닫기</button></div></div></div>`;
  if (!SYSPOP) return "";
  return `<div class="syspop"><div class="syscard">${SYSPOP}<div style="text-align:right;margin-top:12px"><button data-a="syspopclose">닫기</button></div></div></div>`;
}
async function download(path, fallback) {
  const r = await fetch(path, { headers: { Authorization: "Bearer " + TOKEN } });
  if (!r.ok) { let m = r.statusText; try { m = (await r.json()).error.message } catch { } throw new Error(m) }
  let name = fallback; const cd = r.headers.get("content-disposition") || ""; const m = /filename\*=UTF-8''([^;]+)/.exec(cd); if (m) name = decodeURIComponent(m[1]);
  const b = await r.blob(), u = URL.createObjectURL(b), a = document.createElement("a"); a.href = u; a.download = name; document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(u), 2000);
  log("다운로드: " + name);
}
/* ------------------------------------------------------------ AXOS 탭 (피드백 폐루프 · 도메인 신청) */
const FB_FLOW = ["RECEIVED", "APPROVED", "QUEUED", "IN_DEV", "DONE"], FB_LBL = { RECEIVED: "접수", APPROVED: "검토·승인", QUEUED: "개발큐", IN_DEV: "개발중", DONE: "반영완료", REJECTED: "반려", ON_HOLD: "보류" };
const FB_KINDS = { CONNECT_REQUEST: "실제 환경 연결 신청", FEATURE: "기능 추가 요청", UI_BUG: "화면 버그", IMPROVE: "기능 개선", DBX_MISMATCH: "DBX와 맞지 않는 오류", CONTENT: "문항·자료 오류", OTHER: "기타" };
let FBMETA = null, FB = { kind: "UI_BUG", title: "", text: "", images: [] }, DOM = { domain: "", purpose: "", data: "", issues: "", when: "", text: "" }, AXTAB = "fb", MINE = null, FB_UNSEEN = 0, FBQ = { status: "", sel: null, checked: new Set(), edit: false, page: 0, size: 25, q: "", ids: [] };
const viewLabel = v => { for (const t of (SYS?.menu || [])) { const i = t.items.find(x => x.view === v); if (i) return t.tab + " > " + i.label } return v };
const fbBadge = s => badge(FB_LBL[s] || s, s === "DONE" ? "ok" : s === "REJECTED" ? "bad" : s === "ON_HOLD" ? "w" : "");
function fbSteps(s) {
  const at = FB_FLOW.indexOf(s);
  if (at < 0) return `<div class="fbsteps">${fbBadge(s)}</div>`;
  return `<div class="fbsteps">${FB_FLOW.map((x, i) => `<span class="${i < at ? "d" : i === at ? "c" : ""}">${FB_LBL[x]}</span>`).join("")}</div>`;
}
function axosHtml() {
  const head = `<div class="aih"><div class="aiti">${ICON.axos}<div><b>AXOS 피드백</b><small>제출 → 검토 → 개발큐 → 반영</small></div></div><button class="ghost ic" data-a="axostoggle" aria-label="닫기">${ICON.close}</button></div>
    <div class="aitabs">${[["fb", "피드백"], ["dom", "도메인 신청"], ["mine", "내 피드백" + (FB_UNSEEN ? ` <em>${FB_UNSEEN}</em>` : "")]].map(([k, l]) => `<button class="${AXTAB === k ? "on" : ""}" data-a="axtab" data-t="${k}">${l}</button>`).join("")}</div>`;
  let body = "";
  if (AXTAB === "fb") {
    body = `<div class="sub" style="margin:0 0 8px">대상 화면: <b>${esc(viewLabel(VIEW))}</b> <span class="mute">(자동 첨부 · 버전 v${esc(SYS?.version || "")} · ${IS_APP ? "PC 앱" : "웹"})</span></div>
      <label>유형</label><select onchange="FB.kind=this.value">${Object.entries(FB_KINDS).map(([k, l]) => `<option value="${k}" ${FB.kind === k ? "selected" : ""}>${l}</option>`).join("")}</select>
      <label>제목</label><input maxlength="120" value="${esc(FB.title)}" oninput="FB.title=this.value" placeholder="한 줄 요약 (예: SQL 결과가 잘립니다)">
      <label>내용 <small>(재현 절차 · 기대한 동작 · 실제 동작, DBX와 다르면 Databricks 화면/문서 근거)</small></label>
      <textarea rows="7" maxlength="4000" oninput="FB.text=this.value" onpaste="H.fbpaste(event)" placeholder="여기에 이미지를 붙여넣기(Ctrl+V)할 수도 있습니다.">${esc(FB.text)}</textarea>
      <label>이미지 첨부 <small>(최대 5장 · PNG/JPEG/GIF/WEBP · 장당 3MB)</small></label><input type="file" accept="image/png,image/jpeg,image/gif,image/webp" multiple onchange="H.fbfiles(this.files)">
      <div class="fbthumbs">${FB.images.map((im, i) => `<div class="th"><img src="${im.data}" alt=""><button class="ghost ic" data-a="fbimgdel" data-i="${i}" aria-label="삭제">✕</button></div>`).join("")}</div>
      <div class="fine" style="margin:8px 0">개인정보·고객정보·비밀번호·토큰이 보이는 화면은 가리고 제출하세요. 제출 내용은 admin(운영자)만 열람합니다.${IS_SA ? " 이 앱에서는 제출 내용(이름 포함)이 인터넷이 연결되면 운영자 서버로 전송되며, 오프라인이면 나중에 자동 전송됩니다." : ""}</div>
      <button class="primary wide" data-a="fbsubmit">피드백 제출</button>`;
  } else if (AXTAB === "dom") {
    const f = (k, l, ph, rows) => rows ? `<label>${l}</label><textarea rows="${rows}" maxlength="500" oninput="DOM.${k}=this.value" placeholder="${ph}">${esc(DOM[k])}</textarea>` : `<label>${l}</label><input maxlength="80" value="${esc(DOM[k])}" oninput="DOM.${k}=this.value" placeholder="${ph}">`;
    body = `<div class="sub" style="margin:0 0 8px">원하는 산업 도메인의 전이 시드·협업 훈련을 신청하세요. 신청 내용은 AXOS에 접수되어 운영자가 검토·승인 후 개발큐에서 관리하며, 진행 상태는 "내 피드백"에서 확인합니다. <b>합성 데이터 요청</b>만 받으며 실제 고객 데이터는 보내지 마세요.</div>
      ${f("domain", "도메인(산업)", "예: 물류·창고, 의료 청구, 금융 거래")}${f("purpose", "훈련 목적", "어떤 역량을 연습하고 싶은지", 2)}${f("data", "필요한 데이터·테이블", "예: 입출고 이벤트, 재고, 거래처", 2)}${f("issues", "심어 둘 데이터 문제", "예: 중복, 역순 도착, 이상치", 2)}${f("when", "희망 시기", "예: 12월 중")}
      <label>추가 설명</label><textarea rows="3" maxlength="2000" oninput="DOM.text=this.value">${esc(DOM.text)}</textarea><button class="primary wide" style="margin-top:10px" data-a="domsubmit">도메인 신청</button>`;
  } else {
    body = !MINE ? `<div class="mute">불러오는 중…</div>` : !MINE.items.length ? `<div class="empty small">제출한 피드백이 없습니다.</div>` : MINE.items.map(f => `<div class="fbitem"><div><b>${esc(f.title)}</b></div><div class="sub">${esc(f.id)} · ${esc(f.kind_label)} · ${esc(fmtIso(f.created))}${f.priority ? " · " + esc(f.priority) : ""}</div>${fbSteps(f.status)}
      ${IS_SA ? `<div class="mute">운영자 서버 전달: ${f.remote_state === "SENT" ? "전달됨" : "대기 중(인터넷 연결 시 자동 전송)"}</div>` : ""}${f.status === "DONE" ? `<div class="okbox">반영 완료 — v${esc(f.released_version || "")}${f.resolution ? "<br>" + esc(f.resolution) : ""}</div>` : ""}${f.status === "REJECTED" || f.status === "ON_HOLD" ? `<div class="warnbox">${esc(FB_LBL[f.status])} 사유: ${esc(f.resolution)}</div>` : ""}
      </div>`).join("");
  }
  return head + `<div class="aibody axbody">${body}</div>`;
}
function readImage(file) {
  return new Promise((res, rej) => {
    if (!/^image\/(png|jpeg|gif|webp)$/.test(file.type)) return rej(new Error("PNG·JPEG·GIF·WEBP 이미지만 첨부할 수 있습니다."));
    const r = new FileReader(); r.onerror = () => rej(new Error("이미지를 읽을 수 없습니다.")); r.onload = () => {
      const url = r.result; if (file.size < 1.2e6 || file.type === "image/gif") return res({ name: file.name || "paste.png", data: url });
      const im = new Image(); im.onerror = () => res({ name: file.name, data: url }); im.onload = () => {
        const k = Math.min(1, 1600 / Math.max(im.width, im.height)), c = document.createElement("canvas"); c.width = Math.round(im.width * k); c.height = Math.round(im.height * k);
        c.getContext("2d").drawImage(im, 0, 0, c.width, c.height); res({ name: (file.name || "paste").replace(/\.\w+$/, "") + ".jpg", data: c.toDataURL("image/jpeg", .82) })
      }; im.src = url
    }; r.readAsDataURL(file)
  })
}
async function fbAddFiles(files) {
  for (const f of [...files]) {
    if (FB.images.length >= 5) { toast("이미지는 최대 5장입니다."); break }
    try { const im = await readImage(f); if (im.data.length * 0.75 > 3 * 1048576) { toast(`${f.name || "이미지"}가 3MB를 넘습니다.`); continue } FB.images.push(im) } catch (e) { toast(e.message) }
  }
  render(true)
}
async function loadMine() { try { MINE = await api("/api/feedback/mine"); FB_UNSEEN = MINE.unseen_done } catch { MINE = { items: [] } } }
const fbCtx = () => ({ view: VIEW, view_label: viewLabel(VIEW), version: SYS?.version || "", build: CLIENT_BUILD || "", client: IS_APP ? "PC앱 " + APP_VER : "웹", viewport: innerWidth + "x" + innerHeight });
function aiHtml() {
  if (PANEL === "help") return helpHtml();
  if (PANEL === "axos") return axosHtml();
  const g = GUIDE;
  const ring = `<div class="ring" style="--p:${g ? g.percent : 0}"><b>${g ? g.percent : 0}<small>%</small></b></div>`;
  const head = `<div class="aih"><div class="aiti">${ICON.spark}<div><b>AI 지원</b><small>절차 안내 · 원인 진단 · 바로가기</small></div></div>${ring}<button class="ghost ic" data-a="aitoggle" aria-label="닫기">${ICON.close}</button></div>
    <div class="aitabs"><button class="${AI_TAB === "chat" ? "on" : ""}" data-a="aitab" data-t="chat">대화</button><button class="${AI_TAB === "steps" ? "on" : ""}" data-a="aitab" data-t="steps">전체 단계${g ? ` <em>${g.steps.filter(s => s.status === "done").length}/${g.steps.length}</em>` : ""}</button></div>`;
  if (AI_TAB === "steps") return head + `<div class="aibody" id="chatlog">${stepsHtml()}</div>`;
  const nx = g && g.next ? `<div class="nextcard"><div class="k">NEXT · ${g.next.step_no}단계</div><b>${esc(g.next.title)}</b><p>${esc(g.next.sub)}</p>${scBtn(g.next.shortcut, true)}</div>` : g ? `<div class="nextcard done"><div class="k">완료</div><b>모든 단계 증거 확보</b><p>증거 보고서를 검토하고 설명 평가를 받으세요.</p></div>` : "";
  return head + `<div class="aibody" id="chatlog">${nx}${CHAT.map(m => `<div class="msg ${m.r}"><div class="bub">${md(m.t)}</div>${(m.s || []).length ? `<div class="scs">${m.s.map(x => scBtn(x)).join("")}</div>` : ""}</div>`).join("")}${BUSY ? '<div class="msg ai"><div class="bub typing"><i></i><i></i><i></i></div></div>' : ""}</div>
    <div class="aiq">${["다음에 뭐 해?", "왜 실패했어?", "전체 절차 보여줘", "진행률"].map(q => `<button class="qchip" data-a="aiq" data-q="${q}">${q}</button>`).join("")}</div>
    <form class="aiin" onsubmit="return false"><input id="aimsg" placeholder="무엇이든 물어보세요 (예: 권한 오류가 왜 나요?)" autocomplete="off" onkeydown="if(event.key==='Enter'){event.preventDefault();H.aisend()}"><button class="send" data-a="aisend" aria-label="보내기">${ICON.send}</button></form>`;
}
const EXP = new Set(), SCS = [];
function stepsHtml() {
  if (!GUIDE) return `<div class="empty small">세션을 시작하면 전체 단계가 표시됩니다.</div>`;
  let phase = "";
  return `<div class="sub" style="margin:0 0 10px">${esc(GUIDE.note)}</div>` + GUIDE.steps.map(s => {
    const hd = s.phase !== phase ? (phase = s.phase, `<div class="phase">${esc(s.phase)}</div>`) : "";
    const open = s.status === "current" || EXP.has(s.id);
    return `${hd}<div class="step ${s.status}"><button class="sh" data-a="stepx" data-id="${s.id}"><span class="sn">${s.status === "done" ? ICON.check : s.no}</span><span class="stt"><b>${esc(s.title)}</b><small>${s.done}/${s.total} 항목</small></span></button>
      ${open ? `<div class="sb"><p>${esc(s.why)}</p>${s.subs.map(x => `<div class="ss ${x.done ? "d" : ""}"><span class="cb">${x.done ? ICON.check : ""}</span><div><span>${esc(x.text)}</span>${x.done ? "" : scBtn(x.shortcut)}</div></div>`).join("")}</div>` : ""}</div>`;
  }).join("");
}
function scBtn(sc, primary) { SCS.push(sc); return `<button class="sc ${primary ? "primary" : ""}" data-a="sc" data-i="${SCS.length - 1}">${esc(sc.label)} ${ICON.arrow}</button>` }
async function runShortcut(sc) {
  if (sc.type === "ai") { REMEDY_POP = null; SYSPOP = ""; AI_OPEN = true; PANEL = "ai"; AI_TAB = "chat"; ls.set("ai", "1"); ls.set("panel", "ai"); await aiAsk(sc.q); return }
  if (sc.type === "help") { REMEDY_POP = null; SYSPOP = ""; AI_OPEN = true; PANEL = "help"; ls.set("ai", "1"); ls.set("panel", "help"); await render(true); return }
  if (sc.type === "axos") {
    REMEDY_POP = null; SYSPOP = ""; FB.kind = sc.kind || "OTHER"; if (sc.title) FB.title = sc.title; if (sc.text) FB.text = sc.text; if (sc.err) { FB.title = `오류 ${sc.err.code}`; FB.text = `발생 화면: ${viewLabel(VIEW)}\n오류: ${sc.err.code} — ${sc.err.message}\n\n(기대한 동작 / 재현 절차를 적어 주세요)\n` }
    AXTAB = "fb"; AI_OPEN = true; PANEL = "axos"; ls.set("ai", "1"); ls.set("panel", "axos"); await render(true); return
  }
  if (sc.type === "reload") { location.reload(); return }
  REMEDY_POP = null; SYSPOP = "";
  if (sc.type === "nav") { VIEW = sc.view; ls.set("view", VIEW); PREFILL = sc.prefill || null; if (sc.prefill && sc.prefill.sqlbox) LAST.sqlq = sc.prefill.sqlbox; await render(true); return }
  if (sc.type === "cmd") {
    const ex = await cmd(sc.command_type, sc.payload || {});
    if (sc.view) { VIEW = sc.view; ls.set("view", VIEW) }
    if (ex) { if (ex.type === "order.propose") LAST.prop = ex.result; if (ex.type === "sql.execute") LAST.sql = ex }
    await render(true)
  }
}
async function aiAsk(q) {
  q = (q || "").trim(); if (!q || BUSY) return;
  CHAT.push({ r: "me", t: q }); BUSY = true; saveChat(); AI_SCROLL = "bottom"; render(true);
  try { const r = await api("/api/guide/chat", { body: { message: q, session_id: SID, view: VIEW } }); CHAT.push({ r: "ai", t: r.answer, s: r.shortcuts }) } catch (e) { CHAT.push({ r: "ai", t: "응답 오류: " + e.message }) }
  BUSY = false; saveChat(); AI_SCROLL = "bottom"; await render(true); const mi = $("#aimsg"); if (mi) mi.focus();
}
function renderLogin(app) {
  app.className = "";
  app.innerHTML = `<div class="loginwrap"><div class="hero"><div class="brand big"><img class="logobig logo-l" src="/static/logo.png" alt="wizbase"><img class="logobig logo-d" src="/static/logo-white.png" alt="" aria-hidden="true"><div><span>DBX Project Rehearsal</span></div></div><h1>Databricks 현장 PoC,<br>실전 전에 리허설하다.</h1><p>권한·데이터·파이프라인·승인·배포까지 실제 작업 순서대로 훈련하고, 모든 결과를 증거로 남기는 글로벌 AX 프로젝트용 시뮬레이터.</p>
    <ul><li>단계별 AI 지원과 바로가기</li><li>입력에 따라 달라지는 실행 결과 (고정 성공 없음)</li><li>모의·로컬 실행·실제 검증을 구분하는 증거 보고서</li></ul></div>
    <div class="lcard"><h2>로그인</h2><div class="sub">교육 역할과 DBX 권한은 별도 모델입니다.</div><label>이름 <small>(필수 · 실명)</small></label><input id="ln" maxlength="40" placeholder="실명을 입력하세요 (예: 홍길동)" autocomplete="name" onkeydown="if(event.key==='Enter')H.login()"><label>역할</label><select id="lr"><option value="learner">학습자 — 코드 불필요</option><option value="admin">admin — 수퍼유저 (UC 관리자·시스템 문서·피드백 관리)</option><option value="reviewer">리뷰어 / 승인자</option><option value="instructor">강사</option></select><label>접근 코드 <small>(admin·검토자·강사 — 역할별 별도 코드)</small></label><input id="lc" type="password" placeholder="••••••••" onkeydown="if(event.key==='Enter')H.login()"><button class="primary wide" data-a="login">시작하기</button><div id="lerr" class="bad"></div>
    ${IS_APP ? "" : IS_PHONE ? `<div class="dlbox"><b>모바일에서도 바로 이용할 수 있어요</b><div class="mute">설치 없이 이 화면에서 로그인해 모든 작업을 해 볼 수 있습니다. 화면이 좁으면 왼쪽 위 ☰ 메뉴로 이동하고, 오른쪽 위 아이콘으로 도움말·AI 지원·피드백을 엽니다. (PC에서는 설치형 앱을 권장합니다.)</div></div>` : `<div class="dlbox" id="dlbox"><b>${IS_MACOS ? "Mac" : "Windows"} 설치형 앱 (권장)</b><div class="mute">내 PC에서 단독으로 실행됩니다. 서버가 앱 안에 들어 있어 접속자가 많아도 느려지지 않고, 운영자 PC가 꺼져 있어도 학습할 수 있습니다. 학습 데이터는 내 PC에만 저장됩니다.</div>${IS_MACOS ? `<button class="primary" data-a="appdl" data-k="mac-arm64">Apple Silicon 용 다운로드 (M1 이상)</button> <button data-a="appdl" data-k="mac-x64">Intel Mac 용</button>` : `<button class="primary" data-a="appdl" data-k="standalone">단독 설치형 다운로드 (.exe)</button>`}<div class="mute" id="dlinfo"></div><div class="mute" style="margin-top:8px">${IS_MACOS ? "Windows용은 Windows PC에서 같은 주소로 받으세요. " : "Mac용은 Mac에서 같은 주소로 받으세요. "}설치가 어렵다면 위 로그인으로 웹에서 체험할 수도 있습니다(운영자 PC 상태에 따라 느리거나 접속이 안 될 수 있음).</div></div>`}<div class="fine">WIZBASE 교육 환경 · Databricks 공식 제품·인증·교육과정이 아님 · 합성 데이터 전용</div></div></div>`;
  if (!IS_APP && !IS_PHONE) fetch("/api/app/manifest").then(r => r.json()).then(m => { const e = $("#dlinfo"), b = $("#dlbox"); const L = IS_MACOS ? [["Apple Silicon", m.mac_arm64], ["Intel", m.mac_x64]] : [["Windows", m.standalone]];
    const ok = L.filter(([, x]) => x && x.available); if (!ok.length && b) { b.querySelectorAll("button").forEach(x => x.disabled = true); if (e) e.textContent = "설치 파일을 준비 중입니다." }
    else if (e) e.textContent = ok.map(([n, x]) => `${n}: 버전 ${x.version} · ${(x.size / 1048576).toFixed(0)} MB`).join(" / ") + (IS_MACOS ? " · 코드 서명이 없어 처음 실행 시 우클릭 > 열기가 필요합니다." : " · Windows 10/11 64비트 · 코드 서명이 없어 처음 실행 시 SmartScreen 경고가 표시될 수 있습니다.") }).catch(() => { });
}
document.addEventListener("change", ev => { const t = ev.target; if (t && t.classList && t.classList.contains("fbchk")) { t.checked ? FBQ.checked.add(t.dataset.id) : FBQ.checked.delete(t.dataset.id) } if (t && t.classList && t.classList.contains("sesschk")) { t.checked ? SESSQ.checked.add(t.dataset.id) : SESSQ.checked.delete(t.dataset.id) } });
document.addEventListener("click", async ev => {
  if (MENUOPEN >= 0 && !ev.target.closest(".menubar")) menuSet(-1);
  if (ev.target.classList && ev.target.classList.contains("syspop")) { SYSPOP = ""; REMEDY_POP = null; render(true); return }
  const t = ev.target.closest("[data-a]"); if (!t) return; ev.preventDefault();
  const a = t.dataset.a; const h = H[a]; if (h) { try { await h(t.dataset, t) } catch (e) { log(`✗ ${e.message}`, true); const x = $("#lerr"); if (x) x.textContent = e.message } }
});

/* ------------------------------------------------------------ handlers */
window.addEventListener("resize", () => { try { const mb = document.querySelector(".menubar"); if (mb) document.documentElement.style.setProperty("--aitop", Math.round(mb.getBoundingClientRect().bottom) + "px") } catch { } });
window.H = {
  async realsave() {
    try { const r = await api("/api/real/config", { body: { host: val("rh"), warehouse_id: val("rw"), catalog: val("rc"), schema: val("rs"), token: val("rt"), consent: $("#rco")?.checked, confirm_nonprod: $("#rnp")?.checked, write_allowed: $("#rwr")?.checked } }); log("실제 연결 설정을 저장했습니다. [연결 테스트]로 내 계정을 확인하세요."); const t = $("#rt"); if (t) t.value = ""; REAL = r; render(true) }
    catch (e) { log("실제 연결 저장 ✗ " + e.message, true, e.data); toast(e.message) }
  },
  async realtest() { try { await api("/api/real/test", { body: {} }); log("연결 테스트 성공 — 확인된 계정이 맞는지 보세요."); render(true) } catch (e) { log("연결 테스트 ✗ " + e.message, true, e.data); toast(e.message) } },
  async realclear() { try { await api("/api/real/config", { method: "DELETE" }); LAST.real = null; log("연결 설정과 토큰을 삭제했습니다."); render(true) } catch (e) { log("삭제 ✗ " + e.message, true, e.data) } },
  async realrun() {
    LAST.realsql = val("rsql");
    try { LAST.real = await api("/api/real/sql", { body: { sql: LAST.realsql, confirm: $("#rcf")?.checked } }); log(`실제 SQL 실행 → ${LAST.real.keyword} ${LAST.real.rows.length}행 [${LAST.real.evidence_level}]`) } catch (e) { LAST.real = null; log("실제 SQL ✗ " + e.message, true, e.data); toast(e.message) }
    render(true)
  },
  realgo() { const f = $("#realform"); if (f && f.scrollIntoView) f.scrollIntoView({ behavior: "smooth" }) },
  usagerefresh() { USG.at = 0; render(true) },
  mnavopen() { const e = document.querySelector("#mnav"); if (e) e.classList.add("open") },
  mnavclose() { const e = document.querySelector("#mnav"); if (e) e.classList.remove("open") },
  mnavpick(d) { H.mnavclose(); menuPick(+d.n, +d.k) },
  usagedays(d) { USG.days = +d.n; USG.page = 0; USG.upage = 0; render(true) },
  usagefilter() { USG.kind = val("uskind") || ""; USG.q = val("usq") || ""; USG.page = 0; render(true) },
  usagepage(d) { USG.page = Math.max(0, +d.p); render(true) },
  usagepagesize(v) { USG.size = +v; USG.page = 0; render(true) },
  usageclear() { USG.kind = ""; USG.q = ""; USG.page = 0; render(true) },
  usersearch() { USG.uq = (val("usuq") || "").trim(); USG.upage = 0; render(true) },
  usersearchclear() { USG.uq = ""; USG.upage = 0; render(true) },
  userpage(d) { USG.upage = Math.max(0, +d.p); render(true) },
  userpagesize(v) { USG.usize = +v; USG.upage = 0; render(true) },
  sesssel() { const l = [...document.querySelectorAll(".sesschk")]; const all = l.length && l.every(x => x.checked); l.forEach(x => { x.checked = !all; all ? SESSQ.checked.delete(x.dataset.id) : SESSQ.checked.add(x.dataset.id) }); render(true) },
  sessselall() { SESSQ.checked = new Set([...SESSQ.checked, ...SESSQ.ids]); render(true) },
  sesssearch() { SESSQ.q = (val("sessq") || "").trim(); SESSQ.page = 0; render(true) },
  sesssearchclear() { SESSQ.q = ""; SESSQ.page = 0; render(true) },
  sesspage(d) { SESSQ.page = Math.max(0, +d.p); render(true) },
  sesspagesize(v) { SESSQ.size = +v; SESSQ.page = 0; render(true) },
  sessdel() {
    const ids = [...SESSQ.checked];
    if (!ids.length) { toast("삭제할 세션을 선택하세요."); return }
    PENDING_DEL = ids;
    SYSPOP = `<h3 style="margin-top:0">세션 삭제</h3><p><b>${ids.length}개</b> 세션을 삭제합니다. 세션의 데이터와 진행 기록이 사라지며 <b>되돌릴 수 없습니다</b>.</p><div class="sub">${ids.map(esc).join(", ")}</div><p><button class="primary" data-a="sessdelok">삭제</button> <button data-a="syspopclose">취소</button></p>`; render(true)
  },
  async sessdelok() {
    const r = await api("/api/sessions/delete", { body: { ids: PENDING_DEL } }); PENDING_DEL = []; SYSPOP = ""; SESSQ.checked = new Set();
    if (r.deleted.includes(SID)) { SID = null; ls.del("sid"); ST = null; GUIDE = null }
    log(`세션 ${r.deleted.length}개 삭제` + (r.denied.length ? ` · 권한 없음/없는 세션 ${r.denied.length}개 제외` : "")); await refresh()
  },
  axos(d) { AXTAB = d.t || "fb"; AI_OPEN = true; PANEL = "axos"; ls.set("ai", "1"); ls.set("panel", PANEL); if (AXTAB === "mine") H.axtab({ t: "mine" }); else render(true) },
  axostoggle() { if (AI_OPEN && PANEL === "axos") AI_OPEN = false; else { AI_OPEN = true; PANEL = "axos" } ls.set("ai", AI_OPEN ? "1" : "0"); ls.set("panel", PANEL); render(true) },
  async axtab(d) {
    AXTAB = d.t; if (!FBMETA) { try { FBMETA = await api("/api/feedback/meta") } catch { } }
    if (AXTAB === "mine") { await loadMine(); render(true); if (FB_UNSEEN) { try { await api("/api/feedback/mine/seen", { method: "POST", body: {} }) } catch { } FB_UNSEEN = 0 } } else render(true)
  },
  fbfiles(files) { fbAddFiles(files) },
  fbpaste(ev) { const fs = [...(ev.clipboardData?.files || [])].filter(f => f.type.startsWith("image/")); if (fs.length) { ev.preventDefault(); fbAddFiles(fs) } },
  fbimgdel(d) { FB.images.splice(+d.i, 1); render(true) },
  async fbsubmit() {
    if (FB.title.trim().length < 1 || FB.text.trim().length < 5) { toast("제목과 내용(5자 이상)을 입력하세요."); return }
    const r = await api("/api/feedback", { body: { kind: FB.kind, title: FB.title, text: FB.text, view: VIEW, context: fbCtx(), images: FB.images.map(i => ({ name: i.name, data: i.data })) } });
    log(`피드백 접수 ${r.id} (이미지 ${r.images}장) — 진행 상태는 AXOS > 내 피드백에서 확인`); FB = { kind: "UI_BUG", title: "", text: "", images: [] }; await H.axtab({ t: "mine" })
  },
  async domsubmit() {
    if (!DOM.domain.trim()) { toast("도메인(산업)을 입력하세요."); return }
    const r = await api("/api/feedback", { body: { kind: "DOMAIN_REQUEST", title: "도메인 신청: " + DOM.domain.trim(), text: DOM.text.trim() || DOM.purpose.trim() || "(상세 미기재)", view: VIEW, context: fbCtx(), domain: { domain: DOM.domain, purpose: DOM.purpose, data: DOM.data, issues: DOM.issues, when: DOM.when } } });
    log(`도메인 신청 접수 ${r.id} — 진행 상태는 AXOS > 내 피드백에서 확인`); DOM = { domain: "", purpose: "", data: "", issues: "", when: "", text: "" }; await H.axtab({ t: "mine" })
  },
  fbfilter(d) { FBQ.status = d.s || ""; FBQ.sel = null; FBQ.page = 0; render(true) },
  fbsearch() { FBQ.q = (val("fbqq") || "").trim(); FBQ.page = 0; render(true) },
  fbsearchclear() { FBQ.q = ""; FBQ.page = 0; render(true) },
  fbpage(d) { FBQ.page = Math.max(0, +d.p); render(true) },
  fbpagesize(v) { FBQ.size = +v; FBQ.page = 0; render(true) },
  fbselresult() { FBQ.checked = new Set([...FBQ.checked, ...FBQ.ids]); render(true) },
  fbopen(d) { FBQ.sel = d.id; render(true) },
  fbclose() { FBQ.sel = null; FBQ.edit = false; render(true) },
  fbselall() { const l = [...document.querySelectorAll(".fbchk")]; const all = l.length && l.every(x => x.checked); l.forEach(x => { x.checked = !all; all ? FBQ.checked.delete(x.dataset.id) : FBQ.checked.add(x.dataset.id) }); render(true) },
  fbediton() { FBQ.edit = true; render(true) },
  fbeditoff() { FBQ.edit = false; render(true) },
  async fbsaveedit() {
    try { await api(`/api/feedback/${FBQ.sel}/edit`, { body: { title: val("fbet"), text: val("fbex"), kind: val("fbek"), priority: val("fbep") || null } }); log(`${FBQ.sel} 수정했습니다.`); FBQ.edit = false; render(true) } catch (e) { log("수정 ✗ " + e.message, true, e.data); toast(e.message) }
  },
  fbdelone(d) { FBQ.checked = new Set([d.id]); H.fbdel() },
  fbdel() {
    const ids = [...document.querySelectorAll(".fbchk")].filter(x => x.checked).map(x => x.dataset.id); const sel = ids.length ? ids : [...FBQ.checked];
    if (!sel.length) { toast("삭제할 피드백을 선택하세요."); return }
    FBQ.checked = new Set(sel); SYSPOP = `<h3 style="margin-top:0">피드백 삭제</h3><p><b>${sel.length}건</b>을 삭제합니다. 첨부 이미지까지 함께 지워지며 <b>되돌릴 수 없습니다</b>. 제출자의 '내 피드백'에서도 사라집니다.</p><div class="sub">${sel.map(esc).join(", ")}</div><p><button class="danger" data-a="fbdelok">삭제</button> <button data-a="syspopclose">취소</button></p>`; render(true)
  },
  async fbdelok() { const ids = [...FBQ.checked]; SYSPOP = ""; try { const r = await api("/api/feedback/delete", { body: { ids } }); FBQ.checked = new Set(); if (r.deleted.includes(FBQ.sel)) FBQ.sel = null; log(`피드백 ${r.deleted.length}건 삭제` + (r.missing.length ? ` · 없는 건 ${r.missing.length}건` : "")) } catch (e) { log("삭제 ✗ " + e.message, true, e.data) } render(true) },
  async fbbulk() {
    const ids = [...document.querySelectorAll(".fbchk")].filter(x => x.checked).map(x => x.dataset.id), to = val("fbbto");
    if (!ids.length) { toast("변경할 피드백을 선택하세요."); return } if (!to) { toast("바꿀 상태를 고르세요."); return }
    try { const r = await api("/api/feedback/bulk", { body: { ids, to, note: val("fbbnote") || "", released_version: val("fbbrel") || null } }); FBQ.checked = new Set(r.failed.map(x => x.id)); log(`일괄 변경: 성공 ${r.ok.length}건` + (r.failed.length ? ` · 건너뜀 ${r.failed.length}건(${r.failed.slice(0, 3).map(x => x.id + ": " + x.message).join(" / ")})` : ""), r.failed.length > 0) } catch (e) { log("일괄 변경 ✗ " + e.message, true, e.data) }
    render(true)
  },
  async fbmove(d) {
    const r = await api(`/api/feedback/${FBQ.sel}/transition`, { body: { to: d.to, note: val("fbnote") || "", priority: val("fbprio") || null, released_version: val("fbrel") || null } });
    log(`${r.id} → ${FB_LBL[r.status]}${r.status === "QUEUED" ? " (개발 지시서 생성됨)" : ""}`); render(true)
  },
  async fbqueue() { await download("/api/feedback/queue.md", "개발큐.md") },
  mopen(d) { menuSet(MENUOPEN === +d.n ? -1 : +d.n) },
  mpick(d) { menuPick(+d.n, +d.k) },
  keyhelp() {
    SYSPOP = `<h3 style="margin-top:0">단축키 안내</h3>${table(["키", "동작"], [["F10", "메뉴 바 활성화(첫 메뉴 열기)"], ["Alt + 1 ~ 7", "해당 번호의 메뉴 열기/닫기 (7 = 도움말)"], ["↑ ↓ ← →", "열린 메뉴 안에서 항목·메뉴 이동"], ["숫자 1 ~ 9", "열린 메뉴의 해당 번호 항목 실행"], ["Enter / Esc", "항목 실행 / 메뉴 닫기"], ["F1", "사용 안내(HELP) 열기·닫기"], ["Alt + Shift + A", "AI 지원"], ["Alt + Shift + F", "피드백 보내기(AXOS 탭)"], ["Alt + Shift + U", "업데이트 확인"], ["Alt + Shift + I", "시스템 정보"], ["Alt + Shift + K", "단축키 안내"], ...(IS_APP || ME?.role !== "admin" ? [] : [["Alt + Shift + D", "시스템문서.md 다운로드(admin)"]])])}`; render(true)
  },
  appdl(d) {
    const MAP = { standalone: ["/download/standalone", "WIZBASE-DBX-Standalone.exe"], shell: ["/download/app", "WIZBASE-DBX-Rehearsal.exe"], "mac-arm64": ["/download/standalone-mac-arm64", "WIZBASE-DBX-Standalone-mac-arm64.zip"], "mac-x64": ["/download/standalone-mac-x64", "WIZBASE-DBX-Standalone-mac-x64.zip"] };
    if (IS_SA) { H.appupdate(); return }
    if (IS_MACOS && (!d || !d.k)) {   // 메뉴에서 눌렀을 때: Mac은 CPU 종류를 고르게 한다
      SYSPOP = `<h3 style="margin-top:0">Mac 설치형 앱 다운로드</h3><p>사용 중인 Mac의 CPU를 선택하세요. (  메뉴 > 이 Mac에 관하여 에서 확인: "칩 Apple M…"이면 Apple Silicon, "프로세서 Intel…"이면 Intel)</p><p><button class="primary" data-a="appdl" data-k="mac-arm64">Apple Silicon (M1 이상)</button> <button data-a="appdl" data-k="mac-x64">Intel Mac</button></p><div class="sub">내려받은 zip을 풀고 "WIZBASE DBX Rehearsal"을 응용 프로그램 폴더로 옮긴 뒤, 처음에는 우클릭 > 열기로 실행하세요(서명되지 않은 앱이라 보안 경고가 표시됩니다).</div>`; render(true); return
    }
    const [url, fn] = MAP[(d && d.k) || "standalone"] || MAP.standalone;
    SYSPOP = ""; if (IS_APP && window.pywebview?.api?.open_external) { window.pywebview.api.open_external(location.origin + url); return }
    const a = document.createElement("a"); a.href = url; a.download = fn; document.body.appendChild(a); a.click(); a.remove(); log("설치 파일 내려받기를 시작했습니다.");
  },
  async appupdate() {
    const api_ = window.pywebview?.api; if (!api_) { toast("앱 안에서만 업데이트할 수 있습니다."); return }
    await api_.apply_update();
    SYSPOP = `<h3 style="margin-top:0">업데이트</h3><div id="updprog" class="sub">시작하는 중…</div><div style="background:var(--line);border-radius:6px;height:10px;overflow:hidden"><div id="updbar" style="height:10px;width:0;background:var(--acc)"></div></div>`; render(true);
    const t = setInterval(async () => { const s = await api_.update_state(); const m = $("#updprog"), b = $("#updbar"); if (m) m.textContent = s.msg; if (b) b.style.width = s.pct + "%"; if (s.state === "error" || s.state === "ready") clearInterval(t) }, 800)
  },
  async appinfo() {
    const u = await api("/api/system/update-check?build=" + encodeURIComponent(CLIENT_BUILD || ""));
    SYSPOP = IS_SA ? `<h3 style="margin-top:0">단독 설치형 앱 정보</h3>${table(["항목", "값"], [["앱 버전", APP_VER], ["최신 버전", u.app.offline ? "(확인 불가 — 오프라인)" : (u.app.latest_version || "?")], ["내 데이터 폴더", SYS.data_dir || "-"], ["서버", "이 PC 안(127.0.0.1)에서만 실행"]])}<div class="sub">서버가 앱에 포함되어 있어 인터넷 없이도 학습할 수 있습니다. 인터넷이 연결되면 새 버전 확인과 AXOS 피드백 전달이 이루어집니다. 시스템 문서와 admin 기능은 포함되지 않습니다.</div>${u.app.update_available ? `<p><button class="primary" data-a="appupdate">지금 업데이트</button></p>` : ""}`
      : `<h3 style="margin-top:0">PC 앱 정보</h3>${table(["항목", "값"], [["앱 버전", APP_VER], ["최신 앱 버전", u.app ? u.app.shell_version : "?"], ["접속 주소", location.origin], ["서버 버전", u.server_version]])}<div class="sub">이 앱은 ${esc(location.origin)} 사이트를 PC 창으로 여는 접속형 앱입니다.</div>${u.app && verCmp(u.app.shell_version, APP_VER) > 0 ? `<p><button class="primary" data-a="appdl" data-k="shell">새 앱 내려받기</button></p>` : ""}`; render(true)
  },
  async sysinfo() {
    SYS = await api("/api/system/info"); const c = SYS.counts;
    SYSPOP = `<h3 style="margin-top:0">${esc(SYS.name)}</h3><div class="sub">버전 <b>${esc(SYS.version)}</b> · 릴리스 ${esc(SYS.released)} · 빌드 <code>${esc(SYS.build)}</code> · Python ${esc(SYS.python)} · 가동 ${Math.floor(SYS.uptime_sec / 60)}분</div><p>${esc(SYS.purpose)}</p>
      ${table(["구분", "현황"], [["실습 팩", c.labs], ["공식 목표", c.objectives], ["문항", `${c.items} (${Object.entries(c.item_status).map(([k, v]) => k + " " + v).join(", ")})`], ["기능 매니페스트", c.features], ["전이 시드", c.transfer_seeds]])}
      <details open><summary><b>변경 이력</b></summary>${SYS.changelog.map(r => `<div><b>${esc(r.version)}</b> <span class="mute">${esc(r.date)}</span><ul>${r.notes.map(n => `<li>${esc(n)}</li>`).join("")}</ul></div>`).join("")}</details>
      ${ME.role === "admin" && !IS_APP ? `<div style="margin-top:8px"><button data-a="sysdoc">시스템문서.md 다운로드</button></div>` : ""}`; render(true)
  },
  async sysupdate() {
    const u = await api("/api/system/update-check?build=" + encodeURIComponent(CLIENT_BUILD || ""));
    if (IS_SA) { SYSPOP = u.app.update_available ? updateCardHtml(u, true) : `<h3 style="margin-top:0">업데이트 확인</h3><div class="sub">현재 v${esc(APP_VER)}</div><div style="padding:8px;color:var(--${u.app.offline ? "warn" : "ok"})">${u.app.offline ? "운영자 서버에 연결할 수 없어 확인하지 못했습니다(오프라인에서도 학습은 계속할 수 있습니다)." : "최신 상태입니다."}</div><div class="sub">${esc(u.how)}</div>`; render(true); return }
    SYSPOP = `<h3 style="margin-top:0">업데이트 확인</h3><div class="sub">현재 화면 빌드 <code>${esc(u.client_build || "?")}</code> · 서버 빌드 <code>${esc(u.server_build)}</code> · 서버 버전 ${esc(u.server_version)}</div>
      ${u.update_available ? `<div style="background:var(--warn-soft);color:var(--warn);border-radius:8px;padding:8px">새 버전이 적용되었습니다. 화면을 새로 불러와 최신 화면을 적용하세요.</div><p><button class="primary" data-a="sysreload">최신 화면 적용(새로고침)</button></p>` : `<div style="padding:8px;color:var(--ok)">최신 상태입니다.</div>`}
      <div class="sub">${esc(u.how)}</div><details><summary><b>최근 변경</b></summary>${u.changelog.map(r => `<div><b>${esc(r.version)}</b> ${esc(r.date)}<ul>${r.notes.map(n => `<li>${esc(n)}</li>`).join("")}</ul></div>`).join("")}</details>`; render(true)
  },
  sysreload() { location.reload() },
  stepsopen() { AI_OPEN = true; PANEL = "ai"; AI_TAB = "steps"; ls.set("ai", "1"); ls.set("panel", "ai"); AI_SCROLL = "top"; render(true) },
  syspopclose() { SYSPOP = ""; REMEDY_POP = null; render(true) },
  remedyopen() { REMEDY_POP = LASTERR; render(true) },
  hfix(d) { HFIX = HFIX === +d.i ? -1 : +d.i; render(true) },
  hreuse(d) { const h = HIST.sql[+d.i]; if (h) { LAST.sqlq = h.q; render(true) } },
  async sysdoc() { if (IS_APP || ME?.role !== "admin") { log("시스템 문서는 PC 앱에 포함되지 않습니다. 웹에서 내려받으세요.", true); return } await download("/api/system/document", "시스템문서.md") },
  async rvmanual() { await download("/api/review/manual", "검토자_매뉴얼.md") },
  async seeddl(d) { const j = await api(`/api/transfer-seeds/${d.id}/files`); for (const [n, t] of Object.entries(j.files)) { const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([t], { type: "text/csv;charset=utf-8" })); a.download = `${d.id}_${n}`; document.body.appendChild(a); a.click(); a.remove() } log(`${d.id} CSV ${Object.keys(j.files).length}개 다운로드`) },
  async seedkey(d) { const j = await api(`/api/transfer-seeds/${d.id}/answer-key`); LAST.seedkey = { id: d.id, key: j.answer_key }; render(true) },
  async teamnew() { const t = await api("/api/collab/teams", { body: { name: val("tm_name") || "팀" } }); LAST.team = t.team_id; render(true) },
  teamload() { LAST.team = val("tm_id"); render(true) },
  async teamjoin() { await api(`/api/collab/teams/${LAST.team}/join`, { body: { role: val("tm_role") } }); render(true) },
  async teamsubmit() { await api(`/api/collab/teams/${LAST.team}/tasks/${val("tm_task")}/submit`, { body: { artifact_sha256: val("tm_sha"), handoff_note: val("tm_note") } }); render(true) },
  async teamreview(d) { await api(`/api/collab/teams/${LAST.team}/tasks/${val("tm_task")}/review`, { body: { approve: d.ok === "1", reason: val("tm_reason") || "" } }); render(true) },
  async objverify(d) { await api(`/api/objectives/${d.id}/verify`, { body: { source_checked: true } }); log("원문 대조 기록: " + d.id); render(true) },
  async itemrev(d) { await api(`/api/items/${d.id}/review`, { body: { stage: d.stage } }); log(`문항 ${d.id} → ${d.stage}`); render(true) },
  async featcheck(d) { await api(`/api/features/${d.id}/recheck`, { body: { workspace_checked: true } }); log("워크스페이스 재확인 기록: " + d.id); render(true) },
  aitoggle() { if (AI_OPEN && PANEL === "ai") AI_OPEN = false; else { AI_OPEN = true; PANEL = "ai"; AI_SCROLL = "top" } ls.set("ai", AI_OPEN ? "1" : "0"); ls.set("panel", PANEL); render(true) },
  helptoggle() { if (AI_OPEN && PANEL === "help") AI_OPEN = false; else { AI_OPEN = true; PANEL = "help" } ls.set("ai", AI_OPEN ? "1" : "0"); ls.set("panel", PANEL); render(true) },
  aitab(d) { AI_TAB = d.t; AI_SCROLL = "top"; render(true) },
  stepx(d) { EXP.has(d.id) ? EXP.delete(d.id) : EXP.add(d.id); render(true) },
  async sc(d) { const sc = SCS[+d.i]; if (sc) await runShortcut(sc) },
  async aiq(d) { await aiAsk(d.q) },
  async aisend() { const v = $("#aimsg") && $("#aimsg").value; await aiAsk(v) },
  async login() {
    const nm = (val("ln") || "").trim(), x = $("#lerr");
    if (nm.length < 2 || ["학습자", "관리자", "검토자", "강사"].includes(nm)) { if (x) x.textContent = "실명을 입력하세요 (2자 이상). 세션과 피드백 관리에 이 이름이 표시됩니다."; const i = $("#ln"); if (i) i.focus(); return }
    const j = await api("/api/auth/login", { body: { name: nm, role: val("lr"), code: val("lc") || null } }); TOKEN = j.token; ls.set("tok", TOKEN); ME = null; ST = null;
    VIEW = ls.get("lv_" + nm.toLowerCase()) || "env"; ls.set("view", VIEW);   // 처음 접속은 시작 화면, 다시 접속하면 마지막 작업 화면
    render()
  },
  logout() { TOKEN = null; ME = null; ST = null; ls.del("tok"); render() },
  side() { SIDE = !SIDE; render(true) },
  nav(d) { VIEW = d.v; ls.set("view", VIEW); render(true) },
  async newsess() { const j = await api("/api/sessions", { body: { mode: val("mode"), learning_mode: val("lmode"), lesson_id: "UC-SELECT-01", seed: val("seedsel") } }); SID = j.session_id; ls.set("sid", SID); ST = null; GUIDE = null; loadChat(); await refresh() },
  async opensess(d) { SID = d.id; ls.set("sid", SID); ST = null; GUIDE = null; loadChat(); await refresh() },
  async hint() { const j = await api(`/api/sessions/${SID}/hints`); $("#hint").textContent = `[${j.level}/5] ${j.hint}`; await refresh() },
  async c(d, el) { const p = d.p ? JSON.parse(d.p) : {}; await cmd(d.t, p) },
  async sql() { const ex = await cmd("sql.execute", { sql: val("sqlbox"), as_principal: val("asp") || undefined }); LAST.sql = ex; HIST.sql.unshift({ q: val("sqlbox"), s: ex?.status, err: ex?.result?.error || null }); HFIX = ex?.result?.error ? 0 : -1; render(true) },
  async whstart() { await cmd("warehouse", { action: "start" }) }, async whstop() { await cmd("warehouse", { action: "stop" }) },
  async ticket() { await api("/api/permission-requests", { body: { session_id: SID, securable: val("t_sec"), privilege: val("t_priv"), reason: val("t_reason") } }).then(() => { log("권한 요청 티켓 생성"); return refresh() }).catch(e => log("✗ " + e.message, true)) },
  async resolve(d) { await api(`/api/sessions/${SID}/tickets/${d.id}/resolve`, { body: { decision: d.dec, note: "" } }).then(() => log("티켓 " + d.dec)).catch(e => log("✗ " + e.message, true)); await refresh() },
  async nbrun(d) { await cmd("notebook", { action: "run", cell_id: d.id }) },
  async nbedit(d) { await cmd("notebook", { action: "edit", cell_id: d.id, code: val("cell_" + d.id) }) },
  async nbadd(d) { await cmd("notebook", { action: "add_cell", lang: d.lang, code: d.lang === "python" ? "print('hello')" : "SELECT 1" }) },
  async nbrestart() { await cmd("notebook", { action: "restart" }) },
  async conn(d) { await cmd("connection", { action: d.x, mode: d.mode, category: val("diagcat") }) },
  async conntest() { await cmd("connection", { action: "test", host: val("chost") || undefined, password: val("cpass") || undefined }) },
  async pipe(d) { await cmd("pipeline", { action: d.x }) },
  async pipeedit() { await cmd("pipeline", { action: "edit", source_sql: val("plsql") }) },
  async pipeall() { await cmd("pipeline", { action: "edit", source_sql: val("plsql") }); await cmd("pipeline", { action: "validate" }); await cmd("pipeline", { action: "run" }) },
  async pipeas() { await cmd("pipeline", { action: "set_run_as", run_as: val("plas") }) },
  async job(d) { await cmd("job", { action: d.x }) },
  async jobas() { await cmd("job", { action: "set_run_as", run_as: val("jobas") }) },
  async jobtask(d) { await cmd("job", { action: "edit_task", task_key: d.k, sql: val("jt_" + d.k) }) },
  async genie() { await cmd("genie.ask", { question: val("gq"), as_persona: val("gp") || undefined }).then(() => refresh()) },
  async geniecfg() { await cmd("genie.config", { datasets: val("gds").split(",").map(s => s.trim()).filter(Boolean) }) },
  async facts() { const ex = await cmd("order.facts", { order_id: ST.case.order, requested_total: +val("req") }); LAST.facts = ex?.result; render(true) },
  async propose(d) { const ex = await cmd("order.propose", { order_id: ST.case.order, requested_total: +val("req"), alt_index: +(val("alt") || 0) }); LAST.prop = ex?.result; render(true) },
  async approve(d) { await api("/api/approvals", { body: { session_id: SID, proposal_id: d.id, payload_hash: val("ph_" + d.id) } }).then(() => log("승인 완료")).catch(e => log("✗ " + e.message, true)); await refresh() },
  async ax() { let pl; try { pl = JSON.parse(val("axpl")) } catch { return toast("payload JSON 오류") } try { const r = await api(`/api/sessions/${SID}/ax/orders/${ST.case.order}/change`, { body: { approval_id: val("axap"), payload: pl, idempotency_key: val("axk"), expected_version: +val("axv") } }); LAST.ax = r; log("가상 API 성공: " + JSON.stringify(r)) } catch (e) { LAST.ax = { error: e.data || e.message }; log("가상 API 차단: " + (e.data?.code || "") + " " + e.message, true) } await refresh() },
  async contract() { await cmd("contract.check") },
  async policydraft() { await cmd("policy.draft", { yaml: val("polyaml") }) }, async policyact() { await cmd("policy.activate") },
  async evalrun() { const ex = await cmd("eval.run"); LAST.eval = ex?.result; render(true) },
  async cli() { const line = val("clibox"); const ex = await cmd("cli", { line }); HIST.cli.unshift({ line, out: ex?.result?.stdout || ex?.result?.stderr || "", ok: ex?.status }); render(true) },
  async bfile(d) { ls.set("bf", val("bsel")); render(true) },
  async bsave() { await cmd("bundle.edit", { path: val("bsel"), content: val("bedit") }) },
  async fault(d) { await api("/api/instructor/faults", { body: { session_id: d.sid, fault_id: val("fsel") } }).then(r => log("장애 주입: " + r.description)).catch(e => log("✗ " + e.message, true)); await refresh() },
  async release(d) { await api("/api/instructor/faults/release", { body: { session_id: d.sid, fault_id: val("fsel") } }); await refresh() },
  async pause(d) { await api("/api/instructor/pause", { body: { session_id: d.sid, paused: d.p === "1" } }); render(true) },
  async reset(d) { if (!confirm("세션을 시드 상태로 초기화합니다(증거는 보존). 계속?")) return; const r = await api("/api/instructor/reset", { body: { session_id: d.sid } }); log("초기화: 보존 이벤트 " + r.preserved_evidence.audit_events); await refresh() },
  async ckpt(d) { await api("/api/instructor/checkpoint", { body: { session_id: d.sid, name: "cp1" } }); log("체크포인트 cp1") }, async restore(d) { await api("/api/instructor/restore", { body: { session_id: d.sid, name: "cp1" } }).then(() => log("복원")).catch(e => log("✗ " + e.message, true)); await refresh() },
  async replay(d) { const r = await api("/api/instructor/replay", { body: { session_id: d.sid } }); LAST.replay = r; render(true) },
  async explain(d) { const r = await api("/api/instructor/evaluate", { body: { session_id: d.sid, explain_score: +val("exs") } }); LAST.score = r; render(true) },
  async asrole(d) { PRINCIPAL = d.p; await refresh() },
  async ctab(d) { LAST.ctab = d.t; render(true) },
  async ctable(d) { LAST.tbl = await api(`/api/sessions/${SID}/catalog/table?name=${encodeURIComponent(d.n)}`); render(true) },
  /* v1.1 */
  async examstart(d) { LAST.att = await api("/api/exam-attempts", { body: { exam_id: val("exid"), kind: val("exk"), max_items: +val("exmax") || null } }).catch(e => { log("✗ " + e.message + (e.data?.shortfall ? " " + JSON.stringify(e.data.shortfall) : ""), true); return null }); render(true) },
  async examans(d) { const sel = [...document.querySelectorAll(`input[name="q_${d.i}"]:checked`)].map(x => x.value); LAST.ver = (LAST.ver || 0) + 1; await api(`/api/exam-attempts/${LAST.att.attempt_id}/responses`, { body: { item_id: d.i, answer: sel, client_version: LAST.ver } }).then(r => log("응답 저장 " + JSON.stringify(r))).catch(e => log("✗ " + e.message, true)) },
  async examsubmit() { LAST.att = await api(`/api/exam-attempts/${LAST.att.attempt_id}/submit`, { body: {} }); render(true) },
  async plan() { const dg = {}; document.querySelectorAll("[data-dom]").forEach(i => { if (i.value !== "") dg[i.dataset.dom] = +i.value }); LAST.plan = await api("/api/learning-plans", { body: { exam_id: val("plex"), diagnostic: dg, weekly_hours: +val("plwh") || 6 } }); render(true) },
  async tutor() { LAST.tutor = await api("/api/tutor/ask", { body: { question: val("tq"), hint_level: +val("thl") || null } }).catch(e => ({ status: "BLOCKED", answer: e.message })); render(true) },
  async recheck(d) { await api(`/api/features/${d.id}/recheck`, { body: { workspace_checked: false } }).then(() => log("문서 재확인 기록: " + d.id)).catch(e => log("✗ " + e.message, true)); render(true) },
  async matrixadd() { const row = { step: val("vx_step"), severity: val("vx_severity") }; ["feature_id", "profile_version", "doc_path", "observed_menu_path", "input", "actor_runas", "expected", "actual", "simulated_result", "diff", "owner", "evidence", "recheck_date"].forEach(c => row[c] = val("vx_" + c)); await api("/api/verification-matrix", { body: row }).then(() => log("대조 행 기록")).catch(e => log("✗ " + e.message, true)); render(true) },
  async costprofile() { await cmd("cost.set_profile", { unit_price: +val("cp_price"), currency: val("cp_cur"), source: val("cp_src"), as_of: val("cp_asof") }); render(true) },
  async privexport() { const r = await fetch("/api/learners/me/export", { headers: { Authorization: "Bearer " + TOKEN } }); const blob = new Blob([JSON.stringify(await r.json(), null, 1)], { type: "application/json" }); const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = "my-learning-data.json"; a.click() },
  async privdelete() { if (!confirm("학습 활동 데이터(응시·계획·자기 신고 자격·Academy 이력·미승인 증거)를 삭제합니다. 승인된 증거·등급·투입 승인·감사는 보존됩니다. 계속?")) return; const r = await api("/api/learners/me/delete", { body: {} }); log("삭제: " + JSON.stringify(r.deleted)); render(true) },
  async academyadd() { await api("/api/academy-records", { body: { course: val("ac_course"), completed_on: val("ac_date"), proof_ref: val("ac_proof") } }).then(() => log("Academy 이력 등록(확인대기)")).catch(e => log("✗ " + e.message, true)); render(true) },
  async cdcview() { const ex = await cmd("sql.execute", { sql: "SELECT * FROM food_dev.bronze.cdc_events ORDER BY seq" }); LAST.cdcrows = ex && ex.result.rows ? ex.result : null; render(true) },
  async cdccheck() { const ex = await cmd("cdc.check"); LAST.cdc = ex && ex.result; render(true) },
  async cdcrun() { LAST.cdcsql = val("cdcsql"); await cmd("sql.execute", { sql: LAST.cdcsql }); render(true) },
  async labpack(d) { const r = await fetch("/api/labs/" + d.id + "/pack", { headers: { Authorization: "Bearer " + TOKEN } }); const j = await r.json(); const blob = new Blob([JSON.stringify(j, null, 1)], { type: "application/json" }); const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = d.id + ".pack.json"; a.click(); log("팩 내려받기: " + d.id + " (hash " + (j.pack_hash || "").slice(0, 10) + ")") },
  async labjsonsubmit() { let ev; try { ev = JSON.parse(val("labjson")) } catch { return toast("evidence JSON 형식 오류") } ev.exam_id = val("labx"); await api("/api/lab-evidence", { body: ev }).then(r => log("증거 상태: " + r.status + " — " + (r.reason || ""), r.status.startsWith("REJECTED"))).catch(e => log("✗ " + e.message, true)); render(true) },
  labexam() { LAST.labexam = val("labex2"); render(true) },
  async labsubmit() { const b = {}; ["lab_id", "exam_id", "workspace_ref", "cloud", "region", "run_id", "source_hash", "result_checksum", "runtime_version", "observed_runtime_version", "claimed_runtime_version"].forEach(k => { const v = val("lb_" + k); if (v) b[k] = v }); await api("/api/lab-evidence", { body: b }).then(r => log("증거 상태: " + r.status + " " + (r.reason || ""))).catch(e => log("✗ " + e.message, true)); render(true) },
  async labreview(d) { await api(`/api/lab-evidence/${d.id}/review`, { body: { decision: d.dec, original_checked: !!($("#lbchk") && $("#lbchk").checked), rubric_scores: (() => { try { return JSON.parse(val("rubric") || "{}") } catch { return {} } })() } }).then(() => log("검토 완료")).catch(e => log("✗ " + e.message, true)); render(true) },
  async readiness() { LAST.ready = await api("/api/readiness-decisions", { body: { exam_id: val("rdx") } }); render(true) },
  async credadd() { await api("/api/credentials", { body: { name: val("crn") } }); render(true) },
  async itemrev(d) { await api(`/api/items/${d.id}/review`, { body: { stage: d.s } }).then(() => log("검수 진행")).catch(e => log("✗ " + e.message, true)); render(true) },
  async confres(d) { await api(`/api/source-conflicts/${d.id}/resolve`, { body: { resolution: val("cr_" + d.id), evidence_refs: val("ce_" + d.id).split(",").map(s => s.trim()).filter(Boolean) } }).then(() => log("해소 기록")).catch(e => log("✗ " + e.message, true)); render(true) },
  async covsel() { LAST.cov = val("covx"); render(true) },
};
const LAST = {}, HIST = { sql: [], cli: [] };
/* ------------------------------------------------------------ 오류 해결 안내 (실패 → 원인 → 해결 순서 → 바로가기) */
const SCN = (label, view, prefill) => ({ type: "nav", label, view, prefill }), SCR = (label, ct, payload, view) => ({ type: "cmd", label, command_type: ct, payload, view }), SCA = (label, q) => ({ type: "ai", label, q });
let LASTERR = null, REMEDY_POP = null, HFIX = -1;
const EX_SQL = ["SELECT * FROM food_dev.silver.orders LIMIT 5", "SELECT product_id, SUM(on_hand_qty-reserved_qty-damaged_qty) AS available_qty FROM food_dev.silver.inventory GROUP BY product_id"];
const REMEDY = {
  WAREHOUSE_NOT_RUNNING: e => ({ why: "SQL은 SQL Warehouse가 RUNNING일 때만 실행됩니다. 지금은 꺼져 있거나 시작하는 중입니다.", steps: ["[Warehouse 시작]을 누릅니다. 시작은 단계적으로 진행되므로 상태가 RUNNING이 될 때까지 몇 번 더 눌러 확인합니다.", "Compute 화면에서 상태가 RUNNING인지 확인합니다.", "SQL Editor로 돌아와 같은 SQL을 다시 실행합니다."], actions: [SCR("Warehouse 시작", "warehouse", { action: "start" }, "comp"), SCN("Compute 화면에서 상태 보기", "comp"), SCN("SQL Editor로 돌아가기", "sql")] }),
  WAREHOUSE_START_FAILED: e => ({ why: "Warehouse 시작이 실패했습니다(용량·quota 문제 등). 실제 현장에서도 흔한 상황입니다.", steps: ["오류 메시지의 원인(quota/용량)을 확인합니다.", "강사/관리자에게 quota·용량 확인을 요청합니다(요청 내용은 AXOS 피드백이 아니라 담당자에게 직접).", "해결 후 Compute 화면에서 다시 시작합니다."], actions: [SCN("Compute 화면으로", "comp"), SCA("AI 지원에게 물어보기", "Warehouse 시작이 실패했어. 어떻게 해?")] }),
  NO_CAN_USE: e => ({ why: "이 Warehouse를 사용할 수 있는 CAN USE 권한이 내 신원에 없습니다. UC 테이블 권한과는 별개의 권한입니다.", steps: ["Compute 화면에서 CAN USE 대상 그룹을 확인합니다.", "권한 요청 화면에서 Warehouse 사용 권한을 요청합니다(사유를 구체적으로)."], actions: [SCN("Compute에서 CAN USE 확인", "comp"), SCN("권한 요청하러 가기", "perm", { t_sec: "warehouse:wz-training-wh", t_priv: "CAN USE", t_reason: "SQL 실행을 위해 Warehouse 사용 필요" })] }),
  NO_SQL_ENTITLEMENT: e => ({ why: "Databricks SQL 사용 자격(entitlement)이 없습니다. 로그인 성공과 SQL 사용 권한은 다릅니다.", steps: ["권한·관리 화면의 Principal 표에서 내 entitlement를 확인합니다.", "관리자에게 Databricks SQL access 부여를 요청합니다."], actions: [SCN("권한·관리 화면으로", "perm"), SCA("AI 지원에게 물어보기", "SQL entitlement 오류는 어떻게 해결해?")] }),
  INSUFFICIENT_PERMISSIONS: e => { const m = e.missing || {}; return ({ why: `Unity Catalog 권한이 부족합니다${m.privilege ? ` — ${m.securable} 에 ${m.privilege} 권한이 필요합니다` : ""}. 부모(catalog/schema)의 USE 권한과 테이블 SELECT는 별개입니다.`, steps: ["필요한 권한(대상·권한 종류)을 확인합니다.", "권한 요청 화면에 아래 내용이 미리 채워집니다. 사유를 구체적으로 보완해 제출합니다(ALL PRIVILEGES 같은 과도한 요청은 반려).", "관리자가 처리해 승인되면 SQL Editor에서 다시 실행합니다."], actions: [SCN("권한 요청하러 가기 (자동 입력)", "perm", { t_sec: m.securable || "schema:food_dev.silver", t_priv: m.privilege || "USE SCHEMA", t_reason: "SQL 조회를 위해 필요한 최소 권한" }), SCN("Catalog에서 권한 확인", "cat"), SCN("SQL Editor로 돌아가기", "sql")] }) },
  TABLE_OR_VIEW_NOT_FOUND: e => ({ why: "테이블이나 뷰를 찾을 수 없습니다. 이름이 틀렸거나, 권한이 없어 보이지 않는 것일 수 있습니다. 이름은 3단계(catalog.schema.table)로 씁니다.", steps: ["Catalog Explorer에서 실제 테이블 이름과 내가 볼 수 있는 범위를 확인합니다.", "SQL의 catalog.schema.table 철자를 고칩니다.", "그래도 안 보이면 권한 문제일 수 있으니 권한 요청을 확인합니다."], actions: [SCN("Catalog에서 이름 찾기", "cat"), SCN("예제 SQL로 다시 시작", "sql", { sqlbox: EX_SQL[0] }), SCN("권한 확인", "perm")] }),
  PARSE_ERROR: e => ({ why: "SQL 문법을 해석하지 못했습니다(괄호·쉼표·키워드 철자 등).", steps: ["메시지의 위치 주변에서 철자·괄호·쉼표를 확인합니다.", "아래 예제 SQL로 동작을 먼저 확인한 뒤 조금씩 바꿔 봅니다."], actions: [SCN("예제 SQL 불러오기 (조회)", "sql", { sqlbox: EX_SQL[0] }), SCN("예제 SQL 불러오기 (집계)", "sql", { sqlbox: EX_SQL[1] }), SCA("AI 지원에게 물어보기", "SQL 문법 오류가 났어. 어떻게 고쳐?")] }),
  UNSUPPORTED_SQL: e => ({ why: "이 시뮬레이터가 지원하지 않는 SQL입니다(실제 Databricks에서는 될 수 있습니다). 지원: SELECT/JOIN/GROUP BY/CTE/CASE, CREATE SCHEMA/TABLE/VIEW, INSERT, UPDATE/DELETE/MERGE, GRANT/REVOKE(관리자).", steps: ["지원 범위 안의 문장으로 바꿔 봅니다.", "정말 필요한 기능이면 AXOS 탭에서 \"기능 추가 요청\"으로 알려 주세요."], actions: [SCN("지원 예제로 시작", "sql", { sqlbox: EX_SQL[0] }), { type: "axos", label: "기능 추가 요청하기 (AXOS)", kind: "FEATURE" }] }),
  SIMULATOR_UNSUPPORTED: e => REMEDY.UNSUPPORTED_SQL(e),
  TRANSPILE_ERROR: e => REMEDY.UNSUPPORTED_SQL(e),
  EXECUTION_ERROR: e => ({ why: "SQL은 해석됐지만 실행 중 오류가 났습니다(컬럼 이름, 타입, 데이터 문제 등).", steps: ["컬럼·테이블 이름을 Catalog에서 다시 확인합니다.", "작은 조건(LIMIT 5)으로 줄여 어디서 실패하는지 좁혀 봅니다."], actions: [SCN("Catalog에서 컬럼 확인", "cat"), SCN("LIMIT 예제로 시작", "sql", { sqlbox: EX_SQL[0] }), SCA("AI 지원에게 물어보기", "SQL 실행 오류가 났어. 원인이 뭐야?")] }),
  FEATURE_UNVERIFIED: e => ({ why: "아직 확인되지 않은 기능이라 모의로도 실행하지 않습니다(확인되지 않은 것을 된다고 하지 않기 위해).", steps: ["환경 점검의 기능 목록에서 확인 상태와 '사용 가능'을 봅니다.", "확인이 필요하면 검토자가 실제 워크스페이스에서 대조합니다."], actions: [SCN("기능 목록 보기", "env")] }),
  UNKNOWN_FEATURE: e => REMEDY.FEATURE_UNVERIFIED(e),
  CONNECTION_NOT_READY: e => ({ why: "외부 연결(Connection)이 준비되지 않았습니다.", steps: ["수집 화면에서 연결 테스트 결과를 확인합니다.", "자격증명·네트워크 항목을 점검하고 다시 테스트합니다."], actions: [SCN("연결 화면으로", "conn")] }),
  PIPELINE_SOURCE_INVALID: e => ({ why: "파이프라인 입력(source)이 올바르지 않습니다.", steps: ["Pipelines 화면의 source 설정을 확인합니다."], actions: [SCN("Pipelines 화면으로", "pipe")] }),
  PIPELINE_PARSE_ERROR: e => REMEDY.PIPELINE_SOURCE_INVALID(e),
  SESSION_PAUSED: e => ({ why: "세션이 일시정지 상태입니다(강사가 멈춘 경우).", steps: ["강사에게 재개를 요청하거나 잠시 기다립니다."], actions: [SCN("환경 점검으로", "env")] }),
  SESSION_NOT_FOUND: e => ({ why: "세션을 찾을 수 없습니다(삭제되었거나 다른 사용자의 세션).", steps: ["환경 점검에서 새 세션을 시작하세요."], actions: [SCN("새 세션 시작하러 가기", "env")] }),
  NOT_READY: e => ({ why: "이 작업에 필요한 앞 단계가 아직 끝나지 않았습니다.", steps: ["AI 지원의 '전체 단계'에서 지금 해야 할 다음 단계를 확인합니다.", "앞 단계를 마친 뒤 다시 시도합니다."], actions: [{ type: "ai", label: "다음에 뭐 해?", q: "다음에 뭐 해?" }] }),
  FORBIDDEN: e => ({ why: "이 작업은 내 역할로는 할 수 없습니다(권한 모델: 교육 역할과 DBX 권한은 별개).", steps: ["필요한 역할(강사/관리자/검토자)을 오류 메시지에서 확인합니다.", "권한 요청 화면에서 요청하거나 담당자에게 문의합니다."], actions: [SCN("권한·관리 화면으로", "perm")] }),
  BAD_ACTION: e => ({ why: "요청한 동작을 이 화면에서 지원하지 않습니다.", steps: ["화면의 버튼으로 다시 시도합니다.", "계속되면 AXOS로 알려 주세요."], actions: [] }),
  BAD_MODE: e => ({ why: "현재 학습 모드에서는 허용되지 않는 동작입니다(모드는 실행 중 전환할 수 없음).", steps: ["환경 점검에서 원하는 모드로 새 세션을 시작합니다."], actions: [SCN("환경 점검으로", "env")] }),
  UNKNOWN_PRINCIPAL: e => ({ why: "알 수 없는 실행 신원(principal)입니다.", steps: ["권한·관리 화면의 Principal 표에 있는 이름을 사용합니다."], actions: [SCN("Principal 목록 보기", "perm")] }),
  CELL_NOT_FOUND: e => ({ why: "노트북에서 해당 셀을 찾을 수 없습니다.", steps: ["Notebook 화면을 새로 불러와 셀 목록을 확인합니다."], actions: [SCN("Notebook으로", "nb")] }),
  REAL_HOST_BLOCKED: e => ({ why: "이 환경은 실제 외부 호스트 접속을 막습니다(안전을 위한 격리).", steps: ["합성 데이터와 내장 연결만 사용하세요.", "실제 연결이 필요하면 검토자와 별도 환경을 협의합니다."], actions: [SCN("수집 화면으로", "conn")] }),
  PYTHON_ISOLATION_NOT_CONFIGURED: e => ({ why: "Python 코드 실행용 격리 환경이 아직 구성되지 않아 실행하지 않습니다(안전 때문에 차단).", steps: ["SQL 셀로 같은 작업을 해 봅니다.", "Python 실행이 꼭 필요하면 AXOS에서 기능 추가를 요청해 주세요."], actions: [SCN("Notebook(SQL)으로", "nb"), { type: "axos", label: "기능 추가 요청하기 (AXOS)", kind: "FEATURE" }] }),
  REAL_DISABLED: e => ({ why: "웹에서는 사용자 토큰을 서버가 맡지 않도록 실제 연결을 막아 두었습니다.", steps: ["설치형 앱을 내려받아 설치합니다.", "앱에서 [실제 환경 연결]을 열어 내 워크스페이스를 연결합니다."], actions: [SCN("실제 환경 연결 안내", "real")] }),
  BAD_HOST: e => ({ why: "Databricks 공식 주소(…azuredatabricks.net, …cloud.databricks.com, …gcp.databricks.com)만 연결할 수 있습니다.", steps: ["워크스페이스 URL에서 https:// 를 뺀 호스트 이름을 입력합니다.", "회사 전용 도메인이면 운영자에게 허용 목록 추가를 요청합니다."], actions: [SCN("연결 설정으로", "real")] }),
  BAD_WAREHOUSE: e => ({ why: "SQL Warehouse ID 형식이 올바르지 않습니다.", steps: ["워크스페이스 > SQL Warehouses > 사용할 Warehouse > 연결 정보에서 ID를 복사합니다."], actions: [SCN("연결 설정으로", "real")] }),
  TOKEN_REQUIRED: e => ({ why: "액세스 토큰이 없습니다.", steps: ["워크스페이스 > 사용자 설정 > 개발자 > 액세스 토큰에서 새 토큰을 만듭니다(유효기간 짧게).", "토큰을 입력하고 저장합니다."], actions: [SCN("연결 설정으로", "real")] }),
  LOOKS_LIKE_PROD: e => ({ why: "운영 환경으로 보이는 이름입니다. 이 도구는 교육용·비운영 환경 전용입니다.", steps: ["정말 비운영 환경이면 '비운영 환경임을 확인했습니다'에 체크하고 저장합니다.", "운영 환경이면 연결하지 마세요."], actions: [SCN("연결 설정으로", "real")] }),
  CONSENT_REQUIRED: e => ({ why: "교육용·비운영 환경이며 고객 데이터·운영 자격증명이 아님에 동의해야 연결할 수 있습니다.", steps: ["동의 체크박스를 선택하고 다시 저장합니다."], actions: [SCN("연결 설정으로", "real")] }),
  REAL_HTTP_401: e => ({ why: "토큰이 잘못되었거나 만료되었습니다.", steps: ["워크스페이스에서 새 토큰을 만들고 저장합니다."], actions: [SCN("연결 설정으로", "real")] }),
  REAL_HTTP_403: e => ({ why: "토큰의 계정이 SQL Warehouse 사용(CAN USE)이나 데이터 접근 권한이 없습니다.", steps: ["워크스페이스 관리자에게 Warehouse CAN USE와 필요한 catalog/schema 권한을 요청합니다."], actions: [SCN("권한 요청 방법 보기", "perm")] }),
  REAL_HTTP_404: e => ({ why: "주소나 Warehouse ID가 틀렸습니다.", steps: ["워크스페이스 주소와 Warehouse ID를 다시 확인합니다."], actions: [SCN("연결 설정으로", "real")] }),
  REAL_UNREACHABLE: e => ({ why: "워크스페이스에 닿지 못했습니다(네트워크·VPN·주소).", steps: ["인터넷/VPN 연결을 확인합니다.", "주소 철자를 확인합니다.", "Warehouse가 꺼져 있다면 워크스페이스에서 시작합니다."], actions: [SCN("연결 설정으로", "real")] }),
  READ_ONLY: e => ({ why: "읽기 전용 연결에서는 SELECT·SHOW·DESCRIBE·EXPLAIN만 실행됩니다.", steps: ["조회 문장으로 바꾸거나, 교육용 환경이라면 연결 설정에서 '쓰기 허용'을 켭니다."], actions: [SCN("연결 설정으로", "real")] }),
  CONFIRM_REQUIRED: e => ({ why: "되돌릴 수 없거나 권한을 바꾸는 문장입니다.", steps: ["영향 범위를 확인하고, 맞다면 '되돌릴 수 없는 문장 확인'에 체크한 뒤 실행합니다."], actions: [SCN("연결 설정으로", "real")] }),
  ONE_STATEMENT: e => ({ why: "한 번에 한 문장만 실행할 수 있습니다.", steps: ["세미콜론(;)으로 나뉜 문장을 따로 실행합니다."], actions: [SCN("연결 설정으로", "real")] }),
  REVISION_CONFLICT: e => ({ why: "다른 화면에서 같은 세션이 먼저 바뀌어 충돌했습니다.", steps: ["화면을 새로 불러온 뒤 다시 시도합니다."], actions: [{ type: "reload", label: "화면 새로 고침" }] })
};
function remedyOf(err) {
  const f = REMEDY[err?.code]; const r = f ? f(err) : { why: "자세한 해결 안내가 아직 없는 오류입니다. 아래 순서로 확인해 보세요.", steps: ["오류 메시지와 힌트를 읽어 원인을 확인합니다.", "AI 지원에게 \"왜 실패했어?\"라고 물어보면 현재 상태 기준으로 원인과 다음 행동을 알려 줍니다.", "계속 이상하면 AXOS 탭에서 오류 내용을 피드백으로 보내 주세요."], actions: [] };
  r.actions = [...(r.actions || []), SCA("AI 지원: 왜 실패했어?", "왜 실패했어?"), { type: "help", label: "이 화면 도움말(HELP)" }, { type: "axos", label: "이 오류가 이상해요 (피드백)", kind: "DBX_MISMATCH", err }];
  return r;
}
function remedyHtml(err, opt = {}) {
  const r = remedyOf(err);
  return `<div class="remedy"><div class="rmh"><b class="bad">${esc(err.code || "오류")}</b> <span>${esc(err.message || "")}</span></div>
    ${err.hint ? `<div class="warnc">힌트: ${esc(err.hint)}</div>` : ""}
    <div class="rmw"><b>왜 이런가요?</b> ${esc(r.why)}</div>
    <div class="rms"><b>해결 순서</b><ol>${r.steps.map(x => `<li>${esc(x)}</li>`).join("")}</ol></div>
    <div class="rma">${r.actions.map(a => scBtn(a)).join("")}</div></div>`;
}
const kvText = v => v === null || v === undefined ? "-" : typeof v === "object" ? (Array.isArray(v) ? v.map(kvText).join(", ") : Object.entries(v).map(([a, b]) => `${a}: ${kvText(b)}`).join(" · ")) : String(v);
const kvTable = o => table(["항목", "값"], Object.entries(o).map(([k, v]) => [k, kvText(v)]));
function profCards(p) {
  const cred = (p.official_credentials || []).filter(c => c.status && c.status !== "NONE_RECORDED"), empty = o => !o || (typeof o === "object" && !Object.keys(o).length);
  const card = (n, title, state, tone, body, hint, act) => `<div class="pcard"><div class="pc-h"><span class="pc-n">${n}</span><b>${title}</b>${badge(state, tone)}</div>${body ? `<div class="pc-b">${body}</div>` : ""}<div class="pc-s">${hint}</div>${act || ""}</div>`;
  const go = (label, view) => `<div class="pc-a">${scBtn(SCN(label, view))}</div>`;
  const ready = Object.entries(p.readiness || {});
  return `<div class="pgrid">
    ${card(1, "내부 등급", empty(p.internal_grades) ? "아직 평가 전" : "평가됨", empty(p.internal_grades) ? "w" : "ok", empty(p.internal_grades) ? "" : kvTable(p.internal_grades), "WIZBASE 내부 기준의 등급입니다. 시험센터의 모의시험·실습을 마치면 강사/검토자가 결정합니다. 공식 자격이 아닙니다.", empty(p.internal_grades) ? go("시험센터로 가서 시작하기", "exam") : "")}
    ${card(2, "내부 재평가", empty(p.internal_reassessment) ? "해당 없음" : "대상", empty(p.internal_reassessment) ? "" : "w", empty(p.internal_reassessment) ? "" : kvTable(p.internal_reassessment), "내부 등급을 받은 뒤 일정 기간이 지나면 다시 확인하는 절차입니다. 등급이 없으면 해당 사항이 없습니다.", "")}
    ${card(3, "공식 자격", cred.length ? `${cred.length}건 등록` : "등록된 자격 없음", cred.length ? "ok" : "w", cred.length ? table(["자격", "상태"], cred.map(c => [c.name || c.credential_ref || "-", c.status])) : "", "Databricks 공식 자격은 본인이 신고하면 '확인대기'가 되고, 검토자가 발급기관 확인 URL·credential ID로 검증해야 유효가 됩니다. 아래 '공식 자격 등록'에서 신고합니다.", "")}
    ${card(4, "응시 준비(내부 판정)", ready.length ? `${ready.length}개 시험 판정됨` : "판정 전", ready.length ? "ok" : "w", ready.length ? table(["시험", "내부 판정"], ready) : "", "공식 합격선·합격 확률이 아닙니다. 내부 기준(문항 정답률·실습 증거 등)을 충족했는지만 보여줍니다. 아래 '응시준비 판정'에서 실행합니다.", "")}
    ${card(5, "승인된 실제 실습", (p.labs_approved || []).length ? `${p.labs_approved.length}건` : "승인된 실습 없음", (p.labs_approved || []).length ? "ok" : "w", (p.labs_approved || []).length ? p.labs_approved.map(x => badge(x, "ok")).join(" ") : "", "실제 Databricks 워크스페이스에서 한 실습의 증거를 검토자가 승인한 것만 표시됩니다. 모의 실행은 포함되지 않습니다.", (p.labs_approved || []).length ? "" : go("실습 증거함으로 가기", "lab"))}
    ${card(6, "고객 투입 승인", "별도 승인", "", "", `${esc(typeof p.assignment_authorization === "string" ? p.assignment_authorization : "별도 승인(자동 부여 없음)")} — 내부 등급이나 자격과 관계없이 별도 절차로만 부여됩니다. 아래 '투입 승인' 카드에서 확인합니다.`, "")}</div>`;
}
const dimTable = d => !d || !Object.keys(d).length ? `<div class="mute">아직 평가된 차원이 없습니다. 시험센터에서 문항을 풀면 지식·실기·복구·설명 차원별 숙련도가 여기에 표시됩니다.</div>${scBtn(SCN("시험센터로 가기", "exam"))}` : table(["차원", "숙련도"], Object.entries(d).map(([k, v]) => [k, kvText(v)]));
/* ------------------------------------------------------------ 읽기 쉬운 값 표시 (JSON 코드가 그대로 보이지 않게) */
const KL = { usage_index: "모의 사용량 지수", usage: "사용량", unit: "단위", weights: "가중치", approvals: "승인", proposals: "제안", ax_actions: "실행 기록", tickets: "권한 티켓", score: "점수", counts: "건수", count: "건수", by_domain: "영역별", recalls: "회수 이력", families: "문항 묶음(family)", company_program: "회사 파트너 프로그램", partner_status: "파트너 상태", poc: "PoC", purpose: "목적", tier: "등급(tier)", note: "비고", status: "상태", state: "상태", reason: "사유", name: "이름", title: "제목", id: "ID", total: "전체", correct: "정답", pct: "비율(%)", rows: "행 수", columns: "컬럼", sha256: "SHA-256", created: "생성", created_at: "생성 일시", updated_at: "갱신 일시", owner: "소유자", role: "역할", kind: "종류", type: "유형", version: "버전", ok: "정상", passed: "통과", failed: "실패", missing: "부족한 항목", privilege: "권한", securable: "대상", evidence_level: "증거 수준", release_gate_ok: "출시 게이트", blockers: "차단 사유", pilot: "파일럿", learners: "학습자 수", sessions: "세션 수", items: "문항", approved: "승인됨", pending: "대기", rejected: "반려", completed: "완료", percent: "진행률(%)", exam_id: "시험", domain: "영역", domains: "영역", mastery: "숙련도", detail: "상세", result: "결과", recon: "정합성 대조", expected: "기대값", actual: "실제값", diff: "차이", message: "메시지", code: "코드", hint: "힌트" };
const keyLabel = k => KL[k] || String(k).replace(/_/g, " ");
const isObj = v => v && typeof v === "object" && !Array.isArray(v);
function pretty(v, depth = 0) {
  if (v === null || v === undefined || v === "") return `<span class="mute">-</span>`;
  if (typeof v === "boolean") return badge(v ? "예" : "아니오", v ? "ok" : "w");
  if (typeof v === "number") return `<b>${esc(Number.isInteger(v) ? v.toLocaleString("ko-KR") : String(Math.round(v * 1000) / 1000))}</b>`;
  if (typeof v === "string") return esc(v);
  if (Array.isArray(v)) {
    if (!v.length) return `<span class="mute">(없음)</span>`;
    if (v.every(x => x === null || typeof x !== "object")) return v.map(x => `<span class="pchip">${esc(x)}</span>`).join(" ");
    if (v.every(isObj) && depth < 3) { const cols = [...new Set(v.flatMap(o => Object.keys(o)))].slice(0, 8); return `<div class="tw"><table><tr>${cols.map(c => `<th>${esc(keyLabel(c))}</th>`).join("")}</tr>${v.slice(0, 50).map(o => `<tr>${cols.map(c => `<td>${depth < 2 ? pretty(o[c], depth + 1) : esc(kvText(o[c]))}</td>`).join("")}</tr>`).join("")}</table></div>${v.length > 50 ? `<div class="mute">… 외 ${v.length - 50}건</div>` : ""}` }
    return `<ul class="pul">${v.slice(0, 50).map(x => `<li>${pretty(x, depth + 1)}</li>`).join("")}</ul>`;
  }
  const es = Object.entries(v);
  if (!es.length) return `<span class="mute">(없음)</span>`;
  if (depth >= 3) return esc(kvText(v));
  return `<table class="ptab">${es.map(([k, x]) => `<tr><th>${esc(keyLabel(k))}</th><td>${pretty(x, depth + 1)}</td></tr>`).join("")}</table>`;
}
const prettyBox = (v, rawToo) => `<div class="pbox">${pretty(v)}</div>${rawToo ? `<details><summary class="mute">원본 데이터(JSON) 보기</summary><pre>${J(v)}</pre></details>` : ""}`;
/* ------------------------------------------------------------ 연결(내비게이션): 표의 항목 → 관련 화면, 모든 화면 하단 '이어서' */
const EV_NAV = [[/^(SQL|QUERY)/, "sql"], [/^WAREHOUSE/, "comp"], [/^PIPELINE/, "pipe"], [/^(JOB|RUN_|REPAIR)/, "jobs"], [/^(NOTEBOOK|CELL)/, "nb"], [/^(CONN|FOREIGN)/, "conn"], [/^(GRANT|REVOKE|PERMISSION|TICKET|UC_|PRIVILEGE)/, "perm"], [/^(ORDER|AX_|APPROVAL|PROPOSAL|POLICY|PAYLOAD)/, "agent"], [/^GENIE/, "genie"], [/^(BUNDLE|GIT|CLI|DEPLOY)/, "bundle"], [/^CDC/, "cdc"], [/^(TRACE|EVAL)/, "trace"], [/^(EXAM|ATTEMPT)/, "exam"], [/^LAB/, "lab"], [/^(SESSION|ENV|PROFILE)/, "env"], [/^(OBJECTIVE|COVERAGE)/, "map"], [/^(ITEM|QUESTION)/, "qual"]];
const KIND_NAV = { "Notebook cell": "nb", File: "bundle", Pipeline: "pipe", Job: "jobs", Warehouse: "comp", Connection: "conn", Genie: "genie", Agent: "agent" };
const STAFF_VIEWS = new Set(["rvw", "vmx", "inst", "partner", "conf"]);
const viewAllowed = v => !!V[v] && canGo(v);
const canGo = v => (v === "fbq" || v === "usage") ? ME?.role === "admin" : STAFF_VIEWS.has(v) ? staff() : true;
const goLink = (v, label, tip) => `<a href="#" class="golink" data-a="nav" data-v="${v}" title="${esc(tip || (viewLabel(v) + " 화면으로 이동"))}">${esc(label)} ›</a>`;
function autoLink(c) {
  if (typeof c !== "string" || !c || c.length > 64) return null;
  let v = KIND_NAV[c];
  if (!v && /^[A-Z][A-Z0-9_]{3,}$/.test(c)) v = (EV_NAV.find(([re]) => re.test(c)) || [])[1];
  if (!v && /^LAB-[A-Z0-9-]+$/.test(c)) v = "lab";
  if (!v && /^FB-\d+$/.test(c)) v = "fbq";
  if (!v && /^s_[0-9a-f]{8,}$/.test(c)) return `<a href="#" class="golink" data-a="opensess" data-id="${esc(c)}" title="이 세션 열기">${esc(c)} ›</a>`;
  return v && v !== VIEW && canGo(v) ? goLink(v, c) : null;
}
const NEXTV = { env: "req", req: "comp", ws: "cat", cat: "sql", sql: "perm", nb: "pipe", comp: "cat", conn: "pipe", pipe: "jobs", cdc: "jobs", jobs: "nb", genie: "agent", agent: "trace", trace: "bundle", bundle: "perm", perm: "sql", track: "demo", demo: "evid", xfer: "prof", prof: "plan", plan: "map", map: "tutor", ko: "tutor", tutor: "exam", exam: "lab", lab: "qual", qual: "partner", partner: "conf", conf: "vmx", vmx: "rvw", rvw: "vmx", fbq: "usage", usage: "evid", real: "lab", inst: "evid", evid: "prof" };
function viewFooter(v) {
  let n = NEXTV[v]; if (n && !canGo(n)) n = ["evid", "prof", "env"].find(x => x !== v && canGo(x));
  const b = [];
  if (n) b.push(scBtn(SCN(`다음 화면: ${viewLabel(n)}`, n), true));
  b.push(scBtn(SCA("이 화면은 뭐야? (AI 지원)", "이 화면은 뭐야?")), scBtn({ type: "help", label: "이 화면 도움말(F1)" }));
  return `<div class="vfoot"><span class="mute">이어서</span> ${b.join(" ")}</div>`;
}
/* ------------------------------------------------------------ 차트(SVG, 외부 라이브러리 없음) — 접속·사용 기록 화면 */
const nf = n => Number(n || 0).toLocaleString("ko-KR");
const niceMax = v => { if (v <= 4) return 4; const p = Math.pow(10, Math.floor(Math.log10(v))), f = v / p; return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10) * p };
const SER = ["var(--vs1)", "var(--vs2)", "var(--vs3)", "var(--vs4)"];
const tipAttr = h => `data-tip="${esc(h)}"`;
function legend(items) { return `<div class="vlegend">${items.map(([n, c, ic]) => `<span><i style="background:${c}"></i>${ic ? ic + " " : ""}${esc(n)}</span>`).join("")}</div>` }
function tableView(cols, rows) { return `<details class="vtab"><summary>표로 보기</summary>${table(cols, rows, true)}</details>` }
/* 꺾은선: 시리즈 2~3개(같은 척도), 일별. 교차선+툴팁은 칸마다 투명 히트 영역으로 구현 */
function lineChart(labels, series, o = {}) {
  const W = 720, H = 220, L = 38, R = 12, T = 12, B = 26, pw = W - L - R, ph = H - T - B, n = labels.length;
  const max = niceMax(Math.max(1, ...series.flatMap(s => s.values))), x = i => L + (n <= 1 ? pw / 2 : i * pw / (n - 1)), y = v => T + ph - v / max * ph;
  const grid = [0, 1, 2, 3, 4].map(k => { const v = max * k / 4, yy = y(v); return `<line x1="${L}" x2="${W - R}" y1="${yy}" y2="${yy}" class="vgrid"/><text x="${L - 6}" y="${yy + 4}" class="vax" text-anchor="end">${nf(Math.round(v))}</text>` }).join("");
  const step = Math.max(1, Math.ceil(n / 8)), xl = labels.map((d, i) => i % step === 0 || (i === n - 1 && (n - 1) % step >= Math.ceil(step / 2)) ? `<text x="${x(i)}" y="${H - 8}" class="vax" text-anchor="middle">${esc(d.slice(5))}</text>` : "").join("");
  const paths = series.map(s => `<path d="${s.values.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join("")}" fill="none" stroke="${s.color}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>`).join("");
  const hits = labels.map((d, i) => { const w = n <= 1 ? pw : pw / (n - 1), tip = `<b>${d}</b><br>` + series.map(s => `${s.name}: <b>${nf(s.values[i])}</b>`).join("<br>");
    return `<g class="hx"><rect x="${(x(i) - w / 2).toFixed(1)}" y="${T}" width="${w.toFixed(1)}" height="${ph}" fill="transparent" ${tipAttr(tip)}/><line x1="${x(i).toFixed(1)}" x2="${x(i).toFixed(1)}" y1="${T}" y2="${T + ph}" class="vcross"/>${series.map(s => `<circle cx="${x(i).toFixed(1)}" cy="${y(s.values[i]).toFixed(1)}" r="4" fill="${s.color}" class="vdot"/>`).join("")}</g>` }).join("");
  return `<svg viewBox="0 0 ${W} ${H}" class="vsvg" role="img" aria-label="${esc(o.label || "꺾은선 차트")}">${grid}${paths}${hits}${xl}</svg>${series.length > 1 ? legend(series.map(s => [s.name, s.color])) : ""}`;
}
/* 막대(단일 시리즈 또는 성공/실패 누적): 데이터 끝 모서리 둥글게, 막대 사이 2px */
function barChart(labels, series, o = {}) {
  const W = 720, H = 200, L = 38, R = 8, T = 10, B = 26, pw = W - L - R, ph = H - T - B, n = labels.length, bw = Math.max(2, pw / n - 2);
  const tot = labels.map((_, i) => series.reduce((a, s) => a + s.values[i], 0)), max = niceMax(Math.max(1, ...tot)), y = v => T + ph - v / max * ph, x = i => L + i * pw / n + 1;
  const grid = [0, 1, 2, 3, 4].map(k => { const v = max * k / 4, yy = y(v); return `<line x1="${L}" x2="${W - R}" y1="${yy}" y2="${yy}" class="vgrid"/><text x="${L - 6}" y="${yy + 4}" class="vax" text-anchor="end">${nf(Math.round(v))}</text>` }).join("");
  const step = Math.max(1, Math.ceil(n / (o.maxLabels || 12))), xl = labels.map((d, i) => i % step === 0 ? `<text x="${(x(i) + bw / 2).toFixed(1)}" y="${H - 8}" class="vax" text-anchor="middle">${esc(o.fmt ? o.fmt(d) : d)}</text>` : "").join("");
  const bars = labels.map((d, i) => { let acc = 0; const tip = `<b>${esc(o.fmt ? o.fmt(d) : d)}</b><br>` + series.map(s => `${s.name}: <b>${nf(s.values[i])}</b>`).join("<br>");
    const segs = series.map((s, k) => { const v = s.values[i]; if (!v) return ""; const y1 = y(acc + v), h = Math.max(1, y(acc) - y1 - (k < series.length - 1 && series[k + 1].values[i] ? 2 : 0)); acc += v;
      const r = Math.min(4, bw / 2, h); const top = acc >= tot[i] - 1e-9; return `<path d="M${x(i).toFixed(1)},${(y1 + h).toFixed(1)}V${(y1 + (top ? r : 0)).toFixed(1)}${top ? `Q${x(i).toFixed(1)},${y1.toFixed(1)} ${(x(i) + r).toFixed(1)},${y1.toFixed(1)}H${(x(i) + bw - r).toFixed(1)}Q${(x(i) + bw).toFixed(1)},${y1.toFixed(1)} ${(x(i) + bw).toFixed(1)},${(y1 + r).toFixed(1)}` : `H${(x(i) + bw).toFixed(1)}`}V${(y1 + h).toFixed(1)}Z" fill="${s.color}"/>` }).join("");
    return `<g class="vbar">${segs}<rect x="${x(i).toFixed(1)}" y="${T}" width="${bw.toFixed(1)}" height="${ph}" fill="transparent" ${tipAttr(tip)}/></g>` }).join("");
  return `<svg viewBox="0 0 ${W} ${H}" class="vsvg" role="img" aria-label="${esc(o.label || "막대 차트")}">${grid}${bars}${xl}</svg>${series.length > 1 ? legend(series.map(s => [s.name, s.color, s.icon])) : ""}`;
}
/* 가로 막대(순위): 값은 막대 끝에 직접 표시, 정렬된 단일 색 */
function hbars(entries, o = {}) {
  if (!entries.length) return `<div class="mute">(기록 없음)</div>`; const max = Math.max(1, ...entries.map(e => e[1]));
  return `<div class="hbars">${entries.map(([k, v, extra]) => `<div class="hb" ${tipAttr(`<b>${esc(o.label ? o.label(k) : k)}</b><br>${nf(v)}${extra ? " · " + esc(extra) : ""}`)}><span class="hbl">${esc(o.label ? o.label(k) : k)}</span><span class="hbt"><span class="hbf" style="width:${(v / max * 100).toFixed(1)}%;background:${o.color || SER[0]}"></span></span><span class="hbv">${nf(v)}</span></div>`).join("")}</div>`;
}
/* 구성비: 한 줄 100% 막대(조각 사이 2px) + 범례(수·%) — 도넛 대신 */
function segBar(entries, colors) {
  const tot = entries.reduce((a, e) => a + e[1], 0); if (!tot) return `<div class="mute">(기록 없음)</div>`;
  return `<div class="seg">${entries.map(([k, v], i) => `<span style="flex:${v};background:${(colors || SER)[i % 4]}" ${tipAttr(`<b>${esc(k)}</b><br>${nf(v)} (${Math.round(v / tot * 100)}%)`)}></span>`).join("")}</div>
    <div class="vlegend">${entries.map(([k, v], i) => `<span><i style="background:${(colors || SER)[i % 4]}"></i>${esc(k)} <b>${nf(v)}</b> <em>${Math.round(v / tot * 100)}%</em></span>`).join("")}</div>`;
}
/* 히트맵: 요일 × 시간, 단일 색 순차(연한→진한) */
function heatmap(m) {
  const max = Math.max(1, ...m.flat()), days = ["월", "화", "수", "목", "금", "토", "일"], cw = 26, ch = 22, L = 26, T = 4;
  const cells = m.map((row, d) => row.map((v, h) => `<rect x="${L + h * cw}" y="${T + d * ch}" width="${cw - 2}" height="${ch - 2}" rx="3" style="fill:var(--vq${v ? Math.min(6, 1 + Math.floor(v / max * 5.999)) : 0})" ${tipAttr(`<b>${days[d]}요일 ${h}시</b><br>${nf(v)}건`)}/>`).join("")).join("");
  const dl = days.map((d, i) => `<text x="${L - 6}" y="${T + i * ch + 15}" class="vax" text-anchor="end">${d}</text>`).join(""), hl = [0, 3, 6, 9, 12, 15, 18, 21].map(h => `<text x="${L + h * cw + 11}" y="${T + 7 * ch + 14}" class="vax" text-anchor="middle">${h}</text>`).join("");
  return `<svg viewBox="0 0 ${L + 24 * cw} ${T + 7 * ch + 20}" class="vsvg" role="img" aria-label="요일·시간대별 사용량 히트맵">${cells}${dl}${hl}</svg><div class="vlegend"><span>적음</span><span class="vramp">${[1, 2, 3, 4, 5, 6].map(k => `<i style="background:var(--vq${k})"></i>`).join("")}</span><span>많음 (최대 ${nf(max)}건)</span></div>`;
}
/* 툴팁(이벤트 위임) */
(function () {
  let tip = null; const get = () => tip || (tip = (() => { const d = document.createElement("div"); d.className = "vtip"; d.style.display = "none"; document.body.appendChild(d); return d })());
  document.addEventListener("mouseover", e => { const t = e.target.closest && e.target.closest("[data-tip]"); if (!t) { if (tip) tip.style.display = "none"; return } const d = get(); d.innerHTML = t.getAttribute("data-tip"); d.style.display = "block"; d.style.left = Math.max(4, Math.min(innerWidth - d.offsetWidth - 8, e.clientX + 14)) + "px"; d.style.top = (e.clientY + 16 + d.offsetHeight > innerHeight ? e.clientY - d.offsetHeight - 10 : e.clientY + 16) + "px" });
  document.addEventListener("touchstart", e => { if (tip && !(e.target.closest && e.target.closest("[data-tip]"))) tip.style.display = "none" }, { passive: true });
  document.addEventListener("mousemove", e => { if (tip && tip.style.display === "block") { tip.style.left = Math.min(innerWidth - tip.offsetWidth - 8, e.clientX + 14) + "px"; tip.style.top = (e.clientY + 16 + tip.offsetHeight > innerHeight ? e.clientY - tip.offsetHeight - 10 : e.clientY + 16) + "px" } });
})();
let USG = { days: 30, kind: "", q: "", page: 0, size: 25, upage: 0, usize: 15, uq: "", fp: "", at: 0, auto: true, timer: null };
function usageWatch() {
  if (USG.timer) return;
  USG.timer = setInterval(async () => {
    if (VIEW !== "usage" || document.hidden || !USG.auto || ME?.role !== "admin") return;
    try { const p = await api("/api/usage/pulse"); if (USG.fp && p.fp !== USG.fp && Date.now() - USG.at > 30000) render(true) } catch { }   // 새 기록이 있을 때만, 최소 30초 간격
  }, 30000);
}
const ROLEL = { learner: "학습자", instructor: "강사", reviewer: "검토자", admin: "admin" }, CLIL = { web: "웹(PC)", mobile: "웹(모바일)", pc_app: "PC 앱", bot: "봇/도구", unknown: "알 수 없음" };
const DLL = { windows_standalone: "Windows 단독형", windows_shell: "Windows 접속형", pack: "기능 업데이트 팩", mac_arm64: "Mac(Apple Silicon)", mac_x64: "Mac(Intel)" };
function kpiTile(label, v, prev, o = {}) {
  const d = prev ? Math.round((v - prev) / prev * 100) : null;
  return `<div class="kpi"><div class="kl">${esc(label)}</div><div class="kv">${nf(v)}${o.unit ? `<small>${o.unit}</small>` : ""}</div><div class="kd">${d === null ? "이전 기간 기록 없음" : `${d > 0 ? "▲" : d < 0 ? "▼" : "–"} ${Math.abs(d)}% (이전 ${USG.days}일 ${nf(prev)})`}</div></div>`;
}
function pagerHtml(total, page, size, act) {
  const pages = Math.max(1, Math.ceil(total / size)), b = (label, p, dis) => `<button class="ghost" data-a="${act}" data-p="${p}" ${dis ? "disabled" : ""}>${label}</button>`;
  const st = Math.max(0, Math.min(page - 2, pages - 5)), nums = []; for (let i = st; i < Math.min(pages, st + 5); i++) nums.push(`<button class="${i === page ? "primary" : "ghost"}" data-a="${act}" data-p="${i}" ${i === page ? 'aria-current="page"' : ""}>${i + 1}</button>`);
  return `<div class="pager">${b("« 처음", 0, page <= 0)}${b("‹ 이전", page - 1, page <= 0)}${nums.join("")}${b("다음 ›", page + 1, page >= pages - 1)}${b("마지막 »", pages - 1, page >= pages - 1)}<span class="mute">${nf(total)}건 · ${page + 1}/${pages}쪽</span><label class="mute" style="margin-left:auto">쪽당 <select onchange="H.${act}size(this.value)">${[10, 25, 50, 100].map(n => `<option ${n === size ? "selected" : ""}>${n}</option>`).join("")}</select>건</label></div>`;
}
function resBox(ex) {
  if (!ex) return ""; const r = ex.result || ex; const e = r.error;
  if (e) return `<div class="card"><b class="bad">${esc(e.code)}</b> ${esc(e.message)}${e.hint ? `<div class="warnc">힌트: ${esc(e.hint)}</div>` : ""}${e.missing ? pretty(e.missing) : ""} ${ex.evidence_level ? lv(ex.evidence_level) : ""}${remedyHtml(e)}</div>`;
  if (r.columns) return `<div class="card">${lv(ex.evidence_level || "LOCAL_EXECUTED")} 행 ${r.rows?.length} · hash ${esc((r.sql_hash || "").slice(0, 10))}${table(r.columns, r.rows, true)}</div>`;
  return `<div class="card">${prettyBox(r, true)}</div>`;
}

/* ------------------------------------------------------------ views */
const V = {
  async real() {
    const st = await api("/api/real/status"); REAL = st;
    const L = LAST.real, tpl = "[연결 대상] (Databricks 교육용 워크스페이스 / 다른 DB 종류 / 파일·스토리지 중 선택)\n[목적] \n[환경 구분] 비운영(교육·테스트) 환경입니다.\n[필요한 지원] \n※ 비밀번호·토큰·접속 문자열은 절대 적지 마세요.";
    const path = (n, t, body, act) => `<div class="pcard"><div class="pc-h"><span class="pc-n">${n}</span><b>${t}</b></div><div class="pc-s">${body}</div><div class="pc-a">${act}</div></div>`;
    const steps = ["연결할 곳은 <b>교육용·테스트(비운영)</b> 환경이어야 합니다. 운영 환경·고객 데이터·운영 자격증명은 연결하지 마세요.", "워크스페이스에 <b>SQL Warehouse</b>를 만들고(서버리스 권장) 시작해 둡니다. Warehouse ID는 SQL Warehouses > 해당 Warehouse > 연결 정보에 있습니다.", "<b>개인 액세스 토큰(PAT)</b>을 만듭니다(사용자 설정 > 개발자 > 액세스 토큰). 유효기간을 짧게(예: 7일) 두고, 읽기만 필요하면 해당 카탈로그에 SELECT 권한만 가진 계정을 쓰세요.", "아래 연결 정보를 입력하고 [저장] → [연결 테스트]에서 <b>내 계정 이름이 맞는지</b> 확인합니다.", "SQL을 실행해 결과를 확인하고, 실습 증거로 쓸 결과는 <b>결과 해시</b>를 실습 증거함에 제출합니다."];
    const form = !st.enabled ? `<div class="warnbox">웹에서는 보안상 직접 연결을 막아 두었습니다(사용자 토큰을 서버가 맡지 않도록). <b>설치형 앱</b>에서 내 PC에서만 연결할 수 있습니다. <p>${scBtn({ type: "reload", label: "새로고침" })} <button class="primary" data-a="appdl">설치형 앱 다운로드</button></p></div>` : `
      ${st.configured ? `<div class="okbox"><b>연결 설정 저장됨</b> — ${esc(st.host)} · Warehouse ${esc(st.warehouse_id)}${st.catalog ? " · " + esc(st.catalog) + (st.schema ? "." + esc(st.schema) : "") : ""} · ${st.write_allowed ? "쓰기 허용" : "읽기 전용"}<br>토큰 보호: ${esc(st.protection || "-")}${st.identity ? `<br>확인된 계정: <b>${esc(st.identity.user)}</b> (현재 catalog ${esc(st.identity.catalog || "-")})` : ""}${st.last_test ? `<br>마지막 테스트: ${esc(st.last_test)}` : ""}</div>` : `<div class="mute">아직 저장된 연결이 없습니다.</div>`}
      <div class="grid2"><div><label>워크스페이스 주소</label><input id="rh" value="${esc(st.host || "")}" placeholder="adb-1234567890.1.azuredatabricks.net 또는 xxx.cloud.databricks.com"></div><div><label>SQL Warehouse ID</label><input id="rw" value="${esc(st.warehouse_id || "")}" placeholder="예: 1a2b3c4d5e6f7a8b"></div>
        <div><label>기본 catalog <small>(선택)</small></label><input id="rc" value="${esc(st.catalog || "")}"></div><div><label>기본 schema <small>(선택)</small></label><input id="rs" value="${esc(st.schema || "")}"></div></div>
      <label>액세스 토큰 <small>(이 PC에만 저장 · 화면에는 다시 표시되지 않음)</small></label><input id="rt" type="password" autocomplete="off" placeholder="${st.configured ? "저장됨 — 바꾸려면 새 토큰 입력" : "dapi…"}">
      <div class="checks"><label><input type="checkbox" id="rco" ${st.configured ? "checked" : ""}> 교육용(비운영) 환경이며 고객 데이터·운영 자격증명이 아님에 동의합니다</label><label><input type="checkbox" id="rnp"> 이름에 'prod' 등이 있어도 비운영 환경임을 확인했습니다</label><label><input type="checkbox" id="rwr" ${st.write_allowed ? "checked" : ""}> 쓰기(INSERT·CREATE 등)를 허용합니다 <small>(기본은 읽기 전용)</small></label></div>
      <div class="row" style="margin-top:8px"><button class="primary" data-a="realsave">저장</button><button data-a="realtest" ${st.configured ? "" : "disabled"}>연결 테스트</button><button class="danger" data-a="realclear" ${st.configured ? "" : "disabled"}>연결 삭제(토큰 포함)</button></div>
      ${st.configured ? `<h3>실제 워크스페이스에서 SQL 실행</h3><textarea id="rsql" style="min-height:90px">${esc(LAST.realsql || "SELECT current_user() AS user, current_catalog() AS catalog")}</textarea><div class="row"><button data-a="realrun">실행</button><label class="mute"><input type="checkbox" id="rcf"> 되돌릴 수 없는 문장(DROP·TRUNCATE·GRANT 등) 확인</label></div><div class="sub">한 번에 한 문장 · 최대 ${nf(st.row_limit)}행 · ${st.write_allowed ? "쓰기 허용 상태" : "읽기 전용(SELECT·SHOW·DESCRIBE·EXPLAIN)"}</div>
        ${L ? `<div class="card">${badge("REAL_WORKSPACE_EXECUTED", "ok")} ${esc(L.keyword)} · ${nf(L.rows.length)}행${L.truncated ? " (잘림)" : ""} · ${nf(L.ms)}ms<div class="mute" style="word-break:break-all">결과 해시 <code>${esc(L.result_sha256)}</code></div>${table(L.columns, L.rows.map(r => r.map(c => c === null ? "NULL" : String(c))), true)}</div>` : ""}` : ""}`;
    return `<h2>실제 환경 연결</h2><div class="sub">내 교육용 워크스페이스나 테스트 DB에 연결해 실제 결과로 연습하는 방법입니다. 이 앱의 모의 결과와 실제 결과는 증거 수준으로 구분됩니다.</div>
    <div class="card"><b>연결 방법 3가지</b><div class="pgrid">
      ${path("A", "내 PC 어댑터로 실습하고 증거 제출", "설치 없이 가능합니다. 내 PC의 어댑터가 내 워크스페이스에서 실습 팩을 실행하고 <b>결과(해시)만</b> 이 앱에 제출합니다. 토큰은 어댑터가 내 PC에서만 씁니다.", scBtn(SCN("실습 증거함으로", "lab")))}
      ${path("B", "설치형 앱에서 직접 SQL 실행", `앱에서 내 교육용 워크스페이스의 SQL Warehouse에 직접 SQL을 보내 실제 결과를 봅니다. 읽기 전용이 기본이고 토큰은 내 PC에만 저장됩니다. ${st.enabled ? "<b>지금 사용 가능합니다.</b>" : "웹에서는 사용할 수 없습니다."}`, st.enabled ? `<a href="#" class="golink" data-a="realgo">아래 연결 설정으로 이동</a>` : `<button class="primary" data-a="appdl">설치형 앱 다운로드</button>`)}
      ${path("C", "다른 DB·특수 환경은 연결 신청", "Postgres·Oracle 같은 다른 DB나 회사 보안 정책 때문에 A·B가 어려운 경우, 필요한 연결을 신청하면 운영자가 검토해 지원 방법을 안내합니다(AXOS 개발큐로 접수).", scBtn({ type: "axos", label: "연결 신청하기 (AXOS)", kind: "CONNECT_REQUEST", title: "실제 환경 연결 신청", text: tpl }))}</div></div>
    <div class="card"><b>준비와 안전 수칙</b><ol class="pul">${steps.map(x => `<li>${x}</li>`).join("")}</ol><div class="sub">토큰·비밀번호를 피드백·채팅·화면 캡처에 남기지 마세요. 연결 정보는 언제든 [연결 삭제]로 지울 수 있고, 토큰은 워크스페이스에서 폐기하면 즉시 무효가 됩니다.</div></div>
    <div class="card" id="realform"><b>방법 B · 내 워크스페이스 연결 설정</b>${form}</div>`;
  },
  async usage() {
    if (ME.role !== "admin") return `<div class="empty"><h2>admin(수퍼유저) 전용 화면입니다</h2><p>접속·사용 기록은 admin 계정으로 로그인한 경우에만 볼 수 있습니다.</p></div>`;
    usageWatch();
    const [d, ev, pl, us] = await Promise.all([api(`/api/usage/summary?days=${USG.days}`), api(`/api/usage/events?limit=${USG.size}&offset=${USG.page * USG.size}&kind=${encodeURIComponent(USG.kind)}&q=${encodeURIComponent(USG.q)}&days=${USG.days}`), api("/api/usage/pulse"), api(`/api/usage/users?days=${USG.days}&q=${encodeURIComponent(USG.uq)}&offset=${USG.upage * USG.usize}&limit=${USG.usize}`)]);
    USG.fp = pl.fp; USG.at = Date.now();
    const k = d.kpi, p = d.prev, dates = d.daily.map(r => r.date);
    const okc = d.daily.map(r => r.cmds - r.cmd_fail), failc = d.daily.map(r => r.cmd_fail);
    const hourEntries = d.hourly.map((v, h) => [h, v]);
    const cmdOk = d.cmds.reduce((a, r) => a + r[1], 0), cmdBad = d.cmds.reduce((a, r) => a + r[2], 0);
    const vlabel = v => (NAV.flatMap(g => g[1]).find(n => n[0] === v) || [v, v])[1].replace(/^UI-\d+b?\s*/, "");
    const kindOpts = [["", "전체"], ...Object.entries(d.kinds)].map(([v, l]) => `<option value="${v}" ${USG.kind === v ? "selected" : ""}>${esc(l)}</option>`).join("");
    return `<h2>접속·사용 기록 <span class="mute" style="font-size:12px">admin 전용</span></h2>
    <div class="sub">웹 서버에 접속한 사용자의 로그인·화면 이동·명령 실행·오류·세션·피드백·다운로드 기록입니다. 이름·역할·화면/명령 종류·결과만 기록하고 <b>접근 코드, SQL·입력 본문, 피드백 내용은 저장하지 않으며</b> IP는 일부만 저장합니다. 최대 ${d.retention_days}일 보관 후 자동 삭제됩니다. 단독 설치형 앱 안의 사용은 사용자 PC에만 있어 포함되지 않습니다(다운로드·업데이트 요청만 기록).</div>
    <div class="vfilters"><span class="mute">기간</span>${[7, 30, 90].map(n => `<button class="${USG.days === n ? "primary" : ""}" data-a="usagedays" data-n="${n}">최근 ${n}일</button>`).join("")}<button data-a="usagerefresh" title="최신 기록으로 다시 불러오기">↻ 새로고침</button><label class="mute"><input type="checkbox" id="usauto" ${USG.auto ? "checked" : ""} onchange="USG.auto=this.checked"> 자동 갱신(새 기록이 있을 때만, 30초마다 확인)</label><span class="mute" style="margin-left:auto">집계 ${esc(d.generated)} (KST) · 이벤트 ${nf(d.total_events)}건 · 마지막 갱신 ${new Date().toLocaleTimeString("ko-KR")}</span></div>
    <div class="kpis">${kpiTile("로그인", k.logins, p.logins)}${kpiTile("고유 사용자(이름 기준)", k.users, p.users, { unit: "명" })}${kpiTile("명령 실행", k.cmds, p.cmds)}${kpiTile("명령 실패", k.cmd_fail, p.cmd_fail)}${kpiTile("세션 생성", k.sessions, p.sessions)}${kpiTile("화면 열기", k.views, p.views)}${kpiTile("AI 지원 질문", k.chats, p.chats)}${kpiTile("피드백", k.feedback, p.feedback)}${kpiTile("앱 다운로드", k.downloads, p.downloads)}${kpiTile("로그인 실패", k.login_fail, p.login_fail)}</div>
    <div class="vgrid2"><div class="card vc"><b>일별 접속</b><div class="sub">로그인 수와 고유 사용자 수</div>${lineChart(dates, [{ name: "로그인", color: SER[0], values: d.daily.map(r => r.logins) }, { name: "고유 사용자", color: SER[1], values: d.daily.map(r => r.users) }], { label: "일별 로그인과 고유 사용자" })}${tableView(["날짜", "로그인", "고유 사용자"], d.daily.map(r => [r.date, r.logins, r.users]))}</div>
    <div class="card vc"><b>일별 명령 실행</b><div class="sub">성공 / 실패</div>${barChart(dates, [{ name: "성공", icon: "✓", color: "var(--vgood)", values: okc }, { name: "실패", icon: "✕", color: "var(--vbad)", values: failc }], { fmt: x => x.slice(5), label: "일별 명령 실행 성공·실패" })}${tableView(["날짜", "성공", "실패"], d.daily.map((r, i) => [r.date, okc[i], failc[i]]))}</div></div>
    <div class="vgrid2"><div class="card vc"><b>시간대별 사용량</b><div class="sub">모든 이벤트, 한국 시간</div>${barChart(hourEntries.map(e => String(e[0])), [{ name: "이벤트", color: SER[0], values: d.hourly }], { fmt: h => h + "시", maxLabels: 12, label: "시간대별 사용량" })}</div>
    <div class="card vc"><b>요일 × 시간대 히트맵</b><div class="sub">언제 가장 많이 쓰는지</div>${heatmap(d.heat)}</div></div>
    <div class="vgrid2"><div class="card vc"><b>많이 연 화면</b>${hbars(d.views.map(([v, n]) => [v, n]), { label: vlabel })}</div>
    <div class="card vc"><b>많이 쓴 명령</b><div class="sub">실패가 있으면 오른쪽에 표시</div>${hbars(d.cmds.map(([t, ok, bad]) => [t, ok + bad, bad ? `실패 ${bad}` : ""]))}${cmdOk + cmdBad ? `<div class="sub" style="margin-top:6px">성공률 <b>${Math.round(cmdOk / (cmdOk + cmdBad) * 100)}%</b> (${nf(cmdOk)} / ${nf(cmdOk + cmdBad)})</div>` : ""}</div></div>
    <div class="vgrid3"><div class="card vc"><b>역할별 로그인</b>${segBar(Object.entries(d.roles).map(([r, n]) => [ROLEL[r] || r, n]))}</div>
    <div class="card vc"><b>접속 단말</b>${segBar(Object.entries(d.clients).map(([r, n]) => [CLIL[r] || r, n]))}</div>
    <div class="card vc"><b>앱 다운로드</b>${segBar(Object.entries(d.downloads).map(([r, n]) => [DLL[r] || r, n]))}</div></div>
    <div class="vgrid2"><div class="card vc"><b>AI 지원 질문 종류</b><div class="sub">질문 내용은 저장하지 않고 분류만 기록</div>${hbars(d.chat)}</div>
    <div class="card vc"><b>API 오류 코드</b><div class="sub">서버가 거절·실패로 응답한 요청(인증 만료 제외)</div>${hbars(d.errors, { color: "var(--vbad)" })}${d.login_fail_ips.length ? `<div class="sub" style="margin-top:8px">로그인 실패 많은 IP(일부 마스킹): ${d.login_fail_ips.map(([ip, n]) => `${esc(ip)} ${n}회`).join(" · ")}</div>` : ""}</div></div>
    <div class="card"><b>사용자별 활동</b> <span class="mute">이름 기준 · 이벤트 많은 순 · 최근 ${USG.days}일</span>
      <div class="vfilters"><input id="usuq" value="${esc(USG.uq)}" placeholder="이름·역할 검색" style="width:220px" onkeydown="if(event.key==='Enter')H.usersearch()"><button data-a="usersearch">검색</button>${USG.uq ? `<button class="ghost" data-a="usersearchclear">검색 지우기</button>` : ""}</div>
      ${table(["이름", "역할", "이벤트", "로그인", "명령", "명령 실패", "최근", "단말"], us.items.map(u => [u.name, ROLEL[u.role] || u.role, u.events, u.logins, u.cmds, u.cmd_fail, u.last, CLIL[u.client] || u.client || "-"]), true)}${pagerHtml(us.total, USG.upage, USG.usize, "userpage")}</div>
    <div class="card"><b>최근 기록</b>
      <div class="vfilters"><select id="uskind" onchange="H.usagefilter()">${kindOpts}</select><input id="usq" value="${esc(USG.q)}" placeholder="이름·내용·IP 검색" style="width:200px" onkeydown="if(event.key==='Enter')H.usagefilter()"><button data-a="usagefilter">검색</button>${USG.q || USG.kind ? `<button class="ghost" data-a="usageclear">조건 지우기</button>` : ""}<span class="mute" style="margin-left:auto">최근 ${USG.days}일 · 조건에 맞는 ${nf(ev.total)}건</span></div>
      ${table(["시각(KST)", "종류", "이름", "역할", "내용", "단말", "IP"], ev.items.map(e => [e.time, e.kind_label, e.name || "-", ROLEL[e.role] || e.role || "-", Object.entries(e.detail).map(([a, b]) => `${a}=${b}`).join(" · "), CLIL[e.client] || "-", e.ip || "-"]), true)}
      ${pagerHtml(ev.total, USG.page, USG.size, "usagepage")}</div>`;
  },
  async fbq() {
    if (ME.role !== "admin") return `<div class="empty"><h2>admin(수퍼유저) 전용 화면입니다</h2><p>피드백 관리와 개발큐는 admin 계정으로 로그인한 경우에만 사용할 수 있습니다.</p></div>`;
    const d = await api(`/api/feedback/admin?status=${FBQ.status}&q=${encodeURIComponent(FBQ.q)}&page=${FBQ.page}&size=${FBQ.size}`); FBQ.page = d.page; FBQ.ids = d.ids;
    const chips = [["", "전체", Object.values(d.counts).reduce((a, b) => a + b, 0)], ...Object.entries(d.status_labels).map(([k, l]) => [k, l, d.counts[k] || 0])].map(([k, l, n]) => `<button class="${FBQ.status === k ? "primary" : ""}" data-a="fbfilter" data-s="${k}">${esc(l)} ${n}</button>`).join(" ");
    const rows = d.items.map(f => `<tr><td><input type="checkbox" class="fbchk" data-id="${esc(f.id)}" ${FBQ.checked.has(f.id) ? "checked" : ""} aria-label="${esc(f.id)} 선택"></td><td>${esc(f.id)}</td><td>${esc(f.kind_label)}</td><td>${esc(f.title)}</td><td>${esc(f.view)}</td><td>${esc(f.submitted_by_name)}</td><td>${esc(fmtIso(f.created))}</td><td>${esc(f.priority || "")}</td><td>${fbBadge(f.status)}</td><td><button data-a="fbopen" data-id="${esc(f.id)}">열기</button></td></tr>`).join("");
    let det = "";
    if (FBQ.sel) {
      try {
        const f = await api("/api/feedback/" + FBQ.sel);
        const imgs = await Promise.all(f.images.map(async im => { const r = await fetch(`/api/feedback/${f.id}/image/${im.n}`, { headers: { Authorization: "Bearer " + TOKEN } }); return r.ok ? URL.createObjectURL(await r.blob()) : "" }));
        const nxt = d.flow[f.status] || [];
        det = `<div class="card"><div style="display:flex;justify-content:space-between"><b>${esc(f.id)} · ${esc(f.title)}</b><button class="ghost" data-a="fbclose">닫기</button></div>
          <div class="sub">${esc(f.kind_label)} · ${fbBadge(f.status)} · 제출 ${esc(f.submitted_by_name)} (${esc(f.role)}) · 접수 ${esc(fmtIso(f.created))}${f.edited_at ? " · 수정 " + esc(fmtIso(f.edited_at)) : ""}<br>화면 <code>${esc(f.view)}</code> · ${esc(f.context.view_label || "")} · v${esc(f.context.version || "")} · 빌드 ${esc(f.context.build || "")} · ${esc(f.context.client || "")} · ${esc(f.context.viewport || "")}</div>
          <pre style="white-space:pre-wrap">${esc(f.text)}</pre>
          ${f.domain ? `<div class="sub"><b>도메인 신청</b>: ${esc(f.domain.domain)} · 목적 ${esc(f.domain.purpose)} · 데이터 ${esc(f.domain.data)} · 문제 ${esc(f.domain.issues)} · 시기 ${esc(f.domain.when)}</div>` : ""}
          <div class="fbthumbs">${imgs.map(u => u ? `<a href="${u}" target="_blank" rel="noopener"><img src="${u}" alt="첨부" style="max-width:220px;max-height:160px"></a>` : "").join("")}</div>
          <div class="sub"><b>이력</b>: ${f.history.map(h => `${esc(FB_LBL[h.to])}(${esc(fmtIso(h.at))}${h.note ? " · " + esc(h.note) : ""})`).join(" → ")}</div>
          ${nxt.length ? `<div class="row" style="gap:8px;flex-wrap:wrap;align-items:end"><div><label>우선순위</label><select id="fbprio"><option>P1</option><option selected>P2</option><option>P3</option></select></div><div><label>반영 버전 <small>(반영완료 시)</small></label><input id="fbrel" value="${esc(SYS.version)}" style="width:90px"></div><div style="flex:1;min-width:200px"><label>메모·사유 <small>(반려/보류는 필수 · 제출자에게 표시)</small></label><input id="fbnote" maxlength="500"></div></div>
            <div style="margin-top:8px;display:flex;gap:6px;flex-wrap:wrap">${nxt.map(t => `<button class="${t === "REJECTED" ? "" : "primary"}" data-a="fbmove" data-to="${t}">→ ${esc(d.status_labels[t])}</button>`).join("")}</div>` : `<div class="mute">종결된 항목입니다.</div>`}
          ${FBQ.edit ? `<div class="card" style="margin-top:8px"><b>피드백 수정</b> <span class="mute">(수정 이력이 남고, 개발큐·개발중이면 개발 지시서가 다시 만들어집니다)</span><label>제목</label><input id="fbet" value="${esc(f.title)}" maxlength="120"><label>내용</label><textarea id="fbex" rows="5" maxlength="4000">${esc(f.text)}</textarea><div class="row" style="gap:8px;align-items:end"><div><label>유형</label><select id="fbek" ${f.kind === "DOMAIN_REQUEST" ? "disabled" : ""}>${Object.entries(f.kind === "DOMAIN_REQUEST" ? { DOMAIN_REQUEST: "전이 도메인 신청" } : FB_KINDS).map(([k, l]) => `<option value="${k}" ${f.kind === k ? "selected" : ""}>${esc(l)}</option>`).join("")}</select></div><div><label>우선순위</label><select id="fbep">${["", "P1", "P2", "P3"].map(x => `<option value="${x}" ${(f.priority || "") === x ? "selected" : ""}>${x || "(없음)"}</option>`).join("")}</select></div></div><div style="margin-top:8px"><button class="primary" data-a="fbsaveedit">수정 저장</button> <button class="ghost" data-a="fbeditoff">취소</button></div></div>` : ""}
          <div style="margin-top:8px;display:flex;gap:6px"><button data-a="fbediton">수정</button><button class="danger" data-a="fbdelone" data-id="${esc(f.id)}">이 건 삭제</button></div>
          ${f.ticket_md ? `<details ${f.status === "QUEUED" || f.status === "IN_DEV" ? "open" : ""}><summary><b>개발 지시서</b></summary><pre style="white-space:pre-wrap">${esc(f.ticket_md)}</pre></details>` : ""}</div>`;
      } catch (e) { det = err(e) }
    }
    return `<h2>피드백 관리 · 개발큐 <span class="mute" style="font-size:12px">admin 전용</span></h2><div class="sub">AXOS 폐루프: 접수 → 검토·승인 → <b>개발큐</b> → 개발중 → 반영완료. 개발큐로 옮기면 개발 지시서가 자동 생성되며, <b>개발큐.md</b>를 내려받아 개발 입력으로 씁니다.</div>
      <div style="margin:8px 0;display:flex;gap:6px;flex-wrap:wrap">${chips} <span style="flex:1"></span><button data-a="fbqueue">개발큐.md 다운로드</button></div>
      <div class="vfilters"><input id="fbqq" value="${esc(FBQ.q)}" placeholder="번호·제목·내용·제출자·유형·화면·우선순위 검색" style="width:340px" onkeydown="if(event.key==='Enter')H.fbsearch()"><button data-a="fbsearch">검색</button>${FBQ.q ? `<button class="ghost" data-a="fbsearchclear">검색 지우기</button>` : ""}<span class="mute">${FBQ.q || FBQ.status ? `조건에 맞는 ${nf(d.total)}건` : `전체 ${nf(d.total)}건`}</span></div>
      <div class="fbbar"><button data-a="fbselall">이 쪽 전체 선택/해제</button><button data-a="fbselresult" title="검색·상태 조건에 맞는 모든 건(최대 500건)을 선택">조건에 맞는 ${nf(Math.min(d.total, 500))}건 모두 선택</button><span class="mute">선택 <b>${FBQ.checked.size}</b>건(다른 쪽 포함)</span><select id="fbbto"><option value="">상태 변경…</option>${Object.entries(d.status_labels).map(([k, l]) => `<option value="${k}">→ ${esc(l)}</option>`).join("")}</select><input id="fbbnote" placeholder="사유·메모(반려/보류 필수)" style="width:200px"><input id="fbbrel" placeholder="반영 버전(반영완료 시)" value="${esc(SYS.version)}" style="width:130px"><button data-a="fbbulk">선택 일괄 변경</button><button class="danger" data-a="fbdel">선택 삭제</button></div>${det}
      <div class="tw"><table><tr>${["", "번호", "유형", "제목", "화면", "제출자", "접수 일시", "우선", "상태", ""].map(c => `<th>${c}</th>`).join("")}</tr>${rows || `<tr><td colspan="10" class="mute">(없음)</td></tr>`}</table></div>${pagerHtml(d.total, d.page, d.size, "fbpage")}`;
  },
  async ko() {
    const k = await api("/api/ko-guide");
    return `<h2>한국어 공식 가이드 대조</h2><div class="sub">${esc(k.method)}</div>` + Object.entries(k.exams).map(([ex, d]) => `<div class="card"><b>${ex}</b> ${badge(d.status === "ALIGNED_HASH_LINKED" ? "영문 최신본과 구조 일치" : "이전 버전(참고용)", d.status === "ALIGNED_HASH_LINKED" ? "ok" : "w")}
      <div class="sub">한국어판 ${esc(d.version)} · bullet ${d.bullet_count}개 (영문 최신 ${d.en_bullet_count}개) · PDF sha256 <code>${esc(d.guide_sha256.slice(0, 16))}…</code> · <a href="${esc(d.source_url)}" target="_blank" rel="noopener">원문 PDF</a></div><div class="sub">${esc(d.note)}</div>
      ${table(["영역", "이름", "비중", "한국어 bullet", "영문 bullet", "일치"], d.sections.map(r => [r.section_no, r.section_name, r.weight == null ? "-" : r.weight + "%", r.ko_bullets, r.en_bullets, r.match ? "✓" : "차이"]))}</div>`).join("");
  },
  async xfer() {
    const [seeds, sc] = await Promise.all([api("/api/transfer-seeds"), api("/api/collab/scenario")]);
    let team = null; if (LAST.team) { try { team = await api("/api/collab/teams/" + LAST.team) } catch (e) { team = null } }
    const sk = LAST.seedkey;
    return `<h2>전이 산업 시드 · 협업 훈련</h2><div style="margin:-2px 0 10px"><button class="primary" data-a="axos" data-t="dom">원하는 도메인 신청</button> <span class="mute">원하는 산업 도메인이 없나요? 신청하면 담당자에게 전달되어 추가됩니다.</span></div><div class="sub">식자재 주문에서 익힌 규칙을 다른 산업 데이터에 옮겨 보는 과제용 합성 CSV입니다. 본인 교육용 워크스페이스 볼륨에 올려 사용하세요.</div>
    <div class="card"><b>전이 시드</b>${table(["시드", "용도", "파일", ""], seeds.map(s => [s.title, s.use, Object.entries(s.files).map(([n, f]) => `${n} (${f.rows}행, ${f.sha256.slice(0, 8)}…)`).join("<br>"), `<button data-a="seeddl" data-id="${s.seed_id}">CSV 받기</button>${staff() ? ` <button class="ghost" data-a="seedkey" data-id="${s.seed_id}">정답표</button>` : ""}`]))}
    ${sk ? `<div class="sub"><b>${esc(sk.id)} 정답표(직원 전용)</b></div>${prettyBox(sk.key, true)}` : ""}</div>
    <div class="card"><b>협업 훈련: ${esc(sc.title)}</b><div class="sub">${esc(sc.brief)}</div>${table(["작업", "역할", "선행", "산출물", "인계 대상"], sc.tasks.map(t => [t.task_id + " " + t.title, t.role, t.after.join(", ") || "-", t.produce, t.handoff_to || "-"]))}
      <div class="row"><input id="tm_name" placeholder="팀 이름"><button data-a="teamnew">팀 만들기</button><input id="tm_id" placeholder="팀 ID" value="${esc(LAST.team || "")}"><button class="ghost" data-a="teamload">불러오기</button></div>
      ${team ? `<div class="row"><select id="tm_role">${["DBA", "DATA_ENGINEER", "AX", "REVIEWER"].map(r => `<option>${r}</option>`).join("")}</select><button data-a="teamjoin">이 역할로 참여</button></div>
      <div class="row"><select id="tm_task">${sc.tasks.map(t => `<option>${t.task_id}</option>`).join("")}</select><input id="tm_sha" placeholder="산출물 sha256 (64자리)" style="width:300px"><input id="tm_note" placeholder="인계 메모 (10자 이상)" style="width:260px"><button data-a="teamsubmit">제출</button></div>
      <div class="row"><input id="tm_reason" placeholder="반려 사유(반려 시 필수)" style="width:260px"><button data-a="teamreview" data-ok="1">승인</button><button class="ghost" data-a="teamreview" data-ok="0">반려</button></div>
      <div class="sub">팀 ${esc(team.team_id)} · 완료 ${team.complete ? "✓" : "아직"} · 빠진 역할 ${esc(team.missing_roles.join(", ") || "없음")}</div>${table(["작업", "상태", "제출자", "승인자", "반려 사유"], Object.entries(team.tasks).map(([k, v]) => [k, v.status, v.submitted_by || "-", v.approved_by || "-", v.rejected_reason || ""]))}<div class="sub">${esc(team.note)}</div>` : `<div class="sub">팀을 만들거나 팀 ID를 불러오세요.</div>`}</div>`;
  },
  async rvw() {
    if (!staff()) return `<h2>검토 센터</h2><p class="mute">검토자/강사 전용입니다.</p>`;
    const q = await api("/api/review/queue");
    return `<h2>검토 센터 <small class="mute">컨설턴트 자체 검토</small></h2><div class="sub">실제 Databricks 교육용 워크스페이스에서 직접 확인한 것만 기록하세요. 문서로만 본 것은 기록하지 않습니다. ${esc(q.note)}</div>
    <div class="card"><b>검토자 매뉴얼</b> <button data-a="rvmanual">검토자_매뉴얼.md 다운로드</button><div class="sub">준비물 · 기능 재확인 · 원문 대조 · 문항 검수 · 실습 21개 절차 · 기록 규칙이 들어 있습니다.</div></div>
    <div class="grid2"><div class="card"><b>원문 대조</b> ${q.objectives.verified}/${q.objectives.total}${table(["목표", "시험", "요약", ""], q.objectives.unverified_sample.map(o => [o.id, o.exam, o.summary, `<button data-a="objverify" data-id="${o.id}">PDF와 대조함</button>`]))}</div>
    <div class="card"><b>문항 검수</b> ${esc(Object.entries(q.items.by_status).map(([k, v]) => k + " " + v).join(" · "))}${table(["문항", "시험", "상태", "다음"], q.items.queue.map(i => [i.id, i.exam, i.status, `<button data-a="itemrev" data-id="${i.id}" data-stage="${i.next}">${i.next} 통과</button>`]))}</div></div>
    <div class="card"><b>기능 재확인(워크스페이스에서 직접 확인 후)</b> ${q.features.not_workspace_checked.length}/${q.features.total} 미확인${table(["기능", "상태", ""], q.features.not_workspace_checked.map(f => [f.id, f.status, `<button data-a="featcheck" data-id="${f.id}">확인함</button>`]))}</div>
    <div class="card"><b>그 밖의 검토</b> <div class="sub">실습 증거 승인 대기 ${q.lab_evidence_pending}건 · 현장 대조표 ${q.matrix_rows}행. <a href="#" data-a="nav" data-v="lab">실습 증거함</a> · <a href="#" data-a="nav" data-v="vmx">현장 대조표</a> · <a href="#" data-a="nav" data-v="map">공식 목표</a></div></div>`;
  },
  async env() {
    const sp = await api(`/api/sessions/page?q=${encodeURIComponent(SESSQ.q)}&page=${SESSQ.page}&size=${SESSQ.size}`); SESSQ.page = sp.page; SESSQ.ids = sp.ids; const sess = sp.items; const feats = await api("/api/features");
    return `<h2>UI-01 환경 점검</h2><div class="sub">클라우드·리전·프로필·권한·미지원 항목 확인. 프로필은 선택 예시이며 모든 기능이 가능하다는 보증이 아닙니다.</div>
    <div class="card"><b>새 세션</b><div class="row"><select id="mode"><option value="B">B 로컬 코드 실습 (LOCAL_EXECUTED)</option><option value="A">A 완전 모의 (SIMULATED)</option><option value="C">C 실제 교육용 DBX (이 배포 미지원)</option></select>
    <select id="seedsel"><option value="food-order-v1">시드 v1</option><option value="food-order-v2">시드 v2 (다른 숫자)</option><option value="food-order-v3">시드 v3 (다른 숫자)</option></select><select id="lmode"><option value="guided">안내형</option><option value="practice">실습형</option><option value="real">실전형</option><option value="demo">고객 시연형</option></select><button data-a="newsess">세션 시작</button></div>
    <div class="sub">실습 범위: 식자재 주문 변경 합성 데이터(거래처 30·상품 100·주문 300·주문행 900, 시드 food-order-v1, 기준시각 2026-11-11 15:20 KST). 실행 경계: Python/PySpark 미실행, 외부 접속 차단. 모드는 실행 중 전환 불가.</div></div>
    <div class="card"><b>${ME.role === "admin" ? "전체 세션 (admin)" : "내 세션"}</b>${(() => { const L = sess; const bar = `<div class="vfilters"><input id="sessq" value="${esc(SESSQ.q)}" placeholder="세션 ID·사용자·레슨·모드 검색" style="width:260px" onkeydown="if(event.key==='Enter')H.sesssearch()"><button data-a="sesssearch">검색</button>${SESSQ.q ? `<button class="ghost" data-a="sesssearchclear">검색 지우기</button>` : ""}<span class="mute">${SESSQ.q ? "조건에 맞는 " : "전체 "}${nf(sp.total)}개</span></div>`; return (L.length || SESSQ.q) ? bar + `<div style="margin:6px 0;display:flex;gap:6px;flex-wrap:wrap;align-items:center"><button data-a="sesssel">이 쪽 전체 선택/해제</button><button data-a="sessselall">조건에 맞는 ${nf(Math.min(sp.total, 500))}개 모두 선택</button><button data-a="sessdel">선택 삭제</button><span class="mute">선택 <b>${SESSQ.checked.size}</b>개(다른 쪽 포함)</span></div>` + table(["", "세션", "사용자", ...(ME.role === "admin" ? ["사용자 ID"] : []), "레슨", "모드", "진행", "revision", "생성 일시", "최종 작업 일시", ""], L.map(s => [`<input type="checkbox" class="sesschk" data-id="${esc(s.session_id)}" ${SESSQ.checked.has(s.session_id) ? "checked" : ""} aria-label="${esc(s.session_id)} 선택">`, s.session_id, s.owner_name || "(이름 미기록)", ...(ME.role === "admin" ? [s.owner] : []), s.lesson_id, s.mode + "/" + s.learning_mode, `${s.completed}/${s.lessons}`, s.revision, fmtKst(s.created_at), fmtKst(s.last_activity_at), `<a href="#" data-a="opensess" data-id="${esc(s.session_id)}">열기</a>`])) + pagerHtml(sp.total, sp.page, sp.size, "sesspage") : '<div class="mute">(없음)</div>' })()}</div>
    ${ST ? `<div class="card"><button data-a="c" data-t="env.check">환경 점검 실행</button> <button data-a="whstart">Warehouse 시작</button><div class="sub">환경 점검·미확인 항목이 로그와 증거에 기록됩니다.</div></div>` : ""}
    <div class="card"><b>기능 매니페스트</b> <span class="mute">(${esc(feats.profile)})</span><div class="sub">각 기능을 <b>지금 쓸 수 있는지</b>와 <b>얼마나 확인됐는지</b>를 보여 줍니다. <b>[사용해 보기]</b>를 누르면 그 기능을 쓰는 상황을 모의로 실행해 결과(가능/확인 필요)를 실행 로그에 남깁니다.${ST ? "" : " <b>세션을 먼저 시작해야 누를 수 있습니다.</b>"}</div>${table(["기능", "확인 상태", "워크스페이스", "화면 위치", "사용 가능", ""], feats.features.map(f => [`<span><b>${esc(f.feature_id.replace(/_/g, " "))}</b></span>`, badge(({ DOC_CHECKED: "문서 확인", WORKSPACE_CHECKED: "워크스페이스 확인", DRAFT: "초안", STALE: "재확인 필요(오래됨)", DBX_VERIFIED: "DBX 실측" })[f.status] || f.status, f.status === "WORKSPACE_CHECKED" || f.status === "DBX_VERIFIED" ? "ok" : "w"), badge(({ unknown: "미확인", true: "켜짐", false: "꺼짐" })[String(f.workspace_enabled)] || String(f.workspace_enabled), f.workspace_enabled === true ? "ok" : "w"), String(f.ui_path || "-"), badge(f.usable ? "모의 가능" : "확인 필요", f.usable ? "ok" : "bad"), ST ? `<button data-a="c" data-t="feature.use" data-p='${JSON.stringify({ feature_id: f.feature_id })}'>사용해 보기</button>` : `<span class="mute">세션 필요</span>`]))}</div>
    <div class="card"><b>기준 프로필</b> <span class="mute">— 이 학습 환경이 가정하는 Databricks 환경 설정입니다</span>${profileHtml(META.profile)}</div>`;
  },
  async req() {
    return `<h2>UI-02 착수·요구·데이터 계약</h2><div class="sub">고객 인터뷰 카드로 누락 요구를 발견하고 계약을 검토합니다.</div>
    <div class="grid2"><div class="card"><b>인터뷰 카드</b><ul><li>마감(15:00) 이후 주문 변경은 누가 승인하나요? <span class="mute">→ 예외계약 거래처만, 승인 필요</span></li><li>"가용재고"의 정의는? <span class="mute">→ 기존 20박스 예약 이후 추가 할당 가능한 수량</span></li><li>매출 공급가와 VAT, 반품 음수는? <span class="mute">→ 공급가 VAT 별도, 반품은 음수 수량(line_type=RETURN)</span></li><li class="warnc">누락 질문 후보: 여신 차단 기준, 노선 마감 기준, 대체 단위 불일치 처리</li></ul></div>
    <div class="card"><b>데이터 계약 (승인 전 검토)</b><pre>available_qty = SUM(on_hand_qty - reserved_qty - damaged_qty) per product_id
공급가(supply_amount)는 VAT 제외, vat_amount = 공급가 × 10%
반품: line_type = RETURN, qty_boxes &lt; 0
order version: 주문 변경마다 +1 (낙관적 잠금)</pre><div class="sub">gold.v_available_inventory 는 시드 상태에서 계약과 다릅니다. SQL Editor에서 확인하고 수정하세요.</div></div></div>`;
  },
  async ws() {
    const a = await api(`/api/sessions/${SID}/audit`);
    return `<h2>UI-03 Workspace</h2><div class="row"><input id="wsq" placeholder="검색(리소스명)" oninput="document.querySelectorAll('#wsl tr').forEach((r,i)=>{if(i)r.style.display=r.textContent.toLowerCase().includes(this.value.toLowerCase())?'':'none'})"></div>
    <div class="card"><div id="wsl">${table(["종류", "이름", "상태/리비전"], [...ST.notebook.cells.map(c => ["Notebook cell", c.id + " (" + c.lang + ")", c.status]), ...Object.keys(ST.bundle.files).map(f => ["File", f, ST.bundle.local_hash.slice(0, 8)]), ...Object.values(ST.pipelines).map(p => ["Pipeline", p.name, p.state]), ...Object.values(ST.jobs).map(j => ["Job", j.name, j.runs.length + " runs"])])}</div></div>
    <h3>변경 이력 (감사 이벤트 최근 25)</h3>${table(["시각(시나리오)", "유형", "주체", "결과", "증거"], a.slice(-25).reverse().map(e => [e.scenario_clock.slice(11, 19), e.event_type, e.effective_principal, e.outcome, e.evidence_level]))}`;
  },
  async cat() {
    const c = await api(`/api/sessions/${SID}/catalog` + (PRINCIPAL ? `?principal=${encodeURIComponent(PRINCIPAL)}` : ""));
    const t = LAST.tbl;
    return `<h2>UI-04 Catalog Explorer</h2><div class="sub">3단계 이름 catalog.schema.table · 주체 ${esc(c.principal)} 기준 가시성 ${staff() ? `· <a href="#" data-a="asrole" data-p="">trainee</a> | <a href="#" data-a="asrole" data-p="analyst-b@wizbase.training">analyst-b</a> | <a href="#" data-a="asrole" data-p="svc-runner">svc-runner</a>` : ""}</div>
    <div class="grid2"><div class="card"><b>${esc(c.catalog)}</b>${c.schemas.map(s => `<div><b>${s.usable ? "📂" : "🔒"} ${s.schema}</b> ${s.usable ? "" : badge("USE SCHEMA/CATALOG 없음", "bad")}<br>${s.tables.map(x => `<div style="margin-left:14px">${x.type === "VIEW" ? "👁" : "▦"} ${x.can_select ? `<a href="#" data-a="ctable" data-n="${c.catalog}.${s.schema}.${x.name}">${x.name}</a>` : `<span class="mute">${x.name}</span> ${badge("SELECT 불가", "bad")}`} <span class="mute">owner ${esc(x.owner)}</span></div>`).join("")}</div>`).join("")}${c.foreign_catalogs.map(f => `<div>🌐 ${f.catalog} (${f.kind})</div>`).join("")}</div>
    <div class="card">${t ? (t.error ? resBox({ result: { error: t.error } }) : `<b>${esc(t.name)}</b> ${lv(t.evidence_level)} owner ${esc(t.owner)}<h3>컬럼</h3>${table(["이름", "타입"], t.columns.map(x => [x.name, x.type]))}<h3>미리보기</h3>${table(t.preview_columns, t.rows)}<h3>계보</h3>${table(["upstream", "downstream"], t.lineage)}`) : '<span class="mute">테이블을 선택하세요. 부모 USE 권한 없이는 목록에서 잠깁니다.</span>'}</div></div>`;
  },
  async sql() {
    return `<h2>UI-05 SQL Editor</h2><div class="sub">Warehouse ${esc(ST.warehouse.state)} · 구문 분석(AST) → 지원 범위 → UC 권한 → Warehouse → 격리 실행 → 감사. 지원: SELECT/JOIN/GROUP BY/CTE/CASE, CREATE SCHEMA/TABLE/VIEW, INSERT, GRANT/REVOKE(관리자). Spark와 의미가 다를 수 있음.</div>
    <div class="card"><textarea id="sqlbox">${esc(LAST.sqlq || "SELECT * FROM food_dev.silver.orders LIMIT 5")}</textarea><div class="row"><button data-a="sql">실행</button>${ME.role === "instructor" || ME.role === "admin" ? `<select id="asp"><option value="">내 신원</option><option>uc-admin@wizbase.training</option><option>svc-runner</option><option>analyst-b@wizbase.training</option></select>` : ""}<button class="sec" data-a="whstart">Warehouse 시작</button>
    <span class="mute">예: SELECT product_id, SUM(on_hand_qty-reserved_qty-damaged_qty) AS available_qty FROM food_dev.silver.inventory GROUP BY product_id</span></div></div>
    ${resBox(LAST.sql)}<h3>실행 이력</h3><div class="sub">실패(failed)를 누르면 원인과 해결 순서, 바로가기가 펼쳐집니다. 성공한 문장은 [다시 쓰기]로 편집기에 불러옵니다.</div>
    <div class="tw"><table><tr><th>SQL</th><th>상태</th><th></th></tr>${HIST.sql.slice(0, 10).map((h, i) => `<tr><td><code>${esc(h.q.slice(0, 90))}</code></td><td>${h.s === "ok" ? badge("ok", "ok") : `<button class="b bad hfail" data-a="hfix" data-i="${i}" title="원인과 해결 방법 보기">${esc(h.s || "failed")} ▸ ${HFIX === i ? "접기" : "해결 방법"}</button>`}</td><td><button class="ghost" data-a="hreuse" data-i="${i}">다시 쓰기</button></td></tr>${HFIX === i && h.err ? `<tr><td colspan="3">${remedyHtml(h.err)}</td></tr>` : ""}`).join("") || `<tr><td colspan="3" class="mute">(없음)</td></tr>`}</table></div>`;
  },
  async nb() {
    const nb = ST.notebook;
    return `<h2>UI-06 Notebook</h2><div class="sub">셀별 실행 순서·코드 해시·stale 표시. Python 셀은 격리 실행기 미구성으로 차단됩니다(가짜 spark 없음).</div>
    <div class="row"><button data-a="nbadd" data-lang="sql">+ SQL 셀</button><button class="sec" data-a="nbadd" data-lang="python">+ Python 셀</button><button class="danger" data-a="nbrestart">커널 재시작</button></div>
    ${nb.cells.map(c => `<div class="card"><b>[${c.exec_order ?? " "}] ${c.id} ${c.lang}</b> ${c.stale ? badge("STALE: 위 셀 수정됨", "bad") : ""} ${c.status === "failed" ? badge("failed", "bad") : c.status === "ok" ? badge("ok", "ok") : ""}<textarea id="cell_${c.id}">${esc(c.code)}</textarea><div class="row"><button data-a="nbrun" data-id="${c.id}">실행</button><button class="sec" data-a="nbedit" data-id="${c.id}">수정 저장</button></div>${c.output ? (c.output.error ? resBox({ result: { error: c.output.error } }) : table(c.output.columns, c.output.rows)) : ""}</div>`).join("")}
    <h3>변수 상태 (-- as: 이름)</h3>${Object.keys(nb.vars || {}).length ? pretty(nb.vars) : `<div class="mute">(저장된 변수 없음 — 셀에 <code>-- as: 이름</code>을 쓰면 결과가 변수로 저장됩니다)</div>`}<div class="mute">재시작 ${nb.restarts}회 · 메모리 변수 초기화, 영속 테이블 유지</div>`;
  },
  async comp() {
    const w = ST.warehouse; const me = ST.principals[ST.principal] || {};
    return `<h2>UI-07 Compute / SQL Warehouses</h2><div class="card"><b>${esc(w.name)}</b> 상태 ${badge(w.state, w.state === "RUNNING" ? "ok" : w.state === "FAILED" ? "bad" : "w")} CAN USE: ${w.acl.join(", ")}<div class="row"><button data-a="whstart">시작</button><button class="sec" data-a="whstop">중지</button></div>
    <div class="sub">내 entitlement: ${(me.entitlements || []).join(", ")} · UC 권한만으로는 Warehouse가 실행되지 않습니다. 시작에는 몇 번의 명령 후 RUNNING 으로 전이됩니다(결정적).</div></div>
    <div class="card"><b>모의 사용량 지수</b>${pretty(ST.usage_index)}</div>`;
  },
  async conn() {
    const c = ST.connections.oracle_food_conn; const cats = ["NETWORK", "AUTH", "SOURCE_PRIVILEGE", "UC_PRIVILEGE", "UNSUPPORTED", "CDC_PREREQ", "INCREMENTAL", "SCHEMA_DRIFT"];
    return `<h2>UI-08 Connections / 수집</h2><div class="sub">원천: ${esc(c.engine)} · 호스트 ${esc(c.host)} (합성 .invalid). 실제 호스트·비밀번호는 저장/접속되지 않습니다.</div>
    <div class="card"><b>수집 방식 선택</b> 현재: ${c.mode || "미선택"}<div class="row"><button data-a="conn" data-x="select_mode" data-mode="federation">Federation</button><button data-a="conn" data-x="select_mode" data-mode="batch">배치</button><button class="sec" data-a="conn" data-x="select_mode" data-mode="cdc">CDC(Oracle)</button></div><div class="sub">CDC는 프로필에서 unverified → 성공을 모사하지 않고 DBA 증거 요청이 필요합니다.</div></div>
    <div class="card"><b>연결 테스트</b> 상태 ${badge(c.status, c.status === "OK" ? "ok" : c.status === "FAILED" ? "bad" : "w")}<div class="row"><input id="chost" placeholder="호스트 (실제 URL 시도 시 차단됨)"><input id="cpass" type="password" placeholder="가상 비밀번호만"><button data-a="conntest">테스트</button></div>
    ${c.last_test && !c.last_test.ok ? `<div class="bad">${esc(c.last_test.message)}</div><div class="row">원인 분류: <select id="diagcat">${cats.map(x => `<option>${x}</option>`).join("")}</select><button data-a="conn" data-x="diagnose">진단 제출</button></div>` : ""}</div>
    <div class="card"><b>Foreign catalog</b> <button data-a="conn" data-x="create_foreign_catalog">생성(CREATE FOREIGN CATALOG 필요)</button> ${Object.keys(ST.foreign_catalogs).map(k => badge(k)).join("")}<div class="sub">DB 계정 권한과 UC 권한은 별개입니다. 권한 오류 시 UI-15에서 티켓을 제출하세요.</div></div>`;
  },
  async pipe() {
    const p = ST.pipelines.orders_pipeline;
    return `<h2>UI-09 Pipelines</h2><div class="sub">선언적 데이터셋 정의(SQL Editor DDL과 별도 검증기). 상태 ${badge(p.state, p.state === "SUCCEEDED" ? "ok" : p.state === "FAILED" ? "bad" : "w")} · 대상 ${esc(p.target)} · run_as ${esc(p.run_as)}. 검증 성공 ≠ 실행 성공 ≠ 업무 정합성.</div>
    <div class="card"><textarea id="plsql">${esc(p.source_sql)}</textarea><div class="row"><button data-a="pipeedit">소스 저장</button><button class="sec" data-a="pipe" data-x="validate">Validate</button><button data-a="pipe" data-x="run">Run</button><button class="primary" data-a="pipeall" title="소스 저장 → 검증 → 실행을 순서대로 한 번에">저장 → 검증 → 실행 (한 번에)</button><select id="plas"><option>${esc(p.run_as)}</option><option>trainee@wizbase.training</option><option>svc-runner</option></select><button class="sec" data-a="pipeas">run_as 변경</button></div></div>
    <div class="card"><b>품질 결과 (마지막 실행)</b>${table(["규칙", "컬럼", "조치", "위반"], (p.last_quality || []).map(q => [q.rule, q.col, q.action, q.violations]))}<div class="sub">공식 expectation: 경고(EXPECT, 기본) · DROP ROW · FAIL UPDATE. 이 화면의 block≈FAIL UPDATE, warn≈EXPECT이며, <b>quarantine은 공식 내장 동작이 아니라 WIZBASE 격리 패턴</b>입니다. 실제 파이프라인은 streaming table/materialized view 정의에 CONSTRAINT … EXPECT 절을 사용합니다(이 시뮬레이터는 단순화한 SELECT 정의).</div></div>
    <div class="card"><b>실행 이력</b>${table(["rev", "상태", "사유/결과"], p.history.slice().reverse().map(h => [h.rev, h.state, h.reason || (h.recon ? kvText(h.recon) : "")]))}</div>
    <div class="card"><b>의존 그래프</b><div>bronze.raw_orders → [${esc(p.name)}] → silver.orders_pl → job:orders_job</div></div>`;
  },
  async cdc() {
    const key = LAST.cdc;
    return `<h2>UI-09b CDC 이벤트 재생</h2><div class="banner">교육용 CDC 재생입니다. 실제 Lakeflow 커넥터/AUTO CDC 실행과 별개이며, 이벤트(중복·역순·삭제·재삽입)를 SQL로 멱등하게 적용하는 사고방식을 훈련합니다. 실제 AUTO CDC·SCD 실습은 UI-22의 LAB-DE-05(자동 대조)와 실제 워크스페이스에서 확인하세요.</div>
    <div class="card"><b>이벤트 로그</b><div class="sub">bronze.cdc_events(event_id, customer_id, op, city, seq) · 다음 배치 도착 전/후로 달라집니다. 목표: silver.customers_cdc(customer_id, city) = 각 고객의 <b>seq 최신 상태</b>(삭제 제외).</div>
    <div class="row"><button class="sec" data-a="cdcview">이벤트 보기</button><button class="sec" data-a="c" data-t="cdc.next_batch">다음 배치 도착</button><button data-a="cdccheck">정합성 검사</button></div>
    <textarea id="cdcsql" style="min-height:130px">${esc(LAST.cdcsql || "")}</textarea><div class="row"><button data-a="cdcrun">이 SQL 실행(CREATE OR REPLACE TABLE …)</button></div>
    ${key ? prettyBox(key, true) : ""}${LAST.cdcrows ? table(LAST.cdcrows.columns, LAST.cdcrows.rows, true) : ""}</div>`;
  },
  async jobs() {
    const j = ST.jobs.orders_job;
    return `<h2>UI-10 Jobs</h2><div class="sub">소유자 ${esc(j.owner)} · <b>run-as ${esc(j.run_as)}</b> · 재시도 ${j.retries} · 스케줄 ${esc(j.schedule || "없음")} (${esc(j.timezone)}). 편집자의 조회 성공과 실행자의 실패는 다를 수 있습니다.</div>
    <div class="card">${j.tasks.map(t => `<div><b>${t.task_key}</b> 의존: ${t.depends_on.join(",") || "-"}<textarea id="jt_${t.task_key}" style="min-height:44px">${esc(t.sql)}</textarea><button class="sec" data-a="jobtask" data-k="${t.task_key}">저장</button></div>`).join("")}
    <div class="row"><select id="jobas"><option>${esc(j.run_as)}</option><option>trainee@wizbase.training</option><option>svc-runner</option></select><button class="sec" data-a="jobas">run-as 변경</button><button data-a="job" data-x="run">실행</button><button class="sec" data-a="job" data-x="compare_identity">편집자 vs run-as 비교</button><button class="sec" data-a="c" data-t="job" data-p='{"action":"set_retries","retries":2}'>재시도 2회</button></div></div>
    <h3>실행 이력</h3>${j.runs.slice().reverse().map(r => `<div class="card">${r.run_id} ${badge(r.status, r.status === "succeeded" ? "ok" : "bad")} run_as ${esc(r.run_as)} 트리거 ${esc(r.triggered_by)}${table(["task", "상태", "시도", "원인"], Object.entries(r.tasks).map(([k, v]) => [k, v.status, v.attempts || "-", v.reason || (v.error ? v.error.code + ": " + v.error.message : "")]))}</div>`).join("")}${LAST.cmpid ? "" : ""}`;
  },
  async genie() {
    const g = ST.genie, o = ST.ontology;
    return `<h2>UI-11 의미모델 · Genie</h2><div class="banner">결정적 질의 템플릿 + 로컬 SQL 결과로 재현합니다. 실제 Genie(Agents/과거 Spaces)의 모델 품질·추론·응답을 재현하지 않습니다. 템플릿 밖 질문은 범위 밖으로 표시됩니다.</div>
    <div class="card"><b>온톨로지 → 반영 계층 매핑</b><div class="sub">${esc(o.note)}</div>${table(["구분", "이름", "반영 위치"], [...o.entities.map(x => ["개체", x.name, x.maps_to]), ...o.relations.map(x => ["관계", x.name, x.maps_to]), ...o.metrics.map(x => ["지표", x.name, x.maps_to]), ...o.policies.map(x => ["정책", x.name, x.maps_to])])}</div>
    <div class="card"><b>Genie 설정 — 데이터셋</b><div class="row"><input id="gds" style="width:100%" value="${esc(g.datasets.join(", "))}"><button data-a="geniecfg">저장</button></div><div class="sub">v_available_inventory 를 등록하지 않으면 재고 질문에 답하지 못합니다.</div></div>
    <div class="card"><b>질문</b><div class="row"><input id="gq" style="flex:1" placeholder="예: ${ST.case.product} 가용재고는? / 총 주문 박스는? / 상태별 주문"><select id="gp"><option value="">내 권한</option><option value="analyst-b@wizbase.training">analyst-b (다른 사용자)</option></select><button data-a="genie">질의</button></div>
    ${g.history.slice().reverse().slice(0, 6).map(h => `<div class="card"><b>${esc(h.question)}</b> ${badge(h.status, h.status === "OK" ? "ok" : "bad")} <span class="mute">${esc(h.principal)}</span>${h.sql ? `<pre>${esc(h.sql)}</pre>` : ""}${h.rows ? table(h.columns, h.rows) : ""}${h.error ? `<div class="bad">${esc(h.error.code)}: ${esc(h.error.message)}</div>` : ""}${h.note ? `<div class="warnc">${esc(h.note)}</div>` : ""}</div>`).join("")}</div>`;
  },
  async agent() {
    const f = LAST.facts?.facts, pr = LAST.prop; const props = Object.values(ST.proposals), aps = Object.values(ST.approvals);
    const rule = ST.policy.versions[ST.policy.active];
    return `<h2>UI-12 Agent · 승인</h2><div class="sub">조회 → 정책 → 제안 → 승인 → 가상 AX API → 사후 대조. Genie의 데이터 질의와 주문 변경 실행의 책임은 분리됩니다. 승인은 리뷰어/강사 역할이 별도 로그인에서 수행합니다(요청자·승인자 분리). 가상 API 저장소만 변경됩니다.</div>
    <div class="card"><b>대표 사례 ${ST.case.order} / ${ST.case.product}</b> <span class="mute">(시드 ${ST.case.seed})</span> 요청 총량 <input id="req" type="number" value="${ST.case.requested}" style="width:80px">박스 <button data-a="facts">사실 조회</button> <button data-a="propose">정책 평가·제안</button> <select id="alt"><option value="0">대안 0</option><option value="1">대안 1</option></select> <button class="sec" data-a="contract">계약 정합성 검사</button>
    ${LAST.facts ? `<pre>현재 ${f.current_qty} · 요청 ${f.requested_total} · 가용(gold 뷰) ${f.available_qty}\n추가 부족 = max(max(요청-현재,0)-가용,0) = ${LAST.facts.result?.shortage ?? ""}  (총량-가용=${LAST.facts.wrong_if_total_minus_free}은 오답)\n여신차단 ${f.credit_blocked} · 노선 open ${f.route_open} · 마감후 ${f.after_cutoff} · 예외계약 ${f.exception_contract} · 주문버전 ${f.order_version}</pre>` : ""}
    ${pr ? `<h3>정책 결정: ${badge(pr.policy?.decision, pr.policy?.decision === "REQUIRES_APPROVAL" ? "w" : "bad")}</h3><pre>${esc((pr.policy?.reasons || []).join("\n"))}</pre>${table(["대안", "라벨"], (pr.policy?.alternatives || []).map(a => [a.type, a.label]))}` : ""}</div>
    <div class="card"><b>제안·승인</b>${props.length ? table(["제안", "상태", "payload", ""], props.map(p => [p.proposal_id, p.status, p.payload, p.status === "PENDING" ? `hash <input id="ph_${p.proposal_id}" value="${p.payload_hash}" size="12"> <button data-a="approve" data-id="${p.proposal_id}">승인(리뷰어)</button>` : ""]).map(r => r)) : '<span class="mute">제안 없음</span>'}</div>
    <div class="card"><b>가상 AX API 실행</b><div class="row"><select id="axap">${aps.map(a => `<option>${a.approval_id}</option>`).join("") || "<option></option>"}</select>멱등키 <input id="axk" value="idem-${Math.floor(Math.random() * 9999)}" size="10">expected_version <input id="axv" type="number" value="${f ? f.order_version : 1}" style="width:60px"><button data-a="ax">실행</button></div>
    <div class="sub">payload(수정해 변조를 시험할 수 있음 — 서버가 차단하고 감사 이벤트를 남김)</div><textarea id="axpl">${esc(JSON.stringify((props.filter(p => p.status === "APPROVED").slice(-1)[0] || props.slice(-1)[0] || { payload: {} }).payload, null, 1))}</textarea>${LAST.ax ? prettyBox(LAST.ax, true) : ""}</div>
    <div class="card"><b>정책 (WIZBASE 정책 엔진, Databricks 설정 아님) v${ST.policy.active}</b><textarea id="polyaml">${esc(`rule_id: ${rule.rule_id}\nrequires_approval: ${rule.requires_approval}\nprohibited_if: [${rule.prohibited_if.join(", ")}]\nrevalidate_before_execution: [${rule.revalidate_before_execution.join(", ")}]`)}</textarea><div class="row"><button class="sec" data-a="policydraft">초안 테스트</button><button data-a="policyact">활성화(테스트 통과 시)</button></div>${ST.policy.draft ? table(["케이스", "결정", "통과"], ST.policy.draft.tests.map(t => [t.case, t.decision, t.pass ? "✅" : "❌"])) : ""}</div>`;
  },
  async trace() {
    const a = await api(`/api/sessions/${SID}/audit`); const e = LAST.eval;
    return `<h2>UI-13 Tracing / 평가</h2><div class="sub">WIZBASE 교육용 모사입니다(MLflow 호환 내보내기 미검증). 정답은 정책 결정·데이터 결과로 분리하며 문장 유사도로 통과시키지 않습니다.</div>
    <div class="card"><button data-a="evalrun">평가셋 40건 실행 (정책 v${ST.policy.active})</button> ${e ? badge(`${e.passed}/${e.total} 통과`, e.passed === e.total ? "ok" : "bad") : ""}${e ? table(["ID", "분류", "결정", "부족", "기대", "통과"], e.cases.map(c => [c.id, c.category, c.decision, c.shortage, c.expect + (c.expect_shortage != null ? "/" + c.expect_shortage : ""), c.pass ? "✅" : "❌"])) : ""}${ST.eval_runs.length ? `<div class="mute">이전 실행: ${ST.eval_runs.map(r => `v${r.policy_version}:${r.passed}/${r.total}`).join(", ")}</div>` : ""}</div>
    <div class="card"><b>Trace 타임라인</b>${table(["시각", "trace", "유형", "주체", "결과", "코드해시"], a.slice(-40).reverse().map(x => [x.scenario_clock.slice(11, 19), x.trace_id || "-", x.event_type, x.effective_principal, x.outcome, (x.code_hash || "").slice(0, 8)]))}</div>
    <div class="card"><b>비용(가상)</b> <span class="mute">${esc(ST.cost.components_note)}</span>${pretty({ usage: ST.cost.usage, unit: ST.cost.unit, usage_index: ST.cost.usage_index_units, weights: ST.cost.weights })}
    ${ST.cost.estimate ? `<div class="b ok">환산 ${ST.cost.estimate.amount} ${esc(ST.cost.estimate.currency)}</div> <span class="mute">${esc(ST.cost.estimate.basis)}</span>` : `<div class="warnc">${esc(ST.cost.note || "")}</div>`}
    <div class="row"><input id="cp_price" type="number" step="0.01" placeholder="단가" style="width:90px"><input id="cp_cur" placeholder="통화" value="USD" style="width:70px"><input id="cp_src" placeholder="단가 출처(필수)" style="flex:1"><input id="cp_asof" placeholder="기준일 YYYY-MM-DD(필수)" style="width:150px"><button class="sec" data-a="costprofile">단가 프로필 등록</button></div></div>`;
  },
  async bundle() {
    const b = ST.bundle; const files = Object.keys(b.files); const sel = ls.get("bf") && files.includes(ls.get("bf")) ? ls.get("bf") : files[0];
    return `<h2>UI-14 Git / Bundle / CLI</h2><div class="sub">OS shell이 아닌 명령 파서. 지원: databricks auth login/describe, catalogs/schemas/tables list|get, bundle validate|deploy|run|summary, git status|diff|commit -m|log. 파이프·치환·외부 URL 불가.</div>
    <div class="card">로컬 해시 <code>${b.local_hash.slice(0, 12)}</code> · 배포 해시 <code>${(b.deployed_hash || "없음").slice(0, 12)}</code> ${b.drift ? badge("DRIFT: 로컬≠배포", "bad") : b.deployed_hash ? badge("일치", "ok") : ""} ${b.deploy_review ? badge("deploy review: " + b.deploy_review, b.deploy_review === "PASS" ? "ok" : "w") : ""} CLI 로그인 ${b.cli_logged_in ? "✅" : "❌"}</div>
    <div class="grid2"><div class="card"><b>파일 편집</b><div class="row"><select id="bsel" data-a="bfile">${files.map(f => `<option ${f === sel ? "selected" : ""}>${f}</option>`).join("")}</select><button data-a="bsave">저장(미배포)</button></div><textarea id="bedit" style="min-height:230px">${esc(b.files[sel])}</textarea></div>
    <div class="card"><b>가상 터미널</b><div class="row"><input id="clibox" style="flex:1" value="databricks auth login --host https://training-workspace.invalid"><button data-a="cli">실행</button></div>
    <div class="row">${["databricks auth login --host https://training-workspace.invalid", "databricks bundle validate -t dev", "databricks bundle deploy -t dev", "databricks bundle run -t dev training_job", "databricks bundle summary", "databricks catalogs list", "git status", "git diff", "git commit -m 'edit'"].map(c => `<a href="#" onclick="document.getElementById('clibox').value=this.textContent;return false">${esc(c)}</a>`).join(" · ")}</div>
    ${HIST.cli.slice(0, 8).map(h => `<pre>$ ${esc(h.line)}\n${esc(h.out)}</pre>`).join("")}</div></div>`;
  },
  async perm() {
    const pr = ST.principals;
    return `<h2>UI-15 권한 · 관리</h2><div class="sub">로그인 성공 ≠ 권한. principal/group/entitlement/UC privilege/소유자/run-as를 별도 저장합니다. 권한 해결은 티켓으로 요청하고 관리자 역할이 최소권한으로 처리합니다.</div>
    <div class="card"><b>Principal</b>${table(["principal", "종류", "그룹", "entitlement"], Object.entries(pr).map(([k, v]) => [k, v.kind + (v.admin ? " (admin)" : ""), v.groups.join(","), v.entitlements.join(",")]))}</div>
    <div class="card"><b>UC 권한 (grants)</b>${table(["주체", "권한", "대상"], ST.grants)}</div>
    <div class="card"><b>권한 요청</b><div class="row"><input id="t_sec" value="schema:food_dev.silver" size="26"><input id="t_priv" value="USE SCHEMA" size="14"><input id="t_reason" placeholder="사유(구체적으로)" style="flex:1"><button data-a="ticket">요청 제출</button></div>
    <div class="sub">형식: catalog:이름 | schema:cat.sch | table:cat.sch.tbl | connection:이름. ALL PRIVILEGES 같은 과도한 요청은 반려됩니다.</div></div>
    <div class="card"><b>티켓</b>${ST.tickets.length ? table(["ID", "요청자", "대상", "권한", "상태", "처리"], ST.tickets.map(t => [t.ticket_id, t.grantee, t.securable, t.privilege + (t.over_broad ? " ⚠과도" : ""), t.status, t.status === "OPEN" && ["admin", "instructor"].includes(ME.role) ? `<a href="#" data-a="resolve" data-id="${t.ticket_id}" data-dec="approve">승인</a> | <a href="#" data-a="resolve" data-id="${t.ticket_id}" data-dec="reject">반려</a>` : ""])) : '<span class="mute">없음</span>'}${["admin", "instructor"].includes(ME.role) ? "" : '<div class="sub">승인은 UC 관리자/강사 로그인(다른 브라우저 탭 권장)에서 처리합니다. 강사의 대리 처리는 평가에 기록됩니다.</div>'}</div>`;
  },
  async inst() {
    if (!staff()) return `<h2>UI-16 강사·수료</h2><p class="mute">강사/관리자 전용입니다. 학습자는 UI-01~15와 증거 보고서를 사용하세요. 내 세션 점수:</p>${SID ? await scoreBox(SID) : ""}`;
    const ss = await api("/api/sessions"); const faults = ME.role === "instructor" ? await api("/api/instructor/faults") : {};
    return `<h2>UI-16 강사 · 수료</h2><div class="sub">장애 주입은 시점·영향·해제 조건을 기록합니다. 정답·장애 시드·채점 규칙은 학습자 API에 포함되지 않습니다.</div>
    <div class="card"><b>세션</b>${table(["세션", "소유자", "진행", "rev", "대리처리", ""], ss.map(s => [s.session_id, s.owner, `${s.completed}/${s.lessons}`, s.revision, s.admin_assisted, `<a href="#" data-a="opensess" data-id="${s.session_id}">열기</a>`]))}</div>
    ${SID && ME.role === "instructor" ? `<div class="card"><b>현재 세션 ${SID}</b>
    <div class="row"><select id="fsel">${Object.entries(faults).map(([k, v]) => `<option value="${k}">${k} — ${v}</option>`).join("")}</select><button data-a="fault" data-sid="${SID}">주입</button><button class="sec" data-a="release" data-sid="${SID}">해제</button></div>
    <div class="row"><button class="sec" data-a="pause" data-sid="${SID}" data-p="1">일시정지</button><button class="sec" data-a="pause" data-sid="${SID}" data-p="0">재개</button><button class="sec" data-a="ckpt" data-sid="${SID}">체크포인트</button><button class="sec" data-a="restore" data-sid="${SID}">복원</button><button class="danger" data-a="reset" data-sid="${SID}">초기화</button><button data-a="replay" data-sid="${SID}">결정적 재생 검증</button></div>
    <div class="sub">진행 중 장애: ${esc((ST.faults || []).join(", ") || "없음")} · 대리 처리 ${ST.session.admin_assisted}회 (독립 수행 점수와 구분)</div>
    <div class="row">설명·인수 점수(0-15, 평가자 입력) <input id="exs" type="number" min="0" max="15" style="width:70px"><button data-a="explain" data-sid="${SID}">평가 저장</button></div>
    ${LAST.replay ? prettyBox(LAST.replay, true) : ""}</div>` : ""}${SID ? await scoreBox(SID) : ""}`;
  },
  async evid() {
    const e = await api(`/api/sessions/${SID}/evidence`);
    return `<h2>증거 보고서</h2><div class="banner">${esc(e.report)}</div><div class="card"><pre>모드 ${e.mode} / ${e.learning_mode}\n프로필 ${e.profile.profile_id} (${e.profile.evidence_status}, SA 검토 ${e.profile.sa_reviewed_at || "없음"})\n시드 ${e.seed} · 기준 ${e.scenario_clock_base}\n데이터 digest 초기 ${e.data_digest_initial.slice(0, 16)} → 현재 ${e.data_digest_current.slice(0, 16)}\n정책 버전 ${e.policy_version}\n${e.verification_levels_note}</pre></div>
    <div class="card"><b>점수/통제</b>${pretty(e.score)}</div><div class="card"><b>제한 사항</b><ul>${e.limitations.map(x => `<li>${esc(x)}</li>`).join("")}</ul></div>
    <div class="card"><b>승인 · 가상 API 결과</b>${pretty({ approvals: e.approvals, proposals: e.proposals, ax_actions: e.ax_actions, tickets: e.tickets })}</div>
    <div class="card"><b>SQL 증거(코드 해시)</b>${table(["해시", "결과", "주체", "시각", "수준"], e.sql_evidence.slice(-30).map(s => [(s.code_hash || "").slice(0, 12), s.outcome, s.principal, s.clock.slice(11, 19), s.level]))}</div>
    <div class="card"><b>타임라인</b>${table(["시각", "유형", "주체", "결과", "수준", "trace"], e.timeline.slice(-60).map(t => [t.t.slice(11, 19), t.type, t.principal, t.outcome, t.level, t.trace || ""]))}</div>`;
  },
  /* ---- v1.1 ---- */
  async track() {
    const t = await api(`/api/sessions/${SID}/track`);
    return `<h2>프로젝트 트랙 · 8주 모듈</h2><div class="sub">${esc(t.note)} 전체 ${t.percent}%</div>
    <div class="grid2">${t.modules.map(m => `<div class="card"><b>${m.week} · ${esc(m.module)}</b> <span class="b ${m.percent === 100 ? "ok" : m.percent ? "w" : ""}">${m.percent}%</span><div class="bar2"><i style="width:${m.percent}%"></i></div>
    ${m.steps.map(s => `<div class="rel ${s.status}"><b>${s.no}단계 · ${esc(s.title)}</b><small>${s.status === "done" ? "완료" : s.status === "current" ? "진행 중" : "대기"}</small></div>`).join("")}<div class="mute">${m.done}/${m.total} 항목</div></div>`).join("")}</div>`;
  },
  async demo() {
    const d = await api(`/api/sessions/${SID}/demo`);
    return `<h2>고객·SA 시연 20분</h2><div class="sub">${esc(d.note)} 대표 사례: ${esc(d.case.order)} / ${esc(d.case.product)} (현재 ${d.case.current} → 요청 ${d.case.requested}, 가용 ${d.case.available}, 추가 부족 ${d.case.gap})</div>
    <div class="card"><b>표준 시연 타임테이블 (총 ${d.minutes_total}분)</b>${table(["구간", "분", "내용", "준비", "부족한 증거", ""], d.segments.map(s => [s.no, s.minutes, s.title, s.ready ? "✅" : "⬜", s.missing_evidence.join(", ") || "-", `<a href="#" data-a="nav" data-v="${s.view}">화면 열기</a>`]))}</div>
    <div class="card"><b>예상 질문과 증거 기반 답안</b>${d.qa.map(q => `<div class="card"><b>${esc(q.q)}</b> ${q.demonstrated ? '<span class="b ok">이 세션에서 재현됨</span>' : '<span class="b w">아직 재현하지 않음</span>'}<p>${esc(q.answer)}</p>${q.evidence.length ? `<div class="mute">증거 이벤트: ${q.evidence.join(", ")}</div>` : ""}</div>`).join("")}</div>`;
  },
  async vmx() {
    const [m, f] = await Promise.all([api("/api/verification-matrix"), api("/api/features")]);
    const can = ["reviewer", "instructor"].includes(ME.role);
    return `<h2>UI-26 현장 대조표 (V1~V6)</h2><div class="sub">${esc(m.note)}</div>
    <div class="card"><b>기능 매니페스트 검증 상태</b> <span class="mute">문서 확인 35일 초과 시 STALE(월 1회 정기 대조 기준)</span>${table(["feature", "상태", "유효 상태", "문서 확인일", "경과", "워크스페이스 실측", ""], f.features.map(x => [x.feature_id, x.status, x.status_effective + (x.stale ? " ⚠" : ""), x.doc_checked_at || "-", x.age_days ?? "-", x.workspace_checked_at || "미실측", can ? `<a href="#" data-a="recheck" data-id="${x.feature_id}">문서 재확인 기록</a>` : ""]))}</div>
    <div class="card"><b>대조 현황</b> 일치율 ${m.match_rate ?? "대조 전(주장하지 않음)"} · 대조 완료 ${m.verified_features.length} · <b>미검증 ${m.unverified_features.length}</b> (${esc(m.unverified_features.join(", "))})${m.critical_or_high_mismatches.length ? `<div class="bad">중대 불일치: ${m.critical_or_high_mismatches.join(", ")}</div>` : ""}
    <details><summary>절차 V1~V6</summary><ul>${Object.entries(m.steps).map(([k, v]) => `<li><b>${k}</b> ${esc(v)}</li>`).join("")}</ul></details></div>
    ${can ? `<div class="card"><b>대조 행 추가 (필수 14열)</b><div class="row"><select id="vx_step">${Object.keys(m.steps).map(k => `<option>${k}</option>`).join("")}</select><select id="vx_severity"><option>none</option><option>low</option><option>medium</option><option>high</option><option>critical</option></select></div>
    <div class="row">${m.columns.filter(c => c !== "severity").map(c => `<input id="vx_${c}" placeholder="${c}" style="width:150px">`).join("")}</div><button data-a="matrixadd">행 기록</button></div>` : ""}
    <div class="card"><b>대조표</b>${table(["행", "단계", "기능", "관찰 메뉴", "예상", "실제", "차이", "심각도", "재검증일"], m.rows.map(r => [r.row_id, r.step, r.feature_id, r.observed_menu_path, r.expected, r.actual, r.diff, r.severity, r.recheck_date]))}</div>`;
  },
  async prof() {
    const p = await api("/api/learners/me/profile"); const sk = await api("/api/learners/me/skills");
    return `<h2>UI-17 역량 · 등급 프로필</h2><div class="banner">${esc(p.disclaimer)}</div>
    <div class="card"><b>내 현재 상태 — 서로 다른 6가지는 일부러 따로 표시합니다</b><div class="sub">${esc(p.separation_note)} 하나가 올라가도 다른 것이 자동으로 올라가지 않습니다.</div>${profCards(p)}</div>
    <div class="card"><b>공식 자격 등록(자기 신고 → 확인대기)</b><div class="row"><input id="crn" placeholder="자격명" style="flex:1"><button data-a="credadd">등록</button></div><div class="sub">자기 신고만으로는 유효 상태가 되지 않으며 리뷰어가 발급기관 확인 URL·credential ID로 검증합니다. 계정 비밀번호·시험 토큰은 수집하지 않습니다.</div></div>
    <div class="card"><b>공식 Academy 이수 이력</b> <span class="mute">(확인대기 → 검토자 원본 확인)</span><div class="row"><input id="ac_course" placeholder="과정명" style="flex:1"><input id="ac_date" placeholder="이수일" style="width:120px"><input id="ac_proof" placeholder="증빙 참조(배지 ID 등)" style="width:200px"><button class="sec" data-a="academyadd">등록</button></div>${table(["ID", "과정", "상태"], (await api("/api/learners/me/academy")).map(r => [r.record_id, r.course, r.status]))}</div>
    <div class="card"><b>투입 승인(고객 투입)</b> <span class="mute">내부 등급·공식 자격과 별개, 자동 부여 없음</span>${table(["ID", "역할", "범위", "유효 기한", "상태"], (await api("/api/learners/me/assignments")).map(r => [r.authorization_id, r.role, r.scope, r.valid_until, r.effective ? "유효" : r.status]))}</div>
    <div class="card"><b>내 데이터 (열람·삭제)</b><div class="sub">열람/삭제는 즉시 처리됩니다. 승인된 증거·등급·투입 승인·감사는 보존됩니다. 정책은 법무 검토 전 초안입니다.</div><div class="row"><button class="sec" data-a="privexport">내 데이터 내려받기</button><button class="danger" data-a="privdelete">학습 활동 데이터 삭제</button></div></div>
    <div class="card"><b>objective 차원별 숙련도 (평균으로 합치지 않음)</b>${dimTable(sk.dimensions)}</div>
    <div class="card"><b>응시준비 판정(내부)</b><div class="row"><select id="rdx"><option>DE-A</option><option>DE-P</option><option>GEN-A</option></select><button data-a="readiness">판정 실행</button></div>${LAST.ready ? `<h3>${esc(LAST.ready.exam_id)}: ${badge(LAST.ready.label, LAST.ready.label.includes("충족") ? "ok" : "bad")}</h3>${table(["기준", "충족", "상세"], LAST.ready.criteria.map(c => [c.criterion, c.met ? "✅" : "❌", c.detail]))}<div class="sub">${esc(LAST.ready.note)}</div>` : ""}</div>`;
  },
  async plan() {
    const ex = LAST.plexam || "DE-A"; const profs = await api("/api/exam-profiles"); const pr = profs.find(p => p.exam_id === ex) || profs[0]; const pl = LAST.plan;
    return `<h2>UI-18 목표 · 학습계획</h2><div class="sub">진단 → 계획 → 개념 → 연습 → 실제 실습 → 평가 → 보완 → 지연 확인. 사전 진단 점수(%)를 입력하면 약한 영역부터 배정합니다.</div>
    <div class="card"><div class="row"><select id="plex">${profs.filter(p => p.domains.length).map(p => `<option ${p.exam_id === ex ? "selected" : ""}>${p.exam_id}</option>`).join("")}</select> 주당 시간 <input id="plwh" type="number" value="6" style="width:60px"> 기초(SQL/Python) <input data-dom="foundation_sql_python" type="number" style="width:60px"></div>
    <div class="row">${pr.domains.map(d => `${esc(d.name)} <input data-dom="${d.key}" type="number" style="width:56px">`).join(" · ")}</div><button data-a="plan">계획 생성</button></div>
    ${pl ? `<div class="card"><b>${esc(pl.estimate)}</b> <div class="mute">${esc(pl.note)}</div>${table(["단계", "영역/작업", "진단", "우선", "실제 실습"], pl.steps.map(s => [s.phase.slice(0, 12), s.domain || s.task, s.diagnostic_pct ?? s.reason ?? "", s.priority || "", (s.real_dbx_labs || []).join(",")]))}</div>` : ""}`;
  },
  async map() {
    const profs = await api("/api/exam-profiles"); const ex = LAST.cov || "DE-A"; const c = await api(`/api/exam-profiles/${ex}/coverage`);
    return `<h2>UI-19 공식 목표 지도</h2><div class="banner">내부 objective ID는 공식 코드가 아닙니다. 현재 레코드는 <b>도메인 단위 자리표시</b>이며 공식 가이드의 bullet 단위 전수 적재·검토는 미수행입니다(출시 게이트 차단).</div>
    <div class="row"><select id="covx">${profs.map(p => `<option ${p.exam_id === ex ? "selected" : ""}>${p.exam_id}</option>`).join("")}</select><button data-a="covsel">보기</button></div>
    ${profs.filter(p => p.exam_id === ex).map(p => `<div class="card"><b>${esc(p.title)}</b><div class="sub">가이드 ${esc(p.guide_revision)} · 공식 ${p.official_questions}문항/${p.duration_min}분 · 언어 ${esc(p.language)} · 비중합 ${p.sum_weight}% · 내부 모의 ${p.sum_internal_items}문항 ${p.open_conflicts.length ? badge("미해결 상충 " + p.open_conflicts.join(","), "bad") : ""}</div>${p.sources.map(s => `<a href="${s.url}" target="_blank" rel="noopener">${s.id} ${esc(s.title)}</a>`).join(" · ")}</div>`).join("")}
    <div class="card">출시 게이트 ${badge(c.release_gate_ok ? "통과" : "차단", c.release_gate_ok ? "ok" : "bad")}<ul>${c.blockers.map(b => `<li class="bad">${esc(b)}</li>`).join("")}</ul>상태 집계 ${pretty(c.counts)}
    ${table(["objective(내부)", "요약", "비중", "문항", "실습", "coverage", "상충"], c.objectives.map(o => [o.objective_id_internal, o.objective_summary, o.domain_weight, o.question_ids.length, o.lab_ids.join(","), o.coverage_status, o.conflict_status]))}</div>`;
  },
  async tutor() {
    const t = LAST.tutor;
    return `<h2>UI-20 AI 튜터 · 오개념 노트</h2><div class="sub">승인된 공식 문서·검토 콘텐츠만 검색합니다. 근거가 없거나 충돌하면 '확인 필요'와 이슈를 만듭니다. 봉인 시험 중에는 차단됩니다. 튜터는 실행 권한이 없습니다(검색 문서의 지시를 실행하지 않음).</div>
    <div class="card"><div class="row"><input id="tq" style="flex:1" placeholder="예: USE SCHEMA 권한은 왜 필요한가요? / bundle validate vs deploy / Genie Spaces"><select id="thl"><option value="">힌트 단계 없음</option><option>1</option><option>2</option><option>3</option><option>4</option><option>5</option></select><button data-a="tutor">질문</button></div>
    ${t ? `<div class="card">${badge(t.status, t.status === "ANSWERED" ? "ok" : "w")}<pre>${esc(t.answer)}</pre>${t.hint ? `<div class="warnc">${esc(t.hint)}</div>` : ""}${(t.sources || []).map(s => `<div>근거: <a href="${s.url}" target="_blank" rel="noopener">${esc(s.title)}</a> · 기준일 ${s.basis_date} · 프로필 ${esc(t.profile || "")}</div>`).join("")}${t.alias_note ? `<div class="mute">${esc(t.alias_note)}</div>` : ""}</div>` : ""}</div>`;
  },
  async exam() {
    const profs = await api("/api/exam-profiles"); const a = LAST.att;
    const body = !a ? "" : `<div class="card"><b>${a.exam_id} ${a.kind}</b> ${badge(a.status, a.status === "IN_PROGRESS" ? "w" : "ok")} 남은 시간 ${Math.floor(a.remaining_s / 60)}분 · 서버 시간 기준 · 도움: ${esc(a.profile_lock.assist_tools)} · readiness 증거 ${a.readiness_eligible ? "예" : "아니오(연습/부분 시험지)"}
      ${a.items.map((i, n) => `<div class="card"><b>${n + 1}. [${i.domain}] ${esc(i.stem)}</b> ${i.type === "multi" ? badge(`${i.select_count}개 선택 · ${i.scoring_rule}`, "w") : ""}${i.choices.map(c => `<div><label><input type="${i.type === "multi" ? "checkbox" : "radio"}" name="q_${i.item_id}" value="${c.id}" ${(a.responses[i.item_id]?.answer || []).includes(c.id) ? "checked" : ""}> ${c.id}. ${esc(c.text)}</label>${c.why ? `<div class="mute"> ↳ ${esc(c.why)}</div>` : ""}</div>`).join("")}${a.status === "IN_PROGRESS" ? `<button class="sec" data-a="examans" data-i="${i.item_id}">저장</button>` : `<div>정답: ${(i.correct || ["(봉인: 비공개)"]).join(",")}</div>`}</div>`).join("")}
      ${a.status === "IN_PROGRESS" ? `<button data-a="examsubmit">제출 (제출 후 수정 불가)</button>` : `<h3>결과 ${a.result.correct}/${a.result.total} (${a.result.pct}%)</h3>${pretty(a.result.by_domain)}<div class="sub">${esc(a.result.scoring_rule)}</div>`}<div class="sub">${esc(a.disclaimer)}</div></div>`;
    return `<h2>UI-21 시험센터</h2><div class="banner">모든 현재 문항은 AI 보조 초안(DRAFT)으로 인간 검수 전입니다 → 봉인 시험지는 구성되지 않으며 연습 모드(readiness 증거 제외)만 가능합니다. 숨은 공식 채점 규칙을 재현하지 않습니다.</div>
    <div class="card"><div class="row"><select id="exid">${profs.map(p => `<option ${p.domains.length && p.exam_id !== "DE-P-WEB" ? "" : "disabled"}>${p.exam_id}</option>`).join("")}</select><select id="exk"><option value="practice">연습(해설 제공)</option><option value="sealed">봉인 모의시험(제출 전 정답 비공개)</option></select> 최대 문항 <input id="exmax" type="number" style="width:60px"><button data-a="examstart">시작</button></div><div class="sub">프로필·가이드·언어·시간이 시작 시 고정됩니다. DE-P 웹 프로필은 혼합 금지로 시작할 수 없습니다.</div></div>${body}`;
  },
  async lab() {
    const [cat, ev, req] = await Promise.all([api("/api/labs"), api("/api/lab-evidence"), api("/api/required-labs/" + (LAST.labexam || "DE-A"))]);
    const mine = id => { const x = ev.filter(e => e.lab_id === id && (e.learner === ME.user_id)); const best = x.find(e => e.status === "APPROVED") || x[x.length - 1]; return best ? best.status : "미제출" };
    const ex = LAST.labexam || "DE-A";
    const stTone = s => s === "APPROVED" ? "ok" : (s === "SUBMITTED" ? "w" : (s === "미제출" ? "" : "bad"));
    const evRows = ev.slice().reverse().map(e => [e.evidence_id, e.learner === ME.user_id ? "나" : e.learner, e.lab_id, `<span class="b ${stTone(e.status)}">${esc(e.status)}</span>`,
      e.auto_check ? (e.auto_check.per_task ? Object.entries(e.auto_check.per_task).map(([k, v]) => `${k}:${v}`).join(" ") : e.auto_check.state) : "—", (e.reason || "").slice(0, 110),
      ["reviewer", "instructor"].includes(ME.role) && e.status === "SUBMITTED" ? `<a href="#" data-a="labreview" data-id="${e.evidence_id}" data-dec="approve">원본 확인 후 승인</a>` : ""]);
    return `<h2>UI-22 실제 실습 증거함</h2><div class="sub">실제 교육용 Databricks에서 수행한 실습을 증거로 제출하고 자동 대조·검토를 거칩니다. <b>이 서버는 Databricks 토큰·호스트·비밀번호를 받지 않습니다.</b></div>
    <div class="banner">경로(C-검토형): ① 팩 내려받기 → ② <b>내 PC</b>에서 adapter 실행(내 Databricks CLI 프로필 사용, 지정 스키마 wz_lab_* 안에서만 실행) → ③ 출력된 evidence JSON(체크섬·statement ID만 포함)을 여기에 제출 → ④ 서버가 기대 결과와 자동 대조 → ⑤ 검토자가 Query History에서 statement ID로 원본 확인 후 승인. 스크린샷·자기 신고만으로는 통과되지 않습니다. <br>adapter는 이 환경에서 <b>가짜 Statement API로만 검증</b>되었고 실제 Databricks 워크스페이스 대상 실행은 아직 검증되지 않았습니다(첫 실사용 시 검토자와 함께 확인).</div>
    <div class="card"><b>실습 카탈로그</b> <span class="mute">작성 ${cat.authored} / 지시서 팩 ${cat.total_packs_in_spec}개 — ${esc(cat.status_note)}</span>
    ${table(["실습", "제목", "방식", "시험", "예상", "내 상태", ""], cat.labs.map(l => [l.lab_id, l.title, { machine: "자동 대조(SQL)", cli: "CLI 증거", manual: "수동(검토자 면담)" }[l.kind], l.exam.join(","), l.est_minutes + "분", `<span class="b ${stTone(mine(l.lab_id))}">${esc(mine(l.lab_id))}</span>`, `<a href="#" data-a="labpack" data-id="${l.lab_id}">팩/안내 내려받기</a>`]))}
    <details style="margin-top:10px"><summary>단계별 안내 보기</summary>${cat.labs.map(l => `<h3>${l.lab_id} ${esc(l.title)}</h3><div class="sub">${esc(l.goal)}</div><ol>${l.steps.map(s => `<li>${esc(s)}</li>`).join("")}</ol>${l.required_artifacts.length ? `<div class="sub"><b>필수 산출물(해시 제출):</b> ${l.required_artifacts.map(esc).join(", ")}<br><b>루브릭(합격 ${l.pass_score}점):</b> ${l.rubric.map(r => esc(r.item) + " " + r.max).join(" · ")}</div>` : ""}`).join("")}</details></div>
    <div class="card"><b>내 PC에서 실행 (adapter)</b><pre>python dbx_lab_runner.py run --pack LAB-CORE-01.pack.json --catalog &lt;교육용 catalog&gt; --warehouse-id &lt;SQL warehouse id&gt; \\
    --workspace-ref ws-***1234 --cloud aws --region ap-northeast-2 --profile &lt;CLI 프로필&gt; --cleanup
python dbx_lab_runner.py bundle-evidence --dir &lt;bundle 경로&gt; --workspace-ref ws-***1234 --cloud aws --region ap-northeast-2</pre>
    <div class="sub">필요: Python 3.9+, Databricks CLI ≥ 0.218.0(인증 완료), 교육용 워크스페이스의 SQL warehouse와 쓰기 가능한 catalog. 고객 운영 catalog/실데이터 사용 금지. adapter는 GRANT/ALTER/범위 밖 객체 SQL을 실행 전에 거부합니다. 파일: adapter/dbx_lab_runner.py, adapter/dbx_lab_common.py</div></div>
    <div class="card"><b>증거 제출</b><div class="row">시험 <select id="labx"><option>DE-A</option><option>DE-P</option><option>GEN-A</option></select></div>
    <textarea id="labjson" placeholder="adapter가 만든 evidence JSON 전체를 붙여넣으세요"></textarea><div class="row"><button data-a="labjsonsubmit">제출 · 자동 대조</button></div>
    <details><summary>수동 실습 제출(산출물 해시: <code>python dbx_lab_runner.py hash-artifacts --files ...</code> 출력의 artifacts를 evidence JSON에 포함)</summary><div class="row">${["lab_id:LAB-DE-06", "exam_id:DE-A", "workspace_ref:마스킹 ID", "cloud:aws", "region:ap-northeast-2", "run_id", "source_hash", "result_checksum", "runtime_version", "observed_runtime_version"].map(x => { const [k, p] = x.split(":"); return `<input id="lb_${k}" placeholder="${p || k}" style="width:150px">` }).join("")}<button class="sec" data-a="labsubmit">수동 제출</button></div></details></div>
    <div class="card"><b>증거 목록·자동 대조 결과</b>${table(["ID", "제출자", "실습", "상태", "자동 대조", "사유", "검토"], evRows)}${["reviewer", "instructor"].includes(ME.role) ? `<div class="row"><label><input type="checkbox" id="lbchk"> 원본(Query History statement ID·코드·결과) 확인함</label><input id="rubric" style="flex:1" placeholder='수동 실습 루브릭 점수 JSON 예: {"항목명": 25, ...}'></div>` : ""}</div>
    <div class="card"><b>시험별 필수 실습 현황</b><div class="row"><select id="labex2"><option ${ex === "DE-A" ? "selected" : ""}>DE-A</option><option ${ex === "DE-P" ? "selected" : ""}>DE-P</option><option ${ex === "GEN-A" ? "selected" : ""}>GEN-A</option></select><button class="sec" data-a="labexam">보기</button></div>
    <pre>승인 ${req.approved.length}/${req.required.length}  · 작성됨 ${req.authored.length} · 미작성 ${req.not_authored.length}\n승인: ${req.approved.join(", ") || "-"}\n작성됨(수행 가능): ${req.authored.join(", ") || "-"}\n미작성(콘텐츠 없음 → 준비 판정 차단): ${req.not_authored.join(", ") || "-"}</pre><div class="sub">${esc(req.note)}</div></div>`;
  },
  async qual() {
    if (!staff() || ME.role === "admin") return `<h2>UI-23 콘텐츠 품질관리</h2><p class="mute">리뷰어/강사 전용입니다.</p>`;
    const q = await api("/api/content-quality"); const its = await api("/api/items");
    return `<h2>UI-23 콘텐츠 품질관리</h2><div class="sub">DRAFT→TECH_REVIEWED→ASSESSMENT_REVIEWED→PILOTED→ACTIVE→RETIRED. 기술 검토자와 출제 검토자는 분리됩니다(서로 다른 로그인). 표본이 작으면 난이도 보정 완료를 주장하지 않습니다. 현재 상태 집계: ${pretty(q.bank_size_by_status)}</div>
    <div class="card">${table(["문항", "시험", "영역", "상태", "노출", "n", "정답률", "플래그", "검수"], q.items.map(i => [i.item_id, i.exam, i.domain, i.status, i.exposure, i.n, i.p_correct ?? "-", i.flags.join("; "), `<a href="#" data-a="itemrev" data-id="${i.item_id}" data-s="${{ DRAFT: "tech", TECH_REVIEWED: "assessment", ASSESSMENT_REVIEWED: "pilot", PILOTED: "activate" }[i.status] || ""}">다음 단계</a>`]))}</div>
    <div class="card"><b>회수 이력</b>${pretty(q.recalls)}</div><div class="card"><b>문항 family</b>${pretty(q.families)}</div>`;
  },
  async partner() {
    if (!staff() || ME.role === "admin") return `<h2>UI-24 전문인력 · 파트너 운영</h2><p class="mute">리뷰어/강사 전용입니다.</p>`;
    const p = await api("/api/partner-dashboard");
    return `<h2>UI-24 전문인력 · 파트너 운영</h2><div class="card"><b>회사 파트너 프로그램</b>${pretty(p.company_program)}<div class="sub">${esc(p.note)}</div><a href="${p.kb_url}" target="_blank" rel="noopener">공식 KB: Partner Portal 인증 연결</a></div>
    <div class="card"><b>파일럿 지표 (수집 가능한 항목만)</b>${pretty(await api("/api/pilot-report"))}</div>
    <div class="card"><b>인력 현황</b>${table(["학습자", "내부 등급", "공식 credential", "승인 실습"], p.learners.map(l => [l.learner, l.grades.join(",") || "-", l.official_credentials.join(","), l.labs_approved]))}</div>`;
  },
  async conf() {
    const c = await api("/api/source-conflicts");
    return `<h2>UI-25 공식 자료 충돌 검토</h2><div class="sub">웹/PDF/한국어 차이를 기록합니다. 특정 PDF가 항상 웹페이지보다 우선한다는 규칙은 없으며 검토자가 날짜·유효 버전을 비교해 판정합니다. 해소 전에는 해당 시험의 응시준비 판정이 보류됩니다.</div>
    ${c.conflicts.map(x => `<div class="card"><b>${x.conflict_id} · ${x.exam_id} · ${esc(x.topic)}</b> ${badge(x.status || "OPEN", x.status === "RESOLVED" ? "ok" : "bad")}<div>${esc(x.detail)}</div><div class="mute">처리: ${esc(x.handling)}</div>${x.status === "RESOLVED" ? `<div class="ok">판정: ${esc(x.resolution)} (${esc(x.resolved_by)})</div>` : ["reviewer", "instructor"].includes(ME.role) ? `<div class="row"><input id="cr_${x.conflict_id}" placeholder="판정" style="flex:1"><input id="ce_${x.conflict_id}" placeholder="근거 URL(쉼표)" style="flex:1"><button data-a="confres" data-id="${x.conflict_id}">해소 기록</button></div>` : ""}</div>`).join("")}
    <div class="card"><b>자료</b>${Object.entries(c.sources).map(([k, v]) => `<div>${k} <a href="${v.url}" target="_blank" rel="noopener">${esc(v.title)}</a></div>`).join("")}</div>`;
  }
};
async function scoreBox(sid) {
  const s = await api(`/api/sessions/${sid}/score`);
  return `<div class="card"><b>입문 코어 평가 (20.3)</b> ${badge(s.core_completion ? "수료 기준 충족" : "미충족", s.core_completion ? "ok" : "bad")}${table(["영역", "점수"], Object.entries(s.areas).map(([k, v]) => [k, v ?? "평가자 입력 대기"]))}<b>필수 통과 항목</b>${table(["항목", "통과"], s.safety.map(x => [x.item, x.passed ? "✅" : "❌ (미시도 포함)"]))}<div class="sub">${esc(s.note)} · 힌트 ${s.hints_used} · 대리처리 ${s.admin_assisted} · 초기화 ${s.resets} · 실패/차단 이벤트 ${s.failed_events}</div></div>`;
}
loadChat();
render();
