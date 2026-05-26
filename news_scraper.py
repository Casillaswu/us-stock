"""
Phase 3: News scraper using yfinance built-in news + Yahoo Finance RSS.
No API key needed. Runs every Monday, sends Prompt 3 analysis to Claude.
"""
import warnings
warnings.filterwarnings("ignore")

import os
import sys
import json
import anthropic
import yfinance as yf
from datetime import date, timedelta
from watchlist import WATCHLIST

PROMPT3_TEMPLATE = """你是一位只看基本邏輯的獨立交易員。

以下是 {ticker} 過去一週的新聞標題列表：

{news_list}

任務：用 Prompt 3 框架分析。

1. 先把噪音砍掉：
   - 分析師評級調整（無數據支撐的那種）
   - 重複炒的舊標題
   - 公司例行公告
   - 情緒性預測（沒有新信息的）

2. 找出真正會改變這只票邏輯的 1-2 件事：
   - 什麼新信息改變了基本面或市場定價？
   - 這個事件是一次性的還是結構性的？

3. 對每個真實事件，給出時間維度分析：
   - 1 週內：短期價格反應會是什麼？
   - 3 個月內：中期邏輯如何演化？
   - 1 年內：長期影響是正面/負面/中性？

4. 對應的交易含義是什麼（具體方向 + 時機）？

如果這週完全沒有值得關注的新聞，直接說「本週無邏輯變化，無交易含義」。

用繁體中文，直接說，不要廢話。"""


def _load_env():
    env_file = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(env_file):
        for line in open(env_file):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def fetch_news(ticker: str) -> list[str]:
    """
    Fetch recent news headlines via yfinance.
    Returns list of headline strings.
    """
    t = yf.Ticker(ticker)
    news = t.news or []

    headlines = []
    for item in news[:15]:  # cap at 15 per ticker
        title = item.get("content", {}).get("title", "") or item.get("title", "")
        if title:
            headlines.append(title)

    return headlines


def analyze_news(ticker: str, headlines: list[str], client: anthropic.Anthropic) -> dict:
    if not headlines:
        return {"ticker": ticker, "analysis": "本週無新聞數據", "headlines": []}

    news_list = "\n".join(f"- {h}" for h in headlines)
    prompt = PROMPT3_TEMPLATE.format(ticker=ticker, news_list=news_list)

    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=800,
        messages=[{"role": "user", "content": prompt}]
    )
    return {
        "ticker": ticker,
        "analysis": msg.content[0].text,
        "headlines": headlines,
    }


def run_news_scan(tickers: list[str] = None) -> str:
    _load_env()
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")

    if tickers is None:
        # Only scan core watchlist (not ETFs) on Monday
        tickers = [t for t in WATCHLIST if t not in ("SPY", "QQQ", "IWM", "GLD", "TLT")]

    client = anthropic.Anthropic(api_key=api_key)
    results = []

    print(f"[news] 掃描 {len(tickers)} 支新聞...", file=sys.stderr)
    for ticker in tickers:
        print(f"  {ticker}...", file=sys.stderr)
        try:
            headlines = fetch_news(ticker)
            result = analyze_news(ticker, headlines, client)
            results.append(result)
        except Exception as e:
            results.append({"ticker": ticker, "analysis": f"⚠️ 失敗：{e}", "headlines": []})

    lines = [f"# 本週新聞邏輯掃描 — {date.today()}\n"]
    for r in results:
        lines.append(f"## {r['ticker']}\n\n{r['analysis']}\n\n---\n")

    return "\n".join(lines)


if __name__ == "__main__":
    tickers = sys.argv[1:] if len(sys.argv) > 1 else None
    result = run_news_scan(tickers)
    print(result)
