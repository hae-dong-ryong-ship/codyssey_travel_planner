# 국내 여행지 추천 프로그램 (LLM + 지도 API)

여행 날짜를 입력하면 다음 3단계가 자동으로 진행됩니다.

1. **Gemini(LLM)** 가 그 시기에 가기 좋은 국내 도시를 추천하고 날씨·행사·이유를 JSON으로 돌려줍니다.
2. **Kakao Local(지도 API)** 로 추천 도시의 맛집 5곳을 검색합니다.
3. **Gemini(LLM)** 가 1·2단계 데이터를 합쳐 최종 여행 리포트(Markdown)를 작성합니다.

```
날짜 입력 ──▶ [Gemini] 도시 추천(JSON) ──▶ [Kakao] 맛집 검색 ──▶ [Gemini] 리포트(.md)
```

## 폴더 구조

```
travel_planner/
├── travel_planner.py   # 메인 프로그램
├── requirements.txt    # 필요한 라이브러리 목록
├── .env.example        # API 키 설정 예시 (실제 키 없음)
├── .gitignore          # .env 가 업로드되지 않도록 막음
├── README.md
└── results/            # 실행하면 자동 생성
    ├── 2026-03-15_raw.json
    └── 2026-03-15_travel_plan.md
```

## 1. 준비

Python 3.10 이상이 필요합니다. 터미널에서 `python --version` 으로 확인하세요.

```bash
cd travel_planner
python -m venv venv                 # (선택) 가상환경 만들기
source venv/bin/activate            # macOS/Linux
# venv\Scripts\Activate.ps1         # Windows PowerShell
pip install -r requirements.txt
```

## 2. API 키 발급

