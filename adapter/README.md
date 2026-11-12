# WIZBASE 실제 DBX 실습 증거 수집기 (C 경로, 검토형)

시뮬레이터는 **Databricks 자격증명을 받지 않습니다.** 이 도구는 학습자 PC에서 실행되어 본인의 *교육용* 워크스페이스에서 실습 SQL을 수행하고, 결과의 **체크섬과 statement ID만** 증거로 만듭니다.

## 준비
- Python 3.9+, Databricks CLI ≥ 0.218.0 (`databricks auth login` 으로 프로필 인증 완료)
- 교육용 워크스페이스의 SQL Warehouse ID, 쓰기 가능한 catalog (Free Edition/파트너 sandbox/회사 교육용). **고객 운영 catalog·실데이터 금지**
- 이 폴더의 `dbx_lab_runner.py`, `dbx_lab_common.py` 두 파일

## 절차
1. 시뮬레이터 UI-22에서 실습 팩(`LAB-xxx.pack.json`)을 내려받는다.
2. 실행:
   ```
   python dbx_lab_runner.py run --pack LAB-CORE-01.pack.json --catalog <catalog> --warehouse-id <id> \
       --workspace-ref ws-***1234 --cloud aws --region ap-northeast-2 --profile <프로필> --cleanup
   ```
   Bundle 실습: `python dbx_lab_runner.py bundle-evidence --dir <bundle 경로> --workspace-ref ... --cloud ... --region ...`
3. 생성된 `*.evidence.json`을 UI-22 "증거 제출"에 붙여넣는다(또는 `--submit https://… --sim-token <시뮬레이터 로그인 토큰>`; Databricks 토큰이 아님).
4. 서버 자동 대조 → 검토자가 Query History의 statement ID로 원본 확인 → 승인.

## 안전장치
- 팩의 pack_hash 검증(변조 시 실행 거부). 모든 SQL은 실행 전 정적 검사: 허용 구문만, `GRANT/REVOKE/ALTER/COPY/DROP TABLE/CREATE CATALOG` 금지, 3단계 이름은 지정 `catalog.wz_lab_*` 스키마만, `system/samples/hive_metastore` catalog 금지.
- evidence에는 토큰·호스트·비밀번호가 포함되지 않는다(테스트로 검증). `workspace-ref`는 직접 마스킹한 값.
- 모든 외부 호출은 `databricks` CLI를 인자 리스트로 호출(shell 미사용).

## 검증 상태 (정직한 한계)
- 가짜 Statement API(DuckDB)로 파싱·체크섬·안전장치·서버 대조를 테스트했다.
- **실제 Databricks 워크스페이스 대상 실행은 아직 검증하지 못했다.** `databricks api post /api/2.0/sql/statements` 응답 형식, `SELECT version()`, Delta MERGE 결과는 첫 실사용 시 검토자와 함께 확인해야 한다.
- DESCRIBE HISTORY·SHOW TABLES 등 관찰용 task는 자동 대조하지 않고 검토자가 본다.
