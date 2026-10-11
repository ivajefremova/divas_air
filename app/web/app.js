// Divas Air web map. Plays replay bundles (contract.ReplayManifest + ReplayFrame lines, see
// src/divas_air/contract.py) like a live feed: one frame every 5 s, positions eased in between.
// Scenarios come from the simulated library (replay_fake/index.json); Matteo's real bundle (replay/)
// is listed first when it exists. Camera checks and camera feeds are SIMULATED (cameras.jsonl).

const CFG = Object.assign({
  scenarioIndex: '../../data/processed/demo/replay_fake/index.json',
  realBundle: '../../data/processed/demo/replay/',
  layers: 'data/',
  localTiles: '/tiles/{z}/{x}/{y}.jpg',
  onlinePhoto: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
  photoBounds: [12.2027, 41.7710, 12.2941, 41.8512],
  center: [12.2505, 41.7985],
  zoom: 14.2,
  publicUrl: null,
  qr: 'qr.png',
}, window.DIVAS_CFG || {});
const TRAIL_FRAMES = 10, HISTORY_FRAMES = 60, JUMP_M = 150, CAMERA_DELAY_MS = 1800;

const SEV_RANK = { critical: 4, high: 3, medium: 2, low: 1, none: 0 };
const CAUSE_TEXT = {
  plausible: 'Plausible', degraded: 'Degraded data', technical_error: 'Technical error', gnss_anomaly: 'GNSS anomaly',
  possible_interference: 'Possible interference', possible_spoofing: 'Possible spoofing', behavioral_anomaly: 'Unusual behaviour (data sound)',
};
const CLASS_NAME = {
  baggage_tractor: 'Tractor', bus: 'Bus', fuel_truck: 'Fuel truck', catering_truck: 'Catering', sar_vehicle: 'SAR', follow_me: 'Follow-me',
  widebody: 'Widebody', narrowbody: 'Narrowbody', regional: 'Regional', turboprop: 'Turboprop', bizjet: 'Business jet', light: 'Light aircraft',
  helicopter: 'Helicopter', other: 'Aircraft',
};
const HEADLINE = {
  trusted: ['All good', 'Position and movement are as expected.'],
  caution: ['Reduced accuracy', 'The position may be off by a few metres.'],
  real_event: ['Real event', 'The data is sound and the movement is unusual.'],
  data_fault: ['Data fault', "Don't trust this position."],
  silent_risk: ['Position unreliable', "Movement looks normal, but the data isn't."],
};
const ISSUE_WORD = { caution: 'Reduced accuracy', real_event: 'Unusual movement', data_fault: 'Position unreliable', silent_risk: 'Position unreliable' };
const COLORS = { blue: '#2f6bff', pink: '#ff4fa3', red: '#e5383b', amber: '#f5a524', ink: '#18203a', purple: '#8b5cf6' };
const TYPE_COLOR = { bus: '#0d9488', fuel_truck: '#7c3aed', catering_truck: '#65a30d', baggage_tractor: '#64748b', follow_me: '#0ea5e9', sar_vehicle: '#1f2937' };
const TYPE_KEY = [['bus', 'Bus'], ['fuel_truck', 'Fuel truck'], ['catering_truck', 'Catering'], ['baggage_tractor', 'Tractor'], ['follow_me', 'Follow-me'], ['sar_vehicle', 'SAR']];

const PLANE = '<svg viewBox="0 0 24 24"><path class="shape" d="M12 1.5c.9 0 1.5.8 1.5 1.8V9l8 4.8v2.2l-8-2.4v5.1l2.4 1.8v1.7L12 21.2l-3.9 1v-1.7l2.4-1.8v-5.1l-8 2.4v-2.2l8-4.8V3.3c0-1 .6-1.8 1.5-1.8z"/></svg>';
const WIN = (x, y, w, h) => `<rect class="detail" x="${x}" y="${y}" width="${w}" height="${h}" rx="1"/>`;
const ICONS = {  // top-down, front at the top, roughly to scale
  bus: `<svg viewBox="0 0 12 32" width="12" height="32"><rect class="shape" x=".75" y=".75" width="10.5" height="30.5" rx="2.6"/>
    ${WIN(2.4, 2.2, 7.2, 3.2)}<rect class="detail" x="2.4" y="8.5" width="7.2" height="1.4" rx=".7"/><rect class="detail" x="2.4" y="17" width="7.2" height="1.4" rx=".7"/><rect class="detail" x="2.4" y="25.5" width="7.2" height="1.4" rx=".7"/></svg>`,
  fuel_truck: `<svg viewBox="0 0 13 29" width="13" height="29"><rect class="shape" x="1.5" y=".75" width="10" height="7.5" rx="2.2"/>
    ${WIN(3, 1.9, 7, 2.4)}<rect class="shape" x=".75" y="9.6" width="11.5" height="18.65" rx="5.75"/><path class="band" d="M1.5 15.5h10M1.5 22.3h10"/></svg>`,
  catering_truck: `<svg viewBox="0 0 15 27" width="15" height="27"><rect class="shape" x="2.5" y=".75" width="10" height="7.5" rx="2.2"/>
    ${WIN(4, 1.9, 7, 2.4)}<rect class="shape" x=".75" y="9.4" width="13.5" height="16.85" rx="1.4"/><path class="band" d="M3 12.5l9 10.5M12 12.5L3 23"/></svg>`,
  baggage_tractor: `<svg viewBox="0 0 12 33" width="12" height="33"><path class="link" d="M6 10v3M6 21.5v3"/>
    <rect class="shape" x="1" y=".75" width="10" height="9.25" rx="2.8"/>${WIN(2.6, 2, 6.8, 2.6)}
    <rect class="shape" x="1.6" y="13" width="8.8" height="8.5" rx="1.6"/><rect class="shape" x="1.6" y="24.5" width="8.8" height="7.75" rx="1.6"/></svg>`,
  follow_me: `<svg viewBox="0 0 11 19" width="11" height="19"><rect class="shape" x=".75" y=".75" width="9.5" height="17.5" rx="3.6"/>
    ${WIN(2.2, 3.4, 6.6, 2.8)}<rect class="beacon" x="1.8" y="7.6" width="7.4" height="2.4" rx="1.2"/>${WIN(2.2, 12.6, 6.6, 2.4)}</svg>`,
  sar_vehicle: `<svg viewBox="0 0 14 29" width="14" height="29"><rect class="shape" x=".75" y=".75" width="12.5" height="27.5" rx="2.6"/>
    ${WIN(2.4, 2.2, 9.2, 3)}<rect class="beacon" x="2" y="6.6" width="10" height="2.2" rx="1.1"/><path class="band" d="M7 13v10M2 18h10"/></svg>`,
  vehicle: `<svg viewBox="0 0 16 20" width="15" height="19"><path class="shape" d="M8 .8l5.2 5.2H13V16a3 3 0 01-3 3H6a3 3 0 01-3-3V6h-.2L8 .8z"/></svg>`,
};
const iconFor = (v) => (v.domain === 'aircraft' ? PLANE : ICONS[v.asset_class] || ICONS.vehicle);
const CAM_SVG = (c = '#fff') => `<svg viewBox="0 0 24 24" fill="none" stroke="${c}" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 7h12l2 3-2 3H3z"/><path d="M17 9l4-2v6l-4-2"/><path d="M7 13v4H4"/></svg>`;

// ---- state --------------------------------------------------------------------------------

