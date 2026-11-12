"""실제 환경 연결 지원 — 내 교육용(비운영) Databricks 워크스페이스에 SQL을 실제로 실행해 본다.

설계 원칙
- **설치형(단독형) 앱에서만** 켠다. 웹 서버가 사용자 토큰을 맡거나 임의 호스트로 요청을 보내면 자격증명 보관·SSRF 위험이 있어 기본 차단(DBX_REAL_ALLOW=1 로만 예외).
- 자격증명(토큰)은 이 PC 밖으로 나가지 않는다: Windows는 DPAPI로 암호화해 로컬 파일에 저장, 그 외는 600 권한 파일(암호화 안 됨 — 화면에 고지). 화면·로그·감사에는 토큰을 남기지 않는다.
- 접속 대상은 Databricks 공식 도메인(https)만 허용하고, 기본은 **읽기 전용**(SELECT/SHOW/DESCRIBE/EXPLAIN). 쓰기는 사용자가 명시적으로 켠 경우만, 위험 문장(DROP·TRUNCATE·GRANT 등)은 매번 확인을 받는다.
- 운영 환경으로 보이는 이름(prod 등)은 '비운영 확인'을 받아야 연결한다.
"""
from __future__ import annotations
import base64, ctypes, hashlib, json, os, re, sys, time, urllib.error, urllib.request
from ctypes import wintypes
from pathlib import Path

from .core import ApiError

HOST_RE = re.compile(r"^[a-z0-9][a-z0-9.-]*\.(cloud\.databricks\.com|azuredatabricks\.net|gcp\.databricks\.com)$")
PROD_RE = re.compile(r"(^|[^a-z])(prod|prd|production|live)([^a-z]|$)|운영", re.I)
READ_OK = {"SELECT", "WITH", "SHOW", "DESCRIBE", "DESC", "EXPLAIN"}
DESTRUCTIVE = {"DROP", "TRUNCATE", "GRANT", "REVOKE", "DELETE", "MERGE", "ALTER", "OPTIMIZE", "VACUUM"}
ROW_LIMIT = 1000


def enabled() -> bool:
    return os.environ.get("DBX_STANDALONE") == "1" or os.environ.get("DBX_REAL_ALLOW") == "1"


def _dir() -> Path:
    d = Path(os.environ.get("DBX_DATA_DIR", "data")) / "real"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------------------------------------------------------------- 비밀 저장
class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _dpapi(data: bytes, protect: bool) -> bytes:
    inp = _Blob(len(data), ctypes.cast(ctypes.create_string_buffer(data, len(data)), ctypes.POINTER(ctypes.c_char)))
    out = _Blob()
    f = ctypes.windll.crypt32.CryptProtectData if protect else ctypes.windll.crypt32.CryptUnprotectData
    if not f(ctypes.byref(inp), None, None, None, None, 0, ctypes.byref(out)):
        raise OSError("DPAPI 실패")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(out.pbData)


def store_secret(token: str) -> str:
    """토큰을 저장하고 보호 방식 이름을 돌려준다."""
    p = _dir() / "token.bin"
    if sys.platform == "win32":
        p.write_bytes(_dpapi(token.encode("utf-8"), True))
        return "Windows DPAPI(이 PC·이 사용자 계정에서만 복호화)"
    p.write_bytes(base64.b64encode(token.encode("utf-8")))
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass
    return "파일 권한 600(암호화 안 됨)"


def load_secret() -> str | None:
    p = _dir() / "token.bin"
    if not p.exists():
        return None
    raw = p.read_bytes()
    return (_dpapi(raw, False) if sys.platform == "win32" else base64.b64decode(raw)).decode("utf-8")


# ---------------------------------------------------------------- 설정
def _cfg_path() -> Path:
    return _dir() / "config.json"


def _cfg() -> dict | None:
    p = _cfg_path()
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def need_enabled():
    if not enabled():
        raise ApiError(403, "REAL_DISABLED", "실제 환경 연결은 설치형(단독) 앱에서만 사용할 수 있습니다. 웹 서버는 사용자 토큰을 보관하지 않도록 막아 두었습니다.")


def status():
    c = _cfg()
    base = {"enabled": enabled(), "configured": bool(c), "row_limit": ROW_LIMIT}
    if c:
        base.update({k: c.get(k) for k in ("host", "warehouse_id", "catalog", "schema", "write_allowed", "protection", "identity", "last_test", "saved_at")})
    return base


