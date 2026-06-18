"""Terracer — Shiny for Python app: are Helsinki (Kallio) bar terraces in sun?

Run via:  shiny run src/app/app.py   (pixi run app)

All pure data logic lives in `data.py` (importable, unit-tested). This module is
the Shiny shell only: UI, reactives, renderers. It defines a module-level
`app = App(app_ui, server)` as the pixi task expects.
"""

from __future__ import annotations

import html as _html
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import matplotlib

matplotlib.use("Agg")  # headless backend — must precede pyplot import.
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from shiny import App, reactive, render, ui  # noqa: E402

# Import the pure data layer robustly whether launched as a script or a module.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import data as D  # noqa: E402


# ---------------------------------------------------------------------------
# Load-once module-level data
# ---------------------------------------------------------------------------
TERRACES = D.load_terraces()
SHADOWS = D.load_shadows()
BUILDINGS = D.load_buildings_clipped()
PERMITS = D.load_permit_polygons()
TERRACE_POINTS = D.load_terrace_points()
POINT_SHADOWS = D.load_point_shadows()
DEFAULT_DATE = D.default_date()
PERMIT_IDS = set(PERMITS["terrace_id"]) if "terrace_id" in PERMITS.columns else set()

WEEKDAY_FMT = "%a %-d %b"   # e.g. "Mon 17 Jun"
_HKI = ZoneInfo("Europe/Helsinki")


def _fmt_date(d: date) -> str:
    return d.strftime(WEEKDAY_FMT)