const S = {
  scenarios: [], cur: null, bundle: null, cache: new Map(),
  t: 0, idx: -1, playing: true, view: 'photo', show: { aircraft: true, vehicles: true, cameras: false },
  sel: null, more: false, pos: new Map(), markers: new Map(), fcLabels: [], camMarkers: new Map(), seenMarkers: [],
  firstSeen: new Map(), cameras: [], live: null, photo: null, issues: [],
};
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const hhmm = (t) => new Date(t * 1000).toISOString().slice(11, 19);
const forTime = (s) => (s < 60 ? `${Math.max(0, Math.round(s))} s` : `${Math.floor(s / 60)} min ${String(Math.round(s % 60)).padStart(2, '0')} s`);
const nameOf = (v) => v.callsign || `${CLASS_NAME[v.asset_class] || 'Vehicle'} ${(v.asset_id.match(/\d+/) || [v.asset_id])[0]}`;
const quad = (v) => (v.quadrant === 'trusted' && v.trust_state === 'caution' ? 'caution' : v.quadrant);
const shown = (v) => (v.domain === 'aircraft' ? S.show.aircraft : S.show.vehicles);
const isIssue = (v) => v.action.code !== 'none';
const isPhone = () => window.matchMedia('(max-width: 760px)').matches;
const mPerDeg = (lat) => [111320 * Math.cos(lat * Math.PI / 180), 110540];
const distM = (a, b) => { const [kx, ky] = mPerDeg(a.lat); return Math.hypot((a.lon - b.lon) * kx, (a.lat - b.lat) * ky); };
const bearing = (a, b) => { const [kx, ky] = mPerDeg(a.lat); return (Math.atan2((b.lon - a.lon) * kx, (b.lat - a.lat) * ky) * 180 / Math.PI + 360) % 360; };
const empty = () => ({ type: 'FeatureCollection', features: [] });

// ---- data ---------------------------------------------------------------------------------

async function getJson(url) { const r = await fetch(url).catch(() => null); return r && r.ok ? r.json() : null; }
async function getLines(url) {
  const r = await fetch(url).catch(() => null);
  if (!r || !r.ok) return null;
  return (await r.text()).split('\n').filter(Boolean).map((l) => JSON.parse(l));
}

async function loadIndex() {
  const list = [];
  const real = await getJson(CFG.realBundle + 'manifest.json');
  if (real) list.push({ id: 'real', title: 'Live replay (module 6)', category: 'Replay bundle', story: 'The pipeline\'s own replay of the scripted demo scene.',
    base: CFG.realBundle, t_start: real.t_start, onset_t: real.events[0]?.t_start ?? real.t_start, focus: real.events[0]?.track_ids || [], real: true });
  const idx = await getJson(CFG.scenarioIndex);
  const base = CFG.scenarioIndex.replace(/index\.json$/, '');
  for (const sc of idx?.scenarios || []) list.push({ ...sc, base: base + sc.dir + '/' });
  if (!list.length) throw new Error('No scenarios found. Run scripts/make_fake_replay.py.');
  return list;
}

async function loadBundle(sc) {
  if (S.cache.has(sc.id)) return S.cache.get(sc.id);
  const manifest = await getJson(sc.base + 'manifest.json');
  const [frames, cams, halos] = await Promise.all([getLines(sc.base + manifest.frames_file), getLines(sc.base + 'cameras.jsonl'), getJson(sc.base + 'static_halos.geojson')]);
  const b = { manifest, frames, cams, halos, byTrack: frames.map((f) => new Map(f.verdicts.map((v) => [v.track_id, v]))) };
  S.cache.set(sc.id, b);
  return b;
}

const loadLayer = (name) => getJson(CFG.layers + name + '.geojson').then((d) => d || empty());

async function photoTiles() {
  if (!CFG.localTiles) return { tiles: [CFG.onlinePhoto], maxzoom: 19, attribution: 'Imagery © Esri' };
  const z = 16, n = 2 ** z, [lon, lat] = CFG.center;
  const x = Math.floor((lon + 180) / 360 * n), y = Math.floor((1 - Math.asinh(Math.tan(lat * Math.PI / 180)) / Math.PI) / 2 * n);
  const url = CFG.localTiles.replace('{z}', z).replace('{x}', x).replace('{y}', y);
  const ok = await fetch(url, { method: 'HEAD' }).then((r) => r.ok && (r.headers.get('content-type') || '').startsWith('image')).catch(() => false);
  return ok ? { tiles: [CFG.localTiles], minzoom: 13, maxzoom: 19, bounds: CFG.photoBounds, attribution: 'Orthophoto 2023 (AGEA)' }
    : { tiles: [CFG.onlinePhoto], maxzoom: 19, attribution: 'Imagery © Esri' };
}

// ---- map ----------------------------------------------------------------------------------

const map = new maplibregl.Map({
  container: 'map', style: { version: 8, sources: {}, layers: [{ id: 'bg', type: 'background', paint: { 'background-color': '#2b3040' } }] },
  center: CFG.center, zoom: isPhone() ? 13.4 : CFG.zoom, minZoom: 11.5, maxZoom: 19.5, maxPitch: 60,
  attributionControl: false, dragRotate: false, pitchWithRotate: false, touchPitch: false,
});
map.touchZoomRotate.disableRotation();
map.addControl(new maplibregl.AttributionControl({ compact: true }), 'bottom-right');
const iconScale = () => { const lo = isPhone() ? 0.95 : 1.3;
  document.documentElement.style.setProperty('--s', Math.min(2, Math.max(lo, lo + (map.getZoom() - 14.5) * 0.25)).toFixed(2)); };
map.on('zoom', iconScale);
iconScale();

// what each view shows (opacity factor per layer), and its own colours
const VIEWS = {
  photo: { label: 'Photo', bg: '#2b3040', pitch: 0, on: { photo: 1, 'rwy-line': 0.9, 'halo-static': 0.35 } },
  schematic: { label: 'Schematic', bg: '#eef1f7', pitch: 0, on: { aprons: 1, buildings: 1, 'rwy-fill': 1, 'rwy-line': 1, 'routes-service': 1, 'routes-taxi': 1, stands: 1, holding: 1, 'halo-static': 0.35 },
    paint: { 'rwy-fill': '#2c3352', buildings: '#cfd3de' } },
  traffic: { label: 'Traffic', bg: '#f1f3f8', pitch: 45, on: { aprons: 0.8, 'buildings-3d': 1, 'rwy-fill': 1, 'routes-taxi': 0.35, 'routes-service': 0.35 },
    paint: { 'rwy-fill': '#d9deea' } },
  gnss: { label: 'GNSS risk', bg: '#eceef5', pitch: 0, on: { aprons: 0.45, buildings: 0.5, 'rwy-fill': 0.3, 'routes-taxi': 0.25, 'routes-service': 0.25, 'halo-static': 1.5, 'halo-edge': 1 },
    paint: { 'rwy-fill': '#2c3352', buildings: '#cfd3de' } },
};
const OPACITY_PROP = { photo: 'raster-opacity', aprons: 'fill-opacity', buildings: 'fill-opacity', 'buildings-3d': 'fill-extrusion-opacity', 'rwy-fill': 'fill-opacity',
  'rwy-line': 'line-opacity', 'routes-service': 'line-opacity', 'routes-taxi': 'line-opacity', stands: 'circle-opacity', holding: 'circle-opacity',
  'halo-static': 'fill-opacity', 'halo-edge': 'line-opacity' };
const COLOR_PROP = { 'rwy-fill': 'fill-color', buildings: 'fill-color' };

