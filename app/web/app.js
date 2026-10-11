// Divas Air web map. Plays replay bundles (contract.ReplayManifest + one contract.ReplayFrame per line,
// src/divas_air/contract.py) like a live feed: a frame every 5 s, positions eased in between.
// The pipeline's own bundle (module 6, replay/) comes first; simulated scenarios fill the rest.

const CFG = Object.assign({
  scenarioIndex: '../../data/processed/demo/replay_fake/index.json',
  realBundle: '../../data/processed/demo/replay/',
  layers: 'data/',
  localTiles: '/tiles/{z}/{x}/{y}.jpg',
  onlinePhoto: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
  photoBounds: [12.2027, 41.7710, 12.2941, 41.8512],
  center: [12.2505, 41.8005],
  zoom: 14.2,
}, window.DIVAS_CFG || {});
const TRAIL_FRAMES = 8, HISTORY_FRAMES = 60, JUMP_M = 150;

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
const STATE = { trusted: 'Trusted', caution: 'Reduced accuracy', real_event: 'Real event', data_fault: 'Data fault', silent_risk: 'Position unreliable' };
const ISSUE_WORD = { caution: 'Reduced accuracy', real_event: 'Unusual movement', data_fault: 'Position unreliable', silent_risk: 'Position unreliable' };
const COLORS = { blue: '#2f6bff', pink: '#ff4fa3', red: '#e5383b', amber: '#f5a524', ink: '#18203a' };
const TYPE_COLOR = { bus: '#0d9488', fuel_truck: '#7c3aed', catering_truck: '#65a30d', baggage_tractor: '#64748b', follow_me: '#0ea5e9', sar_vehicle: '#1f2937' };

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

// ---- state --------------------------------------------------------------------------------

const S = {
  scenarios: [], cur: null, manifest: null, frames: [], byTrack: [], disp: [], source: '',
  t: 0, idx: -1, playing: true, view: 'photo', show: { aircraft: true, vehicles: true },
  sel: null, impact: null, panelOpen: false, items: [], top: null, notified: null,
  markers: new Map(), pos: new Map(), fcLabels: [], popup: null,
};
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const hhmmss = (t) => new Date(t * 1000).toISOString().slice(11, 19);
const forTime = (s) => (s < 60 ? `${Math.max(0, Math.round(s))} s` : `${Math.floor(s / 60)} min ${String(Math.round(s % 60)).padStart(2, '0')} s`);
const nameOf = (v) => v.callsign || `${CLASS_NAME[v.asset_class] || 'Vehicle'} ${(v.asset_id.match(/\d+/g) || [v.asset_id]).pop()}`;
const quad = (v) => (v.quadrant === 'trusted' && v.trust_state === 'caution' ? 'caution' : v.quadrant);
const isAlert = (v) => v.action.code !== 'none';
const shown = (v) => (v.domain === 'aircraft' ? S.show.aircraft : S.show.vehicles);
const isPhone = () => window.matchMedia('(max-width: 760px)').matches;
const kxy = (lat) => [111320 * Math.cos(lat * Math.PI / 180), 110540];
const distM = (a, b) => { const [kx, ky] = kxy(a.lat); return Math.hypot((a.lon - b.lon) * kx, (a.lat - b.lat) * ky); };
const bearing = (a, b) => { const [kx, ky] = kxy(a.lat); return (Math.atan2((b.lon - a.lon) * kx, (b.lat - a.lat) * ky) * 180 / Math.PI + 360) % 360; };
const empty = () => ({ type: 'FeatureCollection', features: [] });
const getJson = (url) => fetch(url).then((r) => (r.ok ? r.json() : null)).catch(() => null);

// ---- data ---------------------------------------------------------------------------------

async function loadScenarios() {
  const list = [];
  const real = await getJson(CFG.realBundle + 'manifest.json');
  const KIND = { phantom_incursion: 'Data fault', real_incursion: 'Real event', sector_interference: 'Possible interference', red_team: 'Red team' };
  if (real) {
    list.push({ id: 'real_scene', title: 'Full demo scene', category: 'Pipeline replay', base: CFG.realBundle, t_start: real.t_start, onset_t: real.t_start, focus: [], real: true });
    for (const ev of real.events) {
      list.push({ id: `real_${ev.event_id}`, title: ev.title.split(':')[0], category: `${KIND[ev.kind] || ev.kind} · pipeline`,
        base: CFG.realBundle, t_start: real.t_start, onset_t: ev.t_start, focus: ev.track_ids, real: true });
    }
  }
  const covered = new Set((real?.events || []).map((e) => e.kind));  // the pipeline's events replace the simulated versions
  const idx = await getJson(CFG.scenarioIndex);
  const dir = CFG.scenarioIndex.replace(/index\.json$/, '');
  for (const sc of idx?.scenarios || []) {
    if (covered.has(sc.id) || (real && sc.id === 'normal_ops')) continue;
    list.push({ ...sc, base: dir + sc.dir + '/', category: `${sc.category} · simulated` });
  }
  if (!list.length) throw new Error('No scenarios found. Run scripts/make_fake_replay.py.');
  return list;
}

