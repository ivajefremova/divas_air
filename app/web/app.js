// Divas Air web map. Reads the replay bundle (contract.ReplayManifest + ReplayFrame lines, see
// src/divas_air/contract.py) and plays it like a live feed: one frame every 5 s, positions eased in
// between. The real bundle (replay/) is used when it exists, otherwise the fake one (replay_fake/).

const CFG = {
  bundles: ['../../data/processed/demo/replay/', '../../data/processed/demo/replay_fake/'],
  layers: 'data/',
  localTiles: '/tiles/{z}/{x}/{y}.jpg',
  onlinePhoto: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
  photoBounds: [12.2027, 41.7710, 12.2941, 41.8512],
  center: [12.2505, 41.8005],
  zoom: 14.2,
  trailFrames: 10,     // 50 s of trail
  historyFrames: 60,   // 5 min integrity history on the card
  jumpM: 150,          // a move longer than this between two frames is drawn as a jump, not eased
};

const SEV_RANK = { critical: 4, high: 3, medium: 2, low: 1, none: 0 };
const CAUSE_TEXT = {
  plausible: 'Plausible', degraded: 'Degraded data', technical_error: 'Technical error',
  gnss_anomaly: 'GNSS anomaly', possible_interference: 'Possible interference',
  possible_spoofing: 'Possible spoofing', behavioral_anomaly: 'Unusual behavior (data sound)',
};
const CLASS_NAME = {
  baggage_tractor: 'Tractor', bus: 'Bus', fuel_truck: 'Fuel truck', catering_truck: 'Catering',
  sar_vehicle: 'SAR', follow_me: 'Follow-me', widebody: 'Widebody', narrowbody: 'Narrowbody',
  regional: 'Regional', turboprop: 'Turboprop', bizjet: 'Business jet', light: 'Light aircraft',
  helicopter: 'Helicopter', other: 'Aircraft',
};
const HEADLINE = {
  trusted: ['All good', 'Position and movement are as expected.'],
  caution: ['Reduced accuracy', 'The position may be off by a few meters.'],
  real_event: ['Real event', 'The data is sound and the movement is unusual.'],
  data_fault: ['Data fault', "Don't trust this position."],
  silent_risk: ['Position unreliable', "Movement looks normal, but the data isn't."],
};
const ALERT_WORD = {
  caution: 'Reduced accuracy', real_event: 'Unusual movement',
  data_fault: 'Position unreliable', silent_risk: 'Position unreliable',
};
const COLORS = { blue: '#2f6bff', pink: '#ff4fa3', red: '#e5383b', amber: '#f5a524', ink: '#18203a' };

const PLANE = '<svg viewBox="0 0 24 24"><path class="shape" d="M12 1.5c.9 0 1.5.8 1.5 1.8V9l8 4.8v2.2l-8-2.4v5.1l2.4 1.8v1.7L12 21.2l-3.9 1v-1.7l2.4-1.8v-5.1l-8 2.4v-2.2l8-4.8V3.3c0-1 .6-1.8 1.5-1.8z"/></svg>';
// Top-down vehicle icons, front at the top, drawn at real-ish proportions (1 unit = 1 px at full size).
const WIN = (x, y, w, h) => `<rect class="detail" x="${x}" y="${y}" width="${w}" height="${h}" rx="1"/>`;
const ICONS = {
  bus: `<svg viewBox="0 0 12 32" width="12" height="32"><rect class="shape" x=".75" y=".75" width="10.5" height="30.5" rx="2.6"/>
    ${WIN(2.4, 2.2, 7.2, 3.2)}<rect class="detail" x="2.4" y="8.5" width="7.2" height="1.4" rx=".7"/><rect class="detail" x="2.4" y="17" width="7.2" height="1.4" rx=".7"/><rect class="detail" x="2.4" y="25.5" width="7.2" height="1.4" rx=".7"/></svg>`,
  fuel_truck: `<svg viewBox="0 0 13 29" width="13" height="29"><rect class="shape" x="1.5" y=".75" width="10" height="7.5" rx="2.2"/>
    ${WIN(3, 1.9, 7, 2.4)}<rect class="shape" x=".75" y="9.6" width="11.5" height="18.65" rx="5.75"/>
    <path class="band" d="M1.5 15.5h10M1.5 22.3h10"/></svg>`,
  catering_truck: `<svg viewBox="0 0 15 27" width="15" height="27"><rect class="shape" x="2.5" y=".75" width="10" height="7.5" rx="2.2"/>
    ${WIN(4, 1.9, 7, 2.4)}<rect class="shape" x=".75" y="9.4" width="13.5" height="16.85" rx="1.4"/>
    <path class="band" d="M3 12.5l9 10.5M12 12.5L3 23"/></svg>`,
  baggage_tractor: `<svg viewBox="0 0 12 33" width="12" height="33"><path class="link" d="M6 10v3M6 21.5v3"/>
    <rect class="shape" x="1" y=".75" width="10" height="9.25" rx="2.8"/>${WIN(2.6, 2, 6.8, 2.6)}
    <rect class="shape cart" x="1.6" y="13" width="8.8" height="8.5" rx="1.6"/><rect class="shape cart" x="1.6" y="24.5" width="8.8" height="7.75" rx="1.6"/></svg>`,
  follow_me: `<svg viewBox="0 0 11 19" width="11" height="19"><rect class="shape" x=".75" y=".75" width="9.5" height="17.5" rx="3.6"/>
    ${WIN(2.2, 3.4, 6.6, 2.8)}<rect class="beacon" x="1.8" y="7.6" width="7.4" height="2.4" rx="1.2"/>${WIN(2.2, 12.6, 6.6, 2.4)}</svg>`,
  sar_vehicle: `<svg viewBox="0 0 14 29" width="14" height="29"><rect class="shape" x=".75" y=".75" width="12.5" height="27.5" rx="2.6"/>
    ${WIN(2.4, 2.2, 9.2, 3)}<rect class="beacon" x="2" y="6.6" width="10" height="2.2" rx="1.1"/>
    <path class="band" d="M7 13v10M2 18h10"/></svg>`,
  vehicle: `<svg viewBox="0 0 16 20" width="15" height="19"><path class="shape" d="M8 .8l5.2 5.2H13V16a3 3 0 01-3 3H6a3 3 0 01-3-3V6h-.2L8 .8z"/></svg>`,
};
const iconFor = (v) => (v.domain === 'aircraft' ? PLANE : ICONS[v.asset_class] || ICONS.vehicle);