function addLayers(L) {
  map.addSource('photo', { type: 'raster', tileSize: 256, ...S.photo });
  for (const k of ['aprons', 'buildings', 'runway_areas', 'routes', 'stands', 'holding_points']) map.addSource(k, { type: 'geojson', data: L[k] });
  for (const k of ['halos', 'risk', 'trails', 'cones']) map.addSource(k, { type: 'geojson', data: empty() });
  const zw = (a, b) => ['interpolate', ['linear'], ['zoom'], 13, a, 17.5, b];
  map.addLayer({ id: 'photo', type: 'raster', source: 'photo' });
  map.addLayer({ id: 'aprons', type: 'fill', source: 'aprons', paint: { 'fill-color': '#dde5f5' } });
  map.addLayer({ id: 'buildings', type: 'fill', source: 'buildings', paint: { 'fill-color': '#cfd3de', 'fill-outline-color': '#b9bfcd' } });
  map.addLayer({ id: 'rwy-fill', type: 'fill', source: 'runway_areas', paint: { 'fill-color': '#2c3352' } });
  map.addLayer({ id: 'rwy-line', type: 'line', source: 'runway_areas', paint: { 'line-color': '#ffffff', 'line-width': 1.8 } });
  map.addLayer({ id: 'routes-service', type: 'line', source: 'routes', filter: ['==', ['get', 'kind'], 'service_road'], layout: { 'line-cap': 'round' },
    paint: { 'line-color': '#9aa3b8', 'line-width': zw(0.8, 4) } });
  map.addLayer({ id: 'routes-taxi', type: 'line', source: 'routes', filter: ['==', ['get', 'kind'], 'taxiway'], layout: { 'line-cap': 'round' },
    paint: { 'line-color': '#3d7bff', 'line-width': zw(1.4, 7) } });
  map.addLayer({ id: 'stands', type: 'circle', source: 'stands', minzoom: 14.5, paint: { 'circle-radius': 3, 'circle-color': '#6b7390' } });
  map.addLayer({ id: 'holding', type: 'circle', source: 'holding_points', minzoom: 13.5,
    paint: { 'circle-radius': 4, 'circle-color': COLORS.red, 'circle-stroke-color': '#fff', 'circle-stroke-width': 1.5 } });
  map.addLayer({ id: 'buildings-3d', type: 'fill-extrusion', source: 'buildings',
    paint: { 'fill-extrusion-color': ['case', ['==', ['get', 'aeroway'], 'terminal'], '#b7c3dd', '#c9cede'], 'fill-extrusion-height': ['coalesce', ['get', 'h'], 8],
      'fill-extrusion-vertical-gradient': true } });
  map.addLayer({ id: 'halo-static', type: 'fill', source: 'halos', paint: { 'fill-color': COLORS.purple, 'fill-opacity': ['*', ['get', 'level'], 0.5] } });
  map.addLayer({ id: 'halo-edge', type: 'line', source: 'halos', filter: ['>=', ['get', 'level'], 0.5], paint: { 'line-color': '#6d3fe0', 'line-width': 1.2, 'line-dasharray': [2, 2] } });
  map.addLayer({ id: 'cones', type: 'fill', source: 'cones', paint: { 'fill-color': ['get', 'c'], 'fill-opacity': ['get', 'o'] } });
  map.addLayer({ id: 'risk-live', type: 'fill', source: 'risk', filter: ['==', ['get', 'kind'], 'live'], paint: { 'fill-color': COLORS.pink, 'fill-opacity': ['*', ['get', 'level'], 0.28] } });
  map.addLayer({ id: 'risk-live-edge', type: 'line', source: 'risk', filter: ['==', ['get', 'kind'], 'live'], paint: { 'line-color': '#e8368a', 'line-width': 3 } });
  map.addLayer({ id: 'trails', type: 'line', source: 'trails', layout: { 'line-cap': 'round' }, paint: { 'line-color': ['get', 'c'], 'line-opacity': ['get', 'o'], 'line-width': 3 } });
  map.addLayer({ id: 'risk-forecast', type: 'line', source: 'risk', filter: ['==', ['get', 'kind'], 'forecast'], layout: { 'line-cap': 'round' },
    paint: { 'line-color': '#e8368a', 'line-width': 3.5, 'line-dasharray': [1.5, 1.5] } });
  map.on('click', 'risk-live', (e) => { e.preventDefault(); const id = e.features[0].properties.area_alert_id; if (id) select({ kind: 'area', id }); });
  map.on('click', (e) => { if (!e.defaultPrevented && S.sel) select(null); });
  map.on('mouseenter', 'risk-live', () => (map.getCanvas().style.cursor = 'pointer'));
  map.on('mouseleave', 'risk-live', () => (map.getCanvas().style.cursor = ''));
}

function applyView(view) {
  const prev = S.view;
  S.view = view;
  const v = VIEWS[view];
  document.body.className = document.body.className.replace(/view-\w+/, '') + ` view-${view}`;
  map.setPaintProperty('bg', 'background-color', v.bg);
  for (const [id, prop] of Object.entries(OPACITY_PROP)) {
    const k = v.on[id];
    map.setLayoutProperty(id, 'visibility', k ? 'visible' : 'none');
    if (!k) continue;
    if (id === 'halo-static') map.setPaintProperty(id, prop, ['*', ['get', 'level'], 0.5 * k]);
    else if (id === 'buildings-3d') map.setPaintProperty(id, prop, 0.85);
    else map.setPaintProperty(id, prop, k);
  }
  for (const [id, prop] of Object.entries(COLOR_PROP)) if (v.paint?.[id]) map.setPaintProperty(id, prop, v.paint[id]);
  if (VIEWS[prev]?.pitch !== v.pitch || prev === view) map.easeTo({ pitch: v.pitch, duration: 600 });
  map.setPaintProperty('trails', 'line-width', view === 'photo' ? 3.5 : 3);
  renderViews();
  renderLegend();
}

// ---- markers ------------------------------------------------------------------------------

function markerFor(v) {
  let m = S.markers.get(v.track_id);
  if (m && m.cls === v.asset_class) return m;
  if (m) m.marker.remove();
  const wrap = document.createElement('div');
  wrap.innerHTML = `<div class="trk"><div class="halo"></div><div class="ring"></div><div class="icon">${iconFor(v)}</div><div class="tag"></div></div>`;
  const el = wrap.firstElementChild;
  el.addEventListener('click', (e) => { e.stopPropagation(); select({ kind: 'track', id: v.track_id }); });
  const marker = new maplibregl.Marker({ element: wrap, anchor: 'center' }).setLngLat([v.position.lon, v.position.lat]).addTo(map);
  m = { marker, wrap, el, cls: v.asset_class, icon: el.querySelector('.icon'), tag: el.querySelector('.tag') };
  S.markers.set(v.track_id, m);
  return m;
}

function styleMarkers(frame) {
  const present = new Set();
  const areaSel = S.sel?.kind === 'area' ? new Set(frame.verdicts.filter((v) => v.area_alert_id === S.sel.id).map((v) => v.track_id)) : null;
  for (const v of frame.verdicts) {
    present.add(v.track_id);
    const m = markerFor(v);
    const sel = (S.sel?.kind === 'track' && S.sel.id === v.track_id) || (areaSel && areaSel.has(v.track_id));
    m.el.className = ['trk', v.domain, `c-${v.asset_class}`, `s-${v.trust_state}`, v.normality_state === 'abnormal' ? 'abnormal' : '',
      v.confidence_level === 'low' ? 'conf-low' : '', isIssue(v) && SEV_RANK[v.severity.level] >= 2 ? 'problem' : '', sel ? 'sel' : '', shown(v) ? '' : 'hidden'].join(' ');
    m.tag.textContent = nameOf(v);
    if (v.position.track_deg != null) m.icon.style.transform = `rotate(${v.position.track_deg}deg)`;
    m.wrap.style.zIndex = sel ? 40 : v.normality_state === 'abnormal' ? 30 : 10 + SEV_RANK[v.severity.level];
  }
  for (const [id, m] of S.markers) if (!present.has(id)) { m.marker.remove(); S.markers.delete(id); }
}

function moveMarkers() {
  const B = S.bundle, a = B.frames[S.idx], b = B.frames[S.idx + 1];
  if (!a) return;
  const f = b ? Math.min(1, Math.max(0, (S.t - a.t) / (b.t - a.t))) : 0;
  const next = b ? B.byTrack[S.idx + 1] : null;
  for (const v of a.verdicts) {
    const w = next && next.get(v.track_id);
    let p = v.position;
    if (w && distM(p, w.position) < JUMP_M) p = { lon: p.lon + (w.position.lon - p.lon) * f, lat: p.lat + (w.position.lat - p.lat) * f };
    S.pos.set(v.track_id, p);
    S.markers.get(v.track_id)?.marker.setLngLat([p.lon, p.lat]);
  }
}

function drawTrails() {
  const B = S.bundle, feats = [], from = Math.max(0, S.idx - TRAIL_FRAMES);
  for (const v of B.frames[S.idx].verdicts) {
    if (!shown(v)) continue;
    let prev = null;
    for (let i = from; i <= S.idx; i++) {
      const w = B.byTrack[i].get(v.track_id);
      if (!w) { prev = null; continue; }
      if (prev) {
        const age = (i - from) / Math.max(1, S.idx - from);
        const c = w.trust_state === 'untrusted' ? COLORS.red : w.trust_state === 'caution' ? COLORS.amber : (v.domain === 'aircraft' ? COLORS.blue : TYPE_COLOR[v.asset_class] || COLORS.blue);
        feats.push({ type: 'Feature', properties: { c, o: 0.08 + 0.5 * age }, geometry: { type: 'LineString', coordinates: [[prev.lon, prev.lat], [w.position.lon, w.position.lat]] } });
      }
      prev = w.position;
    }
  }
  map.getSource('trails').setData({ type: 'FeatureCollection', features: feats });
}