// Display positions. GNSS positions wobble a few metres every report (that noise is part of what the
// model reads). For trusted tracks the map shows a smoothed position and a steady heading; flagged
// tracks are drawn exactly as reported, because the jump is the information.
function displayTrack(frames, byTrack) {
  const disp = frames.map(() => new Map());
  const ids = new Set(frames.flatMap((f) => f.verdicts.map((v) => v.track_id)));
  for (const id of ids) {
    let prev = null, hdg = null;
    for (let i = 0; i < frames.length; i++) {
      const v = byTrack[i].get(id);
      if (!v) { prev = null; continue; }
      const raw = v.position, trusted = v.trust_state === 'trusted';
      let p = raw;
      if (trusted) {
        let sx = 0, sy = 0, n = 0;
        for (let k = i - 2; k <= i + 2; k++) {
          const w = byTrack[k]?.get(id);
          if (!w || w.trust_state !== 'trusted' || distM(w.position, raw) > 40) continue;
          sx += w.position.lon; sy += w.position.lat; n++;
        }
        p = { lon: sx / n, lat: sy / n };
        if (prev && (raw.speed_mps ?? 1) < 0.6 && distM(prev, p) < 12) p = prev;  // parked: hold still
      }
      if (trusted && prev && distM(prev, p) > 2.5) hdg = bearing(prev, p);
      else if (!trusted || hdg == null) hdg = raw.track_deg ?? hdg ?? 0;
      disp[i].set(id, { lon: p.lon, lat: p.lat, hdg });
      prev = p;
    }
  }
  return disp;
}

const bundleCache = new Map();
async function loadBundle(sc) {
  if (!bundleCache.has(sc.base)) {
    const manifest = await getJson(sc.base + 'manifest.json');
    const text = await (await fetch(sc.base + manifest.frames_file)).text();
    const frames = text.split('\n').filter(Boolean).map((l) => JSON.parse(l));
    const byTrack = frames.map((f) => new Map(f.verdicts.map((v) => [v.track_id, v])));
    bundleCache.set(sc.base, { manifest, frames, byTrack, disp: displayTrack(frames, byTrack),
      source: sc.real ? 'Pipeline replay bundle (module 6)' : 'Simulated scenario' });
  }
  return bundleCache.get(sc.base);
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
  center: CFG.center, zoom: isPhone() ? 13.3 : CFG.zoom, minZoom: 11.5, maxZoom: 19.5,
  attributionControl: false, dragRotate: false, pitchWithRotate: false, touchPitch: false,
});
map.touchZoomRotate.disableRotation();
map.addControl(new maplibregl.AttributionControl({ compact: true }), 'bottom-right');

// Icons are never smaller than readable, and grow to their real size when zoomed in (a bus is a bus long).
function iconScale() {
  const mpp = 156543.03 * Math.cos(41.8 * Math.PI / 180) / 2 ** map.getZoom();  // metres per pixel
  const lo = isPhone() ? 1.15 : 1.5, loA = isPhone() ? 1.1 : 1.4;
  document.documentElement.style.setProperty('--s', Math.min(2.6, Math.max(lo, 0.375 / mpp)).toFixed(2));    // vehicle icons: 1 px = 0.375 m
  document.documentElement.style.setProperty('--sa', Math.min(3, Math.max(loA, 1.36 / mpp)).toFixed(2));    // aircraft: 28 px = 38 m
}
map.on('zoom', iconScale);
iconScale();

const VIEWS = {
  photo: { label: 'Photo', bg: '#2b3040', on: ['photo', 'rwy-line'] },
  schematic: { label: 'Schematic', bg: '#eef1f7', on: ['aprons', 'buildings', 'rwy-fill', 'rwy-line', 'routes-service', 'routes-taxi', 'stands', 'holding'] },
};
const BASE_LAYERS = ['photo', 'aprons', 'buildings', 'rwy-fill', 'rwy-line', 'routes-service', 'routes-taxi', 'stands', 'holding'];

function addLayers(L, photo) {
  map.addSource('photo', { type: 'raster', tileSize: 256, ...photo });
  for (const k of ['aprons', 'buildings', 'runways', 'routes', 'stands', 'holding_points']) map.addSource(k, { type: 'geojson', data: L[k] });
  for (const k of ['risk', 'trails']) map.addSource(k, { type: 'geojson', data: empty() });
  const zw = (a, b) => ['interpolate', ['linear'], ['zoom'], 13, a, 17.5, b];
  map.addLayer({ id: 'photo', type: 'raster', source: 'photo' });
  map.addLayer({ id: 'aprons', type: 'fill', source: 'aprons', paint: { 'fill-color': '#dbe4f6' } });
  map.addLayer({ id: 'buildings', type: 'fill', source: 'buildings', paint: { 'fill-color': '#c9ced9', 'fill-outline-color': '#b3b9c7' } });
  map.addLayer({ id: 'rwy-fill', type: 'fill', source: 'runways', paint: { 'fill-color': '#1f2540' } });
  map.addLayer({ id: 'rwy-line', type: 'line', source: 'runways', paint: { 'line-color': '#ffffff', 'line-width': 2 } });
  map.addLayer({ id: 'routes-service', type: 'line', source: 'routes', filter: ['==', ['get', 'kind'], 'service_road'], layout: { 'line-cap': 'round' },
    paint: { 'line-color': '#c08a5a', 'line-width': zw(1.2, 6) } });
  map.addLayer({ id: 'routes-taxi', type: 'line', source: 'routes', filter: ['==', ['get', 'kind'], 'taxiway'], layout: { 'line-cap': 'round' },
    paint: { 'line-color': '#2f6bff', 'line-width': zw(2, 10) } });
  map.addLayer({ id: 'stands', type: 'circle', source: 'stands', minzoom: 14.5, paint: { 'circle-radius': 4, 'circle-color': '#3d4766', 'circle-stroke-color': '#fff', 'circle-stroke-width': 1 } });
  map.addLayer({ id: 'holding', type: 'circle', source: 'holding_points', minzoom: 13.5,
    paint: { 'circle-radius': 5, 'circle-color': COLORS.red, 'circle-stroke-color': '#fff', 'circle-stroke-width': 1.5 } });
  map.addLayer({ id: 'trails', type: 'line', source: 'trails', layout: { 'line-cap': 'round' }, paint: { 'line-color': ['get', 'c'], 'line-opacity': ['get', 'o'], 'line-width': 3 } });
  map.addLayer({ id: 'risk-forecast', type: 'line', source: 'risk', filter: ['==', ['get', 'kind'], 'forecast'], layout: { 'line-cap': 'round' },
    paint: { 'line-color': '#e8368a', 'line-width': 3, 'line-dasharray': [1.5, 1.5] } });
  map.on('click', (e) => {
    if (S.view === 'schematic') return placeInfo(e.lngLat, e.point);
    if (!e.defaultPrevented) { closeImpact(); if (S.sel) select(null); }
  });
}

