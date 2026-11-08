# Terracer 🍺☀️

**Is your favourite Helsinki bar terrace in the sun right now?**

Terracer is a [Shiny for Python](https://shiny.posit.co/py/) web app that shows
whether the bar terraces of Kallio (Helsinki) are in sunshine or shade at a
chosen date and time. It uses the City of Helsinki **3D city model** and
**ray casting** against the real building geometry to decide, for each terrace,
how much of it is lit by the sun.

## Features

- **Shadow map + sun strips on one screen.** The map shows the shadows at the
  chosen moment, and every bar's open-and-sunny day is one strip in the table.
- **One handle.** A single pill on the table's edge: drag sideways for the time,
  up or down to resize. Near either end the table clicks into full-screen table
  or full-screen map.
- **Date slider.** Tap the date and the pill moves across a season ribbon: fine
  control near where it last rested, big jumps further away. Today is one tap.
- **Colours follow the day.** Light and dark are relative to each date's highest
  sun, so every season gets its full range.
- **Bars ranked by open-and-sunny time left**, using real per-bar opening hours.

## How it works

```
Offline preprocessing (pixi)              Runtime (Shiny app)
─────────────────────────────             ───────────────────
1. Download Helsinki 3D mesh tiles   ┐
2. Footprints + mesh heights         ├─►  data/  ──►  Shiny hosts one page
3. Ray-cast sun→terrace per datetime ┘   (geojson + parquet)   • shadow map (canvas)
   → data/shadows/*.parquet                                    • sun strips table
```

The heavy work is **precomputed offline**: for a grid of dates and hours the
sun position is computed with [`pysolar`](https://pysolar.readthedocs.io/), and
a ray is cast from each terrace toward the sun through the building mesh with
[`trimesh`](https://trimesh.org/). The result (`in_sun` + `sun_fraction` per
terrace per datetime) is stored in a small parquet table the app reads at
runtime, so the UI stays fast.

The current sun/shade table covers **2026**, sampled **biweekly** across the
year at **half-hourly** times from **08:00 to 23:00**, for **44 terraces**
(each with real opening hours). Terraces that occupy more than one side of a
building are stored as multi-part polygons, so the sun fraction integrates
across all of their sides.

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
  app/            Shiny host (app.py), data bundling (data.py), page (www/)
  core/           Shared logic — sun position, mesh loading, ray casting, terraces
  preprocessing/  Offline pipeline — download, parse CityGML, compute shadows
data/
  terraces.geojson            44 terrace locations + opening hours + metadata
  terrace_polygons.geojson    permit terrace polygons matched to bars
  processed/buildings.parquet CityGML building footprints + heights
  processed/city_blocks.parquet map footprints (city WFS) + mesh-measured heights
  shadows/terrace_shadows.parquet  precomputed sun/shade table
  raw/            downloaded 3D model + mesh tiles (gitignored, multi-GB)
tests/            pytest suites
```

## Common commands

| Command | What it does |
|---|---|
| `pixi run app` | Run the Shiny app |
| `pixi run shadows` | Recompute the sun/shade table |
| `pixi run blocks` | Rebuild the map's building footprints |
| `pixi run basemap` | Fetch the map's streets and water |
| `pixi run download_mesh` | Download Helsinki 3D mesh tiles (use `--insecure`) |
| `pixi run fetch_polygons` | Fetch terrace permit polygons (Helsinki WFS) |
| `pixi run test` | Run the test suite |

## Development

```bash
pixi run test                       # full suite (app + core/preprocessing)
pixi run pytest tests/test_app.py   # just the app's data-layer tests
```

## Data

Building footprints, streets and water are open data from the
[City of Helsinki](https://kartta.hel.fi/) (CC BY 4.0), as is the 3D city model.

## Tech stack

[Shiny for Python](https://shiny.posit.co/py/) ·
[geopandas](https://geopandas.org/) · [shapely](https://shapely.readthedocs.io/) ·
[trimesh](https://trimesh.org/) · [pysolar](https://pysolar.readthedocs.io/) ·
[pixi](https://pixi.sh/) for environments.

## Deployment

The app is packaged for **[Posit Connect Cloud](https://connect.posit.cloud)**
(Git-based, builds from `requirements.txt` on Python 3.12). See
[`DEPLOY.md`](DEPLOY.md) for the publish steps.

## Data sources

- [Helsinki 3D city model](https://kartta.hel.fi/3d/) — building geometry
  (ETRS-GK25 / N2000), via [Helsinki Region Infoshare](https://hri.fi/).
- Terrace locations and matched permit polygons from City of Helsinki open data.