// ---- state ------------------------------------------------------------------------------

const S = {
  manifest: null, frames: [], byTrack: [], source: '',
  t: 0, idx: -1, playing: true,
  view: 'photo', show: { aircraft: true, vehicles: true },
  sel: null,            // {kind: 'track' | 'area', id}
  panelOpen: false,
  markers: new Map(),   // track_id -> {marker, el}
  fcLabels: [],
};

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const hhmmss = (t) => new Date(t * 1000).toISOString().slice(11, 19);
const nameOf = (v) => v.callsign || `${CLASS_NAME[v.asset_class] || 'Vehicle'} ${(v.asset_id.match(/\d+/) || [v.asset_id])[0]}`;
const quad = (v) => (v.quadrant === 'trusted' && v.trust_state === 'caution' ? 'caution' : v.quadrant);
const distM = (a, b) => {
  const dx = (a.lon - b.lon) * 111320 * Math.cos(a.lat * Math.PI / 180), dy = (a.lat - b.lat) * 110540;
  return Math.hypot(dx, dy);
};
const isAlert = (v) => v.action.code !== 'none';

// ---- data -------------------------------------------------------------------------------

async function loadBundle() {
  for (const base of CFG.bundles) {
    const res = await fetch(base + 'manifest.json').catch(() => null);
    if (!res || !res.ok) continue;
    const manifest = await res.json();
    const text = await (await fetch(base + manifest.frames_file)).text();
    const frames = text.split('\n').filter(Boolean).map((l) => JSON.parse(l));
    return { manifest, frames, source: base.includes('fake') ? 'Fake demo data' : 'Replay bundle' };
  }
  throw new Error('No replay bundle found. Run scripts/make_fake_replay.py.');
}

const loadLayer = (name) => fetch(CFG.layers + name + '.geojson').then((r) => (r.ok ? r.json() : empty()));
const empty = () => ({ type: 'FeatureCollection', features: [] });

async function photoTiles() {
  // local orthophoto if the tiles are served, the online satellite image otherwise
  const z = 16, n = 2 ** z, [lon, lat] = CFG.center;
  const x = Math.floor((lon + 180) / 360 * n);
  const y = Math.floor((1 - Math.asinh(Math.tan(lat * Math.PI / 180)) / Math.PI) / 2 * n);
  const url = CFG.localTiles.replace('{z}', z).replace('{x}', x).replace('{y}', y);
  const ok = await fetch(url, { method: 'HEAD' }).then((r) => r.ok).catch(() => false);
  return ok
    ? { tiles: [CFG.localTiles], minzoom: 13, maxzoom: 19, bounds: CFG.photoBounds, attribution: 'Orthophoto 2023 (AGEA)' }
    : { tiles: [CFG.onlinePhoto], maxzoom: 19, attribution: 'Imagery © Esri' };
}

// ---- map --------------------------------------------------------------------------------

const map = new maplibregl.Map({
  container: 'map',
  style: { version: 8, sources: {}, layers: [{ id: 'bg', type: 'background', paint: { 'background-color': '#f3f5fa' } }] },
  center: CFG.center, zoom: CFG.zoom, minZoom: 12, maxZoom: 19.5,
  attributionControl: false, dragRotate: false, pitchWithRotate: false,
});
map.touchZoomRotate.disableRotation();
const iconScale = () => document.documentElement.style.setProperty('--s', Math.min(1.5, Math.max(0.65, (map.getZoom() - 12.2) / 3.2)).toFixed(2));
map.on('zoom', iconScale);
iconScale();
map.addControl(new maplibregl.AttributionControl({ compact: true }), 'bottom-right');