function applyView(view) {
  S.view = view;
  document.body.classList.toggle('view-photo', view === 'photo');
  document.body.classList.toggle('view-schematic', view === 'schematic');
  map.setPaintProperty('bg', 'background-color', VIEWS[view].bg);
  for (const id of BASE_LAYERS) map.setLayoutProperty(id, 'visibility', VIEWS[view].on.includes(id) ? 'visible' : 'none');
  map.setPaintProperty('rwy-line', 'line-width', view === 'photo' ? 1.8 : 2.5);
  S.popup?.remove();
  renderViews();
}

// ---- schematic: what is this place? ------------------------------------------------------------

const PLACE = {
  holding: (p) => [`Holding point ${p.ref || ''}`.trim(), 'Stop line before a runway: aircraft and vehicles wait here for clearance.'],
  stands: (p) => [`Stand ${p.ref || ''}`.trim(), 'Parking spot for one aircraft: boarding, fuel, catering and baggage happen here.'],
  'rwy-fill': (p) => [`Runway ${p.ref || ''}`.trim(), 'Where aircraft take off and land. Nobody enters without clearance from the tower.'],
  'routes-taxi': (p) => [p.ref ? `Taxiway ${p.ref}` : 'Taxiway', 'Lane for aircraft moving between the runways and the stands.'],
  'routes-service': (p) => [p.ref ? `Service road (${p.ref})` : 'Service road', 'Airside road for service vehicles: tractors, buses, fuel and catering trucks.'],
  aprons: (p) => [p.ref ? `Apron ${p.ref}` : (p.name || 'Apron'), 'Area where aircraft park and are serviced; vehicles keep to the marked lanes.'],
  buildings: (p) => [p.name || 'Building', p.aeroway === 'terminal' ? 'Passenger terminal.' : p.aeroway === 'hangar' ? 'Aircraft hangar.' : 'Airport building.'],
};
const PLACE_ORDER = ['holding', 'stands', 'rwy-fill', 'routes-taxi', 'routes-service', 'buildings', 'aprons'];

function placeAt(point) {
  const box = [[point.x - 7, point.y - 7], [point.x + 7, point.y + 7]];
  const hits = map.queryRenderedFeatures(box, { layers: PLACE_ORDER });
  for (const id of PLACE_ORDER) { const f = hits.find((h) => h.layer.id === id); if (f) return PLACE[id](f.properties || {}); }
  return ['Open ground', 'Grass or unmarked area inside the airport.'];
}

function placeInfo(lngLat, point, title) {
  const [name, what] = placeAt(point);
  S.popup?.remove();
  S.popup = new maplibregl.Popup({ closeButton: true, maxWidth: '280px', offset: 12 }).setLngLat(lngLat)
    .setHTML(`<div class="place">${title ? `<b>${esc(title)}</b>on ` : ''}<b>${esc(name)}</b>${esc(what)}
      <div class="coords">${lngLat.lat.toFixed(5)}° N, ${lngLat.lng.toFixed(5)}° E</div></div>`).addTo(map);
}

// ---- markers ------------------------------------------------------------------------------

function markerFor(v) {
  let m = S.markers.get(v.track_id);
  if (m) return m;
  const wrap = document.createElement('div');
  wrap.innerHTML = `<div class="trk"><div class="ring"></div><div class="icon">${iconFor(v)}</div><div class="tag"></div></div>`;
  const el = wrap.firstElementChild;
  el.addEventListener('click', (e) => {
    e.stopPropagation();
    if (S.view === 'schematic') {
      const p = S.pos.get(v.track_id);
      return placeInfo({ lng: p.lon, lat: p.lat }, map.project([p.lon, p.lat]), nameOf(S.byTrack[S.idx].get(v.track_id) || v));
    }
    select({ kind: 'track', id: v.track_id });
  });
  const marker = new maplibregl.Marker({ element: wrap, anchor: 'center' }).setLngLat([v.position.lon, v.position.lat]).addTo(map);
  m = { marker, wrap, el, icon: el.querySelector('.icon'), tag: el.querySelector('.tag') };
  S.markers.set(v.track_id, m);
  return m;
}

