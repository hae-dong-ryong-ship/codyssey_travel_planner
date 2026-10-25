"""
국내 여행지 추천 프로그램
- LLM API   : Google Gemini (REST, POST 요청)
- 지도 API  : Kakao Local 키워드 검색 (REST, GET 요청)

사용법:
    python travel_planner.py --date "2026-03-15"
    python travel_planner.py -date "2026-03-15" --no-cache
"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# 기본 설정
# ---------------------------------------------------------------------------
RESULTS_DIR = Path(__file__).resolve().parent / "results"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
KAKAO_URL = "https://dapi.kakao.com/v2/local/search/keyword.json"
TIMEOUT = 30            # API 응답을 기다리는 최대 시간(초)
RESTAURANT_COUNT = 5    # 검색할 맛집 개수

# 실행 중 발생한 오류를 모아두는 목록 (빈 리스트여도 괜찮음)
errors = []


def add_error(step, err_type, message):
    """오류를 목록에 기록한다. 리포트와 원본 JSON의 errors 섹션에 사용된다."""
    errors.append({"step": step, "type": err_type, "message": message})


# ---------------------------------------------------------------------------
# 1) CLI 인자 처리
# ---------------------------------------------------------------------------
def valid_date(text):
    """날짜가 YYYY-MM-DD 형식인지 검사한다. 틀리면 argparse가 사용법을 출력하고 종료한다."""
    try:
        datetime.strptime(text, "%Y-%m-%d")
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"날짜 형식이 올바르지 않습니다: '{text}' (예: 2026-03-15)"
        )
    return text


def parse_args():
    parser = argparse.ArgumentParser(
        description="여행 날짜를 입력하면 국내 여행지와 맛집을 추천하고 리포트를 만듭니다."
    )
    parser.add_argument(
        "-date", "--date", dest="date", required=True, type=valid_date,
        help='여행 날짜 (형식: "YYYY-MM-DD")',
    )
    parser.add_argument(
        "--no-cache", action="store_true",
        help="저장된 결과가 있어도 API를 다시 호출합니다.",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# 2) API 키 불러오기 (.env 또는 환경변수)
# ---------------------------------------------------------------------------
def load_api_keys():
    load_dotenv()  # .env 파일이 있으면 그 내용을 환경변수로 읽어온다
    gemini_key = os.getenv("GEMINI_API_KEY")
    kakao_key = os.getenv("KAKAO_REST_API_KEY")

    missing = [name for name, value in
               [("GEMINI_API_KEY", gemini_key), ("KAKAO_REST_API_KEY", kakao_key)]
               if not value]
    if missing:
        print(f"[오류] API 키가 설정되지 않았습니다: {', '.join(missing)}")
        print("설정 방법:")
        print("  1) 프로젝트 폴더에 .env 파일을 만들고 아래처럼 적으세요 (.env.example 참고).")
        print("       GEMINI_API_KEY=발급받은_키")
        print("       KAKAO_REST_API_KEY=발급받은_키")
        print("  2) 또는 터미널에서 환경변수로 설정하세요.")
        print('       macOS/Linux : export GEMINI_API_KEY="발급받은_키"')
        print('       PowerShell  : $env:GEMINI_API_KEY="발급받은_키"')
        sys.exit(1)
    return gemini_key, kakao_key


# ---------------------------------------------------------------------------
# 공통: HTTP 오류 종류 구분
# ---------------------------------------------------------------------------
def classify_http_error(exc):
    status = exc.response.status_code if exc.response is not None else None
    if status in (401, 403):
        return "AUTH_ERROR", status
    if status == 429:
        return "QUOTA_ERROR", status
    return "HTTP_ERROR", status


# ---------------------------------------------------------------------------
# 3) Gemini 호출 (POST)
# ---------------------------------------------------------------------------
def call_gemini(api_key, prompt, json_mode=False):
    """Gemini에 프롬프트를 보내고 응답 텍스트를 돌려준다."""
    model = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")
    url = GEMINI_URL.format(model=model)
    headers = {"Content-Type": "application/json", "x-goog-api-key": api_key}
    body = {"contents": [{"parts": [{"text": prompt}]}]}
    if json_mode:
        # JSON 형태로만 답하도록 요청하는 옵션
        body["generationConfig"] = {"responseMimeType": "application/json"}

    response = requests.post(url, headers=headers, json=body, timeout=TIMEOUT)
    response.raise_for_status()  # 4xx/5xx 응답이면 HTTPError 발생
    data = response.json()
    parts = data["candidates"][0]["content"]["parts"]
    return "".join(part.get("text", "") for part in parts)


# ---------------------------------------------------------------------------
# 4) 1단계: 여행지 추천 (LLM → JSON)
# ---------------------------------------------------------------------------
RECOMMEND_PROMPT = """너는 국내 여행 전문가야.
여행 날짜: {date}
이 시기에 여행하기 좋은 국내 지역 1곳을 추천해줘.

