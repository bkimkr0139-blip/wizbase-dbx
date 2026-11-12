"use strict";
/* x_vol.js: UC Volumes 화면(UI-08c). 볼륨 만들기·파일 업로드·목록·COPY INTO 예시. 공용 헬퍼는 app.js 전역을 쓴다. */
let VOL = { sel: "", files: null, res: null, name: "", comment: "", path: "", text: "", fname: "" };

// 새 오류 코드의 해결 안내(REMEDY 는 app.js 의 객체라 값을 덧붙이기만 한다)
Object.assign(REMEDY, {
  CATALOG_ALREADY_EXISTS: e => ({ why: "같은 이름의 catalog 가 이미 있습니다.", steps: ["SHOW CATALOGS 로 이름을 확인합니다.", "다른 이름을 쓰거나 IF NOT EXISTS 를 붙여 건너뜁니다."], actions: [SCN("SQL Editor에서 SHOW CATALOGS", "sql", { sqlbox: "SHOW CATALOGS" })] }),
  CATALOG_NOT_FOUND: e => ({ why: "내가 만든 catalog 중에 그 이름이 없습니다.", steps: ["SHOW CATALOGS 로 이름을 확인합니다.", "철자를 고치거나 CREATE CATALOG 로 만듭니다."], actions: [SCN("SQL Editor에서 SHOW CATALOGS", "sql", { sqlbox: "SHOW CATALOGS" })] }),
  CATALOG_NOT_EMPTY: e => ({ why: "catalog 안에 schema/volume 이 남아 있어 그냥 지울 수 없습니다.", steps: ["남은 객체를 먼저 정리하거나 DROP CATALOG 이름 CASCADE 로 함께 삭제합니다(되돌릴 수 없음)."], actions: [] }),
  CATALOG_PROTECTED: e => ({ why: "교육용 기본 catalog 는 삭제할 수 없습니다.", steps: ["연습용 catalog 는 CREATE CATALOG 로 새로 만들어 사용하세요."], actions: [SCN("CREATE CATALOG 예시", "sql", { sqlbox: "CREATE CATALOG IF NOT EXISTS my_course" })] }),
  CATALOG_RESERVED: e => ({ why: "시스템이나 교육 환경이 이미 쓰는 이름입니다.", steps: ["다른 이름(예: my_course)을 고릅니다."], actions: [] }),
  VOLUME_NOT_FOUND: e => ({ why: "volume 을 찾을 수 없습니다. 경로는 /Volumes/catalog/schema/volume/… 형식입니다.", steps: ["Volumes 화면에서 volume 이름을 확인합니다.", "없으면 CREATE VOLUME 으로 만듭니다."], actions: [SCN("Volumes 열기", "vol")] }),
  VOLUME_ALREADY_EXISTS: e => ({ why: "같은 이름의 volume 이 이미 있습니다.", steps: ["다른 이름을 쓰거나 IF NOT EXISTS 를 붙입니다."], actions: [SCN("Volumes 열기", "vol")] }),
  VOLUME_FULL: e => ({ why: "시뮬레이터는 volume 당 파일 30개까지만 보관합니다.", steps: ["필요 없는 파일을 삭제하거나 다른 volume 을 만듭니다."], actions: [SCN("Volumes 열기", "vol")] }),
  FILE_TOO_LARGE: e => ({ why: "시뮬레이터는 파일당 200KB 이하만 받습니다.", steps: ["합성(샘플) 데이터로 줄여서 올립니다."], actions: [] }),
  INVALID_PATH: e => ({ why: "경로 형식이 맞지 않습니다. /Volumes/catalog/schema/volume/폴더/파일.csv 형식이며 '..' 은 쓸 수 없습니다.", steps: ["LIST '/Volumes/…' 로 실제 경로를 확인합니다."], actions: [SCN("Volumes 열기", "vol")] }),
  PATH_NOT_FOUND: e => ({ why: "그 경로에 CSV 파일이 없습니다.", steps: ["LIST '/Volumes/…' 로 파일을 확인합니다.", "파일을 업로드한 volume·폴더 이름이 맞는지 확인합니다."], actions: [SCN("Volumes 열기", "vol")] }),
  UNSUPPORTED_FILEFORMAT: e => ({ why: "시뮬레이터의 COPY INTO 는 CSV 만 지원합니다.", steps: ["FILEFORMAT = CSV 로 바꿉니다."], actions: [] }),
  MALFORMED_CSV: e => ({ why: "파일의 열 수가 테이블과 다릅니다(또는 header 옵션이 맞지 않습니다).", steps: ["FORMAT_OPTIONS ('header'='true') 를 확인합니다.", "파일 안 쉼표가 들어간 값은 큰따옴표로 감쌉니다."], actions: [] }),
  SCHEMA_MISMATCH: e => ({ why: "파일의 열 이름이 테이블과 다릅니다. 시뮬레이터는 스키마 자동 확장을 지원하지 않습니다.", steps: ["파일의 머리글을 테이블 열 이름과 맞춥니다.", "또는 테이블을 새 열로 다시 만듭니다."], actions: [SCN("Catalog에서 열 확인", "cat")] }),
});