// Which layers each view shows, and how strongly. Live risk zones, forecasts and tracks show in every view.
const VIEWS = {
  photo: { label: 'Photo', bg: '#2b3040', on: { photo: 1, 'rwy-line': 0.9, 'risk-static': 0.5 } },
  schematic: { label: 'Schematic', bg: '#f3f5fa', on: { aprons: 1, buildings: 1, 'rwy-fill': 1, 'rwy-line': 1, 'routes-service': 1, 'routes-taxi': 1, stands: 1, holding: 1, 'risk-static': 0.5 } },
  traffic: { label: 'Traffic', bg: '#f7f8fc', on: { 'rwy-fill': 0.25, aprons: 0.6 } },
  gnss: { label: 'GNSS risk', bg: '#eef0f6', on: { aprons: 0.5, buildings: 0.45, 'rwy-fill': 0.35, 'routes-taxi': 0.3, 'routes-service': 0.3, 'risk-static': 1.6 } },
};
const OPACITY_PROP = {
  photo: 'raster-opacity', aprons: 'fill-opacity', buildings: 'fill-opacity', 'rwy-fill': 'fill-opacity', 'rwy-line': 'line-opacity',
  'routes-service': 'line-opacity', 'routes-taxi': 'line-opacity', stands: 'circle-opacity', holding: 'circle-opacity', 'risk-static': 'fill-opacity',
};
const BASE_OPACITY = { 'risk-static': 0.22 };

function addLayers(L, photo) {
  map.addSource('photo', { type: 'raster', tileSize: 256, ...photo });
  for (const k of ['aprons', 'buildings', 'runways', 'routes', 'stands', 'holding_points']) map.addSource(k, { type: 'geojson', data: L[k] });
  map.addSource('risk', { type: 'geojson', data: empty() });
  map.addSource('trails', { type: 'geojson', data: empty() });

  map.addLayer({ id: 'photo', type: 'raster', source: 'photo' });
  map.addLayer({ id: 'aprons', type: 'fill', source: 'aprons', paint: { 'fill-color': '#dde4f4' } });
  map.addLayer({ id: 'buildings', type: 'fill', source: 'buildings', paint: { 'fill-color': '#d9dce6', 'fill-outline-color': '#c5c9d6' } });
  map.addLayer({ id: 'rwy-fill', type: 'fill', source: 'runways', paint: { 'fill-color': '#2c3352' } });
  map.addLayer({ id: 'rwy-line', type: 'line', source: 'runways', paint: { 'line-color': '#ffffff', 'line-width': 1.5 } });
  map.addLayer({ id: 'routes-service', type: 'line', source: 'routes', filter: ['==', ['get', 'kind'], 'service_road'],
    paint: { 'line-color': '#dcdfe8', 'line-width': ['interpolate', ['linear'], ['zoom'], 13, 0.6, 17, 2.5] } });
  map.addLayer({ id: 'routes-taxi', type: 'line', source: 'routes', filter: ['==', ['get', 'kind'], 'taxiway'],
    paint: { 'line-color': '#c9d2ee', 'line-width': ['interpolate', ['linear'], ['zoom'], 13, 1, 17, 5] } });
  map.addLayer({ id: 'stands', type: 'circle', source: 'stands', minzoom: 15,
    paint: { 'circle-radius': 2.5, 'circle-color': '#8d95ad' } });
  map.addLayer({ id: 'holding', type: 'circle', source: 'holding_points', minzoom: 14,
    paint: { 'circle-radius': 3, 'circle-color': '#ffffff', 'circle-stroke-color': '#2c3352', 'circle-stroke-width': 1.5 } });

  map.addLayer({ id: 'risk-static', type: 'fill', source: 'risk', filter: ['==', ['get', 'kind'], 'static'],
    paint: { 'fill-color': '#9b6bff', 'fill-opacity': ['*', ['get', 'level'], 0.22] } });
  map.addLayer({ id: 'risk-live', type: 'fill', source: 'risk', filter: ['==', ['get', 'kind'], 'live'],
    paint: { 'fill-color': COLORS.pink, 'fill-opacity': ['*', ['get', 'level'], 0.25] } });
  map.addLayer({ id: 'risk-live-edge', type: 'line', source: 'risk', filter: ['==', ['get', 'kind'], 'live'],
    paint: { 'line-color': '#e8368a', 'line-width': 2.5 } });
  map.addLayer({ id: 'trails', type: 'line', source: 'trails', layout: { 'line-cap': 'round' },
    paint: { 'line-color': ['get', 'c'], 'line-opacity': ['get', 'o'], 'line-width': 3 } });
  map.addLayer({ id: 'risk-forecast', type: 'line', source: 'risk', filter: ['==', ['get', 'kind'], 'forecast'],
    layout: { 'line-cap': 'round' }, paint: { 'line-color': '#e8368a', 'line-width': 3, 'line-dasharray': [1.5, 1.5] } });

  map.on('click', 'risk-live', (e) => { e.preventDefault(); const p = e.features[0].properties; if (p.area_alert_id) select({ kind: 'area', id: p.area_alert_id }); });
  map.on('click', (e) => { if (!e.defaultPrevented && S.sel) select(null); });
  for (const id of ['risk-live']) {
    map.on('mouseenter', id, () => (map.getCanvas().style.cursor = 'pointer'));
    map.on('mouseleave', id, () => (map.getCanvas().style.cursor = ''));
  }
}

