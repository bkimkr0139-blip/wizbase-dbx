# 전수검사·검수 보고서 — WIZBASE DBX Project Rehearsal (2026-11-11)

검증 방법: ① 공식 문서/웹페이지를 2026-11-11에 직접 열어 대조(WebFetch) ② 가동 중인 서버 대상 전 여정 E2E ③ 자동 테스트 ④ 20명 동시 부하·보안 프로브.
**한계**: 실제 Databricks 워크스페이스에 접속하지 않았고(C 모드·WORKSPACE_CHECKED 없음), 한국 SA 검토 없음, 브라우저 화면 렌더링은 확인 못 함(Chrome 확장 미연결).
따라서 아래 "일치"는 *공개 공식 문서와 일치*를 뜻하며 *실제 워크스페이스 동작과 일치*를 뜻하지 않는다.

## 1. 공식 제품·서비스 대조 (문서 직접 확인)

| # | 항목 | 공식(2026-11-11 확인) | 시스템 | 판정 / 조치 |
|---|---|---|---|---|
| 1 | 테이블 SELECT 권한 | USE CATALOG + USE SCHEMA + SELECT | 동일 + 상위 상속 | 일치 |
| 2 | 뷰/테이블 생성 | `CREATE TABLE` 하나가 테이블·뷰 생성 포괄(별도 CREATE VIEW 없음) | CREATE TABLE로 판정 | 일치 |
| 3 | MODIFY | insert/update/delete 허용 | INSERT에 MODIFY 요구 | 일치 (UPDATE/DELETE는 시뮬레이터 미지원) |
| 4 | Foreign catalog 생성 | connection의 `CREATE FOREIGN CATALOG` **및** metastore의 `CREATE CATALOG` | 연결 권한만 요구 | **불일치→수정**: 두 권한 순차 검사, 가이드·테스트 갱신 |
| 5 | SQL `DENY` | SQL DENY 문 없음(ABAC DENY 정책은 베타) | DENY 구현·채점 보류, 튜터가 '확인 필요' | 일치 (KB-11 추가) |
| 6 | MANAGE 권한 | 소유자 아니어도 권한 관리 가능, ALL PRIVILEGES에 불포함 | GRANT는 관리자만 | **단순화** (MANAGE 미모델) |
| 7 | 뷰 실행 시 소유자 권한 | 해당 페이지 미기재 | 뷰 조회 시 뷰 SELECT만 확인 | **미검증 단순화** |
| 8 | Job run-as | run-as 신원의 UC·컴퓨트 권한으로 실행, 트리거 사용자는 CAN MANAGE RUN 필요 | run-as 기준 실행 ✓ | 핵심 일치 / **단순화**: Job ACL(CAN MANAGE RUN), Service Principal User 권한, 예약 SQL task 예외 미모델 |
| 9 | Bundles 명칭 | **Declarative Automation Bundles**(구 Asset Bundles), CLI ≥ 0.218.0 | 별칭 안내 ✓, 프로필에 최소 버전 기록 | 일치 |
| 10 | `bundle.databricks_cli_version`, target `mode: development/production`, `default: true` | 문서에 존재 | validate가 미고정 경고 ✓ | 일치 / **단순화**: validate는 name·targets·파일 참조만 검사(실제는 전체 스키마 검증) |
| 11 | CLI | `tables list CATALOG SCHEMA`, `tables get FULL_NAME`, `catalogs list` 존재 | 동일 구문 | 일치 (`schemas list`, `auth describe`, `current-user me`는 이번에 페이지 미확인) |
| 12 | Genie | 현재 명칭 **Genie Agents**(구 Spaces), 최종 사용자는 UC SELECT + 에이전트 접근 필요, warehouse 권한 불필요, 데이터 소스 ≤ 50 | 사용자 UC 권한 적용·warehouse 불요 ✓ | 일치 / JOIN 설정 방식은 문서에 없어 '미검증' |
| 13 | 파이프라인 expectation | 경고(EXPECT, 기본)·DROP ROW·FAIL UPDATE. **내장 quarantine 없음** | block/quarantine/warn 표기 | **표기 불일치→수정**: UI·HELP·KB에 공식 대응 명시, quarantine은 WIZBASE 패턴으로 표기 |
| 14 | 파이프라인 제품명·구성 | "Spark Declarative Pipelines on Lakeflow", streaming table·materialized view | 평범한 SELECT 정의 + 가상 expectation | **단순화**(UI에 명시). Python 모듈명 등은 확인 필요 |
| 15 | QUALIFY | Databricks SQL·DBR 10.4+ 지원(집계 불가, 윈도 함수 필요) | 파이프라인 복구에 사용 | 일치 |
| 16 | 명칭 변경 | Vector Search→**AI Search**(2026-06), Delta Sharing→**OpenSharing**(2026-06), Genie Spaces→Genie Agents(2026-07) | 기능 매니페스트는 ai_search, Genie Agents 사용 | 일치 + KB-07/08 별칭 추가 |
| 17 | DE-A 시험 | 45문항·90분·7영역(6/21/22/16/10/10/15%), $200, 유효 2년, 한국어 포함, 합격선 비공개 | 동일 | 일치 (공개 사실표 추가) |
| 18 | GenAI-A 시험 | 45문항·90분·6영역(14/14/30/22/8/12%), $200, 재응시 14일, 한국어 포함, 웹은 Multiple choice만 표기 | 동일, 복수선택은 PDF 근거로 지원 | 일치 + 상충(SC-04) 유지 |
| 19 | DE-P 시험 | 웹: 59문항·120분·10영역·한국어 포함 / 10월 PDF: 60문항·9영역·영어 | 두 프로필 분리 보존 | 일치 — **웹 10개 영역 비중을 이번에 적재**(DE-P-WEB), 혼합 금지·판정 보류 유지 |
| 20 | 릴리스 노트 최신 | 2026-11월 항목까지 게시, DBR 18 LTS(2026-07) | 프로필 `dbr_version: not_applicable`(serverless 기준) | 일치 (버전 고정은 실측 단계 필요) |