function styleMarkers(frame) {
  const causes = new Set(S.items.filter((it) => it.kind === 'track' && headline(it)).map((it) => it.id));
  const present = new Set();
  for (const v of frame.verdicts) {
    present.add(v.track_id);
    const m = markerFor(v);
    const sel = (S.sel?.kind === 'track' && S.sel.id === v.track_id) || S.sel2 === v.track_id;
    m.el.className = ['trk', v.domain, `c-${v.asset_class}`, `s-${v.trust_state}`, v.confidence_level === 'low' ? 'conf-low' : '',
      causes.has(v.track_id) ? 'cause' : '', sel ? 'sel' : '', shown(v) ? '' : 'hidden'].join(' ');
    m.tag.textContent = nameOf(v);
    const d = S.disp[S.idx].get(v.track_id);
    m.icon.style.transform = `rotate(${d ? d.hdg : v.position.track_deg || 0}deg)`;
    m.wrap.style.zIndex = sel ? 40 : causes.has(v.track_id) ? 30 : 10;
  }
  for (const [id, m] of S.markers) if (!present.has(id)) m.el.classList.add('hidden');
}

function moveMarkers() {
  const a = S.disp[S.idx], b = S.disp[S.idx + 1];
  if (!a) return;
  const f0 = S.frames[S.idx], f1 = S.frames[S.idx + 1];
  const f = f1 ? Math.min(1, Math.max(0, (S.t - f0.t) / (f1.t - f0.t))) : 0;
  for (const [id, p] of a) {
    const q = b && b.get(id);
    const pos = q && distM(p, q) < JUMP_M ? { lon: p.lon + (q.lon - p.lon) * f, lat: p.lat + (q.lat - p.lat) * f } : p;
    S.pos.set(id, pos);
    S.markers.get(id)?.marker.setLngLat([pos.lon, pos.lat]);
  }
}

function drawTrails() {
  const feats = [], from = Math.max(0, S.idx - TRAIL_FRAMES);
  for (const v of S.frames[S.idx].verdicts) {
    if (!shown(v)) continue;
    let prev = null;
    for (let i = from; i <= S.idx; i++) {
      const w = S.byTrack[i].get(v.track_id), p = S.disp[i].get(v.track_id);
      if (!w || !p) { prev = null; continue; }
      if (prev) {
        const c = w.trust_state === 'untrusted' ? COLORS.red : w.trust_state === 'caution' ? COLORS.amber : (v.domain === 'aircraft' ? COLORS.blue : TYPE_COLOR[v.asset_class] || COLORS.blue);
        feats.push({ type: 'Feature', properties: { c, o: 0.08 + 0.45 * (i - from) / Math.max(1, S.idx - from) }, geometry: { type: 'LineString', coordinates: [[prev.lon, prev.lat], [p.lon, p.lat]] } });
      }
      prev = p;
    }
  }
  map.getSource('trails').setData({ type: 'FeatureCollection', features: feats });
}

function drawRisk(frame) {
  map.getSource('risk').setData({ type: 'FeatureCollection', features: frame.risk_zones.features.filter((f) => f.properties.kind !== 'static') });
  S.fcLabels.forEach((m) => m.remove());
  // forecasts into a live interference area only; most forecasts point at static building shadows, not interference
  const live = new Set(frame.risk_zones.features.filter((f) => f.properties.kind === 'live').map((f) => f.properties.risk_zone_id));
  const soonest = frame.risk_zones.features.filter((f) => f.properties.kind === 'forecast' && live.has(f.properties.enters_risk_zone_id))
    .sort((a, b) => a.properties.eta_s - b.properties.eta_s).slice(0, 3);
  map.getSource('risk').setData({ type: 'FeatureCollection', features: soonest });
  S.fcLabels = soonest.map((f) => {
    const el = document.createElement('div');
    el.className = 'fc-label';
    el.textContent = `Enters interference area in ${Math.round(f.properties.eta_s)} s`;
    const c = f.geometry.coordinates;
    return new maplibregl.Marker({ element: el, anchor: 'left', offset: [10, 0] }).setLngLat(c[c.length - 1]).addTo(map);
  });
}

// ---- alerts -------------------------------------------------------------------------------

function alertsAt(frame) {
  const items = [], areas = new Map();
  for (const v of frame.verdicts) {
    if (!isAlert(v) || !shown(v)) continue;
    if (v.area_alert_id) {
      const a = areas.get(v.area_alert_id) || { kind: 'area', id: v.area_alert_id, members: [], sev: 'none', score: 0 };
      a.members.push(v);
      if (SEV_RANK[v.severity.level] > SEV_RANK[a.sev]) a.sev = v.severity.level;
      a.score = Math.max(a.score, v.severity.score);
      areas.set(v.area_alert_id, a);
    } else items.push({ kind: 'track', id: v.track_id, v, sev: v.severity.level, score: v.severity.score });
  }
  for (const a of areas.values()) {
    a.zone = frame.risk_zones.features.find((f) => f.properties.area_alert_id === a.id);
    items.push(a);
  }
  return items.sort((x, y) => SEV_RANK[y.sev] - SEV_RANK[x.sev] || (y.kind === 'area') - (x.kind === 'area') || y.score - x.score);
}

function alertSince(it) {
  let i = S.idx;
  const test = it.kind === 'area' ? (k) => S.frames[k].verdicts.some((v) => v.area_alert_id === it.id) : (k) => { const v = S.byTrack[k].get(it.id); return v && isAlert(v); };
  while (i > 0 && test(i - 1)) i--;
  return S.t - S.frames[i].t;
}

