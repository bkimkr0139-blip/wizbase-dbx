"""단독 설치형 exe 빌드: python tools/build_standalone.py

- 현재 저장소 파일의 content_id를 desktop/content_id.txt 로 기록해 exe에 포함(앱이 '내장 버전'을 식별).
- tensorflow/torch/cv2 등 불필요한 대형 패키지는 반드시 제외(미제외 시 600MB), duckdb 메타데이터 포함 필수.
- 결과: dist_app/release/WIZBASE-DBX-Standalone.exe
이후 화면·서버 코드만 바뀌면 이 빌드는 필요 없다(서버가 콘텐츠 팩을 자동 제공). 새 라이브러리 추가 등은
backend/sysinfo.py STANDALONE_COMPAT 와 desktop/dbx_standalone.py EXE_COMPAT 를 함께 올리고 이 스크립트를 다시 실행한다.
"""
import subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from backend import pack  # noqa: E402

(ROOT / "desktop" / "content_id.txt").write_text(pack.content_id(ROOT), encoding="utf-8")
EXCL = "tensorflow torch torchvision cv2 scipy pandas numpy pyarrow matplotlib sklearn IPython jupyter notebook PIL keras onnxruntime transformers sympy numba llvmlite h5py tkinter".split()
cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--windowed", "--name", "WIZBASE-DBX-Standalone", "--icon", str(ROOT / "desktop" / "app.ico"),
       "--distpath", str(ROOT / "dist_app" / "release"), "--workpath", str(ROOT / "build_sa"), "--specpath", str(ROOT / "build_sa"), "--paths", str(ROOT),
       "--collect-submodules", "backend", "--collect-submodules", "uvicorn", "--hidden-import", "duckdb", "--copy-metadata", "duckdb", "--hidden-import", "httptools", "--hidden-import", "websockets",
       "--add-data", f"{ROOT / 'static'};static", "--add-data", f"{ROOT / 'backend' / 'official_objectives.json'};backend", "--add-data", f"{ROOT / 'backend' / 'official_objectives_ko.json'};backend",
       "--add-data", f"{ROOT / 'adapter'};adapter", "--add-data", f"{ROOT / 'desktop' / 'content_id.txt'};."]
for m in EXCL:
    cmd += ["--exclude-module", m]
cmd.append(str(ROOT / "desktop" / "dbx_standalone.py"))
sys.exit(subprocess.call(cmd))