## 2. 상세 작동 검증

| 검증 | 결과 |
|---|---|
| 자동 테스트(AT-01~42 + 가이드 + 추가) | **53 passed** |
| 전 여정 E2E(학습자·관리자·리뷰어·강사 4역할, 15단계) | **43/43 PASS** (수료 판정·증거 보고서·결정적 재생 포함) |
| 20명 동시(로컬 루프백, 단일 PC) | 세션 생성 p95 0.67s, 메타데이터 p95 **0.11s**(목표 ≤1s), SQL p95 **0.44s**(목표 ≤3s), 오류 0 |
| 보안 프로브 | 무토큰 401, 경로 탐색/data 디렉터리 노출 404, openapi 비공개, 잘못된 직원 코드 403, 교차 조인 폭주 → 실행 오류로 제어, 학습자의 principal 사칭 403, 강사 API 403, 문항 정답 미노출 |

### 이번 검수에서 발견·수정한 결함
1. **재생 불일치**: 강사 장애 주입이 재생 로그에 없어 "결정적 재생"이 달라짐 → 로그·재생에 포함(E2E 재검증 일치).
2. **Foreign catalog 권한 모델이 공식 요구보다 느슨함** → metastore `CREATE CATALOG` 추가 검사.
3. **로그인 속도 제한이 교육장 NAT에서 학습자를 차단**(IP당 15회/5분) → 실패한 직원 코드에만 적용, 회귀 테스트 추가.
4. **튜터 키워드 과매칭**(일반어 '파이프라인'으로 근거 없는 답변) → 태그 정리, 기존 AT-37이 포착.
5. **품질 규칙 표기가 공식 의미와 다름**(quarantine) → 공식 expectation 대응표로 정정.
(이전 라운드: 비밀값이 재생 로그에 남던 문제, 재고 변경 시 주문 비교 로직 등 수정 완료.)

## 3. 현장 프로젝트·개발환경 적합성 평가

**현장 흐름과 일치하는 부분(입문 코어)**: 환경·신원 확인 → 요구·데이터 계약 → 권한 오류 진단·최소권한 요청 → 원천 연결·foreign catalog → 정합성 검증 → 파이프라인 품질 실패·복구 → Job run-as → Genie 사용자별 접근 → 승인형 주문 변경(멱등·충돌·변조 차단) → Bundle 검증/배포/실행 구분 → 평가·증거 보고서. 순서·책임 분리(요청자/승인자/실행자)·증거 중심 평가는 파트너 PoC 진행 방식과 맞다.

