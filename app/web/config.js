// Where the web map finds its data. Local defaults (python scripts/serve_map.py); scripts/build_site.py
// writes its own copy of this file for the published site.
window.DIVAS_CFG = {
  scenarioIndex: '../../data/processed/demo/replay_fake/index.json',
  realBundle: '../../data/processed/demo/replay/',
  layers: 'data/',
  localTiles: '/tiles/{z}/{x}/{y}.jpg',
  publicUrl: 'https://ivajefremova.github.io/divas_air/',
  qr: 'qr.png',
};
