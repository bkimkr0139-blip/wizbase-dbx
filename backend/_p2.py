import os
p = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'sysinfo.py')
s = open(p, encoding='utf-8').read()


def rep(a, b):
    global s
    assert a in s, a[:70]
    s = s.replace(a, b, 1)


rep('"6. **세션 관리(UI-01)**:', '"6. **세션 관리(UI-01)**:')
rep('로그인 시 **이름(실명) 입력 필수**(2자 이상, \\\'학습자\\\' 등 기본값 불가).",',
    '로그인 시 **이름(실명) 입력 필수**(2자 이상, \\\'학습자\\\' 등 기본값 불가). **세션 소유자는 이름이 아니라 로그인마다 새로 발급되는 사용자 ID**이므로 이름이 같아도 세션은 공유·연결되지 않으며(웹↔단독형, 웹 재로그인 포함), 로그아웃·재로그인하거나 브라우저·PC를 바꾸면 이전 세션은 \\\'내 세션\\\'에 보이지 않는다(비밀번호가 없어 이름만으로 연결하면 타인이 기록을 볼 수 있기 때문). 이어 쓰려면 로그아웃하지 않고 같은 브라우저를 사용한다.",')
rep('"- 중앙 서버 연계 API:', '"- 소스 저장소: `https://github.com/bkimkr0139-blip/wizbase-dbx`(공개 저장소 — 접근 코드·세션 데이터·설치 파일은 제외). 다른 PC에서 `git clone` → `start_server.bat`로 로컬 서버를 띄우고, 운영자가 별도 전달한 접근 코드 파일을 `data\\\\.staff_codes.json`으로 두거나 환경변수 `DBX_CODES_FILE`로 지정하면 admin 기능을 사용할 수 있다(그 PC에만 데이터가 생기며 운영 서버와 별개). 운영 서버의 admin 기능은 어느 PC에서든 사이트에 admin 코드로 로그인해 사용.",\n          "- 접근 코드: admin·staff·instructor 3종(서로 달라야 함). 우선순위: 환경변수(`DBX_ADMIN_CODE`/`DBX_STAFF_CODE`/`DBX_INSTRUCTOR_CODE`) > 코드 파일(`DBX_CODES_FILE` 또는 `data/.staff_codes.json`) > 최초 실행 시 무작위 생성. 전달받은 파일은 서버가 수정하지 않음.",\n          "- 중앙 서버 연계 API:')
rep('"- 단독 설치형: 업데이트·피드백 전달은', '"- 로그인에 비밀번호·개인 PIN이 없어 사용자 식별은 세션 단위(로그인 단위)이며, 개인 계정·세션 이어쓰기(PIN, 내보내기/가져오기)는 미구현.",\n          "- 단독 설치형: 업데이트·피드백 전달은')
open(p, 'w', encoding='utf-8').write(s)
print('ok')
