"""한국어 공식 시험 가이드 PDF -> backend/official_objectives_ko.json (원문 저장 없이 sha256만).
사용: python -I -X utf8 tools/build_ko_objectives.py DEA.pdf DEP.pdf GEN.pdf   (PDF는 격리 폴더에 받아 경로만 전달)"""
import hashlib, json, re, sys
from pathlib import Path
import pypdf

OUT = Path(__file__).resolve().parent.parent / "backend" / "official_objectives_ko.json"
META = {
    "DE-A": {"url": "https://www.databricks.com/kr/sites/default/files/2026-08/databricks-certified-data-engineer-associate-exam-guide-may-2026-ko.pdf", "version": "2026-05-04"},
    "DE-P": {"url": "https://www.databricks.com/kr/sites/default/files/2025-11/databricks-certified-data-engineer-professional-september-2025-exam-guide3-kr.pdf", "version": "2025-09-30"},
    "GEN-A": {"url": "https://databricks.com/sites/default/files/2024-08/databricks-exam-guide-generative-ai-engineer-associate-exam-guide_ko-kr.pdf", "version": "2024-06-01"},
}
norm = lambda s: re.sub(r"\s+", " ", s).strip()


def parse(pdf):
    raw = Path(pdf).read_bytes()
    r = pypdf.PdfReader(pdf)
    j = norm(" ".join(p.extract_text() or "" for p in r.pages))
    a = j.find("시험 개요")
    a = j.find("섹션 1", a if a >= 0 else 0)
    b = j.find("샘플 질문", a)
    body = j[a:b if b > 0 else len(j)]
    parts = re.split(r"(섹션 \d+ ?: [^●]*?)(?=●|$)", body)
    secs, cur = [], None
    for p in parts:
        m = re.match(r"섹션 (\d+) ?: (.*?)\s*(?:\(\s*(\d+)\s*%\s*\))?\s*$", p.strip())
        if m and p.strip().startswith("섹션"):
            cur = {"section_no": int(m.group(1)), "section_name": m.group(2).strip(), "weight": int(m.group(3)) if m.group(3) else None, "bullets": []}
            secs.append(cur)
        elif cur and "●" in p:
            for t in p.split("●"):
                t = norm(t)
                if t:
                    cur["bullets"].append({"sha256": hashlib.sha256(t.encode()).hexdigest(), "chars": len(t)})
    return hashlib.sha256(raw).hexdigest(), secs


if __name__ == "__main__":
    out = {"extracted": "2026-11-12", "method": "한국어 공식 PDF 텍스트 추출(pypdf, 격리 폴더) — 원문은 저장하지 않고 bullet별 sha256만 보관(검토자가 PDF와 대조). 영문 최신본과 버전이 달라 1:1 매핑하지 않음.", "exams": {}}
    for ex, pdf in zip(("DE-A", "DE-P", "GEN-A"), sys.argv[1:4]):
        sha, secs = parse(pdf)
        out["exams"][ex] = {**META[ex], "guide_sha256": sha, "sections": secs, "bullet_count": sum(len(s["bullets"]) for s in secs)}
        print(ex, len(secs), out["exams"][ex]["bullet_count"], [(s["section_no"], len(s["bullets"])) for s in secs])
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
