"""테스트가 운영 data/ 를 건드리지 않도록, backend 를 임포트하기 전에 임시 데이터 폴더와 시험용 코드를 고정한다.
(테스트 파일 임포트 순서에 따라 core.DATA 가 운영 폴더로 잡히는 문제를 막는다.)"""
import os
import tempfile

os.environ.setdefault("DBX_DATA_DIR", tempfile.mkdtemp(prefix="dbxtest_"))
os.environ.setdefault("DBX_INSTRUCTOR_CODE", "I-test-code")
os.environ.setdefault("DBX_STAFF_CODE", "S-test-code")
os.environ.setdefault("DBX_ADMIN_CODE", "A-test-code")
os.environ.setdefault("DBX_LOGIN_LIMIT", "100000")
os.environ.setdefault("DBX_MAX_SESSIONS", "100000")
