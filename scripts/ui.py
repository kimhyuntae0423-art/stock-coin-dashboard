"""대시보드 공통 UI 컴포넌트."""
import streamlit as st
import plotly.graph_objects as go


def render_fng_gauge(fng: dict, title: str):
    """공포·탐욕 지수를 Plotly 게이지로 표시."""
    if fng.get("error") or fng.get("score") is None:
        st.warning(f"{title} 가져오기 실패: {fng.get('error', '알 수 없는 오류')}")
        return

    score = fng["score"]
    label = fng["label"]
    ts = fng.get("timestamp", "")

    fig = go.Figure(
        go.Indicator(
            mode="gauge+number",
            value=score,
            number={"font": {"size": 38}},
            title={"text": f"<b>{title}</b><br><span style='font-size:0.9em'>{label}</span>",
                   "font": {"size": 16}},
            gauge={
                "axis": {"range": [0, 100], "tickwidth": 1},
                "bar": {"color": "#222"},
                "steps": [
                    {"range": [0, 25], "color": "#c0392b"},      # 극단 공포
                    {"range": [25, 45], "color": "#e67e22"},     # 공포
                    {"range": [45, 55], "color": "#f1c40f"},     # 중립
                    {"range": [55, 75], "color": "#27ae60"},     # 탐욕
                    {"range": [75, 100], "color": "#16a085"},    # 극단 탐욕
                ],
                "threshold": {"line": {"color": "white", "width": 3}, "thickness": 0.75, "value": score},
            },
        )
    )
    fig.update_layout(height=240, margin=dict(l=20, r=20, t=60, b=20))
    st.plotly_chart(fig, use_container_width=True)
    if ts:
        st.caption(f"기준일: {ts[:10]} · 출처: {fng.get('source', '')}")


def render_action_legend():
    """추천 행동 4단계 설명 박스."""
    st.info(
        """
**추천 행동 설명** (50/200일 이동평균 기반)
- 🟢 **매수** — 최근 30일 이내 **골든크로스** 발생 (50일선이 200일선을 상향돌파). 새 상승 추세 시작 신호로 신규 진입 고려.
- 🔵 **보유** — 이미 50일선이 200일선 위에 있고 상승 추세 유지 중. 이전에 매수했다면 계속 보유.
- 🔴 **매도** — 최근 30일 이내 **데드크로스** 발생 (50일선이 200일선을 하향돌파). 추세 전환 신호로 청산 고려.
- ⚪ **미보유** — 50일선이 200일선 아래에 있고 하락 추세 유지 중. 신규 진입 자제 / 관망.
"""
    )
