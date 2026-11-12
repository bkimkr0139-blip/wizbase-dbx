"""시스템 정보·버전·업데이트 확인·시스템문서.md·검토자 매뉴얼 생성. 메뉴(리본) 구성의 단일 원천(MENU)을 여기서 관리한다."""
from __future__ import annotations
import hashlib, os, platform, time
from pathlib import Path

from . import core, labs, pack, transfer, v11

ROOT = Path(__file__).resolve().parent.parent
VERSION = "0.4.4"
RELEASED = "2026-11-12"
SHELL_VERSION = "0.1.1"  # PC 앱(desktop/dbx_app.py APP_VERSION)의 최신 버전 — 새 exe를 배포할 때 함께 올린다
APP_FILE = ROOT / "dist_app" / "release" / "WIZBASE-DBX-Rehearsal.exe"
VERSION_POLICY = ("버전 규칙(MAJOR.MINOR.PATCH): 정식 서비스 전에는 MAJOR=0. 버그 수정은 어떤 자리도 올리지 않는다. 소규모 기능 추가는 PATCH(마지막 숫자), "
                  "주요 개선은 MINOR(가운데 숫자)를 올린다. 정식 서비스 전환은 운영자(WIZBASE)가 판단해 MAJOR를 1로 올린다(자동으로 올리지 않음). 현재 0.4.2이며 다음 기능 추가는 0.4.3. "
                  "PC 앱(exe)은 앱 자체가 바뀔 때만 별도 버전(SHELL_VERSION)을 올린다.")
STANDALONE_COMPAT = 1  # 팩으로 갱신 가능한 범위의 호환 번호 — 새 라이브러리 추가·앱 껍데기 변경 등 팩으로 불가능한 변경 시 올리고 exe를 다시 빌드한다
STANDALONE_FILE = ROOT / "dist_app" / "release" / "WIZBASE-DBX-Standalone.exe"
MAC_FILES = {"mac_arm64": ROOT / "dist_app" / "release" / "WIZBASE-DBX-Standalone-mac-arm64.zip", "mac_x64": ROOT / "dist_app" / "release" / "WIZBASE-DBX-Standalone-mac-x64.zip"}
STARTED = time.time()
_SHA: dict = {}
_CENTRAL: dict = {"t": 0.0, "v": None}


def standalone():
    return os.environ.get("DBX_STANDALONE") == "1"


def _sha(p):
    st = (p.stat().st_mtime, p.stat().st_size)
    if _SHA.get(str(p), (None,))[0] != st:
        _SHA[str(p)] = (st, hashlib.sha256(p.read_bytes()).hexdigest())
    return _SHA[str(p)][1]


def central_manifest():
    """단독형: 운영자 서버의 최신 배포 정보(10분 캐시, 실패 시 None=오프라인)."""
    if time.time() - _CENTRAL["t"] < 600:
        return _CENTRAL["v"]
    try:
        import json as _j, urllib.request
        with urllib.request.urlopen(urllib.request.Request(os.environ.get("DBX_CENTRAL_URL", "https://dbx.wizbase.ai.kr").rstrip("/") + "/api/app/manifest", headers={"User-Agent": "DBXDesktop-Standalone"}), timeout=4) as r:
            v = _j.loads(r.read().decode("utf-8"))
    except Exception:
        v = None
    _CENTRAL.update(t=time.time() if v else time.time() - 540, v=v)
    return v
PURPOSE = ("WIZBASE(Databricks 파트너)의 실제 PoC 준비와 파트너 레벨 상향을 위한 인증 시험 준비를 지원하는 교육·훈련 환경. "
           "Databricks 공식 제품·교육·시험이 아니며 합격·자격·투입을 보증하지 않음.")
