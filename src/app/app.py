"""Terracer — Shiny for Python app: are Helsinki (Kallio) bar terraces in sun?

Run via:  shiny run src/app/app.py   (pixi run app)

All pure data logic lives in `data.py` (importable, unit-tested). This module is
the Shiny shell only: UI, reactives, renderers. It defines a module-level
`app = App(app_ui, server)` as the pixi task expects.
"""

from __future__ import annotations

import html as _html
import sys
from datetime import date
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless backend — must precede pyplot import.
import matplotlib.pyplot as plt  # noqa: E402

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
DEFAULT_DATE = D.default_date()
PERMIT_IDS = set(PERMITS["terrace_id"]) if "terrace_id" in PERMITS.columns else set()

WEEKDAY_FMT = "%a %-d %b"   # e.g. "Mon 17 Jun"
SHORT_FMT = "%-d %b"        # e.g. "17 Jun"


def _fmt_date(d: date) -> str:
    return d.strftime(WEEKDAY_FMT)


def _fmt_short(d: date) -> str:
    return d.strftime(SHORT_FMT)


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
.snap-note {
  background:#FFF6DE; color:#8A5A00; border-left:3px solid #FFC107;
  border-radius:8px; padding:.5rem .7rem; margin-top:.4rem; font-size:.92rem;
}
.snap-note.exact { background:transparent; color:var(--t-muted); border-left:3px solid #cdd3da; }
.snap-chip {
  background:#FFF6DE; color:#8A5A00; border-radius:8px;
  padding:.1rem .5rem; font-size:.82rem; font-weight:600;
}
.hour-ticks {
  display:flex; justify-content:space-between; color:var(--t-muted);
  font-size:.78rem; font-variant-numeric: tabular-nums; margin-top:-.4rem;
  letter-spacing:.5px;
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
                width="100%",
            ),
            ui.div(
                "Sun pattern sampled biweekly across 2026.",
                class_="help-cap",
            ),
        ),
        ui.div(
            ui.input_slider(
                "hour",
                "Time of day",
                min=8,
                max=23,
                value=14,
                step=1,
                ticks=False,
                post=":00",
                width="100%",
            ),
            ui.div(
                "8 · 10 · 12 · 14 · 16 · 18 · 20 · 22", class_="hour-ticks"
            ),
        ),
        col_widths={"sm": (12, 12), "md": (4, 8)},
    ),
    ui.output_ui("snap_note"),
    class_="when-toolbar",
)


# ---------------------------------------------------------------------------
# Tab 1 — Dashboard
# ---------------------------------------------------------------------------
kpi_band = ui.layout_columns(
    ui.value_box(
        "In the sun now",
        ui.output_text("vb_count"),
        showcase=ui.HTML('<i class="bi bi-sun-fill"></i>'),
        theme=ui.value_box_theme(bg="#FFB703", fg="#3a2f00"),
    ),
    ui.value_box(
        "Sunniest spot",
        ui.output_ui("vb_best"),
        showcase=ui.HTML('<i class="bi bi-trophy"></i>'),
        theme=ui.value_box_theme(bg="#FB8500", fg="#ffffff"),
    ),
    ui.value_box(
        "Avg terrace in sun",
        ui.output_text("vb_avg"),
        showcase=ui.HTML('<i class="bi bi-cloud-sun"></i>'),
        theme=ui.value_box_theme(fg="#FB8500"),
    ),
    ui.value_box(
        "Sun left today",
        ui.output_text("vb_left"),
        showcase=ui.HTML('<i class="bi bi-hourglass-split"></i>'),
        theme=ui.value_box_theme(bg="#FFD166", fg="#3a2f00"),
    ),
    col_widths={"sm": (6, 6, 6, 6), "lg": (3, 3, 3, 3)},
)

