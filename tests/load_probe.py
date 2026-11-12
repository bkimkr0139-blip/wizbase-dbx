"""지시서 23절 성능 설계 목표 측정(20명 동시): 메타데이터 p95<=1s, 기본 SQL p95<=3s, 비동기 상태 반영<=2s. + 기본 보안 프로브."""
import sys, json, time, statistics, threading, httpx, pathlib

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8830"
N = 20
meta_t, sql_t, create_t, errs = [], [], [], []
lock = threading.Lock()


def user(i):
    c = httpx.Client(base_url=BASE, timeout=60)
    try:
        h = {"Authorization": "Bearer " + c.post("/api/auth/login", json={"name": f"u{i}", "role": "learner"}).json()["token"]}
        t = time.time(); sid = c.post("/api/sessions", headers=h, json={}).json()["session_id"]; ct = time.time() - t
        c.post(f"/api/sessions/{sid}/commands", headers=h, json={"command_type": "warehouse", "payload": {"action": "start"}})
        for _ in range(2):
            c.post(f"/api/sessions/{sid}/commands", headers=h, json={"command_type": "env.check", "payload": {}})
        local_m, local_s = [], []
        for _ in range(5):
            t = time.time(); c.get(f"/api/sessions/{sid}/state", headers=h); local_m.append(time.time() - t)
            t = time.time(); c.get(f"/api/sessions/{sid}/catalog", headers=h); local_m.append(time.time() - t)
            t = time.time()
            r = c.post(f"/api/sessions/{sid}/commands", headers=h, json={"command_type": "sql.execute", "payload": {"sql": "SELECT status, COUNT(*) FROM food_dev.bronze.raw_orders GROUP BY status"}})
            local_s.append(time.time() - t)
            assert r.status_code == 200 and r.json()["status"] == "ok", r.text[:100]
        with lock:
            meta_t.extend(local_m); sql_t.extend(local_s); create_t.append(ct)
    except Exception as e:
        with lock:
            errs.append(repr(e)[:150])


ths = [threading.Thread(target=user, args=(i,)) for i in range(N)]
t0 = time.time(); [t.start() for t in ths]; [t.join() for t in ths]
p95 = lambda xs: round(sorted(xs)[int(len(xs) * 0.95) - 1], 3) if xs else None
print(json.dumps({"users": N, "wall_s": round(time.time() - t0, 1), "errors": errs, "session_create_p95_s": p95(create_t), "metadata_p95_s": p95(meta_t), "sql_p95_s": p95(sql_t), "samples": [len(create_t), len(meta_t), len(sql_t)],
                  "targets": {"metadata_p95<=1s": p95(meta_t) is not None and p95(meta_t) <= 1, "sql_p95<=3s": p95(sql_t) is not None and p95(sql_t) <= 3}}, ensure_ascii=False))

# ---- security probes
c = httpx.Client(base_url=BASE, timeout=20, follow_redirects=False)
probe = {}
probe["no_token_state"] = c.get("/api/sessions/s_x/state").status_code
probe["static_traversal"] = c.get("/static/..%2f..%2fdata%2f.staff_codes.json").status_code
probe["data_dir_exposed"] = c.get("/data/.staff_codes.json").status_code
probe["openapi_hidden"] = c.get("/openapi.json").status_code
probe["bad_token"] = c.get("/api/me", headers={"Authorization": "Bearer nope"}).status_code
probe["staff_code_wrong"] = c.post("/api/auth/login", json={"name": "x", "role": "instructor", "code": "wrong"}).status_code
h = {"Authorization": "Bearer " + c.post("/api/auth/login", json={"name": "p", "role": "learner"}).json()["token"]}
sid = c.post("/api/sessions", headers=h, json={}).json()["session_id"]
c.post(f"/api/sessions/{sid}/commands", headers=h, json={"command_type": "warehouse", "payload": {"action": "start"}})
for _ in range(2):
    c.post(f"/api/sessions/{sid}/commands", headers=h, json={"command_type": "env.check", "payload": {}})
heavy = c.post(f"/api/sessions/{sid}/commands", headers=h, json={"command_type": "sql.execute", "payload": {"sql": "SELECT COUNT(*) FROM food_dev.bronze.raw_orders a, food_dev.bronze.raw_orders b, food_dev.bronze.raw_orders c, food_dev.bronze.raw_orders d, food_dev.bronze.raw_orders e"}})
probe["cross_join_dos_handled"] = (heavy.status_code, heavy.json().get("status"), (heavy.json().get("result", {}).get("error") or {}).get("code"))
probe["privilege_escalation_as_principal"] = c.post(f"/api/sessions/{sid}/commands", headers=h, json={"command_type": "sql.execute", "payload": {"sql": "SELECT 1", "as_principal": "uc-admin@wizbase.training"}}).status_code
probe["learner_instructor_endpoint"] = c.get("/api/instructor/answer-key", headers=h).status_code
probe["learner_items_answers_exposed"] = any("correct" in i for i in c.get("/api/items", headers=h).json())
print(json.dumps(probe, ensure_ascii=False))