CHANGELOG = [
    {"version": "0.4.4", "date": "2026-11-12", "notes": ["단독 설치형 '콘텐츠 팩' 업데이트 — 화면·서버 코드 변경은 exe 재빌드 없이 작은 파일(수백 KB)로 내려받아 적용(SHA-256·파일별 해시 검증, 문제 시 자동 복구)",
                                                      "macOS 단독 설치형 앱 추가(Apple Silicon·Intel, .app) — 빌드는 Mac 또는 GitHub Actions에서 수행", "UI-01 기준 프로필을 읽기 쉬운 표로 표시"]},
    {"version": "0.4.3", "date": "2026-11-12", "notes": ["Windows 단독 설치형 앱 추가 — 서버·데이터베이스가 앱 안에 포함되어 내 PC에서 단독 실행(인터넷·운영자 PC 없이 학습 가능, 학습 데이터는 내 PC에만 저장)",
                                                      "단독형 업데이트: 운영자 서버에 새 설치 파일이 있으면 알림 → 선택 시 내려받아(SHA-256 검증) 교체, 학습 데이터 유지", "단독형 AXOS 피드백: 인터넷 연결 시 운영자 개발큐로 전달·처리 상태 반영(오프라인이면 보류 후 자동 전송)",
                                                      "AI 지원 채팅창을 열면 처음부터 보이도록 스크롤 개선"]},
    {"version": "0.4.2", "date": "2026-11-12", "notes": ["로그인 이름(실명) 필수, 세션 목록에 사용자명·생성 일시·최종 작업 일시 표시", "Windows 앱 1.1.0(최종 개발 상태 재빌드) 배포", "시스템 문서 갱신", "버전 규칙 도입: 정식 서비스 전은 0.y.z — 버그 수정은 버전 유지, 소규모 기능 추가는 z, 주요 개선은 y, 정식 전환은 운영자 판단으로 1.0.0"]},
    {"version": "0.4.1", "date": "2026-11-12", "notes": ["admin 전용 접근 코드 분리(staff·instructor 코드와 별개) — 피드백·개발큐·시스템 문서·전체 세션 삭제는 admin 고유 범위", "admin은 검토·강사 기능 전체 사용 가능", "UI-01 세션 선택 삭제(본인 것, admin은 전체)", "우측 탭·패널 레이아웃 개선"]},
    {"version": "0.4.0", "date": "2026-11-12", "notes": ["우측 AXOS 탭: 기능 화면별 피드백(텍스트+이미지 다중 첨부) 제출 → 검토·승인 → 개발큐 → 개발중 → 반영완료 폐루프, 제출자는 진행 상태 확인",
                                                      "피드백 관리·개발큐(개발 지시서 자동 생성, 개발큐.md 내려받기)는 admin(수퍼유저) 전용", "전이 산업 도메인 신청도 AXOS로 접수해 개발큐에서 관리(이메일 전송 없음)",
                                                      "시스템 문서는 admin(수퍼유저)만 열람·다운로드", "우측 탭 버튼 크기 50% 축소"]},
    {"version": "0.3.0", "date": "2026-11-12", "notes": ["전역 메뉴를 Windows 표준 앱 방식의 메뉴 바(드롭다운 목록)로 변경, 핫키(F10·Alt+숫자·Alt+Shift+문자) 추가", "시스템 정보·업데이트·시스템문서.md를 도움말 메뉴로 이동", "Windows PC 앱(.exe) 제공 — 시작 화면에서 내려받기, 사이트 업데이트 시 앱에서 적용 여부 알림(시스템 문서 미포함)"]},
    {"version": "0.2.0", "date": "2026-11-12", "notes": ["상단 리본 메뉴(전역 메뉴) 도입, 우측 시스템 정보·업데이트·시스템문서 다운로드", "전이 산업 시드 3종(제조 IoT·클릭스트림·문서 RAG)", "협업 훈련(DBA·DE·AX·리뷰어) 전용 흐름",
                                                      "한국어 공식 가이드 3종 적재(해시 기준) + 영문 대비 차이표", "검토 센터와 검토자 매뉴얼(컨설턴트 자체 검토용)", "dbx.wizbase.ai.kr HTTPS 적용"]},
    {"version": "0.1.1", "date": "2026-11-12", "notes": ["공식 목표 bullet 134개, 문항 66개, 실습 팩 21개, SQL UPDATE/DELETE/MERGE, CDC 재생, Git 훈련, 시드 v1~v3, 프로젝트 트랙, 현장 대조표, 거버넌스"]},
    {"version": "0.1.0", "date": "2026-11-11", "notes": ["지시서 v1.1 기본 구현(UI-01~25, AT-01~42)"]},
]
# (탭, 아이콘 키, [(view, 라벨, 설명)])
MENU = [
    ("홈", "home", [("env", "환경 점검", "클라우드·리전·프로필·세션 시작, 기능 매니페스트"), ("req", "착수·요구", "인터뷰 카드·데이터 계약 검토")]),
    ("워크스페이스", "ws", [("ws", "Workspace", "폴더·객체 탐색"), ("cat", "Catalog", "Unity Catalog 탐색"), ("sql", "SQL Editor", "DuckDB 기반 SQL(권한·MODIFY 포함)"),
                       ("nb", "Notebook", "로컬 코드 실습"), ("comp", "Compute", "Warehouse 시작/중지")]),
    ("데이터 구축", "pipe", [("conn", "수집", "Connections"), ("pipe", "Pipelines", "파이프라인"), ("cdc", "CDC 재생", "중복·역순·삭제 재생"), ("jobs", "Jobs", "Job/repair"),
                        ("genie", "Genie", "의미모델"), ("agent", "Agent", "승인 흐름"), ("trace", "Tracing", "평가"), ("bundle", "Git/Bundle", "branch·PR·배포"), ("perm", "권한", "GRANT/관리")]),
    ("훈련·시연", "train", [("track", "프로젝트 트랙", "8주 훈련"), ("demo", "고객 시연", "20분 시연·Q&A"), ("xfer", "전이 시드·협업", "제조 IoT·클릭스트림·RAG 시드, 4역할 협업")]),
    ("인증 준비", "cert", [("prof", "역량·등급", "내부 등급"), ("plan", "학습계획", "목표 기반 계획"), ("map", "공식 목표", "목표 지도"), ("ko", "한국어 가이드", "한국어 공식 가이드 대조"),
                       ("tutor", "AI 튜터", "근거 기반 답변"), ("exam", "시험센터", "문항·모의시험"), ("lab", "실습 증거함", "21개 실습 팩 증거"), ("qual", "콘텐츠 품질", "문항 검수 상태")]),
    ("검토·운영", "review", [("rvw", "검토 센터", "컨설턴트 자체 검토 큐·매뉴얼"), ("fbq", "피드백·개발큐", "AXOS 피드백 관리·개발큐(admin 전용)"), ("vmx", "현장 대조표", "V1~V6"), ("conf", "자료 충돌", "공식 자료 상충"),
                        ("partner", "파트너 인력", "인력·승인"), ("inst", "강사·수료", "수료 판정"), ("evid", "증거 보고서", "증거 요약")]),
]