**현장과 차이가 큰 부분(보강 필요, 우선순위 순)**
| 우선 | 격차 | 영향 | 권장 |
|---|---|---|---|
| 높음 | **실제 Spark/Delta 미실행**: PySpark, Delta(MERGE·time travel·CDF), Auto Loader/COPY INTO, Structured Streaming, streaming table/materialized view 문법 | DE-A/P 시험 영역 다수·실무 핵심을 손으로 훈련 불가 | C 모드 어댑터 또는 증거 제출 경로로 실제 워크스페이스 실습(DE-01~08) |
| 높음 | Python 격리 실행기 없음 | 노트북·정책 함수·pytest 실습 불가 | 컨테이너 샌드박스(비루트·네트워크 차단) 후 AT-16 재검증 |
| 높음 | 실제 워크스페이스·SA 대조(WORKSPACE_CHECKED/SA_REVIEWED) 없음 | UI·오류문구·권한 의미 차이 미확인 | V1~V6 절차 수행 |
| 중간 | 권한 모델 단순화: MANAGE, Job ACL, 서비스 프린시펄 사용 권한, 행 필터·열 마스크·ABAC, 뷰 소유자 의미 | run-as/거버넌스 시험·현장 질의 | 프로필별 규칙 추가 + 실측 |
| 중간 | 미구현 기능 영역: AI/BI 대시보드, SQL Alert, Job 트리거·repair run, system tables·사용량, Secrets, Git folders, OAuth/서비스 프린시펄 인증, PrivateLink 등 네트워크, AI Search/Serving/MLflow(GEN-A 실습) | 현장 인수·운영 단계 | 해당 팩(DE-09/10/12, GEN-01~07) 구현 |
| 중간 | 개발 환경: 현장 개발자는 로컬 CLI·VS Code·Git·CI(GitHub Actions 등)를 쓰나 본 시스템은 브라우저 내 가상 터미널 | 설치·인증·환경 문제 대응 훈련 공백 | 로컬 CLI 설치/OAuth/프로필 가이드 모듈 + 실제 CLI는 C 모드에서만 |
| 낮음 | 모의 UI가 실제 Databricks UI와 다름(의도) | 메뉴 위치 학습 전이 | 프로필 UI 매핑·캡처 대조 |
| 낮음 | 문항 16개 AI 초안·bullet objective 미적재 | 시험 대비 수준 주장 불가 | 공식 가이드 PDF 적재, 인간 검수 3회 |

## 4. 결론
- **공식 문서 기준 사실 정합성**: 핵심 사실 20개 항목 중 불일치 2건(foreign catalog 권한, 품질 규칙 표기)을 수정했고, 나머지는 일치 또는 *명시된 단순화*다.
- **작동**: 입문 코어 전 여정이 실제 상태 기반으로 끝까지 동작하며 결정적으로 재생된다.
- **주장 가능한 범위**: "공식 문서와 대조한 입문 코어 리허설". **주장 불가**: 실제 DBX와 동일, 시험 준비 완료, SA 검토 완료, 전 직무 인증 지원.

## 5. 후속: 실제 DBX 실습 경로(C-검토형) 구현 (2026-11-11)
- 구성: `adapter/`(학습자 PC 증거 수집기, 표준 라이브러리만) + `backend/labs.py`(실습 콘텐츠·서버 자동 대조) + UI-22 개편. 서버는 Databricks 자격증명을 받지 않음.
- 실습 팩 작성: LAB-CORE-01, LAB-DE-02, LAB-DE-03(자동 대조), LAB-DE-12(CLI 증거), LAB-DE-06/DE-10(수동). 지시서 팩 21개 중 **6개만 작성** — 나머지는 '미작성'으로 표시되고 준비 판정을 차단.
- 검증: 65 tests passed(실습 테스트 12개: 기대값 비공개, 체크섬 정규화, adapter 범위 제한·변조 팩 거부, 자격증명 미포함, 불일치/구버전 팩/재사용 증거 거부, 검토자 승인 조건).
- **미검증**: adapter의 실제 Databricks 워크스페이스 실행(Statement API 응답 형식, `SELECT version()`, Delta MERGE 결과). 가짜 Statement API(DuckDB)로만 테스트함.
