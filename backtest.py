"""
Phase 4: Prompt 4 backtest — Earnings Dislocation strategy.
Rule: Buy day after earnings-related drop ≥5%, if next 2 days close above drop-day low.
Exit: 30 trading days OR close below drop-day low, whichever first.
Position sizing: equal dollar per trade.
Slippage: 5bps each way.
Usage: python3 backtest.py AAPL [NVDA ...]
"""
import warnings
warnings.filterwarnings("ignore")

import os
import sys
import json
import anthropic
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import date
from pathlib import Path

SLIPPAGE = 0.0005  # 5 bps each way
HOLD_DAYS = 30


def _load_env():
    env_file = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(env_file):
        for line in open(env_file):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def fetch_history(ticker: str) -> pd.DataFrame:
    t = yf.Ticker(ticker)
    df = t.history(period="10y", interval="1d")
    df.index = pd.to_datetime(df.index).tz_localize(None)
    return df[["Open", "High", "Low", "Close", "Volume"]].dropna()


def find_earnings_drops(df: pd.DataFrame, threshold: float = -0.05) -> list[int]:
    """
    Find indices where daily close dropped >= threshold (e.g. -5%).
    Proxy for earnings-related drops: large single-day falls.
    Note: without actual earnings dates, we use any gap-down ≥5%.
    """
    pct_change = df["Close"].pct_change()
    drops = pct_change[pct_change <= threshold].index
    return [df.index.get_loc(d) for d in drops]


def run_backtest(ticker: str) -> dict:
    df = fetch_history(ticker)
    n = len(df)

    drop_indices = find_earnings_drops(df)
    trades = []

    for drop_idx in drop_indices:
        # Need at least 2 confirmation days + 30 hold days after
        if drop_idx + 3 + HOLD_DAYS >= n:
            continue

        drop_low = df["Low"].iloc[drop_idx]
        drop_close = df["Close"].iloc[drop_idx]

        # Confirmation: next 2 days both close above drop-day low
        c1 = df["Close"].iloc[drop_idx + 1]
        c2 = df["Close"].iloc[drop_idx + 2]
        if c1 <= drop_low or c2 <= drop_low:
            continue  # no confirmation

        # Entry: open of day after 2nd confirmation day
        entry_idx = drop_idx + 3
        entry_price = df["Open"].iloc[entry_idx] * (1 + SLIPPAGE)

        # Exit: 30 days or close below drop_low
        exit_idx = None
        exit_reason = "time"
        for i in range(entry_idx, min(entry_idx + HOLD_DAYS, n)):
            if df["Close"].iloc[i] < drop_low:
                exit_idx = i
                exit_reason = "stop"
                break
        if exit_idx is None:
            exit_idx = min(entry_idx + HOLD_DAYS - 1, n - 1)

        exit_price = df["Close"].iloc[exit_idx] * (1 - SLIPPAGE)
        pnl_pct = (exit_price / entry_price) - 1

        trades.append({
            "drop_date": df.index[drop_idx].strftime("%Y-%m-%d"),
            "entry_date": df.index[entry_idx].strftime("%Y-%m-%d"),
            "exit_date": df.index[exit_idx].strftime("%Y-%m-%d"),
            "drop_pct": round(df["Close"].pct_change().iloc[drop_idx] * 100, 2),
            "entry_price": round(entry_price, 2),
            "exit_price": round(exit_price, 2),
            "pnl_pct": round(pnl_pct * 100, 2),
            "exit_reason": exit_reason,
            "hold_days": exit_idx - entry_idx,
        })

    if not trades:
        return {"ticker": ticker, "trades": [], "stats": None}

    pnls = [t["pnl_pct"] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]

    # CAGR
    total_return = np.prod([(1 + p / 100) for p in pnls]) - 1
    years = (df.index[-1] - df.index[0]).days / 365.25
    cagr = ((1 + total_return) ** (1 / years) - 1) * 100 if years > 0 else 0

    # Drawdown
    equity = [1.0]
    for p in pnls:
        equity.append(equity[-1] * (1 + p / 100))
    equity = np.array(equity)
    peak = np.maximum.accumulate(equity)
    drawdown = (equity - peak) / peak
    max_dd = drawdown.min() * 100

    # Sharpe (annualized, assuming ~12 trades/year freq)
    if len(pnls) > 1:
        sharpe = (np.mean(pnls) / np.std(pnls)) * np.sqrt(12) if np.std(pnls) > 0 else 0
    else:
        sharpe = 0

    # Max consecutive losses
    max_streak = cur_streak = 0
    for p in pnls:
        if p <= 0:
            cur_streak += 1
            max_streak = max(max_streak, cur_streak)
        else:
            cur_streak = 0

    # Buy-and-hold
    bnh = (df["Close"].iloc[-1] / df["Close"].iloc[0] - 1) * 100

    # Worst 5 trades
    worst5 = sorted(trades, key=lambda t: t["pnl_pct"])[:5]

    stats = {
        "n_trades": len(trades),
        "win_rate": round(len(wins) / len(trades) * 100, 1),
        "avg_win": round(np.mean(wins), 2) if wins else 0,
        "avg_loss": round(np.mean(losses), 2) if losses else 0,
        "payoff_ratio": round(abs(np.mean(wins) / np.mean(losses)), 2) if wins and losses else 0,
        "cagr_pct": round(cagr, 1),
        "max_drawdown_pct": round(max_dd, 1),
        "sharpe": round(sharpe, 2),
        "max_loss_streak": max_streak,
        "buy_hold_return_pct": round(bnh, 1),
        "worst_5_trades": worst5,
    }

    return {"ticker": ticker, "trades": trades, "stats": stats}


