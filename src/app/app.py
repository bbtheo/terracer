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

from shiny import App, ui

# Import the pure data layer robustly whether launched as a script or a module.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import data as D  # noqa: E402

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
        ui.tags.link(rel="preconnect", href="https://fonts.gstatic.com", crossorigin=""),
        ui.tags.link(rel="stylesheet", href=FONT_URL),
        ui.tags.link(rel="stylesheet", href=_asset("terracer.css")),
    ),
    ui.div(id="app"),
    ui.tags.script(ui.HTML(D.payload_json()), id="terracer-data", type="application/json"),
    ui.tags.script(src=_asset("terracer.js")),
)

app = App(app_ui, None, static_assets=WWW)
