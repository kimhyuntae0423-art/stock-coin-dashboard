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

    # MA 유효 행만 비교 (NaN 제거 후 명시적 bool 변환)
    ma50 = df["ma50"].astype("float64")
    ma200 = df["ma200"].astype("float64")

    above = (ma50 > ma200).astype("bool")          # True/False, no NaN
    prev_above = above.shift(1, fill_value=False)   # 첫 행은 False로 채움

    df["state"] = above.map({True: "bull", False: "bear"})
    df["signal"] = "hold"

    # 첫 번째 MA200 유효 행 이후부터만 크로스 감지
    first_ma200_valid = df["ma200"].first_valid_index()

    cross_mask = above != prev_above                # 전환이 일어난 행
    if first_ma200_valid is not None:
        # MA200이 없었던 기간은 크로스로 인정하지 않음
        cross_mask = cross_mask & (df.index >= first_ma200_valid)
        # 데이터 시작점(첫 유효 행) 자체도 제외 — 이전 상태를 알 수 없으므로
        cross_mask.loc[first_ma200_valid] = False

    df.loc[cross_mask & above, "signal"] = "golden_cross"
    df.loc[cross_mask & ~above, "signal"] = "death_cross"

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
