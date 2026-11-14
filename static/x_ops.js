"use strict";
/* x_ops.js: 서버 자원 관리(관리자 전용) — CPU·메모리·SSD/HDD·프로세스 모니터링, 작업 전 판단, 승인형 정리. */
let OPS = { plan: null, res: null, pre: null, timer: null, sel: {} };
const gb = b => (b / 1073741824).toFixed(1) + "GB";
const bar = (p, warn = 85) => `<div style="background:#e5e7eb;border-radius:4px;height:10px;width:160px;display:inline-block;vertical-align:middle"><div style="background:${p >= 92 ? "#dc2626" : p >= warn ? "#d97706" : "#16a34a"};width:${Math.min(p, 100)}%;height:10px;border-radius:4px"></div></div> ${p}%`;
const opsTry = async f => { try { return await f() } catch (e) { OPS.err = e.message; toast(e.message); render(true) } };

function opsLive(s) {
  return `<div class="row"><b>CPU</b> ${bar(s.cpu.percent, 90)} <span class="mute">논리 ${s.cpu.logical}코어(물리 ${s.cpu.physical ?? "-"}) ${s.cpu.mhz ? s.cpu.mhz + "MHz" : ""}</span> ${badge(s.level, s.level === "OK" ? "ok" : "bad")}</div>
  <div class="mute" style="margin:4px 0">코어별: ${s.cpu.per_core.map((p, i) => `<span title="코어 ${i}">${Math.round(p)}</span>`).join(" · ")}</div>
  <div class="row"><b>메모리</b> ${bar(s.memory.percent)} <span class="mute">사용 ${gb(s.memory.used)} / ${gb(s.memory.total)} · 가용 ${gb(s.memory.available)} · 스왑 ${gb(s.memory.swap_used)}/${gb(s.memory.swap_total)}</span></div>
  ${table(["드라이브", "종류", "모델", "파일시스템", "사용", "여유", "전체"], s.disks.map(d => [d.mount, badge(d.kind, d.kind === "SSD" ? "ok" : ""), d.model || "-", d.fs, bar(d.percent, 90), gb(d.free), gb(d.total)]), true)}
  <div class="mute">${s.physical_disks.map(d => `${esc(d.model || d.id)}(${d.kind}${d.bus ? "/" + esc(d.bus) : ""})`).join(" · ")}</div>`;
}
const procRows = rs => rs.map(r => [r.pid, r.name, r.cpu, gb(r.rss), r.role === "other" ? "" : badge(r.role, "ok"), esc(r.cmd || "")]);

