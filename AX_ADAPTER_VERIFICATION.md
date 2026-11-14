# AX 레거시 DB adapter 검증 기록 (2026-11-14)

**범위**: 같은 합성 유통 fixture(`backend/ax_fixture.py`)를 Docker 시험 DB에 적재해 확인했다. 고객 DB·운영 DB가 아니다.

| 엔진 | 버전(시험 DB) | 드라이버 | 결과 |
|---|---|---|---|
| PostgreSQL | 16.16 | psycopg2 2.9.13 | 통과 |
| MySQL | 8.4.13 | PyMySQL 1.2.x | 통과 |
| Oracle | AI Database 26ai Free 23.26.3 | python-oracledb 3.x(thin) | 통과 |

## 확인한 것(엔진별 동일 시험)
연결 7단계(DNS·TCP·인증·DB 식별·메타데이터 가시성·한정 조회) · 잘못된 secret은 AUTH 단계에서만 실패하고 값이 응답에 없음 · 개발 플래그 없으면 직접 접속 거부 ·
구조 수집이 fixture 정의와 일치(컬럼 순서·복합 PK 순서·복합/자기참조 FK·뷰 정의·한글 주석·추정 행 수) · 재수집 diff 없음 ·
관계 후보(선언 FK 제외, 포함률)·ERD·표본 profile(민감 컬럼 마스킹) · 첫 slice(20→35박스: 추가 가용 12·부족 3·최대 32) · tenant 분리 ·
native 파이프라인 · 조회/명령 계정 분리(조회 계정 쓰기 불가, 명령 계정은 `sales_orders.requested_qty/row_version`과 `stock.row_version`만 수정 가능) ·
승인형 명령 1회 처리·멱등 재요청·승인 뒤 레거시 변경 시 STALE · 매출 4·매입 4 도구 golden 24건·보안 11건 · 신호 탐지.

## 시험으로 발견해 고친 것
1. PostgreSQL: `information_schema.table_constraints`는 SELECT 권한만 있는 계정에게 제약을 숨겨 PK가 비어 보였다 → `pg_constraint` 기준으로 수집.
2. MySQL: 뷰 정의는 `SHOW VIEW` 권한이 없으면 비어 있다 → 비어 있으면 "미확인"으로 표시(`view_sql_note`).
3. PostgreSQL/MySQL: `SELECT … FOR UPDATE`는 UPDATE 권한을 요구한다 → 명령 계정에 `stock.row_version` 한 컬럼만 UPDATE 부여, 잠금 순서(재고→주문) 고정.
4. MySQL: 4개 문자열 컬럼 복합키가 utf8mb4에서 키 길이 한도를 넘었다 → fixture 길이 조정.

## 확인하지 못한 것
고객 개발 DB · 다른 DB 버전(Oracle 11g/12c/19c, PostgreSQL 12~15, MySQL 5.7 등) · MariaDB · SQL Server · TLS 접속 · RAC/복제본 · 따옴표 소문자 식별자(Oracle) ·
실제 동시 부하 · 서버의 직접 접속 대신 쓰는 고객망 connector agent(미구현; 직접 접속은 `WZ_AX_ALLOW_DIRECT_DB=1` 개발 전용).

## 재현
```
docker run -d --name wzax-pg -e POSTGRES_PASSWORD=wzpass -e POSTGRES_DB=wzdev -p 127.0.0.1:15432:5432 postgres:16
docker run -d --name wzax-my -e MYSQL_ROOT_PASSWORD=wzpass -e MYSQL_DATABASE=wzdev -p 127.0.0.1:13306:3306 mysql:8.4
docker run -d --name wzax-ora -e ORACLE_PASSWORD=wzpass -p 127.0.0.1:11521:1521 gvenzl/oracle-free:slim-faststart
pip install -r requirements-dev.txt
WZ_AX_REAL=pg,mysql,oracle python -m pytest tests/test_ax_real_db.py -q     # 기본(WZ_AX_REAL 없음)은 건너뜀
```
시험용 비밀번호는 컨테이너 전용 합성 값이다(운영 값 아님).