// Worth interrupting the operator: an area event; the vehicle the story is about; anything else only if
// high or critical. "Reduced accuracy" alone never interrupts.
const isFocus = (it) => it.kind === 'track' && (S.cur?.focus || []).includes(it.id);
const headline = (it) => it.kind === 'area' || (quad(it.v) !== 'caution' && (S.cur?.focus?.length ? isFocus(it) : SEV_RANK[it.sev] >= 3));
const areaTitle = (a) => (a.members[0]?.cause === 'gnss_anomaly' ? 'Warning: GNSS degraded across the airport' : 'Warning: possible GNSS jamming');

// ---- the main notification ------------------------------------------------------------------

let audio = null;
const unlockAudio = () => { try { audio = audio || new AudioContext(); audio.resume(); } catch (e) { /* no sound */ } };
window.addEventListener('pointerdown', unlockAudio, { once: true });
function beep(critical) {
  if (!audio || audio.state !== 'running') return;
  const t = audio.currentTime;
  [[0, critical ? 988 : 880], [0.2, critical ? 740 : 660], [0.4, critical ? 988 : 880]].forEach(([d, hz]) => {
    const o = audio.createOscillator(), g = audio.createGain();
    o.type = 'triangle'; o.frequency.value = hz;
    g.gain.setValueAtTime(0.0001, t + d); g.gain.exponentialRampToValueAtTime(0.3, t + d + 0.02); g.gain.exponentialRampToValueAtTime(0.0001, t + d + 0.18);
    o.connect(g).connect(audio.destination); o.start(t + d); o.stop(t + d + 0.2);
  });
}

function renderNotify() {
  const top = S.items.find((it) => headline(it) && isFocus(it)) || S.items.find(headline) || null;
  S.top = top;
  const n = $('notify');
  if (!top) { n.hidden = true; S.notified = null; return; }
  const critical = top.sev === 'critical';
  n.classList.toggle('critical', critical);
  document.body.classList.toggle('critical', critical);
  if (top.kind === 'area') {
    $('notify-title').textContent = areaTitle(top);
    $('notify-sub').textContent = `${top.members.length} vehicles affected`;
  } else {
    $('notify-title').textContent = ISSUE_WORD[quad(top.v)] || 'Check position';
    $('notify-sub').textContent = `${nameOf(top.v)}${top.v.severity.zone_name ? ' · ' + top.v.severity.zone_name : ''}`;
  }
  const key = top.kind + top.id;
  if (S.notified !== key) {
    S.notified = key;
    n.hidden = false;
    n.style.animation = 'none'; void n.offsetWidth; n.style.animation = '';
    beep(critical);
    keepInView();
    if (top.kind === 'area' && S.view === 'photo') openImpact(top.id);
  }
}

function topTarget() {
  const top = S.top;
  if (!top) return null;
  if (top.kind === 'track') return S.pos.get(top.id);
  const ring = top.zone?.geometry?.coordinates?.[0];
  if (ring) { const [x, y] = ring.reduce(([a, b], [c, d]) => [a + c, b + d], [0, 0]); return { lon: x / ring.length, lat: y / ring.length }; }
  const ps = top.members.map((v) => S.pos.get(v.track_id)).filter(Boolean);
  return ps.length ? { lon: ps.reduce((s, p) => s + p.lon, 0) / ps.length, lat: ps.reduce((s, p) => s + p.lat, 0) / ps.length } : null;
}

// a new alert whose vehicle is off-screen: pan to it, keeping the zoom (no zooming in)
function keepInView() {
  const t = topTarget();
  if (!t || S.view !== 'photo') return;
  const q = map.project([t.lon, t.lat]), c = map.getContainer();
  const pad = 90, right = c.clientWidth - (S.panelOpen && !isPhone() ? 430 : 60);
  if (q.x < pad || q.y < 140 || q.x > right || q.y > c.clientHeight - 120) map.easeTo({ center: [t.lon, t.lat], duration: 1200 });
}

function drawLink() {
  const n = $('notify'), path = $('link-path'), dot = $('link-dot');
  const target = !n.hidden && S.view === 'photo' && !(isPhone() && S.panelOpen) ? topTarget() : null;
  if (!target) { path.setAttribute('d', ''); dot.setAttribute('r', 0); return; }
  const r = n.getBoundingClientRect(), q = map.project([target.lon, target.lat]);
  const x1 = r.left + r.width / 2, y1 = r.bottom;
  path.setAttribute('d', `M${x1},${y1} C${x1},${(y1 + q.y) / 2} ${q.x},${(y1 + q.y) / 2} ${q.x},${q.y}`);
  dot.setAttribute('cx', q.x); dot.setAttribute('cy', q.y); dot.setAttribute('r', 7);
}

$('notify').addEventListener('click', () => {
  const top = S.top;
  if (!top) return;
  if (top.kind === 'track') select({ kind: 'track', id: top.id });
  else openImpact(top.id);
});

// ---- panel: alert list or the vehicle dashboard -------------------------------------------------

function renderPanel() {
  const frame = S.frames[S.idx];
  if (!frame) return;
  const items = S.items;
  $('tab-count').hidden = items.length === 0;
  $('tab-count').textContent = items.length;
  const total = frame.verdicts.filter(shown).length, st = $('status');
  st.textContent = items.length ? `${items.length} need${items.length === 1 ? 's' : ''} attention` : `All ${total} positions trusted`;
  st.classList.toggle('warn', items.length > 0);
  document.body.classList.toggle('dash', S.sel?.kind === 'track');
  if (!S.panelOpen) return;
  $('panel-body').innerHTML = S.sel?.kind === 'track' ? dashboard(S.sel.id) : alertList(items);
}