def _now_slider_value() -> datetime:
    """Current Helsinki time snapped to 30-min grid, clamped 08:00-23:00, on the slider reference day."""
    now = datetime.now(_HKI)
    m = round(now.minute / 30) * 30
    h = now.hour + (1 if m == 60 else 0)
    m = 0 if m == 60 else m
    h = max(8, min(23, h))
    return datetime(2026, 1, 1, h, m, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Theme & CSS
# ---------------------------------------------------------------------------
sun_theme = ui.Theme(preset="shiny")

CUSTOM_CSS = """
:root {
  --t-bg: #FFFDF7; --t-surface: #FFFFFF; --t-border: #F0E6D2;
  --t-accent: #FB8500; --t-amber: #FFB703; --t-gold: #FFD166;
  --t-ink: #2B2118; --t-muted: #8A7E6E; --t-shade: #5B6470;
}
[data-bs-theme="dark"] {
  --t-bg: #16130E; --t-surface: #211C15; --t-border: #2E2820;
  --t-ink: #F4ECDD; --t-muted: #9A8F7C; --t-shade: #515A6B;
}
body {
  background-color: var(--t-bg);
  background-image: radial-gradient(120% 80% at 50% -10%, #FFF3D6 0%, transparent 60%);
  font-family: Inter, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  font-size: 16px; color: var(--t-ink);
}
[data-bs-theme="dark"] body {
  background-image: radial-gradient(120% 80% at 50% -10%, #2A2113 0%, transparent 60%);
}
h1,h2,h3,h4,h5,h6 { font-weight: 650; }
.navbar { background: linear-gradient(90deg,#FB8500,#FFB703) !important; }
.navbar .navbar-brand, .navbar .nav-link, .navbar .brand { color: #fff !important; }
.navbar .nav-link.active { color: #fff !important; font-weight: 700; }
.brand { font-weight: 750; letter-spacing: .2px; }
.card {
  background-color: var(--t-surface);
  border: 1px solid var(--t-border);
  border-radius: 0.75rem;
  box-shadow: 0 2px 10px rgba(120,80,0,.08);
}
.value-box .value-box-value, .value-box-value {
  font-variant-numeric: tabular-nums; font-size: 1.9rem; font-weight: 700;
}
.btn-when {
  border-radius: 999px; font-weight: 650;
  background: rgba(255,255,255,.18); color: #fff !important;
  border: 1px solid rgba(255,255,255,.5);
}
.btn-when:hover { background: rgba(255,255,255,.32); color:#fff; }
.when-summary {
  display:inline-block; padding:.25rem .7rem; cursor:default;
  font-variant-numeric: tabular-nums;
}
.sun-pill {
  display:inline-block; border-radius:999px; padding:.25rem .7rem;
  font-weight:700; font-variant-numeric: tabular-nums; color:#3a2f00;
  background:#FFD166; border:1px solid rgba(0,0,0,.06);
}
.snap-chip {
  background:#FFF6DE; color:#8A5A00; border-radius:8px;
  padding:.1rem .5rem; font-size:.82rem; font-weight:600;
}
.help-cap { color:var(--t-muted); font-size:.82rem; margin-top:.25rem; }
.when-toolbar {
  position: sticky; top: .5rem; z-index: 1020;
  border-color: var(--t-gold) !important;
  box-shadow: 0 4px 18px rgba(251,133,0,.14) !important;
}
.when-toolbar .card-body { padding-top: .6rem; padding-bottom: .6rem; }
.irs-bar, .irs-bar-edge { background:#FFB703 !important; border-color:#FFB703 !important; }
.irs-single, .irs-from, .irs-to { background:#FB8500 !important; }
.irs-handle>i:first-child { background:#FB8500 !important; }
.status-chip {
  display:inline-block; border-radius:999px; padding:.15rem .6rem;
  font-weight:650; font-size:.85rem; margin-left:.4rem;
}
.chip-sun { background:#FFF6DE; color:#8A5A00; }
.chip-shade { background:#ECEEF2; color:#5B6470; }
[data-bs-theme="dark"] .chip-shade { background:#2A2A30; color:#AEB6C2; }
.chip-open { background:#E7F6EC; color:#1a7f37; }
.chip-closed { background:#FBEAEA; color:#b42318; }
[data-bs-theme="dark"] .chip-open { background:#16301f; color:#5fd38a; }
[data-bs-theme="dark"] .chip-closed { background:#3a1f1f; color:#f1a9a0; }
.hours-line { color:var(--t-muted); font-size:.9rem; margin-top:.5rem; }
.hours-line .open { color:#1a7f37; font-weight:700; }
.hours-line .closed { color:#b42318; font-weight:700; }
.chip-type {
  display:inline-block; border-radius:6px; padding:.05rem .45rem;
  font-size:.72rem; font-weight:650; background:var(--t-border); color:var(--t-muted);
  margin-left:.4rem; text-transform:uppercase; letter-spacing:.5px;
}
.btn-warning, .maps-link {
  background:#FB8500 !important; border-color:#FB8500 !important; color:#fff !important;
  font-weight:650;
}
.detail-meta { color:var(--t-muted); font-size:.9rem; margin-top:.5rem; }
.permit-note { color:var(--t-muted); font-size:.82rem; margin-top:.3rem; }
.frac-bar-wrap { height:4px; background:rgba(0,0,0,.08); border-radius:3px; margin-top:.3rem; }
.frac-bar { height:4px; border-radius:3px; background:linear-gradient(90deg,#E9B949,#FB8500); }
.legend-grad {
  height:14px; border-radius:7px; width:100%;
  background:linear-gradient(90deg,#5B6470,#8A7E63,#E9B949,#FFB703,#FB8500);
}
.legend-labels { display:flex; justify-content:space-between; color:var(--t-muted); font-size:.8rem; }

/* ---- Mobile (phones, < 576px) ---- */
@media (max-width: 575.98px) {
  body { font-size: 15px; }
  .bslib-page-navbar > .navbar { padding-top:.3rem; padding-bottom:.3rem; }
  .navbar .brand { font-size: 1rem; }
  /* A tall date+slider toolbar shouldn't pin to the top and eat the screen. */
  .when-toolbar { position: static !important; }
  .when-toolbar .card-body { padding:.55rem .7rem; }
  .value-box .value-box-value, .value-box-value { font-size: 1.4rem; }
  .value-box .value-box-showcase { padding:.4rem !important; }
  .value-box .value-box-showcase i { font-size: 1.3rem; }
  .card-header { font-size: .95rem; }
  .help-cap { font-size:.78rem; }
  /* Stack the rank-card hint under the title instead of floating it. */
  .card-header .help-cap[style*="float"] { float:none !important; display:block; margin-top:.15rem; }
  .snap-chip { display:inline-block; margin-top:.2rem; }
}
/* Maps: comfortable touch height on small screens. */
@media (max-width: 767.98px) {
  .when-toolbar .row > [class*="col"] { margin-bottom:.2rem; }
}
/* Full-screen cards: make the content (iframe or data grid) fill the available height. */
.bslib-card[data-full-screen="true"] > .card-body {
  display: flex !important;
  flex-direction: column !important;
  overflow: hidden !important;
}
.bslib-card[data-full-screen="true"] > .card-body > .shiny-html-output {
  flex: 1 !important;
  min-height: 0 !important;
  display: flex !important;
  flex-direction: column !important;
}
.bslib-card[data-full-screen="true"] .map-iframe-wrap {
  flex: 1 !important;
  height: auto !important;
  min-height: 0 !important;
}
"""


# ---------------------------------------------------------------------------
# Time controls — a sticky toolbar in the page BODY (always visible, never
# collapses behind the mobile hamburger). The navbar keeps a read-only summary.
# ---------------------------------------------------------------------------
when_toolbar = ui.card(
    ui.layout_columns(
        ui.div(
            ui.input_date(
                "date",
                "Date",
                value=DEFAULT_DATE,
                min=date(2026, 1, 1),
                max=date(2026, 12, 31),
                format="M d",
                startview="month",
                weekstart=1,  # weeks start on Monday
                width="100%",
            ),
            ui.div(
                "Sun pattern sampled biweekly across 2026.",
                class_="help-cap",
            ),
        ),
        ui.div(
            ui.input_slider(
                "time",
                "Time of day",
                # UTC-aware + timezone "+0000" so the slider shows the literal
                # wall-clock time (08:00–23:00) and reads it back unshifted.
                min=datetime(2026, 1, 1, 8, 0, tzinfo=timezone.utc),
                max=datetime(2026, 1, 1, 23, 0, tzinfo=timezone.utc),
                value=_now_slider_value(),
                step=1800,  # 30-minute steps, in seconds → half-hourly
                time_format="%H:%M",
                timezone="+0000",
                ticks=False,
                width="100%",
            ),
        ),
        col_widths={"sm": (12, 12), "md": (4, 8)},
    ),
    class_="when-toolbar",
)


# ---------------------------------------------------------------------------
# Tab 1 — Dashboard
# ---------------------------------------------------------------------------
rank_card = ui.card(
    ui.card_header(
        ui.HTML('<i class="bi bi-trophy"></i> Open &amp; sunny — '),
        ui.output_text("rank_when", inline=True),
        ui.span(
            ui.HTML('<i class="bi bi-hand-index"></i> Click a row to inspect a terrace'),
            class_="help-cap",
            style="float:right;font-weight:400;",
        ),
    ),
    ui.output_data_frame("rank_grid"),
    full_screen=True,
    height="560px",
)

detail_card = ui.card(
    ui.card_header(ui.output_ui("detail_title")),
    ui.output_ui("detail_panel"),
    full_screen=True,
)

dashboard_map_card = ui.card(
    ui.card_header(
        "Map — colored by % in sun  ",
        ui.span(ui.output_text("map_snap_chip", inline=True), class_="snap-chip"),
    ),
    ui.output_ui("map"),
    full_screen=True,
    height="440px",
)

nav_dashboard = ui.nav_panel(
    "Dashboard",
    ui.layout_columns(
        rank_card, detail_card, col_widths={"sm": (12, 12), "lg": (7, 5)}
    ),
    dashboard_map_card,
)


# ---------------------------------------------------------------------------
# Tab 2 — Map
# ---------------------------------------------------------------------------
nav_map = ui.nav_panel(
    "Map",
    ui.card(
        ui.card_header("Kallio terraces"),
        ui.output_ui("map_big"),
        full_screen=True,
        height="78vh",
    ),
    ui.card(
        ui.card_header("Legend — % of terrace in sun"),
        ui.output_ui("map_legend"),
    ),
)


# ---------------------------------------------------------------------------
# Page shell
# ---------------------------------------------------------------------------
app_ui = ui.page_navbar(
    nav_dashboard,
    nav_map,
    ui.nav_spacer(),
    ui.nav_control(
        ui.span(
            ui.HTML('<i class="bi bi-clock"></i> '),
            ui.output_text("when_label", inline=True),
            class_="btn-when when-summary",
        )
    ),
    ui.nav_control(ui.output_ui("sun_badge")),
    ui.nav_control(ui.input_dark_mode(id="mode")),
    title=ui.span(ui.HTML("&#9728;&#65039;"), " Terracer", class_="brand"),
    id="nav",
    fillable=True,
    theme=sun_theme,
    header=ui.TagList(
        ui.head_content(
            ui.tags.link(
                rel="stylesheet",
                href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.min.css",
            ),
            ui.tags.style(CUSTOM_CSS),
            ui.busy_indicators.use(spinners=True, pulse=True),
        ),
        when_toolbar,
    ),
)


# ---------------------------------------------------------------------------
# Grid rendering helpers
# ---------------------------------------------------------------------------
def _unicode_bar(frac: float) -> str:
    n = int(round(max(0.0, min(1.0, frac)) * 8))
    return "█" * n + "░" * (8 - n)


def _grid_df(ranked):
    return ranked.assign(
        **{
            "Terrace": ranked["name"],
            "Type": ranked["amenity"],
            "Open-sun left": ranked["osl_slots"].apply(lambda s: D.fmt_duration(int(s))),
            "% now": ranked["sun_fraction"].apply(
                lambda f: f"{f:.0%}  {_unicode_bar(f)}"
            ),
            "Open": ranked["open_now"].apply(lambda o: "open" if bool(o) else "closed"),
        }
    )[["Terrace", "Type", "Open-sun left", "% now", "Open"]]


def _embed_iframe(deck_html: str, height: str) -> ui.HTML:
    escaped = _html.escape(deck_html)
    return ui.HTML(
        f'<div class="map-iframe-wrap" style="height:{height};border-radius:.5rem;overflow:hidden;">'
        f'<iframe srcdoc="{escaped}" style="width:100%;height:100%;border:none;display:block;"></iframe>'
        f'</div>'
    )


# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------
def server(input, output, session):
    selected_id = reactive.value(None)

    @reactive.effect
    def _default_to_open_date():
        ui.update_date("date", value=D._today_ref())
        ui.update_slider("time", value=_now_slider_value())

    @reactive.calc
    def is_dark() -> bool:
        return input.mode() == "dark"

    @reactive.calc
    def snapped():
        """(snapped_date, selected_minutes, datetime, was_snapped, requested_date)."""
        req_date = input.date()
        if not isinstance(req_date, date):
            req_date = DEFAULT_DATE
        snap_d, was = D.snap_date(req_date)
        t = input.time()  # a datetime on the slider's reference day
        minutes = t.hour * 60 + t.minute
        # Snap to the nearest half-hour slot and clamp into the sampled window.
        minutes = int(round(minutes / D.SLOT_STEP_MIN) * D.SLOT_STEP_MIN)
        minutes = max(D.SLOT_START_MIN, min(D.SLOT_END_MIN, minutes))
        dt = D.make_datetime(snap_d, minutes)
        return snap_d, minutes, dt, was, req_date

    @reactive.calc
    def snapshot_df():
        _, _, dt, _, _ = snapped()
        return D.snapshot_for(SHADOWS, TERRACES, dt)

    @reactive.calc
    def ranked():
        snap_d, minutes, _, _, req_date = snapped()
        return D.ranked_for(SHADOWS, TERRACES, snap_d, minutes, req_date=req_date)

    # --- Resolve grid selection -> stable terrace_id ---
    @reactive.effect
    def _resolve_selection():
        r = ranked()
        ids = r["terrace_id"].tolist()
        sel = input.rank_grid_cell_selection()
        chosen = None
        if sel and sel.get("type") == "row":
            rows = list(sel.get("rows", []))
            if rows:
                idx = rows[0]
                if 0 <= idx < len(ids):
                    chosen = ids[idx]
        if chosen is None:
            # Keep prior selection if still present, else fall back to rank-1.
            prior = selected_id()
            chosen = prior if prior in ids else (ids[0] if ids else None)
        if chosen != selected_id():
            selected_id.set(chosen)

    @reactive.calc
    def detail_ctx():
        sid = selected_id()
        r = ranked()
        if sid is None or sid not in set(r["terrace_id"]):
            sid = r["terrace_id"].iloc[0] if len(r) else None
        snap_d, minutes, dt, _, _ = snapped()
        row = r[r["terrace_id"] == sid]
        rec = row.iloc[0].to_dict() if len(row) else None
        prof = D.day_profile(SHADOWS, sid, snap_d) if sid else None
        return {"id": sid, "rec": rec, "profile": prof, "dt": dt, "minutes": minutes}

    # ---------------- Navbar live labels ----------------
    @render.text
    def when_label():
        _, minutes, _, _, req = snapped()
        return f"{req.strftime('%-d %b')} · {D.fmt_minutes(minutes)}"

    @render.ui
    def sun_badge():
        df = snapshot_df()
        n = int(df["in_sun"].sum())
        return ui.span(f"☀ {n} / {len(df)} in sun", class_="sun-pill")

    @render.text
    def map_snap_chip():
        _, minutes, dt, was, _ = snapped()
        if was:
            return f"Sun from nearest sample: {_fmt_date(dt.date())}"
        return ""

    @render.text
    def rank_when():
        _, minutes, _, _, req = snapped()
        return f"{_fmt_date(req)}, {D.fmt_minutes(minutes)}"

    # ---------------- Ranked grid ----------------
    @render.data_frame
    def rank_grid():
        r = ranked()
        df = _grid_df(r)
        fracs = r["sun_fraction"].tolist()
        opens = r["open_now"].tolist()
        dark = is_dark()

        def style_fn(_data):
            infos = []
            for i, (f, is_open) in enumerate(zip(fracs, opens)):
                infos.append(
                    {
                        "location": "body",
                        "rows": [i],
                        "cols": ["% now"],
                        "style": {
                            "background-color": D.hex_color(f, dark=dark),
                            "color": D.readable_fg(f, dark=dark),
                            "font-variant-numeric": "tabular-nums",
                            "font-weight": "600",
                        },
                    }
                )
                infos.append(
                    {
                        "location": "body",
                        "rows": [i],
                        "cols": ["Open"],
                        "style": {
                            "color": "#1a7f37" if is_open else "#b42318",
                            "font-weight": "600",
                        },
                    }
                )
            return infos

        return render.DataGrid(
            df,
            selection_mode="row",
            height=None,
            width="100%",
            styles=style_fn,
        )

    # ---------------- Detail panel ----------------
    @render.ui
    def detail_title():
        ctx = detail_ctx()
        rec = ctx["rec"]
        if rec is None:
            return ui.span("Select a terrace")
        frac = float(rec["sun_fraction"])
        if frac > 0:
            chip = (
                f'<span class="status-chip chip-sun">'
                f'<i class="bi bi-sun-fill"></i> {int(round(frac*100))}% in sun</span>'
            )
        else:
            chip = (
                '<span class="status-chip chip-shade">'
                '<i class="bi bi-cloud"></i> In shade</span>'
            )
        if bool(rec.get("open_now", True)):
            open_chip = (
                '<span class="status-chip chip-open">'
                '<i class="bi bi-door-open"></i> Open now</span>'
            )
        else:
            open_chip = (
                '<span class="status-chip chip-closed">'
                '<i class="bi bi-door-closed"></i> Closed now</span>'
            )
        return ui.HTML(
            f"{_html.escape(str(rec['name']))}"
            f'<span class="chip-type">{_html.escape(str(rec["amenity"]))}</span>'
            f"{chip}{open_chip}"
        )

    @render.ui
    def detail_panel():
        ctx = detail_ctx()
        rec = ctx["rec"]
        prof = ctx["profile"]
        if rec is None:
            return ui.p("No terrace selected.")

        frac = float(rec["sun_fraction"])
        bh_hour, bh_frac = D.best_hour(prof)
        osl_slots = int(rec.get("osl_slots", 0) or 0)

        # Opening-hours: live open/closed + today's hours, then the full week.
        open_now = bool(rec.get("open_now", False))
        today_hours = _html.escape(str(rec.get("today_hours") or "—"))
        hours_text = _html.escape(str(rec.get("hours_text") or ""))
        status = (
            '<span class="open">● Open now</span>'
            if open_now
            else '<span class="closed">● Closed now</span>'
        )
        meta = [
            ui.HTML(
                f'<div class="hours-line"><i class="bi bi-clock"></i> '
                f"{status} · Today {today_hours}</div>"
            )
        ]
        if hours_text:
            meta.append(
                ui.HTML(
                    f'<div class="detail-meta"><i class="bi bi-calendar-week"></i> '
                    f"{hours_text}</div>"
                )
            )
        if osl_slots > 0:
            meta.append(
                ui.HTML(
                    f'<div class="detail-meta"><i class="bi bi-hourglass-split"></i> '
                    f"<b>{D.fmt_duration(osl_slots)}</b> open &amp; sunny left today</div>"
                )
            )
        if bh_hour is not None:
            meta.append(
                ui.HTML(
                    f'<div class="detail-meta"><i class="bi bi-brightness-high"></i> '
                    f"Sunniest at {D.fmt_minutes(bh_hour)} "
                    f"({int(round(bh_frac*100))}% lit)</div>"
                )
            )
        meta.append(
            ui.HTML(
                f'<div class="detail-meta"><i class="bi bi-geo-alt"></i> '
                f"{_html.escape(str(rec.get('address') or ''))}</div>"
            )
        )
        maps_url = rec.get("maps_url")
        if maps_url:
            meta.append(
                ui.tags.a(
                    ui.HTML('<i class="bi bi-geo-alt-fill"></i> Open in Google Maps'),
                    href=str(maps_url),
                    target="_blank",
                    class_="btn btn-warning w-100 maps-link",
                    style="margin-top:.5rem;",
                )
            )
        if str(rec["terrace_id"]) in PERMIT_IDS:
            meta.append(
                ui.HTML(
                    '<div class="permit-note"><i class="bi bi-patch-check"></i> '
                    "Permit terrace area mapped</div>"
                )
            )

        return ui.TagList(
            ui.div(
                ui.HTML(
                    '<i class="bi bi-sun"></i> <b>Sun on the terrace now</b> — '
                    "top-down, north up; orange = sun, grey = shade"
                ),
                class_="help-cap",
                style="margin-top:.6rem;",
            ),
            ui.div(ui.output_plot("sun_map", height="190px")),
            ui.div(ui.output_plot("day_timeline", height="100px"), style="margin-top:.5rem;"),
            ui.div("Sun across the day · ▾ marks the selected time", class_="help-cap"),
            *meta,
        )

    # ---------------- Terrace sun-map (which parts are lit) ----------------
    @render.plot
    def sun_map():
        ctx = detail_ctx()
        sid = ctx["id"]
        dt = ctx["dt"]
        dark = is_dark()
        muted = "#9A8F7C" if dark else "#8A7E6E"
        sun_rgb = (0.98, 0.52, 0.0)
        shade_rgb = (0.34, 0.38, 0.45) if dark else (0.55, 0.58, 0.63)
        shade_pt = "#8A93A0" if dark else "#6B7280"

        fig, ax = plt.subplots(figsize=(4.6, 2.7))
        fig.patch.set_alpha(0.0)
        ax.patch.set_alpha(0.0)
        ax.set_aspect("equal")
        ax.axis("off")

        pts = D.sun_map_points(POINT_SHADOWS, TERRACE_POINTS, sid, dt) if sid else None
        if pts is None or len(pts) < 1:
            ax.text(
                0.5, 0.5, "Terrace layout not mapped", ha="center", va="center",
                transform=ax.transAxes, color=muted, fontsize=9,
            )
            plt.close(fig)
            return fig

        # Local metre frame relative to the terrace centroid (north up).
        lat0 = float(pts["lat"].mean())
        lon0 = float(pts["lon"].mean())
        mx = (pts["lon"].to_numpy() - lon0) * 111320.0 * np.cos(np.radians(lat0))
        my = (pts["lat"].to_numpy() - lat0) * 110540.0
        sun = pts["in_sun"].to_numpy().astype(bool)

        pad = 2.2
        xmin, xmax = mx.min() - pad, mx.max() + pad
        ymin, ymax = my.min() - pad, my.max() + pad
        if xmax - xmin < 7:
            c = (xmin + xmax) / 2; xmin, xmax = c - 3.5, c + 3.5
        if ymax - ymin < 7:
            c = (ymin + ymax) / 2; ymin, ymax = c - 3.5, c + 3.5

        # Nearest-point fill within a radius → an organic lit/shaded terrace shape.
        res = 96
        gx = np.linspace(xmin, xmax, res)
        gy = np.linspace(ymin, ymax, res)
        gxx, gyy = np.meshgrid(gx, gy)
        d2 = (gxx[..., None] - mx) ** 2 + (gyy[..., None] - my) ** 2
        nn = d2.argmin(axis=2)
        nnd = np.sqrt(d2.min(axis=2))
        sun_grid = sun[nn]
        within = nnd <= 2.0
        img = np.zeros((res, res, 4))
        img[within & sun_grid] = (*sun_rgb, 0.88)
        img[within & ~sun_grid] = (*shade_rgb, 0.88)
        ax.imshow(
            img, extent=[xmin, xmax, ymin, ymax], origin="lower",
            interpolation="nearest", zorder=1,
        )
        ax.scatter(mx[sun], my[sun], c="#FB8500", s=15, edgecolors="white",
                   linewidths=0.5, zorder=3)
        ax.scatter(mx[~sun], my[~sun], c=shade_pt, s=15, edgecolors="white",
                   linewidths=0.5, zorder=3)

        # Sun-direction arrow (corner): where the light comes from.
        az, alt = D.sun_az_alt(dt)
        if alt > 0:
            ux, uy = np.sin(np.radians(az)), np.cos(np.radians(az))
            bx, by, L = 0.9, 0.84, 0.15
            ax.annotate(
                "", xy=(bx + ux * L, by + uy * L), xytext=(bx - ux * L * 0.3, by - uy * L * 0.3),
                xycoords="axes fraction",
                arrowprops=dict(arrowstyle="-|>", color="#FB8500", lw=2),
            )
            ax.scatter([bx + ux * L], [by + uy * L], transform=ax.transAxes, c="#FFB703",
                       s=70, edgecolors="#FB8500", linewidths=1, zorder=5, clip_on=False)
            ax.text(bx, 1.0, f"sun {D.compass_dir(az)}", transform=ax.transAxes,
                    ha="center", va="bottom", color=muted, fontsize=7.5)

        ax.set_xlim(xmin, xmax)
        ax.set_ylim(ymin, ymax)
        fig.tight_layout(pad=0.2)
        plt.close(fig)
        return fig

    # ---------------- Day timeline ----------------
    @render.plot
    def day_timeline():
        ctx = detail_ctx()
        prof = ctx["profile"]
        dark = is_dark()
        cur_minutes = int(ctx["minutes"])

        fig, ax = plt.subplots(figsize=(6, 1.0))
        fig.patch.set_alpha(0.0)
        ax.patch.set_alpha(0.0)
        tick_color = "#F4ECDD" if dark else "#2B2118"

        if prof is None or prof.empty:
            ax.axis("off")
            plt.close(fig)
            return fig

        minutes = prof["minutes"].tolist()
        n = len(minutes)
        for i, (_, row) in enumerate(prof.iterrows()):
            f = float(row["sun_fraction"])
            # No per-bar white edge at half-hour density; whole-hour ticks below.
            ax.barh(0, width=1.0, left=i, height=0.8, color=D.hex_color(f, dark=dark))
            if int(row["minutes"]) == cur_minutes:
                ax.barh(
                    0, width=1.0, left=i, height=0.8, facecolor="none",
                    edgecolor=("#FFD166" if dark else "#2B2118"), linewidth=2.4,
                )
                ax.annotate(
                    "▾", (i + 0.5, 0.46), ha="center", va="bottom",
                    color=tick_color, fontsize=11,
                )

        # Tick only on whole hours (every other half-hour slot).
        hour_pos = [i for i, m in enumerate(minutes) if m % 60 == 0]
        ax.set_xlim(0, n)
        ax.set_ylim(-0.5, 0.6)
        ax.set_yticks([])
        ax.set_xticks([i + 0.5 for i in hour_pos])
        ax.set_xticklabels(
            [str(minutes[i] // 60) for i in hour_pos], color=tick_color, fontsize=8
        )
        ax.tick_params(length=0)
        for spine in ax.spines.values():
            spine.set_visible(False)
        fig.tight_layout()
        plt.close(fig)
        return fig

    # ---------------- Maps ----------------
    @reactive.calc
    def deck_html_dash():
        _, _, dt, _, _ = snapped()
        df = D.snapshot_for(SHADOWS, TERRACES, dt)
        return D.build_deck_html(
            df, selected_id(), BUILDINGS, PERMITS, is_dark(), dt=dt, zoom=13.7
        )

    @reactive.calc
    def deck_html_big():
        _, _, dt, _, _ = snapped()
        df = D.snapshot_for(SHADOWS, TERRACES, dt)
        return D.build_deck_html(
            df, selected_id(), BUILDINGS, PERMITS, is_dark(), dt=dt, zoom=14.2
        )

    @render.ui
    def map():
        return _embed_iframe(deck_html_dash(), "400px")

    @render.ui
    def map_big():
        return _embed_iframe(deck_html_big(), "72vh")

    @render.ui
    def map_legend():
        _, _, dt, _, _ = snapped()
        az, alt = D.sun_az_alt(dt)
        if alt > 0:
            sun_txt = (
                f'<i class="bi bi-sun-fill"></i> Sun is to the '
                f"<b>{D.compass_dir(az)}</b> ({round(az)}°), "
                f"<b>{round(alt)}°</b> above the horizon"
            )
        else:
            sun_txt = (
                '<i class="bi bi-moon-stars"></i> Sun is '
                f"<b>below the horizon</b> ({round(alt)}°) — terraces are in shade"
            )
        return ui.TagList(
            ui.div(class_="legend-grad"),
            ui.div(
                ui.span("Shade (0%)"),
                ui.span("Full sun (100%)"),
                class_="legend-labels",
            ),
            ui.div(
                ui.HTML(sun_txt),
                class_="detail-meta",
                style="margin-top:.6rem;",
            ),
            ui.div(
                ui.HTML(
                    '<span style="display:inline-block;width:22px;border-top:2px solid '
                    '#2856aa;vertical-align:middle;margin-right:6px"></span>'
                    "Blue outline = edge of the 3D building data"
                ),
                class_="detail-meta",
                style="margin-top:.3rem;",
            ),
        )


app = App(app_ui, server)
