# Databricks 실제 워크스페이스 조회 결과와 시뮬레이터 비교 (2026-11-12)

- 조회 대상: Databricks **Free Edition** 워크스페이스(사용자 계정으로 로그인된 브라우저, 조회 전용 — 생성·설정 변경·수강 시작 등 상태를 바꾸는 동작은 하지 않음).
- 한계: Free Edition 은 유료(Enterprise) 워크스페이스와 메뉴·기능이 다르다(서버리스 전용, SQL Warehouse 생성 비활성 등). 이 문서는 **이 계정에서 보인 범위**의 기록이며 '문서 확인'이 아니라 '화면 관찰(WORKSPACE_OBSERVED)' 수준이다. 아래 '미조회 항목'은 아직 보지 못했다.

## 1. 관찰한 화면 구성

| 영역 | 관찰 내용 |
|---|---|
| 좌측 메뉴 | New · Home · Learn · Workspace · Recents · Catalog · Jobs & Pipelines · Compute · Discover · Marketplace / **SQL**: SQL Editor · Queries · Dashboards · Genie Agents · Alerts · Query History · SQL Warehouses / **Data Engineering**: Runs · Data Ingestion · Visual Data Prep |
| 상단 | 통합 검색(Ctrl+P), "Verify identity" 배지, workspace 선택, Genie Code, Switch apps, 계정 메뉴 |
| Home | Welcome, 학습 지표(Day streak·Courses taken·Data sets created·Friends added·Achievements), Start learning 카드, Your resources |
| Catalog | 상단에 컴퓨트 표시(Serverless Starter Warehouse · Serverless · 2XS), 트리(My organization: workspace·system / Shares received: samples), 탭 Suggested·Favorites·Recents, 툴바 Govern·Connect·Share·Create, 열 Name·Reason for suggestion·Type |
| 테이블 상세 | 경로 Catalog Explorer > samples > bakehouse, 탭 **Overview · Sample Data · Details · Permissions · History · Lineage · Insights · Quality**, 우측 About this table(State·Owner·Type·Data source·Tags), Description, Columns(Column·Type·Comment), Open in a dashboard · Create |
| SQL Editor | 탭형 편집기(SQL Editor ▾ · New tab +), 시작 화면 "Create new: SQL Query" + Quick access(Recents·Favorites), 좌측 보조 아이콘(workspace·catalog) |
| SQL Warehouses | "Compute - SQL warehouses", 상단 탭 Serverless·SQL warehouses·AI Search·Apps·Lakebase, 필터(Only my…·Created by·Size·Status), 열 Status·Name·Created by·Size·Active/Max·Type, 기본 Serverless Starter Warehouse(2X-Small, 0/1), Create 비활성 |
| Jobs & Pipelines | 탭 Jobs & pipelines · Runs, Create new 카드(Ingestion pipeline·ETL pipeline·Job), 필터 All·Jobs·Pipelines / Owned by me·Accessible by me·Favorites / Tags·Run as, 열 Name·Type·Tags·Run as·Trigger·Recent runs |
| Workspace | 트리 Home·Shared with me·Workspace·Favorites·Trash, 경로 Workspace > Users > 이메일, 열 Name·Type·Owner·Created at·Last updated at, Create 메뉴 |
| Genie Agents | 검색, 필터(Domain·Owned by me·Modified this week·Favorited·Certified·Popular), Genie One 안내, 목록(Name·Description·Modified·Owner·Tags) |
| Add data | Files(Create or modify table · Upload files to a volume), Databricks connectors 목록(Amazon S3·Foreign Catalog·OpenSharing·Salesforce·SQL Server·Google Analytics·SAP·Workday·ServiceNow·Dynamics 365·MySQL·SharePoint …) |
| Visual Data Prep | Lakeflow Designer 안내(No-code data prep), 파일 검색·필터 |
| Dashboards / Alerts / Query History | Dashboards(View samples gallery·Create dashboard, 필터 Domain 등), Alerts(탭 Alerts·Legacy alerts, Create alert), Query History(필터 User·기간·Compute·Duration·Status·Statement·Source·Statement ID, Refresh) |
| Discover | Domains(Sales·Marketing·Finance·Human Resources) 기반 자산 탐색, 자산 유형 필터(Notebooks·Tables·Jobs·Dashboards…) |
| Learn / Academy | 역할별 경로(데이터 엔지니어·분석가·ML·생성형 AI), 코스 개요 페이지: 예상 시간 235분·레슨 11·실습 8, What you'll learn·Skills·Prerequisites(Free Edition, 서버리스, 코스 전용 catalog 생성 권한), 좌측 개요 목록(진행 0/19, Demo → Lab 쌍, 보너스 레슨, Summary) |

## 2. 시뮬레이터와의 차이와 개선 제안

