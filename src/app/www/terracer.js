// Terracer page: one screen with a shadow map above per-bar sun strips.
(() => {
  const DATA = JSON.parse(document.getElementById('terracer-data').textContent);
  const SLOTS = DATA.slots;
  const N = SLOTS.length;
  const BARS = DATA.bars;
  const DATES = DATA.dates;
  for (const d of DATES) for (const id in d.s) d.s[id] = [...d.s[id]].map((c) => parseInt(c, 11) / 10);

  const boxed = (points) => {
    const xs = points.map((p) => p[0]);
    const ys = points.map((p) => p[1]);
    return { x0: Math.min(...xs), x1: Math.max(...xs), y0: Math.min(...ys), y1: Math.max(...ys) };
  };
  const ROADS = DATA.roads.map(([width, line]) => ({ width, line, ...boxed(line) }));
  const ROAD_WIDTHS = [...new Set(ROADS.map((r) => r.width))].sort((a, b) => a - b);
  const WATER = DATA.water;

  const BLOCKS = DATA.blocks.map(([height, ring]) => ({ height, ring, ...boxed(ring) }));

  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
  const esc = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;');
  const fmt = (m) => `${String(Math.floor(m / 60) % 24).padStart(2, '0')}:${String(m % 60).padStart(2, '0')}`;

  // --- Colour ---------------------------------------------------------------
  const TOKENS = ['ground', 'shade', 'bldg', 'sheet', 'ink', 'mut', 'sun', 'slot', 'line', 'dot', 'row', 'water'];
  const keys = (s) => s.split(' ').map((x) => `#${x}`);

  // Keyed on sun height scaled so the day's peak is 55 (see equivalentAltitude).
  const DARK_FROM = 7;
  const DARK = [
    [-6, keys('0E0D30 0B0A28 22215A 0D0C28 F2EEFA B4AED0 FFA95C 2E2C58 24224C 0D0C28 25234F 12254F')],
    [-2, keys('17164A 121140 2C2A6C 12113A F2EEFA B8B2D6 FFA95C 34315F 2A2755 12113A 2C2958 1A2F63')],
    [2, keys('4F3A96 35297C 6650AE 1E1A44 F4EFFA BFB6D8 FFA050 3D3568 322A5A 1E1A44 352C60 3E4FA6')],
    [7, keys('E8705E 4F3A96 F2A88E 2A1F4A F6EFFA C4B8DA FF9A4D 4A3D70 3E3260 2A1F4A 42346A 6C7FC4')],
  ];
  const AFTERNOON = [
    [7, keys('E8705E 4F3A96 F2A88E FFE1CF 2B1230 63405A B8391A EBC8BA F4D6C8 33246E FBCFB9 5F7FC8')],
    [12, keys('FF9A58 6448AE FFC79A FFEBD6 2F1530 6A4560 C84512 EFD2BD F6DFCB 3F2E80 FFDCBE 6FA8D6')],
    [20, keys('FFC56E 8470CC FFEBC8 FFF6E6 33213F 6C5367 D9531C F0DECC F7E8D9 4D3D8C FFE6CF 8CC4E0')],
    [35, keys('FFE3C2 A79ADF FFF8EE FFFDF9 2F2748 6A6189 E25A1E E7E1F3 F1ECF7 5B4F98 FFF0E6 9FD6E6')],
    [55, keys('FFF6DC A9B4F0 FFFFFF FFFFFF 2A2448 625A82 E25A1E E6E5F6 F0EFF9 4F4A9A FFF2E2 A8E0EC')],
  ];
  const MORNING = [
    AFTERNOON[0],
    [12, keys('FFC6A8 7C7FD6 FFE0CC FFF0E6 2A2048 5F4F70 D64A26 EAD6D8 F3E2E0 3E3880 FCDDD4 86B6DC')],
    [20, keys('FFDFB0 8F97DF FFF1DE FFF9F0 2C2448 63597D DB531F E8E0EC F2EAEC 4A478F FFEBDD 98CCE6')],
    [35, keys('FFEECB 9FACE8 FFFDF3 FFFFFA 2A2848 615F85 E25A1E E3E4F3 EEEFF7 54579E FFF0E3 A5DAEA')],
    AFTERNOON[4],
  ];

  const toLinear = (c) => { c /= 255; return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4; };
  const toSrgb = (x) => { x = clamp(x, 0, 1); return Math.round(255 * (x <= 0.0031308 ? 12.92 * x : 1.055 * x ** (1 / 2.4) - 0.055)); };
  const toLab = (h) => {
    const n = parseInt(h.slice(1), 16);
    const r = toLinear((n >> 16) & 255), g = toLinear((n >> 8) & 255), b = toLinear(n & 255);
    const l = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b);
    const m = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b);
    const s = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b);
    return [0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s, 1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s, 0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s];
  };
  const toHex = ([L, a, b]) => {
    const l = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3;
    const m = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3;
    const s = (L - 0.0894841775 * a - 1.291485548 * b) ** 3;
    const rgb = [4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s, -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s, -0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s];
    return `#${rgb.map((v) => toSrgb(v).toString(16).padStart(2, '0')).join('')}`;
  };
  const mix = (a, b, t) => a.map((x, k) => x + (b[k] - x) * t);
  const smooth = (t) => t * t * (3 - 2 * t);
  const toLabRamp = (ramp) => ramp.map(([alt, colours]) => [alt, colours.map(toLab)]);
  const LAB_DARK = toLabRamp(DARK);
  const LAB_AFTERNOON = toLabRamp(AFTERNOON);
  const LAB_MORNING = toLabRamp(MORNING);

  const sampleRamp = (ramp, alt) => {
    alt = clamp(alt, ramp[0][0], ramp[ramp.length - 1][0]);
    let k = 0;
    while (k < ramp.length - 2 && alt > ramp[k + 1][0]) k++;
    const t = smooth((alt - ramp[k][0]) / (ramp[k + 1][0] - ramp[k][0]));
    return ramp[k][1].map((c, q) => mix(c, ramp[k + 1][1][q], t));
  };
  // Relative, not absolute: each date runs its full light-to-dark range.
  const equivalentAltitude = (alt, peak) => (alt > 0 ? (alt / peak) * 55 : alt);
  const paletteAt = (date, slot) => {
    const x = equivalentAltitude(date.sun[slot][1], date.noon);
    if (x < DARK_FROM) return sampleRamp(LAB_DARK, x);
    const w = smooth(clamp((SLOTS[slot] - date.noonT + 60) / 120, 0, 1));
    const am = sampleRamp(LAB_MORNING, x);
    const pm = sampleRamp(LAB_AFTERNOON, x);
    return am.map((c, q) => mix(c, pm[q], w));
  };

  // --- Calendar -------------------------------------------------------------
  const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  const WEEKDAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
  const parts = Object.fromEntries(
    new Intl.DateTimeFormat('en-GB', { timeZone: 'Europe/Helsinki', year: 'numeric', month: 'numeric', day: 'numeric', hour: 'numeric', minute: 'numeric', hourCycle: 'h23' })
      .formatToParts(new Date()).map((p) => [p.type, p.value]),
  );
  const YEAR = +parts.year;
  const dateOf = (n) => new Date(YEAR, 0, n);
  const doyOf = (d) => Math.round((Date.UTC(YEAR, d.getMonth(), d.getDate()) - Date.UTC(YEAR, 0, 0)) / 864e5);
  const shortDate = (d) => `${d.getDate()} ${MONTHS[d.getMonth()]}`;
  const longDate = (d) => `${WEEKDAYS[d.getDay()]} ${shortDate(d)}`;
  const wrapFloat = (n) => ((n - 1) % 365 + 365) % 365 + 1;
  const wrapDay = (n) => Math.round(wrapFloat(n));
  const dayDiff = (a, b) => { let q = a - b; if (q > 182.5) q -= 365; if (q < -182.5) q += 365; return q; };
  const TODAY = Math.min(365, doyOf(new Date(YEAR, +parts.month - 1, +parts.day)));
  const NOW_SLOT = clamp(Math.round((+parts.hour * 60 + +parts.minute - SLOTS[0]) / 30), 0, N - 1);

  // The date slider is a lens around the last resting date: u is -1..1 of the
  // half-track, 46px is about a week and the far edge is half a year.
  const lensDays = (u) => { const a = Math.abs(u); return Math.sign(u) * (23 * a + 159 * a ** 5); };
  const lensPos = (days) => {
    const target = Math.min(182, Math.abs(days));
    let lo = 0, hi = 1;
    for (let k = 0; k < 26; k++) { const m = (lo + hi) / 2; if (lensDays(m) < target) lo = m; else hi = m; }
    return Math.sign(days) * lo;
  };

  const peakAt = (n) => {
    if (n <= DATES[0].doy) return DATES[0].noon;
    for (let k = 1; k < DATES.length; k++) {
      if (n <= DATES[k].doy) return DATES[k - 1].noon + (DATES[k].noon - DATES[k - 1].noon) * (n - DATES[k - 1].doy) / (DATES[k].doy - DATES[k - 1].doy);
    }
    return DATES[DATES.length - 1].noon;
  };
  const SEASON_START = [60, 152, 244, 335];
  const SEASON_NAME = ['Spring', 'Summer', 'Autumn', 'Winter'];
  const SEASON_COLOUR = ['#7CC47A', '#F5B93A', '#D9743A', '#7FB3E6'].map(toLab);
  const seasonOf = (n) => (n < 60 || n >= 335 ? 3 : n < 152 ? 0 : n < 244 ? 1 : 2);
  const seasonColour = (n) => {
    for (let k = 0; k < 4; k++) {
      const q = dayDiff(n, SEASON_START[k]);
      if (Math.abs(q) <= 12) return toHex(mix(SEASON_COLOUR[(k + 3) % 4], SEASON_COLOUR[k], (q + 12) / 24));
    }
    return toHex(SEASON_COLOUR[seasonOf(n)]);
  };
  const SEASON_ICON = [
    '<path d="M6 11V5M6 7C6 4 4 3 2 3c0 3 2 4 4 4zM6 6c0-3 2-4 4-4 0 3-2 4-4 4z"/>',
    '<circle cx="6" cy="6" r="2.3"/><path d="M6 .8v1.4M6 9.8v1.4M.8 6h1.4M9.8 6h1.4M2.3 2.3l1 1M8.7 8.7l1 1M2.3 9.7l1-1M8.7 3.3l1-1"/>',
    '<path d="M2 10C2 5 5 2 10 2c0 5-3 8-8 8zM2 10l4-4"/>',
    '<path d="M6 1v10M1.7 3.5l8.6 5M1.7 8.5l8.6-5"/>',
  ].map((p) => `<svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round">${p}</svg>`);

  // --- Page -----------------------------------------------------------------
  const app = document.getElementById('app');
  // Drawn from an attribute: as real text, iOS Safari links these as a phone number.
  const HOUR_LABELS = [8, 12, 16, 20, 23]
    .map((h) => `<span aria-hidden="true" data-label="${String(h).padStart(2, '0')}" style="left:${(((h - 8) * 2 + 0.5) / N) * 100}%"></span>`).join('');
  app.innerHTML = `
    <canvas class="map"></canvas>
    <div class="credit">© City of Helsinki</div>
    <div class="sheet">
      <button class="pill" aria-label="Drag sideways to change the value, or up and down to resize the table. Arrow keys also work."></button>
      <div class="column"></div><div class="neck"></div>
      <div class="hrow">
        <div class="date-buttons">
          <button class="date" aria-label="Change date"></button>
          <button class="today" aria-label="Go back to today">Today</button>
        </div>
        <span class="count"></span>
      </div>
      <div class="track-wrap"><div class="track"></div></div>
      <div class="mini"></div>
      <div class="wrap"><div class="list"></div></div>
    </div>`;
  const $ = (q) => app.querySelector(q);
  const canvas = $('.map'), sheet = $('.sheet'), pill = $('.pill'), column = $('.column'), neck = $('.neck');
  const track = $('.track'), mini = $('.mini'), wrap = $('.wrap'), list = $('.list');
  const dateButton = $('.date'), todayButton = $('.today'), hrow = $('.hrow'), countLabel = $('.count');
  const ctx = canvas.getContext('2d');
  const shadowCanvas = document.createElement('canvas');
  const shadowCtx = shadowCanvas.getContext('2d');
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const still = matchMedia('(prefers-reduced-motion: reduce)').matches;

  const DEFAULT_ZOOM = 2; // metres per CSS pixel; smaller is closer
  const MIN_ZOOM = 0.5;
  const MAX_ZOOM = 5;
  const MIN_ROAD_PX = { 3: 0.8, 8: 1.5, 13: 2.5 };
  const MAX_SHADOW_M = 260;
  const SNAP_PX = 70;
  const MINI_H = 50;
  const [X0, Y0, X1, Y1] = DATA.bounds;

  let W = 0, H = 0, MID = 0, MAP_TOP = 0;
  let doy = TODAY, slot = NOW_SLOT, picking = false;
  let rest = doy, lensCentre = doy;
  let dateRow, weekday;
  const syncDate = () => {
    let best = 0;
    DATES.forEach((d, k) => { if (Math.abs(d.doy - doy) < Math.abs(DATES[best].doy - doy)) best = k; });
    dateRow = DATES[best];
    weekday = (dateOf(doy).getDay() + 6) % 7;
  };
  syncDate();

  const hours = (b) => b.h[weekday];
  const isOpen = (b, j) => { const h = hours(b); return !!h && h[0] <= SLOTS[j] && SLOTS[j] < h[1]; };
  const isSunny = (b, j) => isOpen(b, j) && dateRow.s[b.id][j] >= 0.5;
  const sunnyRun = (b, j) => { let k = 0; while (j + k < N && isSunny(b, j + k)) k++; return k; };
  const sunLeft = (b, j) => { let k = 0; for (let q = j; q < N; q++) if (isSunny(b, q)) k++; return k; };
  const nextSun = (b, j) => { for (let q = j; q < N; q++) if (isSunny(b, q)) return q; return -1; };
  const ranked = () => [...BARS].sort((a, b) => (isSunny(b, slot) - isSunny(a, slot)) || (sunLeft(b, slot) - sunLeft(a, slot)) || (isOpen(b, slot) - isOpen(a, slot)) || a.n.localeCompare(b.n));

  let order = ranked(), selected = order[0];
  let colours = paletteAt(dateRow, slot).map((c) => [...c]), P = {};
  let top = 0, topTarget = 0, raf = 0;
  let cx = 0, cy = 0, cxTarget = 0, cyTarget = 0;
  let zoom = DEFAULT_ZOOM, zoomTarget = DEFAULT_ZOOM;

  const cardHeight = () => (picking ? 50 + 52 : 44 + 20) + MINI_H + 4;
  const viewCentreY = () => top / 2 + 8;
  const visibleBottom = () => (top >= MAP_TOP - 100 ? H : top);
  const clampCx = (x) => { const half = (W * zoom) / 2, a = X0 + half, b = X1 - half; return a < b ? clamp(x, a, b) : (a + b) / 2; };
  const clampCy = (y) => { const a = Y0 + (visibleBottom() - viewCentreY()) * zoom, b = Y1 - viewCentreY() * zoom; return a < b ? clamp(y, a, b) : (a + b) / 2; };
  const px = (x) => W / 2 + (x - cx) / zoom;
  const py = (y) => viewCentreY() - (y - cy) / zoom;

  function applyColours() {
    TOKENS.forEach((name, k) => { P[name] = toHex(colours[k]); app.style.setProperty(`--${name}`, P[name]); });
    document.body.style.background = P.sheet;
  }

  function placeHandle() {
    const width = sheet.clientWidth || W;
    const inner = width - 32;
    const x = 16 + (picking ? (1 + lensPos(dayDiff(doy, lensCentre))) / 2 : (slot + 0.5) / N) * inner;
    const slotWidth = inner / N;
    const pillTop = parseFloat(pill.style.top) || -18;
    pill.style.left = `${clamp(x, 50, width - 50)}px`;
    column.style.display = picking ? 'none' : 'block';
    column.style.left = `${x - slotWidth / 2}px`;
    column.style.width = `${slotWidth}px`;
    column.style.top = `${Math.max(0, pillTop + 18)}px`;
    neck.style.left = `${x - 6}px`;
    neck.style.top = `${pillTop + 35}px`;
  }

  // Full-screen map turns the sheet into a floating card.
  function shapeSheet() {
    const e = smooth(clamp((top - (MAP_TOP - 118)) / 118, 0, 1));
    const nearTop = Math.min(top, 40) / 40;
    sheet.style.top = `${top}px`;
    sheet.style.left = sheet.style.right = `${10 * e}px`;
    sheet.style.bottom = `${12 * e}px`;
    sheet.style.paddingTop = `${30 * (1 - nearTop)}px`;
    sheet.style.borderRadius = `${28 * nearTop}px ${28 * nearTop}px ${24 * e}px ${24 * e}px`;
    mini.style.height = `${MINI_H * e}px`;
    mini.style.opacity = e;
    wrap.style.opacity = 1 - e;
    wrap.style.visibility = e > 0.97 ? 'hidden' : 'visible';
    pill.style.top = `${-18 + 30 * (1 - nearTop)}px`;
    column.style.bottom = `${10 * e}px`;
    placeHandle();
  }

  function drawMap() {
    if (top < 4 || !W) return;
    const [azimuth, altitude] = dateRow.sun[slot];
    const v = viewCentreY();
    const left = cx - (W * zoom) / 2, right = cx + (W * zoom) / 2;
    const north = cy + v * zoom, south = cy - (H - v) * zoom;

    shadowCtx.globalCompositeOperation = 'source-over';
    shadowCtx.clearRect(0, 0, W, H);
    shadowCtx.fillStyle = '#000';
    if (altitude <= 0.3) {
      shadowCtx.fillRect(0, 0, W, H);
    } else {
      const perMetre = 1 / Math.tan((altitude * Math.PI) / 180);
      const dx = -Math.sin((azimuth * Math.PI) / 180), dy = -Math.cos((azimuth * Math.PI) / 180);
      const reach = MAX_SHADOW_M + 10;
      for (const b of BLOCKS) {
        if (b.x1 < left - reach || b.x0 > right + reach || b.y1 < south - reach || b.y0 > north + reach) continue;
        const length = Math.min(b.height * perMetre, MAX_SHADOW_M), ex = dx * length, ey = dy * length, r = b.ring;
        for (let j = 0; j < r.length; j++) {
          const a = r[j], c = r[(j + 1) % r.length];
          shadowCtx.beginPath();
          shadowCtx.moveTo(px(a[0]), py(a[1]));
          shadowCtx.lineTo(px(c[0]), py(c[1]));
          shadowCtx.lineTo(px(c[0] + ex), py(c[1] + ey));
          shadowCtx.lineTo(px(a[0] + ex), py(a[1] + ey));
          shadowCtx.closePath();
          shadowCtx.fill();
        }
        tracePolygon(shadowCtx, r, ex, ey);
        shadowCtx.fill();
      }
    }
    shadowCtx.globalCompositeOperation = 'source-in';
    shadowCtx.fillStyle = P.shade;
    shadowCtx.fillRect(0, 0, W, H);

    ctx.fillStyle = P.ground;
    ctx.fillRect(0, 0, W, H);
    ctx.drawImage(shadowCanvas, 0, 0, W, H);
    drawWater();
    drawRoads(left, right, south, north);
    ctx.fillStyle = P.bldg;
    for (const b of BLOCKS) {
      if (b.x1 < left || b.x0 > right || b.y1 < south || b.y0 > north) continue;
      tracePolygon(ctx, b.ring, 0, 0);
      ctx.fill();
    }
    for (const b of BARS) if (b !== selected) drawDot(b, false);
    drawDot(selected, true);

    const dotX = px(selected.x), dotY = py(selected.y);
    ctx.font = '800 13px Nunito, system-ui';
    const labelW = ctx.measureText(selected.n).width + 16;
    const labelX = clamp(dotX - labelW / 2, 6, W - labelW - 6);
    const labelY = dotY - 40 < 8 ? dotY + 16 : dotY - 40;
    ctx.fillStyle = P.ink;
    ctx.beginPath();
    ctx.roundRect(labelX, labelY, labelW, 24, 6);
    ctx.fill();
    ctx.fillStyle = P.sheet;
    ctx.textBaseline = 'middle';
    ctx.textAlign = 'center';
    ctx.fillText(selected.n, labelX + labelW / 2, labelY + 12.5);
  }

  function drawWater() {
    ctx.fillStyle = P.water;
    ctx.beginPath();
    for (const rings of WATER) {
      for (const ring of rings) {
        ring.forEach((p, j) => { if (j) ctx.lineTo(px(p[0]), py(p[1])); else ctx.moveTo(px(p[0]), py(p[1])); });
        ctx.closePath();
      }
    }
    ctx.fill('evenodd');
  }

  // Translucent, so streets stay visible in both sun and shade.
  function drawRoads(left, right, south, north) {
    ctx.save();
    ctx.lineCap = ctx.lineJoin = 'round';
    ctx.strokeStyle = P.bldg;
    ctx.globalAlpha = 0.6;
    for (const width of ROAD_WIDTHS) {
      ctx.lineWidth = Math.max(width / zoom, MIN_ROAD_PX[width]);
      ctx.beginPath();
      for (const r of ROADS) {
        if (r.width !== width || r.x1 < left || r.x0 > right || r.y1 < south || r.y0 > north) continue;
        r.line.forEach((p, j) => { if (j) ctx.lineTo(px(p[0]), py(p[1])); else ctx.moveTo(px(p[0]), py(p[1])); });
      }
      ctx.stroke();
    }
    ctx.restore();
  }

  function tracePolygon(target, ring, ex, ey) {
    target.beginPath();
    ring.forEach((p, j) => {
      const X = px(p[0] + ex), Y = py(p[1] + ey);
      if (j) target.lineTo(X, Y); else target.moveTo(X, Y);
    });
    target.closePath();
  }

  function drawDot(b, isSelected) {
    const X = px(b.x), Y = py(b.y);
    if (X < -20 || X > W + 20 || Y < -20 || Y > H + 20) return;
    const sunny = isSunny(b, slot);
    ctx.beginPath();
    ctx.arc(X, Y, isSelected ? 10 : sunny ? 8 : 6, 0, 7);
    ctx.fillStyle = sunny ? P.sun : isOpen(b, slot) ? P.dot : '#FFFFFF';
    ctx.fill();
    ctx.lineWidth = isSelected ? 3 : 2;
    ctx.strokeStyle = '#FFFFFF';
    ctx.stroke();
  }

  function rowHtml(b) {
    const next = nextSun(b, slot);
    const note = hours(b) === null ? 'closed'
      : isSunny(b, slot) ? `until ${fmt(SLOTS[slot + sunnyRun(b, slot) - 1] + 30)}`
      : next >= 0 ? `from ${fmt(SLOTS[next])}` : 'no sun';
    const cells = SLOTS.map((_, j) => {
      if (!isOpen(b, j)) return '<i></i>';
      const past = j < slot ? ' past' : '';
      if (!isSunny(b, j)) return `<i class="shade${past}"></i>`;
      const first = j === 0 || !isSunny(b, j - 1) ? ' first' : '';
      const last = j === N - 1 || !isSunny(b, j + 1) ? ' last' : '';
      return `<i class="sun${first}${last}${past}" style="--f:${dateRow.s[b.id][j]}"></i>`;
    }).join('');
    return `<div class="row${b === selected ? ' on' : ''}" data-id="${b.id}"><div class="title"><span>${esc(b.n)}</span><em>${note}</em></div><div class="strip">${cells}</div></div>`;
  }
  function renderList() {
    list.innerHTML = order.map(rowHtml).join('');
    mini.innerHTML = rowHtml(selected);
  }

  function renderLabels() {
    const count = BARS.filter((b) => isSunny(b, slot)).length;
    countLabel.textContent = `${count} in the sun`;
    pill.textContent = picking ? shortDate(dateOf(doy)) : fmt(SLOTS[slot]);
    dateButton.textContent = picking ? 'Done' : `${longDate(dateOf(doy))} ▾`;
    dateButton.classList.toggle('done', picking);
    hrow.classList.toggle('picking', picking);
    todayButton.style.display = picking ? '' : 'none';
    todayButton.disabled = doy === TODAY;
    placeHandle();
  }

  function renderTrack() {
    track.classList.toggle('year', picking);
    track.innerHTML = picking
      ? `<canvas class="ribbon" width="${Math.round(track.clientWidth * dpr)}" height="${36 * dpr}"></canvas><div class="seasons"></div><div class="marks"></div>`
      : HOUR_LABELS;
    drawRibbon();
  }

  // The ribbon's colour is the season and its height is that date's peak sun.
  function drawRibbon() {
    if (!picking) return;
    const ribbon = $('.ribbon');
    if (!ribbon) return;
    const width = ribbon.width, height = ribbon.height, bandH = 30 * dpr, g = ribbon.getContext('2d');
    const halfCss = track.clientWidth / 2;
    g.clearRect(0, 0, width, height);
    for (let p = 0; p < width; p++) {
      const day = wrapFloat(lensCentre + lensDays((2 * (p + 0.5)) / width - 1));
      const h = (14 + (peakAt(day) / 53.3) * 16) * dpr;
      g.fillStyle = seasonColour(day);
      g.fillRect(p, bandH - h, 1, h);
    }
    const centre = Math.round(lensCentre);
    g.fillStyle = '#8A8296';
    for (let k = -16; k <= 16; k++) {
      const n = centre + k;
      const isMonday = dateOf(wrapDay(n)).getDay() === 1;
      g.fillRect(((1 + lensPos(n - lensCentre)) / 2) * width - 0.6 * dpr, bandH + dpr, 1.2 * dpr, (isMonday ? 5 : 2.5) * dpr);
    }

    const cuts = [-182, ...SEASON_START.map((c) => dayDiff(c, lensCentre)).filter((c) => c > -182 && c < 182).sort((a, b) => a - b), 182];
    let seasons = '';
    for (let k = 0; k < cuts.length - 1; k++) {
      const a = lensPos(cuts[k]), b = lensPos(cuts[k + 1]);
      if ((b - a) * halfCss < 62) continue;
      const q = seasonOf(wrapDay(lensCentre + (cuts[k] + cuts[k + 1]) / 2));
      seasons += `<span style="left:${((a + b) / 2 + 1) * 50}%">${SEASON_ICON[q]}${SEASON_NAME[q]}</span>`;
    }
    $('.seasons').innerHTML = seasons;

    const placed = [];
    let marks = '';
    const put = (days, text, w) => {
      const x = (lensPos(days) + 1) * halfCss;
      if (x < w / 2 || x > 2 * halfCss - w / 2 || placed.some(([px2, w2]) => Math.abs(px2 - x) < (w2 + w) / 2 + 6)) return;
      placed.push([x, w]);
      marks += `<span style="left:${(x / (2 * halfCss)) * 100}%">${text}</span>`;
    };
    [-7, 7].forEach((q) => put(q, shortDate(dateOf(wrapDay(centre + q))), 40));
    MONTHS.map((m, k) => [dayDiff(doyOf(new Date(YEAR, k, 1)), lensCentre), m])
      .sort((a, b) => Math.abs(a[0]) - Math.abs(b[0]))
      .forEach(([days, m]) => put(days, m, 24));
    $('.marks').innerHTML = marks;
  }

  // One animation loop eases colours, sheet, map and lens together.
  function frame() {
    raf = 0;
    let moving = false;
    const target = paletteAt(dateRow, slot);
    let delta = 0;
    colours.forEach((c, k) => c.forEach((x, q) => {
      const e = target[k][q] - x;
      delta += Math.abs(e);
      c[q] = x + e * (still ? 1 : 0.13);
    }));
    if (delta > 0.006) moving = true; else colours = target.map((c) => [...c]);
    applyColours();

    if (picking) {
      const e = dayDiff(rest, lensCentre);
      if (Math.abs(e) > 0.08) { lensCentre = wrapFloat(lensCentre + e * (still ? 1 : 0.2)); drawRibbon(); moving = true; }
      else if (lensCentre !== rest) { lensCentre = rest; drawRibbon(); }
    }

    const et = topTarget - top;
    if (Math.abs(et) > 0.5) { top += et * (still ? 1 : 0.25); moving = true; } else top = topTarget;
    shapeSheet();

    const ez = zoomTarget - zoom;
    if (Math.abs(ez) > 0.005) { zoom += ez * (still ? 1 : 0.25); moving = true; } else zoom = zoomTarget;

    cxTarget = clampCx(cxTarget);
    cyTarget = clampCy(cyTarget);
    const ex = cxTarget - cx, ey = cyTarget - cy;
    if (Math.abs(ex) + Math.abs(ey) > 1) { cx += ex * (still ? 1 : 0.22); cy += ey * (still ? 1 : 0.22); moving = true; } else { cx = cxTarget; cy = cyTarget; }

    drawMap();
    if (moving) raf = requestAnimationFrame(frame);
  }
  const requestFrame = () => { if (!raf) raf = requestAnimationFrame(frame); };

  function setSlot(next) {
    next = clamp(next, 0, N - 1);
    if (next === slot) return;
    slot = next;
    renderLabels();
    renderList();
    requestFrame();
  }
  function setDay(next) {
    next = wrapDay(next);
    if (next === doy) return;
    doy = next;
    syncDate();
    order = ranked();
    renderLabels();
    renderList();
    requestFrame();
  }
  // Rows only re-sort on release, so they don't jump under a dragging finger.
  function settle() {
    if (picking) { rest = doy; requestFrame(); return; }
    order = ranked();
    renderList();
  }
  function selectBar(b) {
    selected = b;
    cxTarget = clampCx(b.x);
    cyTarget = clampCy(b.y);
    renderList();
    requestFrame();
  }
  function setPicking(on) {
    const wasFullMap = Math.abs(topTarget - MAP_TOP) < 1;
    picking = on;
    rest = lensCentre = doy;
    MAP_TOP = H - 12 - cardHeight();
    if (wasFullMap) topTarget = MAP_TOP;
    renderTrack();
    renderLabels();
    requestFrame();
  }

  // --- Sheet sizing ---------------------------------------------------------
  const clampTop = (v) => clamp(v, 0, MAP_TOP);
  const snapTop = (v) => (v < SNAP_PX ? 0 : v > MAP_TOP - SNAP_PX ? MAP_TOP : v);
  function resizeTo(gesture, dy) { moveSheet(gesture, clampTop(gesture.top + dy)); }
  function moveSheet(gesture, raw) {
    const snapped = snapTop(raw);
    const isSnapped = snapped !== raw;
    if (isSnapped && !gesture.snapped && navigator.vibrate) navigator.vibrate(8);
    gesture.snapped = isSnapped;
    topTarget = snapped;
    if (!isSnapped && Math.abs(top - raw) < 12) top = raw;
    requestFrame();
  }
  function cycleSize() {
    const stops = [0, MID, MAP_TOP];
    const k = stops.findIndex((q) => q > topTarget + 1);
    topTarget = stops[k < 0 ? 0 : k];
    requestFrame();
  }

  // --- Gestures -------------------------------------------------------------
  const timeFromTrack = (p) => setSlot(Math.floor(p * N));
  const valueFromTrack = (p) => (picking ? setDay(rest + Math.round(lensDays(2 * p - 1))) : timeFromTrack(p));
  const ratioIn = (el, e, pad) => {
    const r = el.getBoundingClientRect();
    return clamp((e.clientX - r.left - pad) / (r.width - 2 * pad), 0, 1);
  };

  // The whole table is one bottom sheet: sideways scrubs, up and down resizes
  // it, and once the table is full-screen the same drag scrolls the bars.
  let sheetGesture = null, suppressRowTap = false, coastFrame = 0;

  function coast(velocity) {
    let last = performance.now();
    const step = (now) => {
      const dt = now - last;
      last = now;
      list.scrollTop += velocity * dt;
      velocity *= Math.exp(-dt / 325);
      coastFrame = Math.abs(velocity) > 0.02 ? requestAnimationFrame(step) : 0;
    };
    coastFrame = requestAnimationFrame(step);
  }

  function dragVertically(g, step) {
    let scrolled = false;
    if (step < 0) {
      if (topTarget > 0) {
        g.pos = Math.max(0, g.pos + step);
        moveSheet(g, g.pos);
        if (topTarget === 0) g.pos = 0;
      } else if (g.inList) {
        list.scrollTop -= step;
        scrolled = true;
      }
      return scrolled;
    }
    let rest = step;
    if (g.inList && list.scrollTop > 0) {
      const used = Math.min(rest, list.scrollTop);
      list.scrollTop -= used;
      rest -= used;
      scrolled = true;
    }
    if (rest > 0) {
      g.pos = Math.min(MAP_TOP, g.pos + rest);
      moveSheet(g, g.pos);
    }
    return scrolled;
  }

  sheet.addEventListener('pointerdown', (e) => {
    if (!e.isPrimary || e.target.closest('button')) return;
    cancelAnimationFrame(coastFrame);
    suppressRowTap = false;
    sheetGesture = {
      id: e.pointerId, x: e.clientX, y: e.clientY, lastY: e.clientY, lastTime: e.timeStamp,
      axis: null, inList: !!e.target.closest('.wrap'), inTrack: !!e.target.closest('.track'),
      pos: topTarget, snapped: topTarget < 1 || topTarget > MAP_TOP - 1, velocity: 0, scrolling: false,
    };
  });
  sheet.addEventListener('pointermove', (e) => {
    const g = sheetGesture;
    if (!g || e.pointerId !== g.id) return;
    if (!g.axis) {
      const dx = e.clientX - g.x, dy = e.clientY - g.y;
      if (Math.hypot(dx, dy) <= 6) return;
      g.axis = Math.abs(dx) > Math.abs(dy) ? 'x' : 'y';
      suppressRowTap = true;
      sheet.setPointerCapture(e.pointerId);
    }
    if (g.axis === 'x') {
      if (g.inTrack) valueFromTrack(ratioIn(track, e, 0)); else timeFromTrack(ratioIn(wrap, e, 16));
      return;
    }
    const step = e.clientY - g.lastY;
    const dt = Math.max(e.timeStamp - g.lastTime, 1);
    g.scrolling = dragVertically(g, step);
    g.velocity = 0.7 * (-step / dt) + 0.3 * g.velocity;
    g.lastY = e.clientY;
    g.lastTime = e.timeStamp;
  });
  sheet.addEventListener('pointerup', (e) => {
    const g = sheetGesture;
    if (!g || e.pointerId !== g.id) return;
    sheetGesture = null;
    if (g.axis === 'x') settle();
    else if (g.axis === 'y' && g.scrolling && e.timeStamp - g.lastTime < 80) coast(g.velocity);
    else if (!g.axis && g.inTrack) { valueFromTrack(ratioIn(track, e, 0)); settle(); }
  });
  sheet.addEventListener('pointercancel', () => { sheetGesture = null; });

  let pillGesture = null;
  pill.addEventListener('pointerdown', (e) => {
    pillGesture = { x: e.clientX, y: e.clientY, top, slot, axis: null, snapped: top < 1 || top > MAP_TOP - 1, u0: picking ? lensPos(dayDiff(doy, lensCentre)) : 0 };
    pill.setPointerCapture(e.pointerId);
  });
  pill.addEventListener('pointermove', (e) => {
    const g = pillGesture;
    if (!g) return;
    const dx = e.clientX - g.x, dy = e.clientY - g.y;
    if (!g.axis && Math.hypot(dx, dy) > 6) g.axis = Math.abs(dx) > Math.abs(dy) ? 'x' : 'y';
    if (g.axis === 'y') { resizeTo(g, dy); return; }
    if (g.axis !== 'x') return;
    const inner = sheet.clientWidth - 32;
    if (picking) setDay(rest + Math.round(lensDays(clamp(g.u0 + dx / (inner / 2), -1, 1))));
    else setSlot(g.slot + Math.round(dx / (inner / N)));
  });
  pill.addEventListener('pointerup', () => {
    if (pillGesture) { if (!pillGesture.axis) cycleSize(); else if (pillGesture.axis === 'x') settle(); }
    pillGesture = null;
  });
  pill.addEventListener('pointercancel', () => { pillGesture = null; });
  pill.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
      e.preventDefault();
      const step = e.key === 'ArrowLeft' ? -1 : 1;
      if (picking) setDay(doy + step); else setSlot(slot + step);
      settle();
    } else if (e.key === 'ArrowUp' || e.key === 'ArrowDown') {
      e.preventDefault();
      const d = e.key === 'ArrowUp' ? -40 : 40;
      topTarget = snapTop(clampTop(topTarget < 1 && d > 0 ? SNAP_PX + d : topTarget > MAP_TOP - 1 && d < 0 ? MAP_TOP - SNAP_PX + d : topTarget + d));
      requestFrame();
    }
  });

  dateButton.addEventListener('click', () => setPicking(!picking));
  todayButton.addEventListener('click', () => { setDay(TODAY); settle(); });

  list.addEventListener('click', (e) => {
    if (suppressRowTap) { suppressRowTap = false; return; }
    const row = e.target.closest('.row');
    if (row) selectBar(BARS.find((b) => b.id === row.dataset.id));
  });

  // Keeps the map point under (sx, sy) in place while the zoom changes.
  function zoomAround(sx, sy, next) {
    next = clamp(next, MIN_ZOOM, MAX_ZOOM);
    const mx = cx + (sx - W / 2) * zoom, my = cy + (viewCentreY() - sy) * zoom;
    zoom = zoomTarget = next;
    cx = cxTarget = clampCx(mx - (sx - W / 2) * next);
    cy = cyTarget = clampCy(my - (viewCentreY() - sy) * next);
    requestFrame();
  }

  const pointers = new Map();
  const canvasPoint = (e) => { const r = canvas.getBoundingClientRect(); return { x: e.clientX - r.left, y: e.clientY - r.top }; };
  const pinchOf = () => {
    const [a, b] = [...pointers.values()];
    return { distance: Math.hypot(a.x - b.x, a.y - b.y), x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
  };
  let panGesture = null, pinchGesture = null, lastTap = null;
  const startPan = (p, moved) => { panGesture = { x: p.x, y: p.y, cx, cy, moved }; };

  canvas.addEventListener('pointerdown', (e) => {
    canvas.setPointerCapture(e.pointerId);
    const p = canvasPoint(e);
    pointers.set(e.pointerId, p);
    if (pointers.size === 2) {
      pinchGesture = { ...pinchOf(), zoom };
      panGesture = null;
    } else if (pointers.size === 1) {
      startPan(p, false);
    }
  });
  canvas.addEventListener('pointermove', (e) => {
    if (!pointers.has(e.pointerId)) return;
    const p = canvasPoint(e);
    pointers.set(e.pointerId, p);
    if (pinchGesture && pointers.size >= 2) {
      const now = pinchOf();
      zoomAround(now.x, now.y, pinchGesture.zoom * (pinchGesture.distance / Math.max(now.distance, 1)));
      return;
    }
    const g = panGesture;
    if (!g) return;
    const dx = p.x - g.x, dy = p.y - g.y;
    if (Math.abs(dx) + Math.abs(dy) > 5) g.moved = true;
    if (g.moved) {
      cx = cxTarget = clampCx(g.cx - dx * zoom);
      cy = cyTarget = clampCy(g.cy + dy * zoom);
      requestFrame();
    }
  });
  const endPointer = (e) => {
    if (!pointers.has(e.pointerId)) return;
    const p = pointers.get(e.pointerId);
    pointers.delete(e.pointerId);
    if (pinchGesture) {
      if (pointers.size < 2) pinchGesture = null;
      if (pointers.size === 1) startPan([...pointers.values()][0], true);
      return;
    }
    const g = panGesture;
    panGesture = null;
    if (e.type !== 'pointerup' || !g || g.moved) return;
    const now = performance.now();
    if (lastTap && now - lastTap.time < 300 && Math.hypot(p.x - lastTap.x, p.y - lastTap.y) < 30) {
      lastTap = null;
      // Double tap steps closer, then back out once fully zoomed in.
      const next = zoomTarget <= MIN_ZOOM + 0.01 ? DEFAULT_ZOOM : Math.max(MIN_ZOOM, zoomTarget / 2);
      const mx = cx + (p.x - W / 2) * zoom, my = cy + (viewCentreY() - p.y) * zoom;
      zoomTarget = next;
      cxTarget = mx - (p.x - W / 2) * next;
      cyTarget = my - (viewCentreY() - p.y) * next;
      requestFrame();
      return;
    }
    lastTap = { time: now, x: p.x, y: p.y };
    let best = null, bestDist = 24 * 24;
    for (const b of BARS) {
      const q = (px(b.x) - p.x) ** 2 + (py(b.y) - p.y) ** 2;
      if (q < bestDist) { bestDist = q; best = b; }
    }
    if (best) {
      selectBar(best);
      const row = list.children[order.indexOf(best)];
      if (row) list.scrollTop = row.offsetTop - 8;
    }
  };
  canvas.addEventListener('pointerup', endPointer);
  canvas.addEventListener('pointercancel', endPointer);
  canvas.addEventListener('wheel', (e) => {
    e.preventDefault();
    const p = canvasPoint(e);
    zoomAround(p.x, p.y, zoom * Math.exp(e.deltaY * 0.0015));
  }, { passive: false });

  // --- Layout ---------------------------------------------------------------
  function layout() {
    const wasFullMap = H > 0 && Math.abs(topTarget - MAP_TOP) < 1;
    const wasFullTable = H > 0 && topTarget < 1;
    const ratio = H > 0 ? topTarget / H : null;
    W = app.clientWidth;
    H = app.clientHeight;
    MID = Math.round(H * 0.49);
    MAP_TOP = H - 12 - cardHeight();
    topTarget = wasFullMap ? MAP_TOP : wasFullTable ? 0 : ratio === null ? MID : clampTop(Math.round(ratio * H));
    top = topTarget;
    for (const c of [canvas, shadowCanvas]) { c.width = W * dpr; c.height = H * dpr; }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    shadowCtx.setTransform(dpr, 0, 0, dpr, 0, 0);
    renderTrack();
    cx = cxTarget = clampCx(selected.x);
    cy = cyTarget = clampCy(selected.y);
    shapeSheet();
    drawMap();
  }

  applyColours();
  renderLabels();
  renderList();
  layout();
  new ResizeObserver(() => { if (app.clientWidth !== W || app.clientHeight !== H) layout(); }).observe(app);
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(drawMap);
})();
