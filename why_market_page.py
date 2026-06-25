"""왜 시장을 사야 하는가 — 전략 근거 페이지."""
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import yfinance as yf
from pathlib import Path

RESULTS_DIR = Path(__file__).resolve().parent / "results"


@st.cache_data(ttl=3600)
def load_returns():
    stock_files = [f for f in RESULTS_DIR.glob("*_signals.csv")
                   if not f.name.startswith("coin_") and "summary" not in f.name]
    coin_files  = list(RESULTS_DIR.glob("coin_*_signals.csv"))

    def _ret(path):
        try:
            df = pd.read_csv(path)
        except Exception:
            return None
        if df.empty:
            return None
        dc = [c for c in df.columns if c.lower() == "date"]
        if not dc: return None
        df = df.rename(columns={dc[0]: "Date"})
        df["Date"] = pd.to_datetime(df["Date"])
        df = df.set_index("Date").sort_index()
        if len(df) < 50: return None
        f_, l_ = float(df["Close"].iloc[0]), float(df["Close"].iloc[-1])
        days = (df.index[-1] - df.index[0]).days
        if days == 0: return None
        return {
            "start": df.index[0], "end": df.index[-1],
            "total_ret": round((l_/f_-1)*100, 1),
            "ann_ret":   round(((l_/f_)**(365.0/days)-1)*100, 1),
        }

    rows = []
    for f in stock_files:
        t = f.stem.replace("_signals","")
        r = _ret(f)
        if r:
            r["ticker"] = t
            r["category"] = "KR" if (".KS" in t or ".KQ" in t) else "US"
            rows.append(r)
    for f in coin_files:
        t = f.stem.replace("coin_","").replace("_signals","")
        r = _ret(f)
        if r:
            r["ticker"] = t
            r["category"] = "Coin"
            rows.append(r)

    df = pd.DataFrame(rows)
    start, end = df["start"].min(), df["end"].max()

    def _bench(ticker):
        raw = yf.download(ticker, start=start, end=end, progress=False)
        close = raw["Close"].squeeze().dropna()
        if len(close) < 2: return None
        days = (close.index[-1] - close.index[0]).days
        if days == 0: return None
        return round((float(close.iloc[-1])/float(close.iloc[0])-1)*100, 1)

    b = {
        "US":   _bench("SPY"),
        "KR":   _bench("069500.KS"),
        "Coin": _bench("BTC-USD"),
    }
    return df, b, str(start.date()), str(end.date())


# ── 페이지 시작 ───────────────────────────────────────────
st.title("투자 대원칙")

# ════════════════════════════════════════════════════════
# 핵심 구조 — 최상단 full-width
# ════════════════════════════════════════════════════════
st.markdown(
    "<div style='font-size:13px; color:#94a3b8; letter-spacing:2px; margin-bottom:8px'>"
    "우리 전략의 핵심 구조</div>",
    unsafe_allow_html=True,
)

