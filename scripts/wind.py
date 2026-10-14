#!/usr/bin/env python3
"""Refresh the windmill so it turns at the real wind speed right now.

    python3 scripts/wind.py

Asks Open-Meteo (the same key-free source living-scene uses for the sky) for the
current wind where you live, then hands the number to windmill.py. The scene
workflow runs this after every banner repaint, so the rotor speeds up and slows
down with the weather instead of being frozen at whatever it was the day the
banner was set up.

Only the spin rate moves on a refresh: the rotor is redrawn with --keep-caption,
so wording stays exactly as written. If the wind has not moved across a quarter
km/h step, the file is not rewritten, and git therefore records no commit — calm
days leave no trace.

Coordinates come from the SCENE_* environment variables the scene workflow
already sets, falling back to whatever .github/workflows/scene.yml declares, so
there is still exactly one place to edit them.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "scene.yml"
BANNER = ROOT / "header.svg"
FOOTER = ROOT / "garden-footer.svg"
FOOTER_NIGHT = ROOT / "garden-footer-night.svg"

# quarter km/h: finer than this and the blades would twitch for nothing
STEP = 0.25

# living-scene repaints the footers on every run and then writes its own night
# variant from the day file. Its windmill-free output means our injected windmill
# would survive only in the day footer, so derive the night one here with the same
# palette it uses. Copied from living-scene's NIGHT_MAP, narrowed to the colours
# the windmill actually paints.
WINDMILL_NIGHT = {
    "#F4795B": "#FF9075",   # petal
    "#E2542F": "#F4694A",   # petal tip / door
    "#FFD9A0": "#FFE9C9",   # hub
    "#8B949E": "#8B949E",   # tower grey is already night-safe
}


def from_workflow(key: str, fallback: str) -> str:
    try:
        text = WORKFLOW.read_text(encoding="utf-8")
    except OSError:
        return fallback
    m = re.search(rf"^\s*{key}:\s*[\"']?([^\"'#\s]+)", text, re.M)
    return m.group(1) if m else fallback


def current_wind(lat: str, lon: str, tz: str) -> float:
    query = urllib.parse.urlencode({
        "latitude": lat, "longitude": lon,
        "current": "wind_speed_10m", "timezone": tz,
    })
    req = urllib.request.Request(f"https://api.open-meteo.com/v1/forecast?{query}",
                                 headers={"User-Agent": "living-scene-windmill"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return float(json.load(r)["current"]["wind_speed_10m"])


def baked_speed() -> float | None:
    """The speed currently baked into the windmill's SMIL base layer.

    Plain string slicing rather than a regex: `class="wm-base"; ... dur="18.46s"`
    is a fixed shape, and the regex version of this silently failed to match.
    """
    periods: list[float] = []
    for path in (BANNER, FOOTER):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        at = text.find('class="wm-base"')
        if at < 0:
            continue
        dur = text.find('dur="', at)
        end = text.find("s\"", dur)
        if dur < 0 or end < 0:
            continue
        try:
            periods.append(float(text[dur + 5:end]) / 2.0)   # base dur == 2 x period
        except ValueError:
            continue
    if not periods:
        return None
    return 60.0 / min(periods) - 1.0


def write_footer_night() -> None:
    """Derive garden-footer-night.svg from the day footer, windmill included."""
    if not FOOTER.exists():
        return
    day = FOOTER.read_text(encoding="utf-8")
    night = re.sub(r"#[0-9A-Fa-f]{6}",
                   lambda m: WINDMILL_NIGHT.get(m.group(0).upper(), m.group(0)), day)
    FOOTER_NIGHT.write_text(night, encoding="utf-8")
    print(f"  {FOOTER_NIGHT.name}: derived from {FOOTER.name} ({len(night)} bytes)")


def main() -> int:
    lat = os.environ.get("SCENE_LAT") or from_workflow("lat", "30.5928")
    lon = os.environ.get("SCENE_LON") or from_workflow("lon", "114.3055")
    tz = os.environ.get("SCENE_TZ") or from_workflow("tz", "Asia/Shanghai")
    force = os.environ.get("FORCE", "").lower() == "true"

    try:
        wind = current_wind(lat, lon, tz)
    except Exception as exc:                                  # noqa: BLE001
        # a flaky forecast API must not fail the run or remove the windmill
        print(f"wind lookup failed ({type(exc).__name__}: {exc}) — keeping the current spin")
        return 0

    shade = round(wind / STEP) * STEP
    was = baked_speed()
    print(f"wind now {wind:.1f} km/h -> quantised {shade:.2f} km/h"
          + (f" (baked at {was:.2f})" if was is not None else " (no windmill yet)"))

    # Always re-inject, never skip. living-scene redraws BOTH garden footers from
    # scratch on every run, which throws the footer windmill away, so the injection
    # has to be replayed even when the wind has not moved. It is byte-deterministic
    # for fixed arguments, so replaying it changes nothing and git stays quiet.
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "windmill.py"),
         "--wind", f"{shade:.2f}", "--all"],
        capture_output=True, text=True, cwd=ROOT,
    )
    sys.stdout.write(proc.stdout)
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr)
        return proc.returncode

    if was is not None and abs(was - shade) < STEP / 2 and not force:
        print("wind steady — spin already correct")
    else:
        print(f"windmill refreshed to {shade:.2f} km/h -> "
              f"{60.0 / (1.0 + shade):.2f}s per turn")

    # Unconditionally: the night footer must always be a faithful transform of the
    # day footer that was just written. Skipping this when the wind was steady left
    # a night footer from two runs ago, which is how the windmill went missing from
    # night mode. Re-deriving is byte-identical when nothing changed.
    write_footer_night()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
