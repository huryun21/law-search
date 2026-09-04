# Claude Code 인수인계 — 대한민국 법령 통합검색기

갱신일: 2026-09-03

대상: 이 저장소를 이어서 수정하는 Claude Code 또는 개발자
대화 원문을 복사하지 않고, 최종 의도·검증된 사실·실패 사례·남은 작업만 보존한다.

## 1. 프로젝트 목적

건축법, 국토계획법 등 상위법과 특정 지자체의 자치법규를 하나의 검색창에서 찾는 내부 업무용 도구다. 사용자는 법률용어를 정확히 찾아야 하므로 그럴듯한 관련 정보보다 검색어의 정확한 일치를 우선한다.

현재 구현은 Windows 로컬 Streamlit 앱이다. 팀 배포와 모바일 최적화는 아직 구현하지 않았다. AI 요약과 법적 판단은 이번 제품 범위 밖이다.

## 2. 사용자가 확정한 검색 원칙

### 검색 문법

- 주차 대수: 전국 상위법·행정규칙만 검색한다.
- @평택 주차 대수, 주차 대수 @평택: 평택시 자치법규와 경기도 자치법규를 최우선으로, 그 아래 상위법을 보여 준다.
- @경기/평택 주차 대수: 광역/기초지자체를 명시해 지역을 확정한다.
- @중구처럼 여러 지역이 가능한 경우 임의 선택하지 않고 후보 선택 후에만 검색한다.
- 지역 구분자는 @이다. 일반 키워드와 혼동하지 않고, 사용자가 명시적으로 지역 검색을 요청했다는 뜻을 전달한다.

### 정확도와 순위

1. 제목의 정확한 일치
2. 본문에서 정확한 문구 일치
3. 띄어쓰기만 다른 일치
4. 여러 단어가 모두 같은 문서에 있는 보조 결과

검색어가 방화구획이면 방화만 포함된 문서는 본문 결과가 되어서는 안 된다. AI가 유사어·연관어를 만들어 확장 검색하는 것도 금지다. 법제처 공식 용어 API가 제공한 연관 검색어를 화면에 나열하는 것은 가능하지만, 이 목록 때문에 별도 검색을 무분별하게 실행하면 안 된다.

## 3. 현재 구현 완료 상태

| 영역 | 현재 상태 | 근거 파일 |
| --- | --- | --- |
| 통합 검색 | 현행 법령, 행정규칙, 선택 지역의 기초/광역 자치법규를 공식 API로 검색 | src/lawsearch/api.py, service.py |
| 지역 검색 | @지역 문법, 후보 선택, 기초→광역→상위법 우선순위 | query.py, regions.py, ranking.py |
| 정확도 | 정확/띄어쓰기/전 단어 일치 우선순위와 본문 상세 검증 | service.py, detail.py, tests/test_service.py |
| 오탐 방지 | 본문 후보를 상세 조·항·호·목에서 재검증해 정확 문구가 없는 결과 제거 | SearchService._verify_body_results() |
| 본문 문맥 | 최대 5개(미리보기는 20개)의 정확 일치 문맥을 조·항·호·목 위치와 함께 표시 | detail.extract_contexts(), service.load_contexts() |
| 캐시 | 검색목록과 상세본문을 분리한 SQLite 24시간 캐시, 강제 새로고침·stale fallback | cache.py, service.py |
| 검색 제출 | 검색창에서 Enter로 제출 | app._render_search_form() |
| 순수 뷰모델 | 그룹·카드·사이드바·비교 목록·공식 URL 검증을 Streamlit 비의존 모듈로 분리 | src/lawsearch/viewmodels.py, tests/test_viewmodels.py |
| 데스크톱 워크스페이스 | 폭 제한 2열 카드, 유형별 사이드바 바로가기, 단일 문서 미리보기(지연 로딩·캐시 재사용), 좌우 비교 | src/lawsearch/app.py, tests/test_app.py |
| 공식 링크 | HTTPS law.go.kr만 버튼으로 허용, 인증이 필요한 DRF 상세 링크는 공개 LSW 독자 페이지로 전환 | normalize.py, viewmodels.is_official_url() |
| 인증 보호 | 외부 키 파일만 런타임에 읽고, API 오류·캐시 응답에서 인증값을 제거 | config.py, api.py, cache.py |
| 테스트 | 단위·통합(명시적 opt-in) 테스트 존재 | tests/ |