Object.assign(V, {
  async ops() {
    const s = await api("/api/ops/resources"), hist = await api("/api/ops/history").catch(() => []);
    OPS.res = s;
    clearInterval(OPS.timer);
    OPS.timer = setInterval(async () => { if (VIEW !== "ops") { clearInterval(OPS.timer); return } try { const l = await api("/api/ops/live"); const el = $("#opslive"); if (el) el.innerHTML = opsLive(l) } catch { } }, 5000);
    const spark = hist.length > 1 ? `<div class="mute">최근 ${hist.length}회 샘플(15초 간격): CPU ${hist.slice(-20).map(h => Math.round(h.cpu)).join(" ")} · 메모리 ${hist.slice(-20).map(h => Math.round(h.mem)).join(" ")}</div>` : "";
    const p = OPS.plan, pre = OPS.pre;
    return `<h2>서버 자원 관리</h2><div class="sub">이 시스템이 돌아가는 서버의 CPU·메모리·SSD/HDD와 실행 중 프로세스를 봅니다(관리자 전용). 무거운 작업 전에 자원을 판단하고, 부족하면 <b>승인한 항목만</b> 정리합니다. 다른 앱의 프로세스·컨테이너는 건드리지 않습니다.</div>
    <div class="card"><b>실시간 자원</b> <span class="mute">5초마다 갱신</span><div id="opslive">${opsLive(s)}</div>${spark}</div>
    <div class="card"><b>프로세스</b> <span class="mute">총 ${s.process_count}개 · ${esc(s.processes_note || "")}</span> <button class="ghost" data-a="opsfresh">프로세스 표 새로 조회(느림)</button>
      <h4>메모리 많이 쓰는 순</h4>${table(["PID", "이름", "CPU%(전체 대비)", "메모리", "구분", "명령(비밀 가림)"], procRows(s.top_memory), true)}
      <h4>CPU 많이 쓰는 순</h4>${table(["PID", "이름", "CPU%(전체 대비)", "메모리", "구분", "명령(비밀 가림)"], procRows(s.top_cpu), true)}
      <h4>이 시스템 관련 프로세스</h4>${table(["PID", "이름", "CPU%(전체 대비)", "메모리", "구분", "명령(비밀 가림)"], procRows(s.app_processes), true)}
      <h4>이름별 합계</h4>${table(["이름", "개수", "CPU%(전체 대비)", "메모리"], s.by_name.map(g => [g.name, g.count, g.cpu, gb(g.rss)]), true)}
      <div class="sub">이 서버: PID ${s.app.pid} · 메모리 ${gb(s.app.rss)} · 스레드 ${s.app.threads} · 데이터 폴더 ${gb(s.app.data_size)}(AX ${gb(s.app.ax_size)}) · 가동 ${Math.round(s.app.uptime_s / 60)}분</div></div>
    <div class="card"><b>작업 전 자원 판단</b><div class="vfilters"><label>작업 <select id="opstask">${["auto_build", "ax_scan", "pipeline", "embedding", "embedding_neural", "full_tests", "real_db_tests"].map(t => `<option>${t}</option>`).join("")}</select></label><button data-a="opspre">판단</button></div>
      ${pre ? `<div>${badge(pre.verdict, pre.verdict === "OK" ? "ok" : "bad")} ${esc(pre.label)} — ${pre.reasons.map(r => esc(r.msg)).join(" / ")}<div class="mute">측정: 가용 ${pre.measured.mem_available_gb}GB · 메모리 ${pre.measured.mem_percent}% · CPU ${pre.measured.cpu_percent}% · 디스크 여유 ${pre.measured.disk_free_gb}GB · 기준: 가용 ${pre.thresholds.mem_gb}GB/CPU ${pre.thresholds.cpu_max}%/디스크 ${pre.thresholds.disk_gb}GB (경험적 기준)</div>${pre.suggestions.map(x => `<div>→ ${esc(x)}</div>`).join("")}</div>` : '<div class="mute">작업을 고르고 판단을 눌러 보세요. 자동 구축은 BLOCK이면 시작되지 않습니다.</div>'}</div>
    <div class="card"><b>자원 정리(승인형)</b> <button data-a="opsplan">정리 후보 찾기</button>
      ${p ? `<div class="sub">계획 ${esc(p.plan_id)} · 10분 안에 승인해야 합니다 · 확보 가능 약 ${gb(p.reclaim_bytes)}</div>
        ${table(["선택", "항목", "크기", "위험", "이유"], Object.values(p.candidates).map(c => [`<input type="checkbox" data-a="opssel" data-id="${esc(c.id)}" ${OPS.sel[c.id] ? "checked" : ""}>`, esc(c.label), gb(c.bytes), c.risk, esc(c.why)]), true)}
        <div class="sub">건드리지 않는 것: ${p.never_touched.map(esc).join(" · ")}</div>
        <div class="vfilters"><label>확인 문구 <input id="opsconf" placeholder="${esc(p.confirm_phrase)}" style="width:160px"></label><button data-a="opsexec">선택 항목 승인·정리</button></div>` : '<div class="mute">자원이 부족하면 후보를 찾아 항목별로 승인 후 정리합니다. 승인 없이는 아무것도 지우거나 종료하지 않습니다.</div>'}
      ${OPS.out ? `<div class="card"><b>정리 결과</b> 성공 ${OPS.out.ok} · 실패 ${OPS.out.failed} · 확보 ${gb(OPS.out.freed_bytes)}${table(["항목", "결과", "메시지"], OPS.out.results.map(r => [r.id, r.ok ? badge("성공", "ok") : badge("실패", "bad"), esc(r.msg || "")]), true)}</div>` : ""}</div>`;
  }
});

Object.assign(H, {
  opsfresh() { opsTry(async () => { OPS.res = await api("/api/ops/resources?fresh=true"); render(true) }) },
  opspre() { opsTry(async () => { OPS.pre = await api("/api/ops/preflight/" + val("opstask")); render(true) }) },
  opsplan() { opsTry(async () => { OPS.plan = await api("/api/ops/cleanup/plan", { body: {} }); OPS.sel = {}; OPS.out = null; render(true) }) },
  opssel(d, el) { OPS.sel[d.id] = !OPS.sel[d.id] },
  opsexec() { opsTry(async () => { const ids = Object.keys(OPS.sel).filter(k => OPS.sel[k]); OPS.out = await api("/api/ops/cleanup/execute", { body: { plan_id: OPS.plan.plan_id, ids, confirm: val("opsconf") || "" } }); OPS.plan = null; render(true) }) },
});
