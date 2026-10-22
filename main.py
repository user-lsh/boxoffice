from datetime import date, datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
from html import escape

import pandas as pd
import requests
import streamlit as st


# 박스오피스 자료를 불러옵니다.
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


# 위키백과에서 포스터를 찾아 하루 동안 저장합니다.
@st.cache_data(ttl=86400, show_spinner=False)
def load_poster(movie_name, open_date, movie_code, api_key):
    headers = {
        "User-Agent": "BoxOfficeStudentApp/1.0 (Streamlit educational project)"
    }
    year = str(open_date)[:4]

    korean_titles = [
        f"{movie_name} ({year}년 영화)",
        f"{movie_name} (영화)",
        movie_name,
    ]

    def wiki_poster(language, titles):
        try:
            response = requests.get(
                f"https://{language}.wikipedia.org/w/api.php",
                params={
                    "action": "query",
                    "format": "json",
                    "formatversion": 2,
                    "prop": "pageimages|info",
                    "inprop": "url",
                    "redirects": 1,
                    "titles": "|".join(titles),
                    "piprop": "thumbnail|name",
                    "pithumbsize": 400,
                    "pilicense": "any",
                },
                headers=headers,
                timeout=6,
            )
            response.raise_for_status()
            data = response.json()
            pages = data.get("query", {}).get("pages", [])

            for page in pages:
                thumbnail = page.get("thumbnail", {})
                filename = page.get("pageimage", "").lower()
                image_url = thumbnail.get("source", "")

                # 배우 사진이나 로고가 표시되는 것을 줄입니다.
                is_poster = "poster" in filename or "포스터" in filename
                is_portrait = (
                    thumbnail.get("height", 0)
                    > thumbnail.get("width", 0)
                )
                valid_url = image_url.startswith(
                    "https://upload.wikimedia.org/"
                )

                if is_poster and is_portrait and valid_url:
                    return {
                        "url": image_url,
                        "source": page.get("fullurl", ""),
                    }

        except (
            requests.exceptions.RequestException,
            ValueError,
            TypeError,
            AttributeError,
        ):
            pass

        return None

    poster = wiki_poster("ko", korean_titles)
    if poster:
        return poster

    # 한국어 문서에서 못 찾으면 영문 제목으로도 조회합니다.
    if not movie_code:
        return None

    try:
        response = requests.get(
            "https://www.kobis.or.kr/kobisopenapi/webservice/rest/movie/searchMovieInfo.json",
            params={"key": api_key, "movieCd": movie_code},
            timeout=6,
        )
        response.raise_for_status()

        info = (
            response.json()
            .get("movieInfoResult", {})
            .get("movieInfo", {})
        )
        english_name = info.get("movieNmEn", "").strip()
        production_year = str(info.get("prdtYear", year))

    except (
        requests.exceptions.RequestException,
        ValueError,
        TypeError,
        AttributeError,
    ):
        return None

    if not english_name:
        return None

    english_titles = [
        f"{english_name} ({production_year} film)",
        f"{english_name} (film)",
        english_name,
    ]
    return wiki_poster("en", english_titles)


# 순위 증감을 화살표로 표시합니다.
def rank_change(value):
    if value > 0:
        return f"▲ {value}"
    if value < 0:
        return f"▼ {abs(value)}"
    return "—"


# 어두운 배경에서도 잘 보이는 빨강과 파랑을 사용합니다.
def rank_colors(values):
    colors = []

    for value in values:
        if value > 0:
            colors.append("color: #ff7676;")
        elif value < 0:
            colors.append("color: #78b5ff;")
        else:
            colors.append("")

    return colors


st.set_page_config(
    page_title="날짜별 박스오피스",
    page_icon="🎬",
    layout="wide",
)

# 검은 배경과 포스터 카드 디자인입니다.
st.markdown(
    """
<style>
.stApp,
[data-testid="stAppViewContainer"],
[data-testid="stMain"] {
    background: #08090c;
    color: #f2f3f5;
}

[data-testid="stHeader"] {
    background: #08090c;
}

h1, h2, h3, p, label,
[data-testid="stMetricValue"] {
    color: #f2f3f5;
}

[data-testid="stCaptionContainer"] p {
    color: #a9b0bf;
}

[data-testid="stMetric"] {
    background: #141720;
    border: 1px solid #2b3040;
    border-radius: 16px;
    padding: 20px;
}

.stButton button {
    background: #202633;
    color: #fafafa;
    border: 1px solid #40485c;
}

.stButton button:hover {
    border-color: #e6b85c;
    color: #e6b85c;
}

.poster-grid {
    display: grid;
    grid-template-columns: repeat(5, minmax(0, 1fr));
    gap: 16px;
}

.poster-card {
    background: #141720;
    border: 1px solid #2b3040;
    border-radius: 14px;
    overflow: hidden;
}

.poster-card img {
    width: 100%;
    aspect-ratio: 2 / 3;
    object-fit: contain;
    display: block;
    background: #0d0f14;
}

.poster-empty {
    aspect-ratio: 2 / 3;
    display: flex;
    align-items: center;
    justify-content: center;
    flex-direction: column;
    background: #1b1f2a;
    color: #a9b0bf;
    text-align: center;
}

.poster-details {
    padding: 14px;
}

.poster-rank {
    color: #e6b85c;
    font-weight: bold;
    font-size: 14px;
}

.poster-name {
    color: #f2f3f5;
    font-size: 17px;
    font-weight: bold;
    margin: 8px 0;
    overflow-wrap: anywhere;
}

.poster-count {
    color: #f2f3f5;
    font-size: 20px;
    font-weight: bold;
}

.poster-note,
.poster-details a {
    color: #a9b0bf;
    font-size: 12px;
}

@media (max-width: 900px) {
    .poster-grid {
        grid-template-columns: repeat(3, minmax(0, 1fr));
    }
}

@media (max-width: 550px) {
    .poster-grid {
        grid-template-columns: repeat(2, minmax(0, 1fr));
    }
}
</style>
""",
    unsafe_allow_html=True,
)

