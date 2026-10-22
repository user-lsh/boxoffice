from datetime import date, datetime, timedelta, timezone

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


def rank_change(value):
    if value > 0:
        return f"▲ {value}"
    if value < 0:
        return f"▼ {abs(value)}"
    return "—"


def rank_colors(values):
    colors = []
    for value in values:
        if value > 0:
            colors.append("color: #d32f2f;")
        elif value < 0:
            colors.append("color: #1976d2;")
        else:
            colors.append("")
    return colors


st.set_page_config(
    page_title="날짜별 박스오피스",
    page_icon="🎬",
    layout="wide",
)
st.title("🎬 날짜별 박스오피스")

# 서버 시간대에 상관없이 한국 시간으로 어제를 계산합니다.
kst = timezone(timedelta(hours=9))
yesterday = datetime.now(kst).date() - timedelta(days=1)

selected_date = st.date_input(
    "조회 날짜",
    value=yesterday,
    min_value=date(1900, 1, 1),
    max_value=yesterday,
    format="YYYY-MM-DD",
)

if selected_date is None:
    st.info("조회할 날짜를 선택해 주세요.")
    st.stop()

st.caption(
    f"조회일: {selected_date:%Y년 %m월 %d일}"
    " · 한국 시간 기준 · 자료: 영화진흥위원회 KOBIS"
)

# 인증키는 Secrets에서만 읽습니다.
try:
    api_key = st.secrets["KOBIS_KEY"]
except (KeyError, FileNotFoundError):
    st.error('Secrets에 KOBIS_KEY = "발급받은 인증키"를 등록해 주세요.')
    st.stop()

if not isinstance(api_key, str) or not api_key.strip():
    st.error("Secrets의 KOBIS_KEY가 비어 있거나 올바른 문자열이 아닙니다.")
    st.stop()

if st.button("새로고침"):
    load_movies.clear()

with st.spinner("박스오피스를 불러오는 중입니다…"):
    movies, error = load_movies(
        selected_date.strftime("%Y%m%d"),
        api_key.strip(),
    )

if error:
    st.error(error)
    st.info("확인 후 위의 ‘새로고침’을 눌러 주세요.")
    st.stop()

if not movies:
    st.info("그날은 아직 집계 전입니다")
    st.stop()

# API의 숫자 문자열을 실제 숫자로 변환합니다.
df = pd.DataFrame(movies)

columns = {
    "rank": "순위",
    "rankInten": "순위 변동",
    "movieNm": "영화명",
    "openDt": "개봉일",
    "audiCnt": "관객수",
    "audiAcc": "누적관객",
    "scrnCnt": "스크린수",
}

if not set(columns).issubset(df.columns):
    st.error("필수 영화 정보가 누락됐습니다. KOBIS 자료 상태를 확인해 주세요.")
    st.stop()

for col in ["rank", "rankInten", "audiCnt", "audiAcc", "scrnCnt"]:
    numbers = pd.to_numeric(df[col], errors="coerce")
    invalid_number = numbers.isna().any() or (numbers % 1 != 0).any()
    invalid_negative = col != "rankInten" and (numbers < 0).any()

    if invalid_number or invalid_negative:
        st.error("숫자 정보가 올바르지 않습니다. KOBIS 자료 상태를 확인해 주세요.")
        st.stop()

    df[col] = numbers.astype("int64")

df = df.sort_values("rank")

# 정확히 100만 명일 때는 붙이지 않고, 초과할 때만 붙입니다.
df["movieNm"] = df["movieNm"].astype(str)
df["movieNm"] += df["audiAcc"].apply(
    lambda count: " 🏆" if count > 1_000_000 else ""
)

first_place = df[df["rank"] == 1]

if not first_place.empty:
    top = first_place.iloc[0]
    st.subheader(f"1위 · {top['movieNm']}")

    card1, card2, card3 = st.columns(3)
    card1.metric("관객수", f"{top['audiCnt']:,}명")
    card2.metric("누적관객", f"{top['audiAcc']:,}명")
    card3.metric("스크린수", f"{top['scrnCnt']:,}개")
else:
    st.warning("응답에 1위 영화가 없습니다. KOBIS 집계 상태를 확인해 주세요.")

# 숫자로 보관한 순위 변동을 화살표로 표시하고 색상을 적용합니다.
st.subheader("전체 순위")

table = df[list(columns)].rename(columns=columns)
styled_table = table.style.apply(
    rank_colors,
    subset=["순위 변동"],
)
styled_table = styled_table.format({
    "순위 변동": rank_change,
    "관객수": "{:,}",
    "누적관객": "{:,}",
    "스크린수": "{:,}",
})

st.dataframe(
    styled_table,
    hide_index=True,
    use_container_width=True,
)
st.caption(
    "빨간 ▲: 순위 상승 · 파란 ▼: 순위 하락"
    " · —: 변동 없음 · 🏆: 누적관객 100만 명 초과"
)

st.subheader("관객수 상위 5편")

top5 = df.sort_values("audiCnt", ascending=False).head(5).copy()
top5["영화"] = top5["rank"].astype(str) + "위 · " + top5["movieNm"]

chart = top5.set_index("영화")[["audiCnt"]].rename(
    columns={"audiCnt": "관객수"}
)
st.bar_chart(chart, sort=False)
