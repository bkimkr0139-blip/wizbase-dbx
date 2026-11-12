# 구현 현황과 남은 항목 (2026-11-12)

테스트: pytest 84 passed · 전 여정 E2E 47/47 · 20명 동시 p95(메타 0.10s, SQL 0.13s) · 보안 프로브 통과.

## 이번 라운드에서 구현 완료
| 항목 | 내용 |
|---|---|
| 공식 목표 bullet 적재 | 공식 가이드 PDF 3종에서 추출: DE-A 33 · DE-P 45 · GEN-A 56 = **134개**(원문 sha256 + WIZBASE 요약, 영역 비중 일치 검증) |
| 문항은행 | 66문항(22개 영역 모두 ≥3, 선택지 결정적 셔플로 정답 위치 편향 제거, 전부 bullet에 연결) — **전부 AI 초안(DRAFT)** |
| 실습 팩 21/21 | 자동 대조(SQL) 4: CORE-01·DE-02·DE-03·DE-05 / CLI 1: DE-12 / 수동(산출물 해시+루브릭 70점+검토자) 16 |
| 실습 증거 경로 | adapter(학습자 PC) · 서버 자동 대조 · 재사용/구버전/변조 거부 · `hash-artifacts` |
| SQL 엔진 | UPDATE/DELETE/MERGE 지원(MODIFY 권한, 실제 엔진 의미 오류 그대로 반환) |
| CDC 재생 | 중복·역순·삭제·재삽입·seq 누락 + 새 배치 재적용(교육용, 실제 커넥터와 별개) |
| Git 훈련 | branch·checkout·merge(충돌 표시)·PR·배포 소스 커밋 |
| 시드 변형 | v1/v2/v3(다른 숫자·거래처·상품, 안내·정답·장애 주입이 시드 값으로 치환) |
| 프로젝트 트랙 | 8주 훈련 모듈 · 고객 시연 20분(증거 기반 Q&A 6개) |
| 현장 대조표 | V1~V6 14열 기록, 기능 STALE(35일), 일치율은 실제 대조 행만 분모 |
| 거버넌스 | 투입 승인(내부 등급 근거·본인 승인 금지·만료) · Academy 이력(확인대기) · 개인정보 열람/삭제/보존 정책 초안 |
| 운영 | 단가 프로필(출처·기준일 필수) 비용 환산 · 파일럿 지표 보고 |

## 2026-11-12 추가 라운드
- **전이 산업 시드 구현(5번 해소)**: 제조 IoT·클릭스트림·문서 RAG 합성 CSV(`/api/transfer-seeds`, 결정적·sha256), 심어 둔 문제의 정답표는 직원 전용. 테스트에서 정답표가 실제 데이터와 일치함을 검증.
- **협업 훈련 구현(7번 해소)**: 4역할(DBA·DE·AX·리뷰어) 전용 흐름 `/api/collab/*` — 선행 산출물 없이 진행 불가, 인계 메모·산출물 해시 필수, 본인 승인 금지, 반려 사유 필수, 서로 다른 4명이어야 완료.
- **인증서(9번 해소)**: dbx.wizbase.ai.kr nginx 사이트+Let's Encrypt 적용(만료 2027-02-09), dbx 전용 frpc 재기동.
- 아직 화면(UI)은 없음 — 위 두 기능은 API만 제공.

## 2026-11-12 추가 라운드 2 (v0.2.0)
- **리본 전역 메뉴**: 상단 탭형 리본(홈·워크스페이스·데이터 구축·훈련·시연·인증 준비·검토·운영), 오른쪽 끝에 시스템 정보(버전)·업데이트·시스템문서.md 다운로드. 좌측 메뉴 제거.
- **검토 센터(rvw)** + 검토자 매뉴얼.md: 컨설턴트가 실제 워크스페이스에서 직접 대조 후 원문 대조·문항 검수·기능 재확인 기록. 실제 대조 자체는 컨설턴트 수행 필요(기록 전까지 WORKSPACE_CHECKED 0).
- **한국어 가이드 적재(6번)**: DE-A 33개 영문과 구조 일치(해시 연결), DE-P 54개(웹 프로필 계열, 이전 버전), GEN-A 45개(이전 버전). 화면: 인증 준비 > 한국어 가이드.
- **파트너 표기(8번)**: 'Databricks 파트너의 실제 PoC 준비·레벨 상향 인증 시험 준비 지원 환경'으로 상단 배너·면책·파트너 화면 갱신(공식 제품 아님 유지). Portal 원본·tier 확인은 회사가 수행.
- **9번**: AI_Department.key로 서버 점검 완료(nginx 정상, 인증서 89일, certbot.timer 활성).
- 화면 렌더는 DOM 스텁+실서버로 검증(Chrome 확장 미연결, 실제 브라우저 시각 확인은 여전히 미수행).