| 우선 | 항목 | 현재(시뮬레이터) | 실제(관찰) | 제안 |
|---|---|---|---|---|
| P1 | Query History | SQL Editor 안 간단한 이력 | 전용 화면 + 8가지 필터 | 쿼리 이력 화면 추가(상태·기간·소스·시간, 실패 클릭 시 해결 안내 연결) |
| P1 | 테이블 상세 | 컬럼·미리보기·계보 | Overview·Sample Data·Details·Permissions·History·Lineage·Insights·Quality 탭 | 탭 구조로 개편, **History(버전 이력)** 탭 추가 |
| P1 | 버전 이력·타임 트래블 | 없음 | 코스 레슨 주제이자 History 탭 | Delta 이력 시뮬레이션(DESCRIBE HISTORY, VERSION AS OF) 실습 추가 |
| P1 | 데이터 적재 | Connections/수집 중심 | Add data 허브(파일 업로드·볼륨·커넥터), CTAS·COPY INTO 실습 | 합성 CSV 업로드→테이블 생성(Create or modify table), COPY INTO 증분 적재 실습 |
| P2 | 서버리스 웨어하우스 | 프로필은 서버리스인데 **수동 시작** 필요 | 서버리스 Starter Warehouse(Active 0/1) | 서버리스는 쿼리 시 자동 시작으로 동작하는 모드 추가, 수동 시작은 Classic/Pro 모드로 분리(실제 자동 시작 동작은 SELECT 1 실행으로 확인 필요) |
| P2 | Free Edition 프로필 | AWS 서울 교육 기준 1종 | 서버리스 전용·Warehouse 생성 비활성·catalog `workspace` | 프로필 선택지에 Free Edition 추가(제약 안내 포함) |
| P2 | 메뉴 이름·묶음 | Jobs / Pipelines 분리, Genie | **Jobs & Pipelines**(+Runs 탭), SQL 그룹, Data Engineering 그룹, **Genie Agents** | 메뉴·화면 이름을 실제와 맞추고 SQL·Data Engineering 그룹 반영 |
| P2 | Workspace 트리 | 리소스 목록 | Home·Shared with me·Workspace·Favorites·Trash | 같은 구조로 개편 |
| P2 | Academy 연계 | 16단계 여정 | 레슨 11·실습 8, Demo→Lab 쌍, 예상 시간, 선수 조건 | "Get started with data engineering" 대응 실습 경로(레슨↔우리 실습 매핑), 단계에 예상 시간·선수 조건 표기 |
| P3 | 없는 화면 | — | Queries(저장 쿼리)·Dashboards·Alerts·Recents·Discover·Marketplace·통합 검색(Ctrl+P) | 필요도 순으로 간이 버전 추가 |
| P3 | 용어 | Genie·DLT 표기 | Genie Agents·Genie Code·Genie One·Lakebase·AI Search(Compute 탭)·Visual Data Prep(Lakeflow Designer)·OpenSharing | 용어 사전·공식 명칭 변경 표에 추가 |
| P3 | 동기 부여 | 진행률 % | Day streak·Achievements | 연속 학습일·성취 배지 검토 |

## 3. 역할별 학습 경로(Learn > Browse, 2차 조회)
조회 전용. 레슨 본문은 열지 않았고 코스 개요(제목·시간·선수 조건)만 읽었다.

| 역할 경로 | 토픽(사용자 제공) | 코스(단계) |
|---|---|---|
| Data engineers | Workspace · Databricks Apps · Jobs and pipelines | 온보딩 1: Get started with data engineering(235분) / Associate 2: Spark Declarative Pipelines(240분), 3 Lakeflow Connect·4 Lakeflow Jobs·5 DevOps(공개 예정) / Professional 6: Declarative Automation Bundles(공개 예정) |
| Data analysts | AI/BI Dashboards · Visualizations · Genie (페이지 태그: Data cleaning, joins, and aggregations · Lakeflow Designer · Medallion Architecture) | 온보딩 1: SQL analytics and BI(230분) / Associate 2: No code ETL with Lakeflow Designer(245분), 3 AI/BI for data analysts(310분, 개요 링크 없음), 4 SQL analytics(공개 예정) |
| ML practitioners | Workspace · Notebooks · Unity Catalog | 온보딩 1: Get started with Databricks for machine learning(145분) |
| Generative AI engineers | Generative AI · RAG · Model Serving | 온보딩 1: Get started with Databricks for generative AI(315분) / 2 AI agents·3 Agent evaluation(공개 예정) |

관찰 사항: 코스 개요가 레슨을 Demo/Lab/Lecture 로 구분하고, 선수 조건에 "코스 전용 catalog 생성 권한"이 4개 코스에 공통으로 나온다. ML·GenAI 코스는 Marketplace 데이터 설치, 모델 서빙/AI Search 엔드포인트 용량을 요구한다.
시뮬레이터 반영: `backend/academy.py`(68개 레슨 제목 단위 대응) · 화면 UI-07b Academy 경로 대응 · 세션 기록 기반 자동 실습 확인.

## 4. 미조회 항목(다음에 확인 필요)
Recents · Marketplace · Queries · Runs · Data Ingestion 하위 화면 · Visual Data Prep 상세 · Settings(Identity & access) · New 메뉴 · Genie Code 패널 · 테이블의 Permissions/History/Lineage 탭 내용 · Academy **레슨 본문 화면**(수강 시작 시 진행 상태가 생겨 보류) · SQL 실행 결과 화면과 웨어하우스 자동 시작 동작(쿼리 실행이 필요해 보류).
