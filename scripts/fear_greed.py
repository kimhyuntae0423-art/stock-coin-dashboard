"""
공포·탐욕 지수(Fear & Greed Index) 가져오기.
- CNN: 미국 주식시장 지수
- Alternative.me: 암호화폐 시장 지수
"""
from datetime import datetime
from urllib.request import Request, urlopen
import json


CNN_URL = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
CRYPTO_URL = "https://api.alternative.me/fng/?limit=1"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

CNN_HEADERS = {
    "User-Agent": UA,
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.cnn.com/",
    "Origin": "https://www.cnn.com",
}


def _classify(score: float, scheme: str = "cnn") -> str:
    """0~100 점수를 한글 분류로 변환."""
    if score < 25:
        return "극단적 공포"
    if score < 45:
        return "공포"
    if score < 55:
        return "중립"
    if score < 75:
        return "탐욕"
    return "극단적 탐욕"


def fetch_cnn_fear_greed() -> dict:
    try:
        req = Request(CNN_URL, headers=CNN_HEADERS)
        with urlopen(req, timeout=8) as r:
            data = json.loads(r.read())
        fng = data.get("fear_and_greed", {})
        score = float(fng.get("score", 0))
        return {
            "score": round(score, 1),
            "label": _classify(score),
            "raw_rating": fng.get("rating"),
            "timestamp": fng.get("timestamp"),
            "source": "CNN",
        }
    except Exception as e:
        return {"error": str(e), "source": "CNN"}


def fetch_crypto_fear_greed() -> dict:
    try:
        req = Request(CRYPTO_URL, headers={"User-Agent": UA})
        with urlopen(req, timeout=8) as r:
            data = json.loads(r.read())
        d = data["data"][0]
        score = float(d["value"])
        ts = int(d["timestamp"])
        return {
            "score": round(score, 1),
            "label": _classify(score),
            "raw_rating": d.get("value_classification"),
            "timestamp": datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d"),
            "source": "Alternative.me",
        }
    except Exception as e:
        return {"error": str(e), "source": "Alternative.me"}


if __name__ == "__main__":
    print("CNN  :", fetch_cnn_fear_greed())
    print("Crypto:", fetch_crypto_fear_greed())
