"""
Morning report: Prompt 1 scan + Prompt 2 chart analysis (+ Prompt 3 on Mondays).
Outputs: daily log (Markdown) + shareable HTML report.
Usage: python3 reporter.py
"""
import warnings
warnings.filterwarnings("ignore")

import sys
import subprocess
from datetime import date, datetime
from pathlib import Path
from analyst import build_report
from scanner import scan, fetch_all
from watchlist import DAILY_ANALYSIS, WATCHLIST
from renderer import parse_opportunities, parse_charts, render_html, save_report


def main():
    today = date.today()
    daily_path = Path.home() / ".claude" / "daily" / f"{today}.md"
    daily_path.parent.mkdir(parents=True, exist_ok=True)

    sections = []
    scan_text = ""
    chart_text = ""
    news_items = {}

    # ── Phase 2: Opportunity Scan (Prompt 1) ──────────────────────────
    print("[reporter] Phase 2: 機會掃描...", file=sys.stderr)
    try:
        scan_text = scan()
        sections.append("### [美股晨報 AUTO] 今日 5 大機會\n\n" + scan_text)
    except Exception as e:
        sections.append(f"### [美股晨報 AUTO] 機會掃描失敗\n\n⚠️ {e}")

    # ── Phase 1: Chart Analysis (Prompt 2) ───────────────────────────
    print(f"[reporter] Phase 1: 圖表分析 {DAILY_ANALYSIS}...", file=sys.stderr)
    try:
        chart_text = build_report(DAILY_ANALYSIS)
        sections.append("### [美股晨報 AUTO] 每日圖表分析\n\n" + chart_text)
    except Exception as e:
        sections.append(f"### [美股晨報 AUTO] 圖表分析失敗\n\n⚠️ {e}")

    # ── Phase 3: News Scan (Mondays only) ────────────────────────────
    if today.weekday() == 0:  # Monday
        print("[reporter] Phase 3: 週一新聞掃描...", file=sys.stderr)
        try:
            from news_scraper import run_news_scan
            import re
            news_text = run_news_scan()
            sections.append("### [美股晨報 AUTO] 本週新聞邏輯\n\n" + news_text)
            # Parse news into dict for HTML renderer
            for m in re.finditer(r"## ([A-Z]{2,5})\n\n(.*?)(?=\n## |\Z)", news_text, re.S):
                ticker, analysis = m.group(1), m.group(2).strip()
                if "無邏輯變化" not in analysis and "無新聞數據" not in analysis:
                    news_items[ticker] = [{"headline": "本週重點", "trade_implication": analysis[:200]}]
        except Exception as e:
            sections.append(f"### [美股晨報 AUTO] 新聞掃描失敗\n\n⚠️ {e}")

    # ── Write to daily log ────────────────────────────────────────────
    output = "\n\n---\n\n".join(sections)
    with open(daily_path, "a") as f:
        f.write(f"\n\n---\n\n{output}\n")
    print(f"[reporter] ✓ daily log → {daily_path}", file=sys.stderr)

    # ── Render HTML report ────────────────────────────────────────────
    try:
        # Fetch fresh data for price/change display in HTML
        data_cache = {}
        try:
            data_cache = fetch_all(DAILY_ANALYSIS)
        except Exception:
            pass

        opportunities, avoid = parse_opportunities(scan_text)
        charts = parse_charts(chart_text, data_cache)
        html = render_html(
            opportunities=opportunities,
            avoid_tickers=avoid,
            charts=charts,
            news_items=news_items if news_items else None,
            phase=3 if today.weekday() == 0 else 2,
        )
        report_path = save_report(html)
        print(f"[reporter] ✓ HTML report → {report_path}", file=sys.stderr)

        # Add HTML path to daily log footer
        with open(daily_path, "a") as f:
            f.write(f"\n> 📊 HTML 晨報：`{report_path}`\n")

        # Auto-open in browser
        import subprocess
        subprocess.Popen(["open", str(report_path)])
        print(f"[reporter] ✓ 開啟瀏覽器", file=sys.stderr)

    except Exception as e:
        print(f"[reporter] ⚠️ HTML render 失敗：{e}", file=sys.stderr)

    print(output)


if __name__ == "__main__":
    main()
