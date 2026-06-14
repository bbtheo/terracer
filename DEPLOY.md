# Deploying Terracer to Posit Connect Cloud

The app is hosted on [Posit Connect Cloud](https://connect.posit.cloud), which
deploys directly from this GitHub repo and builds the Python environment from
`requirements.txt`.

## What ships

- **`requirements.txt`** (repo root) — the **runtime** dependency subset only,
  pinned to versions validated on **Python 3.12** (Connect Cloud's build).
  geopandas reads the GeoJSON via `pyogrio` (GDAL bundled in its wheels), so no
  system libraries are needed.
- **`src/app/app.py`** — the Shiny entry point (`app = App(app_ui, server)`).
- **`data/`** — the small precomputed inputs the app loads at startup
  (`terraces.geojson`, `terrace_polygons.geojson`, `processed/buildings.parquet`,
  `shadows/terrace_shadows.parquet`, ~0.9 MB total). `data/raw/` (the multi-GB
  3D mesh) is **gitignored** and only used by the offline pipeline.

`pixi` and the preprocessing pipeline (`src/preprocessing/`, `src/core/`,
`trimesh`, `rtree`, …) are **development/offline only** — they are not part of
the deployed runtime.

## Deploy steps (Connect Cloud UI)

1. Sign in at [connect.posit.cloud](https://connect.posit.cloud).
2. Click **Publish** → **Shiny**.
3. Select the repo **`bbtheo/terracer`**, branch **`main`**.
4. Set the primary file to **`src/app/app.py`**.
5. Choose Python **3.12**.
6. Click **Publish**.

Re-deploy after changes by pushing to `main` and clicking **republish** on the
content item (or enabling auto-republish).

## Regenerating the data (offline, not needed to deploy)

The sun/shade table is precomputed for **2026, hourly 08:00–23:00** on a
biweekly date grid:

```bash
pixi run shadows          # writes data/shadows/terrace_shadows.parquet
```

## Local check against the deploy environment

To reproduce Connect Cloud's pip-only build before pushing:

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest tests/test_app.py
.venv/bin/python -m shiny run src/app/app.py   # then open the printed URL
```
