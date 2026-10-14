#!/usr/bin/env python3
"""Put a windmill in the profile banner, spinning at a speed you pass in.

    python3 scripts/windmill.py --wind 6.0

The banner (header.svg) is owned by yuki4266/living-scene, which repaints the sky
between its <!--WEATHER--> markers every few hours. This windmill lives OUTSIDE
those markers, on a patch of canvas the weather never touches, so the two never
fight. Re-running replaces the windmill in place rather than stacking a second one.

    --wind      wind speed in km/h; sets the rotation period
    --hover     what hovering the rotor does: slow (default), stop, or off
    --x/--y     hub position        --radius  blade length
    --spin      only refresh the speed, keep the existing caption wording

Rotation law: period = 60 / (1 + wind_km/h) seconds per turn. Calm air crawls at
one turn a minute; a 6 km/h breeze turns in ~8.6s; a 40 km/h gale whips round in
~1.5s. The rotor is never still, so the banner never looks broken.

How the speed is actually produced
----------------------------------
Two rotations are stacked additively on the rotor group: one driven by CSS, one
by SMIL. They must add up to the intended rate, so they are given shares of it
(see LAYERS). Stacking buys the hover brake: CSS can be retimed and paused, SMIL
cannot, so pausing the CSS share drops the rotor to the SMIL share and the blades
visibly ease down instead of stopping dead.

If GitHub strips the <style> — it sanitises SVGs aggressively — the SMIL share
survives untouched and the windmill still turns at the speed it was baked with,
just slower than intended. The feature degrades instead of breaking.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_FILES = ["header.svg", "header-night.svg"]

BEGIN = "<!--WINDMILL-->"
END = "<!--/WINDMILL-->"
STYLE_END = "<!--/WINDMILL-STYLE-->"

PETAL = "#F4795B"      # the banner's coral
PETAL_TIP = "#E2542F"  # its deeper coral
HUB = "#FFD9A0"        # the banner's cream
TOWER = "#8b949e"      # the muted grey the banner already uses for its tagline

# (name, share of the rotation rate, retimeable by CSS, class)
# CSS carries two thirds so it has real authority over the speed; SMIL keeps one
# third, which is the floor the windmill falls back to when CSS is unavailable.
LAYERS = (
    ("css", 2 / 3, True, "wm-css0"),
    ("smil", 1 / 3, False, "wm-smil0"),
)

# Blade shape: widest near the hub, tapering to a point at the rim; the two -R /
# -0.66R tokens are substituted with the radius by blades().
BLADE_D = "M11 -7 C21 -27 9 -0.66R 0 -1R C-9 -0.66R -21 -27 -11 -7 Z"
TIP_R = 0.06  # tip dot radius, as a fraction of --radius

# "stop" stretches the SMIL layer out to this period once CSS has let go.
SLOW_TO = 300
HOVER_EASE = 1.4


def period_for(wind_kmh: float) -> float:
    """Seconds per revolution for a given wind speed."""
    return 60.0 / (1.0 + max(0.0, float(wind_kmh)))


def beaufort(wind_kmh: float) -> int:
    """Beaufort force from km/h, using the standard 1 km/h = 0.539957 kn."""
    kn = max(0.0, float(wind_kmh)) * 0.539957
    for force, top in enumerate([1, 3, 6, 10, 16, 21, 27, 33, 40, 47, 55, 63]):
        if kn < top:
            return force
    return 12


def layer_period(period: float, share: float) -> float:
    """A layer holding `share` of the rate needs duration period/share, because
    rate = 1/duration and the layers' rates are what add up."""
    return period / share


def blades(radius: float) -> str:
    d = BLADE_D.replace("-0.66R", f"{-0.66 * radius:.2f}").replace("-1R", f"{-radius:.2f}")
    tip = max(3.0, radius * TIP_R)
    return "".join(
        f'<g transform="rotate({i * 45})">'
        f'<path d="{d}" fill="{PETAL}"/>'
        f'<circle cx="0" cy="{-radius:.2f}" r="{tip:.2f}" fill="{PETAL_TIP}"/>'
        f"</g>"
        for i in range(8)
    )