def build_id():
    h = hashlib.sha256(VERSION.encode())
    for d, pat in (("static", "*"), ("backend", "*.py")):
        for f in sorted((ROOT / d).glob(pat)):
            if f.is_file():
                h.update(f.read_bytes())
    return h.hexdigest()[:12]


def counts():
    V = v11.V
    st = {}
    for i in V["items"].values():
        st[i["status"]] = st.get(i["status"], 0) + 1
    return {"labs": len(labs.LABS), "items": len(V["items"]), "item_status": st, "objectives": len(V["objectives"]), "features": len(core.FEATURES), "transfer_seeds": len(transfer.SEEDS)}


def info():
    return {"name": "WIZBASE DBX Project Rehearsal", "version": VERSION, "released": RELEASED, "build": build_id(), "python": platform.python_version(), "uptime_sec": int(time.time() - STARTED),
            "counts": counts(), "standalone": standalone(), "data_dir": os.environ.get("DBX_DATA_DIR", "") if standalone() else "", "purpose": PURPOSE, "version_policy": VERSION_POLICY, "changelog": CHANGELOG,
            "menu": [{"tab": t, "icon": i, "items": [{"view": v, "label": l, "desc": d} for v, l, d in its]} for t, i, its in MENU]}


def app_manifest():
    ok = APP_FILE.is_file()
    sa = STANDALONE_FILE.is_file()
    return {"shell_version": SHELL_VERSION, "available": ok, "size": APP_FILE.stat().st_size if ok else 0, "filename": APP_FILE.name,
            "sha256": _sha(APP_FILE) if ok else "", "download": "/download/app", "server_version": VERSION, "server_build": build_id(),
            "standalone": {"available": sa, "version": VERSION, "size": STANDALONE_FILE.stat().st_size if sa else 0, "filename": STANDALONE_FILE.name,
                           "sha256": _sha(STANDALONE_FILE) if sa else "", "download": "/download/standalone", "compat": STANDALONE_COMPAT},
            "pack": pack_info(), **{k: {"available": f.is_file(), "version": VERSION, "size": f.stat().st_size if f.is_file() else 0, "filename": f.name, "sha256": _sha(f) if f.is_file() else "",
                                        "download": "/download/standalone-" + k.replace("_", "-"), "compat": STANDALONE_COMPAT} for k, f in MAC_FILES.items()}}