function alertList(items) {
  const close = `<button class="p-close" data-close aria-label="Hide">${isPhone() ? '×' : '›'}</button>`;
  if (!items.length) return `${close}<h2 class="p-title">Alerts</h2><div class="empty"><strong>All clear</strong>Every position can be trusted.</div>`;
  return `${close}<h2 class="p-title">Alerts</h2>` + items.map((it, k) => {
    if (it.kind === 'area') {
      return `<button class="alert" data-k="${k}"><span class="bar sev-${it.sev}"></span><span><div class="a-what">${esc(areaTitle(it).replace('Warning: ', ''))}</div>
        <div class="a-meta">${it.members.length} vehicles · for ${forTime(alertSince(it))}</div></span></button>`;
    }
    const v = it.v;
    return `<button class="alert" data-k="${k}"><span class="bar sev-${it.sev}"></span><span><div class="a-what">${esc(ISSUE_WORD[quad(v)] || 'Check position')}</div>
      <div class="a-meta">${esc(nameOf(v))}${v.severity.zone_name ? ' · ' + esc(v.severity.zone_name) : ''} · for ${forTime(alertSince(it))}</div></span></button>`;
  }).join('');
}

const barColor = (x) => (x < 40 ? COLORS.red : x < 70 ? COLORS.amber : '#9aa3bd');
const bar = (label, x, major) => `<div class="dim${major ? ' major' : ''}"><span>${label}</span><span class="track"><span class="fill" style="width:${x}%;background:${barColor(x)}"></span></span><span class="val">${Math.round(x)} / 100</span></div>`;

function dashboard(id, second = false) {
  const v = S.byTrack[S.idx].get(id);
  const head = second ? '<button class="p-close" data-close2 aria-label="Close">×</button>'
    : `<button class="p-close" data-close aria-label="Hide">${isPhone() ? '×' : '›'}</button><button class="back" data-back>‹ All alerts</button>`;
  if (!v) return `${head}<div class="empty">No position for this vehicle right now.</div>`;
  const q = quad(v), p = v.position;
  const conf = { low: 1, medium: 2, high: 3 }[v.confidence_level];
  const dims = Object.entries(v.dimensions).map(([k, x]) => bar(k[0].toUpperCase() + k.slice(1), x)).join('');
  return `${head}
    <div class="d-head"><div class="d-name">${esc(nameOf(v))}</div></div>
    <div class="pinkbox"><div class="pb-label">Confidence</div>
      <div class="pb-main">${v.confidence_level[0].toUpperCase() + v.confidence_level.slice(1)} <small>· ${Math.round(v.confidence * 100)} %</small>
      <span class="meter">${[1, 2, 3].map((k) => `<i class="${k <= conf ? 'on' : ''}"></i>`).join('')}</span></div></div>
    <div class="bars">${bar('Integrity', v.integrity, true)}${bar('Normality', v.normality, true)}<div class="dim-sep"></div>${dims}</div>
    <div class="pinkbox"><div class="pb-label">Likely cause</div>
      <div class="pb-main">${esc(CAUSE_TEXT[v.cause])} <small>· ${Math.round(v.cause_probs[v.cause] * 100)} %</small></div></div>
    <div class="label">Integrity, last 5 min</div>${sparkline(id)}
    <div class="dash-end">
      ${isAlert(v) ? `<div class="label">What to do</div><div class="todo">${esc(v.action.text)}</div>` : ''}
      ${isAlert(v) ? `<button class="impact-btn" data-impact="${esc(v.area_alert_id || '')}" data-from="${esc(v.track_id)}">Check impact</button>` : ''}
    </div>`;
}

function sparkline(id) {
  const from = Math.max(0, S.idx - HISTORY_FRAMES), pts = [];
  for (let i = from; i <= S.idx; i++) { const v = S.byTrack[i].get(id); if (v) pts.push([i, v.integrity]); }
  if (pts.length < 2) return '<svg class="spark"></svg>';
  const W = 340, H = 44, x = (i) => ((i - from) / Math.max(1, S.idx - from)) * (W - 6) + 3, y = (val) => H - 3 - (val / 100) * (H - 6);
  const [li, lv] = pts[pts.length - 1];
  return `<svg class="spark" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none"><line x1="0" x2="${W}" y1="${y(40)}" y2="${y(40)}" stroke="#f3d3d4" stroke-dasharray="4 4"/>
    <polyline points="${pts.map(([i, val]) => `${x(i).toFixed(1)},${y(val).toFixed(1)}`).join(' ')}" fill="none" stroke="${COLORS.ink}" stroke-width="2" vector-effect="non-scaling-stroke"/>
    <circle cx="${x(li)}" cy="${y(lv)}" r="3.5" fill="${barColor(lv)}"/></svg>`;
}

// ---- impact card: the vehicles hit by an area event -------------------------------------------------

