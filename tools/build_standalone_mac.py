"""macOS 단독 설치형 빌드(반드시 Mac에서 실행): python tools/build_standalone_mac.py

결과: dist_app/release/WIZBASE-DBX-Standalone-mac-<arm64|x64>.zip  (안에 'WIZBASE DBX Rehearsal.app')
- Apple Silicon(M1~)과 Intel Mac은 각각 그 CPU의 Mac에서 빌드해야 한다(GitHub Actions 워크플로: .github/workflows/build-standalone-mac.yml).
- 사전 설치: python3 -m pip install -r requirements.txt pywebview pyinstaller
- 코드 서명·공증이 없으므로 내려받은 앱은 Gatekeeper가 막는다 → 사용자는 앱을 우클릭 > 열기 하거나 `xattr -dr com.apple.quarantine "WIZBASE DBX Rehearsal.app"`.
- 빌드 후 화면·서버 코드 변경은 재빌드 없이 서버의 콘텐츠 팩으로 갱신된다(Windows와 동일).
"""
import platform, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from backend import pack  # noqa: E402

arch = "arm64" if platform.machine() == "arm64" else "x64"
(ROOT / "desktop" / "content_id.txt").write_text(pack.content_id(ROOT), encoding="utf-8")
EXCL = "tensorflow torch torchvision cv2 scipy pandas numpy pyarrow matplotlib sklearn IPython jupyter notebook PIL keras onnxruntime transformers sympy numba llvmlite h5py tkinter".split()
dist = ROOT / "dist_mac"
cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--windowed", "--name", "WIZBASE DBX Rehearsal", "--icon", str(ROOT / "desktop" / "app.icns"),
       "--osx-bundle-identifier", "kr.ai.wizbase.dbx.rehearsal", "--distpath", str(dist), "--workpath", str(ROOT / "build_mac"), "--specpath", str(ROOT / "build_mac"), "--paths", str(ROOT),
       "--collect-submodules", "backend", "--collect-submodules", "uvicorn", "--hidden-import", "duckdb", "--copy-metadata", "duckdb", "--hidden-import", "httptools", "--hidden-import", "websockets",
       "--add-data", f"{ROOT / 'static'}:static", "--add-data", f"{ROOT / 'backend' / 'official_objectives.json'}:backend", "--add-data", f"{ROOT / 'backend' / 'official_objectives_ko.json'}:backend",
       "--add-data", f"{ROOT / 'adapter'}:adapter", "--add-data", f"{ROOT / 'desktop' / 'content_id.txt'}:."]
for m in EXCL:
    cmd += ["--exclude-module", m]
cmd.append(str(ROOT / "desktop" / "dbx_standalone.py"))
rc = subprocess.call(cmd)
if rc:
    sys.exit(rc)
out = ROOT / "dist_app" / "release"
out.mkdir(parents=True, exist_ok=True)
z = out / f"WIZBASE-DBX-Standalone-mac-{arch}.zip"
subprocess.check_call(["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", str(dist / "WIZBASE DBX Rehearsal.app"), str(z)])
print("OK:", z)