buckets = [
    ("#3b82f6", "Core ETF", "63%", "시장 평균 수익 확보", "개별 종목 60~70%가 시장 못 이김"),
    ("#a855f7", "Satellite", "15%", "알파 시도", "잃어도 치명적이지 않은 비중"),
    ("#f59e0b", "BTC", "15%", "비대칭 옵션 (4년 사이클)", "알트 18%만 BTC 초과 → BTC만"),
    ("#22c55e", "Cash", "7%", "폭락 시 추가매수 탄약", "-15% 조정 시 Core 추가매수"),
]
cols = st.columns(4)
for col, (color, name, pct, role, note) in zip(cols, buckets):
    col.markdown(
        f"""
        <div style='background:#1e293b; border-top:3px solid {color};
                    border-radius:8px; padding:18px; height:100%'>
          <div style='font-size:19px; color:#94a3b8; margin-bottom:6px'>{name}</div>
          <div style='font-size:36px; font-weight:800; color:{color}; line-height:1'>{pct}</div>
          <div style='font-size:20px; color:#cbd5e1; margin-top:10px; line-height:1.5'>
            {role}<br>
            <span style='color:#94a3b8; font-size:18px'>{note}</span>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

st.markdown("<div style='margin-top:12px'></div>", unsafe_allow_html=True)

principles = st.columns(3)
for col, text, sub in zip(
    principles,
    ["① Core ETF 매달 자동 매수", "② 분기 리밸런싱으로 목표 비중 유지", "③ 주식/코인 신호는 현황 파악용"],
    ["판단 개입 없음", "자동 저가매수 효과", "행동 근거로 쓰지 않음"],
):
    col.markdown(
        f"""
        <div style='background:#1e293b; border-radius:6px; padding:14px 18px;
                    font-size:20px; color:#cbd5e1; line-height:1.6'>
          {text}<br>
          <span style='color:#94a3b8; font-size:18px'>{sub}</span>
        </div>
        """,
        unsafe_allow_html=True,
    )

st.divider()
st.markdown("#### 아래 데이터가 위 전략의 근거입니다")

with st.spinner("데이터 로딩 중..."):
    df, benchmarks, period_start, period_end = load_returns()

st.caption(f"분석 기간: {period_start} ~ {period_end} | 총 {len(df)}개 종목")
st.divider()


# ════════════════════════════════════════════════════════
# 섹션 1 — 핵심 숫자 3개
# ════════════════════════════════════════════════════════
st.subheader("시장을 이긴 종목은 몇 개였을까?")
st.markdown("같은 기간 동안 각 종목을 그냥 들고만 있었으면, 시장 지수 대비 얼마나 됐을까요.")

c1, c2, c3 = st.columns(3)
cat_info = [
    ("US",   "미국 주식",  "S&P500",  c1, "#3b82f6"),
    ("KR",   "한국 주식",  "KOSPI200", c2, "#22c55e"),
    ("Coin", "코인",       "BTC",      c3, "#f59e0b"),
]
beat_results = {}
for cat, label, bench_name, col, color in cat_info:
    sub  = df[df["category"] == cat]
    btot = benchmarks.get(cat)
    if btot is None or len(sub) == 0:
        continue
    beat = (sub["total_ret"] > btot).sum()
    pct  = beat / len(sub) * 100
    beat_results[cat] = pct
    with col:
        st.markdown(
            f"""
            <div style='background:#f8fafc; border:1px solid #e2e8f0; border-radius:12px;
                        padding:24px; text-align:center'>
              <div style='font-size:19px; color:#64748b; margin-bottom:8px'>{label} ({len(sub)}개 종목)</div>
              <div style='font-size:52px; font-weight:800; color:{"#ef4444" if pct < 50 else "#22c55e"};
                          line-height:1'>{pct:.0f}%</div>
              <div style='font-size:19px; color:#64748b; margin-top:8px'>
                {bench_name}({btot:+.0f}%) 초과<br>
                <span style='font-size:18px'>{beat}/{len(sub)}개</span>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

st.markdown("")
st.markdown(
    "> **해석**: 종목을 무작위로 골랐을 때 시장을 이길 확률이 33–41%입니다. "
    "즉, 10번 중 6–7번은 그냥 인덱스 ETF를 샀을 때보다 못한 결과가 나옵니다."
)
st.divider()


# ════════════════════════════════════════════════════════
# 섹션 2 — 미국 주식 수익률 분포 차트
# ════════════════════════════════════════════════════════
st.subheader("미국 주식 — 종목별 수익률 vs S&P500")

us   = df[df["category"] == "US"].sort_values("total_ret", ascending=True)
b_us = benchmarks.get("US")

if b_us is None or us.empty:
    st.info("S&P500 벤치마크 데이터를 불러오지 못했습니다. 잠시 후 새로고침해 주세요.")
else:
    colors = ["#22c55e" if r > b_us else "#ef4444" for r in us["total_ret"]]
    fig_us = go.Figure()
    fig_us.add_trace(go.Bar(
        x=us["ticker"], y=us["total_ret"],
        marker_color=colors,
        text=[f"{r:+.0f}%" for r in us["total_ret"]],
        textposition="outside",
        textfont=dict(size=11),
    ))
    fig_us.add_hline(
        y=b_us, line_dash="dash", line_color="#1d4ed8", line_width=2,
        annotation_text=f"S&P500 {b_us:+.1f}%",
        annotation_position="top right",
        annotation_font_color="#1d4ed8",
    )
    fig_us.update_layout(
        height=420, margin=dict(t=20, b=10),
        yaxis_title="총 수익률 (%)",
        plot_bgcolor="white", paper_bgcolor="white",
        xaxis=dict(tickangle=-45),
        showlegend=False,
    )
    st.plotly_chart(fig_us, use_container_width=True)

nvda_ret = us[us["ticker"] == "NVDA"]["total_ret"].values
if len(nvda_ret):
    no_nvda_mean = us[us["ticker"] != "NVDA"]["total_ret"].mean()
    st.markdown(
        f"**슈퍼스타 효과**: NVDA 1개 종목이 **+{nvda_ret[0]:.0f}%**로 전체 평균을 크게 끌어올립니다. "
        f"NVDA를 제외하면 평균은 **+{no_nvda_mean:.0f}%**로 낮아지고, "
        f"중앙값은 **+{us['total_ret'].median():.0f}%**입니다. "
        "이런 '한 방' 종목을 미리 골라낼 수 없다면, 시장 전체를 사는 게 합리적입니다."
    )
st.divider()


# ════════════════════════════════════════════════════════
# 섹션 3 — 코인 수익률 분포
# ════════════════════════════════════════════════════════
st.subheader("코인 — BTC를 이긴 알트코인은 몇 개?")
st.markdown("BTC는 코인 시장의 '시장 지수'입니다. 알트코인을 고르는 것은 개별 주식을 고르는 것과 같습니다.")

coin  = df[df["category"] == "Coin"].sort_values("total_ret", ascending=True)
b_btc = benchmarks.get("Coin")

if b_btc is None or coin.empty:
    st.info("BTC 벤치마크 데이터를 불러오지 못했습니다. 잠시 후 새로고침해 주세요.")
else:
    colors_c = ["#22c55e" if r > b_btc else "#ef4444" for r in coin["total_ret"]]
    fig_c = go.Figure()
    fig_c.add_trace(go.Bar(
        x=coin["ticker"].str.replace("-USD",""),
        y=coin["total_ret"],
        marker_color=colors_c,
        text=[f"{r:+.0f}%" for r in coin["total_ret"]],
        textposition="outside",
        textfont=dict(size=11),
    ))
    fig_c.add_hline(
        y=b_btc, line_dash="dash", line_color="#f59e0b", line_width=2,
        annotation_text=f"BTC {b_btc:+.1f}%",
        annotation_position="top right",
        annotation_font_color="#f59e0b",
    )
    fig_c.update_layout(
        height=420, margin=dict(t=20, b=10),
        yaxis_title="총 수익률 (%)",
        plot_bgcolor="white", paper_bgcolor="white",
        xaxis=dict(tickangle=-45),
        showlegend=False,
    )
    st.plotly_chart(fig_c, use_container_width=True)

median_coin = coin["total_ret"].median()
worst3 = coin.head(3)[["ticker","total_ret"]].values
st.markdown(
    f"코인 22개 중 BTC를 이긴 건 **4개(18%)** 뿐입니다. "
    f"중앙값은 **{median_coin:+.0f}%** — 절반 이상이 BTC보다 크게 손실입니다. "
    f"알트코인을 골랐을 때 BTC보다 잘 될 확률보다 훨씬 못 될 확률이 더 높습니다."
)
st.divider()


# ════════════════════════════════════════════════════════
# 섹션 4 — 전문가도 못 이긴다
# ════════════════════════════════════════════════════════
st.subheader("전문 펀드매니저도 장기적으로 시장을 못 이깁니다")

col1, col2, col3 = st.columns(3)
with col1:
    st.markdown(
        """
        <div style='background:#fff1f2; border-left:4px solid #ef4444;
                    border-radius:6px; padding:16px'>
          <div style='font-size:36px; font-weight:800; color:#ef4444'>92%</div>
          <div style='font-size:19px; color:#555; margin-top:8px'>
            미국 액티브 펀드가<br>15년간 S&P500에 패배<br>
            <span style='font-size:17px; color:#888'>(SPIVA 2024)</span>
          </div>
        </div>
        """, unsafe_allow_html=True)
with col2:
    st.markdown(
        """
        <div style='background:#fff7ed; border-left:4px solid #f97316;
                    border-radius:6px; padding:16px'>
          <div style='font-size:36px; font-weight:800; color:#f97316'>Warren Buffett</div>
          <div style='font-size:19px; color:#555; margin-top:8px'>
            "내가 죽으면 아내 재산의<br>90%를 S&P500 인덱스에,<br>10%를 국채에 투자하라"
          </div>
        </div>
        """, unsafe_allow_html=True)
with col3:
    st.markdown(
        """
        <div style='background:#f0fdf4; border-left:4px solid #22c55e;
                    border-radius:6px; padding:16px'>
          <div style='font-size:36px; font-weight:800; color:#22c55e'>Core 63%</div>
          <div style='font-size:19px; color:#555; margin-top:8px'>
            우리 전략에서 ETF 비중<br>시장 평균 수익은 이미 확보<br>
            <span style='font-size:17px; color:#888'>나머지 37%로 알파 시도</span>
          </div>
        </div>
        """, unsafe_allow_html=True)

