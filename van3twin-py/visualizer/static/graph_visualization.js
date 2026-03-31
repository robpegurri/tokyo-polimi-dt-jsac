/* graph_visualization.js — Network graph overlay rendered directly on the Leaflet map */

const GraphVisualization = (() => {
  let _map = null;
  let _settings = null;
  let _layer = null;         // L.layerGroup for all graph elements
  let _currentParams = null;
  let _currentDirection = 'both';
  let _debounceTimer = null;
  let _lastData = null;

  // Colors per hop distance from RSU (hop 0 = RSU, hop 1 = direct, hop 2, ...)
  const HOP_COLORS = ['#e74c3c', '#3498db', '#1abc9c', '#f39c12', '#9b59b6', '#1abc9c'];

  function init(opts) {
    _settings = opts.settings;
    _map = MapLayer.getMap();
    _layer = L.layerGroup();
    console.log('✓ GraphVisualization ready (Leaflet mode)');
  }

  function render(frame, params) {
    if (!frame || !params || !params.rsu_id || !params.timestamp) return;
    _currentParams = params;
    _currentDirection = params.direction || 'both';

    // Debounce rapid timeline scrubbing
    clearTimeout(_debounceTimer);
    _debounceTimer = setTimeout(() => _fetchAndRender(params), 120);
  }

  function _fetchAndRender(params) {
    const hasBbox = params.bbox && params.bbox.length === 4;
    const query = new URLSearchParams({
      rsu_id: params.rsu_id,
      min_x: hasBbox ? params.bbox[0] : -99999,
      max_x: hasBbox ? params.bbox[1] : 99999,
      min_y: hasBbox ? params.bbox[2] : -99999,
      max_y: hasBbox ? params.bbox[3] : 99999,
      max_hops: params.max_hops || 3,
      rssi_threshold: params.rssi_threshold !== undefined ? params.rssi_threshold : -100,
      sinr_threshold: params.sinr_threshold !== undefined ? params.sinr_threshold : 0,
      throughput_threshold: params.throughput_threshold !== undefined ? params.throughput_threshold : 0,
      timestamp: params.timestamp,
      path: params.path,
    });

    fetch('/api/graph/generate?' + query)
      .then(r => r.json())
      .then(data => {
        if (data.error) { _updateStats('⚠ ' + data.error); return; }
        _lastData = data;
        _drawGraph(data);
      })
      .catch(err => _updateStats('⚠ Fetch error: ' + err.message));
  }

  function _drawGraph(data) {
    _layer.clearLayers();

    // Pick the right subgraph
    let g;
    if (_currentDirection === 'uplink') g = data.uplink;
    else if (_currentDirection === 'downlink') g = data.downlink;
    else g = data.both;

    if (!g || !g.nodes || g.nodes.length === 0) {
      _updateStats('No nodes in graph');
      return;
    }

    // Build a quick lookup: id -> node
    const nodeById = {};
    for (const n of g.nodes) nodeById[n.id] = n;

    // BFS from RSU to compute hop distance
    const hopOf = {};
    const queue = [];
    for (const n of g.nodes) {
      if (n.type === 'rsu') { hopOf[n.id] = 0; queue.push(n.id); }
    }
    const adj = {};
    for (const e of g.edges) {
      if (!adj[e.source]) adj[e.source] = [];
      adj[e.source].push(e.target);
    }
    while (queue.length) {
      const cur = queue.shift();
      for (const nb of (adj[cur] || [])) {
        if (hopOf[nb] === undefined) { hopOf[nb] = hopOf[cur] + 1; queue.push(nb); }
      }
    }

    // Draw edges first (below nodes)
    for (const edge of g.edges) {
      const src = nodeById[edge.source];
      const tgt = nodeById[edge.target];
      if (!src || !tgt) continue;

      const hop = hopOf[edge.source] !== undefined ? hopOf[edge.source] : 0;
      const color = HOP_COLORS[Math.min(hop, HOP_COLORS.length - 1)];
      const srcLL = _toLatLon(src.x, src.y);
      const tgtLL = _toLatLon(tgt.x, tgt.y);

      const line = L.polyline([srcLL, tgtLL], { color, weight: 3, opacity: 0.75 });
      line.bindTooltip(
        `<b>${edge.source} → ${edge.target}</b><br>` +
        `Hop ${hop} | RSSI: ${edge.rssi_dbm != null ? edge.rssi_dbm.toFixed(1) : '?'} dBm<br>` +
        `SINR: ${edge.sinr_eff_db != null ? edge.sinr_eff_db.toFixed(1) : '?'} dB | ` +
        `Tput: ${edge.throughput_kbps != null ? (edge.throughput_kbps/1000).toFixed(1) : '?'} Mbps`,
        { sticky: true, className: 'node-label' }
      );
      _layer.addLayer(line);
    }

    // Draw nodes on top
    for (const node of g.nodes) {
      const hop = hopOf[node.id] !== undefined ? hopOf[node.id] : 99;
      const latlng = _toLatLon(node.x, node.y);
      const color = HOP_COLORS[Math.min(hop, HOP_COLORS.length - 1)];

      let marker;
      if (node.type === 'rsu') {
        marker = L.circleMarker(latlng, {
          radius: 10, color: '#922b21', fillColor: '#e74c3c', fillOpacity: 0.9, weight: 2,
        });
      } else {
        marker = L.circleMarker(latlng, {
          radius: 7, color: _darken(color, 40), fillColor: color, fillOpacity: 0.85, weight: 2,
        });
      }
      marker.bindTooltip(
        `<b>${node.id}</b> (hop ${hop})`,
        { permanent: false, direction: 'top', className: 'node-label' }
      );
      _layer.addLayer(marker);
    }

    const meta = data.metadata || {};
    _updateStats(
      `${g.nodes.length} nodes · ${g.edges.length} edges · t=${data.timestamp}` +
      (meta.links_filtered_out ? ` · ${meta.links_filtered_out} links filtered` : '')
    );
  }

  function _toLatLon(x, y) {
    const R = 6371000;
    const dx = x - (_settings.origin_x || 0);
    const dy = y - (_settings.origin_y || 0);
    const lat = _settings.center_lat + (dy / R) * (180 / Math.PI);
    const lon = _settings.center_lon + (dx / (R * Math.cos(_settings.center_lat * Math.PI / 180))) * (180 / Math.PI);
    return [lat, lon];
  }

  function _darken(hex, amount) {
    const r = Math.max(0, parseInt(hex.slice(1,3),16) - amount);
    const g = Math.max(0, parseInt(hex.slice(3,5),16) - amount);
    const b = Math.max(0, parseInt(hex.slice(5,7),16) - amount);
    return `rgb(${r},${g},${b})`;
  }

  function _updateStats(text) {
    const el = document.getElementById('graph-stats');
    if (el) el.textContent = text;
  }

  function setVisible(visible) {
    if (visible) _layer.addTo(_map);
    else _layer.remove();
  }

  function clear() { _layer.clearLayers(); }

  function setDirection(dir) {
    _currentDirection = dir;
    if (_lastData) _drawGraph(_lastData);  // re-draw with new direction without re-fetching
  }

  function getParams() { return _currentParams; }

  function updateSettings(s) { _settings = s; }

  return { init, render, clear, setVisible, setDirection, getParams, updateSettings };
})();
