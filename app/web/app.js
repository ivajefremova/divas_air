// Divas Security web map. Plays the pipeline's replay bundle (contract.ReplayManifest + one contract.ReplayFrame
// per line, src/divas_air/contract.py) like a live feed: a frame every 5 s, positions eased in between.
// Simulated scenarios (replay_fake/) are only a fallback when there is no bundle. Cameras are simulated.

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
const CAM_SVG = '<svg viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 7h12l2 3-2 3H3z"/><path d="M17 9l4-2v6l-4-2"/><path d="M7 13v4H4"/></svg>';
const iconFor = (v) => (v.domain === 'aircraft' ? PLANE : ICONS[v.asset_class] || ICONS.vehicle);

// ---- state --------------------------------------------------------------------------------

const S = {
  scenarios: [], cur: null, manifest: null, frames: [], byTrack: [], disp: [], source: '',
  t: 0, idx: -1, playing: true, view: 'photo', show: { aircraft: true, vehicles: true },
  impact: null, panelOpen: false, items: [], top: null, notified: null,
  markers: new Map(), pos: new Map(), fcLabels: [], popup: null, cameras: [], camMarkers: [], hasVideo: false, compare: [], camFor: {},
};
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const hhmmss = (t) => new Date(t * 1000).toISOString().slice(11, 19);
const forTime = (s) => (s < 60 ? `${Math.max(0, Math.round(s))} s` : `${Math.floor(s / 60)} min ${String(Math.round(s % 60)).padStart(2, '0')} s`);
const nameOf = (v) => v.callsign || (v.domain === 'aircraft'
  ? `${CLASS_NAME[v.asset_class] || 'Aircraft'} ${v.asset_id.toUpperCase()}`
  : `${CLASS_NAME[v.asset_class] || 'Vehicle'} ${(v.asset_id.match(/\d+/g) || [v.asset_id]).pop()}`);
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
  if (real) return list;  // pipeline demos only; simulated scenarios are a fallback when there is no bundle
  const idx = await getJson(CFG.scenarioIndex);
  const dir = CFG.scenarioIndex.replace(/index\.json$/, '');
  for (const sc of idx?.scenarios || []) list.push({ ...sc, base: dir + sc.dir + '/', category: `${sc.category} · simulated` });
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
  cameras: { label: 'Cameras', bg: '#eef1f7', on: ['aprons', 'buildings', 'rwy-fill', 'rwy-line', 'routes-service', 'routes-taxi', 'cam-cover', 'cam-edge'] },
};
const BASE_LAYERS = ['photo', 'aprons', 'buildings', 'rwy-fill', 'rwy-line', 'routes-service', 'routes-taxi', 'stands', 'holding', 'cam-cover', 'cam-edge'];

