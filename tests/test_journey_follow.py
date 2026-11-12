"""초보자 시뮬레이션: AI 지원이 알려 주는 '다음 단계' 버튼만 순서대로 눌러서 전체 여정이 끝까지 진행되는지 확인한다.
(화면의 버튼이 하는 일 = nav(prefill 채우기) + 그 화면의 실행 버튼 / cmd(바로 실행). 서버 API로 똑같이 재현한다.)"""
import json
from test_at import client, env, login  # noqa: F401


def _guide(e):
    return e["c"].get(f"/api/sessions/{e['sid']}/guide", headers=e["L"]).json()


def _press(e, sc, log):
    """버튼 1회 동작을 재현한다. 반환: 진행을 시도했으면 True, 사람이 직접 입력/판단해야 하면 False."""
    c, sid, L, A = e["c"], e["sid"], e["L"], e["A"]
    if sc["type"] == "cmd":
        r = c.post(f"/api/sessions/{sid}/commands", headers=L, json={"command_type": sc["command_type"], "payload": sc.get("payload") or {}})
        log.append(f"cmd {sc['command_type']} {sc.get('payload')} -> {r.status_code} {r.json().get('status')} {str(r.json().get('result'))[:160]}")
        return r.status_code == 200
    pf = sc.get("prefill") or {}
    if "sqlbox" in pf:    # 화면 이동 후 [실행] 버튼
        r = c.post(f"/api/sessions/{sid}/commands", headers=L, json={"command_type": "sql.execute", "payload": {"sql": pf["sqlbox"]}})
        log.append(f"sql({pf['sqlbox'][:40]}) -> {r.json().get('status')}")
        return r.status_code == 200
    if "cdcsql" in pf:    # CDC 화면: [이 SQL 실행] 뒤 [정합성 점검]
        r = c.post(f"/api/sessions/{sid}/commands", headers=L, json={"command_type": "sql.execute", "payload": {"sql": pf["cdcsql"]}})
        c.post(f"/api/sessions/{sid}/commands", headers=L, json={"command_type": "cdc.check", "payload": {}})
        log.append(f"cdc sql+check -> {r.json().get('status')}")
        return r.status_code == 200
    if "plsql" in pf:     # 파이프라인 화면의 [저장 → 검증 → 실행 (한 번에)]
        for body in ({"action": "edit", "source_sql": pf["plsql"]}, {"action": "validate"}, {"action": "run"}):
            r = c.post(f"/api/sessions/{sid}/commands", headers=L, json={"command_type": "pipeline", "payload": body})
        log.append(f"pipeline 저장→검증→실행 -> {r.json().get('status')}")
        return r.status_code == 200
    if "t_sec" in pf:     # 권한 요청서 제출 → 관리자가 승인(다른 사람이 처리하는 단계)
        t = c.post("/api/permission-requests", headers=L, json={"session_id": sid, "securable": pf["t_sec"], "privilege": pf["t_priv"], "reason": pf.get("t_reason", "필요 권한 요청(업무 조회)")}).json()
        log.append(f"ticket {pf['t_sec']} {pf['t_priv']} -> {t.get('status') or t}")
        if t.get("ticket_id"):
            c.post(f"/api/sessions/{sid}/tickets/{t['ticket_id']}/resolve", headers=A, json={"decision": "approve"})
        return bool(t.get("ticket_id"))
    log.append(f"nav {sc.get('view')} (사람이 화면에서 직접 입력/선택 필요) prefill={list(pf)}")
    return False


def test_following_the_next_buttons_makes_progress_or_names_the_human_step(env):
    log, last = [], -1
    stuck = []
    for i in range(60):
        g = _guide(env)
        n = g["next"]
        if not n:
            break
        last = g["percent"]
        sc = n["shortcut"]
        ok = _press(env, sc, log)
        g2 = _guide(env)
        if g2["percent"] == g["percent"] and g2["next"] and g2["next"]["sub"] == n["sub"]:
            stuck.append(n["sub"])
            if len(stuck) >= 6 and len(set(stuck[-6:])) == 1:
                break        # 같은 버튼을 여러 번 눌러도 더 못 나아감
        else:
            stuck.clear()
    g = _guide(env)
    done = g["percent"]
    print("\n".join(log))
    print("진행률", done, "% / 막힌 단계:", g["next"] and (g["next"]["step_no"], g["next"]["title"], g["next"]["sub"]))
    # 버튼만으로도 상당 부분(초기 단계)은 끝까지 진행되어야 한다
    assert done >= 55, "AI 지원의 다음 단계 버튼만 따라가도 진행되지 않음"
