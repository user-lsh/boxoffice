from datetime import datetime, timedelta, timezone

import pandas as pd
import requests
import streamlit as st

# 화면의 제목과 너비를 설정합니다.
st.set_page_config(
    page_title="어제의 박스오피스", page_icon="🎬", layout="wide"
)
st.title("🎬 어제의 박스오피스")

# 서버의 시간대와 관계없이 한국 시간(UTC+9)으로 어제를 계산합니다.
kst = timezone(timedelta(hours=9))
yesterday = datetime.now(kst).date() - timedelta(days=1)
target_date = yesterday.strftime("%Y%m%d")
st.caption(
    f"조회일: {yesterday:%Y년 %m월 %d일} · 한국 시간 기준"
    " · 자료: 영화진흥위원회 KOBIS"
)

# 인증키는 코드에 적지 않고 Streamlit의 Secrets에서만 가져옵니다.
try:
    api_key = st.secrets["KOBIS_KEY"]
except (KeyError, FileNotFoundError):
    st.error(
        '인증키 설정이 없습니다. Streamlit Cloud의 Secrets에 '
        'KOBIS_KEY = "발급받은 인증키"를 등록해 주세요.'
    )
    st.stop()

if not isinstance(api_key, str) or not api_key.strip():
    st.error(
        "KOBIS_KEY가 비어 있거나 문자열이 아닙니다. "
        "Secrets의 인증키 설정을 확인해 주세요."
    )
    st.stop()


# 같은 날짜의 정상 응답은 10분간 재사용해 API 호출을 줄입니다.
# 날짜도 함수 인수이므로 날짜가 바뀌면 새로운 자료를 요청합니다.
@st.cache_data(ttl=600, show_spinner=False)
def load_movies(date_text, key):
    url = (
        "https://www.kobis.or.kr/kobisopenapi/webservice/rest/"
        "boxoffice/searchDailyBoxOfficeList.json"
    )
    try:
        response = requests.get(
            url,
            params={"key": key, "targetDt": date_text},
            timeout=15,
        )
        response.raise_for_status()
    except requests.exceptions.Timeout:
        raise ValueError(
            "응답 시간이 초과됐습니다. 잠시 후 다시 시도하고 "
            "KOBIS 서비스 상태를 확인해 주세요."
        ) from None
    except requests.exceptions.RequestException:
        # 예외 원문에 인증키가 포함될 수 있어 출력하지 않습니다.
        raise ValueError(
            "요청에 실패했습니다. 인터넷 연결, KOBIS 서비스 상태와 "
            "API 이용 한도를 확인해 주세요."
        ) from None

    try:
        data = response.json()
    except ValueError:
        raise ValueError(
            "정상적인 JSON 응답이 아닙니다. KOBIS 점검 여부를 확인하고 "
            "잠시 후 다시 시도해 주세요."
        ) from None

    if not isinstance(data, dict):
        raise ValueError(
            "응답 형식이 예상과 다릅니다. "
            "KOBIS 서비스 상태와 요청 주소를 확인해 주세요."
        )

    # 인증 오류는 HTTP 200이어도 faultInfo로 전달될 수 있습니다.
    if "faultInfo" in data:
        raise ValueError(
            "KOBIS가 오류 응답(faultInfo)을 보냈습니다. "
            "Secrets의 KOBIS_KEY가 정확한지, 인증키가 유효한지, "
            "이용 한도를 초과했는지 확인해 주세요."
        )

    result = data.get("boxOfficeResult")
    if not isinstance(result, dict):
        raise ValueError(
            "박스오피스 결과가 없습니다. "
            "요청 주소와 KOBIS 서비스 상태를 확인해 주세요."
        )

    movies = result.get("dailyBoxOfficeList")
    if not isinstance(movies, list):
        raise ValueError(
            "영화 목록의 형식이 올바르지 않습니다. "
            "KOBIS 응답 형식과 서비스 상태를 확인해 주세요."
        )
    if not movies:
        raise ValueError(
            "어제의 영화 목록이 아직 비어 있습니다. "
            "집계가 늦어질 수 있으니 조회 날짜를 확인하고 "
            "잠시 후 다시 시도해 주세요."
        )
    if not all(isinstance(movie, dict) for movie in movies):
        raise ValueError(
            "영화 정보 형식이 올바르지 않습니다. "
            "KOBIS 서비스 상태를 확인해 주세요."
        )
    return movies


if st.button("새로고침"):
    load_movies.clear()

try:
    with st.spinner("어제의 박스오피스를 불러오는 중입니다…"):
        movies = load_movies(target_date, api_key.strip())

    df = pd.DataFrame(movies)
    columns = {
        "rank": "순위",
        "movieNm": "영화명",
        "openDt": "개봉일",
        "audiCnt": "관객수",
        "audiAcc": "누적관객",
        "scrnCnt": "스크린수",
    }

    if not set(columns).issubset(df.columns):
        raise ValueError(
            "필수 영화 정보가 누락됐습니다. "
            "KOBIS 응답 형식을 확인하고 다시 시도해 주세요."
        )

    # 문자열로 받은 숫자를 정수로 바꿔 정렬과 그래프에 사용합니다.
    for col in ["rank", "audiCnt", "audiAcc", "scrnCnt"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
        if (
            df[col].isna().any()
            or (df[col] < 0).any()
            or (df[col] % 1 != 0).any()
        ):
            raise ValueError(
                "숫자 정보가 올바르지 않습니다. "
                "KOBIS 자료 상태를 확인하고 다시 시도해 주세요."
            )
        df[col] = df[col].astype("int64")

    df = df.sort_values("rank")

except ValueError as error:
    st.error(str(error))
    st.info(
        "설정을 수정했거나 잠시 기다린 뒤 "
        "위의 ‘새로고침’을 눌러 주세요."
    )
    st.stop()

# 1위 영화의 주요 수치를 카드 세 장으로 표시합니다.
first_place = df[df["rank"] == 1]
if not first_place.empty:
    top = first_place.iloc[0]
    st.subheader(f"🏆 1위 · {top['movieNm']}")

    card1, card2, card3 = st.columns(3)
    card1.metric("관객수", f"{top['audiCnt']:,}명")
    card2.metric("누적관객", f"{top['audiAcc']:,}명")
    card3.metric("스크린수", f"{top['scrnCnt']:,}개")
else:
    st.warning(
        "응답에 1위 영화가 없습니다. KOBIS 집계 상태를 확인해 주세요."
    )

st.subheader("전체 순위")
st.dataframe(
    df[list(columns)].rename(columns=columns),
    hide_index=True,
    use_container_width=True,
)

# 관객수가 많은 순서로 최대 다섯 편을 선택합니다.
st.subheader("관객수 상위 5편")
top5 = df.sort_values("audiCnt", ascending=False).head(5).copy()

# 같은 제목이 있어도 구별하도록 순위를 함께 표시합니다.
top5["영화"] = (
    top5["rank"].astype(str) + "위 · " + top5["movieNm"]
)
st.bar_chart(
    top5.set_index("영화")[["audiCnt"]].rename(
        columns={"audiCnt": "관객수"}
    ),
    sort=False,
)
