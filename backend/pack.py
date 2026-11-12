"""단독 설치형 앱용 '콘텐츠 팩' — 화면(static/**)과 서버 코드(backend/*.py·*.json)만 담은 작은 업데이트 파일.

exe를 다시 빌드하지 않고 팩을 내려받아 덮어쓰는 방식으로 단독형을 갱신한다. 팩은 운영 서버가 저장소 파일에서 즉석에 만들고(재빌드 불필요),
내용 식별자(content_id)는 파일 경로+내용 해시로 계산해 서버와 앱이 같은 값을 얻는다. 새 라이브러리·exe 껍데기 변경 등은 팩으로 불가(STANDALONE_COMPAT 변경 → exe 교체).
"""
from __future__ import annotations
import hashlib, io, json, zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXED_TIME = (2026, 1, 1, 0, 0, 0)


def collect(root: Path) -> dict:
    """팩에 포함되는 파일: static/** 와 backend/*.py·*.json (임시 파일 `_*`·__pycache__ 제외)."""
    out = {}
    for sub, pats in (("static", ("**/*",)), ("backend", ("*.py", "*.json"))):
        d = Path(root) / sub
        if not d.is_dir():
            continue
        for pat in pats:
            for f in d.glob(pat):
                if not f.is_file() or "__pycache__" in f.parts:
                    continue
                if f.name.startswith("_") and f.name != "__init__.py":
                    continue
                out[f.relative_to(root).as_posix()] = f
    return dict(sorted(out.items()))


def _digest(files: dict) -> dict:
    return {rel: hashlib.sha256(p.read_bytes()).hexdigest() for rel, p in files.items()}


def content_id_of(file_hashes: dict) -> str:
    h = hashlib.sha256()
    for rel in sorted(file_hashes):
        h.update(rel.encode("utf-8") + b"\0" + file_hashes[rel].encode() + b"\n")
    return h.hexdigest()[:16]


def content_id(root: Path) -> str:
    return content_id_of(_digest(collect(root)))


_CACHE: dict = {"sig": None, "val": None}


def build(version: str, compat: int, root: Path = ROOT):
    """(zip bytes, manifest) — 파일 시그니처가 같으면 캐시를 재사용한다."""
    files = collect(root)
    sig = (version, compat, tuple((r, p.stat().st_mtime_ns, p.stat().st_size) for r, p in files.items()))
    if _CACHE["sig"] == sig:
        return _CACHE["val"]
    hashes = _digest(files)
    cid = content_id_of(hashes)
    mf = {"content_id": cid, "version": version, "compat": compat, "files": hashes}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        zi = zipfile.ZipInfo("manifest.json", FIXED_TIME)
        z.writestr(zi, json.dumps(mf, ensure_ascii=False, sort_keys=True))
        for rel, p in files.items():
            zi = zipfile.ZipInfo(rel, FIXED_TIME)
            zi.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(zi, p.read_bytes())
    data = buf.getvalue()
    mf2 = dict(mf, size=len(data), sha256=hashlib.sha256(data).hexdigest())
    _CACHE.update(sig=sig, val=(data, mf2))
    return data, mf2


def extract_verified(zip_path: Path, dest: Path, expect_id: str, expect_compat: int):
    """팩 zip을 dest에 풀고 경로 이탈·해시·content_id·compat를 검증한다. 문제가 있으면 ValueError."""
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    base = dest.resolve()
    with zipfile.ZipFile(zip_path) as z:
        names = z.namelist()
        if "manifest.json" not in names:
            raise ValueError("manifest.json 없음")
        mf = json.loads(z.read("manifest.json").decode("utf-8"))
        if int(mf.get("compat", -1)) != int(expect_compat):
            raise ValueError("호환되지 않는 팩(앱 전체 업데이트가 필요합니다)")
        for n in names:
            if n == "manifest.json":
                continue
            t = (base / n).resolve()
            if base not in t.parents or n not in mf["files"]:
                raise ValueError(f"허용되지 않는 파일: {n}")
        for rel, hx in mf["files"].items():
            data = z.read(rel)
            if hashlib.sha256(data).hexdigest() != hx:
                raise ValueError(f"파일 해시 불일치: {rel}")
            t = base / rel
            t.parent.mkdir(parents=True, exist_ok=True)
            t.write_bytes(data)
        (base / "manifest.json").write_text(json.dumps(mf, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    if content_id_of(mf["files"]) != mf["content_id"] or mf["content_id"] != expect_id:
        raise ValueError("content_id 불일치")
    return mf


def verify_dir(d: Path, expect_compat: int):
    """이미 풀려 있는 팩(overlay/current)이 온전한지 확인하고 manifest를 돌려준다. 아니면 ValueError."""
    d = Path(d)
    mf = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
    if int(mf.get("compat", -1)) != int(expect_compat):
        raise ValueError("compat 불일치")
    if content_id(d) != mf["content_id"]:
        raise ValueError("팩 파일이 변경되었거나 손상됨")
    return mf