function addLayers(L, photo) {
  map.addSource('photo', { type: 'raster', tileSize: 256, ...photo });
  for (const k of ['aprons', 'buildings', 'runways', 'routes', 'stands', 'holding_points', 'camcover']) map.addSource(k, { type: 'geojson', data: L[k] });
  map.addSource('trails', { type: 'geojson', data: empty() });
  const zw = (a, b) => ['interpolate', ['linear'], ['zoom'], 13, a, 17.5, b];
  map.addLayer({ id: 'photo', type: 'raster', source: 'photo' });
  map.addLayer({ id: 'aprons', type: 'fill', source: 'aprons', paint: { 'fill-color': '#dbe4f6' } });
  map.addLayer({ id: 'buildings', type: 'fill', source: 'buildings', paint: { 'fill-color': '#c9ced9', 'fill-outline-color': '#b3b9c7' } });
  map.addLayer({ id: 'rwy-fill', type: 'fill', source: 'runways', paint: { 'fill-color': '#1f2540' } });
  map.addLayer({ id: 'rwy-line', type: 'line', source: 'runways', paint: { 'line-color': '#ffffff', 'line-width': 2 } });
  map.addLayer({ id: 'routes-service', type: 'line', source: 'routes', filter: ['==', ['get', 'kind'], 'service_road'], layout: { 'line-cap': 'round' },
    paint: { 'line-color': '#c08a5a', 'line-width': zw(1.2, 6) } });
  map.addLayer({ id: 'routes-taxi', type: 'line', source: 'routes', filter: ['==', ['get', 'kind'], 'taxiway'], layout: { 'line-cap': 'round' },
    paint: { 'line-color': '#16a34a', 'line-width': zw(2, 10) } });
  map.addLayer({ id: 'stands', type: 'circle', source: 'stands', minzoom: 14.5, paint: { 'circle-radius': 4, 'circle-color': '#3d4766', 'circle-stroke-color': '#fff', 'circle-stroke-width': 1 } });
  map.addLayer({ id: 'holding', type: 'circle', source: 'holding_points', minzoom: 13.5,
    paint: { 'circle-radius': 5, 'circle-color': COLORS.red, 'circle-stroke-color': '#fff', 'circle-stroke-width': 1.5 } });
  // simulated cameras: only the selected camera's view is drawn, in pink
  const none = ['==', ['get', 'camera_id'], ''];
  map.addLayer({ id: 'cam-cover', type: 'fill', source: 'camcover', filter: none, paint: { 'fill-color': COLORS.pink, 'fill-opacity': 0.35 } });
  map.addLayer({ id: 'cam-edge', type: 'line', source: 'camcover', filter: none, paint: { 'line-color': '#d12b7d', 'line-width': 1.5 } });
  map.addLayer({ id: 'trails', type: 'line', source: 'trails', layout: { 'line-cap': 'round' }, paint: { 'line-color': ['get', 'c'], 'line-opacity': ['get', 'o'], 'line-width': 3 } });
  map.on('click', (e) => {
    if (S.view === 'schematic') return placeInfo(e.lngLat, e.point);
    if (!e.defaultPrevented) closeImpact();
  });
}

function applyView(view) {
  S.view = view;
  for (const k of Object.keys(VIEWS)) document.body.classList.toggle(`view-${k}`, view === k);
  map.setPaintProperty('bg', 'background-color', VIEWS[view].bg);
  for (const id of BASE_LAYERS) map.setLayoutProperty(id, 'visibility', VIEWS[view].on.includes(id) ? 'visible' : 'none');
  map.setPaintProperty('rwy-line', 'line-width', view === 'photo' ? 1.8 : 2.5);
  S.popup?.remove();
  if (view !== 'cameras') { S.compare = S.compare.filter((k) => !k.startsWith('cam:')); renderCompare(); }
  highlightCamera();
  renderViews();
  if (S.frames.length) onFrame();
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
  return ['Open ground'];
}

const shortPlace = (name) => (name.length > 22 ? name.split(' ').slice(0, 2).join(' ') : name);
function placeInfo(lngLat, point) {
  const [name] = placeAt(point);
  S.popup?.remove();
  S.popup = new maplibregl.Popup({ closeButton: false, maxWidth: '320px', offset: 14 }).setLngLat(lngLat)
    .setHTML(`<div class="place"><b>${esc(shortPlace(name))}</b><div class="coords">${lngLat.lat.toFixed(5)}° N<br>${lngLat.lng.toFixed(5)}° E</div></div>`).addTo(map);
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
      return placeInfo({ lng: p.lon, lat: p.lat }, map.project([p.lon, p.lat]));
    }
    openWindow(v.track_id);
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
    const sel = S.compare.includes(v.track_id);
    m.el.className = ['trk', v.domain, `c-${v.asset_class}`, `s-${v.trust_state}`, v.confidence_level === 'low' ? 'conf-low' : '',
      causes.has(v.track_id) ? 'cause' : '', sel ? 'sel' : '', shown(v) && (S.view !== 'cameras' || isAlert(v)) ? '' : 'hidden'].join(' ');
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
    if (!shown(v) || (S.view === 'cameras' && !isAlert(v))) continue;
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