const NEAR_M = 400;
function openImpact(areaId, trackId) { S.impact = areaId ? { area: areaId } : { near: trackId }; document.body.classList.add('impact-open'); renderImpact(); }
function closeImpact() { S.impact = null; $('impact').hidden = true; document.body.classList.remove('impact-open'); }
function renderImpact() {
  const box = $('impact');
  if (!S.impact) { box.hidden = true; return; }
  const vs = S.frames[S.idx].verdicts;
  let members, label;
  if (S.impact.area) {
    members = vs.filter((v) => v.area_alert_id === S.impact.area).sort((a, b) => b.confidence - a.confidence);
    label = 'Impacted vehicles';
  } else {
    const c = S.pos.get(S.impact.near);
    members = c ? vs.filter((v) => v.track_id !== S.impact.near && S.pos.get(v.track_id) && distM(c, S.pos.get(v.track_id)) < NEAR_M)
      .sort((a, b) => distM(c, S.pos.get(a.track_id)) - distM(c, S.pos.get(b.track_id))) : [];
    label = `Vehicles within ${NEAR_M} m`;
  }
  box.hidden = false;
  $('impact-body').innerHTML = `<div class="i-label">${members.length ? label : 'No vehicles nearby'}</div>` +
    members.map((v) => `<button class="imp" data-track="${esc(v.track_id)}">${esc(nameOf(v))}<b>${Math.round(v.confidence * 100)} %</b></button>`).join('');
}
$('impact-close').addEventListener('click', closeImpact);
$('impact-body').addEventListener('click', (e) => {
  const b = e.target.closest('[data-track]');
  if (!b) return;
  if (S.sel?.kind === 'track' && S.sel.id !== b.dataset.track) { S.sel2 = b.dataset.track; renderPanel2(); styleMarkers(S.frames[S.idx]); }
  else select({ kind: 'track', id: b.dataset.track });
});

function renderPanel2() {
  const box = $('panel2');
  box.hidden = !S.sel2;
  if (S.sel2) $('panel2-body').innerHTML = dashboard(S.sel2, true);
}
$('panel2-body').addEventListener('click', (e) => {
  if (e.target.closest('[data-close2]')) { S.sel2 = null; renderPanel2(); return styleMarkers(S.frames[S.idx]); }
  const imp = e.target.closest('[data-impact]');
  if (imp) return imp.dataset.impact ? openImpact(imp.dataset.impact) : openImpact(null, imp.dataset.from);
});

// ---- selection --------------------------------------------------------------------------------

function select(sel) {
  S.sel = sel;
  S.sel2 = null;
  renderPanel2();
  if (sel) openPanel(true);
  styleMarkers(S.frames[S.idx]);
  renderPanel();
}

function openPanel(open) {
  S.panelOpen = open;
  document.body.classList.toggle('panel-open', open);
  $('panel').setAttribute('aria-hidden', String(!open));
  renderPanel();
}

$('panel-tab').addEventListener('click', () => openPanel(!S.panelOpen));
$('panel-body').addEventListener('click', (e) => {
  if (e.target.closest('[data-close]')) { S.sel = null; S.sel2 = null; renderPanel2(); return openPanel(false); }
  if (e.target.closest('[data-back]')) return select(null);
  const imp = e.target.closest('[data-impact]');
  if (imp) return imp.dataset.impact ? openImpact(imp.dataset.impact) : openImpact(null, imp.dataset.from);
  const a = e.target.closest('.alert');
  if (a) {
    const it = S.items[Number(a.dataset.k)];
    if (it?.kind === 'area') openImpact(it.id); else if (it) select({ kind: 'track', id: it.id });
  }
});

// ---- views menu + key -----------------------------------------------------------------------------

const THUMBS = {
  photo: `<svg viewBox="0 0 84 62"><rect width="84" height="62" fill="#5b6b4f"/><path d="M0 40 L84 18 L84 30 L0 52Z" fill="#3d4148"/><rect x="46" y="38" width="30" height="16" fill="#7c8577"/>
    <rect x="8" y="8" width="22" height="14" fill="#8a8c84"/><path d="M0 46 L84 24" stroke="#e8e8e8" stroke-dasharray="4 3"/><circle cx="56" cy="22" r="3" fill="#2f6bff" stroke="#fff"/></svg>`,
  schematic: `<svg viewBox="0 0 84 62"><rect width="84" height="62" fill="#eef1f7"/><rect x="40" y="34" width="36" height="20" rx="2" fill="#dbe4f6"/>
    <path d="M0 40 L84 18 L84 27 L0 49Z" fill="#1f2540"/><path d="M6 10 Q 40 30 80 6" stroke="#2f6bff" stroke-width="4" fill="none"/><path d="M10 58 L60 30" stroke="#c08a5a" stroke-width="3"/><circle cx="30" cy="18" r="3" fill="#e5383b"/></svg>`,
};
function renderViews() {
  $('views-thumb').innerHTML = THUMBS[S.view];
  $('views-label').textContent = VIEWS[S.view].label;
  $('view-grid').innerHTML = Object.entries(VIEWS).map(([k, v]) => `<button class="view-opt ${k === S.view ? 'on' : ''}" data-view="${k}"><span class="thumb">${THUMBS[k]}</span>${v.label}</button>`).join('');
}
$('key').innerHTML = [[COLORS.blue, 'Aircraft'], [TYPE_COLOR.bus, 'Bus'], [TYPE_COLOR.fuel_truck, 'Fuel'], [TYPE_COLOR.catering_truck, 'Catering'],
  [TYPE_COLOR.baggage_tractor, 'Tractor'], [TYPE_COLOR.follow_me, 'Follow-me'], [TYPE_COLOR.sar_vehicle, 'SAR'], [COLORS.amber, 'Reduced accuracy'],
  ['#fff;box-shadow:inset 0 0 0 2px #e5383b', 'Unreliable']].map(([c, l]) => `<span><i style="background:${c}"></i>${l}</span>`).join('');