Object.assign(V, {
  async vol() {
    const d = await api(`/api/sessions/${SID}/volumes`);
    if (!VOL.sel || !d.volumes.some(v => v.volume === VOL.sel)) VOL.sel = d.volumes[0]?.volume || "";
    VOL.files = VOL.sel ? await api(`/api/sessions/${SID}/volumes/files?volume=${encodeURIComponent(VOL.sel)}`) : null;
    const v = d.volumes.find(x => x.volume === VOL.sel), r = VOL.res;
    const fl = VOL.files, copySql = v ? `COPY INTO ${(v.volume.split(".").slice(0, 2).join("."))}.my_table\nFROM '${v.path}/'\nFILEFORMAT = CSV\nFORMAT_OPTIONS ('header'='true')` : "";
    return `<h2>UI-08c Volumes</h2><div class="sub">Unity Catalog Volume 은 파일(CSV 등)을 올려 두는 저장 공간입니다. 경로는 <code>/Volumes/catalog/schema/volume/…</code> 이며, 올린 파일을 <b>COPY INTO</b> 로 테이블에 적재합니다(같은 파일은 다시 적재하지 않음). ${esc(d.note)} 파일은 ${d.max_file_kb}KB·volume 당 ${d.max_files}개까지, 합성 데이터만 올리세요. ${lv(d.evidence_level)}</div>
    <div class="card"><b>Volume 만들기</b> <span class="mute">(USE SCHEMA + CREATE VOLUME 권한 또는 catalog/schema 소유자)</span>
      <div class="vfilters"><label>이름 <input id="vlname" value="${esc(VOL.name)}" placeholder="catalog.schema.volume" style="width:230px" oninput="VOL.name=this.value" list="vltargets"></label>
      <datalist id="vltargets">${d.create_targets.map(t => `<option value="${esc(t)}.landing"></option>`).join("")}</datalist>
      <label>설명 <input id="vlcm" value="${esc(VOL.comment)}" placeholder="선택" style="width:160px" oninput="VOL.comment=this.value"></label><button data-a="volcreate">만들기</button></div>
      <div class="sub">${d.create_targets.length ? `만들 수 있는 위치: ${d.create_targets.map(t => `<code>${esc(t)}</code>`).join(" ")}` : "지금 CREATE VOLUME 권한이 있는 schema 가 없습니다. Catalog 화면에서 내 catalog 를 만들거나 권한 요청 화면에서 요청하세요."}</div>
      <div class="row">${scBtn(SCN("내 catalog 만들기(SQL 예시)", "sql", { sqlbox: "CREATE CATALOG IF NOT EXISTS my_course;" }))}${scBtn(SCN("권한 요청", "perm"))}</div></div>
    ${r && r.error ? `<div class="card">${remedyHtml(r.error)}</div>` : ""}
    <div class="card"><b>Volumes</b>${d.volumes.length ? table(["volume", "경로", "소유자", "파일", "읽기", "쓰기", "선택", "삭제"], d.volumes.map(x => [x.volume, x.path, x.owner, x.files, x.can_read ? badge("가능", "ok") : badge("불가", "bad"), x.can_write ? badge("가능", "ok") : badge("불가", "bad"), x.volume === VOL.sel ? badge("선택됨", "ok") : `<a href="#" data-a="volsel" data-v="${esc(x.volume)}">선택</a>`, `<a href="#" data-a="voldel" data-v="${esc(x.volume)}">삭제</a>`])) : '<div class="mute">아직 volume 이 없습니다. 위에서 만들어 보세요.</div>'}</div>
    ${v ? `<div class="card"><b>파일 — ${esc(v.volume)}</b> <span class="mute">${esc(v.path)}</span>
      <div class="vfilters"><label>파일 경로 <input id="vlpath" value="${esc(VOL.path)}" placeholder="예: orders/day1.csv" style="width:210px" oninput="VOL.path=this.value"></label><input type="file" accept=".csv,.txt,text/csv,text/plain" onchange="H.volfile(this)"><button data-a="volupload">업로드</button><button class="ghost" data-a="volsample">샘플 CSV 채우기</button></div>
      <textarea id="vltext" oninput="VOL.text=this.value" placeholder="CSV 내용을 붙여 넣거나 파일을 고르세요(첫 줄은 머리글)" style="min-height:90px">${esc(VOL.text)}</textarea>
      ${fl && fl.error ? remedyHtml(fl.error) : (fl && fl.files.length ? table(["파일", "크기(B)", "올린 시각", "삭제"], fl.files.map(f => [f.path, f.size, fmtIso(f.uploaded_at), `<a href="#" data-a="volfdel" data-p="${esc(f.path)}">삭제</a>`])) : '<div class="mute">파일이 없습니다.</div>')}
      <div class="row">${scBtn(SCN("LIST 로 확인", "sql", { sqlbox: `LIST '${v.path}'` }))}${scBtn(SCN("COPY INTO 예시 열기", "sql", { sqlbox: copySql }))}</div>
      <div class="sub">COPY INTO 는 <b>대상 테이블이 먼저 있어야</b> 합니다. 예: <code>CREATE TABLE ${esc(v.volume.split(".").slice(0, 2).join("."))}.my_table (id BIGINT, name VARCHAR, qty BIGINT)</code> → 위 COPY INTO 실행 → 같은 명령을 다시 실행하면 0행(건너뜀). 다시 적재하려면 <code>COPY_OPTIONS ('force'='true')</code>.</div></div>` : ""}`;
  },
});