st.title("🎬 날짜별 박스오피스")

# 한국 시간 기준으로 어제를 계산합니다.
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

# 인증키는 기존 Secrets 설정을 사용합니다.
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
    load_poster.clear()

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

# 문자열로 받은 숫자를 정수로 바꿉니다.
for col in ["rank", "rankInten", "audiCnt", "audiAcc", "scrnCnt"]:
    numbers = pd.to_numeric(df[col], errors="coerce")
    invalid_number = numbers.isna().any() or (numbers % 1 != 0).any()
    invalid_negative = col != "rankInten" and (numbers < 0).any()

    if invalid_number or invalid_negative:
        st.error("숫자 정보가 올바르지 않습니다. KOBIS 자료 상태를 확인해 주세요.")
        st.stop()

    df[col] = numbers.astype("int64")

df = df.sort_values("rank")

# 포스터 검색에는 트로피가 없는 원래 영화명을 사용합니다.
df["original_name"] = df["movieNm"].astype(str)
df["movieNm"] = df["movieNm"].astype(str)

# 누적관객이 100만 명을 초과하면 트로피를 붙입니다.
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

st.subheader("전체 순위")

table = df[list(columns)].rename(columns=columns)

styled_table = table.style.set_properties(
    **{
        "background-color": "#141720",
        "color": "#f2f3f5",
    }
)
styled_table = styled_table.apply(
    rank_colors,
    subset=["순위 변동"],
)
styled_table = styled_table.format(
    {
        "순위 변동": rank_change,
        "관객수": "{:,}",
        "누적관객": "{:,}",
        "스크린수": "{:,}",
    }
)

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
records = top5.to_dict("records")


def poster_for_movie(movie):
    return load_poster(
        movie["original_name"],
        movie["openDt"],
        movie.get("movieCd", ""),
        api_key.strip(),
    )


# 최대 다섯 편의 포스터를 동시에 조회합니다.
with st.spinner("영화 포스터를 찾는 중입니다…"):
    with ThreadPoolExecutor(max_workers=5) as pool:
        posters = list(pool.map(poster_for_movie, records))

cards = []

for movie, poster in zip(records, posters):
    if poster:
        image_url = escape(poster["url"], quote=True)
        image_title = escape(movie["original_name"], quote=True)

        picture = (
            f'<img src="{image_url}" '
            f'alt="{image_title} 포스터" loading="lazy">'
        )

        source = poster.get("source", "")
        source_link = ""

        if source.startswith(
            ("https://ko.wikipedia.org/", "https://en.wikipedia.org/")
        ):
            safe_source = escape(source, quote=True)
            source_link = (
                f'<a href="{safe_source}" target="_blank" '
                'rel="noopener noreferrer">'
                '포스터 출처 · 위키백과</a>'
            )
    else:
        picture = (
            '<div class="poster-empty">'
            '<span style="font-size:40px">🎬</span>'
            '<span>포스터를 찾지 못했어요</span>'
            '</div>'
        )
        source_link = '<span class="poster-note">포스터 정보 없음</span>'

    movie_rank = int(movie["rank"])
    movie_name = escape(movie["movieNm"])
    audience = int(movie["audiCnt"])

    card = (
        '<div class="poster-card">'
        + picture
        + '<div class="poster-details">'
        + f'<div class="poster-rank">{movie_rank}위</div>'
        + f'<div class="poster-name">{movie_name}</div>'
        + f'<div class="poster-count">{audience:,}명</div>'
        + '<div class="poster-note">선택한 날짜의 관객수</div>'
        + source_link
        + '</div></div>'
    )
    cards.append(card)

st.markdown(
    '<div class="poster-grid">' + "".join(cards) + "</div>",
    unsafe_allow_html=True,
)

st.caption(
    "포스터는 위키백과에서 조회하며, 제공되지 않거나 "
    "연결이 실패하면 안내 문구가 표시됩니다."
)

top5["영화"] = (
    top5["rank"].astype(str) + "위 · " + top5["movieNm"]
)

chart = top5.set_index("영화")[["audiCnt"]].rename(
    columns={"audiCnt": "관객수"}
)

# 확대·이동 기능이 없는 고정형 막대그래프입니다.
st.vega_lite_chart(
    chart.reset_index(),
    {
        "mark": {"type": "bar", "color": "#e6b85c"},
        "encoding": {
            "x": {
                "field": "영화",
                "type": "nominal",
                "sort": None,
            },
            "y": {
                "field": "관객수",
                "type": "quantitative",
            },
            "tooltip": [
                {"field": "영화", "type": "nominal"},
                {
                    "field": "관객수",
                    "type": "quantitative",
                    "format": ",",
                },
            ],
        },
        "config": {
            "background": "#08090c",
            "view": {"stroke": None},
            "axis": {
                "labelColor": "#c8ceda",
                "titleColor": "#f2f3f5",
                "gridColor": "#2b3040",
                "domainColor": "#40485c",
            },
        },
    },
    use_container_width=True,
)