function drawRisk(frame) {
  const feats = frame.risk_zones.features;
  map.getSource('risk').setData({ type: 'FeatureCollection', features: feats.filter((f) => f.properties.kind !== 'static') });
  if (!S.bundle.halos) map.getSource('halos').setData({ type: 'FeatureCollection', features: feats.filter((f) => f.properties.kind === 'static') });
  S.fcLabels.forEach((m) => m.remove());
  S.fcLabels = feats.filter((f) => f.properties.kind === 'forecast').map((f) => {
    const el = document.createElement('div');
    el.className = 'fc-label';
    el.textContent = `Enters in ${Math.round(f.properties.eta_s)} s`;
    const end = f.geometry.coordinates[f.geometry.coordinates.length - 1];
    return new maplibregl.Marker({ element: el, anchor: 'left', offset: [10, 0] }).setLngLat(end).addTo(map);
  });
}

// ---- issues -------------------------------------------------------------------------------

function camCheck(id) {
  const c = S.bundle.cams?.[S.idx]?.checks?.[id];
  if (!c) return S.bundle.cams ? { summary: 'not_covered', results: [] } : null;
  return c;
}

function checking(key) {
  if (!S.firstSeen.has(key)) S.firstSeen.set(key, performance.now());
  return performance.now() - S.firstSeen.get(key) < CAMERA_DELAY_MS;
}

function issuesAt(frame) {
  const items = [], areas = new Map();
  for (const v of frame.verdicts) {
    if (!isIssue(v) || !shown(v)) continue;
    if (v.area_alert_id) {
      const a = areas.get(v.area_alert_id) || { kind: 'area', id: v.area_alert_id, members: [], sev: 'none', score: 0 };
      a.members.push(v);
      if (SEV_RANK[v.severity.level] > SEV_RANK[a.sev]) a.sev = v.severity.level;
      a.score = Math.max(a.score, v.severity.score);
      areas.set(v.area_alert_id, a);
    } else items.push({ kind: 'track', id: v.track_id, v, sev: v.severity.level, score: v.severity.score, cam: camCheck(v.track_id) });
  }
  for (const a of areas.values()) {
    a.zone = frame.risk_zones.features.find((f) => f.properties.area_alert_id === a.id)?.properties;
    const checks = a.members.map((v) => camCheck(v.track_id)).filter(Boolean);
    a.cam = checks.find((c) => c.summary === 'seen_at_position') || checks.find((c) => c.summary === 'position_wrong') ||
      checks.find((c) => c.summary === 'cannot_confirm') || checks[0] || null;
    items.push(a);
  }
  return items.sort((x, y) => SEV_RANK[y.sev] - SEV_RANK[x.sev] || y.score - x.score);
}

function issueSince(it) {
  const B = S.bundle;
  let i = S.idx;
  const test = it.kind === 'area' ? (k) => B.frames[k].verdicts.some((v) => v.area_alert_id === it.id) : (k) => { const v = B.byTrack[k].get(it.id); return v && isIssue(v); };
  while (i > 0 && test(i - 1)) i--;
  return S.t - B.frames[i].t;
}

function camSummary(cam, key) {
  if (!cam) return { cls: 'na', text: 'No camera data in this replay', short: '' };
  if (checking(key)) return { cls: 'wait', text: 'Checking partner cameras…', short: 'checking…' };
  const r0 = cam.results[0];
  switch (cam.summary) {
    case 'seen_at_position': return { cls: 'ok', text: `${r0.camera_id} sees it there`, short: `${r0.camera_id} sees it`, cam: r0 };
    case 'position_wrong': {
      const empty = cam.results.find((r) => r.outcome === 'no_vehicle');
      const real = cam.results.find((r) => r.target === 'true' && r.outcome === 'vehicle_seen');
      const text = empty ? `${empty.camera_id}: nothing at the reported spot` : `${real.camera_id} sees it elsewhere`;
      return { cls: 'bad', text, short: empty ? `${empty.camera_id}: spot empty` : `${real.camera_id}: elsewhere`, cam: empty || real, real };
    }
    case 'cannot_confirm': return { cls: 'na', text: `Camera can't confirm (${r0.reason})`, short: "camera can't confirm", cam: r0 };
    default: return { cls: 'na', text: 'No camera covers this spot', short: 'no camera' };
  }
}

function renderIssues() {
  const frame = S.bundle.frames[S.idx];
  const items = S.issues = issuesAt(frame);
  const n = items.length, total = frame.verdicts.filter(shown).length;
  $('issues-count').textContent = n;
  $('issues-count').classList.toggle('hot', n > 0);
  $('status').textContent = n ? `${n} issue${n === 1 ? '' : 's'}` : `All ${total} trusted`;
  $('status').classList.toggle('warn', n > 0);
  const list = $('issues-list'), top = list.scrollTop;
  list.innerHTML = n ? items.map((it, k) => {
    const cs = camSummary(it.cam, it.kind + it.id);
    const on = S.sel && S.sel.kind === it.kind && S.sel.id === it.id ? ' on' : '';
    const camHtml = cs.short ? `<span class="cam-note ${cs.cls}">${CAM_SVG(cs.cls === 'ok' ? '#0f7a52' : cs.cls === 'bad' ? '#e5383b' : '#5b6380')}${esc(cs.short)}</span>` : '';
    if (it.kind === 'area') {
      return `<button class="issue${on}" data-k="${k}"><span class="bar sev-${it.sev}"></span><span class="i-body">
        <div class="i-what">${esc(it.zone?.label || 'Possible interference')}</div>
        <div class="i-where">${it.members.length} positions affected</div>
        <div class="i-meta">for ${forTime(issueSince(it))} ${camHtml}</div></span></button>`;
    }
    const v = it.v;
    return `<button class="issue${on}" data-k="${k}"><span class="bar sev-${it.sev}"></span><span class="i-body">
      <div class="i-what">${esc(ISSUE_WORD[quad(v)] || 'Check position')}</div>
      <div class="i-where">${esc(nameOf(v))} · ${esc(v.severity.zone_name || '')}</div>
      <div class="i-meta">for ${forTime(issueSince(it))} ${camHtml}</div></span></button>`;
  }).join('') : '<div class="empty"><strong>All clear</strong>Every position on the map can be trusted.</div>';
  list.scrollTop = top;
}

// ---- details window -------------------------------------------------------------------------

function camBlock(cam, key) {
  const cs = camSummary(cam, key);
  const lines = cam && !checking(key) ? cam.results.slice(0, 3).map((r) => {
    const camInfo = S.cameras.find((c) => c.camera_id === r.camera_id);
    const what = r.outcome === 'vehicle_seen' ? (r.target === 'true' ? 'vehicle seen away from the reported spot' : 'vehicle visible') :
      r.outcome === 'no_vehicle' ? 'no vehicle at the reported spot' : `can't confirm (${r.reason})`;
    return `<div class="cc-line">${esc(r.camera_id)} · ${esc(camInfo?.label || '')}: ${what} · ${Math.round(r.confidence * 100)} % · ${r.distance_m} m</div>`;
  }).join('') : '';
  const btn = cs.cam ? `<button class="look-btn" data-live="${esc(cs.cam.camera_id)}">Look here · open ${esc(cs.cam.camera_id)}</button>` : '';
  return `<div class="label">Camera check <span class="sim-tag">simulated</span></div>
    <div class="camcheck ${cs.cls}"><div class="cc-sum">${CAM_SVG(cs.cls === 'ok' ? '#0f7a52' : cs.cls === 'bad' ? '#b3262a' : '#5b6380')}${esc(cs.text)}</div>${lines}${btn}</div>`;
}