rank_card = ui.card(
    ui.card_header(
        "Sunniest now — ",
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
    kpi_band,
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


def _sun_glyph(frac: float) -> str:
    if frac >= 0.66:
        return "☀"
    if frac > 0.0:
        return "⛅"
    return "☁"


def _grid_df(ranked):
    return ranked.assign(
        **{
            "#": ranked["Rank"],
            "Terrace": ranked["name"],
            "Type": ranked["amenity"],
            "% in sun": ranked["sun_fraction"].apply(
                lambda f: f"{f:.0%}  {_unicode_bar(f)}"
            ),
            "Sun?": ranked["sun_fraction"].apply(_sun_glyph),
        }
    )[["#", "Terrace", "Type", "% in sun", "Sun?"]]


def _embed_iframe(deck_html: str, height: str) -> ui.HTML:
    escaped = _html.escape(deck_html)
    return ui.HTML(
        f'<iframe srcdoc="{escaped}" '
        f'style="width:100%;height:{height};border:none;border-radius:.5rem;"></iframe>'
    )


# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------
def server(input, output, session):
    selected_id = reactive.value(None)

    @reactive.effect
    def _default_to_open_date():
        # Default the date picker to the day the app is OPENED (today, mapped
        # onto the 2026 data year). Recomputed per session so a long-lived
        # Connect Cloud process never stays pinned to its start date. Runs once
        # at session start (no reactive dependencies).
        ui.update_date("date", value=D._today_ref())

    @reactive.calc
    def is_dark() -> bool:
        return input.mode() == "dark"

    @reactive.calc
    def snapped():
        """(snapped_datetime, was_snapped, requested_date)."""
        req_date = input.date()
        if not isinstance(req_date, date):
            req_date = DEFAULT_DATE
        snap_d, was = D.snap_date(req_date)
        dt = D.make_datetime(snap_d, int(input.hour()))
        return dt, was, req_date

    @reactive.calc
    def snapshot_df():
        dt, _, _ = snapped()
        return D.snapshot_for(SHADOWS, TERRACES, dt)

    @reactive.calc
    def ranked():
        return D.rank(snapshot_df())

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
        dt, _, _ = snapped()
        row = r[r["terrace_id"] == sid]
        rec = row.iloc[0].to_dict() if len(row) else None
        prof = D.day_profile(SHADOWS, sid, dt.date()) if sid else None
        return {"id": sid, "rec": rec, "profile": prof, "dt": dt}

    # ---------------- Navbar live labels ----------------
    @render.text
    def when_label():
        dt, _, _ = snapped()
        return dt.strftime("%-d %b · %H:00")

    @render.ui
    def sun_badge():
        df = snapshot_df()
        n = int(df["in_sun"].sum())
        return ui.span(f"☀ {n} / {len(df)} in sun", class_="sun-pill")

    @render.ui
    def snap_note():
        dt, was, req = snapped()
        if was:
            return ui.HTML(
                f'<div class="snap-note"><i class="bi bi-calendar-event"></i> '
                f"Nearest sample: <b>{_fmt_date(dt.date())}</b> "
                f"(you picked {_fmt_short(req)})</div>"
            )
        return ui.HTML(
            '<div class="snap-note exact"><i class="bi bi-check-circle"></i> '
            "Exact sample date.</div>"
        )

    @render.text
    def map_snap_chip():
        dt, was, _ = snapped()
        if was:
            return f"Showing nearest sample: {_fmt_date(dt.date())} · {dt.strftime('%H:00')}"
        return ""

    @render.text
    def rank_when():
        dt, _, _ = snapped()
        return f"{_fmt_date(dt.date())}, {dt.strftime('%H:00')}"

    # ---------------- KPI value boxes ----------------
    @render.text
    def vb_count():
        df = snapshot_df()
        return f"{int(df['in_sun'].sum())} / {len(df)}"

    @render.ui
    def vb_best():
        r = ranked()
        if not len(r):
            return ui.span("—")
        top = r.iloc[0]
        if top["sun_fraction"] <= 0:
            return ui.span("No sun anywhere")
        return ui.HTML(
            f'<div style="font-size:1.1rem;font-weight:700;line-height:1.1">'
            f"{_html.escape(str(top['name']))}</div>"
            f'<div style="font-size:.9rem;opacity:.9">{int(top["pct"])}% lit</div>'
        )

    @render.text
    def vb_avg():
        df = snapshot_df()
        return f"{df['sun_fraction'].mean() * 100:.0f}%"

    @render.text
    def vb_left():
        ctx = detail_ctx()
        prof = ctx["profile"]
        if prof is None:
            return "—"
        left = D.sun_hours_left(prof, ctx["dt"].hour)
        return f"{left}h" if left > 0 else "None left"

    # ---------------- Ranked grid ----------------
    @render.data_frame
    def rank_grid():
        r = ranked()
        df = _grid_df(r)
        fracs = r["sun_fraction"].tolist()
        dark = is_dark()

        def style_fn(_data):
            infos = []
            for i, f in enumerate(fracs):
                hexc = D.hex_color(f, dark=dark)
                fg = D.readable_fg(f, dark=dark)
                infos.append(
                    {
                        "location": "body",
                        "rows": [i],
                        "cols": ["% in sun"],
                        "style": {
                            "background-color": hexc,
                            "color": fg,
                            "font-variant-numeric": "tabular-nums",
                            "font-weight": "600",
                        },
                    }
                )
            return infos

        return render.DataGrid(
            df,
            selection_mode="row",
            height="540px",
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
        return ui.HTML(
            f"{_html.escape(str(rec['name']))}"
            f'<span class="chip-type">{_html.escape(str(rec["amenity"]))}</span>'
            f"{chip}"
        )

    @render.ui
    def detail_panel():
        ctx = detail_ctx()
        rec = ctx["rec"]
        prof = ctx["profile"]
        if rec is None:
            return ui.p("No terrace selected.")

        frac = float(rec["sun_fraction"])
        in_sun = bool(rec["in_sun"])
        bh_hour, bh_frac = D.best_hour(prof)

        d1 = ui.value_box(
            "In sun?",
            "☀ In sun" if in_sun else "☁ In shade",
            showcase=ui.HTML(
                '<i class="bi bi-sun"></i>' if in_sun else '<i class="bi bi-cloud"></i>'
            ),
            theme=ui.value_box_theme(bg="#FFB703", fg="#3a2f00")
            if in_sun
            else ui.value_box_theme(bg="#ECEEF2", fg="#5B6470"),
        )
        d2 = ui.value_box(
            "% of terrace lit",
            ui.HTML(
                f"{int(round(frac*100))}%"
                f'<div class="frac-bar-wrap"><div class="frac-bar" '
                f'style="width:{int(round(frac*100))}%"></div></div>'
            ),
            showcase=ui.HTML('<i class="bi bi-brightness-high"></i>'),
            theme=ui.value_box_theme(bg="#FFB703", fg="#3a2f00"),
        )
        if bh_hour is None:
            best_txt = "No sun today"
        else:
            best_txt = f"{bh_hour:02d}:00 ({int(round(bh_frac*100))}%)"
        d3 = ui.value_box(
            "Best sunny hour",
            best_txt,
            showcase=ui.HTML('<i class="bi bi-brightness-high"></i>'),
            theme=ui.value_box_theme(fg="#FB8500"),
        )

        meta = [
            ui.HTML(
                f'<div class="detail-meta"><i class="bi bi-geo-alt"></i> '
                f"{_html.escape(str(rec.get('address') or ''))}</div>"
            )
        ]
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
            ui.layout_columns(
                d1, d2, d3, col_widths={"xs": (12, 12, 12), "sm": (4, 4, 4)}
            ),
            ui.div(ui.output_plot("day_timeline", height="100px"), style="margin-top:.5rem;"),
            ui.div("Cool grey = shade · warm orange = full sun", class_="help-cap"),
            *meta,
        )

    # ---------------- Day timeline ----------------
    @render.plot
    def day_timeline():
        ctx = detail_ctx()
        prof = ctx["profile"]
        dark = is_dark()
        cur_hour = ctx["dt"].hour

        fig, ax = plt.subplots(figsize=(6, 1.0))
        fig.patch.set_alpha(0.0)
        ax.patch.set_alpha(0.0)
        tick_color = "#F4ECDD" if dark else "#2B2118"

        if prof is None or prof.empty:
            ax.axis("off")
            plt.close(fig)
            return fig

        hours = prof["hour"].tolist()
        n = len(hours)
        for i, (_, row) in enumerate(prof.iterrows()):
            f = float(row["sun_fraction"])
            color = D.hex_color(f, dark=dark)
            ax.barh(
                0, width=0.92, left=i + 0.04, height=0.8, color=color,
                edgecolor="white", linewidth=1.2,
            )
            if int(row["hour"]) == int(cur_hour):
                ax.barh(
                    0, width=0.92, left=i + 0.04, height=0.8,
                    facecolor="none",
                    edgecolor=("#FFD166" if dark else "#2B2118"), linewidth=2.4,
                )
                ax.annotate(
                    "▾", (i + 0.5, 0.46), ha="center", va="bottom",
                    color=tick_color, fontsize=11,
                )

        ax.set_xlim(0, n)
        ax.set_ylim(-0.5, 0.6)
        ax.set_yticks([])
        ax.set_xticks([i + 0.5 for i in range(n)])
        ax.set_xticklabels([str(h) for h in hours], color=tick_color, fontsize=7.5)
        ax.tick_params(length=0)
        for spine in ax.spines.values():
            spine.set_visible(False)
        fig.tight_layout()
        plt.close(fig)
        return fig

    # ---------------- Maps ----------------
    @reactive.calc
    def deck_html_dash():
        dt, _, _ = snapped()
        df = D.snapshot_for(SHADOWS, TERRACES, dt)
        return D.build_deck_html(
            df, selected_id(), BUILDINGS, PERMITS, is_dark(), dt=dt, zoom=13.7
        )

    @reactive.calc
    def deck_html_big():
        dt, _, _ = snapped()
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
        dt, _, _ = snapped()
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
        )


app = App(app_ui, server)
