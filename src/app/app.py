"""Terracer — Shiny for Python app: are Helsinki (Kallio) bar terraces in sun?

Run via:  shiny run src/app/app.py   (pixi run app)

Shiny hosts one client-side page. `data.py` bundles the data into it once, and
`www/terracer.js` does all drawing and interaction, so scrubbing never waits
for the server. This module defines the module-level `app` the pixi task expects.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import asyncio
import time

from shiny import App, reactive, ui

# Import the pure data layer robustly whether launched as a script or a module.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import data as D  # noqa: E402
import sunshine  # noqa: E402

WWW = Path(__file__).resolve().parent / "www"
FONT_URL = "https://fonts.googleapis.com/css2?family=Nunito:wght@600;700;800&display=swap"


def _asset(name: str) -> str:
    """URL for a static file, versioned so a redeploy is never served stale."""
    digest = hashlib.md5((WWW / name).read_bytes()).hexdigest()[:8]
    return f"{name}?v={digest}"


app_ui = ui.TagList(
    ui.head_content(
        ui.tags.title("Terracer"),
        ui.tags.meta(name="viewport", content="width=device-width, initial-scale=1, viewport-fit=cover"),
        # Otherwise iOS Safari turns the row of hour labels into a phone-number link.
        ui.tags.meta(name="format-detection", content="telephone=no"),
        ui.tags.link(rel="preconnect", href="https://fonts.gstatic.com", crossorigin=""),
        ui.tags.link(rel="stylesheet", href=FONT_URL),
        ui.tags.link(rel="stylesheet", href=_asset("terracer.css")),
    ),
    ui.div(id="app"),
    ui.tags.script(ui.HTML(D.payload_json()), id="terracer-data", type="application/json"),
    ui.tags.script(src=_asset("terracer.js")),
)

RECENT_MAX_AGE_S = 3600
_recent: dict[str, str] = {}
_recent_fetched = 0.0
_recent_lock = asyncio.Lock()


async def _recent_sunshine() -> dict[str, str]:
    """Days newer than the bundled history, fetched at most once an hour."""
    global _recent, _recent_fetched
    async with _recent_lock:
        if time.monotonic() - _recent_fetched > RECENT_MAX_AGE_S or not _recent_fetched:
            try:
                _recent = await asyncio.to_thread(sunshine.recent_days, sunshine.read_history())
                _recent_fetched = time.monotonic()
            except Exception as error:  # the page still works from the bundled history
                print(f"Could not fetch recent sunshine: {error}", file=sys.stderr)
    return _recent


def server(input, output, session):
    @reactive.effect
    async def send_recent_sunshine():
        days = await _recent_sunshine()
        if days:
            await session.send_custom_message("terracer-sunshine", days)


app = App(app_ui, server, static_assets=WWW)