반드시 아래 형식의 JSON 객체 하나만 출력해. 설명, 마크다운, 코드블록은 넣지 마.
{{
  "recommended_city": "도시 이름 (예: 제주, 강릉)",
  "weather": "해당 시기 일반적인 날씨 요약 (한 문장)",
  "events": ["행사/축제 후보 1~3개"],
  "reason": "추천 근거 2~4문장"
}}"""

RETRY_PROMPT = """여행 날짜 {date}에 갈 만한 국내 도시 1곳을 추천해.
이전 응답은 JSON으로 읽을 수 없었다. 이번에는 필수 키 4개만 담은 JSON 객체만 출력해.
다른 글자는 한 글자도 쓰지 마.
{{"recommended_city": "문자열", "weather": "문자열", "events": ["문자열"], "reason": "문자열"}}"""


def parse_recommendation(text):
    """LLM 응답 텍스트에서 JSON을 꺼내고, 필수 키와 타입을 검사한다."""
    cleaned = text.replace("```json", "").replace("```", "").strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("응답에서 JSON 객체를 찾을 수 없습니다.")
    data = json.loads(cleaned[start:end + 1])

    for key in ("recommended_city", "weather", "reason"):
        if not isinstance(data.get(key), str) or not data[key].strip():
            raise ValueError(f"'{key}' 키가 없거나 문자열이 아닙니다.")
    events = data.get("events")
    if not isinstance(events, list) or not events or not all(isinstance(e, str) for e in events):
        raise ValueError("'events' 키가 없거나 문자열 배열이 아닙니다.")

    return {
        "recommended_city": data["recommended_city"].strip(),
        "weather": data["weather"].strip(),
        "events": events[:3],
        "reason": data["reason"].strip(),
    }


def step1_recommend(api_key, date):
    """최초 요청 1회 + 파싱 실패 시 재시도 1회 (최대 2번, 무한 재시도 금지)."""
    prompts = [RECOMMEND_PROMPT.format(date=date), RETRY_PROMPT.format(date=date)]
    for attempt, prompt in enumerate(prompts, start=1):
        try:
            text = call_gemini(api_key, prompt, json_mode=True)
            return parse_recommendation(text)
        except requests.HTTPError as exc:
            err_type, status = classify_http_error(exc)
            add_error("recommend", err_type, f"HTTP {status}")
            print(f"    - 오류: LLM API 호출 실패(HTTP {status}). 키/쿼터를 확인하세요.")
            return None  # 추천 도시가 없으면 다음 단계를 진행할 수 없음
        except requests.RequestException as exc:
            add_error("recommend", "NETWORK_ERROR", str(exc))
            print("    - 오류: 네트워크 문제로 LLM API에 연결하지 못했습니다.")
            return None
        except (ValueError, KeyError, IndexError) as exc:
            # json.JSONDecodeError도 ValueError의 한 종류
            add_error("recommend", "PARSE_ERROR", f"attempt {attempt}: {exc}")
            if attempt == 1:
                print("    - JSON 파싱 실패 → 필수 키만 다시 요청합니다(재시도 1회).")
            else:
                print("    - 재시도도 실패했습니다.")
    return None


# ---------------------------------------------------------------------------
# 5) 2단계: 맛집 검색 (Kakao Local, GET)
# ---------------------------------------------------------------------------
def step2_search_restaurants(api_key, city):
    """실패하거나 0건이어도 프로그램을 멈추지 않고 빈 리스트를 돌려준다."""
    query = f"{city} 맛집"
    headers = {"Authorization": f"KakaoAK {api_key}"}
    params = {"query": query, "category_group_code": "FD6", "size": RESTAURANT_COUNT}

    try:
        response = requests.get(KAKAO_URL, headers=headers, params=params, timeout=TIMEOUT)
        response.raise_for_status()
        documents = response.json().get("documents", [])
    except requests.HTTPError as exc:
        err_type, status = classify_http_error(exc)
        add_error("place_search", err_type, f"HTTP {status}")
        if err_type == "AUTH_ERROR":
            print(f"    - 오류: 인증 실패({status}). 키 설정을 확인하세요.")
        else:
            print(f"    - 오류: 장소 검색 실패(HTTP {status}).")
        print("    - 맛집 섹션은 '데이터 없음'으로 처리하고 계속 진행합니다.")
        return []
    except requests.RequestException as exc:
        add_error("place_search", "NETWORK_ERROR", str(exc))
        print("    - 오류: 네트워크 문제로 장소 검색에 실패했습니다. 계속 진행합니다.")
        return []
    except ValueError as exc:
        add_error("place_search", "PARSE_ERROR", str(exc))
        print("    - 오류: 장소 검색 응답을 읽지 못했습니다. 계속 진행합니다.")
        return []

    if not documents:
        add_error("place_search", "EMPTY_RESULT", f"0 results for query={query}")
        print("    - 검색 결과 0건 → 다음 단계로 진행합니다.")
        return []

    restaurants = []
    for doc in documents:
        restaurants.append({
            "name": doc.get("place_name", ""),
            "address": doc.get("road_address_name") or doc.get("address_name", ""),
            "category": doc.get("category_name", ""),
            "url": doc.get("place_url", ""),
            "x": float(doc["x"]) if doc.get("x") else None,  # 경도(lng)
            "y": float(doc["y"]) if doc.get("y") else None,  # 위도(lat)
        })
    print(f"    - 맛집 {len(restaurants)}곳 검색 완료")
    return restaurants


# ---------------------------------------------------------------------------
# 6) 3단계: 최종 리포트 생성 (LLM → Markdown)
# ---------------------------------------------------------------------------
REPORT_PROMPT = """너는 국내 여행 리포트 작성자야. 아래 데이터만 사용해서 한국어 Markdown 리포트를 작성해.