## 4. 해결한 실패 사례와 이유

### 방화구획 검색에 자연공원법 같은 무관한 결과가 나왔던 문제

원인: API 본문검색은 검색어 전체가 아닌 일부 형태나 색인 결과를 넓게 반환할 수 있다. 예를 들어 자연공원법의 방화는 방화구획과 같지 않다.

수정: 검색 결과 후보를 곧바로 화면에 보이지 않고, 각 본문 후보의 상세 원문을 다시 읽어 정확 문구가 실제 조문·항·호·목에 있는지 확인한다. 정확 문맥이 없으면 제거한다.

회귀 근거: tests/test_service.py의 test_body_search_keeps_only_results_with_a_matching_article. 이 테스트는 자연공원법의 방화만 있는 결과를 제외하고, 방화구획이 실제로 있는 건축법 시행령만 남기는 사례다.

### 본문 일치 보기에서 무관한 정보가 보이던 문제

원인: 결과 카드가 본문 일치 여부와 무관하게 API가 돌려준 일반 결과 메타데이터를 먼저 노출하면 사용자가 이를 일치 근거로 오해할 수 있었다.

수정: detail.extract_contexts()가 조·항·호·목별 텍스트에서 정확 일치를 우선 추출한다. 일치 문맥이 없으면 검색어와 일치하는 본문 구간이 없습니다만 표시하며, 임의 조문으로 대체하지 않는다.

잔여 한계: 현재 화면은 세로 목록의 본문 일치 보기 버튼을 누르는 방식이다. 카드 요약 문맥, 한 문서 미리보기, 두 문서 비교는 아직 구현되지 않았다.

### 공식 원문 열기가 OpenAPI 사용자 인증 실패 화면으로 갔던 문제

원인: 검색 API 응답에 /DRF/lawService.do?...&OC=... 형태의 인증용 상세 URL이 섞여 올 수 있다. 이 URL을 브라우저로 열면 API 사용자 인증을 다시 요구한다.

수정: normalize._official_url()는 법령/자치법규/행정규칙의 DRF 상세 URL에서 식별자만 읽고, 인증값을 버린 뒤 /LSW/lsInfoP.do, /LSW/ordinInfoP.do, /LSW/admRulInfoP.do 공개 원문 URL로 바꾼다. API 응답 캐시에서도 OC 쿼리값을 제거한다.

회귀 근거: tests/test_normalize.py의 test_authenticated_drf_detail_links_become_public_reader_links와 tests/test_api_response_security.py.

## 5. 현재 실행·서버·데이터 흐름

