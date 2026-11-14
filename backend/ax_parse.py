"""비정형 문서 파서(AX-07 사전작업): txt/md/csv/json/html/docx/pdf → 텍스트(+페이지 표지) + 파싱 보고서.
- 모든 입력은 데이터다. 실행·매크로·스크립트는 실행하지 않고, 크기·압축 해제 크기·행 수를 제한한다.
- 못 읽는 것(스캔 PDF의 이미지 글자, 암호화 문서)은 조용히 비우지 않고 경고로 알린다(OCR 미지원)."""
from __future__ import annotations
import csv, io, json, os, re, zipfile
from html.parser import HTMLParser
from pathlib import Path

from .core import ApiError

MAX_BYTES = 5 * 1024 * 1024
MAX_CHARS = 200_000
EXT = {".txt", ".md", ".csv", ".json", ".html", ".htm", ".docx", ".pdf"}
BLOCK_MAGIC = (b"MZ", b"\x7fELF", b"#!")           # 실행 파일·스크립트는 거부


class _H(HTMLParser):
    def __init__(self):
        super().__init__()
        self.out, self.skip = [], 0

    def handle_starttag(self, t, a):
        if t in ("script", "style", "noscript"):
            self.skip += 1
        if t in ("p", "br", "div", "li", "tr", "h1", "h2", "h3", "h4", "table"):
            self.out.append("\n\n" if t in ("p", "div", "h1", "h2", "h3", "h4", "table") else "\n")

    def handle_endtag(self, t):
        if t in ("script", "style", "noscript") and self.skip:
            self.skip -= 1

    def handle_data(self, d):
        if not self.skip and d.strip():
            self.out.append(d.strip() + " ")


def _decode(b):
    for enc in ("utf-8-sig", "cp949", "utf-16"):
        try:
            return b.decode(enc), enc
        except Exception:
            continue
    return b.decode("utf-8", "replace"), "utf-8(replace)"