def pack_info():
    """콘텐츠 팩(화면+서버 코드 업데이트 파일) 정보 — 저장소 파일에서 즉석 생성되므로 재빌드 없이 최신 상태가 반영된다."""
    if standalone():
        return {"available": False}
    data, mf = pack.build(VERSION, STANDALONE_COMPAT, ROOT)
    return {"available": True, "content_id": mf["content_id"], "version": VERSION, "size": mf["size"], "sha256": mf["sha256"], "compat": STANDALONE_COMPAT, "download": "/download/pack"}


def update_check(client_build):
    cur = build_id()
    if standalone():  # 단독형: 화면 자산은 앱에 포함 — 갱신은 운영자 서버의 새 설치 파일 유무로 판단
        rm = central_manifest()
        sa = (rm or {}).get("standalone" if os.environ.get("DBX_PLATFORM", "win") == "win" else os.environ["DBX_PLATFORM"]) or {}   # 내 플랫폼의 설치 파일 항목
        pk = (rm or {}).get("pack") or {}
        mine_compat = int(os.environ.get("DBX_EXE_COMPAT", "0") or 0)
        cur = os.environ.get("DBX_CONTENT_ID", "")
        kind, size, latest = "", 0, ""
        if rm and sa.get("available") and mine_compat and int(sa.get("compat", 0)) != mine_compat:
            kind, size, latest = "exe", sa.get("size", 0), sa.get("version", "")      # 앱 자체(exe) 교체가 필요한 변경
        elif rm and pk.get("available") and pk.get("content_id") != cur and int(pk.get("compat", 0)) == mine_compat:
            kind, size, latest = "pack", pk.get("size", 0), pk.get("version", "")     # 화면·서버 코드만 교체(작은 파일)
        elif rm and not mine_compat and sa.get("available") and sa.get("sha256") != os.environ.get("DBX_EXE_SHA", "~"):
            kind, size, latest = "exe", sa.get("size", 0), sa.get("version", "")      # 구형 앱(호환 정보 없음)은 전체 교체
        app = {"shell_version": VERSION, "standalone": True, "offline": rm is None, "latest_version": latest, "update_available": bool(kind), "kind": kind, "size": size}
        return {"server_version": VERSION, "server_build": cur, "client_build": client_build, "update_available": False, "changelog": CHANGELOG[:3], "app": app,
                "how": "단독 설치형은 운영자 서버에 새 설치 파일이 올라오면 알림을 표시하고, 선택하면 내려받아 교체합니다(내 학습 데이터는 유지)."}
    return {"server_version": VERSION, "server_build": cur, "client_build": client_build, "update_available": bool(client_build) and client_build != cur, "changelog": CHANGELOG[:3], "app": app_manifest(),
            "how": "서버 코드가 갱신되면 화면을 새로 불러와 최신 화면 자산을 적용합니다. 서버 코드 자체의 배포는 운영자가 파일 반영 후 서버를 재시작합니다."}


