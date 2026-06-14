# Repository Guidelines

## Quick Start

```bash
pixi install
pixi run download_mesh --insecure
pixi run shadows --validate
pixi run app
```

## Project Structure & Module Organization
Core code lives in `src/`: preprocessing scripts in `src/preprocessing/`, shared geometry logic in `src/core/`, and the Shiny app in `src/app/`. Data lives in `data/`: `data/raw/` for CityGML or mesh tiles, `data/processed/` for parsed building footprints, and `data/shadows/` for precomputed sun/shade tables. Terrace locations are stored in `data/terraces.geojson`.

## Build, Test, and Development Commands
Use pixi tasks from the repo root:
- `pixi install` - install dependencies.
- `pixi run app` or `pixi run shiny` - run the Shiny app.
- `pixi run preprocess` - run the CityGML pipeline (download + parse).
- `pixi run download -- --url <URL> --filename <FILE.gml>` - download CityGML manually.
- `pixi run download_mesh --insecure` - download mesh tiles covering terraces.
- `pixi run shadows --validate` - precompute sun/shade table and run a sun-altitude sanity check.
- `pixi run test` - run tests (pytest).

## Coding Style & Naming Conventions
Default to consistent, language-native formatting and keep changes self-contained. Until a formatter is added, use 2 spaces for JSON/YAML, 4 spaces for Python, and tabs or 2 spaces for JS/TS depending on the ecosystem you add. Use descriptive, lower_snake_case names for files unless the language prefers another pattern (for example, `PascalCase` for class-based modules).

## Testing Guidelines
Tests run with `pytest` via `pixi run test`. Name tests `test_*.py` and keep fixtures small. Add fixtures for sample CityGML/OBJ paths if you introduce new preprocessing steps.

## Commit & Pull Request Guidelines
No commit conventions are established. Use clear, imperative commit messages that explain intent (for example, "Add initial parsing pipeline"). For pull requests, include a short summary, list of changes, and any relevant command output. Attach screenshots for UI changes and link related issues when available.

## Security & Configuration Tips
Avoid committing secrets. The public mesh and CityGML hosts use expired TLS certificates; downloading requires `--insecure` flags in the provided scripts. Document any new environment variables in `README.md` and use example files for config.