Object.assign(H, {
  volsel(d) { VOL.sel = d.v; VOL.res = null; render(true) },
  async volcreate() { try { VOL.name = val("vlname") ?? VOL.name; VOL.comment = val("vlcm") ?? VOL.comment; const r = await api(`/api/sessions/${SID}/volumes`, { body: { name: VOL.name, comment: VOL.comment } }); VOL.res = r.status === "succeeded" ? null : r; if (r.status === "succeeded") { VOL.sel = VOL.name.trim().toLowerCase(); log(`volume ${VOL.sel} 생성`) } else { LASTERR = r.error; log("✗ " + r.error.message, true) } await refresh() } catch (e) { toast(e.message) } },
  async voldel(d) { try { const r = await api(`/api/sessions/${SID}/volumes/delete`, { body: { name: d.v } }); VOL.res = r.status === "succeeded" ? null : r; if (r.status !== "succeeded") { LASTERR = r.error; log("✗ " + r.error.message, true) } else log(`volume ${d.v} 삭제`); await refresh() } catch (e) { toast(e.message) } },
  volfile(el) { const f = el.files && el.files[0]; if (!f) return; if (f.size > 200000) { toast("200KB 이하 파일만 올릴 수 있습니다."); return } const fr = new FileReader(); fr.onload = () => { VOL.text = String(fr.result || ""); VOL.fname = f.name; if (!VOL.path) VOL.path = f.name.replace(/[^A-Za-z0-9_.\-]/g, "_"); render(true) }; fr.readAsText(f, "utf-8") },
  volsample() { VOL.text = "id,name,qty\n1,apple,10\n2,banana,20\n3,cherry,30\n"; if (!VOL.path) VOL.path = "sample_orders.csv"; render(true) },
  async volupload() { try { VOL.path = val("vlpath") ?? VOL.path; VOL.text = val("vltext") ?? VOL.text; const r = await api(`/api/sessions/${SID}/volumes/files`, { body: { volume: VOL.sel, path: VOL.path, text: VOL.text } }); VOL.res = r.status === "succeeded" ? null : r; if (r.status === "succeeded") { log(`${r.path} 업로드(${r.size}B)`); } else { LASTERR = r.error; log("✗ " + r.error.message, true) } await refresh() } catch (e) { toast(e.message) } },
  async volfdel(d) { try { const r = await api(`/api/sessions/${SID}/volumes/files/delete`, { body: { volume: VOL.sel, path: d.p } }); VOL.res = r.status === "succeeded" ? null : r; await refresh() } catch (e) { toast(e.message) } },
});
