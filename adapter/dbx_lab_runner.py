#!/usr/bin/env python3
"""WIZBASE 실제 DBX 실습 증거 수집기 (학습자 PC에서 실행).

- 본인 교육용 워크스페이스에서 실습 SQL 팩을 실행하고 결과 '체크섬'만 evidence JSON으로 만든다.
- Databricks 자격증명(토큰·호스트·비밀번호)은 이 PC의 Databricks CLI 프로필만 사용한다. 시뮬레이터 서버로 전송하거나 evidence에 저장하지 않는다.
- 실행 범위: 팩이 지정한 스키마(wz_lab_*) 안의 객체만. 그 밖의 객체를 건드리는 SQL은 실행 전에 거부한다.
- 표준 라이브러리만 사용. 모든 외부 호출은 `databricks` CLI를 인자 리스트로 호출(shell 미사용).

사용:
  python dbx_lab_runner.py run --pack LAB-CORE-01.pack.json --catalog <교육용 catalog> --warehouse-id <id> \
        --workspace-ref <마스킹 ID 예: ws-***1234> --cloud aws --region ap-northeast-2 [--profile P] [--cleanup] [--out evidence.json] --attempt-id <UI-22에서 발급한 시도 ID>
  python dbx_lab_runner.py doctor --catalog <교육용 catalog> --warehouse-id <id> [--profile P]   # 첫 실행 전 사전 점검(권장)
  python dbx_lab_runner.py bundle-evidence --dir <bundle 경로> --workspace-ref ... --cloud ... --region ... [--profile P]
  (선택) --submit https://dbx.wizbase.ai.kr --sim-token <시뮬레이터 로그인 토큰>   # Databricks 토큰이 아님
"""
from __future__ import annotations
import argparse, datetime, hashlib, json, os, re, subprocess, sys, time, urllib.request, uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dbx_lab_common as common  # noqa: E402

ADAPTER_VERSION = "1.1"
ALLOWED_VERBS = re.compile(r"^\s*(CREATE SCHEMA IF NOT EXISTS|CREATE OR REPLACE TABLE|INSERT INTO|SELECT|WITH|MERGE INTO|SHOW TABLES IN|DESCRIBE HISTORY|DROP SCHEMA IF EXISTS)\b", re.I)
FORBIDDEN = re.compile(r"\b(GRANT|REVOKE|ALTER|COPY\s+INTO|DROP\s+CATALOG|DROP\s+TABLE|TRUNCATE|VOLUME|CREATE\s+CATALOG|CREATE\s+EXTERNAL|LOCATION|SET\s+TAG)\b", re.I)
THREE_PART = re.compile(r"(?<![\w.`])`?([A-Za-z_][\w-]*)`?\.`?([A-Za-z_][\w-]*)`?\.`?([A-Za-z_][\w-]*)`?(?![\w(])")
DENY_CATALOGS = {"system", "samples", "hive_metastore"}


class SafetyError(Exception):
    pass


def check_sql_safe(sql: str, catalog: str, schema: str):
    """실행 전 정적 검사. 팩 SQL이 변조되었거나 잘못 채워져도 범위를 벗어나지 못하게 한다."""
    if not schema.startswith("wz_lab_"):
        raise SafetyError(f"스키마 이름은 wz_lab_ 로 시작해야 합니다: {schema}")
    if catalog.lower() in DENY_CATALOGS:
        raise SafetyError(f"허용되지 않는 catalog: {catalog}")
    s = sql.strip().rstrip(";")
    if ";" in s:
        raise SafetyError("한 번에 하나의 SQL만 허용")
    if not ALLOWED_VERBS.match(s):
        raise SafetyError("허용되지 않는 구문: " + s[:40])
    if FORBIDDEN.search(s):
        raise SafetyError("금지 키워드 포함: " + s[:60])
    S = f"{catalog}.{schema}"
    for m in THREE_PART.finditer(s):
        if (m.group(1), m.group(2)) != (catalog, schema):
            raise SafetyError(f"범위 밖 객체 참조: {m.group(0)}")
    if re.match(r"^\s*(CREATE SCHEMA|DROP SCHEMA)", s, re.I) and S not in s:
        raise SafetyError("스키마 DDL은 지정된 스키마만 대상으로 해야 합니다")
    return s