## 소프트웨어만으로는 끝낼 수 없는 항목 (미완료, 숨기지 않음)
1. **실제 Databricks 워크스페이스 실행/대조**: adapter·실습 팩은 가짜 Statement API로만 검증. WORKSPACE_CHECKED·SA_REVIEWED·DBX_VERIFIED 0건. → 교육용 워크스페이스 필요(첫 실행을 검토자와 함께).
2. **인간 검수**: objective 134개 원문 대조 검토 0건, 문항 ACTIVE 0건(기술·출제 검토자 분리 필요), objective당 3문항 목표 대비 **76개 objective가 문항 0개**, 봉인 시험 3회·통계·한영 이중 검토 불가.
3. **파일럿**: 12명 이상 사전-사후-지연 평가 미수행(지표 수집 도구만 있음).
4. **Python 격리 실행기** 미구성(AT-16 일부는 '차단' 방식으로만 충족). PySpark/Delta 실제 실행은 adapter 경로에만 의존.
5. ~~전이 산업 시드~~ 완료(위 참조).
6. **한국어 가이드(S05)** 및 DE-P 웹 프로필의 bullet은 미적재. SC-07(가이드의 DENY 표현 vs UC 문서) 확인 대기.
7. ~~협업 훈련~~ 완료(API, UI 없음).
8. **비공개 Partner Academy/Portal·한국 지사 확인**, 법무·개인정보 정책 검토 미수행.
9. ~~외부 URL 인증서~~ 완료.
10. **브라우저 화면 확인**: Chrome 확장 미연결로 렌더링 직접 확인 못 함(JS 문법·스텁 렌더 검사만).

## 라운드 3 (v0.3.0)
- 리본 → Windows 표준 메뉴 바(드롭다운). 핫키: F10, Alt+1~7, ↑↓←→/숫자/Enter/Esc, F1, Alt+Shift+A/U/I/K/D. 시스템 정보·업데이트·시스템문서.md·앱 다운로드는 `도움말` 메뉴.
- PC 앱: `desktop/dbx_app.py`(pywebview/WebView2) → `dist_app/WIZBASE-DBX-Rehearsal.exe`(PyInstaller onefile). 시작 화면에서 `/download/app`으로 다운로드. 앱 UA(`DBXDesktop/버전`)에는 시스템 문서 메뉴 숨김 + 서버 403.
- 업데이트 알림: 5분 주기·창 포커스 시 `/api/system/update-check` → 사이트 빌드 변경 시 "지금 적용/나중에", 앱 신버전은 `sysinfo.SHELL_VERSION` 상승 시 알림.
- **앱 재빌드 절차**: desktop/dbx_app.py `APP_VERSION`과 backend/sysinfo.py `SHELL_VERSION`을 같이 올리고 PyInstaller 재실행(테스트가 두 값 일치를 검사).
- 미해결: exe 코드서명 없음(SmartScreen 경고 가능), 실제 설치 PC·실제 브라우저 시각 확인 미수행.

## 버전 규칙 (v0.4.2부터)
- 정식 서비스 전: 0.y.z. **버그 수정은 버전을 올리지 않음**, 소규모 기능 추가 → z, 주요 개선 → y, 정식 전환은 운영자 판단으로 1.0.0. 현재 0.4.2, 다음 기능 추가는 0.4.3.
- 서버 버전 `backend/sysinfo.py VERSION`, 앱 버전 `SHELL_VERSION` = `desktop/dbx_app.py APP_VERSION`(앱 자체가 바뀔 때만).
- 기존 1.x 표기는 0.x로 재매핑(1.5.0→0.4.2, 1.4.1→0.4.1, 1.4.0→0.4.0, 1.3.0→0.3.0, 1.2.0→0.2.0, 1.1.0→0.1.1, 1.0.0→0.1.0).

## 단독 설치형 (v0.4.3)
- `desktop/dbx_standalone.py` → PyInstaller(`--exclude-module`로 tensorflow/torch/cv2 등 제외 필수, `--copy-metadata duckdb` 필수) → `dist_app/release/WIZBASE-DBX-Standalone.exe`(약 46MB). 빌드 명령은 세션 기록 참고(제외 목록 누락 시 600MB).
- 데이터: `%LOCALAPPDATA%\WIZBASE\DBXRehearsal-Standalone\data`. 서버: 127.0.0.1:18830. 업데이트: 중앙 `/api/app/manifest`의 standalone.sha256 ≠ 내 exe SHA-256 이면 알림.
- 중앙 서버에서 새 단독형을 배포하려면 exe를 다시 빌드해 `dist_app/release`에 덮어쓴 뒤 서버 재시작(없어도 manifest는 즉시 갱신).
- 미검증: 실제 다른 PC 설치, 인터넷 단절 상태의 업데이트 다운로드 UI(코드 경로만 단위 테스트).