def save_config(b: dict):
    need_enabled()
    host = str(b.get("host", "")).strip().lower().replace("https://", "").rstrip("/")
    token = str(b.get("token", "")).strip()
    wh = str(b.get("warehouse_id", "")).strip()
    if not HOST_RE.match(host) and host not in [h.strip() for h in os.environ.get("DBX_REAL_HOST_ALLOW", "").split(",") if h.strip()]:
        raise ApiError(400, "BAD_HOST", "Databricks 워크스페이스 주소(예: adb-123.4.azuredatabricks.net 또는 xxx.cloud.databricks.com)만 연결할 수 있습니다.")
    if not re.fullmatch(r"[A-Za-z0-9]{8,32}", wh):
        raise ApiError(400, "BAD_WAREHOUSE", "SQL Warehouse ID(영문·숫자 8~32자)를 입력하세요. 워크스페이스의 SQL Warehouses > 연결 정보에 있습니다.")
    if not token and not (_cfg() and load_secret()):
        raise ApiError(400, "TOKEN_REQUIRED", "개인 액세스 토큰(PAT) 또는 서비스 주체 토큰을 입력하세요.")
    names = " ".join(str(b.get(k, "")) for k in ("catalog", "schema")) + " " + host
    if PROD_RE.search(names) and not b.get("confirm_nonprod"):
        raise ApiError(409, "LOOKS_LIKE_PROD", "운영 환경으로 보이는 이름입니다. 교육용·비운영 환경이 맞는다면 '비운영 확인'에 체크하세요.")
    if not b.get("consent"):
        raise ApiError(400, "CONSENT_REQUIRED", "교육용(비운영) 환경이며 고객 데이터·운영 자격증명이 아님에 동의해야 합니다.")
    protection = store_secret(token) if token else (_cfg() or {}).get("protection", "")
    cfg = {"host": host, "warehouse_id": wh, "catalog": str(b.get("catalog", "")).strip()[:64], "schema": str(b.get("schema", "")).strip()[:64], "write_allowed": bool(b.get("write_allowed")),
           "protection": protection, "identity": None, "last_test": None, "saved_at": time.strftime("%Y-%m-%d %H:%M:%S")}
    _cfg_path().write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    return status()


def clear_config():
    need_enabled()
    for n in ("config.json", "token.bin"):
        try:
            (_dir() / n).unlink()
        except OSError:
            pass
    return status()


