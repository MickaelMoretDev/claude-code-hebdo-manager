"""Generate the README illustrations.

Run: python3 docs/make_images.py
Writes docs/*.svg (sources) and docs/*.png (used by the README — PNG so that the
block glyphs render identically whatever font the reader's browser picks)."""
from pathlib import Path

HERE = Path(__file__).parent
FONT = "ui-monospace, SFMono-Regular, Menlo, Consolas, 'Liberation Mono', monospace"
BG, FG, DIM = "#0d1117", "#e6edf3", "#7d8590"
GREEN, YELLOW, RED, BLUE = "#3fb950", "#d29922", "#f85149", "#58a6ff"


def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def terminal(width: int, lines, title: str, line_h: int = 24, pad: int = 18, font_size: int = 14) -> str:
    """lines: list of list of (text, color) segments."""
    h = 40 + pad * 2 + line_h * len(lines)
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{h}" viewBox="0 0 {width} {h}" font-family="{FONT}" font-size="{font_size}">']
    out.append(f'<rect width="{width}" height="{h}" rx="10" fill="{BG}" stroke="#30363d"/>')
    out.append(f'<rect width="{width}" height="40" rx="10" fill="#161b22"/><rect y="20" width="{width}" height="20" fill="#161b22"/>')
    for i, c in enumerate(("#ff5f57", "#febc2e", "#28c840")):
        out.append(f'<circle cx="{20 + i * 20}" cy="20" r="6" fill="{c}"/>')
    out.append(f'<text x="{width / 2}" y="25" text-anchor="middle" fill="{DIM}" font-size="12">{esc(title)}</text>')
    y = 40 + pad + 16
    for segs in lines:
        x = pad
        parts = []
        for text, color in segs:
            parts.append(f'<tspan fill="{color}" xml:space="preserve">{esc(text)}</tspan>')
        out.append(f'<text x="{x}" y="{y}" xml:space="preserve">{"".join(parts)}</text>')
        y += line_h
    out.append("</svg>")
    return "\n".join(out)


def statusline_svg() -> str:
    lines = [
        [("> ", GREEN), ("Try \"refactor the billing module\"", DIM)],
        [("", FG)],
        [("Fable 5.1", DIM), (" │ ", DIM), ("weekly 38% ████░░┆░░░ cap d2 37% (margin +2)", GREEN),
         (" │ ", DIM), ("fable 12%", DIM), (" │ ", DIM), ("reset 4d 11h", DIM)],
    ]
    return terminal(760, lines, "Claude Code — statusline")


def states_svg() -> str:
    lines = [
        [("ok      ", DIM), ("weekly 38% ████░░┆░░░ cap d2 45% (margin +2)", GREEN)],
        [("warn    ", DIM), ("weekly 41% ████░┆░░░░ cap d2 45% ⚠", YELLOW)],
        [("over    ", DIM), ("weekly 52% █████┆░░░░ cap d2 45% ✖", RED)],
        [("", FG)],
        [("┆ = today's cap   █ = used   margin = today's allowance vs. the static plan", DIM)],
    ]
    return terminal(760, lines, "statusline states")


def simulate_svg() -> str:
    rows = [
        ("  day planned cum.      cap  day margin   end of day  status", DIM),
        ("   d1          30%    30.0%           —          20%  ok", GREEN),
        ("   d2          45%    37.1%        +2.1          40%  ✖ exceeded", RED),
        ("   d3          60%    56.4%        +1.4          55%  ⚠ close", YELLOW),
        ("   d4          72%    68.5%        +1.5          70%  ✖ exceeded", RED),
        ("   d5          84%    82.9%        +0.9          80%  ⚠ close", YELLOW),
        ("   d6          94%    92.5%        +2.5          92%  ⚠ close", YELLOW),
        ("   d7         100%   100.0%        +2.0          99%  ⚠ close", YELLOW),
    ]
    lines = [[("$ ", GREEN), ("claude-usage-budget simulate 20 40 55 70 80 92 99", FG)]] + [[(t, c)] for t, c in rows]
    return terminal(760, lines, "simulate — adaptive caps over a week")


def toast_svg() -> str:
    w, h = 420, 120
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" font-family="Segoe UI, system-ui, sans-serif">
<defs><filter id="s" x="-10%" y="-10%" width="120%" height="130%"><feDropShadow dx="0" dy="6" stdDeviation="8" flood-color="#000" flood-opacity="0.35"/></filter></defs>
<rect x="10" y="8" width="{w - 20}" height="{h - 20}" rx="10" fill="#202020" filter="url(#s)"/>
<rect x="30" y="30" width="44" height="44" rx="10" fill="#d97757"/>
<text x="52" y="60" text-anchor="middle" fill="#fff" font-size="22" font-weight="700">C</text>
<text x="92" y="44" fill="#fff" font-size="15" font-weight="600">Claude — daily cap exceeded</text>
<text x="92" y="68" fill="#c8c8c8" font-size="13">weekly usage 52% ≥ cap 45% (d2).</text>
<text x="92" y="90" fill="#8a8a8a" font-size="11">Claude Usage Budget · now</text>
</svg>'''


def main() -> None:
    (HERE / "statusline.svg").write_text(statusline_svg(), encoding="utf-8")
    (HERE / "states.svg").write_text(states_svg(), encoding="utf-8")
    (HERE / "simulate.svg").write_text(simulate_svg(), encoding="utf-8")
    (HERE / "toast.svg").write_text(toast_svg(), encoding="utf-8")
    print("docs/*.svg written")


if __name__ == "__main__":
    main()


# --------------------------------------------------------------------------- #
# PNG export (what the README uses — font-independent, identical on every host)
# --------------------------------------------------------------------------- #

def export_png(scale: int = 2) -> None:
    """Rasterize each SVG with headless Chromium. Requires: pip install playwright."""
    import asyncio

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("playwright not installed — SVGs only (pip install playwright && playwright install chromium)")
        return

    async def run() -> None:
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            for svg in sorted(HERE.glob("*.svg")):
                page = await browser.new_page(device_scale_factor=scale)
                await page.goto(svg.resolve().as_uri())
                el = await page.query_selector("svg")
                await el.screenshot(path=str(svg.with_suffix(".png")), omit_background=True)
                await page.close()
                print("wrote", svg.with_suffix(".png").name)
            await browser.close()

    asyncio.run(run())


if __name__ == "__main__":
    export_png()
