"""Map hex in signals.html <style> to theme CSS variables."""
from __future__ import annotations

import re
from pathlib import Path

REPL: dict[str, str] = {
    # Longest / special first (keep #3a8ef6aa as-is: 8-digit hex in keyframes)
    "#171c28": "var(--mp-c-surface-2, #171c28)",
    "#1a1a1a": "var(--mp-c-text-bright, #1a1a1a)",
    "#1a1f2e": "var(--mp-c-surface, #1a1f2e)",
    "#1a2030": "var(--mp-c-surface, #1a2030)",
    "#1e2533": "var(--mp-c-surface, #1e2533)",
    "#1e2538": "var(--mp-c-surface-2, #1e2538)",
    "#1e2a42": "var(--mp-c-surface, #1e2a42)",
    "#223366": "var(--mp-c-surface, #223366)",
    "#232a3e": "var(--mp-c-raised, #232a3e)",
    "#243050": "var(--mp-signal-row-alt, #243050)",
    "#2a3145": "var(--mp-c-raised, #2a3145)",
    "#2a3345": "var(--mp-c-border, #2a3345)",
    "#2d3550": "var(--mp-c-border, #2d3550)",
    "#2d3a5e": "var(--mp-signal-pill-ok, #2d3a5e)",
    "#2f3a52": "var(--mp-c-border, #2f3a52)",
    "#2f3d5c": "var(--mp-c-border, #2f3d5c)",
    "#343d52": "var(--mp-c-raised, #343d52)",
    "#35456a": "var(--mp-signal-pill-ok, #35456a)",
    "#3a2626": "var(--mp-signal-pill-err, #3a2626)",
    "#3a4558": "var(--mp-c-border, #3a4558)",
    "#3a4a70": "var(--mp-c-border, #3a4a70)",
    "#3a5bbf": "var(--mp-signal-tab-active, #3a5bbf)",
    "#3a8ef6": "var(--mp-c-link, #3a8ef6)",
    "#445577": "var(--mp-c-hint, #445577)",
    "#4a3030": "var(--mp-purge-hover, #4a3030)",
    "#4a5a7a": "var(--mp-c-hint, #4a5a7a)",
    "#4a6fd0": "var(--mp-c-link, #4a6fd0)",
    "#4caf50": "var(--mp-sound-on, #4caf50)",
    "#5566aa": "var(--mp-signal-empty, #5566aa)",
    "#5a3a3a": "var(--mp-signal-pill-err, #5a3a3a)",
    "#5a6a8a": "var(--mp-c-hint, #5a6a8a)",
    "#5a6a9c": "var(--mp-c-hint, #5a6a9c)",
    "#5b9cf6": "var(--mp-c-link, #5b9cf6)",
    "#664040": "var(--mp-signal-pill-err, #664040)",
    "#6677aa": "var(--mp-c-hint, #6677aa)",
    "#6a7a9a": "var(--mp-c-hint, #6a7a9a)",
    "#7a8fb0": "var(--mp-c-text-muted, #7a8fb0)",
    "#7ab8ff": "var(--mp-c-link, #7ab8ff)",
    "#8899bb": "var(--mp-c-text-muted, #8899bb)",
    "#8ab88a": "var(--mp-cat-active-fg, #8ab88a)",
    "#9aa8c4": "var(--mp-events-text, #9aa8c4)",
    "#9ec5ff": "var(--mp-c-link, #9ec5ff)",
    "#9ecbff": "var(--mp-c-link, #9ecbff)",
    "#a8c4ff": "var(--mp-c-link, #a8c4ff)",
    "#aab8d0": "var(--mp-cat-done-fg, #aab8d0)",
    "#b0bedb": "var(--mp-c-text-muted, #b0bedb)",
    "#b0c0d8": "var(--mp-c-text-soft, #b0c0d8)",
    "#c0ccdd": "var(--mp-c-text-soft, #c0ccdd)",
    "#c8d4e8": "var(--mp-c-text-soft, #c8d4e8)",
    "#d8e2f0": "var(--mp-c-text, #d8e2f0)",
    "#e0e6f0": "var(--mp-c-text, #e0e6f0)",
    "#e57373": "var(--mp-err, #e57373)",
    "#e8f0ff": "var(--mp-c-text-bright, #e8f0ff)",
    "#f0d0d0": "var(--mp-purge-fg, #f0d0d0)",
    "#f44336": "var(--mp-sound-off, #f44336)",
    "#f5c518": "var(--mp-accent, #f5c518)",
    "#ff9800": "var(--mp-sound-warn, #ff9800)",
    "#fff": "#fff",
}

def main() -> None:
    p = Path(__file__).resolve().parents[1] / "templates" / "signals.html"
    text = p.read_text(encoding="utf-8")
    start, end = text.find("<style>"), text.find("</style>")
    if start < 0 or end < 0:
        raise SystemExit("style block not found")
    pre = text[: start + len("<style>")]
    css = text[start + len("<style>") : end]
    post = text[end:]
    keys = sorted(REPL.keys(), key=len, reverse=True)
    for k in keys:
        css = css.replace(k, REPL[k])
    p.write_text(pre + css + post, encoding="utf-8")
    print("OK", p)

if __name__ == "__main__":
    main()
