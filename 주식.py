"""엔트리 스크립트: st.navigation으로 주식/코인 페이지 라우팅."""
import streamlit as st

st.set_page_config(
    layout="wide",
    page_title="주식 & 코인 분석 대시보드",
    page_icon="📊",
)

pages = [
    st.Page("stocks_page.py", title="주식", icon="📈", default=True),
    st.Page("coin_page.py",   title="코인", icon="🪙"),
]
nav = st.navigation(pages)
nav.run()