**Gemini API 키**: [Google AI Studio](https://aistudio.google.com/apikey) 에 구글 계정으로 로그인 → "Create API key" 를 누르면 발급됩니다. 무료 사용량이 있습니다.

**Kakao REST API 키**: [Kakao Developers](https://developers.kakao.com) 로그인 → "내 애플리케이션" → 애플리케이션 추가 → 앱 키 화면의 **REST API 키** 를 복사합니다. 앱 설정에서 **카카오맵(지도/로컬) 서비스가 활성화**되어 있어야 하며, 꺼져 있으면 403 오류가 납니다.

## 3. API 키 설정

`.env.example` 을 복사해 `.env` 파일을 만들고 키를 넣습니다.

```bash
cp .env.example .env        # Windows: copy .env.example .env
```

```
GEMINI_API_KEY=발급받은_키
KAKAO_REST_API_KEY=발급받은_키
```

`.env` 대신 환경변수로 설정해도 됩니다(현재 터미널 세션에만 적용).

```bash
export GEMINI_API_KEY="YOUR_KEY"          # macOS/Linux
$env:GEMINI_API_KEY="YOUR_KEY"            # Windows PowerShell
```

## 4. 실행

```bash
python travel_planner.py --date "2026-03-15"
python travel_planner.py -date "2026-03-15"            # -date 도 동일하게 동작
python travel_planner.py --date "2026-03-15" --no-cache  # 캐시 무시하고 API 다시 호출
```

실행 예시:

```
[1/3] 1차 추천 생성 중(LLM)...
    - recommended_city: "제주"
[2/3] 맛집 검색 중(지도/장소 API)...
    - 맛집 5곳 검색 완료
[3/3] 최종 리포트 생성 중(LLM)...
    - 리포트 생성 완료

완료! results/2026-03-15_travel_plan.md 를 확인하세요.
```

날짜 형식이 틀리면(`2026/03/15`, `2026-13-01` 등) 사용법을 출력하고 종료합니다.

## 5. 결과물 확인

`results/{날짜}_raw.json` 은 원본 데이터로, 1차 추천 JSON(`recommendation`), 맛집 검색 결과(`restaurants`, 0건 가능), 오류 목록(`errors`)이 들어 있습니다.

`results/{날짜}_travel_plan.md` 는 최종 리포트로, 추천 지역·추천 이유·날씨·행사/축제·맛집·1일 일정·오류 요약 섹션으로 구성됩니다. VS Code 등에서 Markdown 미리보기로 열면 보기 편합니다.

## 6. 오류 처리 방식

| 상황 | 동작 |
|---|---|
| API 키 미설정 | 즉시 종료하고 설정 방법 안내 |
| LLM 응답이 JSON이 아님 | "필수 키만 JSON으로" 프롬프트로 **1회만** 재시도, 그래도 실패하면 종료 |
| LLM API 호출 실패 (1단계) | 추천 도시가 없어 진행 불가 → 오류를 JSON에 저장하고 종료 |
| 지도 API 401/403 | 인증 오류 안내, 맛집 = "데이터 없음"으로 계속 진행 |
| 지도 API 429/네트워크 오류 | 맛집 = "데이터 없음"으로 계속 진행 |
| 맛집 검색 0건 | `EMPTY_RESULT` 기록, 맛집 = "데이터 없음"으로 계속 진행 |
| LLM 리포트 생성 실패 | 프로그램이 기본 형식 리포트를 직접 만들어 저장 |

모든 오류는 `{"step", "type", "message"}` 형태로 기록되어 원본 JSON과 리포트의 오류 요약 섹션에 남습니다.

## 7. 보너스 기능: 캐싱

같은 날짜로 다시 실행하면 `results/{날짜}_raw.json` 을 재사용해 1~2단계 API 호출을 건너뛰고 리포트만 다시 만듭니다. API 비용과 시간을 아낄 수 있습니다. 새로 받고 싶으면 `--no-cache` 를 붙이세요.

## 8. ⚠️ API 키 보안 주의사항

- API 키를 **코드, README, 결과 파일에 절대 직접 쓰지 마세요.** 이 프로그램은 키를 `.env` 또는 환경변수에서만 읽고, 화면이나 파일에 출력하지 않습니다.
- `.env` 파일은 `.gitignore` 에 등록되어 있어 Git에 올라가지 않습니다. 제출 전 `git status` 로 `.env` 가 목록에 없는지 확인하세요.
- 제출할 때는 `.env` 가 아닌 `.env.example`(가짜 값) 만 포함하세요.
- 키가 실수로 공개되었다면 즉시 발급 사이트에서 키를 삭제(재발급)하세요.

**왜 키를 코드에 쓰면 안 될까?** 코드를 공유하는 순간 키도 함께 공개되어 다른 사람이 내 계정으로 과금되는 API를 쓸 수 있습니다. 또 키를 환경변수로 분리해 두면 키를 바꿀 때 코드를 고칠 필요가 없습니다.

## 9. 학습 정리

**REST API와 GET/POST**: REST API는 URL(주소) + 메서드 + 헤더 + 본문으로 요청을 보내고 JSON으로 응답을 받는 방식입니다. GET은 데이터를 *조회*할 때 쓰며 조건을 URL 쿼리 파라미터로 보냅니다(카카오 맛집 검색: `?query=제주 맛집`). POST는 서버에 데이터를 *보내서 처리*를 요청할 때 쓰며 내용을 요청 본문(body)에 담습니다(Gemini에 프롬프트 전송).

**LLM 출력의 구조화**: LLM이 자유로운 문장으로 답하면 프로그램이 도시 이름을 정확히 꺼내기 어렵습니다. 그래서 JSON으로만 답하게 요청하고(`responseMimeType: application/json` + 프롬프트), 파싱 후 필수 키와 타입을 검사합니다. 그렇게 얻은 `recommended_city` 값이 다음 단계 지도 검색의 입력이 됩니다.

**대표 오류와 대응 원칙**: 인증(401/403)은 키·권한 문제라 재시도해도 소용없으니 안내 후 건너뜁니다. 쿼터(429)는 사용량 초과, 네트워크 오류는 연결 문제입니다. 파싱 오류는 응답 형식 문제라 형식을 더 엄격히 요구해 한 번만 재시도합니다. 핵심 원칙은 "부가 기능(맛집)이 실패해도 핵심 결과(리포트)는 만든다"와 "무한 재시도 금지"입니다.
