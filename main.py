from datetime import date, datetime, timedelta, timezone

import pandas as pd
import requests
import streamlit as st

# 화면의 제목과 너비를 설정합니다.
st.set_page_config(page_title="날짜별 박스오피스", page_icon="🎬", layout="wide")
st.title("🎬 날짜별 박스오피스")

# 서버의 시간대와 관계없이 한국 시간(UTC+9)으로 어제를 계산합니다.
kst = timezone(timedelta(hours=9))
yesterday = datetime.now(kst).date() - timedelta(days=1)
# 기본값은 어제이고, 오늘 이후 날짜는 선택할 수 없습니다.
selected_date = st.date_input(
    "조회 날짜", value=yesterday, min_value=date(1900, 1, 1),
    max_value=yesterday, format="YYYY-MM-DD",
)
if selected_date is None:
    st.info("달력에서 조회할 날짜를 선택해 주세요.")
    st.stop()
target_date = selected_date.strftime("%Y%m%d")
st.caption(f"조회일: {selected_date:%Y년 %m월 %d일} · 한국 시간 기준 · 자료: 영화진흥위원회 KOBIS")

# 인증키는 코드에 적지 않고 Streamlit의 Secrets에서만 가져옵니다.
try:
    api_key = st.secrets["KOBIS_KEY"]
except (KeyError, FileNotFoundError):
    st.error('인증키 설정이 없습니다. Streamlit Cloud의 Secrets에 KOBIS_KEY = "발급받은 인증키"를 등록해 주세요.')
    st.stop()

if not isinstance(api_key, str) or not api_key.strip():
    st.error("KOBIS_KEY가 비어 있거나 문자열이 아닙니다. Secrets의 인증키 설정을 확인해 주세요.")
    st.stop()


# 같은 날짜의 정상 응답은 10분간 재사용해 불필요한 API 호출을 줄입니다.
# 날짜도 함수 인수이므로 날짜가 바뀌면 새로운 자료를 요청합니다.
@st.cache_data(ttl=600, show_spinner=False)
def load_movies(date_text, key):
    url = "https://www.kobis.or.kr/kobisopenapi/webservice/rest/boxoffice/searchDailyBoxOfficeList.json"
    try:
        response = requests.get(
            url, params={"key": key, "targetDt": date_text}, timeout=15
        )
        response.raise_for_status()
    except requests.exceptions.Timeout:
        raise ValueError("응답 시간이 초과됐습니다. 잠시 후 다시 시도하고 KOBIS 서비스 상태를 확인해 주세요.") from None
    except requests.exceptions.RequestException:
        # 예외 원문에는 인증키가 포함된 URL이 있을 수 있어 출력하지 않습니다.
        raise ValueError("요청에 실패했습니다. 인터넷 연결, KOBIS 서비스 상태와 API 이용 한도를 확인해 주세요.") from None

    try:
        data = response.json()
    except ValueError:
        raise ValueError("정상적인 JSON 응답이 아닙니다. KOBIS 점검 여부를 확인하고 잠시 후 다시 시도해 주세요.") from None

    if not isinstance(data, dict):
        raise ValueError("응답 형식이 예상과 다릅니다. KOBIS 서비스 상태와 요청 주소를 확인해 주세요.")

    # 인증 오류는 HTTP 200이어도 faultInfo로 전달될 수 있습니다.
    if "faultInfo" in data:
        raise ValueError("KOBIS가 오류 응답(faultInfo)을 보냈습니다. Secrets의 KOBIS_KEY가 정확한지, 인증키가 유효한지, 이용 한도를 초과했는지 확인해 주세요.")

    result = data.get("boxOfficeResult")
    if not isinstance(result, dict):
        raise ValueError("박스오피스 결과가 없습니다. 요청 주소와 KOBIS 서비스 상태를 확인해 주세요.")
    movies = result.get("dailyBoxOfficeList")
    if not isinstance(movies, list):
        raise ValueError("영화 목록의 형식이 올바르지 않습니다. KOBIS 응답 형식과 서비스 상태를 확인해 주세요.")
    if not all(isinstance(movie, dict) for movie in movies):
        raise ValueError("영화 정보 형식이 올바르지 않습니다. KOBIS 서비스 상태를 확인해 주세요.")
    return movies


if st.button("새로고침"):
    load_movies.clear()

try:
    with st.spinner("선택한 날짜의 박스오피스를 불러오는 중입니다…"):
        movies = load_movies(target_date, api_key.strip())
    if not movies:
        st.info("그날은 아직 집계 전입니다")
        st.stop()
    df = pd.DataFrame(movies)
    columns = {
        "rank": "순위", "rankInten": "순위 변동", "movieNm": "영화명", "openDt": "개봉일",
        "audiCnt": "관객수", "audiAcc": "누적관객", "scrnCnt": "스크린수",
    }
    if not set(columns).issubset(df.columns):
        raise ValueError("필수 영화 정보가 누락됐습니다. KOBIS 응답 형식을 확인하고 다시 시도해 주세요.")
    # API의 숫자는 문자열이므로 표 정렬과 그래프를 위해 정수로 바꿉니다.
    for col in ["rank", "rankInten", "audiCnt", "audiAcc", "scrnCnt"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
        if (df[col].isna().any() or (df[col] % 1 != 0).any()
                or (col != "rankInten" and (df[col] < 0).any())):
