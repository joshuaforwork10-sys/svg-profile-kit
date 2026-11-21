#!/usr/bin/env python3
"""Build animated light and dark SVG cards for a GitHub profile README from profile.json.

  python3 build.py                       # reads profile.json, writes assets/<card>-light.svg and -dark.svg
  python3 build.py me.json --out assets  # any profile file, any folder
  python3 build.py --snippet             # also print the <picture> markdown for every card

Each card is written twice, once per fixed palette. Motion stops under prefers-reduced-motion.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from html import escape as esc
from pathlib import Path

FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI','Helvetica Neue',Helvetica,Arial,sans-serif"
MONO = "ui-monospace,SFMono-Regular,'SF Mono',Menlo,Consolas,monospace"
W = 1000

PALETTES = {
    "light": {"bg": "#FFFFFF", "bg2": "#F6F8FB", "card": "#FFFFFF", "card2": "#EEF2F7", "line": "#E2E8F0",
              "line2": "#CBD5E1", "ink": "#0B1220", "mut": "#475569", "q": "#5B6779", "acc": "#2457E6",
              "acct": "#1D47C4", "on": "#FFFFFF", "gr": "#047857", "okbg": "#ECFDF5"},
    "dark": {"bg": "#0D1117", "bg2": "#111826", "card": "#141C2E", "card2": "#1E293B", "line": "#1E293B",
             "line2": "#334155", "ink": "#F1F5F9", "mut": "#A3B0C2", "q": "#94A3B8", "acc": "#6EA8FF",
             "acct": "#93C0FF", "on": "#0A0F1A", "gr": "#6EE7B7", "okbg": "#052E1F"},
}

BASE_CSS = f"""
text{{font-family:{FONT};fill:var(--ink)}}
.mono{{font-family:{MONO}}}
.mut{{fill:var(--mut)}} .q{{fill:var(--q)}} .acct{{fill:var(--acct)}} .on{{fill:var(--on)}} .gr{{fill:var(--gr)}}
.bg2{{fill:var(--bg2)}} .card{{fill:var(--card);stroke:var(--line)}} .card2{{fill:var(--card2);stroke:var(--line2)}}
.wire{{fill:none;stroke:var(--line2);stroke-width:1.6;stroke-dasharray:5 6;animation:dash 1.2s linear infinite}}
.dot{{fill:var(--acc)}}
.rise{{animation:rise .7s ease-out both}} .grow{{transform-box:fill-box;transform-origin:left;animation:grow 1s ease-out both}}
.ping{{transform-box:fill-box;transform-origin:center;animation:ping 2.4s ease-out infinite}}
@keyframes dash{{to{{stroke-dashoffset:-22}}}}
@keyframes grow{{from{{transform:scaleX(0)}}to{{transform:scaleX(1)}}}}
@keyframes rise{{from{{opacity:0;transform:translateY(10px)}}to{{opacity:1;transform:none}}}}
@keyframes ping{{0%{{opacity:.55;transform:scale(1)}}100%{{opacity:0;transform:scale(1.9)}}}}
@media (prefers-reduced-motion:reduce){{*{{animation:none!important}} .mover{{display:none}}}}
"""

ICONS = {
    "db": '<ellipse cx="0" cy="-8" rx="10" ry="4"/><path d="M-10 -8v14c0 2.2 4.5 4 10 4s10-1.8 10-4v-14"/><path d="M-10 -1c0 2.2 4.5 4 10 4s10-1.8 10-4"/>',
    "signal": '<path d="M-11 4c3-9 8-9 11 0s8 9 11 0"/><circle cx="0" cy="0" r="2.4"/><path d="M-6 -10a12 12 0 0 1 12 0M-3 -6a6 6 0 0 1 6 0"/>',
    "send": '<path d="M-11 -3 11 -11 3 11 0 2z"/><path d="M0 2 11 -11"/>',
    "table": '<rect x="-11" y="-10" width="22" height="20" rx="3"/><path d="M-11 -3h22M-4 -3v13"/>',
    "spark": '<path d="M0 -11l2.6 7.4L10 -1l-7.4 2.6L0 9l-2.6-7.4L-10 -1l7.4-2.6z"/>',
    "chart": '<path d="M-11 10h22M-7 10v-8M0 10v-15M7 10v-11"/>',
}


# ------------------------------------------------------------------ primitives
def palette_css(mode: str, overrides: dict) -> str:
    pal = {**PALETTES[mode], **overrides.get(mode, {})}
    return "svg{" + ";".join(f"--{k}:{v}" for k, v in pal.items()) + "}"


def svg(w, h, body, title, css=""):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" '
            f'role="img" aria-label="{esc(title)}"><title>{esc(title)}</title>'
            f'<style>@@PAL@@{BASE_CSS}{css}</style>{body}</svg>')


def T(x, y, s, size=14, cls="", weight=400, anchor="start", extra=""):
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" font-weight="{weight}" text-anchor="{anchor}" '
            f'class="{cls}" {extra}>{esc(str(s))}</text>')


def tw(s: str, size: float) -> float:
    """Rough rendered width of a string in the system font. No font metrics needed."""
    narrow = sum(1 for c in s if c in "iljtfrI.,:;'| ")
    wide = sum(1 for c in s if c in "mwMW@%")
    return size * (0.56 * len(s) - 0.24 * narrow + 0.3 * wide)


def wrap(text: str, size: float, width: float):
    lines, cur = [], ""
    for w in text.split():
        if cur and tw(cur + " " + w, size) > width:
            lines.append(cur)
            cur = w
        else:
            cur = (cur + " " + w).strip()
    return lines + [cur]


def clip(lines, n, where):
    """Keep the first n lines and say so on stderr, so cut-off text is never silent."""
    if len(lines) > n:
        print(f"warning: {where} needs {len(lines)} lines, only {n} fit; shorten it", file=sys.stderr)
    return lines[:n]


def accent_line(x, y, line, size):
    """'{and} Analytics Lead' renders 'and' in the accent color."""
    parts = re.split(r"(\{[^}]*\})", line)
    spans = "".join(f'<tspan class="acct">{esc(p[1:-1])}</tspan>' if p.startswith("{") else esc(p)
                    for p in parts if p)
    return f'<text x="{x}" y="{y}" font-size="{size:.0f}" font-weight="600" letter-spacing="-1.6">{spans}</text>'


# ------------------------------------------------------------------ cards
def hero(p):
    H = 340
    b = ['<defs><pattern id="g" width="40" height="40" patternUnits="userSpaceOnUse">'
         '<path d="M40 0H0V40" fill="none" stroke="var(--line)"/></pattern>'
         '<radialGradient id="glow"><stop offset="0" stop-color="var(--acc)" stop-opacity=".22"/>'
         '<stop offset="1" stop-color="var(--acc)" stop-opacity="0"/></radialGradient>'
         f'<clipPath id="clip"><rect width="{W}" height="{H}" rx="18"/></clipPath></defs>',
         f'<g clip-path="url(#clip)"><rect width="{W}" height="{H}" class="bg2"/>'
         f'<rect width="{W}" height="{H}" fill="url(#g)" opacity=".6"/><circle cx="800" cy="150" r="260" fill="url(#glow)"/></g>'
         f'<rect x=".5" y=".5" width="{W-1}" height="{H-1}" rx="18" fill="none" stroke="var(--line)"/>',
         '<g class="rise"><circle cx="52" cy="62" r="5" class="dot"/><circle cx="52" cy="62" r="5" class="dot ping"/>',
         T(66, 67, p["name"].upper(), 13, "mono q", 500, extra='letter-spacing="2.4"')]
    lines = p["title_lines"][:2]
    size = min(50, 470 / max(tw(re.sub(r"[{}]", "", ln), 1) for ln in lines))
    for i, ln in enumerate(lines):
        b.append(accent_line(44, 128 + i * 56, ln, size))
    for i, ln in enumerate(p.get("tagline", [])[:2]):
        b.append(T(46, 222 + i * 22, ln, 16, "mut"))
    b.append("</g>")

    css = ""
    msgs = p.get("ticker", [])
    if msgs:
        step = 3.2
        dur = len(msgs) * step
        b += ['<rect x="44" y="270" width="420" height="38" rx="10" class="card"/>',
              '<rect x="58" y="282" width="46" height="14" rx="7" fill="var(--okbg)"/><circle cx="66" cy="289" r="3" class="gr"/>',
              T(73, 293, "LIVE", 9.5, "mono gr", 600, extra='letter-spacing="1"')]
        for i, m in enumerate(msgs):
            a, e = i * step / dur * 100, (i + 1) * step / dur * 100
            css += (f"@keyframes t{i}{{0%{{opacity:0}}{a:.2f}%{{opacity:0;transform:translateY(6px)}}"
                    f"{a+2.5:.2f}%{{opacity:1;transform:none}}{e-2.5:.2f}%{{opacity:1;transform:none}}"
                    f"{e:.2f}%{{opacity:0;transform:translateY(-6px)}}100%{{opacity:0}}}}"
                    f".t{i}{{opacity:0;animation:t{i} {dur:.1f}s linear infinite}}")
            b.append(T(114, 294, m, min(13.5, 336 / tw(m, 1)), f"t{i}", 500))  # shrink long lines to fit
        css += "@media (prefers-reduced-motion:reduce){.t0{opacity:1}}"

    f = p.get("flow")
    if f:
        hx, hy = 790, 168
        ys = [70 + i * 56 for i in range(len(f["inputs"][:4]))]
        paths = []
        for name, y in zip(f["inputs"], ys):
            d = f"M678 {y} C 730 {y}, 720 {hy}, {hx-46} {hy}"
            paths.append(d)
            b += [f'<path d="{d}" class="wire"/>', f'<rect x="560" y="{y-17}" width="118" height="34" rx="9" class="card2"/>',
                  T(619, y + 5, name, 13, "", 500, "middle")]
        out_d = f"M{hx+46} {hy} L 868 {hy}"
        b += [f'<path d="{out_d}" class="wire"/>',
              f'<circle cx="{hx}" cy="{hy}" r="46" fill="var(--acc)" opacity=".18" class="ping"/>',
              f'<circle cx="{hx}" cy="{hy}" r="46" fill="var(--acc)"/>',
              T(hx, hy - 3, f["hub"][0], 13, "on", 600, "middle"), T(hx, hy + 14, f["hub"][1], 13, "on", 600, "middle"),
              f'<rect x="868" y="{hy-22}" width="104" height="44" rx="10" fill="var(--card)" stroke="var(--acc)" stroke-width="1.6"/>',
              T(920, hy - 1, f["output"][0], 13, "", 600, "middle"), T(920, hy + 14, f["output"][1], 10.5, "mono q", 400, "middle")]
        for i, d in enumerate(paths):
            b.append(f'<circle r="4" class="dot mover"><animateMotion dur="2.6s" begin="-{i*.45:.2f}s" '
                     f'repeatCount="indefinite" path="{d}"/></circle>')
        b.append(f'<circle r="4.5" fill="var(--gr)" class="mover"><animateMotion dur="1.3s" '
                 f'repeatCount="indefinite" path="{out_d}"/></circle>')
    title = f"{p['name']}, {' '.join(re.sub(r'[{}]', '', ln) for ln in lines)}. {' '.join(p.get('tagline', []))}"
    return svg(W, H, "".join(b), title, css)


def pillars(p):
    P, H, gap = p["pillars"][:5], 236, 12
    cw = (W - 2 - gap * (len(P) - 1)) / len(P)
    b = []
    for i, it in enumerate(P):
        x = 1 + i * (cw + gap)
        b += [f'<g class="rise" style="animation-delay:{i*.08:.2f}s">',
              f'<rect x="{x:.1f}" y="1" width="{cw:.1f}" height="{H-2}" rx="14" class="card"/>',
              f'<rect x="{x+18:.1f}" y="20" width="40" height="40" rx="11" fill="var(--acc)" fill-opacity=".12"/>',
              f'<g transform="translate({x+38:.1f} 40)" fill="none" stroke="var(--acct)" stroke-width="1.8" '
              f'stroke-linecap="round" stroke-linejoin="round">{ICONS.get(it.get("icon"), ICONS["spark"])}</g>',
              T(x + 18, 90, it["title"], 16, "", 650)]
        b += [T(x + 18, 116 + k * 19, ln, 13, "mut") for k, ln in enumerate(clip(wrap(it["text"], 13, cw - 36), 5, f"pillar {it['title']!r}"))]
        b.append("</g>")
    return svg(W, H, "".join(b), "What I do: " + ", ".join(it["title"] for it in P) + ".")


def metrics(p):
    M, H, gap = p["metrics"][:4], 210, 16
    cw = (W - 2 - gap * (len(M) - 1)) / len(M)
    b = []
    for i, m in enumerate(M):
        x, d = 1 + i * (cw + gap), i * 0.12
        top = max(m["before_value"], m["after_value"]) or 1
        full = cw - 40
        b += [f'<g class="rise" style="animation-delay:{d:.2f}s">',
              f'<rect x="{x:.1f}" y="1" width="{cw:.1f}" height="{H-2}" rx="14" class="card"/>',
              *[T(x + 20, 34 + k * 19, ln, 14, "mut") for k, ln in enumerate(m["label"][:2])],
              T(x + 20, 96, m["before"], 17, "q"),
              f'<line x1="{x+19:.1f}" y1="90" x2="{x+21+tw(m["before"], 17):.1f}" y2="90" stroke="var(--line2)" stroke-width="1.5"/>',
              T(x + 20, 134, m["after"], 32, "", 650, extra='letter-spacing="-1"'),
              f'<rect x="{x+20:.1f}" y="158" width="{max(5, full*m["before_value"]/top):.1f}" height="7" rx="3.5" '
              f'fill="var(--line2)" class="grow" style="animation-delay:{d+.2:.2f}s"/>',
              f'<rect x="{x+20:.1f}" y="172" width="{max(5, full*m["after_value"]/top):.1f}" height="7" rx="3.5" '
              f'fill="var(--acc)" class="grow" style="animation-delay:{d+.5:.2f}s"/>',
              T(x + 20, 198, "BEFORE  /  AFTER", 9.5, "mono q", 500, extra='letter-spacing="1.2"'), "</g>"]
    title = "Results: " + "; ".join(f"{' '.join(m['label'])} {m['before']} to {m['after']}" for m in M) + "."
    return svg(W, H, "".join(b), title)


def work(p):
    Wk, cols, gap, ch = p["work"], 3, 14, 150
    cw = (W - 2 - gap * (cols - 1)) / cols
    b = []
    for i, it in enumerate(Wk):
        r, c = divmod(i, cols)
        x, y = 1 + c * (cw + gap), 1 + r * (ch + gap)
        b += [f'<g class="rise" style="animation-delay:{i*.08:.2f}s">',
              f'<rect x="{x:.1f}" y="{y}" width="{cw:.1f}" height="{ch}" rx="14" class="card"/>',
              T(x + 20, y + 26, f"{i+1:02d}", 11, "mono acct", 600),
              f'<circle cx="{x+cw-24:.1f}" cy="{y+22}" r="4" class="gr"/>'
              f'<circle cx="{x+cw-24:.1f}" cy="{y+22}" r="4" fill="var(--gr)" class="ping"/>',
              T(x + 20, y + 54, it["title"], 17, "", 650),
              *[T(x + 20, y + 78 + k * 18, ln, 13, "mut") for k, ln in enumerate(clip(wrap(it["text"], 13, cw - 40), 2, f"work card {it['title']!r}"))],
              f'<line x1="{x+20:.1f}" y1="{y+ch-38}" x2="{x+cw-20:.1f}" y2="{y+ch-38}" stroke="var(--line)"/>',
              T(x + 20, y + ch - 15, it["metric"], 15, "", 650), "</g>"]
    rows = -(-len(Wk) // cols)
    return svg(W, rows * ch + (rows - 1) * gap + 2, "".join(b), "Selected work: " + ", ".join(it["title"] for it in Wk) + ".")


def stack(p):
    colw, gap, fs, ph, pv, cg, rg = 491, 16, 12, 10, 24, 6, 8
    blocks = []
    for g in p["stack"]:
        rows, cur, used = [], [], 0
        for it in g["items"]:
            w = tw(it, fs) + 2 * ph
            if cur and used + w > colw - 36:
                rows.append(cur)
                cur, used = [], 0
            cur.append((it, w))
            used += w + cg
        rows.append(cur)
        blocks.append((g["group"], rows, 52 + len(rows) * (pv + rg) + 10))
    b, y = [], 1
    for r in range(0, len(blocks), 2):
        pair = blocks[r:r + 2]
        hh = max(blk[2] for blk in pair)
        for c, (title, rows, _) in enumerate(pair):
            x = 1 + c * (colw + gap)
            b += [f'<g class="rise" style="animation-delay:{r*.08+c*.05:.2f}s">',
                  f'<rect x="{x}" y="{y}" width="{colw}" height="{hh}" rx="14" class="card"/>',
                  T(x + 18, y + 32, title, 15, "", 650),
                  T(x + colw - 18, y + 32, sum(len(rw) for rw in rows), 11, "mono q", 500, "end")]
            yy = y + 48
            for rw in rows:
                xx = x + 18
                for it, w in rw:
                    b += [f'<rect x="{xx:.1f}" y="{yy}" width="{w:.1f}" height="{pv}" rx="7" class="card2"/>',
                          T(xx + w / 2, yy + 16, it, fs, "mut", 500, "middle")]
                    xx += w + cg
                yy += pv + rg
            b.append("</g>")
        y += hh + gap
    return svg(W, y - gap + 1, "".join(b), "Stack: " + ", ".join(g["group"] for g in p["stack"]) + ".")


CARDS = {"hero": hero, "pillars": pillars, "metrics": metrics, "work": work, "stack": stack}


# ------------------------------------------------------------------ build
def build(profile: dict, out: Path):
    """Write every card the profile has content for. Returns the card names written."""
    for key in ("name", "title_lines"):
        if not profile.get(key):
            raise ValueError(f"profile.json needs '{key}'")
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for name, fn in CARDS.items():
        if name != "hero" and not profile.get(name):
            continue  # optional section left out of the profile
        content = fn(profile)
        for mode in PALETTES:
            (out / f"{name}-{mode}.svg").write_text(content.replace("@@PAL@@", palette_css(mode, profile.get("palette", {}))))
        written.append(name)
    return written


def snippet(card: str, alt: str, folder: str = "assets") -> str:
    return (f'<picture>\n  <source media="(prefers-color-scheme: dark)" srcset="{folder}/{card}-dark.svg">\n'
            f'  <img alt="{esc(alt)}" src="{folder}/{card}-light.svg" width="100%">\n</picture>')


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("profile", nargs="?", default="profile.json", type=Path)
    ap.add_argument("--out", default="assets", type=Path)
    ap.add_argument("--snippet", action="store_true", help="print <picture> markdown for each card")
    args = ap.parse_args(argv)
    profile = json.loads(args.profile.read_text())
    for name in build(profile, args.out):
        sizes = [(args.out / f"{name}-{m}.svg").stat().st_size for m in PALETTES]
        print(f"wrote {args.out}/{name}-light.svg + -dark.svg  ({sizes[0]:,} bytes)")
        if args.snippet:
            print(snippet(name, f"{profile['name']}: {name}", str(args.out)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
