@echo off
REM WIZBASE DBX Project Rehearsal - 서버 실행 (Windows)
REM 사용: start_server.bat            -> http://127.0.0.1:8830  (이 PC에서만 접속)
REM 접근 코드 파일: 운영자가 따로 전달한 JSON 을 data\.staff_codes.json 으로 복사하거나, 아래처럼 경로 지정
REM   set DBX_CODES_FILE=C:\경로\access_codes.json
cd /d "%~dp0"
if not exist .venv (
  python -m venv .venv || goto :err
  call .venv\Scripts\activate.bat
  python -m pip install -r requirements.txt || goto :err
) else (
  call .venv\Scripts\activate.bat
)
if not exist data mkdir data
echo.
echo  서버 시작: http://127.0.0.1:8830   (종료: Ctrl+C)
echo  로그인 화면에서 역할=admin 선택 후 전달받은 admin 접근 코드를 입력하세요.
echo.
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8830
goto :eof
:err
echo 설치/실행 중 오류가 발생했습니다. Python 3.11+ 설치 여부를 확인하세요.
pause
