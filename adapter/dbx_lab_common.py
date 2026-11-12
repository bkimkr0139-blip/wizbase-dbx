"""서버와 증거 수집기(adapter)가 공유하는 결과 정규화·체크섬. 외부 의존성 없음(표준 라이브러리만).
Spark/Databricks SQL Statement API는 값을 모두 문자열로 돌려주므로, DuckDB 기대값과 같은 규칙으로 정규화한다."""
import hashlib, json, re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

_NUM = re.compile(r"^-?\d+(\.\d+)?$")


def norm_val(v):
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, (int, float, Decimal)) or (isinstance(v, str) and _NUM.match(v.strip())):
        try:
            d = Decimal(str(v).strip())
        except InvalidOperation:
            return str(v)
        return str(int(d)) if d == d.to_integral_value() else format(d.normalize(), "f")
    s = str(v)
    if s.lower() in ("true", "false"):
        return s.lower()
    return s


def checksum_rows(rows):
    """행 순서와 무관한 체크섬. 반환: (sha256, row_count)."""
    norm = sorted(json.dumps([norm_val(c) for c in r], ensure_ascii=False) for r in rows)
    return hashlib.sha256("\n".join(norm).encode("utf-8")).hexdigest(), len(norm)


def combine(task_checksums):
    return hashlib.sha256(json.dumps(task_checksums, sort_keys=True).encode()).hexdigest()


def pack_hash(setup, tasks, cleanup):
    body = {"setup": setup, "tasks": [{"id": t["id"], "sql": t["sql"], "compare": t.get("compare", True)} for t in tasks], "cleanup": cleanup}
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
