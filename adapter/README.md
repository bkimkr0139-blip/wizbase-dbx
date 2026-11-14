# WIZBASE 실제 DBX 실습 증거 수집기 (C 경로, 검토형) — adapter 1.1

운영 방식: **앱에서 사전훈련 → 내 PC에서 실제 DBX 수행(이 도구) → 앱에서 증거 검토·등급 판정.**

시뮬레이터는 **Databricks 자격증명을 받지 않습니다.** 이 도구는 학습자 PC에서 실행되어 본인의 *교육용* 워크스페이스에서 실습 SQL을 수행하고, 결과의 **체크섬과 statement ID만** 증거로 만듭니다.

## 준비
- Python 3.9+, Databricks CLI ≥ 0.218.0 (`databricks auth login` 으로 프로필 인증 완료)
- 교육용 워크스페이스의 SQL Warehouse ID, 쓰기 가능한 catalog (Free Edition/파트너 sandbox/회사 교육용). **고객 운영 catalog·실데이터 금지**
- 이 폴더의 `dbx_lab_runner.py`, `dbx_lab_common.py` 두 파일 (UI-22의 "adapter 내려받기 (.zip)" 로 받을 수 있음)

## 절차
0. **처음 한 번 사전 점검** — CLI 버전·로그인·warehouse·catalog 쓰기를 확인하고, 실패하면 원인을 알려 줍니다(토큰·사용자 이름은 출력하지 않음).
   ```
   python dbx_lab_runner.py doctor --catalog <catalog> --warehouse-id <id> --profile <프로필>
   ```
1. 시뮬레이터 UI-22에서 실습 팩(`LAB-xxx.pack.json`)을 내려받고 **[시도 ID 발급]** 으로 1회용 `wzA-…` ID(72시간)를 받는다.
2. 실행(한 줄로 입력하거나 줄 이음 문자 사용: cmd `^`, PowerShell 백틱, bash 역슬래시):
   ```
   python dbx_lab_runner.py run --pack LAB-CORE-01.pack.json --catalog <catalog> --warehouse-id <id> --workspace-ref ws-***1234 --cloud aws --region ap-northeast-2 --profile <프로필> --attempt-id wzA-xxxxxxxxxxxx --cleanup
   ```
   모든 SQL 끝에 `/* wzA-… */` 주석이 붙어 Query History 검색창에서 이 시도의 쿼리만 찾을 수 있습니다.
   Bundle 실습: `python dbx_lab_runner.py bundle-evidence --dir <bundle 경로> --workspace-ref ... --cloud ... --region ...`
3. 생성된 `*.evidence.json`을 UI-22 "증거 제출"에 붙여넣는다(또는 `--submit https://… --sim-token <시뮬레이터 로그인 토큰>`; Databricks 토큰이 아님).
4. 서버 자동 대조 → 검토자가 Query History에서 시도 ID로 검색해 task별 statement ID를 **직접 입력**(제출값과 다르면 승인 불가) → 승인/보류/반려. 보류·반려 사유는 UI-22 진행 현황에 표시됩니다.
5. 승인 뒤 실습 팩이 개정되면 그 승인은 STALE이 되어 등급·준비 판정에서 빠집니다(새 시도로 재수행).

## 서버가 거부하는 경우
- 시도 ID 없음·발급된 적 없음·다른 사람/다른 실습 것·재사용·72시간 만료
- adapter 버전 1.1 미만(SQL 자동 대조 팩), pack_hash 불일치(구 팩), 다른 학습자 증거와 같은 statement ID

## 안전장치
- 팩의 pack_hash 검증(변조 시 실행 거부). 모든 SQL은 실행 전 정적 검사: 허용 구문만, `GRANT/REVOKE/ALTER/COPY/DROP TABLE/CREATE CATALOG` 금지, 3단계 이름은 지정 `catalog.wz_lab_*` 스키마만, `system/samples/hive_metastore` catalog 금지. 시도 ID 주석은 이 검사를 통과한 뒤에 붙으며 형식(`wzA-` + 12자리 16진수)이 아니면 거부합니다.
- evidence에는 토큰·호스트·비밀번호가 포함되지 않는다(테스트로 검증). `workspace-ref`는 직접 마스킹한 값.
- 모든 외부 호출은 `databricks` CLI를 인자 리스트로 호출(shell 미사용).

## 검증 상태 (정직한 한계)
- 가짜 Statement API(DuckDB)로 파싱·체크섬·안전장치·시도 ID·doctor·서버 대조를 테스트했고, 위 실환경 확인을 더했다.
- **실환경 확인(2026-11-14, Free Edition 1곳, CLI 1.26.0)**: doctor 5개 항목 통과, LAB-CORE-01 실행 성공, count·available 체크섬이 서버 기대값과 일치, 시도 ID 주석이 Query History(`/api/2.0/sql/history/queries`)에 기록됨. `SELECT version()` 결과는 `4.2.0 …`.
- **아직 확인하지 못한 것**: 다른 실습 팩(LAB-DE-02·03·05 등), 다른 워크스페이스·클라우드·리전, TIMESTAMP/DATE 컬럼의 문자열 형식(현재 팩은 STRING 컬럼만 사용), Delta MERGE·DESCRIBE HISTORY 결과.
- 시도 ID·statement ID 대조는 자기 보고를 어렵게 할 뿐 위조 불가능을 보증하지 않는다. 최종 판단은 검토자의 원본 확인이다.
- DESCRIBE HISTORY·SHOW TABLES 등 관찰용 task는 자동 대조하지 않고 검토자가 본다.