def parse_bytes(name, data):
    """→ (text, report). 실패는 ApiError."""
    ext = Path(name).suffix.lower()
    if ext not in EXT:
        raise ApiError(400, "UNSUPPORTED_FILE", f"지원 형식: {', '.join(sorted(EXT))}")
    if len(data) > MAX_BYTES:
        raise ApiError(400, "FILE_TOO_LARGE", f"파일은 {MAX_BYTES // 1024 // 1024}MB 이하만 받습니다.")
    if any(data.startswith(m) for m in BLOCK_MAGIC):
        raise ApiError(400, "EXECUTABLE_REJECTED", "실행 파일·스크립트로 보이는 내용은 받지 않습니다.")
    rep = {"file": os.path.basename(name), "ext": ext, "bytes": len(data), "parser": None, "pages": None, "warnings": []}
    if ext in (".txt", ".md"):
        text, enc = _decode(data)
        rep.update(parser="text", encoding=enc)
    elif ext == ".json":
        text, enc = _decode(data)
        try:
            text = json.dumps(json.loads(text), ensure_ascii=False, indent=1)
        except Exception:
            rep["warnings"].append("JSON 형식 오류 — 원문 텍스트로 처리")
        rep.update(parser="json", encoding=enc)
    elif ext == ".csv":
        raw, enc = _decode(data)
        rows = list(csv.reader(io.StringIO(raw)))
        if not rows:
            raise ApiError(400, "EMPTY_DOC", "빈 CSV 입니다.")
        head, body = rows[0], rows[1:501]
        text = "\n\n".join(", ".join(f"{h}: {v}" for h, v in zip(head, r)) for r in body)
        if len(rows) > 501:
            rep["warnings"].append(f"행 {len(rows) - 1}개 중 500개만 사용")
        rep.update(parser="csv", encoding=enc, rows=len(rows) - 1, columns=head)
    elif ext in (".html", ".htm"):
        raw, enc = _decode(data)
        h = _H()
        h.feed(raw)
        text = re.sub(r"\n{3,}", "\n\n", "".join(h.out)).strip()
        rep.update(parser="html(script/style 제거)", encoding=enc)
    elif ext == ".docx":
        try:
            z = zipfile.ZipFile(io.BytesIO(data))
        except Exception:
            raise ApiError(400, "BAD_DOCX", "docx 형식이 아닙니다.")
        if sum(i.file_size for i in z.infolist()) > 40 * 1024 * 1024:
            raise ApiError(400, "ZIP_TOO_LARGE", "압축 해제 크기가 너무 큽니다(zip bomb 방지).")
        if "word/document.xml" not in z.namelist():
            raise ApiError(400, "BAD_DOCX", "word/document.xml 이 없습니다.")
        xml = z.read("word/document.xml").decode("utf-8", "replace")
        xml = re.sub(r"</w:p>", "\n\n", xml)
        xml = re.sub(r"<w:tab/>|<w:br/>", " ", xml)
        text = re.sub(r"<[^>]+>", "", xml)
        text = (text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"').replace("&apos;", "'"))
        if any(n.startswith("word/vbaProject") for n in z.namelist()):
            rep["warnings"].append("매크로(vbaProject)가 있으나 실행하지 않았고 내용에서도 제외")
        rep["parser"] = "docx(텍스트·단락만, 표·이미지 서식은 단순화)"
    else:  # pdf
        try:
            from pypdf import PdfReader
        except Exception:
            raise ApiError(501, "PDF_PARSER_MISSING", "pypdf 가 설치되어 있지 않아 PDF 를 읽을 수 없습니다(pip install pypdf).")
        try:
            r = PdfReader(io.BytesIO(data))
            if r.is_encrypted:
                raise ApiError(400, "PDF_ENCRYPTED", "암호화된 PDF 는 읽지 않습니다.")
            parts, empty = [], 0
            for i, pg in enumerate(r.pages[:300], 1):
                t = (pg.extract_text() or "").strip()
                if not t:
                    empty += 1
                parts.append(f"--- page {i} ---\n\n{t}")
            text = "\n\n".join(parts)
            rep.update(parser="pypdf(텍스트 추출)", pages=len(r.pages))
            if len(r.pages) > 300:
                rep["warnings"].append("300쪽까지만 사용")
            if empty:
                rep["warnings"].append(f"텍스트가 없는 쪽 {empty}개 — 스캔 이미지일 수 있으며 OCR 은 지원하지 않습니다")
        except ApiError:
            raise
        except Exception as e:
            raise ApiError(400, "BAD_PDF", f"PDF 를 읽지 못했습니다({type(e).__name__}).")
    text = text.replace("\x00", "").strip()
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS]
        rep["warnings"].append(f"{MAX_CHARS}자까지만 사용")
    if len(text) < 10:
        raise ApiError(400, "EMPTY_DOC", "추출된 텍스트가 거의 없습니다(스캔 이미지·빈 문서 가능). 파싱을 중단합니다.")
    rep["chars"] = len(text)
    return text, rep


def allowed_dirs():
    return [Path(p).resolve() for p in os.environ.get("WZ_AX_DOC_DIRS", "").split(os.pathsep) if p.strip()]


def list_folder(path):
    """허용 폴더(WZ_AX_DOC_DIRS) 안의 파일만. 심볼릭 링크·상위 경로 이탈 거부."""
    dirs = allowed_dirs()
    if not dirs:
        raise ApiError(403, "FOLDER_SOURCE_DISABLED", "폴더 소스는 서버 환경변수 WZ_AX_DOC_DIRS(허용 폴더)가 설정된 경우에만 쓸 수 있습니다.")
    p = Path(path).resolve()
    if not any(p == d or d in p.parents for d in dirs):
        raise ApiError(403, "FOLDER_NOT_ALLOWED", "허용된 폴더 밖입니다.")
    if not p.is_dir():
        raise ApiError(404, "FOLDER_NOT_FOUND", "폴더가 없습니다.")
    out = []
    for f in sorted(p.rglob("*")):
        if len(out) >= 200:
            break
        if f.is_file() and not f.is_symlink() and f.suffix.lower() in EXT and (f.resolve() == f or any(d in f.resolve().parents for d in dirs)):
            out.append(f)
    return out
