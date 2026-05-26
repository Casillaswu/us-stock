"""
HTML renderer: converts Claude text output → structured data → Jinja2 HTML report.
Parses the analyst/scanner output and renders finalized.html for sharing.
"""
import warnings
warnings.filterwarnings("ignore")

import re
import sys
import json
from datetime import date, datetime
from pathlib import Path

TEMPLATE_PATH = Path.home() / ".gstack/projects/Claude/designs/us-stock-report-20260526/finalized.html"
OUTPUT_DIR = Path.home() / "showcase/us-stock/reports"

# ─── Simple Markdown → HTML converter (no external deps) ─────────────────────

def md_to_html(text: str) -> str:
    """Convert markdown to HTML for chart analysis bodies."""
    lines = text.split("\n")
    out = []
    in_table = False
    in_ul = False

    for line in lines:
        # Table rows
        if line.strip().startswith("|"):
            if not in_table:
                out.append("<table>")
                in_table = True
            cells = [c.strip() for c in line.split("|")[1:-1]]
            if all(set(c).issubset("-| ") for c in cells):
                continue  # separator row
            tag = "th" if not any(out[-1].startswith("<tr") for _ in [0]) else "td"
            # Detect header: first table row
            if "<table>" in (out[-1] if out else ""):
                out.append("<tr>" + "".join(f"<th>{c}</th>" for c in cells) + "</tr>")
            else:
                out.append("<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>")
            continue
        elif in_table:
            out.append("</table>")
            in_table = False

        # UL
        if line.startswith("- ") or line.startswith("* "):
            if not in_ul:
                out.append("<ul>")
                in_ul = True
            content = line[2:].strip()
            out.append(f"<li>{_inline_md(content)}</li>")
            continue
        elif in_ul:
            out.append("</ul>")
            in_ul = False

        # Headings
        m = re.match(r"^(#{1,4})\s+(.*)", line)
        if m:
            level = min(len(m.group(1)) + 1, 4)
            out.append(f"<h{level}>{_inline_md(m.group(2))}</h{level}>")
            continue

        # HR
        if re.match(r"^[-*_]{3,}$", line.strip()):
            out.append("<hr>")
            continue

        # Blank line
        if not line.strip():
            if in_ul:
                out.append("</ul>")
                in_ul = False
            continue

        out.append(f"<p>{_inline_md(line)}</p>")

    if in_table:
        out.append("</table>")
    if in_ul:
        out.append("</ul>")

    return "\n".join(out)


def _inline_md(text: str) -> str:
    """Bold, italic, code inline."""
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"\*(.+?)\*", r"<em>\1</em>", text)
    text = re.sub(r"`(.+?)`", r"<code>\1</code>", text)
    return text


# ─── Opportunity parser ───────────────────────────────────────────────────────

def parse_opportunities(scan_text: str) -> tuple[list[dict], list[str]]:
    """Parse scanner Prompt-1 output into opportunity cards + avoid list."""
    opportunities = []
    avoid = []

    # ── Avoid tickers ────────────────────────────────────────────────
    avoid_m = re.search(
        r"(?:今天不值得碰|❌|不值得碰)[^\n]*\n(.*?)(?:\Z|\n#)",
        scan_text, re.S | re.I
    )
    if avoid_m:
        avoid = re.findall(r"\b([A-Z]{2,5})\b", avoid_m.group(1))

    # ── Opportunity sections ─────────────────────────────────────────
    # Match "機會一/二/三.." or "## TICKER" blocks
    blocks = re.split(r"\n(?=##\s+機會|##\s+[A-Z]{2,5})", scan_text)

    for block in blocks:
        if not block.strip():
            continue
        # Extract ticker
        ticker_m = re.search(r"##\s+(?:機會[一二三四五六七]：)?([A-Z]{2,5})", block)
        if not ticker_m:
            continue
        ticker = ticker_m.group(1)

        # Signal direction
        if re.search(r"做空|空頭|逆向做空|short", block, re.I):
            signal_class, signal_label = "short", "做空"
        elif re.search(r"等等|觀望", block, re.I):
            signal_class, signal_label = "wait", "觀望"
        else:
            signal_class, signal_label = "long", "做多"

        def ep(pattern):
            m = re.search(pattern, block, re.I)
            return m.group(1).replace(",", "") if m else "—"

        # Claude output: **進場價：** 382.00 or 進場：382.00
        entry  = ep(r"進場[價位\*：: 　]+\*?\s*\$?\s*([\d,\.]+)")
        stop   = ep(r"止損[位\*：: 　]+\*?\s*\$?\s*([\d,\.]+)")
        target = ep(r"目標[位\*：: 　]+\*?\s*\$?\s*([\d,\.]+)")
        rr_raw = ep(r"風報比[約\*：: 　]+\*?\s*([1-9][0-9]*:[0-9\.]+)")

        # Edge: 市場錯了什麼 paragraph
        edge_m = re.search(r"市場錯了什麼[^：:]*[：:]\s*\n?\*?\*?(.+?)(?:\n\n|\n-|\n\*\*|\Z)", block, re.S)
        if edge_m:
            edge = re.sub(r"\*+", "", edge_m.group(1)).strip()[:150]
        else:
            paras = [p.strip() for p in block.split("\n\n") if len(p.strip()) > 20 and not p.strip().startswith("#")]
            edge = re.sub(r"\*+", "", paras[1] if len(paras) > 1 else (paras[0] if paras else ""))[:150]

        opportunities.append({
            "ticker": ticker,
            "signal_class": signal_class,
            "signal_label": signal_label,
            "edge": edge,
            "entry": entry,
            "stop": stop,
            "target": target,
            "rr": rr_raw if rr_raw != "—" else "N/A",
        })

    return opportunities[:5], avoid