PROMPT4_VERDICT = """你是一位不會說軟話的量化交易員。

以下是 {ticker} 「盈利後錯位」策略過去 10 年的回測結果：

{stats_json}

最差的 5 筆交易：
{worst5}

任務：回答以下三個問題，直接說，不要廢話：

1. 這是真有優勢，還是噪音？
   - 如果樣本不足 30 筆，直接說「樣本不足，無法判斷」
   - 如果是曲線擬合，直接說
   - 給出明確結論

2. 這是哪種市場環境喂出來的優勢？今天看起來像那種環境嗎？

3. 如果明天就實盤上線，前 6 個月最有可能從哪個地方讓你失望？

用繁體中文，三段回答，不要廢話，不要免責聲明。"""


def get_verdict(ticker: str, result: dict, client: anthropic.Anthropic) -> str:
    if not result["stats"] or result["stats"]["n_trades"] < 5:
        return f"**{ticker}**：樣本數 {result['stats']['n_trades'] if result['stats'] else 0} 筆，遠不足 30 筆，無統計意義，跳過。"

    stats = result["stats"].copy()
    worst5 = stats.pop("worst_5_trades")
    worst5_str = "\n".join(
        f"- {t['drop_date']} 進 {t['entry_date']} 出 {t['exit_date']} | PnL: {t['pnl_pct']}% | 原因: {t['exit_reason']}"
        for t in worst5
    )

    prompt = PROMPT4_VERDICT.format(
        ticker=ticker,
        stats_json=json.dumps(stats, ensure_ascii=False, indent=2),
        worst5=worst5_str,
    )

    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=600,
        messages=[{"role": "user", "content": prompt}]
    )
    return f"**{ticker}**\n\n{msg.content[0].text}"


def run_backtest_report(tickers: list[str]) -> str:
    _load_env()
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")

    client = anthropic.Anthropic(api_key=api_key)
    lines = [f"# 回測週報 — 盈利後錯位策略 — {date.today()}\n"]

    for ticker in tickers:
        print(f"  [backtest] {ticker}...", file=sys.stderr)
        try:
            result = run_backtest(ticker)
            if result["stats"]:
                s = result["stats"]
                lines.append(
                    f"## {ticker} 數據摘要\n"
                    f"- 交易筆數：{s['n_trades']} | 勝率：{s['win_rate']}%\n"
                    f"- 平均盈利：{s['avg_win']}% | 平均虧損：{s['avg_loss']}%\n"
                    f"- 盈亏比：{s['payoff_ratio']} | CAGR：{s['cagr_pct']}%\n"
                    f"- 最大回撤：{s['max_drawdown_pct']}% | Sharpe：{s['sharpe']}\n"
                    f"- 最長連敗：{s['max_loss_streak']} 筆 | 買入持有：{s['buy_hold_return_pct']}%\n"
                )
                verdict = get_verdict(ticker, result, client)
                lines.append(f"### Claude 判斷\n{verdict}\n\n---\n")
            else:
                lines.append(f"## {ticker}\n\n⚠️ 無有效交易信號，跳過。\n\n---\n")
        except Exception as e:
            lines.append(f"## {ticker}\n\n⚠️ 回測失敗：{e}\n\n---\n")

    return "\n".join(lines)


if __name__ == "__main__":
    tickers = sys.argv[1:] if len(sys.argv) > 1 else ["AAPL", "NVDA", "TSLA"]
    report = run_backtest_report(tickers)
    print(report)

    # Save to daily log
    today = date.today()
    daily_path = Path.home() / ".claude" / "daily" / f"{today}.md"
    with open(daily_path, "a") as f:
        f.write(f"\n\n---\n\n### [回測報告 AUTO]\n\n{report}\n")
    print(f"\n✓ 寫入 {daily_path}", file=sys.stderr)
