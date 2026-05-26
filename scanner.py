"""
Phase 2: Opportunity scanner using Prompt 1 logic.
Fetches all watchlist stocks, filters by momentum/volume,
sends one batched Claude call to rank top 5 opportunities.
"""
import warnings
warnings.filterwarnings("ignore")

import os
import sys
import json
import anthropic
from fetcher import fetch
from watchlist import WATCHLIST

PROMPT1_TEMPLATE = """你是一位只對自己負責的獨立交易員，不需要對任何人解釋任何事。

以下是今日美股盤前數據（{date}），包含 {n} 支股票的技術快照：

{data_json}

任務：用 Prompt 1 框架挑出 **5 個今天真正有優勢的交易機會**。

評估標準：
- **不是看起來像牛的**——是風險/收益比真的對我有利的
- 排除那些顯而易見、人人都已經進場的（RSI 超買 + 量縮 + 靠近歷史高點 = 排除）
- 優先找：被錯殺的反彈、有量突破的、均線支撐明確的、市場在哪裡定價錯了的

對每一個機會，必須回答：
1. **進場價位**：具體數字，不是範圍
2. **止損位**：做錯了損失多少（金額 or %）
3. **目標位**：止盈在哪，風報比是多少（例如 1:3）
4. **市場錯了什麼**：這裡的邏輯錯誤或定價偏差是什麼

最後加一行：**今天不值得碰的票**（1-3 支，附理由）

用繁體中文，直接說，不要廢話，不要免責聲明。"""


def _load_env():
    env_file = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(env_file):
        for line in open(env_file):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def fetch_all(tickers: list[str]) -> dict:
    results = {}
    failed = []
    for ticker in tickers:
        try:
            results[ticker] = fetch(ticker)
            print(f"  ✓ {ticker}", file=sys.stderr)
        except Exception as e:
            failed.append(ticker)
            print(f"  ✗ {ticker}: {e}", file=sys.stderr)
    if failed:
        print(f"  [skip] {failed}", file=sys.stderr)
    return results


def _filter_candidates(data: dict) -> dict:
    """
    Pre-filter: keep stocks with at least one signal.
    Reduces Claude input size and focuses on actionable names.

    Keep if ANY of:
    - Volume ratio > 1.2 (unusual activity)
    - RSI 35-65 (not overbought/oversold extremes — room to move)
    - Price within 3% of SMA20 (potential breakout/breakdown setup)
    - 1-week change > 3% (momentum)
    - 1-week change < -4% (potential reversal)
    """
    candidates = {}
    excluded = []
    for ticker, d in data.items():
        dd = d["daily"]
        vol_ok = dd["volume_ratio_vs_20d_avg"] > 1.2
        rsi_ok = 35 <= dd["rsi14"] <= 65
        near_sma20 = abs(d["current_price"] - dd["sma20"]) / dd["sma20"] < 0.03
        momentum_up = dd["change_1w_pct"] > 3
        momentum_down = dd["change_1w_pct"] < -4

        # Explicit exclusion: overbought + volume shrinking + near 52w high
        pct_from_high = abs(dd["pct_from_52w_high"])
        overbought_extended = dd["rsi14"] > 75 and dd["volume_ratio_vs_20d_avg"] < 0.95 and pct_from_high < 2

        if overbought_extended:
            excluded.append(ticker)
        elif any([vol_ok, rsi_ok, near_sma20, momentum_up, momentum_down]):
            candidates[ticker] = d

    print(f"  [filter] {len(candidates)} candidates, {len(excluded)} excluded: {excluded}", file=sys.stderr)
    return candidates


def _compress_for_prompt(data: dict) -> str:
    """Compress data to essential fields only to reduce token usage."""
    compressed = {}
    for ticker, d in data.items():
        dd = d["daily"]
        dw = d["weekly"]
        compressed[ticker] = {
            "price": d["current_price"],
            "date": d["as_of"],
            "chg_1w%": dd["change_1w_pct"],
            "chg_1m%": dd["change_1m_pct"],
            "rsi_d": dd["rsi14"],
            "rsi_w": dw["rsi14"],
            "macd_hist": dd["macd_hist"],
            "vol_ratio_d": dd["volume_ratio_vs_20d_avg"],
            "vol_ratio_w": dw["volume_ratio_vs_10w_avg"],
            "trend": dd["trend_structure"],
            "sma20": dd["sma20"],
            "sma50": dd["sma50"],
            "sma200": dd["sma200"],
            "atr14": dd["atr14"],
            "bb_upper": dd["bb_upper"],
            "bb_lower": dd["bb_lower"],
            "high_52w": dd["high_52w"],
            "low_52w": dd["low_52w"],
            "pct_from_high": dd["pct_from_52w_high"],
            "support": dd["recent_low_20d"],
            "resistance": dd["recent_high_20d"],
        }
    return json.dumps(compressed, ensure_ascii=False, indent=2)


def scan(tickers: list[str] = None) -> str:
    _load_env()
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")

    if tickers is None:
        tickers = WATCHLIST

    print(f"[scanner] 拉取 {len(tickers)} 支數據...", file=sys.stderr)
    all_data = fetch_all(tickers)

    print("[scanner] 過濾候選...", file=sys.stderr)
    candidates = _filter_candidates(all_data)

    if len(candidates) < 3:
        print("[scanner] 候選太少，放寬條件使用全部", file=sys.stderr)
        candidates = all_data

    as_of = next(iter(all_data.values()))["as_of"]
    compressed = _compress_for_prompt(candidates)

    prompt = PROMPT1_TEMPLATE.format(
        date=as_of,
        n=len(candidates),
        data_json=compressed,
    )

    print(f"[scanner] 送 Claude 分析 {len(candidates)} 支候選...", file=sys.stderr)
    client = anthropic.Anthropic(api_key=api_key)
    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}]
    )
    return msg.content[0].text


if __name__ == "__main__":
    result = scan()
    print(result)
