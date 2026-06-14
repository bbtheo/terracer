# Terracer - sunshine checker for Helsinki terraces

Goal: build a website that shows whether Helsinki bar terraces are in sun at a chosen time, using the City of Helsinki 3D model and sunlight ray casting.

**Stack:** Shiny for Python, hosted on Posit Connect. Dependencies managed with pixi.

---

## Data sources

### Helsinki 3D city model
- **Download service:** https://kartta.hel.fi/3d/
- **WFS API:** https://kartta.hel.fi/3d/citydb-wfs/wfs (version 2.0.0)
- **Formats:** CityGML, 3D Tiles, OBJ, DAE, FBX, 3MX/3SM
- **Coordinate system:** ETRS-GK25 (plane) + N2000 (height)
- **Detail levels:** LoD1 and LoD2

**Recommendation:** CityGML for semantics and analysis; export simplified meshes for ray casting.

### Terrace locations
- Source options: manual curation, OpenStreetMap (`amenity=cafe` + `outdoor_seating=yes`), Helsinki open data.
- Store as `data/terraces.geojson` with geometry + metadata (name, address, opening hours).

---

## Architecture (offline + runtime)

```
┌─────────────────────────────────────────────────────────────────┐
│                        PREPROCESSING (offline)                   │
├─────────────────────────────────────────────────────────────────┤
│  1. Download Helsinki 3D model (target area)                    │
│  2. Convert CityGML → simplified mesh (trimesh/PyVista)         │
│  3. Precompute sun/shade by terrace for a time grid             │
│  4. Store results in parquet or SQLite                          │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      DATA LAYER (static files)                   │
├─────────────────────────────────────────────────────────────────┤
│  • data/terraces.geojson        - terrace geometry + metadata   │
│  • data/shadows/                - precomputed sun/shade tables  │
│  • data/buildings.parquet       - simplified meshes for viz     │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      SHINY APP (runtime)                         │
├─────────────────────────────────────────────────────────────────┤
│  UI Components:                                                  │
│  • Map view (pydeck) with terrace markers                       │
│  • Date/time picker (reactive input)                            │
│  • Terrace detail panel (sun hours today)                       │
│  • "Best terraces now" ranking                                  │
│                                                                  │
│  Server Logic:                                                   │
│  • Load precomputed sun/shade for selected datetime             │
│  • Query which terraces are in sun                              │
│  • Render map with sun/shade status per terrace                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## Key libraries

| Purpose | Library | Notes |
|---------|---------|-------|
| Dependency management | `pixi` | Conda/pip lockfile, reproducible environments |
| Sun position | `pysolar` | Calculate sun azimuth/elevation for Helsinki coords |
| 3D mesh processing | `trimesh` or `pyvista` | Load/simplify CityGML meshes |
| Shadow/ray casting | `trimesh.ray` or custom | Cast rays from sun direction to terrace points |
| Web framework | `shiny` (Python) | Reactive UI |
| Map rendering | `pydeck` | 3D building extrusions + terrace markers |
| Geospatial ops | `geopandas`, `shapely` | Coordinate transforms, spatial queries |

### Pixi commands

```bash
pixi install          # Install dependencies
pixi run app          # Run the Shiny app (define task in pixi.toml)
pixi run preprocess   # Run preprocessing pipeline
pixi run test         # Run tests
pixi shell            # Enter the environment shell
```

---

## Shadow calculation strategy

### Recommended: precompute
1. Define a time grid (hourly; seasonal sampling for the year).
2. Compute sun position with `pysolar`.
3. Ray cast from each terrace toward the sun through the building mesh.
4. Store sun/shade per terrace per datetime.
5. At runtime, select the nearest precomputed time.

**Why:** Fast UI responses and predictable compute cost.

---

## Implementation phases

### Phase 1: Data pipeline
- [ ] Download 3D model for the initial target area
- [ ] Parse CityGML → building geometries
- [ ] Build a simplified mesh for ray casting
- [ ] Curate 20-30 terraces with coordinates

### Phase 2: Shadow engine
- [ ] Implement sun position calculation for Helsinki (lat 60.17°, lon 24.94°)
- [ ] Build ray casting: terrace point → sun direction → intersection test
- [ ] Validate against known cases (midsummer noon vs winter midday)
- [ ] Precompute sun/shade matrix for terraces × time grid

### Phase 3: Shiny app MVP
- [ ] Map view showing terraces with sun/shade icons
- [ ] Date/time slider input
- [ ] Click terrace → show daily sun hours
- [ ] Deploy to Posit Connect

### Phase 4: Polish
- [ ] "Best sunny terraces right now" feature
- [ ] Weekly/monthly sun exposure summary
- [ ] Mobile-friendly layout
- [ ] Add more terraces based on user feedback

---

## Proposed file structure

```
terracer/
├── src/
│   ├── preprocessing/
│   │   ├── download_3d_model.py
│   │   ├── parse_citygml.py
│   │   └── compute_shadows.py
│   ├── app/
│   │   ├── app.py              # Shiny app entry point
│   │   ├── ui.py               # UI components
│   │   ├── server.py           # Server logic
│   │   └── components/
│   │       ├── map.py
│   │       └── charts.py
│   └── core/
│       ├── sun.py              # Sun position calculations
│       ├── shadow.py           # Ray casting logic
│       └── terraces.py         # Terrace data model
├── data/
│   ├── raw/                    # Downloaded 3D models
│   ├── processed/              # Simplified meshes, shadow maps
│   └── terraces.geojson
├── tests/
├── pixi.toml
├── pixi.lock
└── plan.md
```

---

## Open questions

1. **Terrace data source:** Manual curation vs OSM vs Helsinki open data?
2. **3D model scope:** Central Helsinki only, or expand (Kallio, Töölö, etc.)?
3. **Time resolution:** Hourly vs 15-minute grid?
4. **Partial shade:** Binary sun/shade vs percent of terrace area in sun?

---

## References

- [Helsinki 3D City Model](https://www.hel.fi/en/decision-making/information-on-helsinki/maps-and-geospatial-data/helsinki-3d)
- [Helsinki 3D Download Service](https://kartta.hel.fi/3d/)
- [Helsinki Region Infoshare - 3D Models](https://hri.fi/data/en_GB/dataset/helsingin-3d-kaupunkimalli)
- [PySolar](https://pysolar.readthedocs.io/)
- [Shiny for Python](https://shiny.posit.co/py/docs/overview.html)
- [PyDeck](https://pydeck.gl/)
- [Trimesh](https://trimesh.org/)