function trackDetails(frame, id) {
  const v = S.bundle.byTrack[S.idx].get(id);
  if (!v) return '<div class="empty">No position for this track right now.</div>';
  const q = quad(v), [hl, hlText] = HEADLINE[q];
  const confOn = { low: 1, medium: 2, high: 3 }[v.confidence_level];
  const p = v.position;
  const speed = p.speed_mps == null ? '—' : `${(p.speed_mps * 3.6).toFixed(0)} km/h`;
  const alt = p.alt_m ? ` · ${Math.round(p.alt_m)} m up` : '';
  const more = !S.more ? '' : `
    <div class="label">Likely cause</div><div class="cause">${esc(CAUSE_TEXT[v.cause])} <span>· ${Math.round(v.cause_probs[v.cause] * 100)} % likely</span></div>
    ${v.evidence.length ? `<div class="label">Why</div><ul class="why">${v.evidence.map((e) => `<li>${esc(e.text)}</li>`).join('')}</ul>` : ''}
    <div class="label">Scores</div>
    <div class="scores"><div class="score"><div class="num">${Math.round(v.integrity)} <small>/ 100</small></div><div class="cap">Can we trust the position?</div></div>
      <div class="score"><div class="num">${Math.round(v.normality)} <small>/ 100</small></div><div class="cap">Is the movement normal?</div></div></div>
    ${Object.entries(v.dimensions).map(([k, val]) => `<div class="dim"><span>${k[0].toUpperCase() + k.slice(1)}</span>
      <span class="track"><span class="fill" style="width:${val}%;background:${val < 40 ? COLORS.red : val < 70 ? COLORS.amber : '#9aa3bd'}"></span></span>
      <span class="val">${Math.round(val)} / 100</span></div>`).join('')}
    <div class="label">Now</div>
    <div class="facts"><div><span>Zone</span>${esc(v.severity.zone_name || '—')}</div><div><span>Speed</span>${speed}</div><div><span>Heading</span>${p.track_deg == null ? '—' : Math.round(p.track_deg) + '°'}</div></div>
    <div class="label">Position trust, last 5 min</div>${sparkline(id)}`;
  return `<div class="d-name">${esc(nameOf(v))}</div>
    <div class="d-kind">${esc(CLASS_NAME[v.asset_class] || v.asset_class)} · ${esc(v.asset_id)}${alt}</div>
    <div class="headline hl-${q}"><b>${hl}</b><span>${hlText}</span></div>
    ${isIssue(v) ? `<div class="label">What to do</div><div class="todo">${esc(v.action.text)}</div>` : ''}
    ${v.early_warning ? `<div class="label">Heads-up</div><div class="todo" style="color:var(--pink-ink)">Enters an interference area in ${Math.round(v.early_warning.eta_s)} s</div>` : ''}
    <div class="label">Confidence</div>
    <div class="conf"><span class="conf-meter">${[1, 2, 3].map((k) => `<i class="${k <= confOn ? 'on' : ''}"></i>`).join('')}</span>
      <span><b>${v.confidence_level[0].toUpperCase() + v.confidence_level.slice(1)}</b> · ${Math.round(v.confidence * 100)} %</span></div>
    ${isIssue(v) ? camBlock(camCheck(id), 'track' + id) : ''}
    <button class="more-btn" data-more>${S.more ? 'Less detail ▴' : 'More detail ▾'}</button>${more}`;
}

function areaDetails(frame, id) {
  const it = S.issues.find((x) => x.kind === 'area' && x.id === id);
  if (!it) return '<div class="d-name">Resolved</div><div class="empty">This area alert has ended.</div>';
  const action = it.zone?.action?.text || it.members[0].action.text;
  const conf = it.members.reduce((s, v) => s + v.confidence, 0) / it.members.length;
  const confLvl = conf >= 0.75 ? 'High' : conf >= 0.45 ? 'Medium' : 'Low';
  return `<div class="d-name">${esc(it.zone?.label || 'Possible interference')}</div>
    <div class="d-kind">${it.members.length} positions affected · for ${forTime(issueSince(it))}</div>
    <div class="headline hl-area"><b>${esc(CAUSE_TEXT[it.members[0].cause] || 'Possible interference')}</b><span>Several positions degraded at the same time in one area.</span></div>
    <div class="label">What to do</div><div class="todo">${esc(action)}</div>
    <div class="label">Confidence</div>
    <div class="conf"><span class="conf-meter">${[1, 2, 3].map((k) => `<i class="${k <= { Low: 1, Medium: 2, High: 3 }[confLvl] ? 'on' : ''}"></i>`).join('')}</span>
      <span><b>${confLvl}</b> · ${Math.round(conf * 100)} % (average)</span></div>
    ${camBlock(it.cam, 'area' + id)}
    <button class="more-btn" data-more>${S.more ? 'Less detail ▴' : 'Affected positions ▾'}</button>
    ${S.more ? it.members.map((v) => `<button class="member" data-track="${esc(v.track_id)}">${esc(nameOf(v))}<span>${Math.round(v.confidence * 100)} % confidence</span></button>`).join('') : ''}`;
}

function sparkline(id) {
  const B = S.bundle, from = Math.max(0, S.idx - HISTORY_FRAMES), pts = [];
  for (let i = from; i <= S.idx; i++) { const v = B.byTrack[i].get(id); if (v) pts.push([i, v.integrity, v.trust_state]); }
  if (pts.length < 2) return '<div class="cc-line">Not enough history yet.</div>';
  const W = 340, H = 66, x = (i) => ((i - from) / Math.max(1, S.idx - from)) * (W - 8) + 4, y = (val) => H - 4 - (val / 100) * (H - 8);
  const [li, lv, ls] = pts[pts.length - 1];
  return `<svg class="spark" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">
    <line x1="0" x2="${W}" y1="${y(70)}" y2="${y(70)}" stroke="#e3e6ef" stroke-dasharray="4 4"/><line x1="0" x2="${W}" y1="${y(40)}" y2="${y(40)}" stroke="#f3d3d4" stroke-dasharray="4 4"/>
    <polyline points="${pts.map(([i, val]) => `${x(i).toFixed(1)},${y(val).toFixed(1)}`).join(' ')}" fill="none" stroke="${COLORS.ink}" stroke-width="2" vector-effect="non-scaling-stroke"/>
    <circle cx="${x(li)}" cy="${y(lv)}" r="4.5" fill="${ls === 'untrusted' ? COLORS.red : ls === 'caution' ? COLORS.amber : COLORS.blue}" stroke="#fff" stroke-width="1.5"/></svg>
    <div class="spark-axis"><span>${forTime((S.idx - from) * S.bundle.manifest.step_s)} ago</span><span>now · ${Math.round(lv)} / 100</span></div>`;
}

function renderDetails() {
  const box = $('details');
  box.hidden = !S.sel;
  document.body.classList.toggle('details-open', !!S.sel);
  if (!S.sel) return;
  const frame = S.bundle.frames[S.idx], top = box.scrollTop;
  $('details-body').innerHTML = S.sel.kind === 'track' ? trackDetails(frame, S.sel.id) : areaDetails(frame, S.sel.id);
  box.scrollTop = top;
}

// ---- cameras --------------------------------------------------------------------------------

function cone(cam, color, opacity) {
  const [lon, lat] = cam.coords, [kx, ky] = mPerDeg(lat), pts = [[lon, lat]];
  for (let a = -cam.fov_deg / 2; a <= cam.fov_deg / 2 + 0.01; a += cam.fov_deg / 12) {
    const b = (cam.heading_deg + a) * Math.PI / 180;
    pts.push([lon + Math.sin(b) * cam.range_m / kx, lat + Math.cos(b) * cam.range_m / ky]);
  }
  pts.push([lon, lat]);
  return { type: 'Feature', properties: { c: color, o: opacity }, geometry: { type: 'Polygon', coordinates: [pts] } };
}

function hotCameras() {
  const hot = new Map();  // camera_id -> issue key
  for (const it of S.issues) {
    const cs = camSummary(it.cam, it.kind + it.id);
    if (cs.cam) hot.set(cs.cam.camera_id, it);
  }
  return hot;
}

