"""
Re-render today's HTML report from existing daily log (no API calls).
Usage: python3 rerender.py
"""
import warnings
warnings.filterwarnings("ignore")

import re
import sys
from datetime import date
from pathlib import Path
from renderer import parse_opportunities, parse_charts, render_html, save_report
from fetcher import fetch
from watchlist import DAILY_ANALYSIS

daily_path = Path.home() / ".claude" / "daily" / f"{date.today()}.md"
if not daily_path.exists():
    print("找不到今天的 daily log", file=sys.stderr)
    sys.exit(1)

content = daily_path.read_text()

# Extract scan text (Prompt 1 section)
scan_m = re.search(r"今日 5 大機會\n\n(.*?)(?=###|\Z)", content, re.S)
scan_text = scan_m.group(1).strip() if scan_m else ""

# Extract chart text (Prompt 2 section)
chart_m = re.search(r"每日圖表分析\n\n(.*?)(?=###|\Z)", content, re.S)
chart_text = chart_m.group(1).strip() if chart_m else ""

if not scan_text and not chart_text:
    print("daily log 裡找不到分析內容，請先跑 reporter.py", file=sys.stderr)
    sys.exit(1)

print(f"scan_text: {len(scan_text)} chars", file=sys.stderr)
print(f"chart_text: {len(chart_text)} chars", file=sys.stderr)

# Fetch fresh prices (no Claude API, just yfinance)
data_cache = {}
for ticker in DAILY_ANALYSIS:
    try:
        data_cache[ticker] = fetch(ticker)
        print(f"  ✓ {ticker}", file=sys.stderr)
    except Exception as e:
        print(f"  ✗ {ticker}: {e}", file=sys.stderr)

opportunities, avoid = parse_opportunities(scan_text)
charts = parse_charts(chart_text, data_cache)

print(f"opportunities parsed: {len(opportunities)}", file=sys.stderr)
print(f"charts parsed: {len(charts)}", file=sys.stderr)
for o in opportunities:
    print(f"  {o['ticker']} {o['signal_label']} entry={o['entry']} stop={o['stop']}", file=sys.stderr)

html = render_html(opportunities=opportunities, avoid_tickers=avoid, charts=charts, phase=2)
path = save_report(html)
print(f"\n✓ HTML → {path}")

import subprocess
subprocess.run(["open", str(path)])
