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

# quarter km/h: finer than this and the blades would twitch for nothing
STEP = 0.25


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
    """The speed currently baked into the banner's <animateTransform> durations."""
    try:
        text = BANNER.read_text(encoding="utf-8")
    except OSError:
        return None
    durs = [float(d) for d in re.findall(r'class="wm-css0"[^>]*dur="([\d.]+)s"', text)]
    durs += [float(d) for d in re.findall(r'class="wm-smil0"[^>]*dur="([\d.]+)s"', text)]
    if not durs:
        return None
    # rate = sum(1/dur); the ratio between the two layers is fixed at 1:2, so the
    # wind speed is recoverable from the shared period
    period = 1.0 / sum(1.0 / d for d in durs)
    return 60.0 / period - 1.0


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
          + (f" (banner is at {was:.2f})" if was is not None else " (no windmill found)"))

    if was is not None and abs(was - shade) < STEP / 2 and not force:
        print("within one step of the baked value — leaving the banner untouched")
        return 0

    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "windmill.py"),
         "--wind", f"{shade:.2f}", "--keep-caption", "--spin"],
        capture_output=True, text=True, cwd=ROOT,
    )
    sys.stdout.write(proc.stdout)
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr)
        return proc.returncode
    print(f"windmill refreshed to {shade:.2f} km/h -> "
          f"{60.0 / (1.0 + shade):.2f}s per turn")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
