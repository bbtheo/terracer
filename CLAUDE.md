# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Quick Start

```bash
pixi install
pixi run download_mesh --insecure
pixi run shadows --validate
pixi run app
```

## Project Overview

Terracer: a Shiny for Python web app that shows whether Helsinki bar terraces are in sun at a chosen time, using the City of Helsinki 3D data and ray casting. The preprocessing pipeline now supports CityGML (buildings parquet) and the full-city mesh tiles (OBJ) to cover the terrace area. See `plan.md` for architecture.

## Commands

```bash
pixi install          # Install dependencies
pixi run app          # Run the Shiny app
pixi run shiny        # Alias for running the Shiny app
pixi run preprocess   # Run preprocessing pipeline
pixi run download     # Download CityGML (manual URL required)
pixi run download_mesh # Download mesh tiles covering terraces
pixi run fetch_polygons # Fetch terrace permit polygons (Helsinki WFS), match to bars
pixi run test         # Run tests
pixi shell            # Enter the environment shell
```

## Directory Structure

- `src/preprocessing/` - offline data pipeline (download 3D model, parse CityGML, compute shadows)
- `src/app/` - Shiny application (UI, server logic)
- `src/core/` - shared logic (sun position, ray casting, terrace model)
- `data/raw/` - downloaded CityGML + mesh tiles (gitignored)
- `data/processed/` - simplified buildings parquet
- `data/shadows/` - precomputed sun/shade tables
- `data/terraces.geojson` - terrace locations + metadata
- `data/terrace_polygons.geojson` - terrace permit polygons matched to bars (city WFS)
- `tests/` - test suites

## Code Style

- Python: 4 spaces
- File naming: `lower_snake_case`

## Key Libraries

- `pixi` - dependency management
- `pysolar` - sun position calculation
- `trimesh` - 3D mesh processing and ray casting
- `shiny` - web framework
- `pydeck` - map rendering
- `geopandas` - geospatial operations
- `rtree` - spatial index for mesh ray casting

## Notes

- Mesh downloads from `3d.hel.ninja` use an expired TLS cert; use `--insecure` with `pixi run download` or `pixi run download_mesh`.