class CliRunner:
    """`databricks api` 호출. 자격증명은 CLI 프로필이 처리한다."""
    def __init__(self, profile=None, timeout=120):
        self.profile, self.timeout = profile, timeout

    def call(self, method, path, body=None):
        cmd = ["databricks", "api", method.lower(), path]
        if body is not None:
            cmd += ["--json", json.dumps(body)]
        if self.profile:
            cmd += ["--profile", self.profile]
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=self.timeout)
        if p.returncode != 0:
            raise RuntimeError("databricks CLI 오류: " + (p.stderr or p.stdout)[:300])
        return json.loads(p.stdout or "{}")


def run_statement(runner, warehouse_id, sql, max_wait=120):
    r = runner.call("post", "/api/2.0/sql/statements", {"warehouse_id": warehouse_id, "statement": sql, "wait_timeout": "30s", "on_wait_timeout": "CONTINUE", "disposition": "INLINE", "format": "JSON_ARRAY"})
    sid = r.get("statement_id")
    t0 = time.time()
    while r.get("status", {}).get("state") in ("PENDING", "RUNNING"):
        if time.time() - t0 > max_wait:
            raise RuntimeError("statement 대기 시간 초과: " + str(sid))
        time.sleep(2)
        r = runner.call("get", f"/api/2.0/sql/statements/{sid}")
    st = r.get("status", {})
    if st.get("state") != "SUCCEEDED":
        raise RuntimeError(f"SQL 실패({st.get('state')}): {(st.get('error') or {}).get('message', '')[:200]}")
    cols = [c["name"] for c in (r.get("manifest", {}).get("schema", {}).get("columns") or [])]
    rows = (r.get("result") or {}).get("data_array") or []
    return sid, cols, rows


def cli_version():
    try:
        p = subprocess.run(["databricks", "--version"], capture_output=True, text=True, timeout=20)
        m = re.search(r"(\d+\.\d+\.\d+)", p.stdout + p.stderr)
        return m.group(1) if m else "unknown"
    except Exception:
        return "unknown"


def tag_sql(sql, attempt_id):
    """안전검사를 통과한 문장 끝에 시도 표식(블록 주석)을 붙인다. 검토자가 Query History 검색창에서 이 표식으로 원본을 찾는다."""
    if not attempt_id:
        return sql
    if not re.fullmatch(r"wzA-[0-9a-f]{12}", attempt_id):
        raise SafetyError("attempt_id 형식 오류(예: wzA-0123456789ab)")
    return f"{sql} /* {attempt_id} */"


