import pandas as pd


def generate_signals(df: pd.DataFrame) -> pd.DataFrame:
    """
    Golden Cross / Death Cross (50/200 MA) 전략.

    - golden_cross: 50일선이 200일선을 상향돌파한 그 날
    - death_cross : 50일선이 200일선을 하향돌파한 그 날
    - state=bull  : 평소 50 > 200
    - state=bear  : 평소 50 < 200
    """
    df = df.copy()

    above = df["ma50"] > df["ma200"]
    prev_above = above.shift(1)

    df["state"] = "bear"
    df.loc[above, "state"] = "bull"

    df["signal"] = "hold"
    df.loc[above & (~prev_above.fillna(False)), "signal"] = "golden_cross"
    df.loc[(~above) & (prev_above.fillna(False)), "signal"] = "death_cross"

    return df


# 최근 N일 이내의 크로스는 "신선한 신호"로 간주
FRESH_DAYS = 30


def latest_signal(df: pd.DataFrame) -> dict:
    """
    추천 행동(action)을 4가지로 단순화:
      - 매수   : 최근 FRESH_DAYS일 이내 골든크로스 발생
      - 매도   : 최근 FRESH_DAYS일 이내 데드크로스 발생
      - 보유   : bull 상태이지만 크로스가 오래 전
      - 미보유 : bear 상태이지만 크로스가 오래 전
    """
    if df.empty:
        return {"signal": "no_data", "action": "no_data"}

    last = df.iloc[-1]
    crosses = df[df["signal"].isin(["golden_cross", "death_cross"])]

    last_cross_date = None
    last_cross_type = None
    days_since_cross = None
    if not crosses.empty:
        last_cross_dt = crosses.index[-1]
        last_cross_date = last_cross_dt.strftime("%Y-%m-%d")
        last_cross_type = crosses.iloc[-1]["signal"]
        days_since_cross = (last.name - last_cross_dt).days

    is_bull = last["state"] == "bull"
    if (
        last_cross_type == "golden_cross"
        and days_since_cross is not None
        and days_since_cross <= FRESH_DAYS
    ):
        action = "매수"
    elif (
        last_cross_type == "death_cross"
        and days_since_cross is not None
        and days_since_cross <= FRESH_DAYS
    ):
        action = "매도"
    elif is_bull:
        action = "보유"
    else:
        action = "미보유"

    return {
        "date": last.name.strftime("%Y-%m-%d"),
        "close": float(last["Close"]),
        "state": last["state"],
        "action": action,
        "last_cross": last_cross_type,
        "last_cross_date": last_cross_date,
        "days_since_cross": days_since_cross,
    }


if __name__ == "__main__":
    print("Use generate_signals(df) and latest_signal(df)")