function drawCameras() {
  const hot = hotCameras(), feats = [];
  for (const cam of S.cameras) {
    const isHot = hot.has(cam.camera_id);
    const want = isHot || S.show.cameras;
    let m = S.camMarkers.get(cam.camera_id);
    if (!want) { if (m) { m.remove(); S.camMarkers.delete(cam.camera_id); } continue; }
    if (!m) {
      const el = document.createElement('div');
      el.innerHTML = CAM_SVG();
      el.title = `${cam.camera_id} · ${cam.label} (simulated)`;
      el.addEventListener('click', (e) => { e.stopPropagation(); openLive(cam.camera_id); });
      m = new maplibregl.Marker({ element: el, anchor: 'center' }).setLngLat(cam.coords).addTo(map);
      S.camMarkers.set(cam.camera_id, m);
    }
    m.getElement().className = `cam ${isHot ? 'hot' : 'faint'} ${cam.status !== 'online' ? 'offline' : ''}`;
    m.getElement().style.zIndex = isHot ? 50 : 5;
    feats.push(cone(cam, isHot ? COLORS.pink : '#5b6380', isHot ? 0.14 : 0.06));
  }
  map.getSource('cones').setData({ type: 'FeatureCollection', features: feats });
  // where a camera actually sees the vehicle the GPS misplaced
  S.seenMarkers.forEach((m) => m.remove());
  S.seenMarkers = [];
  const it = S.sel && S.issues.find((x) => x.kind === S.sel.kind && x.id === S.sel.id);
  const cs = it && camSummary(it.cam, it.kind + it.id);
  if (cs?.real) {
    const el = document.createElement('div');
    el.className = 'seen-here';
    el.innerHTML = `<span>📷 seen here · ${esc(cs.real.camera_id)}</span>`;
    S.seenMarkers.push(new maplibregl.Marker({ element: el, anchor: 'center' }).setLngLat(cs.real.at).addTo(map));
  }
}

let liveMap = null;
function openLive(camId) {
  const cam = S.cameras.find((c) => c.camera_id === camId);
  if (!cam) return;
  const hot = hotCameras().get(camId);
  S.live = { cam, issue: hot ? { kind: hot.kind, id: hot.id } : null };
  $('live').hidden = false;
  $('live').className = `card ${S.cur?.night && !cam.infrared ? 'night' : ''} ${S.cur?.fog ? 'fog' : ''}`;
  $('live-title').textContent = `${cam.camera_id} · ${cam.label}`;
  $('live-cam').textContent = `${cam.camera_id} ${cam.provider.replace(' (simulated)', '').toUpperCase()}`;
  if (!liveMap) {
    liveMap = new maplibregl.Map({ container: 'live-map', interactive: false, attributionControl: false, maxPitch: 85, fadeDuration: 0,
      style: { version: 8, sources: { photo: { type: 'raster', tileSize: 256, ...S.photo } }, layers: [{ id: 'bg', type: 'background', paint: { 'background-color': '#202530' } }, { id: 'photo', type: 'raster', source: 'photo' }] } });
  }
  const c = { lon: cam.coords[0], lat: cam.coords[1] };
  const target = liveTarget() || (() => { const [kx, ky] = mPerDeg(c.lat), b = cam.heading_deg * Math.PI / 180, d = Math.min(cam.range_m * 0.5, 180); return { lon: c.lon + Math.sin(b) * d / kx, lat: c.lat + Math.cos(b) * d / ky }; })();
  const d = distM(c, target);
  liveMap.resize();
  liveMap.jumpTo({ center: [target.lon, target.lat], bearing: bearing(c, target), pitch: 68, zoom: Math.max(15.6, Math.min(19, 19.6 - Math.log2(Math.max(d, 40) / 30))) });
  if (isPhone()) $('issues').classList.remove('open');
}

function liveTarget() {
  const L = S.live;
  if (!L?.issue) return null;
  const it = S.issues.find((x) => x.kind === L.issue.kind && x.id === L.issue.id);
  const r = it?.cam?.results.find((x) => x.camera_id === L.cam.camera_id);
  return r ? { lon: r.at[0], lat: r.at[1] } : null;
}

function drawLive() {
  if (!S.live || !liveMap) return;
  const L = S.live, ov = $('live-overlay'), c = { lon: L.cam.coords[0], lat: L.cam.coords[1] };
  const it = L.issue && S.issues.find((x) => x.kind === L.issue.kind && x.id === L.issue.id);
  const ids = it ? (it.kind === 'area' ? it.members.map((v) => v.track_id) : [it.id]) : [];
  const results = (it?.cam?.results || []).filter((r) => r.camera_id === L.cam.camera_id);
  const html = [];
  const W = ov.clientWidth, H = ov.clientHeight;
  const put = (p, cls) => { const q = liveMap.project([p.lon, p.lat]); if (q.x > -20 && q.x < W + 20 && q.y > 0 && q.y < H + 20) html.push(`<div class="live-veh ${cls}" style="left:${q.x}px;top:${q.y}px"></div>`); return q; };
  for (const [id, p] of S.pos) {  // everything the camera can see, except the tracks this check is about
    if (ids.includes(id) || distM(c, p) > L.cam.range_m * 1.1) continue;
    put(p, S.bundle.byTrack[S.idx].get(id)?.domain === 'aircraft' ? 'ac' : '');
  }
  const blind = results.length && results.every((r) => r.outcome === 'cannot_confirm');
  for (const r of results) {
    const p = { lon: r.at[0], lat: r.at[1] }, q = liveMap.project(r.at);
    const size = Math.max(28, Math.min(90, 3600 / Math.max(r.distance_m, 30)));
    if (r.outcome === 'vehicle_seen') {
      put(p, '');
      html.push(`<div class="det-box" style="left:${q.x - size / 2}px;top:${q.y - size / 2}px;width:${size}px;height:${size}px"><span>vehicle ${Math.round(r.confidence * 100)}%</span></div>`);
    } else if (r.outcome === 'no_vehicle') {
      html.push(`<div class="det-box empty" style="left:${q.x - size / 2}px;top:${q.y - size / 2}px;width:${size}px;height:${size}px"><span>reported spot · empty</span></div>`);
    }
  }
  if (it && it.kind === 'area') for (const v of it.members) { const p = S.pos.get(v.track_id); if (p && !blind) put(p, ''); }
  ov.innerHTML = html.join('');
  const msg = $('live-msg');
  msg.hidden = !blind && L.cam.status === 'online';
  msg.textContent = L.cam.status !== 'online' ? 'Camera offline' : blind ? `Can't confirm: ${results[0].reason}` : '';
  $('live-time').textContent = hhmm(S.t);
  const r0 = results[0];
  $('live-result').textContent = !it ? 'No open issue in this camera\'s view.' : !r0 ? 'This camera does not cover the issue.' :
    r0.outcome === 'vehicle_seen' ? `Vehicle visible · ${Math.round(r0.confidence * 100)} % · ${r0.distance_m} m from the camera` :
    r0.outcome === 'no_vehicle' ? `Nothing at the reported position · ${Math.round(r0.confidence * 100)} % · ${r0.distance_m} m from the camera` :
    `Can't confirm: ${r0.reason}`;
}

$('live-close').addEventListener('click', () => { $('live').hidden = true; S.live = null; });

// ---- legend -------------------------------------------------------------------------------

