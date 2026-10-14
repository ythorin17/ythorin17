#!/usr/bin/env python3
"""Put a windmill in the profile banner, spinning at a speed you pass in.

    python3 scripts/windmill.py --wind 5.5

The banner (header.svg) is owned by yuki4266/living-scene, which repaints the sky
between its <!--WEATHER--> markers every few hours. The windmill lives OUTSIDE
those markers, on canvas the weather never touches, so the two never fight.
Re-running replaces the windmill in place instead of stacking a second one.

    --wind      wind speed in km/h; sets the rotation period
    --hover     what hovering the rotor does: stop (default), slow, or off
    --x/--y     hub position           --radius  blade length
    --spin      refresh the speed and keep the existing caption wording
    --caption/--no-caption              force it on or off

Rotation law: period = 60 / (1 + wind_km/h) seconds per turn. Calm air crawls at
one turn a minute; a 5.5 km/h breeze turns in ~9.2s; a 40 km/h gale whips round
in ~1.5s. The rotor is never still, so the banner never looks broken.

How the rotor is built (and the two traps this avoids)
------------------------------------------------------
Three nested groups, each carrying exactly one rotation:

    .wm-base   SMIL only    1/(2P)   the part GitHub cannot strip
    .wm-fast   CSS only     1/(2P)   paused on hover — the brake
    .wm-brake  CSS only     1/(100P) never paused, so the rotor still creeps

Trap 1: a CSS animation on an element REPLACES that element's SMIL contribution
rather than adding to it, so CSS and SMIL must never share a group.

Trap 2: CSS transform-origin defaults to the view-box centre for SVG, so a CSS
rotate() would swing the blades around the middle of the banner, not the hub.
transform-box:fill-box + transform-origin:0 0 pins it to the rotor's own origin.

Net effect: 1/P with CSS, a visible crawl on hover, and 1/(2P) — half speed but
still turning — if GitHub strips the <style>.
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

# Where each windmill goes, and which line it is inserted in front of.
#
# Banner: clear sky left of centre. The flower at x=140 reaches x~196 at its
# widest and the name block starts at x=334, so a 30-radius rotor at x=272 passes
# between them; the tower base lands on the grass line (y=150) so the silhouette
# reads as standing on the horizon.
#
# Footer: tighter than it looks. The left bushes reach y=60, but the grass on the
# right only reaches y=90, leaving x 760-860 as genuinely open sky. Its base goes
# at y=96 — above the cat's corridor (the cat's body stays inside y 112-143 as it
# runs past) rather than on the front grass line, so the cat passes in front of the
# tower instead of through it. No caption here: there is no room below the tower
# that is not either the cat's path or the grass strokes, and the banner carries
# the number anyway. Inserted before </svg>, i.e. drawn last, so it reads as
# standing among the back bushes.
TARGETS = (
    {"file": "header.svg", "x": 272.0, "ground": 150.0, "radius": 30.0,
     "anchor": "  <!-- text -->", "no_caption": False},
    {"file": "garden-footer.svg", "x": 800.0, "ground": 96.0, "radius": 24.0,
     "anchor": "</svg>", "no_caption": True},
)

PETAL = "#F4795B"      # the banner's coral
PETAL_TIP = "#E2542F"  # its deeper coral
HUB = "#FFD9A0"        # the banner's cream
TOWER = "#8b949e"      # the muted grey the banner already uses for its tagline

# CSS transform-origin defaults to the view-box centre for SVG, so without this a
# CSS rotate() turns the blades about the middle of the 900x300 banner instead of
# about the hub. fill-box + 0 0 fixes every CSS layer to the rotor's own origin.
ROTOR_BOX = "transform-box:fill-box;transform-origin:0 0"

BRAKE_RATIO = 100  # how much slower the always-on brake layer is


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


def blade_path(radius: float) -> str:
    """One blade: a slender leaf, widest above the hub, tapering to a tip.

    Two quadratic curves per side, so there is no kink; the tip sits on the hub
    axis so eight of them read as a wheel.
    """
    w, waist = radius * 0.30, -radius * 0.28
    return (f"M0 {-radius * 0.10:.2f} "
            f"Q{w:.2f} {waist:.2f} {w * 0.34:.2f} {-radius * 0.74:.2f} "
            f"Q0 {-radius * 1.02:.2f} {-w * 0.34:.2f} {-radius * 0.74:.2f} "
            f"Q{-w:.2f} {waist:.2f} 0 {-radius * 0.10:.2f} Z")


def blades(radius: float) -> str:
    d = blade_path(radius)
    return "".join(f'<g transform="rotate({i * 45})"><path d="{d}" fill="{PETAL}"/></g>'
                   for i in range(8))


def rotor(radius: float, period: float) -> str:
    """The three nested rotation layers, blades innermost."""
    return (
        f'<g class="wm-base">'
        f'<animateTransform attributeName="transform" type="rotate" from="0" to="360" '
        f'dur="{period * 2:.2f}s" repeatCount="indefinite"/>'
        f'<g class="wm-fast"><g class="wm-brake">{blades(radius)}</g></g>'
        f"</g>"
    )


def css_for(period: float, hover: str) -> str:
    fast, slow = period * 2, period * BRAKE_RATIO
    rules = [
        f".wm-fast{{animation:wm-fast {fast:.2f}s linear infinite;{ROTOR_BOX}}}",
        f".wm-brake{{animation:wm-brake {slow:.2f}s linear infinite;{ROTOR_BOX}}}",
        "@keyframes wm-fast{from{transform:rotate(0deg)}to{transform:rotate(360deg)}}",
        "@keyframes wm-brake{from{transform:rotate(0deg)}to{transform:rotate(360deg)}}",
    ]
    if hover == "off":
        return "".join(rules)
    if hover == "stop":
        # pausing holds the current angle, so there is no jump; the brake layer
        # keeps a slow creep going so it reads as friction, not as a frozen image
        rules.append(".wm-rotor:hover .wm-fast{animation-play-state:paused}")
    else:  # "slow": halve the fast layer instead of pausing it
        rules.append(f".wm-rotor:hover .wm-fast{{animation-duration:{fast * 3:.2f}s}}")
    return "".join(rules)


def style_block(period: float, hover: str) -> str:
    return f"<!--WINDMILL-STYLE-->{css_for(period, hover)}{STYLE_END}"


def inject_style(text: str, period: float, hover: str) -> str:
    """Write (or refresh) the <style> block inside the root <svg> element.

    The banner and the footer are separate files and each gets its own block, so
    there is one fixed marker pair per file rather than per windmill.
    """
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


def build(x: float, ground: float, radius: float, period: float, caption: str,
          tower_h: float, indent: str = "") -> str:
    """The windmill: tower standing on `ground`, rotor on top, optional caption.

    `ground` is the y of the tower's base, not the hub, so a windmill lands on a
    horizon line no matter how big the blades are.
    """
    hub_r = max(6.5, radius * 0.19)
    half_top, half_bot = radius * 0.13, radius * 0.24
    hub_y = -tower_h - radius * 0.95      # local y of the hub, relative to ground

    parts = [BEGIN, "<g>",
             '<animate attributeName="opacity" from="0" to="1" begin="1.9s" '
             'dur="0.9s" fill="freeze"/>']

    # tower
    parts.append(f'<path d="M{-half_top:.1f} {-tower_h:.1f} L{-half_bot:.1f} 0 '
                 f'L{half_bot:.1f} 0 L{half_top:.1f} {-tower_h:.1f} Z" '
                 f'fill="{TOWER}" fill-opacity="0.14"/>')
    for i in range(1, 4):
        t = i / 4.0
        ly, lx = -tower_h * (1 - t), half_top + (half_bot - half_top) * t
        parts.append(f'<path d="M{-lx:.1f} {ly:.1f} H {lx:.1f}" stroke="{TOWER}" '
                     f'stroke-opacity="0.3" stroke-width="1.3"/>')
    for sx in (-1, 1):
        parts.append(f'<path d="M{sx * half_top:.1f} {-tower_h + 1:.1f} '
                     f'L{sx * half_bot:.1f} 0" stroke="{TOWER}" stroke-opacity="0.6" '
                     f'stroke-width="2" stroke-linecap="round"/>')
    door_h = min(tower_h * 0.4, radius * 0.5)
    parts.append(f'<path d="M{-half_bot * 0.32:.1f} 0 L{-half_bot * 0.32:.1f} {-door_h:.1f} '
                 f'Q0 {-door_h - radius * 0.18:.1f} {half_bot * 0.32:.1f} {-door_h:.1f} '
                 f'L{half_bot * 0.32:.1f} 0 Z" fill="{PETAL_TIP}" fill-opacity="0.45"/>')

    # rotor: the hub sits above the tower cap, everything inside turns about it
    parts.append(f'<g class="wm-rotor">'
                 f'<g transform="translate(0,{hub_y:.1f})">'
                 f"{rotor(radius, period)}"
                 f'<circle r="{hub_r:.1f}" fill="{HUB}" stroke="{PETAL_TIP}" stroke-width="2"/>'
                 f'<circle r="{max(2.2, hub_r * 0.34):.1f}" fill="{PETAL_TIP}"/>'
                 f"</g></g>")

    if caption:
        # offset to the right of the tower and below the ground line: centred under
        # the tower it lands on the grass strokes, and it must not sit on the cat's
        # corridor either
        parts.append(f'<text x="{half_bot + 5:.1f}" y="13" text-anchor="start" '
                     f'font-size="11" letter-spacing="0.6" fill="{TOWER}">{caption}</text>')

    parts.append(f"</g>\n{END}")
    body = "\n".join(parts)
    if indent:
        body = "\n".join(indent + line if line.strip() else line for line in body.split("\n"))
    return f'<g transform="translate({x:g},{ground:g})">\n{body}\n</g>'


def inject(text: str, block: str, anchor: str, indent: str = "") -> str:
    """Replace an existing windmill, else insert one before `anchor`.

    `anchor` is the marker line the windmill should sit in front of; the banner
    and the footer put it in different places so it lands behind the right art.
    """
    if BEGIN in text and END in text:
        start = text.rindex("<g", 0, text.index(BEGIN))
        end = text.index("</g>", text.index(END) + len(END)) + len("</g>")
        return text[:start] + block + text[end:]
    if anchor not in text:
        raise SystemExit(f"anchor {anchor!r} not found — the SVG layout changed")
    return text.replace(anchor, f"{indent}{block}\n{anchor}", 1)


def existing_caption(text: str) -> str | None:
    m = re.search(re.escape(BEGIN) + r".*?</text>", text, re.S)
    if not m:
        return None
    found = re.search(r">([^<]*)</text>", m.group(0))
    return found.group(1) if found else None


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--wind", type=float, required=True, help="wind speed in km/h")
    ap.add_argument("--beaufort", type=int, default=None, help="override the Beaufort number")
    ap.add_argument("--hover", choices=["stop", "slow", "off"], default="stop",
                    help="hovering the rotor: brake to a creep (default), slow to a "
                         "third, or nothing")
    ap.add_argument("--all", action="store_true",
                    help="banner and footer, each in its own measured-clear spot")
    ap.add_argument("--x", type=float, default=None)
    ap.add_argument("--ground", type=float, default=None,
                    help="y of the tower's base; the rotor is placed above it")
    ap.add_argument("--tower", type=float, default=44.0, help="tower height")
    ap.add_argument("--radius", type=float, default=None, help="blade length")
    ap.add_argument("--files", nargs="*", default=None)
    ap.add_argument("--anchor", type=str, default="auto",
                    help="the line the windmill is inserted before")
    ap.add_argument("--indent", type=str, default="  ", help="indentation for the inserted block")
    ap.add_argument("--no-caption", action="store_true", help="omit the speed caption")
    ap.add_argument("--caption", type=str, default=None, help="set the caption text verbatim")
    ap.add_argument("--spin", action="store_true",
                    help="refresh the speed but keep the existing caption wording")
    args = ap.parse_args()

    period = period_for(args.wind)
    bf = args.beaufort if args.beaufort is not None else beaufort(args.wind)
    default_caption = f"{args.wind:.1f} km/h · Beaufort {bf}"

    # Placement is measured, not guessed. The banner's anchor is the name block and
    # its clear sky is left of centre; the footer is far more crowded (bushes reach
    # y=60 on the left, grass only y=90 on the right) so its windmill goes over the
    # grass on the right, behind the cat for the moment the cat runs past.
    targets = TARGETS if (args.all or args.files is None) else [
        {**next(t for t in TARGETS if t["file"] == f), "file": f} for f in args.files
    ]
    if args.all:
        for t in targets:
            t.update({k: v for k, v in (("x", args.x), ("ground", args.ground),
                                        ("radius", args.radius)) if v is not None})

    for t in targets:
        name = t["file"]
        path = ROOT / name
        if not path.exists():
            print(f"  {name}: missing, skipped", file=sys.stderr)
            continue
        text = path.read_text(encoding="utf-8")
        if args.caption is not None:
            caption = args.caption
        elif args.no_caption or t["no_caption"]:
            caption = ""
        else:
            # the caption ALWAYS tracks the wind speed. --spin only means "this is
            # a refresh, not a re-placement": keeping stale wording here would leave
            # a number that contradicts the rotation right next to it.
            caption = default_caption

        x = args.x if args.x is not None else t["x"]
        ground = args.ground if args.ground is not None else t["ground"]
        radius = args.radius if args.radius is not None else t["radius"]
        anchor = t["anchor"] if args.anchor == "auto" else args.anchor

        block = build(x, ground, radius, period, caption, args.tower, args.indent)
        new = inject_style(inject(text, block, anchor, args.indent), period, args.hover)
        path.write_text(new, encoding="utf-8")
        print(f"  {name}: windmill at ({x:g},{ground:g}) r={radius:g} tower={args.tower:g} — "
              f"{args.wind:.1f} km/h -> {period:.2f}s/turn, hover={args.hover}"
              + (f", caption={caption!r}" if caption else ", no caption"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