# ─── Chart parser ─────────────────────────────────────────────────────────────

def parse_charts(chart_text: str, data_cache: dict = None) -> list[dict]:
    """Parse Prompt-2 chart analysis into chart dicts with full HTML body."""
    charts = []
    # Split on "## TICKER" headings (the ticker sub-sections)
    sections = re.split(r"\n(?=## [A-Z]{2,5}\b)", chart_text)

    for sec in sections:
        m = re.match(r"## ([A-Z]{2,5})\b", sec.strip())
        if not m:
            continue
        ticker = m.group(1)

        # Verdict detection
        verdict_class, verdict_label = "wait", "等等"
        if re.search(r"最終判斷[：:「『\s*\*]*買|判斷.*：.*買入", sec, re.I):
            verdict_class, verdict_label = "buy", "買入"
        elif re.search(r"最終判斷[：:「『\s*\*]*遠離|判斷.*：.*遠離", sec, re.I):
            verdict_class, verdict_label = "avoid", "遠離"

        price, change_1w = "—", "—"
        if data_cache and ticker in data_cache:
            d = data_cache[ticker]
            price = d.get("current_price", "—")
            chg = d.get("daily", {}).get("change_1w_pct", "—")
            change_1w = f"+{chg}" if isinstance(chg, (int, float)) and chg > 0 else str(chg)

        # Convert full section body (skip the ## TICKER header line)
        body = re.sub(r"^## [A-Z]{2,5}[^\n]*\n", "", sec, count=1)
        charts.append({
            "ticker": ticker,
            "verdict_class": verdict_class,
            "verdict_label": verdict_label,
            "price": price,
            "change_1w": change_1w,
            "analysis_html": md_to_html(body),
        })

    return charts


# ─── Jinja2 render ────────────────────────────────────────────────────────────

def render_html(
    opportunities: list[dict],
    avoid_tickers: list[str],
    charts: list[dict],
    news_items: dict = None,
    phase: int = 2,
) -> str:
    template = TEMPLATE_PATH.read_text()

    today = date.today().strftime("%Y-%m-%d")
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    # Simple Jinja2-like substitution (no jinja2 dep)
    from jinja2 import Environment

    env = Environment(autoescape=False)
    tmpl = env.from_string(template)

    return tmpl.render(
        date=today,
        generated_at=now,
        watchlist_count=len(__import__("watchlist").WATCHLIST),
        opportunities=opportunities,
        avoid_tickers=avoid_tickers,
        charts=charts,
        news_items=news_items or {},
        phase=phase,
    )


def save_report(html: str) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUTPUT_DIR / f"report-{date.today()}.html"
    out.write_text(html)
    return out


if __name__ == "__main__":
    # Quick test with dummy data
    opps = [
        {"ticker": "TEST", "signal_class": "long", "signal_label": "做多",
         "edge": "這是測試機會，市場定價錯誤", "entry": "100.00",
         "stop": "95.00", "target": "115.00", "rr": "1:3"},
    ]
    charts = [
        {"ticker": "AAPL", "verdict_class": "wait", "verdict_label": "等等",
         "price": "308.82", "change_1w": "+3.7",
         "analysis_html": "<p>測試分析內容</p>"},
    ]
    html = render_html(opps, ["ARM"], charts, phase=2)
    path = save_report(html)
    print(f"Report saved: {path}")
    import subprocess
    subprocess.run(["open", str(path)])