function applyView(view) {
  S.view = view;
  const v = VIEWS[view];
  map.setPaintProperty('bg', 'background-color', v.bg);
  for (const id of Object.keys(OPACITY_PROP)) {
    const k = v.on[id];
    map.setLayoutProperty(id, 'visibility', k ? 'visible' : 'none');
    if (!k) continue;
    if (id === 'risk-static') map.setPaintProperty(id, 'fill-opacity', ['*', ['get', 'level'], BASE_OPACITY[id] * k]);
    else map.setPaintProperty(id, OPACITY_PROP[id], k);
  }
  map.setPaintProperty('trails', 'line-width', view === 'photo' ? 3.5 : 3);
  renderViews();
}

// ---- markers ----------------------------------------------------------------------------

function markerFor(v) {
  let m = S.markers.get(v.track_id);
  if (m) return m;
  const wrap = document.createElement('div');
  wrap.innerHTML = `<div class="trk"><div class="halo"></div><div class="ring"></div><div class="icon">${iconFor(v)}</div><div class="tag"></div></div>`;
  const el = wrap.firstElementChild;
  el.addEventListener('click', (e) => { e.stopPropagation(); select({ kind: 'track', id: v.track_id }); });
  const marker = new maplibregl.Marker({ element: wrap, anchor: 'center' }).setLngLat([v.position.lon, v.position.lat]).addTo(map);
  m = { marker, wrap, el, icon: el.querySelector('.icon'), tag: el.querySelector('.tag') };
  S.markers.set(v.track_id, m);
  return m;
}

function styleMarkers(frame) {
  const present = new Set();
  const areaMembers = S.sel?.kind === 'area' ? new Set(areaTracks(frame, S.sel.id)) : null;
  for (const v of frame.verdicts) {
    present.add(v.track_id);
    const m = markerFor(v);
    const shown = v.domain === 'aircraft' ? S.show.aircraft : S.show.vehicles;
    const selected = (S.sel?.kind === 'track' && S.sel.id === v.track_id) || (areaMembers && areaMembers.has(v.track_id));
    m.el.className = [
      'trk', v.domain, `c-${v.asset_class}`, `s-${v.trust_state}`,
      v.normality_state === 'abnormal' ? 'abnormal' : '',
      v.confidence_level === 'low' ? 'conf-low' : '',
      isAlert(v) && SEV_RANK[v.severity.level] >= 2 ? 'problem' : '',
      selected ? 'sel' : '', shown ? '' : 'hidden',
    ].join(' ');
    m.tag.textContent = nameOf(v);
    if (v.position.track_deg != null) m.icon.style.transform = `rotate(${v.position.track_deg}deg)`;
    m.wrap.style.zIndex = selected ? 30 : 10 + SEV_RANK[v.severity.level];
  }
  for (const [id, m] of S.markers) if (!present.has(id)) m.el.classList.add('hidden');
}

function moveMarkers() {
  // ease each track from frame idx to idx+1; a jump (e.g. a spoofed position) is shown as a jump
  const a = S.frames[S.idx], b = S.frames[S.idx + 1];
  if (!a) return;
  const f = b ? Math.min(1, Math.max(0, (S.t - a.t) / (b.t - a.t))) : 0;
  const next = b ? S.byTrack[S.idx + 1] : null;
  for (const v of a.verdicts) {
    const m = S.markers.get(v.track_id);
    if (!m) continue;
    const w = next && next.get(v.track_id);
    let p = v.position;
    if (w && distM(p, w.position) < CFG.jumpM) {
      p = { lon: p.lon + (w.position.lon - p.lon) * f, lat: p.lat + (w.position.lat - p.lat) * f };
    }
    m.marker.setLngLat([p.lon, p.lat]);
  }
}

function drawTrails() {
  const feats = [];
  const from = Math.max(0, S.idx - CFG.trailFrames);
  for (const v of S.frames[S.idx].verdicts) {
    const shown = v.domain === 'aircraft' ? S.show.aircraft : S.show.vehicles;
    if (!shown) continue;
    let prev = null;
    for (let i = from; i <= S.idx; i++) {
      const w = S.byTrack[i].get(v.track_id);
      if (!w) { prev = null; continue; }
      if (prev) {
        const age = (i - from) / Math.max(1, S.idx - from);
        const c = w.trust_state === 'untrusted' ? COLORS.red : w.trust_state === 'caution' ? COLORS.amber : COLORS.blue;
        feats.push({ type: 'Feature', properties: { c, o: 0.08 + 0.5 * age },
          geometry: { type: 'LineString', coordinates: [[prev.lon, prev.lat], [w.position.lon, w.position.lat]] } });
      }
      prev = w.position;
    }
  }
  map.getSource('trails').setData({ type: 'FeatureCollection', features: feats });
}