def run_pack(pack, catalog, warehouse_id, runner, cleanup=False, log=print, attempt_id=None):
    if pack.get("kind") != "machine":
        raise SafetyError("SQL 팩이 아닙니다(kind != machine)")
    schema = pack["schema"]
    if common.pack_hash(pack["setup"], pack["tasks"], pack["cleanup"]) != pack["pack_hash"]:
        raise SafetyError("팩 내용이 pack_hash와 다릅니다(변조 또는 손상). 서버에서 다시 내려받으세요.")
    S = f"{catalog}.{schema}"
    sub = lambda q: tag_sql(check_sql_safe(q.replace("{S}", S), catalog, schema), attempt_id)
    sids, results = [], {}
    for q in pack["setup"]:
        sid, _, _ = run_statement(runner, warehouse_id, sub(q)); sids.append(sid); log(f"setup OK {sid}")
    for t in pack["tasks"]:
        sid, cols, rows = run_statement(runner, warehouse_id, sub(t["sql"])); sids.append(sid)
        entry = {"statement_id": sid, "row_count": len(rows)}
        if t.get("compare"):
            entry["checksum"], entry["row_count"] = common.checksum_rows(rows)
        if t.get("observe"):
            entry["observed_head"] = [[str(c)[:40] for c in r] for r in rows[:6]]   # 검토자 참고용(소량)
        results[t["id"]] = entry
        log(f"task {t['id']} OK rows={len(rows)}")
    try:
        sid, _, vrows = run_statement(runner, warehouse_id, "SELECT version()")
        version = str(vrows[0][0]) if vrows else "unknown"
    except Exception:
        version = "unknown"
    if cleanup:
        for q in pack["cleanup"]:
            run_statement(runner, warehouse_id, sub(q)); log("cleanup OK")
    compared = {k: v["checksum"] for k, v in results.items() if "checksum" in v}
    return {"lab_id": pack["lab_id"], "pack_hash": pack["pack_hash"], "source_hash": pack["pack_hash"], "task_results": results, "statement_ids": sids,
            "result_checksum": common.combine(compared), "runtime_version": version, "observed_runtime_version": version, "cli_version": cli_version(), "adapter_version": ADAPTER_VERSION,
            "attempt_id": attempt_id, "run_id": "run-" + uuid.uuid4().hex[:12], "executed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(), "schema_used": schema}


def doctor(catalog, warehouse_id, runner, log=print):
    """첫 실행 전 사전 점검. 토큰·호스트·사용자 이름은 출력하지 않는다. 각 항목은 {name, ok, hint}.
    (주의) 실제 워크스페이스 응답 형식은 이 개발 환경에서 검증하지 못했다 — 실패하면 hint와 함께 검토자에게 알려 달라."""
    checks = []

    def chk(name, fn, hint):
        try:
            detail = fn()
            checks.append({"name": name, "ok": True, "detail": detail or "", "hint": ""})
        except SafetyError as e:
            checks.append({"name": name, "ok": False, "detail": "", "hint": str(e)})
        except Exception as e:  # noqa: BLE001
            checks.append({"name": name, "ok": False, "detail": "", "hint": f"{hint} ({str(e)[:140]})"})
        log(("OK  " if checks[-1]["ok"] else "FAIL") + " " + name + ("" if checks[-1]["ok"] else " — " + checks[-1]["hint"]))

    def _cli():
        v = cli_version()
        t = tuple(int(x) for x in v.split(".")) if re.fullmatch(r"\d+\.\d+\.\d+", v) else None
        if not t or t < (0, 218, 0):
            raise SafetyError(f"Databricks CLI {v} — 0.218.0 이상으로 업데이트하세요(databricks --version).")
        return v

    def _auth():
        runner.call("get", "/api/2.0/preview/scim/v2/Me")
        return "인증됨(사용자 정보는 출력하지 않음)"

    def _wh():
        w = runner.call("get", f"/api/2.0/sql/warehouses/{warehouse_id}")
        st = w.get("state", "?")
        if st not in ("RUNNING", "STARTING", "STOPPED"):
            raise SafetyError(f"warehouse 상태 {st}")
        return "상태 " + str(st) + (" — STOPPED면 첫 SQL에서 기동되어 1~2분 걸릴 수 있음" if st == "STOPPED" else "")

    def _ver():
        _, _, rows = run_statement(runner, warehouse_id, "SELECT version()")
        return str(rows[0][0]) if rows else "unknown"

    def _write():
        schema = "wz_lab_doctor"
        sub = lambda q: check_sql_safe(q.replace("{S}", f"{catalog}.{schema}"), catalog, schema)
        run_statement(runner, warehouse_id, sub("CREATE SCHEMA IF NOT EXISTS {S}"))
        run_statement(runner, warehouse_id, sub("CREATE OR REPLACE TABLE {S}.t (a INT)"))
        run_statement(runner, warehouse_id, sub("DROP SCHEMA IF EXISTS {S} CASCADE"))
        return f"{catalog}.{schema} 생성·삭제 가능"

    chk("Databricks CLI 버전", _cli, "databricks CLI가 설치되어 있지 않거나 PATH에 없습니다")
    chk("CLI 인증(프로필)", _auth, "`databricks auth login`으로 로그인했는지, --profile 이름이 맞는지 확인하세요")
    chk("SQL warehouse 접근", _wh, "warehouse ID가 맞는지, 이 사용자에게 CAN USE 권한이 있는지 확인하세요")
    chk("SELECT version()", _ver, "warehouse가 SQL을 실행하지 못합니다(기동 중이거나 권한 부족)")
    chk("catalog 쓰기(wz_lab_doctor 스키마 생성·삭제)", _write, "이 catalog에 CREATE SCHEMA 권한(USE CATALOG + CREATE SCHEMA)이 있는 교육용 catalog인지 확인하세요")
    return {"adapter_version": ADAPTER_VERSION, "ok": all(c["ok"] for c in checks), "checks": checks,
            "note": "모든 항목이 OK여도 실습 결과가 맞는다는 뜻은 아닙니다. 실습 실행은 `run`으로 하세요."}


def bundle_evidence(dirpath, runner_cmd=None):
    """bundle validate 결과를 해시로만 남긴다(출력 본문에는 host 등이 있을 수 있어 저장하지 않음)."""
    cmd = runner_cmd or ["databricks", "bundle", "validate", "-o", "json"]
    p = subprocess.run(cmd, cwd=dirpath, capture_output=True, text=True, timeout=120)
    yml = os.path.join(dirpath, "databricks.yml")
    return {"cli_version": cli_version(), "validate_exit": p.returncode, "validate_output_sha256": hashlib.sha256((p.stdout or "").encode()).hexdigest(),
            "bundle_file_sha256": hashlib.sha256(open(yml, "rb").read()).hexdigest() if os.path.exists(yml) else None}


def submit(url, sim_token, evidence):
    req = urllib.request.Request(url.rstrip("/") + "/api/lab-evidence", data=json.dumps(evidence).encode(), headers={"Content-Type": "application/json", "Authorization": "Bearer " + sim_token})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


def hash_artifacts(files):
    """수동 실습 산출물의 sha256(파일명→해시). 파일 내용은 서버로 보내지 않는다."""
    out = {}
    for f in files:
        h = hashlib.sha256()
        with open(f, "rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
        out[os.path.basename(f)] = h.hexdigest()
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    ph = sp.add_parser("hash-artifacts"); ph.add_argument("--files", nargs="+", required=True)
    pd_ = sp.add_parser("doctor"); pd_.add_argument("--catalog", required=True); pd_.add_argument("--warehouse-id", required=True); pd_.add_argument("--profile")
    for name in ("run", "bundle-evidence"):
        p = sp.add_parser(name)
        p.add_argument("--workspace-ref", required=True, help="마스킹한 워크스페이스 식별자(예: ws-***1234)")
        p.add_argument("--cloud", required=True); p.add_argument("--region", required=True)
        p.add_argument("--profile"); p.add_argument("--out"); p.add_argument("--submit"); p.add_argument("--sim-token")
        if name == "run":
            p.add_argument("--pack", required=True); p.add_argument("--catalog", required=True); p.add_argument("--warehouse-id", required=True); p.add_argument("--cleanup", action="store_true"); p.add_argument("--attempt-id", help="UI-22에서 발급한 시도 ID(wzA-...). 없으면 서버가 증거를 받지 않습니다")
        else:
            p.add_argument("--dir", required=True); p.add_argument("--lab-id", default="LAB-DE-12"); p.add_argument("--run-id", help="deploy/run 후 Job run ID(검토자 확인용 자기 신고)")
    a = ap.parse_args(argv)
    if a.cmd == "hash-artifacts":
        print(json.dumps({"artifacts": hash_artifacts(a.files)}, indent=1))
        return 0
    if a.cmd == "doctor":
        rep_ = doctor(a.catalog, a.warehouse_id, CliRunner(a.profile))
        print(json.dumps(rep_, ensure_ascii=False, indent=1))
        return 0 if rep_["ok"] else 1
    if a.cmd == "run":
        pack = json.load(open(a.pack, encoding="utf-8"))
        ev = run_pack(pack, a.catalog, a.warehouse_id, CliRunner(a.profile), a.cleanup, attempt_id=a.attempt_id)
        ev.update(exam_id=None)
    else:
        b = bundle_evidence(a.dir)
        ev = {"lab_id": a.lab_id, **b, "run_id": a.run_id or ("run-" + uuid.uuid4().hex[:12]), "source_hash": b["bundle_file_sha256"] or "none", "result_checksum": b["validate_output_sha256"],
              "runtime_version": b["cli_version"], "observed_runtime_version": b["cli_version"], "pack_hash": None, "adapter_version": ADAPTER_VERSION}
    ev.update(workspace_ref=a.workspace_ref, cloud=a.cloud, region=a.region)
    out = a.out or f"{ev['lab_id']}.evidence.json"
    json.dump(ev, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("evidence 저장:", out, "(Databricks 토큰·호스트는 포함되지 않음)")
    if a.submit:
        if not a.sim_token:
            print("--sim-token(시뮬레이터 로그인 토큰) 필요", file=sys.stderr); return 2
        print(json.dumps(submit(a.submit, a.sim_token, ev), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
