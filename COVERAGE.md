# 지시서 v1.1 구현 매트릭스 (2026-11-11)

실행: `python -m uvicorn backend.main:app --host 127.0.0.1 --port 8830` · 테스트: `python -m pytest tests -q` (46 passed)
접근 코드: `data/.staff_codes.json` (강사/직원). 외부: frpc `frpc-dbx.toml` → dbx.wizbase.ai.kr (서버 nginx+DNS 필요)

| 영역 | 상태 |
|---|---|
| UI-01~16, 증거 보고서 | 구현 (A/B 모드). C 모드: 이 배포에 없음(차단) |
| UI-17~25 | 구현. 단, 공식 objective는 도메인 자리표시(bullet 미적재) → 출시 게이트 차단 |
| AT-01~42 | 자동화 테스트 통과. AT-16: Python 실행기 미구성(비활성 처리·DuckDB 외부접근 잠금 검증). AT-22: 어댑터 측 차단은 이 배포에서 증명 불가 |
| 문항은행 | 16문항 AI 초안(DRAFT). 인간 검수 전 → 봉인 시험 구성 불가 |
| 미수행 | 실제 DBX(C)·SA 검토·공식 가이드 bullet 적재·파일럿·부하(20명) 측정·Python 격리 실행기 |
