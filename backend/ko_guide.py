"""한국어 공식 가이드(S05 등) 적재 결과 조회: bullet 원문은 저장하지 않고 sha256만 보관, 영문 최신본과의 차이를 표로 제공."""
from __future__ import annotations
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
NOTES = {
    "DE-A": "영문 2026-08 가이드와 영역·bullet 구성이 일치(7영역 33개) → 같은 순서의 bullet에 한국어 원문 해시를 연결. 번역 문구 차이는 검토자가 PDF로 확인.",
    "DE-P": "한국어 2025-09-30판(10영역·54 bullet)은 영문 2026-10 PDF(9영역)와 다른 이전 버전이며 웹 프로필(10영역·59문항)과 같은 계열로 추정. 학습 기준이 아니라 'DE-P 웹 프로필' 보존용 — 웹 페이지 대조는 검토자 확인 필요.",
    "GEN-A": "한국어 2024-06-01판(6영역·45 bullet)은 영문 2026-08판과 영역별 bullet 수가 달라 이전 버전으로 취급. 1:1 매핑하지 않음.",
}


def _load(name):
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


def ko_guide():
    ko, en = _load("official_objectives_ko.json"), _load("official_objectives.json")
    out = {"extracted": ko["extracted"], "method": ko["method"], "exams": {}}
    for ex, d in ko["exams"].items():
        enc = Counter(o["section_no"] for o in en["exams"][ex]["objectives"])
        rows = [{"section_no": s["section_no"], "section_name": s["section_name"], "weight": s["weight"], "ko_bullets": len(s["bullets"]), "en_bullets": enc.get(s["section_no"], 0),
                 "match": len(s["bullets"]) == enc.get(s["section_no"], 0)} for s in d["sections"]]
        aligned = all(r["match"] for r in rows) and len(rows) == len(enc)
        out["exams"][ex] = {"version": d["version"], "source_url": d["url"], "guide_sha256": d["guide_sha256"], "bullet_count": d["bullet_count"], "en_bullet_count": len(en["exams"][ex]["objectives"]),
                            "aligned_with_en_latest": aligned, "status": "ALIGNED_HASH_LINKED" if aligned else "OLDER_VERSION_REFERENCE", "sections": rows, "note": NOTES[ex],
                            "bullets": [{"section_no": s["section_no"], "index": i + 1, "sha256": b["sha256"], **({"linked_oid": f"OBJ-{ex}-s{s['section_no']}b{i + 1}"} if aligned else {})} for s in d["sections"] for i, b in enumerate(s["bullets"])]}
    return out