def system_document():
    c = counts()
    L = ["# WIZBASE DBX Project Rehearsal — 시스템 문서", "", f"- 버전: **{VERSION}** (릴리스 {RELEASED}, 빌드 `{build_id()}`, PC 앱 {SHELL_VERSION}) — 정식 서비스 전(0.y.z)", f"- {VERSION_POLICY}", "- 목적: " + PURPOSE, "",
         "## 1. 한눈에 보기", "",
         "WIZBASE 컨설턴트가 Databricks 데이터 엔지니어링·생성형 AI 업무와 공식 인증 시험(DE-A·DE-P·GEN-A)을 준비하도록, **합성 데이터 기반 Workspace 시뮬레이터**에서 실습·평가·증거 수집·검토를 한 곳에서 수행하는 웹 시스템입니다.", "",
         "| 구분 | 현황 |", "|---|---|", f"| 공식 목표(objective) | {c['objectives']}개(영문 가이드 기준 + 한국어 가이드 대조) |", f"| 문항 | {c['items']}개, 상태 {c['item_status']} (AI 초안은 인간 검수 전) |",
         f"| 실습 팩 | {c['labs']}개(자동 대조 4·CLI 1·수동 16) |", f"| 기능 매니페스트 | {c['features']}개 |", f"| 전이 산업 시드 | {c['transfer_seeds']}종 |", "",
         "## 2. 화면 구성(특징)", "",
         "- **상단 메뉴 바**: Windows 표준 앱처럼 메뉴 제목을 누르면 아래로 항목 목록(드롭다운)이 펼쳐지는 전역 메뉴(홈·워크스페이스·데이터 구축·훈련·시연·인증 준비·검토·운영·도움말).",
         "- **핫키**: F10(메뉴 바 활성화), Alt+1~7(메뉴 열기), ↑↓←→·숫자·Enter·Esc(메뉴 조작), F1(사용 안내), Alt+Shift+A/U/I/K/D(AI 지원·업데이트·시스템 정보·단축키 안내·시스템문서).",
         "- **도움말 메뉴**: 사용 안내, AI 지원, 단축키 안내, 업데이트 확인, 시스템 정보(버전), Windows 앱 다운로드, 시스템문서(.md) 다운로드(**admin 수퍼유저에게만 표시**). 메뉴 바 오른쪽 끝에 버전을 표시.",
         "- **우측 탭(HELP·AI 지원·AXOS)**: 작은 세로 탭 3개. AXOS 탭에서 현재 화면에 대한 피드백(텍스트+이미지)·전이 도메인 신청·내 피드백 진행 상태를 확인.",
         "- **Windows PC 앱**: 시작 화면에서 내려받는 설치용 exe. 사이트를 PC 창으로 열고, 사이트·앱이 갱신되면 적용 여부를 알림. 일반 사용자용 앱에는 시스템 문서를 포함하지 않음.",
         "- **본문**: 선택한 화면. **우측 탭**: HELP(화면별 설명)·AI 지원(절차 안내). **하단**: 실행 로그·오류·증거 수준.",
         "- **상태 표기**: 모든 결과에 증거 수준(LOCAL_EXECUTED/SIMULATED 등)과 '확인대기·초안' 상태를 구분해 표시하며 모의 결과를 실제 Databricks 검증으로 주장하지 않음.", "", "### 메뉴 상세", ""]
    for t, _, its in MENU:
        L += [f"**{t}**", "", "| 메뉴 | 설명 |", "|---|---|"] + [f"| {l} | {d} |" for _, l, d in its] + [""]
    L += ["## 3. 핵심 기능과 특징", "",
          "1. **Workspace 시뮬레이터**: 식자재 주문 합성 데이터(거래처 30·상품 100·주문 300·주문행 900)를 DuckDB에 세션별로 격리 배치. SQL(SELECT/UPDATE/DELETE/MERGE)·권한·Notebook·Pipelines·Jobs·CDC·Git 훈련·Genie/Agent 승인 흐름을 모의. 시드 v1~v3로 정답 암기 방지.",
          "2. **실습 팩 21개**: 학습자 PC의 adapter가 실제 Databricks에서 실행한 결과를 증거(해시·버전)로 제출하거나, 수동 팩은 산출물 해시+루브릭(70점)+검토자 승인.",
          "3. **공식 목표·문항**: 공식 가이드 PDF(영문 3종, 한국어 3종)에서 bullet 단위로 적재(원문 sha256만 보관). 문항은 목표에 연결, 정답 위치 편향 제거, 검수 2단계(기술·출제) 후에만 ACTIVE.",
          "4. **전이 산업 시드·협업 훈련**: 제조 IoT·클릭스트림·문서 RAG 합성 CSV와 정답표(직원 전용), DBA→DE→AX→리뷰어 4역할 인계·상호 승인 흐름.",
          "5. **검토 센터**: 위즈베이스 DB 컨설턴트(검토자)가 매뉴얼에 따라 실제 워크스페이스에서 스스로 대조하고 결과를 기록. 목표 대조·문항 검수·기능 재확인·현장 대조표를 한 화면에서 진행.",
          "6. **세션 관리(UI-01)**: 세션 목록에 사용자명·사용자 ID(admin)·생성 일시·최종 작업 일시(KST)를 표시. 본인 세션은 선택 삭제 가능, admin은 전체 세션 선택 삭제(삭제 전 확인, 되돌릴 수 없음, 감사 로그 기록). 로그인 시 **이름(실명) 입력 필수**(2자 이상, '학습자' 등 기본값 불가). **세션 소유자는 이름이 아니라 로그인마다 새로 발급되는 사용자 ID**이므로 이름이 같아도 세션은 공유·연결되지 않으며(웹↔단독형, 웹 재로그인 포함), 로그아웃·재로그인하거나 브라우저·PC를 바꾸면 이전 세션은 '내 세션'에 보이지 않는다(비밀번호가 없어 이름만으로 연결하면 타인이 기록을 볼 수 있기 때문). 이어 쓰려면 로그아웃하지 않고 같은 브라우저를 사용한다.",
          "6-1. **AXOS 피드백 폐루프**: 사용자는 우측 AXOS 탭에서 기능 추가·화면 버그·기능 개선·DBX 불일치 오류·문항/자료 오류·기타를 제출(텍스트 + PNG/JPEG/GIF/WEBP 최대 5장·장당 3MB, 붙여넣기·끌어놓기 지원). 화면·버전·빌드·클라이언트(웹/PC 앱)가 자동 첨부됨. 상태: 접수 → 검토·승인 → 개발큐 → 개발중 → 반영완료(반려·보류는 사유 필수, 제출자에게 표시). 개발큐로 옮기면 **개발 지시서**(대상 화면·후보 파일·완료 기준)가 자동 생성되고 `개발큐.md`로 내려받아 개발 입력으로 사용. 반영완료 시 반영 버전을 기록하고 제출자에게 알림. **관리(전이·이미지 열람·큐)는 admin만**, 제출자는 본인 건의 상태만 조회. 개발 자체는 자동 실행이 아니라 개발큐를 입력으로 운영자가 수행.",
          "7. **전이 도메인 신청**: 원하는 산업 도메인(목적·필요 데이터·심어 둘 문제·희망 시기)을 AXOS 탭에서 신청하면 다른 피드백과 같은 폐루프(접수 → 검토·승인 → 개발큐 → 개발중 → 반영완료)로 관리되며 이메일은 보내지 않음. 합성 데이터 요청만 받음.",
          f"8. **설치형 앱(Windows·macOS)**: ① **단독 설치형(권장, Windows .exe / macOS .app)** — 서버(FastAPI)와 DuckDB가 앱 안에 포함되어 내 PC(127.0.0.1)에서만 실행. 학습 데이터는 `%LOCALAPPDATA%\\WIZBASE\\DBXRehearsal-Standalone\\data`에 저장되며 인터넷·운영자 PC가 없어도 학습 가능. 인터넷이 연결되면 업데이트 확인(알림 → 선택 시 적용, 데이터 유지)과 AXOS 피드백 전달(운영자 개발큐 접수·처리 상태 반영, 오프라인이면 보류 후 자동 전송)이 이루어짐. **업데이트는 두 종류**: (가) **콘텐츠 팩**(화면·서버 코드 변경, 수백 KB, 재빌드 불필요 — 운영 서버가 저장소 파일에서 즉석 생성, 앱이 내려받아 SHA-256과 파일별 해시를 검증해 `overlay/current`에 두고 자동 재시작, 새 팩이 서버를 못 띄우면 자동으로 폐기하고 내장 버전으로 복구), (나) **앱 전체 교체**(새 라이브러리·앱 껍데기 변경 시 `STANDALONE_COMPAT`가 바뀐 경우: Windows는 내려받아 SHA-256 검증 후 교체, macOS는 새 .app 다운로드 후 사용자가 교체). macOS 앱은 Apple Silicon·Intel 별도 빌드, 코드 서명·공증이 없어 처음에는 우클릭 > 열기가 필요. admin 기능·시스템 문서는 포함되지 않고 접근 코드는 PC마다 무작위 생성. ② **접속형** — 운영자 서버 사이트를 PC 창으로 여는 앱(서버 부하·오프라인 제약은 웹과 동일).\n          8-1. **Windows PC 앱(접속형)**(현재 {SHELL_VERSION}): 시작 화면에서 내려받는 설치용 exe(WebView2, Windows 10/11 64비트, 코드 서명 없음 — SmartScreen 경고 가능). 사이트가 갱신되면 적용 여부 알림, 앱 신버전도 알림. 시스템 문서는 포함되지 않으며 서버도 앱 요청에는 문서를 내주지 않음.",
          "9. **거버넌스**: 투입 승인(본인 승인 금지·만료), Academy 이력 확인대기, 개인정보 열람/삭제, 감사 로그.", "",
          "## 4. 역할", "", "| 역할 | 권한 |", "|---|---|", "| learner | 본인 세션(선택 삭제 가능)·실습·시험 |", "| instructor | 강사: 정답표·수료·검토 (admin 고유 기능 접근 불가) |",
          "| reviewer | 검토자(위즈베이스 DB 컨설턴트): 검수·재확인·대조표 |", "| admin | **수퍼유저**: 시스템 문서, 피드백 관리·개발큐, 도메인 신청 포함 모든 요구사항·피드백 관리 (별도 admin 접근 코드 필요 — staff·instructor 코드로는 로그인 불가) |", "",
          "## 5. 구성", "", "- 서버: Python FastAPI(`backend/`), 화면: 정적 HTML/JS(`static/`), 데이터: `data/`(세션·v11.json), 학습자 PC adapter: `adapter/`.",
          "- 외부 공개: `https://dbx.wizbase.ai.kr`(nginx + Let's Encrypt, frp 터널). 로컬 포트 8830. 단독 설치형은 사용자 PC의 127.0.0.1:18830에서 자체 서버 실행.",
          "- 소스 저장소: `https://github.com/bkimkr0139-blip/wizbase-dbx`(공개 저장소 — 접근 코드·세션 데이터·설치 파일은 제외). 다른 PC에서 `git clone` → `start_server.bat`로 로컬 서버를 띄우고, 운영자가 별도 전달한 접근 코드 파일을 `data\\.staff_codes.json`으로 두거나 환경변수 `DBX_CODES_FILE`로 지정하면 admin 기능을 사용할 수 있다(그 PC에만 데이터가 생기며 운영 서버와 별개). 운영 서버의 admin 기능은 어느 PC에서든 사이트에 admin 코드로 로그인해 사용.",
          "- 접근 코드: admin·staff·instructor 3종(서로 달라야 함). 우선순위: 환경변수(`DBX_ADMIN_CODE`/`DBX_STAFF_CODE`/`DBX_INSTRUCTOR_CODE`) > 코드 파일(`DBX_CODES_FILE` 또는 `data/.staff_codes.json`) > 최초 실행 시 무작위 생성. 전달받은 파일은 서버가 수정하지 않음.",
          "- 중앙 서버 연계 API: `/api/app/manifest`(배포 정보), `/download/standalone`·`/download/standalone-mac-arm64`·`/download/standalone-mac-x64`·`/download/pack`·`/download/app`, `/api/feedback/intake`(단독형 피드백 접수, 비로그인·한도 있음), `/api/feedback/intake/{id}?receipt=`(처리 상태 조회).",
          "- 주요 API: `/api/feedback/*`(제출·내역은 로그인 사용자, 관리·큐·이미지는 admin), `/api/app/manifest`, `/download/app`, `/api/system/*`, `/api/ko-guide`, `/api/transfer-seeds`, `/api/collab/*`, `/api/verification-matrix`, `/api/objectives`, `/api/items`.", "",
          "## 6. 한계와 미완료(숨기지 않음)", "",
          "- 실제 Databricks 워크스페이스 대조는 컨설턴트의 직접 수행이 필요(WORKSPACE_CHECKED·DBX_VERIFIED는 기록 전까지 0).",
          "- 문항·목표의 인간 검수, 파일럿(12명 이상) 미수행. 한국어 DE-P·GEN-A 가이드는 영문 최신본과 다른 이전 버전(참고용).",
          "- 로그인에 비밀번호·개인 PIN이 없어 사용자 식별은 로그인 단위이며, 개인 계정·세션 이어쓰기(PIN, 내보내기/가져오기)는 미구현.",
          "- macOS 앱은 이 개발 환경(Windows)에서 빌드·시험하지 못해 Mac 또는 GitHub Actions(`build-standalone-mac`)에서 빌드해야 하며, 실제 Mac 실행은 미검증. 콘텐츠 팩은 새 라이브러리 추가·앱 껍데기 변경을 담을 수 없음(앱 전체 교체 필요).",
          "- 단독 설치형: 업데이트·피드백 전달은 운영자 서버가 켜져 있고 인터넷이 연결될 때만 가능. 설치 파일은 약 46MB, 코드 서명 없음(SmartScreen 경고 가능). 단독형은 PC별 데이터가 분리되어 사용자 간 협업 기능(팀)·중앙 검토는 이용할 수 없음.",
          "- 피드백 → 개발은 자동 개발이 아님(개발큐 지시서를 운영자가 처리). PC 앱 exe는 코드 서명 없음.",
          "- Python 격리 실행기 미구성(AT-16은 차단 방식). 파트너 tier·Portal 연결은 회사가 직접 확인.", "", "## 7. 변경 이력", ""]
    for r in CHANGELOG:
        L += [f"**{r['version']}** ({r['date']})"] + [f"- {n}" for n in r["notes"]] + [""]
    L += ["---", "WIZBASE 내부 훈련 환경 · Databricks 공식 제품·교육·시험이 아님 · 합성 데이터만 사용."]
    return "\n".join(L)