function drawRisk(frame) {
  map.getSource('risk').setData(frame.risk_zones);
  S.fcLabels.forEach((m) => m.remove());
  S.fcLabels = frame.risk_zones.features.filter((f) => f.properties.kind === 'forecast').map((f) => {
    const el = document.createElement('div');
    el.className = 'fc-label';
    el.textContent = `Enters interference area in ${Math.round(f.properties.eta_s)} s`;
    const end = f.geometry.coordinates[f.geometry.coordinates.length - 1];
    return new maplibregl.Marker({ element: el, anchor: 'left', offset: [10, 0] }).setLngLat(end).addTo(map);
  });
}

// ---- alerts -----------------------------------------------------------------------------

function areaTracks(frame, areaId) {
  return frame.verdicts.filter((v) => v.area_alert_id === areaId).map((v) => v.track_id);
}

function alertsAt(frame) {
  const items = [], areas = new Map();
  for (const v of frame.verdicts) {
    if (!isAlert(v)) continue;
    if (!(v.domain === 'aircraft' ? S.show.aircraft : S.show.vehicles)) continue;
    if (v.area_alert_id) {
      const a = areas.get(v.area_alert_id) || { kind: 'area', id: v.area_alert_id, members: [], sev: 'none', score: 0 };
      a.members.push(v);
      if (SEV_RANK[v.severity.level] > SEV_RANK[a.sev]) a.sev = v.severity.level;
      a.score = Math.max(a.score, v.severity.score);
      areas.set(v.area_alert_id, a);
    } else {
      items.push({ kind: 'track', id: v.track_id, v, sev: v.severity.level, score: v.severity.score });
    }
  }
  for (const a of areas.values()) {
    a.zone = frame.risk_zones.features.find((f) => f.properties.area_alert_id === a.id)?.properties;
    items.push(a);
  }
  return items.sort((x, y) => SEV_RANK[y.sev] - SEV_RANK[x.sev] || y.score - x.score);
}

function alertSince(item) {
  // how long this track (or area) has needed attention, counted back through the frames
  let i = S.idx;
  const test = item.kind === 'area'
    ? (k) => S.frames[k].verdicts.some((v) => v.area_alert_id === item.id)
    : (k) => { const v = S.byTrack[k].get(item.id); return v && isAlert(v); };
  while (i > 0 && test(i - 1)) i--;
  return S.t - S.frames[i].t;
}

const forTime = (s) => (s < 60 ? `${Math.max(0, Math.round(s))} s` : `${Math.floor(s / 60)} min ${String(Math.round(s % 60)).padStart(2, '0')} s`);

// ---- panel ------------------------------------------------------------------------------

function renderPanel() {
  const frame = S.frames[S.idx];
  if (!frame) return;
  const items = alertsAt(frame);
  $('tab-count').hidden = items.length === 0;
  $('tab-count').textContent = items.length;
  const shown = frame.verdicts.filter((v) => (v.domain === 'aircraft' ? S.show.aircraft : S.show.vehicles)).length;
  const st = $('status');
  st.textContent = items.length ? `${items.length} need${items.length === 1 ? 's' : ''} attention` : `All ${shown} positions trusted`;
  st.classList.toggle('warn', items.length > 0);
  if (!S.panelOpen) return;

  let html;
  if (S.sel?.kind === 'track') html = trackCard(frame, S.sel.id);
  else if (S.sel?.kind === 'area') html = areaCard(frame, S.sel.id);
  else html = alertList(items);
  const body = $('panel-body'), top = body.scrollTop;
  body.innerHTML = html;
  body.scrollTop = top;
}

function alertList(items) {
  if (!items.length) {
    return `<div class="p-head"><h2 class="p-title">Alerts</h2></div>
      <div class="empty"><strong>All clear</strong>Every position on the map can be trusted.</div>`;
  }
  return `<div class="p-head"><h2 class="p-title">Alerts</h2><span class="p-sub">${items.length} open</span></div>` +
    items.map((it, k) => {
      if (it.kind === 'area') {
        const label = it.zone?.label || 'Possible interference';
        return `<button class="alert" data-k="${k}"><span class="bar sev-${it.sev}"></span><span>
          <div class="a-what">${esc(label)}</div>
          <div class="a-where">${it.members.length} vehicles affected</div>
          <div class="a-meta">for ${forTime(alertSince(it))}</div></span></button>`;
      }
      const v = it.v;
      return `<button class="alert" data-k="${k}"><span class="bar sev-${it.sev}"></span><span>
        <div class="a-what">${esc(ALERT_WORD[quad(v)] || 'Check position')}</div>
        <div class="a-where">${esc(nameOf(v))} · ${esc(v.severity.zone_name || '')}</div>
        <div class="a-meta">for ${forTime(alertSince(it))}</div></span></button>`;
    }).join('');
}