def spin_anims(period: float) -> str:
    """One additive <animateTransform> per layer, each carrying its own share."""
    return "".join(
        f'<animateTransform class="{cls}" attributeName="transform" type="rotate" '
        f'from="0" to="360" dur="{layer_period(period, share):.3f}s" '
        f'repeatCount="indefinite" additive="sum"/>'
        for _, share, _, cls in LAYERS
    )


def css_for(period: float, hover: str) -> str:
    """Drive the CSS layer, then take it away on hover (the brake)."""
    rules = []
    for name, share, retimeable, cls in LAYERS:
        if not retimeable:
            continue
        t = layer_period(period, share)
        rules.append(f".wm-rotor .{cls}{{animation:wm-{name} {t:.3f}s linear infinite}}")
        rules.append(f"@keyframes wm-{name}{{from{{transform:rotate(0)}}"
                     f"to{{transform:rotate(360deg)}}}}")
    if hover == "off":
        return "".join(rules)

    releasable = [cls for _, _, retimeable, cls in LAYERS if retimeable]
    rules.append("".join(f".wm-rotor:hover .{cls}{{animation-play-state:paused}}"
                         for cls in releasable))
    if hover == "stop":
        # stretch what is left so the coast down ends near a standstill; the angle
        # is 360*t/dur on both sides of a duration change, so it stays continuous
        rules.append("".join(f".wm-rotor:hover .{cls}{{animation-duration:{SLOW_TO}s}}"
                             for _, _, retimeable, cls in LAYERS if not retimeable))
    return "".join(rules)


def style_block(period: float, hover: str) -> str:
    return f"<!--WINDMILL-STYLE-->{css_for(period, hover)}{STYLE_END}"


def inject_style(text: str, period: float, hover: str) -> str:
    """Write (or refresh) the <style> block inside the root <svg> element."""
    block = style_block(period, hover)
    existing = re.compile(r"<!--WINDMILL-STYLE-->.*?" + re.escape(STYLE_END), re.S)
    if existing.search(text):
        # a lambda, not a string: the CSS is full of backslashes and re.sub would
        # read them as escape sequences and mangle the whole file
        return existing.sub(lambda _: block, text, count=1)
    m = re.search(r"<svg\b[^>]*>", text)
    if not m:
        raise SystemExit("no root <svg> element found")
    return text[:m.end()] + "\n" + block + text[m.end():]


def build(x: float, y: float, radius: float, period: float,
          caption: str) -> str:
    """The windmill: tower, rotating rotor, hub, and an optional caption."""
    hub_r = max(7.0, radius * 0.17)
    # tower scales with the rotor so the silhouette stays a windmill, not a mast
    tower_h = radius * 0.55 + 26
    half_top, half_bot = radius * 0.16, radius * 0.28

    parts = [BEGIN, "<g>",
             # one fade-in for the whole assembly, matching the banner's timing
             '<animate attributeName="opacity" from="0" to="1" begin="1.9s" '
             'dur="0.9s" fill="freeze"/>']

    parts.append(
        f'<path d="M{-half_top:.1f} 0 L{-half_bot:.1f} {tower_h:.1f} '
        f'L{half_bot:.1f} {tower_h:.1f} L{half_top:.1f} 0 Z" '
        f'fill="{TOWER}" fill-opacity="0.13"/>'
    )
    for i in range(1, 5):
        t = i / 5.0
        ly, lx = tower_h * t, half_top + (half_bot - half_top) * t
        parts.append(f'<path d="M{-lx:.1f} {ly:.1f} H {lx:.1f}" stroke="{TOWER}" '
                     f'stroke-opacity="0.3" stroke-width="1.4"/>')
    for sx in (-1, 1):
        parts.append(f'<path d="M{sx * half_top:.1f} 1 L{sx * half_bot:.1f} {tower_h:.1f}" '
                     f'stroke="{TOWER}" stroke-opacity="0.55" stroke-width="2.2" '
                     f'stroke-linecap="round"/>')
    parts.append(
        f'<path d="M{-half_bot * 0.34:.1f} {tower_h:.1f} L{-half_bot * 0.34:.1f} '
        f'{tower_h - radius * 0.3:.1f} Q0 {tower_h - radius * 0.48:.1f} '
        f'{half_bot * 0.34:.1f} {tower_h - radius * 0.3:.1f} '
        f'L{half_bot * 0.34:.1f} {tower_h:.1f} Z" fill="{PETAL_TIP}" fill-opacity="0.45"/>'
    )

    # rotor — the only thing that turns
    parts.append(
        f'<g transform="translate(0,-{radius * 0.55:.1f})">'
        f'<g class="wm-rotor">{blades(radius)}{spin_anims(period)}</g>'
        f'<circle r="{hub_r:.1f}" fill="{HUB}" stroke="{PETAL_TIP}" stroke-width="2"/>'
        f'<circle r="{max(2.5, hub_r * 0.34):.1f}" fill="{PETAL_TIP}"/>'
        f"</g>"
    )

    if caption:
        parts.append(f'<text x="0" y="{tower_h + 17:.1f}" text-anchor="middle" '
                     f'font-size="11" letter-spacing="0.6" fill="{TOWER}">{caption}</text>')

    parts.append(f"</g>\n{END}")
    return f'<g transform="translate({x:g},{y:g})">\n' + "\n".join(parts) + "\n</g>"


