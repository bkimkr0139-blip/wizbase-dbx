# WIZBASE DBX Project Rehearsal

WIZBASE(Databricks 파트너)의 Databricks PoC 업무 흐름 연습 및 인증 시험 준비를 지원하는 **합성 데이터 기반 모의 학습 환경**입니다.
Databricks 공식 제품·교육·시험이 아니며 합격을 보장하지 않습니다.

- 서버: Python FastAPI + DuckDB (`backend/`), 화면: 정적 HTML/JS (`static/`), 학습자 PC 실습 어댑터: `adapter/`
- 운영 서비스: https://dbx.wizbase.ai.kr (운영자 PC에서 실행, frp 터널)
- Windows 앱: 단독 설치형(서버 내장, `desktop/dbx_standalone.py`) · 접속형(`desktop/dbx_app.py`) — 설치 파일은 저장소가 아니라 운영 서버 `/download/standalone`, `/download/app`으로 배포
- 버전 규칙: 정식 서비스 전 `0.y.z`. 버그 수정은 버전 유지, 소규모 기능 추가는 z, 주요 개선은 y, 정식 전환(1.0.0)은 운영자 판단 (`backend/sysinfo.py`)

## 빠른 시작 (Windows, Python 3.11+)

```bat
git clone https://github.com/bkimkr0139-blip/wizbase-dbx.git
cd wizbase-dbx
start_server.bat
```
브라우저에서 http://127.0.0.1:8830 접속. 처음 실행 시 가상환경과 패키지를 자동 설치합니다.

## 다른 PC에서 admin 기능 사용하기

admin(수퍼유저)은 피드백·개발큐 관리, 시스템 문서, 전체 세션 관리, 검토·강사 기능을 모두 쓸 수 있습니다.
**접근 코드는 저장소에 없습니다.** 운영자가 별도 파일(`access_codes.json`)로 직접 전달합니다.

1. 위 *빠른 시작*으로 저장소를 받습니다.
2. 전달받은 파일을 `data\.staff_codes.json` 이름으로 복사합니다(또는 `set DBX_CODES_FILE=전체경로\access_codes.json`).
   형식은 `access_codes.example.json` 참고: `{"admin": "...", "staff": "...", "instructor": "..."}` — 세 코드는 서로 달라야 합니다.
3. `start_server.bat` 실행 → 로그인 화면에서 **역할 = admin**, 이름(실명), 접근 코드 입력.
4. 이 방식은 **그 PC의 로컬 서버**를 쓰므로 데이터(세션·피드백)는 그 PC에만 있습니다.
   운영 중인 서비스의 admin 기능(피드백·개발큐)은 어느 PC에서든 https://dbx.wizbase.ai.kr 에 admin 코드로 로그인하면 됩니다. 설치가 필요 없습니다.

접근 코드 파일은 절대 커밋하지 마세요(`.gitignore`가 `data/`, `.staff_codes.json`, `access_codes*.json`을 제외합니다).

## 테스트·빌드

```bat
pip install -r requirements-dev.txt
python -m pytest tests -q
```
Windows 앱 빌드는 `desktop/` 참고. 단독형은 PyInstaller 빌드 시 `tensorflow`, `torch`, `cv2` 등을 `--exclude-module`로 제외하고 `--copy-metadata duckdb`를 지정해야 합니다(`REMAINING.md` 참고).

## 보안 메모
- 접근 코드·토큰·세션 데이터(`data/`)는 저장소에 포함되지 않습니다.
- 서버는 기본적으로 127.0.0.1에만 바인딩합니다. 외부 공개는 별도 터널·리버스 프록시로 하며 HTTPS를 사용하세요.
- 합성 데이터만 사용합니다. 실제 고객 데이터나 개인정보를 입력하지 마세요.