def reviewer_manual():
    L = [f"# 검토자 매뉴얼 (WIZBASE DB 컨설턴트용) — v{VERSION}", "",
         "이 매뉴얼은 위즈베이스 DB 컨설턴트가 **실제 Databricks 교육용 워크스페이스**에서 스스로 대조·검토하고 그 결과를 시스템에 기록하는 절차입니다. 합성 데이터만 사용하고 고객 운영 데이터는 쓰지 않습니다.", "",
         "## 0. 준비", "", "1. 본인 소유 Databricks 교육용(비운영) 워크스페이스, SQL Warehouse 1개, Unity Catalog 사용 가능한 catalog/schema.",
         "2. 이 시스템에 `reviewer` 로그인(직원 코드).", "3. 학습자 PC adapter 설치: `adapter/README.md` 참고(실행 결과를 증거 해시로 제출).",
         "4. 모든 확인은 **본인이 화면에서 본 것**만 기록. 문서만 본 것은 DOC_CHECKED로 남기고 WORKSPACE_CHECKED로 올리지 않습니다.", "",
         "## 1. 기능 재확인(WORKSPACE_CHECKED)", "", "1. 검토 센터의 기능 목록에서 항목 선택 → 실제 워크스페이스에서 해당 메뉴 경로를 직접 연다.",
         "2. 보이는 메뉴·옵션·오류 문구를 기록하고 `현장 대조표`에 행을 추가(14열: 기대/실제/차이/심각도 등).",
         "3. 일치하면 '재확인(워크스페이스)' 실행 → 상태가 WORKSPACE_CHECKED로 바뀌고 확인일이 기록된다. 35일이 지나면 STALE.", "",
         "## 2. 공식 목표 원문 대조", "",
         "1. `인증 준비 > 공식 목표`에서 목표 선택. 공식 PDF(영문, 필요 시 한국어)를 열어 해당 bullet의 sha256이 일치하는지, 요약이 의미를 바꾸지 않는지 확인.",
         "2. 이상 없으면 '원문 대조 완료' 기록(검토자 ID·일시 저장). 요약이 틀리면 이슈로 남긴다.", "3. `한국어 가이드` 화면의 차이표로 영문과 다른 영역/개수를 먼저 확인.", "",
         "## 3. 문항 검수(2단계 분리)", "",
         "1. 기술 검토: 정답·오답 근거가 현재 공식 문서·실측과 맞는지. 2. 출제 검토: 모호성·중복·난이도. 두 단계는 **서로 다른 사람**이 수행(한 사람이 둘 다 하면 ACTIVE 불가).",
         "3. 두 단계 통과 시에만 ACTIVE. 의심되면 recall.", "", "## 4. 실습 팩별 실제 워크스페이스 절차", ""]
    for lid, l in sorted(labs.LABS.items()):
        L += [f"### {lid} — {l['title']}", "", f"- 목표: {l.get('goal', '')}"]
        if l.get("steps"):
            L += ["- 절차:"] + [f"  {i + 1}. {s}" for i, s in enumerate(l["steps"])]
        L += ["- 제출 산출물: " + ", ".join(l.get("required_artifacts") or ["adapter 자동 증거"])]
        if l.get("rubric"):
            L += ["- 루브릭: " + " / ".join(f"{r['item']}({r['max']})" for r in l["rubric"]) + f" — 합격 {l.get('pass_score', 70)}점"]
        L += [""]
    L += ["## 5. 기록 규칙", "", "- 본인이 만든 증거는 본인이 승인하지 않는다(타 검토자).", "- 실패·불일치도 숨기지 않고 기록(심각도 표기).",
          "- 제품 동작은 작성 시점 문서 기준 — 실제 화면과 다르면 현장 대조표가 우선.", "- 개인정보·고객 데이터는 절대 업로드하지 않는다.", "", "## 6. 완료 기준(권고)", "",
          "- 기능 매니페스트 전 항목 WORKSPACE_CHECKED 또는 사유 기재 / 목표 134개 원문 대조 / 문항 목표당 3개 이상 ACTIVE / 실습 팩 21개 증거 승인 / 파일럿 12명 이상.", ""]
    return "\n".join(L)