const toggleMenu = (btn, menu, open) => { menu.hidden = !open; btn.setAttribute('aria-expanded', String(open)); };
$('views-btn').addEventListener('click', (e) => { e.stopPropagation(); toggleMenu($('views-btn'), $('views-menu'), $('views-menu').hidden); });
$('view-grid').addEventListener('click', (e) => { const b = e.target.closest('[data-view]'); if (b) applyView(b.dataset.view); });
for (const [id, key] of [['show-aircraft', 'aircraft'], ['show-vehicles', 'vehicles']]) {
  $(id).addEventListener('change', (e) => { S.show[key] = e.target.checked; onFrame(); });
}

// ---- demos: each one plays as a story, starting calm ---------------------------------------------------

function renderDemo() {
  $('demo-events').innerHTML = S.scenarios.map((sc, k) => `<button class="menu-item${S.cur === sc ? ' on' : ''}" data-ev="${k}">${esc(sc.title)}<small>${esc(sc.category || '')}${sc.night ? ' · night' : ''}${sc.fog ? ' · fog' : ''}</small></button>`).join('');
  $('demo-play').textContent = S.playing ? 'Pause' : 'Play';
  $('demo-source').textContent = S.source;
}

// A demo starts a few seconds before its banner fires: calm first, but no long wait.
const LEAD_S = 4;
function storyStart(sc) {
  if (['real_scene', 'normal_ops'].includes(sc.id)) return sc.t_start;
  const M = S.manifest, i0 = Math.max(0, Math.floor((sc.onset_t - M.t_start) / M.step_s) - 2);
  const k = S.frames.findIndex((f, i) => i >= i0 && alertsAt(f).some(headline));  // same rule as the banner
  return Math.max(M.t_start, (k >= 0 ? S.frames[k].t : sc.onset_t) - LEAD_S);
}

async function openScenario(sc, overview = true) {
  Object.assign(S, await loadBundle(sc));
  S.cur = sc;
  S.markers.forEach((m) => m.marker.remove());  // track ids repeat across scenarios with other vehicle types
  S.markers.clear();
  S.sel = null; S.sel2 = null; S.notified = null; S.top = null;
  closeImpact();
  openPanel(false);
  S.popup?.remove();
  S.t = storyStart(sc);
  S.idx = -1;
  S.playing = true;
  tick(0);
  if (overview) map.easeTo({ center: CFG.center, zoom: isPhone() ? 13.3 : CFG.zoom, duration: 700 });
  renderDemo();
}

$('demo-btn').addEventListener('click', (e) => { e.stopPropagation(); toggleMenu($('demo-btn'), $('demo-menu'), $('demo-menu').hidden); });
$('demo-events').addEventListener('click', (e) => {
  const b = e.target.closest('[data-ev]');
  if (!b) return;
  toggleMenu($('demo-btn'), $('demo-menu'), false);
  openScenario(S.scenarios[Number(b.dataset.ev)]);
});
$('demo-play').addEventListener('click', () => { S.playing = !S.playing; renderDemo(); });
$('demo-restart').addEventListener('click', () => openScenario(S.cur, false));
document.addEventListener('click', (e) => {
  if (!e.target.closest('#views')) toggleMenu($('views-btn'), $('views-menu'), false);
  if (!e.target.closest('#demo')) toggleMenu($('demo-btn'), $('demo-menu'), false);
});

// ---- clock ---------------------------------------------------------------------------------------

function onFrame() {
  const frame = S.frames[S.idx];
  S.items = alertsAt(frame);
  styleMarkers(frame);
  drawRisk(frame);
  drawTrails();
  renderPanel();
  renderPanel2();
  renderImpact();
  renderNotify();
  $('clock').textContent = `${hhmmss(frame.t)} UTC`;
}

let last = performance.now();
function tick(now) {
  const dt = now ? Math.min(0.25, (now - last) / 1000) : 0;
  last = now || performance.now();
  if (S.manifest) {
    if (S.playing && now) S.t += dt;
    if (S.t > S.manifest.t_end) { S.t = storyStart(S.cur); S.notified = null; }  // loop the story
    const i = Math.min(S.frames.length - 1, Math.max(0, Math.floor((S.t - S.manifest.t_start) / S.manifest.step_s)));
    if (i !== S.idx) { S.idx = i; moveMarkers(); onFrame(); }
    moveMarkers();
    drawLink();
  }
  if (now) requestAnimationFrame(tick);
}

// ---- start ---------------------------------------------------------------------------------------

(async function start() {
  try {
    const [scenarios, photo, L] = await Promise.all([
      loadScenarios(), photoTiles(),
      Promise.all(['aprons', 'buildings', 'runway_areas', 'routes', 'stands', 'holding_points'].map(loadLayer))
        .then(([aprons, buildings, runways, routes, stands, holding_points]) => ({ aprons, buildings, runways, routes, stands, holding_points })),
    ]);
    S.scenarios = scenarios;
    if (!map.loaded()) await new Promise((r) => map.once('load', r));
    addLayers(L, photo);
    applyView('photo');
    await openScenario(scenarios.find((s) => s.id === 'real_scene') || scenarios.find((s) => s.id === 'normal_ops') || scenarios[0], false);
    requestAnimationFrame(tick);
  } catch (err) {
    $('status').textContent = err.message;
    $('status').classList.add('warn');
    console.error(err);
  }
})();