function trackCard(frame, id) {
  const v = frame.verdicts.find((x) => x.track_id === id);
  const back = '<button class="back" data-back>‹ All alerts</button>';
  if (!v) return `${back}<div class="empty">No position for this track right now.</div>`;
  const q = quad(v), [hl, hlText] = HEADLINE[q];
  const confOn = { low: 1, medium: 2, high: 3 }[v.confidence_level];
  const pCause = v.cause_probs[v.cause];
  const dims = Object.entries(v.dimensions).map(([k, val]) => {
    const c = val < 40 ? COLORS.red : val < 70 ? COLORS.amber : '#9aa3bd';
    return `<div class="dim"><span>${k[0].toUpperCase() + k.slice(1)}</span>
      <span class="track"><span class="fill" style="display:block;width:${val}%;background:${c}"></span></span>
      <span class="val">${Math.round(val)} / 100</span></div>`;
  }).join('');
  const p = v.position;
  const speed = p.speed_mps == null ? '—' : `${(p.speed_mps * 3.6).toFixed(0)} km/h`;
  const heading = p.track_deg == null ? '—' : `${Math.round(p.track_deg)}°`;
  const warn = v.early_warning ? `<div class="label">Heads-up</div><div style="font-weight:700;color:var(--pink-ink)">Enters a GNSS risk area in ${Math.round(v.early_warning.eta_s)} s</div>` : '';
  return `${back}
    <div class="d-name">${esc(nameOf(v))}</div>
    <div class="d-kind">${esc(CLASS_NAME[v.asset_class] || v.asset_class)} · ${esc(v.asset_id)}</div>
    <div class="headline hl-${q}"><b>${hl}</b><span>${hlText}</span></div>
    ${v.action.code !== 'none' ? `<div class="label">What to do</div><div class="todo">${esc(v.action.text)}</div>` : ''}
    ${warn}
    <div class="label">Confidence</div>
    <div class="conf"><span class="conf-meter">${[1, 2, 3].map((k) => `<i class="${k <= confOn ? 'on' : ''}"></i>`).join('')}</span>
      <span><b>${v.confidence_level[0].toUpperCase() + v.confidence_level.slice(1)}</b> · ${Math.round(v.confidence * 100)} %</span></div>
    <div class="label">Likely cause</div>
    <div class="cause">${esc(CAUSE_TEXT[v.cause])} <span>· ${Math.round(pCause * 100)} % likely</span></div>
    ${v.evidence.length ? `<div class="label">Why</div><ul class="why">${v.evidence.map((e) => `<li>${esc(e.text)}</li>`).join('')}</ul>` : ''}
    <div class="label">Scores</div>
    <div class="scores">
      <div class="score"><div class="num">${Math.round(v.integrity)} <small>/ 100</small></div><div class="cap">Can we trust the position?</div></div>
      <div class="score"><div class="num">${Math.round(v.normality)} <small>/ 100</small></div><div class="cap">Is the movement normal?</div></div>
    </div>
    ${dims}
    <div class="label">Now</div>
    <div class="facts"><div><span>Zone</span>${esc(v.severity.zone_name || '—')}</div><div><span>Speed</span>${speed}</div><div><span>Heading</span>${heading}</div></div>
    <div class="label">Position trust, last 5 min</div>
    ${sparkline(id)}`;
}

function areaCard(frame, areaId) {
  const back = '<button class="back" data-back>‹ All alerts</button>';
  const zone = frame.risk_zones.features.find((f) => f.properties.area_alert_id === areaId)?.properties;
  const members = frame.verdicts.filter((v) => v.area_alert_id === areaId);
  if (!members.length) return `${back}<div class="empty"><strong>Resolved</strong>This area alert has ended.</div>`;
  const action = zone?.action?.text || members[0].action.text;
  return `${back}
    <div class="d-name">${esc(zone?.label || 'Possible interference')}</div>
    <div class="d-kind">${members.length} vehicles affected · for ${forTime(alertSince({ kind: 'area', id: areaId }))}</div>
    <div class="headline hl-silent_risk"><b>Possible interference</b><span>Several positions degraded at the same time in one area.</span></div>
    <div class="label">What to do</div><div class="todo">${esc(action)}</div>
    ${zone ? `<div class="label">Interference level</div><div class="cause">${Math.round(zone.level * 100)} %</div>` : ''}
    <div class="label">Affected</div>
    ${members.map((v) => `<button class="member" data-track="${esc(v.track_id)}">${esc(nameOf(v))}<span>${Math.round(v.confidence * 100)} % confidence</span></button>`).join('')}`;
}

function sparkline(id) {
  const from = Math.max(0, S.idx - CFG.historyFrames);
  const pts = [];
  for (let i = from; i <= S.idx; i++) { const v = S.byTrack[i].get(id); if (v) pts.push([i, v.integrity, v.trust_state]); }
  if (pts.length < 2) return '<div class="p-sub">Not enough history yet.</div>';
  const W = 340, H = 70, x = (i) => ((i - from) / Math.max(1, S.idx - from)) * (W - 8) + 4, y = (val) => H - 4 - (val / 100) * (H - 8);
  const line = pts.map(([i, val]) => `${x(i).toFixed(1)},${y(val).toFixed(1)}`).join(' ');
  const [li, lv, ls] = pts[pts.length - 1];
  const dot = ls === 'untrusted' ? COLORS.red : ls === 'caution' ? COLORS.amber : COLORS.blue;
  return `<svg class="spark" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">
      <line x1="0" x2="${W}" y1="${y(70)}" y2="${y(70)}" stroke="#e3e6ef" stroke-dasharray="4 4"/>
      <line x1="0" x2="${W}" y1="${y(40)}" y2="${y(40)}" stroke="#f3d3d4" stroke-dasharray="4 4"/>
      <polyline points="${line}" fill="none" stroke="${COLORS.ink}" stroke-width="2" stroke-linejoin="round" vector-effect="non-scaling-stroke"/>
      <circle cx="${x(li)}" cy="${y(lv)}" r="4.5" fill="${dot}" stroke="#fff" stroke-width="1.5"/></svg>
    <div class="spark-axis"><span>${forTime((S.idx - from) * S.manifest.step_s)} ago</span><span>now · ${Math.round(lv)} / 100</span></div>`;
}