~~~
run.bat
  └─ Streamlit (로컬 PC의 http://127.0.0.1:8501)
       └─ app.py
            └─ SearchService
                 ├─ LawApiClient (https://www.law.go.kr/DRF/)
                 ├─ RegionRegistry
                 ├─ exact-context extractor
                 └─ SQLite 24시간 캐시
~~~

- run.bat은 Python 가상환경을 준비하고 loopback 주소에만 서버를 연다. 다른 PC나 휴대폰에서는 접근할 수 없다.
- http://127.0.0.1:8501은 HTTP이지만 내 PC만 가리키는 loopback 통신이다. 외부 공개 주소가 아니다.
- 182.x.x.x처럼 공인 IP가 보였다면 그것은 네트워크/라우터 또는 별도 서버 주소이며, 현재 앱의 기본 실행 방식이 아니다.
- 검색 API 통신은 HTTPS로 국가법령정보센터에 나간다.
- localhost:58152는 앱 기능의 정식 포트가 아니다. 목업/개발 미리보기 서버와 실제 Streamlit 앱을 혼동하지 않는다.

## 6. 캐시와 성능

- 캐시 키는 자료원·검색어·지역 코드·페이지를 기준으로 만든다.
- 목록과 본문 상세는 다른 SQLite 항목이다.
- 기본 TTL은 24시간이다. 유효 캐시가 있으면 공식 API를 다시 호출하지 않는다.
- 공식 API에서 새로고침은 캐시를 건너뛴다.
- API가 실패했지만 만료 캐시가 있으면 이전 결과와 조회시각을 표시한다. 캐시도 없으면 해당 자료원만 오류로 표시하고 다른 자료원의 결과는 유지한다.

### 성능상 남은 문제

현재 검색은 자료원별 검색 자체는 병렬로 시작하지만, 각 자료원에서는 제목 검색·본문 변형 검색과 본문 상세 검증이 추가로 일어난다. 정확도 회귀를 막기 위해 필요한 과정이지만, 결과가 많은 검색어는 느려질 수 있다.

성능을 손댈 때 절대 하지 말 것:

- 상세 본문 검증을 단순히 삭제해 오탐을 다시 노출하는 것
- 키워드 일부만 맞아도 결과를 허용하는 것
- 정확도가 낮은 연관 검색어를 동시에 대량 조회하는 것

우선 검토할 방법:

1. 검색 화면에 자료원별 진행 상태와 캐시 적중 여부를 표시한다.
2. 정확도 검증 대상 수와 상세 요청 시간을 측정하되, 키·전체 요청 URL·본문 전체를 로그로 남기지 않는다.
3. 제목 정확 일치 결과는 현재처럼 상세 조회를 미루고, 사용자가 열 때만 조회한다.
4. 결과 렌더링과 본문 미리보기를 분리해 검색 결과가 먼저 보이게 한다.

## 7. UI 구현 상태와 남은 작업

상세 설계는 [desktop search workspace spec](superpowers/specs/2026-09-03-desktop-search-workspace-design.md), 구현 계획은 [plan](superpowers/plans/2026-09-03-desktop-search-workspace-ui.md)에 있다.

구현 완료(2026-09-03):

1. 최대 폭을 제한한 데스크톱 2열 카드 레이아웃.
2. 법규 유형별 사이드바 바로가기. 결과를 숨기는 필터가 아니라 문서 바로가기이며 검색·상세 API를 호출하지 않는다.
3. 카드·사이드바에서 문서를 열면 이미 가져온 결과와 캐시를 재사용하는 본문 미리보기. 검색 결과로 돌아가도 다시 검색하지 않는다.
4. 상단 `비교하기`로 현재 검색 결과 중 임의의 두 법규를 좌우로 선택해 정확 일치 문맥을 비교. 모든 법규 유형 조합을 허용하며 위임관계·우선순위·법적 차이를 자동 판단하지 않는다.

남은 작업:

5. 좁은 폭에서 1열로 자연스럽게 재배치되는지 수동 검증(모바일 UX 우선순위는 낮음).

## 8. 배포 상태와 권장 순서

### 저장소 준비 완료 (2026-09-03)

- 루트 `streamlit_app.py` 진입점 — `lawsearch.app.main` 위임.
- `requirements.txt` — `streamlit`·`httpx`를 테스트한 버전으로 고정하고 `.`로 패키지 설치.
- `.streamlit/secrets.toml` Git 제외, `.streamlit/secrets.toml.example` 추가.
- `lawsearch.config.resolve_api_key()`가 `st.secrets`의 `LAW_API_KEY` → 로컬 키 파일 순으로 인증값을 고른다. `Settings`에는 인증값을 담지 않고, 값은 `LawApiClient` 생성 시에만 전달된다.
- `config.local.toml`이 없어도 앱이 시작된다(캐시 경로 기본값 `data/cache.db`). `run.bat`(로컬 전용)은 그대로 `config.local.toml`을 요구한다.

### 남은 것은 사용자의 Community Cloud 대시보드 작업

약 10명, 인당 하루 1~2회 검색이라는 가정에서 비공개 Streamlit Community Cloud가 첫 배포 후보다. GitHub `main`이 배포 원본이다.

1. Community Cloud에서 저장소 연결, 브랜치 `main`, 메인 파일 `streamlit_app.py` 지정.
2. 앱 Settings > Secrets 에 `LAW_API_KEY = "..."` 입력(`.streamlit/secrets.toml.example` 참고).
3. 앱을 비공개로 설정하고 팀원 이메일만 뷰어로 초대. 워크스페이스당 비공개 앱은 1개 제한.
4. 실제 키·URL을 저장소나 문서에 적지 않는다.

클라우드 SQLite 캐시는 컨테이너 재시작 시 사라지며, 이 경우 공식 API에서 다시 조회한다(정상 동작).

Azure 이전은 이 앱의 검색·서비스·정확도 계층을 버리고 다시 만들 일이 아니다. 나중에 호스팅, 비밀값 저장, 영구 캐시 운영만 바꾸면 된다.

## 9. 주요 파일과 테스트 위치

| 파일 | 역할 | 관련 테스트 |
| --- | --- | --- |
| src/lawsearch/app.py | Streamlit UI, view_mode 분기(결과/미리보기/비교), 세션 상태 | tests/test_app.py |
| src/lawsearch/viewmodels.py | 순수 뷰모델: 그룹·카드·사이드바·비교 목록, 공식 URL 검증, detail_session_key | tests/test_viewmodels.py |
| src/lawsearch/api.py | 국가법령 API 요청, 응답 인증값 제거 | tests/test_api.py, test_api_response_security.py |
| src/lawsearch/cache.py | SQLite TTL 캐시와 인증값 방어 | tests/test_cache.py |
| src/lawsearch/config.py | 로컬 키 파일·캐시 경로, resolve_api_key(st.secrets→키 파일) | tests/test_config.py |
| streamlit_app.py | Community Cloud 진입점 (lawsearch.app.main 위임) | tests/test_deployment.py |
| src/lawsearch/detail.py | 정확 문맥·조항 위치 추출 | tests/test_detail.py |
| src/lawsearch/normalize.py | API 응답 공통 모델화, 공개 원문 URL | tests/test_normalize.py |
| src/lawsearch/query.py | @지역 파싱 | tests/test_query.py |
| src/lawsearch/ranking.py | 일치도·지역·현행 우선순위 | tests/test_ranking.py |
| src/lawsearch/regions.py | 지역 코드와 후보 해석 | tests/test_regions.py |
| src/lawsearch/service.py | 자료원 병렬 검색, 본문 검증, 검증 첫 문맥을 match_context에 전달, 캐시 | tests/test_service.py |

## 10. Claude Code가 시작할 때의 절차

1. GitHub에서 저장소를 내려받고, 기본 브랜치와 git status --short를 확인한다.
2. 이 문서, CLAUDE.md, 기존 설계서, 변경하려는 파일의 테스트를 먼저 읽는다.
3. 실제 키는 GitHub나 대화에 붙이지 않는다. 로컬 실행에는 사용자의 외부 키 파일을 가리키는 무시된 config.local.toml만 사용한다.
4. run.bat으로 로컬 실행을 확인하거나, 테스트 의존성을 설치한 환경에서 python -m pytest -v를 실행한다.
5. 사용자가 요구한 행동을 먼저 실패하는 테스트로 고정한다.
6. 최소 변경만 하고, 관련 테스트 → 전체 테스트 → git diff --check 순서로 검증한다.
7. 커밋 메시지는 한 목적만 담는다. 원격 push와 배포는 사용자가 별도로 승인했을 때만 한다.

## 11. GitHub 상태를 읽는 방법

GitHub에는 대화 원문이 자동으로 올라가지 않는다. 이 문서와 CLAUDE.md가 대화에서 확정된 맥락을 대신한다.

- 코드와 테스트: Git에 커밋된다.
- 실제 API 키, config.local.toml, .streamlit/secrets.toml, SQLite 캐시, 로그, 가상환경: Git에 넣지 않는다.
- 새 작업은 기본 브랜치 최신 상태에서 별도 작업 브랜치를 만든 뒤, 작은 검증 단위로 커밋한다.
- GitHub의 실제 최신 상태는 작업을 시작할 때 반드시 git fetch와 커밋 그래프로 확인한다. 이 문서는 2026-09-03 시점의 제품 상태이며, GitHub의 최신 커밋 SHA를 고정된 사실로 주장하지 않는다.

## 12. 완료 판단 기준

다음 항목을 모두 만족해야 수정 완료라고 말할 수 있다.

- 새 동작을 증명하는 실패-후-통과 pytest가 있다.
- 기존 전체 테스트가 통과한다.
- 방화구획 오탐 회귀 사례가 계속 차단된다.
- API 키·인증 URL 값이 Git diff, 캐시, 오류 화면, 로그에 없다.
- 공식 원문 링크는 인증 API URL이 아닌 공개 law.go.kr 독자 URL이다.
- 구현하지 않은 UI/배포 계획을 현재 완료된 기능처럼 문서화하지 않았다.
