from datetime import date, datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
from html import escape

import pandas as pd
import requests
import streamlit as st


# 오류 원문에는 인증키가 포함될 수 있으므로 안내 문구만 반환합니다.
@st.cache_data(ttl=600, show_spinner=False)
def load_movies(target_date, api_key):
    url = (
        "https://www.kobis.or.kr/kobisopenapi/webservice/rest/"
        "boxoffice/searchDailyBoxOfficeList.json"
    )
    try:
        response = requests.get(
            url,
            params={"key": api_key, "targetDt": target_date},
            timeout=15,
        )
        response.raise_for_status()
    except requests.exceptions.Timeout:
        return None, "응답 시간이 초과됐습니다. 잠시 후 새로고침해 주세요."
    except requests.exceptions.RequestException:
        return None, "요청에 실패했습니다. 인터넷 연결과 KOBIS 서비스 상태, 이용 한도를 확인해 주세요."

    try:
        data = response.json()
    except ValueError:
        return None, "응답을 읽을 수 없습니다. KOBIS 점검 여부를 확인하고 다시 시도해 주세요."

    if not isinstance(data, dict):
        return None, "응답 형식이 올바르지 않습니다. KOBIS 서비스 상태를 확인해 주세요."
    if "faultInfo" in data:
        return None, "KOBIS 오류 응답입니다. Secrets의 KOBIS_KEY와 인증키 유효 여부, 이용 한도를 확인해 주세요."

    result = data.get("boxOfficeResult")
    if not isinstance(result, dict):
        return None, "박스오피스 결과가 없습니다. KOBIS 서비스 상태를 확인해 주세요."

    movies = result.get("dailyBoxOfficeList")
    if not isinstance(movies, list):
        return None, "영화 목록 형식이 올바르지 않습니다. KOBIS 서비스 상태를 확인해 주세요."
    if not all(isinstance(movie, dict) for movie in movies):
        return None, "영화 정보 형식이 올바르지 않습니다. 잠시 후 다시 시도해 주세요."
    return movies, None



# 포스터 조회 결과는 하루 동안 재사용합니다. 인증키는 외부로 보내지 않습니다.
@st.cache_data(ttl=86400, show_spinner=False)
def load_poster(movie_name, open_date, movie_code, api_key):
    headers = {"User-Agent": "BoxOfficeStudentApp/1.0 (Streamlit educational project)"}
    year = str(open_date)[:4]
    korean_titles = [f"{movie_name} ({year}년 영화)", f"{movie_name} (영화)", movie_name]

    def wiki_poster(language, titles):
        try:
            response = requests.get(
                f"https://{language}.wikipedia.org/w/api.php",
                params={
                    "action": "query", "format": "json", "formatversion": 2,
                    "prop": "pageimages|info", "inprop": "url", "redirects": 1,
                    "titles": "|".join(titles), "piprop": "thumbnail|name",
                    "pithumbsize": 400, "pilicense": "any",
                },
                headers=headers, timeout=6,
            )
            response.raise_for_status()
            data = response.json()
            pages = data.get("query", {}).get("pages", [])
            for page in pages:
                thumbnail = page.get("thumbnail", {})
                filename = page.get("pageimage", "").lower()
                image_url = thumbnail.get("source", "")
                # 배우 사진이나 로고를 포스터로 표시하지 않도록 확인합니다.
                is_poster = "poster" in filename or "포스터" in filename
                is_portrait = thumbnail.get("height", 0) > thumbnail.get("width", 0)
                if is_poster and is_portrait and image_url.startswith("https://upload.wikimedia.org/"):
                    return {"url": image_url, "source": page.get("fullurl", "")}
        except (requests.exceptions.RequestException, ValueError, TypeError, AttributeError):
            pass
        return None

    poster = wiki_poster("ko", korean_titles)
    if poster:
        return poster

    # 한국어 문서에서 못 찾으면 KOBIS의 영문 제목으로도 조회합니다.
    if not movie_code:
        return None
    try:
        response = requests.get(
            "https://www.kobis.or.kr/kobisopenapi/webservice/rest/movie/searchMovieInfo.json",