// ---- selection --------------------------------------------------------------------------

function select(sel, fly = false) {
  if (JSON.stringify(sel) !== JSON.stringify(S.sel)) $('panel-body').scrollTop = 0;
  S.sel = sel;
  if (sel) openPanel(true);
  const frame = S.frames[S.idx];
  if (fly && sel && frame) {
    if (sel.kind === 'track') {
      const v = S.byTrack[S.idx].get(sel.id);
      if (v) map.easeTo({ center: [v.position.lon, v.position.lat], zoom: Math.max(map.getZoom(), 15.5), padding: panelPadding() });
    } else {
      fitTo(frame.verdicts.filter((v) => v.area_alert_id === sel.id).map((v) => v.position));
    }
  }
  styleMarkers(frame);
  renderPanel();
}

function fitTo(positions) {
  if (!positions.length) return;
  const b = new maplibregl.LngLatBounds();
  positions.forEach((p) => b.extend([p.lon, p.lat]));
  map.fitBounds(b, { padding: { top: 120, bottom: 120, left: 120, right: 120 + (S.panelOpen ? 400 : 0) }, maxZoom: 16.2 });
}

const panelPadding = () => ({ right: S.panelOpen ? 400 : 0 });

function openPanel(open) {
  S.panelOpen = open;
  document.body.classList.toggle('panel-open', open);
  $('panel').setAttribute('aria-hidden', String(!open));
  $('panel-tab').setAttribute('aria-expanded', String(open));
  renderPanel();
}

$('panel-tab').addEventListener('click', () => openPanel(!S.panelOpen));
$('panel-body').addEventListener('click', (e) => {
  const frame = S.frames[S.idx];
  if (e.target.closest('[data-back]')) return select(null);
  const m = e.target.closest('[data-track]');
  if (m) return select({ kind: 'track', id: m.dataset.track }, true);
  const a = e.target.closest('.alert');
  if (a) {
    const it = alertsAt(frame)[Number(a.dataset.k)];
    if (it) select({ kind: it.kind, id: it.id }, true);
  }
});

// ---- views menu ---------------------------------------------------------------------------

const THUMBS = {
  photo: () => `<svg viewBox="0 0 84 62"><rect width="84" height="62" fill="#5b6b4f"/><path d="M0 40 L84 18 L84 30 L0 52Z" fill="#3d4148"/>
    <rect x="46" y="38" width="30" height="16" fill="#7c8577"/><rect x="8" y="8" width="22" height="14" fill="#8a8c84"/>
    <path d="M0 46 L84 24" stroke="#e8e8e8" stroke-width="1" stroke-dasharray="4 3"/><circle cx="56" cy="22" r="3" fill="#2f6bff" stroke="#fff"/></svg>`,
  schematic: () => `<svg viewBox="0 0 84 62"><rect width="84" height="62" fill="#f3f5fa"/><rect x="40" y="34" width="36" height="20" rx="2" fill="#dde4f4"/>
    <path d="M0 40 L84 18 L84 27 L0 49Z" fill="#2c3352"/><path d="M6 10 Q 40 30 80 6" stroke="#c9d2ee" stroke-width="3" fill="none"/>
    <path d="M10 58 L60 30" stroke="#bfc5d4" stroke-width="1.5"/><circle cx="30" cy="18" r="2.5" fill="#ff4fa3"/></svg>`,
  traffic: () => `<svg viewBox="0 0 84 62"><rect width="84" height="62" fill="#f7f8fc"/><path d="M0 40 L84 18 L84 27 L0 49Z" fill="#e3e6ef"/>
    <circle cx="20" cy="16" r="4" fill="#2f6bff"/><circle cx="52" cy="44" r="4" fill="#2f6bff"/><circle cx="66" cy="12" r="4" fill="#2f6bff"/>
    <circle cx="38" cy="28" r="4" fill="#fff" stroke="#e5383b" stroke-width="1.6" stroke-dasharray="2 1.5"/></svg>`,
  gnss: () => `<svg viewBox="0 0 84 62"><rect width="84" height="62" fill="#eef0f6"/><path d="M0 40 L84 18 L84 27 L0 49Z" fill="#cfd4e2"/>
    <circle cx="26" cy="20" r="14" fill="#9b6bff" opacity=".35"/><path d="M48 34 h26 v20 h-26z" fill="#ff4fa3" opacity=".4" stroke="#e8368a" stroke-width="1.5"/>
    <path d="M30 58 L48 46" stroke="#e8368a" stroke-width="2" stroke-dasharray="3 2"/></svg>`,
};