[여행 날짜] {date}
[1차 추천 데이터] {recommendation}
[맛집 목록] {restaurants}

규칙:
- 아래 제목 구조를 그대로 사용해.
  # {date} 국내 여행 추천 리포트
  ## 추천 지역
  ## 추천 이유
  ## 날씨 요약
  ## 행사/축제
  ## 맛집 추천
  ## 1일 일정 제안   (오전 / 오후 / 저녁으로 나눠서)
- 맛집은 목록에 있는 가게만 쓰고 이름, 주소, 링크를 표기해. 새로 지어내지 마.
- 맛집 목록이 비어 있으면 "## 맛집 추천" 아래에 "- 데이터 없음 (장소 검색 결과 0건 또는 검색 실패)"이라고만 써.
- 오류 요약 섹션은 쓰지 마(프로그램이 따로 붙인다).
- 코드블록(```)으로 감싸지 말고 Markdown 본문만 출력해."""


def build_fallback_report(date, rec, restaurants):
    """LLM 리포트 생성이 실패했을 때 프로그램이 직접 만드는 기본 리포트."""
    lines = [
        f"# {date} 국내 여행 추천 리포트",
        "## 추천 지역", rec["recommended_city"], "",
        "## 추천 이유", rec["reason"], "",
        "## 날씨 요약", rec["weather"], "",
        "## 행사/축제", *[f"- {e}" for e in rec["events"]], "",
        "## 맛집 추천",
    ]
    if restaurants:
        lines += [f"- [{r['name']}]({r['url']}) — {r['address']}" for r in restaurants]
    else:
        lines.append("- 데이터 없음 (장소 검색 결과 0건 또는 검색 실패)")
    lines += ["", "## 1일 일정 제안", "- 데이터 없음 (리포트 생성 실패로 기본 형식만 제공)"]
    return "\n".join(lines)


def step3_make_report(api_key, date, rec, restaurants):
    prompt = REPORT_PROMPT.format(
        date=date,
        recommendation=json.dumps(rec, ensure_ascii=False),
        restaurants=json.dumps(restaurants, ensure_ascii=False),
    )
    try:
        text = call_gemini(api_key, prompt)
        text = text.replace("```markdown", "").replace("```", "").strip()
        if not text:
            raise ValueError("빈 응답")
        print("    - 리포트 생성 완료")
        return text
    except requests.HTTPError as exc:
        err_type, status = classify_http_error(exc)
        add_error("report", err_type, f"HTTP {status}")
    except requests.RequestException as exc:
        add_error("report", "NETWORK_ERROR", str(exc))
    except (ValueError, KeyError, IndexError) as exc:
        add_error("report", "PARSE_ERROR", str(exc))
    print("    - 오류: LLM 리포트 생성 실패 → 기본 형식으로 리포트를 만듭니다.")
    return build_fallback_report(date, rec, restaurants)


def build_errors_section():
    lines = ["", "## 오류 요약(errors)"]
    if not errors:
        lines.append("- 없음")
    else:
        lines += [f"- [{e['step']}] {e['type']}: {e['message']}" for e in errors]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# 7) 저장 / 캐시
# ---------------------------------------------------------------------------
def save_raw(path, date, rec, restaurants):
    data = {
        "date": date,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "recommendation": rec,
        "restaurants": restaurants,
        "errors": errors,
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_cache(path):
    """같은 날짜로 저장된 원본 JSON이 있으면 불러온다(보너스: 캐싱)."""
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("recommendation"):
            return data
    except (json.JSONDecodeError, OSError):
        pass
    return None


# ---------------------------------------------------------------------------
# 메인 흐름
# ---------------------------------------------------------------------------
def main():
    args = parse_args()
    gemini_key, kakao_key = load_api_keys()

    RESULTS_DIR.mkdir(exist_ok=True)
    raw_path = RESULTS_DIR / f"{args.date}_raw.json"
    report_path = RESULTS_DIR / f"{args.date}_travel_plan.md"

    cached = None if args.no_cache else load_cache(raw_path)
    if cached:
        print(f"[캐시] {raw_path.name} 을(를) 찾았습니다. 1~2단계 API 호출을 건너뜁니다.")
        rec = cached["recommendation"]
        restaurants = cached.get("restaurants", [])
        errors.extend(cached.get("errors", []))
    else:
        print("[1/3] 1차 추천 생성 중(LLM)...")
        rec = step1_recommend(gemini_key, args.date)
        if rec is None:
            save_raw(raw_path, args.date, None, [])
            print(f"\n추천 결과를 얻지 못해 종료합니다. 오류 내용: {raw_path}")
            sys.exit(1)
        print(f'    - recommended_city: "{rec["recommended_city"]}"')

        print("[2/3] 맛집 검색 중(지도/장소 API)...")
        restaurants = step2_search_restaurants(kakao_key, rec["recommended_city"])
        save_raw(raw_path, args.date, rec, restaurants)

    print("[3/3] 최종 리포트 생성 중(LLM)...")
    report = step3_make_report(gemini_key, args.date, rec, restaurants)
    report += "\n" + build_errors_section()

    report_path.write_text(report, encoding="utf-8")
    save_raw(raw_path, args.date, rec, restaurants)  # 3단계 오류까지 반영해 다시 저장

    print(f"\n완료! {report_path.relative_to(RESULTS_DIR.parent)} 를 확인하세요.")
    print(f"      원본 데이터: {raw_path.relative_to(RESULTS_DIR.parent)}")


if __name__ == "__main__":
    main()