def inject(text: str, block: str) -> str:
    """Replace an existing windmill, else insert one just before the name text."""
    if BEGIN in text and END in text:
        start = text.rindex("<g", 0, text.index(BEGIN))
        end = text.index("</g>", text.index(END) + len(END)) + len("</g>")
        return text[:start] + block + text[end:]

    anchor = "  <!-- text -->"
    if anchor not in text:
        raise SystemExit("anchor '<!-- text -->' not found — header.svg layout changed")
    return text.replace(
        anchor,
        "  <!-- windmill: spins at the real wind speed, see scripts/windmill.py -->\n"
        f"  {block}\n\n{anchor}",
        1,
    )


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--wind", type=float, required=True, help="wind speed in km/h")
    ap.add_argument("--beaufort", type=int, default=None, help="override the Beaufort number")
    ap.add_argument("--hover", choices=["slow", "stop", "off"], default="slow",
                    help="hovering the rotor: brake to the SMIL share (default), "
                         "coast to a near stop, or nothing")
    ap.add_argument("--x", type=float, default=232.0)
    ap.add_argument("--y", type=float, default=80.0)
    ap.add_argument("--radius", type=float, default=36.0)
    ap.add_argument("--files", nargs="*", default=DEFAULT_FILES)
    ap.add_argument("--no-caption", action="store_true", help="omit the speed caption")
    ap.add_argument("--spin", action="store_true",
                    help="refresh the speed but keep the existing caption wording")
    ap.add_argument("--keep-caption", action="store_true",
                    help="refresh the speed and leave the caption exactly as it is")
    args = ap.parse_args()

    period = period_for(args.wind)
    bf = args.beaufort if args.beaufort is not None else beaufort(args.wind)
    caption = "" if args.no_caption else f"{args.wind:.1f} km/h · Beaufort {bf}"

    for name in args.files:
        path = ROOT / name
        if not path.exists():
            print(f"  {name}: missing, skipped", file=sys.stderr)
            continue
        text = path.read_text(encoding="utf-8")
        # preserve the caption already in the file when asked, so a scheduled
        # refresh never rewrites wording the owner may have edited
        cap = caption
        if args.spin or args.keep_caption:
            m = re.search(re.escape(BEGIN) + r".*?</text>", text, re.S)
            if m:
                found = re.search(r">([^<]*)</text>", m.group(0))
                if found:
                    cap = found.group(1)
        new = inject_style(inject(text, build(args.x, args.y, args.radius, period, cap)),
                           period, args.hover)
        path.write_text(new, encoding="utf-8")
        print(f"  {name}: windmill at ({args.x:g},{args.y:g}) r={args.radius:g} — "
              f"{args.wind:.1f} km/h -> {period:.2f}s/turn "
              f"(css {layer_period(period, LAYERS[0][1]):.2f}s + "
              f"smil {layer_period(period, LAYERS[1][1]):.2f}s), hover={args.hover}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