function renderViews() {
  $('views-thumb').innerHTML = THUMBS[S.view]();
  $('views-label').textContent = VIEWS[S.view].label;
  $('view-grid').innerHTML = Object.entries(VIEWS).map(([k, v]) =>
    `<button class="view-opt ${k === S.view ? 'on' : ''}" data-view="${k}"><span class="thumb">${THUMBS[k]()}</span>${v.label}</button>`).join('');
}

function toggleMenu(btn, menu, open) {
  menu.hidden = !open;
  btn.setAttribute('aria-expanded', String(open));
}
$('views-btn').addEventListener('click', (e) => { e.stopPropagation(); toggleMenu($('views-btn'), $('views-menu'), $('views-menu').hidden); });
$('view-grid').addEventListener('click', (e) => { const b = e.target.closest('[data-view]'); if (b) applyView(b.dataset.view); });
for (const [id, key] of [['show-aircraft', 'aircraft'], ['show-vehicles', 'vehicles']]) {
  $(id).addEventListener('change', (e) => { S.show[key] = e.target.checked; styleMarkers(S.frames[S.idx]); drawTrails(); renderPanel(); });
}

// ---- demo menu ----------------------------------------------------------------------------

function renderDemo() {
  $('demo-events').innerHTML = S.manifest.events.map((ev, k) =>
    `<button class="menu-item" data-ev="${k}">${esc(ev.title)}<small>${hhmmss(ev.t_start)} UTC · ${forTime(ev.t_end - ev.t_start)}</small></button>`).join('');
  $('demo-play').textContent = S.playing ? 'Pause' : 'Play';
  $('demo-source').textContent = `${S.source} · ${S.manifest.airport}`;
}

function jumpTo(t) {
  S.t = Math.max(S.manifest.t_start, t);
  S.idx = -1;
  tick(0);
}

$('demo-btn').addEventListener('click', (e) => { e.stopPropagation(); toggleMenu($('demo-btn'), $('demo-menu'), $('demo-menu').hidden); });
$('demo-events').addEventListener('click', (e) => {
  const b = e.target.closest('[data-ev]');
  if (!b) return;
  const ev = S.manifest.events[Number(b.dataset.ev)];
  jumpTo(ev.t_start - 10);
  S.playing = true;
  const pos = ev.track_ids.map((id) => S.byTrack[S.idx].get(id)?.position).filter(Boolean);
  if (ev.track_ids.length === 1) select({ kind: 'track', id: ev.track_ids[0] }, true);
  else { select(null); openPanel(true); fitTo(pos); }
  toggleMenu($('demo-btn'), $('demo-menu'), false);
  renderDemo();
});
$('demo-play').addEventListener('click', () => { S.playing = !S.playing; renderDemo(); });
$('demo-restart').addEventListener('click', () => { jumpTo(S.manifest.t_start); S.playing = true; renderDemo(); });
document.addEventListener('click', (e) => {
  if (!e.target.closest('#views')) toggleMenu($('views-btn'), $('views-menu'), false);
  if (!e.target.closest('#demo')) toggleMenu($('demo-btn'), $('demo-menu'), false);
});

// ---- clock --------------------------------------------------------------------------------

function onFrame() {
  const frame = S.frames[S.idx];
  styleMarkers(frame);
  drawRisk(frame);
  drawTrails();
  renderPanel();
  $('clock').textContent = `${hhmmss(frame.t)} UTC`;
}

let last = performance.now(), pulse = 0;
function tick(now) {
  const dt = now ? (now - last) / 1000 : 0;
  last = now || performance.now();
  if (S.playing && now) S.t += dt;
  if (S.t > S.manifest.t_end) S.t = S.manifest.t_start;  // loop the demo
  const i = Math.min(S.frames.length - 1, Math.floor((S.t - S.manifest.t_start) / S.manifest.step_s));
  if (i !== S.idx) { S.idx = i; onFrame(); }
  moveMarkers();
  pulse += dt;
  if (map.getLayer('risk-live-edge')) map.setPaintProperty('risk-live-edge', 'line-opacity', 0.55 + 0.45 * Math.sin(pulse * 3.5));
  if (now) requestAnimationFrame(tick);
}

// ---- start --------------------------------------------------------------------------------

(async function start() {
  try {
    const [bundle, photo, L] = await Promise.all([
      loadBundle(),
      photoTiles(),
      Promise.all(['aprons', 'buildings', 'runways', 'routes', 'stands', 'holding_points'].map(loadLayer))
        .then(([aprons, buildings, runways, routes, stands, holding_points]) => ({ aprons, buildings, runways, routes, stands, holding_points })),
    ]);
    Object.assign(S, bundle);
    S.byTrack = S.frames.map((f) => new Map(f.verdicts.map((v) => [v.track_id, v])));
    S.t = S.manifest.t_start;
    if (!map.loaded()) await new Promise((r) => map.once('load', r));
    addLayers(L, photo);
    applyView('photo');
    renderDemo();
    requestAnimationFrame(tick);
  } catch (err) {
    $('status').textContent = err.message;
    $('status').classList.add('warn');
    console.error(err);
  }
})();
