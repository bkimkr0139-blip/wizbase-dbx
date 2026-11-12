"""Model Serving 공용 계층(시뮬레이션). ML(모델)과 생성형 AI(에이전트)가 같은 엔드포인트 슬롯을 쓴다.

- 슬롯: Free Edition처럼 동시에 2개(MAX_SLOTS). 초과하면 SERVING_QUOTA.
- 종류별 처리기: HANDLERS[kind](S, endpoint, payload) -> dict. ext_ml 이 "model", ext_genai 가 "agent" 를 등록한다.
- 상태: 시뮬레이션이라 만들면 바로 READY(실제는 시간이 걸림).
"""
from __future__ import annotations
import re, time
from typing import Optional

from fastapi import Header

from . import core
from .core import ApiError

MAX_SLOTS = 2
HANDLERS: dict = {}
VALIDATORS: dict = {}   # kind -> fn(S, config) : 만들기 전에 config 를 검사(실패 시 ApiError)
_NAME = re.compile(r"^[a-z][a-z0-9-]{1,40}$")


def register_handler(kind: str, fn, validator=None):
    HANDLERS[kind] = fn
    if validator:
        VALIDATORS[kind] = validator


def _eps(S) -> dict:
    return S.setdefault("serving", {})


def create(S, actor, name: str, kind: str, config: dict) -> dict:
    if not isinstance(config, dict):
        raise ApiError(400, "INVALID_INPUT", "config 는 JSON 객체여야 합니다.")
    if not _NAME.match(name or ""):
        raise ApiError(400, "INVALID_NAME", "엔드포인트 이름은 영문 소문자로 시작하고 소문자·숫자·- 만 쓸 수 있습니다(2~41자).")
    if kind not in HANDLERS:
        raise ApiError(400, "UNSUPPORTED_KIND", f"지원하지 않는 종류: {kind}. 지원: {', '.join(HANDLERS) or '(없음)'}")
    if kind in VALIDATORS:
        VALIDATORS[kind](S, config or {})
    eps = _eps(S)
    if name in eps:
        raise ApiError(409, "ENDPOINT_EXISTS", f"엔드포인트 `{name}`이(가) 이미 있습니다.")
    if len(eps) >= MAX_SLOTS:
        raise ApiError(429, "SERVING_QUOTA", f"엔드포인트 슬롯 {MAX_SLOTS}개를 모두 사용 중입니다.", )
    ep = {"name": name, "kind": kind, "config": config, "state": "READY", "created_by": actor["user_id"], "created_at": core.now_utc(), "queries": 0, "last_query_at": None}
    eps[name] = ep
    core.audit(S, actor["user_id"], "SERVING_CREATE", name, "succeeded", "SIMULATED", {"kind": kind})
    return ep


def delete(S, actor, name: str):
    if name not in _eps(S):
        raise ApiError(404, "ENDPOINT_NOT_FOUND", f"엔드포인트 `{name}`이(가) 없습니다.")
    del _eps(S)[name]
    core.audit(S, actor["user_id"], "SERVING_DELETE", name, "succeeded", "SIMULATED", {})


def query(S, actor, name: str, payload: dict) -> dict:
    ep = _eps(S).get(name)
    if not ep:
        raise ApiError(404, "ENDPOINT_NOT_FOUND", f"엔드포인트 `{name}`이(가) 없습니다.")
    t0 = time.time()
    if not isinstance(payload, dict):
        raise ApiError(400, "INVALID_INPUT", "질의 본문은 JSON 객체여야 합니다.")
    principal = core.ADMIN if actor.get("role") == "admin" else core.TRAINEE
    out = HANDLERS[ep["kind"]](S, ep, {**payload, "__principal": principal})
    ep["queries"] += 1
    ep["last_query_at"] = core.now_utc()
    core.audit(S, actor["user_id"], "SERVING_QUERY", name, "succeeded", "SIMULATED", {"kind": ep["kind"]})
    return {"endpoint": name, "kind": ep["kind"], "result": out, "latency_ms": int((time.time() - t0) * 1000), "evidence_level": "SIMULATED"}


def register(app, actor_of, sess):
    @app.get("/api/sessions/{sid}/serving")
    def serving_list(sid: str, authorization: Optional[str] = Header(None)):
        S = sess(sid, actor_of(authorization))
        with core.lock_for(sid):
            return {"endpoints": list(_eps(S).values()), "max_slots": MAX_SLOTS, "kinds": list(HANDLERS), "evidence_level": "SIMULATED",
                    "note": "엔드포인트는 교육용 시뮬레이션입니다. 실제 모델 서빙이 아니며 응답은 로컬 계산 결과입니다."}

    @app.post("/api/sessions/{sid}/serving")
    def serving_create(sid: str, b: dict, authorization: Optional[str] = Header(None)):
        a = actor_of(authorization)
        S = sess(sid, a)
        with core.lock_for(sid):
            ep = create(S, a, str(b.get("name", "")), str(b.get("kind", "")), b.get("config") or {})
            core.save(S)
            return ep

    @app.post("/api/sessions/{sid}/serving/{name}/delete")
    def serving_delete(sid: str, name: str, authorization: Optional[str] = Header(None)):
        a = actor_of(authorization)
        S = sess(sid, a)
        with core.lock_for(sid):
            delete(S, a, name)
            core.save(S)
            return {"deleted": name}

    @app.post("/api/sessions/{sid}/serving/{name}/query")
    def serving_query(sid: str, name: str, b: dict, authorization: Optional[str] = Header(None)):
        a = actor_of(authorization)
        S = sess(sid, a)
        with core.lock_for(sid):
            r = query(S, a, name, b)
            core.save(S)
            return r