function drawRisk() {
  // Forecasts ("enters interference area in N s") are not shown on screen.
  S.fcLabels.forEach((m) => m.remove());
  S.fcLabels = [];
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
function unlockAudio() {  // browsers (iPhone especially) only allow sound started from a tap
  try {
    audio = audio || new (window.AudioContext || window.webkitAudioContext)();
    audio.resume();
    const src = audio.createBufferSource();
    src.buffer = audio.createBuffer(1, 1, 22050);
    src.connect(audio.destination);
    src.start(0);
  } catch (e) { /* no sound */ }
}
for (const ev of ['pointerdown', 'touchend', 'click']) window.addEventListener(ev, unlockAudio, { passive: true });
function beep(critical) {
  if (navigator.vibrate) navigator.vibrate(critical ? [200, 100, 200, 100, 200] : [200, 100, 200]);
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
    if (top.kind === 'area' && S.view === 'photo' && !isPhone()) openImpact(top.id);
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
  const top = isPhone() ? 150 : 110, bottom = c.clientHeight - (isPhone() && S.panelOpen ? c.clientHeight * 0.5 : 120);
  const right = c.clientWidth - (S.panelOpen && !isPhone() ? 560 : 60);
  const tooClose = map.getZoom() > (isPhone() ? 16 : 17);
  if (tooClose || q.x < 60 || q.y < top || q.x > right || q.y > bottom) {
    map.easeTo({ center: [t.lon, t.lat], zoom: tooClose ? (isPhone() ? 15.5 : 16) : map.getZoom(), duration: 1000,
      padding: { top: isPhone() ? 140 : 90, bottom: isPhone() && S.panelOpen ? c.clientHeight * 0.5 : 0, left: 0, right: S.panelOpen && !isPhone() ? 560 : 0 } });
  }
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
  // go straight to the issue: for jamming, to the first vehicle in the priority queue
  const id = top.kind === 'track' ? top.id : priorityOrder(top.members)[0]?.track_id;
  const t = id && S.pos.get(id);
  if (t) map.jumpTo({ center: [t.lon, t.lat], zoom: Math.max(map.getZoom(), 16.5),
    padding: { right: isPhone() ? 0 : (top.kind === 'area' ? 560 : 0), top: 90, left: 0, bottom: isPhone() ? innerHeight * 0.38 : 380 } });
  if (top.kind === 'area' && !isPhone()) openImpact(top.id);  // phones: one window at a time, the list opens via Check impact
  if (id) openWindow(id);
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
  if (!S.panelOpen) return;
  $('panel-body').innerHTML = alertList(items);
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

const barColor = (x) => (x < 40 ? COLORS.red : x < 70 ? COLORS.amber : '#4d8dff');
const bar = (label, x, major) => `<div class="dim${major ? ' major' : ''}"><span>${label}</span><span class="track"><span class="fill" style="width:${x}%;background:${barColor(x)}"></span></span><span class="val" data-v="${Math.round(x)}">${Math.round(x)} / 100</span></div>`;

const winClose = (key) => `<button class="cmp-x" data-cmpclose="${esc(key)}" aria-label="Close">×</button>`;

// vehicle window: horizontal, everything visible without scrolling
function dashboard(id) {
  const v = S.byTrack[S.idx].get(id), head = winClose(id);
  if (!v) return `${head}<div class="empty">No position for this vehicle right now.</div>`;
  const conf = { low: 1, medium: 2, high: 3 }[v.confidence_level];
  const dims = Object.entries(v.dimensions).map(([k, x]) => bar(k[0].toUpperCase() + k.slice(1), x)).join('');
  return `${head}
    <div class="dash-grid">
      <div class="col-a">
        <div class="d-head"><div class="d-name">${esc(nameOf(v))}</div></div>
        <div class="pinkbox"><div class="pb-label">Confidence</div>
          <div class="pb-main">${v.confidence_level[0].toUpperCase() + v.confidence_level.slice(1)}
          <span class="meter">${[1, 2, 3].map((k) => `<i class="${k <= conf ? 'on' : ''}"></i>`).join('')}</span></div></div>
        <div class="pinkbox"><div class="pb-label">Likely cause</div><div class="pb-main">${esc(CAUSE_TEXT[v.cause])}</div></div>
      </div>
      <div class="col-b">
        <div class="bars">${bar('Integrity', v.integrity, true)}${bar('Normality', v.normality, true)}<div class="dim-sep"></div>${dims}</div>
        <div class="label">Integrity, last 5 min</div>${sparkline(id)}
      </div>
    </div>
    ${isAlert(v) ? `<div class="dash-end"><div class="todo-wrap"><div class="label">What to do</div><div class="todo">${esc(v.action.text)}</div></div>
      <div class="btns"><button class="impact-btn cam-btn" data-checkcam="${esc(v.track_id)}">Check camera</button>
      <button class="impact-btn" data-impact="${esc(v.area_alert_id || '')}" data-from="${esc(v.track_id)}">Check impact</button></div></div>` : ''}`;
}

// ---- cameras (simulated) ----------------------------------------------------------------------

function inRing(p, ring) {  // point in polygon, lon/lat
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i], [xj, yj] = ring[j];
    if ((yi > p.lat) !== (yj > p.lat) && p.lon < ((xj - xi) * (p.lat - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

function addCameras(points, cover) {
  const rings = new Map(cover.features.map((f) => [f.properties.camera_id, f.geometry.coordinates[0]]));
  S.cameras = points.features.map((f) => ({ ...f.properties, coords: f.geometry.coordinates, ring: rings.get(f.properties.camera_id) }));
  for (const cam of S.cameras) {
    const el = document.createElement('div');
    el.className = `cam-pt${cam.status !== 'online' ? ' off' : ''}`;
    el.innerHTML = CAM_SVG;
    el.title = cam.camera_id;
    el.addEventListener('click', (e) => {
      e.stopPropagation();
      openWindow(`cam:${cam.camera_id}`);
    });
    S.camMarkers.push({ id: cam.camera_id, el, marker: new maplibregl.Marker({ element: el, anchor: 'center' }).setLngLat(cam.coords).addTo(map) });
  }
}

function highlightCamera() {
  if (!map.getLayer('cam-cover')) return;
  const ids = ['', ...S.compare.filter((k) => k.startsWith('cam:')).map((k) => k.slice(4))];
  const filter = ['in', ['get', 'camera_id'], ['literal', ids]];
  map.setFilter('cam-cover', filter);
  map.setFilter('cam-edge', filter);
  S.camMarkers.forEach((m) => m.el.classList.toggle('on', ids.includes(m.id)));
}

// The best camera for a flagged vehicle: an online camera whose view covers its position, closest first
// (night vision first at night); otherwise the nearest online camera.
function bestCamera(trackId) {
  const p = S.pos.get(trackId);
  if (!p) return null;
  const night = S.cur?.night;
  const online = S.cameras.filter((c) => c.status === 'online').map((c) => ({ c, d: distM({ lon: c.coords[0], lat: c.coords[1] }, p), sees: !!c.ring && inRing(p, c.ring) }));
  const rank = (x) => x.d - (night && x.c.infrared ? 1e4 : 0);
  const seeing = online.filter((x) => x.sees).sort((a, b) => rank(a) - rank(b));
  return seeing[0] || online.sort((a, b) => a.d - b.d)[0] || null;
}

function checkCamera(trackId) {
  const best = bestCamera(trackId);
  if (!best) return;
  S.camFor[best.c.camera_id] = { track: trackId, sees: best.sees, d: Math.round(best.d) };
  applyView('cameras');
  const p = S.pos.get(trackId), c = best.c.coords;
  const b = new maplibregl.LngLatBounds([p.lon, p.lat], [p.lon, p.lat]).extend(c);
  map.fitBounds(b, { padding: { top: 120, bottom: isPhone() ? innerHeight * 0.5 : 80, left: isPhone() ? 40 : 300, right: isPhone() ? 40 : 600 }, maxZoom: 15.8, duration: 800 });
  openWindow(`cam:${best.c.camera_id}`);
}

// camera window: horizontal, three columns (details | what it sees | footage), no scrolling
function cameraDash(id) {
  const cam = S.cameras.find((c) => c.camera_id === id);
  const head = winClose(`cam:${id}`);
  if (!cam) return head;
  const inView = cam.ring ? S.frames[S.idx].verdicts.filter((v) => isAlert(v) && S.pos.get(v.track_id) && inRing(S.pos.get(v.track_id), cam.ring)) : [];
  const footage = S.hasVideo
    ? '<video class="footage" src="media/camera.mp4" autoplay muted loop playsinline></video>'
    : `<div class="footage empty-feed">${CAM_SVG}<b>Live footage</b><span>Available once camera access is granted</span></div>`;
  const f = S.camFor[id], fv = f && S.byTrack[S.idx].get(f.track);
  const checking = fv ? `<div class="pinkbox"><div class="pb-label">Checking</div><div class="pb-main">${esc(nameOf(fv))}</div>
    <div class="pb-sub">${f.sees ? `In view · ${f.d} m away` : `Not in view · nearest camera, ${f.d} m away`}</div></div>` : '';
  const anomalies = inView.slice(0, 4).map((v) => `<button class="imp" data-track="${esc(v.track_id)}"><span class="who">${esc(nameOf(v))}</span><b>${esc(ISSUE_WORD[quad(v)] || 'Check')}</b></button>`).join('')
    + (inView.length > 4 ? `<div class="none">+${inView.length - 4} more</div>` : '');
  return `${head}
    <div class="cam-grid">
      <div>
        <div class="d-head"><div class="d-name">${esc(cam.camera_id)}</div></div>
        <div class="cam-label">${esc(cam.label)}</div>
        ${checking}
        <div class="facts2">
          <div><span>Range</span>${cam.range_m} m</div><div><span>Field of view</span>${cam.fov_deg}°</div>
          <div><span>Night vision</span>${cam.infrared ? 'Yes' : 'No'}</div><div><span>Status</span>${cam.status === 'online' ? 'Online' : 'Offline'}</div>
        </div>
      </div>
      <div>
        <div class="label">Sees</div>
        <div class="sees">${(cam.sees || []).slice(0, 6).map((x) => `<span>${esc(x)}</span>`).join('') || '<span>Nothing mapped</span>'}</div>
        <div class="label">Anomalies in view</div>
        ${anomalies || '<div class="none">None right now</div>'}
      </div>
      <div>${footage}</div>
    </div>`;
}

function sparkline(id) {
  const from = Math.max(0, S.idx - HISTORY_FRAMES), pts = [];
  for (let i = from; i <= S.idx; i++) { const v = S.byTrack[i].get(id); if (v) pts.push([i, v.integrity]); }
  if (pts.length < 2) return '<svg class="spark"></svg>';
  const W = 340, H = 44, x = (i) => ((i - from) / Math.max(1, S.idx - from)) * (W - 6) + 3, y = (val) => H - 3 - (val / 100) * (H - 6);
  const [li, lv] = pts[pts.length - 1];
  return `<svg class="spark" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none"><line x1="0" x2="${W}" y1="${y(40)}" y2="${y(40)}" stroke="#ff8a8c" stroke-dasharray="4 4"/>
    <polyline points="${pts.map(([i, val]) => `${x(i).toFixed(1)},${y(val).toFixed(1)}`).join(' ')}" fill="none" stroke="#e9ecf5" stroke-width="2" vector-effect="non-scaling-stroke"/>
    <circle cx="${x(li)}" cy="${y(lv)}" r="3.5" fill="${barColor(lv)}"/></svg>`;
}

// ---- impact card: the vehicles hit by an area event -------------------------------------------------

const NEAR_M = 400;
const ZONE_WORD = { taxiway: 'Taxiway', runway: 'Runway', holding: 'Holding point', service: 'Service road', stand: 'Stand', apron: 'Apron' };
const zoneWord = (v) => ZONE_WORD[Object.keys(ZONE_WORD).find((k) => (v.severity.zone_id || '').startsWith(k))] || 'Airside';
const moving = (v) => (v.position.speed_mps || 0) > 1;

// Priority among impacted vehicles, from pipeline fields only: severity level, zone criticality, moving before
// stopped, aircraft before vehicles, lower integrity first. Recovered vehicles sink to the bottom.
function priorityOrder(vs) {
  return [...vs].sort((a, b) => isAlert(b) - isAlert(a) || SEV_RANK[b.severity.level] - SEV_RANK[a.severity.level]
    || b.severity.zone_criticality - a.severity.zone_criticality || moving(b) - moving(a)
    || (b.domain === 'aircraft') - (a.domain === 'aircraft') || a.integrity - b.integrity);
}
const reason = (v) => (!isAlert(v) ? 'Recovered' : moving(v) ? `Moving · ${zoneWord(v)}` : `${zoneWord(v)} · stopped`);
function openImpact(areaId, trackId) {
  if (!(areaId && S.impact?.area === areaId)) S.impact = areaId ? { area: areaId, seen: new Set() } : { near: trackId };
  document.body.classList.add('impact-open');
  renderImpact();
}
function closeImpact() { S.impact = null; $('impact').hidden = true; document.body.classList.remove('impact-open'); }
function renderImpact() {
  const box = $('impact');
  if (!S.impact) { box.hidden = true; return; }
  const vs = S.frames[S.idx].verdicts;
  let members, label;
  if (S.impact.area) {
    members = priorityOrder(vs.filter((v) => v.area_alert_id === S.impact.area || S.impact.seen.has(v.track_id)));
    members.forEach((v) => S.impact.seen.add(v.track_id));  // a recovered vehicle stays listed, at the bottom
    label = 'Impacted vehicles';
  } else {
    const c = S.pos.get(S.impact.near);
    members = c ? vs.filter((v) => v.track_id !== S.impact.near && S.pos.get(v.track_id) && distM(c, S.pos.get(v.track_id)) < NEAR_M)
      .sort((a, b) => distM(c, S.pos.get(a.track_id)) - distM(c, S.pos.get(b.track_id))) : [];
    label = `Vehicles within ${NEAR_M} m`;
  }
  box.hidden = false;
  const level = (v) => v.confidence_level[0].toUpperCase() + v.confidence_level.slice(1);
  const TOP = 5, more = members.length - TOP, shownRows = S.impact.all ? members : members.slice(0, TOP);
  box.style.setProperty('--cols', shownRows.length > 10 ? 3 : shownRows.length > 5 ? 2 : 1);  // wider, not taller
  $('impact-body').innerHTML = `<div class="i-label">${members.length ? label : 'No vehicles nearby'}</div><div class="imp-grid">` +
    shownRows.map((v, k) => `<button class="imp${k < 3 && isAlert(v) ? ' top' : ''}${isAlert(v) ? '' : ' done'}" data-track="${esc(v.track_id)}">
      <span class="rank">${k + 1}</span><span class="who">${esc(nameOf(v))}<small>${esc(reason(v))}</small></span><b>${level(v)}</b></button>`).join('') + '</div>' +
    (more > 0 ? `<button class="imp-more" data-more>${S.impact.all ? 'Show top 5' : `⋯ ${more} more`}</button>` : '');
}
$('impact-close').addEventListener('click', closeImpact);
$('impact-body').addEventListener('click', (e) => {
  if (e.target.closest('[data-more]')) { S.impact.all = !S.impact.all; return renderImpact(); }
  const b = e.target.closest('[data-track]');
  if (!b) return;
  openWindow(b.dataset.track);
});

// ---- windows: every vehicle and camera opens in its own window; they tile and can be dragged ---------------

function openWindow(key) {
  if (!S.compare.includes(key)) S.compare.push(key);
  renderCompare();
  highlightCamera();
  styleMarkers(S.frames[S.idx]);
  const el = $('compare').querySelector(`[data-id="${CSS.escape(key)}"]`);  // already open: flash it
  if (el) { el.classList.remove('flash'); void el.offsetWidth; el.classList.add('flash'); el.scrollIntoView({ block: 'nearest', inline: 'nearest' }); }
}
function closeWindow(key) {
  S.compare = S.compare.filter((k) => k !== key);
  renderCompare();
  highlightCamera();
  styleMarkers(S.frames[S.idx]);
}
function renderCompare() {
  const box = $('compare');
  box.hidden = !S.compare.length;
  for (const el of [...box.children]) if (!S.compare.includes(el.dataset.id)) el.remove();
  for (const key of S.compare) {
    let el = box.querySelector(`[data-id="${CSS.escape(key)}"]`);
    if (!el) {
      el = document.createElement('div'); el.className = `cmp ${key.startsWith('cam:') ? 'win-cam' : 'win-veh'}`; el.dataset.id = key; box.appendChild(el);
      el.innerHTML = '<div class="grip" aria-hidden="true"></div><div class="cmp-body"></div>';
      makeMovable(el, `win:${key}`); placeSaved(el, `win:${key}`);
    }
    el.querySelector('.cmp-body').innerHTML = key.startsWith('cam:') ? cameraDash(key.slice(4)) : dashboard(key);
  }
  document.body.classList.toggle('comparing', S.compare.length > 0);
}
$('compare').addEventListener('click', (e) => {
  const x = e.target.closest('[data-cmpclose]');
  if (x) return closeWindow(x.dataset.cmpclose);
  const imp = e.target.closest('[data-impact]');
  if (imp) return imp.dataset.impact ? openImpact(imp.dataset.impact) : openImpact(null, imp.dataset.from);
  const cc = e.target.closest('[data-checkcam]');
  if (cc) return checkCamera(cc.dataset.checkcam);
  const veh = e.target.closest('[data-track]');
  if (veh) return openWindow(veh.dataset.track);
});

// ---- movable windows (desktop): drag a window by its background, it stays where it is dropped -------------

const placed = new Map();  // window key -> {x, y}
function placeSaved(el, key) {
  const p = placed.get(key);
  if (!p) return;
  Object.assign(el.style, { position: 'fixed', left: `${p.x}px`, top: `${p.y}px`, right: 'auto', bottom: 'auto', transform: 'none', zIndex: 20 });
}
// A press that moves more than a few pixels is a drag; one that doesn't stays a click (so list rows still work).
const NO_DRAG = '.close-btn, .p-close, .cmp-x, .impact-btn, .imp-more, .back, a, input, video, .menu-item';
function makeMovable(el, key) {
  el.addEventListener('pointerdown', (e) => {
    if (e.button !== 0 || e.target.closest(NO_DRAG)) return;
    const r = el.getBoundingClientRect(), x0 = e.clientX, y0 = e.clientY, dx = x0 - r.left, dy = y0 - r.top;
    let dragging = false;
    const move = (ev) => {
      if (!dragging) {
        if (Math.hypot(ev.clientX - x0, ev.clientY - y0) < 6) return;
        dragging = true;
        el.classList.add('dragging');
        try { el.setPointerCapture(ev.pointerId); } catch (err) { /* already released */ }
      }
      const x = Math.min(Math.max(-r.width + 60, ev.clientX - dx), innerWidth - 60);
      const y = Math.min(Math.max(0, ev.clientY - dy), innerHeight - 40);
      placed.set(key, { x, y });
      placeSaved(el, key);
      ev.preventDefault();
    };
    const up = () => {
      el.removeEventListener('pointermove', move);
      el.removeEventListener('pointerup', up);
      el.removeEventListener('pointercancel', up);
      if (!dragging) return;
      el.classList.remove('dragging');
      // the click that ends a drag must not also press the row under the finger
      const eat = (ce) => { ce.stopPropagation(); ce.preventDefault(); };
      el.addEventListener('click', eat, { capture: true, once: true });
      setTimeout(() => el.removeEventListener('click', eat, { capture: true }), 350);
    };
    el.addEventListener('pointermove', move);
    el.addEventListener('pointerup', up);
    el.addEventListener('pointercancel', up);
  });
}
makeMovable($('panel'), 'panel');
new ResizeObserver(() => {
  const r = $('panel').getBoundingClientRect();
  document.body.style.setProperty('--panel-bottom', `${S.panelOpen && r.height ? Math.round(r.bottom) : 0}px`);
}).observe($('panel'));
makeMovable($('impact'), 'impact');
placeSaved($('panel'), 'panel');

// ---- alerts panel ----------------------------------------------------------------------------------

function openPanel(open) {
  S.panelOpen = open;
  if (!open) document.body.style.setProperty('--panel-bottom', '0px');
  document.body.classList.toggle('panel-open', open);
  $('panel').setAttribute('aria-hidden', String(!open));
  renderPanel();
}

$('panel-tab').addEventListener('click', () => openPanel(!S.panelOpen));
$('panel-body').addEventListener('click', (e) => {
  if (e.target.closest('[data-close]')) return openPanel(false);
  const a = e.target.closest('.alert');
  if (!a) return;
  const it = S.items[Number(a.dataset.k)];
  if (it?.kind === 'area') openImpact(it.id); else if (it) openWindow(it.id);
});

// ---- views menu + key -----------------------------------------------------------------------------

const THUMBS = {
  photo: `<svg viewBox="0 0 84 62"><rect width="84" height="62" fill="#5b6b4f"/><path d="M0 40 L84 18 L84 30 L0 52Z" fill="#3d4148"/><rect x="46" y="38" width="30" height="16" fill="#7c8577"/>
    <rect x="8" y="8" width="22" height="14" fill="#8a8c84"/><path d="M0 46 L84 24" stroke="#e8e8e8" stroke-dasharray="4 3"/><circle cx="56" cy="22" r="3" fill="#2f6bff" stroke="#fff"/></svg>`,
  cameras: `<svg viewBox="0 0 84 62"><rect width="84" height="62" fill="#eef1f7"/><path d="M0 40 L84 18 L84 27 L0 49Z" fill="#1f2540"/>
    <path d="M64 46 L50 14 L82 22Z" fill="#ff4fa3" opacity=".35"/><circle cx="20" cy="50" r="5" fill="#0b2e6e"/><circle cx="64" cy="46" r="5" fill="#0b2e6e"/></svg>`,
  schematic: `<svg viewBox="0 0 84 62"><rect width="84" height="62" fill="#eef1f7"/><rect x="40" y="34" width="36" height="20" rx="2" fill="#dbe4f6"/>
    <path d="M0 40 L84 18 L84 27 L0 49Z" fill="#1f2540"/><path d="M6 10 Q 40 30 80 6" stroke="#16a34a" stroke-width="4" fill="none"/><path d="M10 58 L60 30" stroke="#c08a5a" stroke-width="3"/><circle cx="30" cy="18" r="3" fill="#e5383b"/></svg>`,
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
  S.compare = []; S.notified = null; S.top = null; S.camFor = {};
  renderCompare();
  highlightCamera();
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
  drawRisk();
  drawTrails();
  renderPanel();
  renderCompare();
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
    const [scenarios, photo, L, camPoints, hasVideo] = await Promise.all([
      loadScenarios(), photoTiles(),
      Promise.all(['aprons', 'buildings', 'runway_areas', 'routes', 'stands', 'holding_points'].map(loadLayer))
        .then(([aprons, buildings, runways, routes, stands, holding_points]) => ({ aprons, buildings, runways, routes, stands, holding_points })),
      loadLayer('cameras'),
      fetch('media/camera.mp4', { method: 'HEAD' }).then((r) => r.ok && (r.headers.get('content-type') || '').startsWith('video')).catch(() => false),
    ]);
    S.hasVideo = hasVideo;
    L.camcover = await loadLayer('camera_coverage');
    S.scenarios = scenarios;
    if (!map.loaded()) await new Promise((r) => map.once('load', r));
    addLayers(L, photo);
    addCameras(camPoints, L.camcover);
    applyView('photo');
    await openScenario(scenarios.find((s) => s.id === 'real_scene') || scenarios.find((s) => s.id === 'normal_ops') || scenarios[0], false);
    requestAnimationFrame(tick);
  } catch (err) {
    $('status').textContent = err.message;
    $('status').classList.add('warn');
    console.error(err);
  }
})();