function renderLegend() {
  const ic = (cls, svg) => `<span class="lg-icon"><span class="trk ${cls}" style="width:22px;height:22px;--s:.85;--ring:30px"><span class="halo"></span><span class="icon">${svg}</span></span></span>`;
  const views = {
    photo: [['fill', '#3d4148', 'Runway (white outline)'], ['fill', COLORS.purple, 'Signal shadow (faint)'], ['fill', COLORS.pink, 'Possible interference'], ['dash', '#e8368a', 'Heading into interference']],
    schematic: [['fill', '#2c3352', 'Runway'], ['line', '#3d7bff', 'Taxiway'], ['line', '#9aa3b8', 'Service road'], ['fill', '#dde5f5', 'Apron'], ['fill', '#cfd3de', 'Building'],
      ['dot', '#6b7390', 'Stand'], ['dot', COLORS.red, 'Holding point']],
    traffic: [['fill', '#b7c3dd', 'Terminal (3D)'], ['fill', '#c9cede', 'Building (3D)'], ['fill', '#d9deea', 'Runway'], ['fill', '#dde5f5', 'Apron']],
    gnss: [['fill', 'rgba(139,92,246,.42)', 'Signal shadow: strong'], ['fill', 'rgba(139,92,246,.26)', 'Signal shadow: medium'], ['fill', 'rgba(139,92,246,.13)', 'Signal shadow: weak'],
      ['fill', 'rgba(255,79,163,.45)', 'Possible interference (live)'], ['dash', '#e8368a', 'Heading into interference']],
  };
  const sw = ([kind, c, label, bg]) => `<div class="lg-row"><span class="sw ${kind === 'line' ? 'line' : kind === 'dash' ? 'dash' : kind === 'dot' ? 'dot' : ''}"
    style="${kind === 'fill' || kind === 'dot' ? `background:${c}` : `border-color:${c}`}${bg ? `;background:${bg}` : ''}"></span>${label}</div>`;
  $('legend').innerHTML = `<div class="lg-title">Positions</div>
    <div class="lg-row">${ic('s-trusted aircraft', PLANE)}Trusted</div>
    <div class="lg-row">${ic('s-caution aircraft', PLANE)}Reduced accuracy</div>
    <div class="lg-row">${ic('s-untrusted aircraft', PLANE)}Don't trust the position</div>
    <div class="lg-row">${ic('s-trusted aircraft abnormal', PLANE)}Unusual movement</div>
    <div class="lg-row">${ic('s-trusted aircraft conf-low', PLANE)}Faded: little evidence</div>
    <div class="lg-title">Vehicles (when trusted)</div>
    <div class="lg-grid">${TYPE_KEY.map(([k, l]) => `<div class="lg-row"><span class="sw dot" style="background:${TYPE_COLOR[k]}"></span>${l}</div>`).join('')}</div>
    <div class="lg-title">Cameras <span class="sim-tag">simulated</span></div>
    <div class="lg-row"><span class="cam hot" style="width:24px;height:24px;animation:none">${CAM_SVG()}</span>Camera that checked an issue</div>
    <div class="lg-row"><span class="cam faint" style="width:22px;height:22px">${CAM_SVG()}</span>Other cameras (switch in Views)</div>
    <div class="lg-title">${VIEWS[S.view].label} view</div>
    ${views[S.view].map(sw).join('')}`;
}
$('legend-btn').addEventListener('click', () => {
  if (isPhone()) document.body.classList.toggle('legend-open');
  else document.body.classList.toggle('legend-closed');
});

// ---- selection ------------------------------------------------------------------------------

function select(sel, fly = false) {
  const changed = JSON.stringify(sel) !== JSON.stringify(S.sel);
  S.sel = sel;
  if (changed) { S.more = false; $('details').scrollTop = 0; }
  const frame = S.bundle.frames[S.idx];
  if (fly && sel) {
    const pts = sel.kind === 'track' ? [S.pos.get(sel.id)] : frame.verdicts.filter((v) => v.area_alert_id === sel.id).map((v) => S.pos.get(v.track_id));
    fitTo(pts.filter(Boolean), sel.kind === 'track' ? 15.8 : 16);
  }
  styleMarkers(frame);
  renderIssues();
  renderDetails();
  drawCameras();
}

function fitTo(pts, maxZoom = 16) {
  if (!pts.length) return;
  const b = new maplibregl.LngLatBounds();
  pts.forEach((p) => b.extend([p.lon, p.lat]));
  const right = isPhone() ? 40 : 380 + (S.sel ? 400 : 0);
  map.fitBounds(b, { padding: { top: 110, bottom: isPhone() ? 160 : 110, left: isPhone() ? 40 : 330, right }, maxZoom, duration: 900 });
}

$('issues-list').addEventListener('click', (e) => {
  const b = e.target.closest('.issue');
  if (!b) return;
  const it = S.issues[Number(b.dataset.k)];
  if (it) select({ kind: it.kind, id: it.id }, true);
  if (isPhone()) document.body.classList.remove('sheet-open');
});
$('details-body').addEventListener('click', (e) => {
  if (e.target.closest('[data-more]')) { S.more = !S.more; return renderDetails(); }
  const live = e.target.closest('[data-live]');
  if (live) return openLive(live.dataset.live);
  const m = e.target.closest('[data-track]');
  if (m) select({ kind: 'track', id: m.dataset.track }, true);
});
$('details-close').addEventListener('click', () => select(null));
$('issues-head').addEventListener('click', () => { if (isPhone()) document.body.classList.toggle('sheet-open'); });

// ---- views menu ------------------------------------------------------------------------------

const THUMBS = {
  photo: `<svg viewBox="0 0 84 62"><rect width="84" height="62" fill="#5b6b4f"/><path d="M0 40 L84 18 L84 30 L0 52Z" fill="#3d4148"/><rect x="46" y="38" width="30" height="16" fill="#7c8577"/>
    <rect x="8" y="8" width="22" height="14" fill="#8a8c84"/><path d="M0 46 L84 24" stroke="#e8e8e8" stroke-dasharray="4 3"/><circle cx="56" cy="22" r="3" fill="#2f6bff" stroke="#fff"/></svg>`,
  schematic: `<svg viewBox="0 0 84 62"><rect width="84" height="62" fill="#eef1f7"/><rect x="40" y="34" width="36" height="20" rx="2" fill="#dde5f5"/>
    <path d="M0 40 L84 18 L84 27 L0 49Z" fill="#2c3352"/><path d="M6 10 Q 40 30 80 6" stroke="#3d7bff" stroke-width="3" fill="none"/><path d="M10 58 L60 30" stroke="#9aa3b8" stroke-width="2"/><circle cx="30" cy="18" r="2.6" fill="#e5383b"/></svg>`,
  traffic: `<svg viewBox="0 0 84 62"><rect width="84" height="62" fill="#f1f3f8"/><path d="M8 40 l14 -6 l0 -14 l-14 6z" fill="#b7c3dd"/><path d="M22 34 l14 6 l0 -14 l-14 -6z" fill="#c9cede"/>
    <path d="M44 50 l20 -8 l0 -10 l-20 8z" fill="#c9cede"/><circle cx="58" cy="16" r="5" fill="#2f6bff"/><rect x="66" y="40" width="5" height="12" rx="2" fill="#0d9488"/><circle cx="30" cy="54" r="5" fill="#2f6bff"/></svg>`,
  gnss: `<svg viewBox="0 0 84 62"><rect width="84" height="62" fill="#eceef5"/><rect x="14" y="12" width="20" height="14" fill="#cfd3de"/><rect x="6" y="4" width="36" height="30" rx="9" fill="#8b5cf6" opacity=".18"/>
    <rect x="10" y="8" width="28" height="22" rx="6" fill="#8b5cf6" opacity=".25"/><path d="M48 34 h26 v20 h-26z" fill="#ff4fa3" opacity=".4" stroke="#e8368a" stroke-width="1.5"/><path d="M30 58 L48 46" stroke="#e8368a" stroke-width="2" stroke-dasharray="3 2"/></svg>`,
};
function renderViews() {
  $('views-thumb').innerHTML = THUMBS[S.view];
  $('views-label').textContent = VIEWS[S.view].label;
  $('view-grid').innerHTML = Object.entries(VIEWS).map(([k, v]) => `<button class="view-opt ${k === S.view ? 'on' : ''}" data-view="${k}"><span class="thumb">${THUMBS[k]}</span>${v.label}</button>`).join('');
}
const toggleMenu = (btn, menu, open) => { menu.hidden = !open; btn.setAttribute('aria-expanded', String(open)); };
$('views-btn').addEventListener('click', (e) => { e.stopPropagation(); toggleMenu($('views-btn'), $('views-menu'), $('views-menu').hidden); });
$('view-grid').addEventListener('click', (e) => { const b = e.target.closest('[data-view]'); if (b) applyView(b.dataset.view); });
for (const key of ['aircraft', 'vehicles', 'cameras']) {
  $(`show-${key}`).addEventListener('change', (e) => { S.show[key] = e.target.checked; onFrame(); });
}

// ---- demos, jam switch, share ------------------------------------------------------------------

