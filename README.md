# Terracer 🍺☀️

**Is your favourite Helsinki bar terrace in the sun right now?**

Terracer is a [Shiny for Python](https://shiny.posit.co/py/) web app that shows
whether the bar terraces of Kallio (Helsinki) are in sunshine or shade at a
chosen date and time. It uses the City of Helsinki **3D city model** and
**ray casting** against the real building geometry to decide, for each terrace,
how much of it is lit by the sun.

## Features

- **Interactive dashboard** — pick a date and hour and instantly see how many
  terraces are sunny, the sunniest spot, the average sunlight, and how many sun
  hours are left in the day.
- **"Sunniest now" ranking** — all terraces sorted by the share of the terrace
  in sun; click a row to inspect one.
- **Per-terrace detail** — % of the terrace lit, the best sunny hour, an hourly
  **day timeline** (08:00–23:00), address, and a Google Maps link.
- **3D map** — terraces coloured on a shade→sun gradient over extruded Kallio
  buildings, with a **sun-direction compass** showing where the sun is
  (azimuth + elevation, or "below horizon").
- **Dark mode**, a warm "sunshine" theme, and a **mobile-friendly** responsive
  layout. The date picker defaults to the day you open the app.

## How it works

```
Offline preprocessing (pixi)              Runtime (Shiny app)
─────────────────────────────             ───────────────────
1. Download Helsinki 3D mesh tiles   ┐
2. Parse CityGML → building heights  ├─►  data/  ──►  Shiny app
3. Ray-cast sun→terrace per datetime ┘   (geojson + parquet)   • map (pydeck)
   → data/shadows/*.parquet                                    • ranking + detail
                                                               • sun compass (pysolar)
```

The heavy work is **precomputed offline**: for a grid of dates and hours the
sun position is computed with [`pysolar`](https://pysolar.readthedocs.io/), and
a ray is cast from each terrace toward the sun through the building mesh with
[`trimesh`](https://trimesh.org/). The result (`in_sun` + `sun_fraction` per
terrace per datetime) is stored in a small parquet table the app reads at
runtime, so the UI stays fast.

The current sun/shade table covers **2026**, sampled **biweekly** across the
year at **hourly** times from **08:00 to 23:00**, for **37 terraces**.

## Quick start

The precomputed data is committed, so you can run the app straight away:

```bash
pixi install
pixi run app          # open the printed URL
```

To regenerate the 3D model and sun/shade data from scratch:

```bash
pixi run download_mesh --insecure   # fetch Helsinki 3D mesh tiles
pixi run shadows --validate         # recompute data/shadows/terrace_shadows.parquet
```

> **Note:** mesh downloads from `3d.hel.ninja` use an expired TLS certificate,
> so `--insecure` is required for the download steps.

## Project structure

```
src/
  app/            Shiny app — app.py (UI + server), data.py (pure data layer)
  core/           Shared logic — sun position, mesh loading, ray casting, terraces
  preprocessing/  Offline pipeline — download, parse CityGML, compute shadows
data/
  terraces.geojson            37 terrace locations + metadata
  terrace_polygons.geojson    permit terrace polygons matched to bars
  processed/buildings.parquet building footprints + heights
  shadows/terrace_shadows.parquet  precomputed sun/shade table
  raw/            downloaded 3D model + mesh tiles (gitignored, multi-GB)
tests/            pytest suites
```

## Common commands

| Command | What it does |
|---|---|
| `pixi run app` | Run the Shiny app |
| `pixi run shadows` | Recompute the sun/shade table |
| `pixi run download_mesh` | Download Helsinki 3D mesh tiles (use `--insecure`) |
| `pixi run fetch_polygons` | Fetch terrace permit polygons (Helsinki WFS) |
| `pixi run test` | Run the test suite |

## Development

```bash
pixi run test                       # full suite (app + core/preprocessing)
pixi run pytest tests/test_app.py   # just the app's data-layer tests
```

## Tech stack

[Shiny for Python](https://shiny.posit.co/py/) · [pydeck](https://pydeck.gl/) ·
[geopandas](https://geopandas.org/) · [shapely](https://shapely.readthedocs.io/) ·
[trimesh](https://trimesh.org/) · [pysolar](https://pysolar.readthedocs.io/) ·
[matplotlib](https://matplotlib.org/) · [pixi](https://pixi.sh/) for environments.

## Deployment

The app is packaged for **[Posit Connect Cloud](https://connect.posit.cloud)**
(Git-based, builds from `requirements.txt` on Python 3.12). See
[`DEPLOY.md`](DEPLOY.md) for the publish steps.

## Data sources

- [Helsinki 3D city model](https://kartta.hel.fi/3d/) — building geometry
  (ETRS-GK25 / N2000), via [Helsinki Region Infoshare](https://hri.fi/).
- Terrace locations and matched permit polygons from City of Helsinki open data.
