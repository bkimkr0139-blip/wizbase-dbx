"""테스트가 운영 data/ 를 건드리지 않도록, backend 를 임포트하기 전에 임시 데이터 폴더와 시험용 코드를 고정한다.
(테스트 파일 임포트 순서에 따라 core.DATA 가 운영 폴더로 잡히는 문제를 막는다.)"""
import os
import tempfile

_OWN_TMP = None
if "DBX_DATA_DIR" not in os.environ:
    _OWN_TMP = tempfile.mkdtemp(prefix="dbxtest_")
    os.environ["DBX_DATA_DIR"] = _OWN_TMP
os.environ.setdefault("DBX_INSTRUCTOR_CODE", "I-test-code")
os.environ.setdefault("DBX_STAFF_CODE", "S-test-code")
os.environ.setdefault("DBX_ADMIN_CODE", "A-test-code")
os.environ.setdefault("DBX_LOGIN_LIMIT", "100000")
os.environ.setdefault("DBX_MAX_SESSIONS", "100000")


def pytest_sessionfinish(session, exitstatus):
    """테스트가 만든 임시 데이터 폴더(DuckDB 포함)를 종료 시 지운다 — 실행할 때마다 수백 MB가 쌓이던 문제 방지.
    직접 지정한 DBX_DATA_DIR 은 건드리지 않는다."""
    if not _OWN_TMP:
        return
    import gc, shutil, sys
    core = sys.modules.get("backend.core")
    try:
        if core is not None:
            for c in list(getattr(core, "_conns", {}).values()):
                try:
                    c.close()
                except Exception:
                    pass
            core._conns.clear()
    except Exception:
        pass
    gc.collect()
    shutil.rmtree(_OWN_TMP, ignore_errors=True)
