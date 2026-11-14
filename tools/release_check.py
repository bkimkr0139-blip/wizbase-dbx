"""릴리스 점검: 코드가 바뀌면 변경 이력·HELP·AI 지원·시스템 문서가 함께 갱신됐는지 자동으로 확인한다.
사용: python tools/release_check.py            (직접 실행)
      git push 때 .githooks/pre-push 가 자동 실행 — 설치: python tools/release_check.py --install
우회(비상용): SKIP_RELEASE_CHECK=1 git push

점검 내용
1. 기능 코드(backend/*.py, static/*.js, adapter/*)가 원격보다 바뀌었는데 backend/sysinfo.py(변경 이력·문서)는 안 바뀌었으면 실패
2. VERSION·CHANGELOG 맨 위 버전·RELEASED 날짜의 일관성
3. 안내 누락 시험(오류 코드·메뉴·도구·환경변수·AI 질문·HELP 항목·시스템 문서) 통과 여부
"""
import os, re, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FEATURE = re.compile(r"^(backend/(?!sysinfo\.py)[^/]+\.py|static/[^/]+\.(js|html)|adapter/[^/]+)$")


def run(cmd, **kw):
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, **kw)


def changed_files():
    for base in ("origin/main", "main@{upstream}", "HEAD~1"):
        r = run(["git", "diff", "--name-only", f"{base}...HEAD"])
        if r.returncode == 0:
            return [x.strip() for x in r.stdout.splitlines() if x.strip()], base
    return [], None


def main():
    if "--install" in sys.argv:
        r = run(["git", "config", "core.hooksPath", ".githooks"])
        print("pre-push 훅 설치" + (" 완료(core.hooksPath=.githooks)" if r.returncode == 0 else " 실패: " + r.stderr))
        return r.returncode
    if os.environ.get("SKIP_RELEASE_CHECK") == "1":
        print("[release_check] SKIP_RELEASE_CHECK=1 — 점검을 건너뜁니다(비상용).")
        return 0
    errs = []
    files, base = changed_files()
    feat = [f for f in files if FEATURE.match(f)]
    if feat and "backend/sysinfo.py" not in files:
        errs.append(f"기능 코드가 바뀌었는데({len(feat)}개, 예: {feat[0]}) backend/sysinfo.py 의 변경 이력(CHANGELOG)·시스템 문서가 갱신되지 않았습니다. "
                    "CHANGELOG 에 항목을 추가하세요(HELP·AI 지원은 변경 이력·메뉴·시스템 문서를 자동으로 따라갑니다).")
    sys.path.insert(0, str(ROOT))
    os.environ.setdefault("DBX_NO_OPS_WARM", "1")
    from backend import sysinfo
    if sysinfo.CHANGELOG[0]["version"] != sysinfo.VERSION:
        errs.append(f"VERSION({sysinfo.VERSION}) 과 CHANGELOG 맨 위 버전({sysinfo.CHANGELOG[0]['version']})이 다릅니다.")
    if not sysinfo.CHANGELOG[0]["notes"]:
        errs.append("CHANGELOG 맨 위 항목에 notes 가 없습니다.")
    if sysinfo.RELEASED < sysinfo.CHANGELOG[0]["date"]:
        errs.append(f"RELEASED({sysinfo.RELEASED})가 CHANGELOG 맨 위 날짜({sysinfo.CHANGELOG[0]['date']})보다 이전입니다.")
    t = run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests/test_help_coverage.py", "tests/test_ax_help_coverage.py", "tests/test_auto_reflection.py"],
            env={**os.environ, "PYTHONIOENCODING": "utf-8", "DBX_NO_OPS_WARM": "1"})
    if t.returncode != 0:
        tail = "\n".join((t.stdout or "").splitlines()[-25:])
        errs.append("안내 누락 시험이 실패했습니다:\n" + tail)
    if errs:
        print("[release_check] 실패\n- " + "\n- ".join(errs))
        return 1
    print("[release_check] 통과 — 변경 이력·HELP·AI 지원·시스템 문서가 일관됩니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
