"""
Run Prompt 2 chart analysis via Claude API.
Usage: python3 analyst.py AAPL [NVDA SPY ...]
"""
import warnings
warnings.filterwarnings("ignore")

import os
import sys
import json
import anthropic
from fetcher import fetch

PROMPT2_TEMPLATE = """你是一位不替任何人說話的獨立市場分析師。
以下是 {ticker} 的技術數據（日線 + 週線），請用 Prompt 2 框架直接分析：

{data_json}

分析要求（每項都要直接回答，不要模糊）：

1. **真正的買家在哪裡出現**
   - 成交量放大的具體價位區間？
   - 哪些日子的量價配合是真實的需求，而不是軋空或噪音？

2. **這只票一直在哪裡失敗**
   - 具體壓力位在哪？（用實際價格說）
   - 上漲動能在哪裡開始衰減？反覆失守的價位？

3. **成交量在說什麼 vs 價格在說什麼**
   - 量價是否一致？還是背離？
   - 近期量能和趨勢走向有沒有矛盾的地方？

4. **趨勢是健康的還是快沒油了**
   - RSI、MACD、均線結構的真實含義是什麼？
   - 動能在加速還是減速？

5. **最終判斷：買 / 等等 / 遠離（三選一）**
   - 理由要具體：進場條件是什麼、做錯了止損在哪、目標在哪
   - 如果是「等等」：等什麼信號出現？

用繁體中文回答，直接說結論，不要廢話，不要免責聲明。"""


def analyze(ticker: str, client: anthropic.Anthropic) -> str:
    data = fetch(ticker)
    data_str = json.dumps(data, ensure_ascii=False, indent=2)

    prompt = PROMPT2_TEMPLATE.format(ticker=ticker, data_json=data_str)

    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1200,
        messages=[{"role": "user", "content": prompt}]
    )
    return msg.content[0].text


def _load_env():
    env_file = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(env_file):
        for line in open(env_file):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def build_report(tickers: list[str]) -> str:
    _load_env()
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")

    client = anthropic.Anthropic(api_key=api_key)
    lines = [f"# 美股技術分析晨報 — {__import__('datetime').date.today()}\n"]

    for ticker in tickers:
        print(f"  analyzing {ticker}...", file=sys.stderr)
        try:
            result = analyze(ticker, client)
            lines.append(f"## {ticker}\n\n{result}\n\n---\n")
        except Exception as e:
            lines.append(f"## {ticker}\n\n⚠️ 分析失敗：{e}\n\n---\n")

    return "\n".join(lines)


if __name__ == "__main__":
    tickers = sys.argv[1:] if len(sys.argv) > 1 else ["AAPL", "NVDA", "SPY"]
    report = build_report(tickers)
    print(report)
