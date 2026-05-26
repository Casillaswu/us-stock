"""
Fetch daily + weekly OHLCV data for a ticker using yfinance.
Returns dict with price stats and indicator summary for LLM consumption.
"""
import warnings
warnings.filterwarnings("ignore")

import yfinance as yf
import pandas as pd
import talib
from datetime import datetime, timedelta


def fetch(ticker: str) -> dict:
    t = yf.Ticker(ticker)

    # Daily: 1 year
    daily = t.history(period="1y", interval="1d")
    # Weekly: 2 years
    weekly = t.history(period="2y", interval="1wk")

    if daily.empty or len(daily) < 20:
        raise ValueError(f"Insufficient data for {ticker}")

    # --- Daily indicators ---
    close_d = daily["Close"].values
    volume_d = daily["Volume"].values
    high_d = daily["High"].values
    low_d = daily["Low"].values

    sma20 = talib.SMA(close_d, 20)[-1]
    sma50 = talib.SMA(close_d, 50)[-1]
    sma200 = talib.SMA(close_d, 200)[-1] if len(close_d) >= 200 else None
    rsi14 = talib.RSI(close_d, 14)[-1]
    macd, signal, hist = talib.MACD(close_d, 12, 26, 9)
    macd_val, macd_sig, macd_hist = macd[-1], signal[-1], hist[-1]
    atr14 = talib.ATR(high_d, low_d, close_d, 14)[-1]
    bb_upper, bb_mid, bb_lower = talib.BBANDS(close_d, 20)
    bb_upper, bb_lower = bb_upper[-1], bb_lower[-1]

    # Volume analysis
    vol_avg20 = pd.Series(volume_d).rolling(20).mean().iloc[-1]
    vol_ratio = volume_d[-1] / vol_avg20 if vol_avg20 > 0 else 1.0

    # Recent price action
    current_price = close_d[-1]
    week_ago = close_d[-5] if len(close_d) >= 5 else close_d[0]
    month_ago = close_d[-20] if len(close_d) >= 20 else close_d[0]
    three_month_ago = close_d[-60] if len(close_d) >= 60 else close_d[0]

    # 52-week high/low
    high_52w = max(high_d[-252:]) if len(high_d) >= 252 else max(high_d)
    low_52w = min(low_d[-252:]) if len(low_d) >= 252 else min(low_d)

    # Support/Resistance: recent swing highs/lows (last 20 bars)
    recent_high = max(high_d[-20:])
    recent_low = min(low_d[-20:])

    # --- Weekly indicators ---
    close_w = weekly["Close"].values
    volume_w = weekly["Volume"].values
    high_w = weekly["High"].values
    low_w = weekly["Low"].values

    sma20_w = talib.SMA(close_w, 20)[-1] if len(close_w) >= 20 else None
    rsi14_w = talib.RSI(close_w, 14)[-1] if len(close_w) >= 14 else None
    vol_avg10_w = pd.Series(volume_w).rolling(10).mean().iloc[-1]
    vol_ratio_w = volume_w[-1] / vol_avg10_w if vol_avg10_w > 0 else 1.0

    # Trend health: price vs MAs
    trend = "above_all_mas" if current_price > sma20 > sma50 else \
            "above_20_below_50" if current_price > sma20 else \
            "below_20_above_50" if current_price < sma20 and current_price > sma50 else \
            "below_all_mas"

    return {
        "ticker": ticker,
        "as_of": daily.index[-1].strftime("%Y-%m-%d"),
        "current_price": round(current_price, 2),
        "daily": {
            "change_1w_pct": round((current_price / week_ago - 1) * 100, 2),
            "change_1m_pct": round((current_price / month_ago - 1) * 100, 2),
            "change_3m_pct": round((current_price / three_month_ago - 1) * 100, 2),
            "high_52w": round(high_52w, 2),
            "low_52w": round(low_52w, 2),
            "pct_from_52w_high": round((current_price / high_52w - 1) * 100, 2),
            "recent_high_20d": round(recent_high, 2),
            "recent_low_20d": round(recent_low, 2),
            "sma20": round(sma20, 2),
            "sma50": round(sma50, 2),
            "sma200": round(sma200, 2) if sma200 else None,
            "rsi14": round(rsi14, 1),
            "macd": round(macd_val, 4),
            "macd_signal": round(macd_sig, 4),
            "macd_hist": round(macd_hist, 4),
            "atr14": round(atr14, 2),
            "bb_upper": round(bb_upper, 2),
            "bb_lower": round(bb_lower, 2),
            "volume_ratio_vs_20d_avg": round(vol_ratio, 2),
            "trend_structure": trend,
        },
        "weekly": {
            "sma20": round(sma20_w, 2) if sma20_w else None,
            "rsi14": round(rsi14_w, 1) if rsi14_w else None,
            "volume_ratio_vs_10w_avg": round(vol_ratio_w, 2),
            "last_week_close": round(close_w[-1], 2),
            "last_week_high": round(high_w[-1], 2),
            "last_week_low": round(low_w[-1], 2),
        }
    }


if __name__ == "__main__":
    import json, sys
    ticker = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    data = fetch(ticker)
    print(json.dumps(data, indent=2))