# ---------------------------------------------------------------- 실행
def _api(host: str, token: str, method: str, path: str, body: dict | None = None, timeout: int = 45) -> dict:
    """Databricks REST 호출(테스트에서 교체한다). 토큰은 헤더로만 보낸다."""
    req = urllib.request.Request(f"https://{host}{path}", method=method, data=json.dumps(body).encode("utf-8") if body is not None else None,
                                 headers={"Authorization": "Bearer " + token, "Content-Type": "application/json", "User-Agent": "wizbase-dbx-rehearsal/real"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = json.loads(e.read().decode("utf-8")).get("message", "")
        except Exception:
            pass
        raise ApiError(502, "REAL_HTTP_" + str(e.code), _http_hint(e.code, detail))
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise ApiError(502, "REAL_UNREACHABLE", f"워크스페이스에 연결하지 못했습니다(주소·네트워크·VPN 확인): {str(getattr(e, 'reason', e))[:80]}")


def _http_hint(code: int, detail: str) -> str:
    base = {401: "토큰이 올바르지 않거나 만료되었습니다. 새 토큰을 발급해 다시 저장하세요.", 403: "이 토큰에 SQL Warehouse 사용(CAN USE) 또는 데이터 접근 권한이 없습니다.", 404: "SQL Warehouse ID 또는 주소가 올바르지 않습니다.", 429: "요청이 너무 많습니다. 잠시 후 다시 시도하세요."}.get(code, "워크스페이스가 오류를 반환했습니다.")
    return f"{base} (HTTP {code}{': ' + detail[:120] if detail else ''})"


def _tokens(sql: str):
    """주석 제거 + 문자열 밖의 ';' 로 문장 분리."""
    s = re.sub(r"--[^\n]*", " ", sql)
    s = re.sub(r"/\*.*?\*/", " ", s, flags=re.S)
    out, cur, q = [], [], None
    for ch in s:
        if q:
            cur.append(ch)
            if ch == q:
                q = None
        elif ch in "'\"`":
            q = ch
            cur.append(ch)
        elif ch == ";":
            out.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
    out.append("".join(cur).strip())
    return [x for x in out if x]


def check_sql(sql: str, write_allowed: bool, confirm: bool):
    st = _tokens(sql or "")
    if len(st) != 1:
        raise ApiError(400, "ONE_STATEMENT", "한 번에 한 문장만 실행할 수 있습니다.")
    kw = re.match(r"\s*([A-Za-z]+)", st[0])
    kw = kw.group(1).upper() if kw else ""
    if kw in READ_OK:
        return kw, False
    if not write_allowed:
        raise ApiError(403, "READ_ONLY", f"{kw or '이 문장'}은(는) 읽기 전용 연결에서 실행할 수 없습니다. 쓰기가 필요하면 연결 설정에서 '쓰기 허용'을 켜세요(교육용 환경에서만).")
    danger = kw in DESTRUCTIVE or bool(re.search(r"\b(DROP|TRUNCATE|GRANT|REVOKE)\b", st[0], re.I))
    if danger and not confirm:
        raise ApiError(409, "CONFIRM_REQUIRED", f"{kw} 문은 되돌릴 수 없거나 권한을 바꿉니다. 실행하려면 확인에 체크하세요.")
    return kw, danger


def _call(sql: str, cfg: dict, token: str, limit: int = ROW_LIMIT) -> dict:
    body = {"warehouse_id": cfg["warehouse_id"], "statement": sql, "wait_timeout": "30s", "on_wait_timeout": "CANCEL", "row_limit": limit, "disposition": "INLINE", "format": "JSON_ARRAY"}
    if cfg.get("catalog"):
        body["catalog"] = cfg["catalog"]
    if cfg.get("schema"):
        body["schema"] = cfg["schema"]
    r = _api(cfg["host"], token, "POST", "/api/2.0/sql/statements", body)
    stt = (r.get("status") or {})
    if stt.get("state") != "SUCCEEDED":
        err = stt.get("error") or {}
        raise ApiError(400, "REAL_SQL_" + str(err.get("error_code", stt.get("state", "FAILED"))), str(err.get("message", "실행에 실패했습니다."))[:400])
    cols = [c["name"] for c in ((r.get("manifest") or {}).get("schema") or {}).get("columns", [])]
    rows = (r.get("result") or {}).get("data_array") or []
    total = (r.get("manifest") or {}).get("total_row_count")
    return {"columns": cols, "rows": rows[:limit], "truncated": bool(total and total > len(rows)) or (len(rows) >= limit), "statement_id": r.get("statement_id")}


def test():
    need_enabled()
    cfg = _cfg()
    tok = load_secret() if cfg else None
    if not cfg or not tok:
        raise ApiError(400, "NOT_CONFIGURED", "먼저 연결 정보를 저장하세요.")
    t0 = time.time()
    r = _call("SELECT current_user() AS user, current_catalog() AS catalog, current_schema() AS schema", cfg, tok, 1)
    row = r["rows"][0] if r["rows"] else []
    cfg["identity"] = {"user": row[0] if row else "?", "catalog": row[1] if len(row) > 1 else "", "schema": row[2] if len(row) > 2 else ""}
    cfg["last_test"] = time.strftime("%Y-%m-%d %H:%M:%S") + f" · {int((time.time() - t0) * 1000)}ms · 성공"
    _cfg_path().write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    return status()


def run_sql(sql: str, confirm: bool = False):
    need_enabled()
    cfg = _cfg()
    tok = load_secret() if cfg else None
    if not cfg or not tok:
        raise ApiError(400, "NOT_CONFIGURED", "먼저 연결 정보를 저장하세요.")
    kw, danger = check_sql(sql, bool(cfg.get("write_allowed")), confirm)
    t0 = time.time()
    h = hashlib.sha256(sql.encode("utf-8")).hexdigest()
    try:
        r = _call(sql, cfg, tok)
        ok = True
    finally:
        with open(_dir() / "audit.jsonl", "a", encoding="utf-8") as f:   # 토큰·결과 데이터는 남기지 않는다
            f.write(json.dumps({"t": int(time.time()), "kw": kw, "sql_sha256": h, "sql_head": sql.strip()[:80], "danger": danger}, ensure_ascii=False) + "\n")
    canon = json.dumps({"columns": r["columns"], "rows": r["rows"]}, ensure_ascii=False, sort_keys=True, default=str)
    return {**r, "keyword": kw, "ms": int((time.time() - t0) * 1000), "result_sha256": hashlib.sha256(canon.encode("utf-8")).hexdigest(), "sql_sha256": h,
            "evidence_level": "REAL_WORKSPACE_EXECUTED", "note": "실제 워크스페이스에서 실행된 결과입니다. 결과 해시는 실습 증거함 제출에 사용할 수 있습니다.", "ok": ok}