function renderDemo() {
  $('demo-list').innerHTML = S.scenarios.map((sc, k) => `<button class="demo-item ${S.cur?.id === sc.id ? 'on' : ''}" data-sc="${k}">
    <span class="cat">${esc(sc.category)}${sc.night ? ' · night' : ''}${sc.fog ? ' · fog' : ''}</span><b>${esc(sc.title)}</b><span class="story">${esc(sc.story)}</span></button>`).join('');
  $('demo-play').textContent = S.playing ? 'Pause' : 'Play';
  $('demo-source').textContent = S.cur?.real ? 'Replay bundle from the pipeline' : 'Simulated data and camera feeds (until the real bundle arrives).';
  $('scenario-title').innerHTML = S.cur ? `${esc(S.cur.title)}<small>${esc(S.cur.category)} · simulated</small>` : '';
}

async function startScenario(sc, at, opts = {}) {
  S.cur = sc;
  S.bundle = await loadBundle(sc);
  S.firstSeen.clear();
  map.getSource('halos').setData(S.bundle.halos || empty());
  S.t = Math.max(S.bundle.manifest.t_start, Math.min(S.bundle.manifest.t_end, at ?? S.bundle.manifest.t_start));
  if (opts.untilIssue) {  // open where the scenario's alert is already showing (area alerts need a moment to form)
    const M = S.bundle.manifest, want = new Set(sc.focus || []);
    const ok = (f) => f.verdicts.some((v) => isIssue(v) && (v.area_alert_id || want.has(v.track_id) || !want.size)) &&
      (!opts.area || f.verdicts.some((v) => v.area_alert_id && isIssue(v)));
    const i0 = Math.floor((S.t - M.t_start) / M.step_s), i = S.bundle.frames.findIndex((f, k) => k >= i0 && ok(f));
    if (i >= 0) S.t = S.bundle.frames[Math.min(i + 1, S.bundle.frames.length - 1)].t + 0.2;
  }
  S.idx = -1;
  S.sel = null;
  $('live').hidden = true;
  S.live = null;
  tick(0);
  const frame = S.bundle.frames[S.idx];
  if (opts.focus !== false) {
    const area = frame.verdicts.find((v) => v.area_alert_id && isIssue(v))?.area_alert_id;
    if (opts.area && area) select({ kind: 'area', id: area }, true);
    else if (sc.focus?.length === 1 && S.bundle.byTrack[S.idx].get(sc.focus[0])) select({ kind: 'track', id: sc.focus[0] }, true);
    else if (sc.focus?.length) { select(null); fitTo(sc.focus.map((id) => S.pos.get(id)).filter(Boolean), 15.5); }
    else if (area) select({ kind: 'area', id: area }, true);
    else select(null);
  }
  S.playing = true;
  renderDemo();
}

$('demo-btn').addEventListener('click', (e) => { e.stopPropagation(); toggleMenu($('demo-btn'), $('demo-menu'), $('demo-menu').hidden); });
$('demo-list').addEventListener('click', (e) => {
  const b = e.target.closest('[data-sc]');
  if (!b) return;
  const sc = S.scenarios[Number(b.dataset.sc)];
  $('jam-toggle').checked = !!sc.jam;
  startScenario(sc, sc.id === 'normal_ops' ? null : sc.onset_t, { untilIssue: true, area: /interference|anomaly/i.test(sc.category) });
  toggleMenu($('demo-btn'), $('demo-menu'), false);
});
$('demo-play').addEventListener('click', () => { S.playing = !S.playing; renderDemo(); });
$('demo-restart').addEventListener('click', () => startScenario(S.cur, S.cur.id === 'normal_ops' ? null : Math.max(S.cur.t_start, S.cur.onset_t - 5), { focus: false }));
$('jam-toggle').addEventListener('change', (e) => {
  if (e.target.checked) {
    const jam = S.scenarios.find((s) => s.jam) || S.scenarios.find((s) => s.category === 'Possible interference');
    if (!jam) return;
    const fl = $('flash');
    fl.classList.remove('go'); void fl.offsetWidth; fl.classList.add('go');
    startScenario(jam, jam.onset_t + 20, { area: true, untilIssue: true });
  } else {
    const normal = S.scenarios.find((s) => s.id === 'normal_ops') || S.scenarios[0];
    startScenario(normal, null);
    map.easeTo({ center: CFG.center, zoom: isPhone() ? 13.4 : CFG.zoom, duration: 900 });
  }
});
$('share-btn').addEventListener('click', () => {
  toggleMenu($('demo-btn'), $('demo-menu'), false);
  const url = CFG.publicUrl || location.href;
  $('share-qr').src = CFG.qr;
  $('share-url').href = url;
  $('share-url').textContent = url.replace(/^https?:\/\//, '');
  $('share').hidden = false;
});
$('share-close').addEventListener('click', () => ($('share').hidden = true));
$('share').addEventListener('click', (e) => { if (e.target.id === 'share') $('share').hidden = true; });
document.addEventListener('click', (e) => {
  if (!e.target.closest('#views')) toggleMenu($('views-btn'), $('views-menu'), false);
  if (!e.target.closest('#topright')) toggleMenu($('demo-btn'), $('demo-menu'), false);
});

// ---- clock ------------------------------------------------------------------------------------

function onFrame() {
  const frame = S.bundle.frames[S.idx];
  styleMarkers(frame);
  drawRisk(frame);
  drawTrails();
  renderIssues();
  renderDetails();
  drawCameras();
  $('clock').textContent = `${hhmm(frame.t)} UTC`;
}

let last = performance.now(), pulse = 0, lastUi = 0;
function tick(now) {
  const dt = now ? Math.min(0.25, (now - last) / 1000) : 0;
  last = now || performance.now();
  const M = S.bundle?.manifest;
  if (M) {
    if (S.playing && now) S.t += dt;
    if (S.t > M.t_end) S.t = S.cur && S.cur.id !== 'normal_ops' ? Math.max(M.t_start, S.cur.onset_t - 5) : M.t_start;  // loop the scenario
    const i = Math.min(S.bundle.frames.length - 1, Math.max(0, Math.floor((S.t - M.t_start) / M.step_s)));
    if (i !== S.idx) { S.idx = i; moveMarkers(); onFrame(); }
    moveMarkers();
    if (now - lastUi > 400) {  // camera "checking…" turns into a result without waiting for the next frame
      lastUi = now;
      if ([...S.firstSeen.values()].some((t0) => now - t0 < CAMERA_DELAY_MS + 450)) { renderIssues(); renderDetails(); drawCameras(); }
    }
    drawLive();
    pulse += dt;
    if (map.getLayer('risk-live-edge')) map.setPaintProperty('risk-live-edge', 'line-opacity', 0.55 + 0.45 * Math.sin(pulse * 3.5));
  }
  if (now) requestAnimationFrame(tick);
}

// ---- start ------------------------------------------------------------------------------------

(async function start() {
  try {
    const [scenarios, photo, L, cams] = await Promise.all([
      loadIndex(), photoTiles(),
      Promise.all(['aprons', 'buildings', 'runway_areas', 'routes', 'stands', 'holding_points'].map(loadLayer))
        .then(([aprons, buildings, runway_areas, routes, stands, holding_points]) => ({ aprons, buildings, runway_areas, routes, stands, holding_points })),
      loadLayer('cameras'),
    ]);
    S.scenarios = scenarios;
    S.photo = photo;
    S.cameras = cams.features.map((f) => ({ ...f.properties, coords: f.geometry.coordinates }));
    if (!map.loaded()) await new Promise((r) => map.once('load', r));
    addLayers(L);
    applyView('photo');
    if (isPhone()) document.body.classList.remove('legend-closed');
    else if (window.innerHeight < 820) document.body.classList.add('legend-closed');
    const first = scenarios.find((s) => s.real) || scenarios.find((s) => s.id === 'normal_ops') || scenarios[0];
    await startScenario(first, first.real ? first.onset_t - 10 : null, { focus: false });
    requestAnimationFrame(tick);
  } catch (err) {
    $('status').textContent = err.message;
    $('status').classList.add('warn');
    console.error(err);
  }
})();
