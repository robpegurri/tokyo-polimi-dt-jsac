/* map_layer.js — Leaflet map, node markers, and link polylines */

const R_EARTH = 6371000;

// 4-level color scale: good → ok → poor → bad
const QUALITY_COLORS = ['#2ecc71', '#f1c40f', '#e67e22', '#e74c3c'];

// Perpendicular offset so both direction-lines appear side-by-side with no gap.
// Value is in map meters; adjust if your simulation scale is very different.
const OFFSET_METERS = 0.5;

function metersToLatLon(x, y, settings) {
  const dx = x - (settings.origin_x || 0);
  const dy = y - (settings.origin_y || 0);
  const lat = settings.center_lat + (dy / R_EARTH) * (180 / Math.PI);
  const lon = settings.center_lon + (dx / (R_EARTH * Math.cos(settings.center_lat * Math.PI / 180))) * (180 / Math.PI);
  return [lat, lon];
}

// Inverse: convert lat/lon back to meter coordinates
function latLonToMeters(lat, lon, settings) {
  const dlat = (lat - settings.center_lat) * (Math.PI / 180);
  const dlon = (lon - settings.center_lon) * (Math.PI / 180);
  const dy = dlat * R_EARTH;
  const dx = dlon * R_EARTH * Math.cos(settings.center_lat * Math.PI / 180);
  const x = dx + (settings.origin_x || 0);
  const y = dy + (settings.origin_y || 0);
  return [x, y];
}

function rsuIcon() {
  return L.divIcon({
    html: `<svg width="16" height="16" viewBox="0 0 16 16">
      <rect x="1" y="1" width="14" height="14" rx="2"
            fill="rgba(141,110,99,0.7)" stroke="#8d6e63" stroke-width="1.5"/>
    </svg>`,
    iconSize: [16, 16],
    iconAnchor: [8, 8],
    className: '',
  });
}

// ──────────────────────────────────────────────────────────────────────────────

const MapLayer = (() => {
  let map = null;
  let nodeMarkers = {};   // nodeId -> L.marker / L.circleMarker
  let linkLines = {};     // "sortedA|sortedB:a" / ":b" -> L.polyline
  let currentFrame = null;
  let settings = {};
  let selectedMetric = 'rssi_dbm';
  let linkDirection = 'both';
  let focusNode = null;
  let hideOutage = false;

  // Threshold state — keyed by metric name, value = [t0, t1, t2]
  // Lower-is-better only for BLER; all others: higher = better.
  let thresholds = {
    rssi_dbm:        [-70, -85, -100],
    sinr_eff_db:     [20,  10,  0],
    throughput_kbps: [1000, 500, 100],
    bler:            [0.05, 0.15, 0.3],
  };

  // Area selection state
  let areaSelectMode = false;
  let drawStart = null;
  let drawRect = null;
  let areaRect = null;
  let areaBounds = null;

  // ── INIT ────────────────────────────────────────────────────────────────────

  function init(opts) {
    console.log('🗺️ MapLayer.init() called with:', opts);
    if (typeof L === 'undefined') {
      throw new Error('Leaflet library (L) not found - check if leaflet.js loaded correctly');
    }
    settings = opts.settings;
    if (opts.settings.thresholds) thresholds = { ...thresholds, ...opts.settings.thresholds };
    try {
      const mapDiv = document.getElementById('map');
      if (!mapDiv) throw new Error('Map container #map not found in DOM');
      console.log('✓ Map container found, initializing...');

      map = L.map('map', { zoomControl: true }).setView(
        [settings.center_lat, settings.center_lon], 17
      );
      console.log('✓ Map initialized at', [settings.center_lat, settings.center_lon]);
      L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
        maxZoom: 19,
      }).addTo(map);
      console.log('✓ Tile layer added');
      return map;
    } catch (e) {
      console.error('❌ MapLayer.init() failed:', e);
      throw e;
    }
  }

  function updateSettings(newSettings) {
    settings = newSettings;
    if (newSettings.thresholds) thresholds = { ...thresholds, ...newSettings.thresholds };
    map.setView([settings.center_lat, settings.center_lon]);
    if (currentFrame) render(currentFrame);
  }

  function setMetric(metric) {
    selectedMetric = metric;
    if (currentFrame) render(currentFrame);
  }

  function setThresholds(t) {
    thresholds = { ...thresholds, ...t };
    if (currentFrame) render(currentFrame);
  }

  function setLinkDirection(dir) {
    linkDirection = dir;
    if (currentFrame) render(currentFrame);
  }

  function setHideOutage(val) {
    hideOutage = val;
    if (currentFrame) render(currentFrame);
  }

  // ── AREA SELECTION ─────────────────────────────────────────────────────────

  function startAreaSelectMode() {
    if (areaSelectMode) { cancelAreaSelectMode(); return; }
    areaSelectMode = true;
    map.getContainer().style.cursor = 'crosshair';
    map.dragging.disable();
    map.once('mousedown', _onDrawStart);
  }

  function cancelAreaSelectMode() {
    areaSelectMode = false;
    map.getContainer().style.cursor = '';
    map.dragging.enable();
    map.off('mousedown', _onDrawStart);
    map.off('mousemove', _onDrawMove);
    map.off('mouseup', _onDrawEnd);
    if (drawRect) { drawRect.remove(); drawRect = null; }
    drawStart = null;
  }

  function clearArea() {
    if (areaRect) { areaRect.remove(); areaRect = null; }
    areaBounds = null;
    if (currentFrame) render(currentFrame);
  }

  // Get area bounding box as (minX, maxX, minY, maxY) in meter coordinates
  function getAreaBoundingBox() {
    if (!areaBounds) return null;
    const sw = areaBounds.getSouthWest();  // bottom-left
    const ne = areaBounds.getNorthEast();  // top-right
    const [swX, swY] = latLonToMeters(sw.lat, sw.lng, settings);
    const [neX, neY] = latLonToMeters(ne.lat, ne.lng, settings);
    const minX = Math.min(swX, neX);
    const maxX = Math.max(swX, neX);
    const minY = Math.min(swY, neY);
    const maxY = Math.max(swY, neY);
    return { minX, maxX, minY, maxY };
  }

  function _onDrawStart(e) {
    drawStart = e.latlng;
    drawRect = L.rectangle([e.latlng, e.latlng], {
      color: '#3d5afe', weight: 2, dashArray: '6,3',
      fillColor: '#3d5afe', fillOpacity: 0.12, interactive: false,
    }).addTo(map);
    map.on('mousemove', _onDrawMove);
    map.once('mouseup', _onDrawEnd);
  }

  function _onDrawMove(e) {
    if (drawRect && drawStart) drawRect.setBounds(L.latLngBounds(drawStart, e.latlng));
  }

  function _onDrawEnd(e) {
    map.off('mousemove', _onDrawMove);
    map.getContainer().style.cursor = '';
    map.dragging.enable();
    areaSelectMode = false;
    if (areaRect) areaRect.remove();
    areaRect = drawRect;
    drawRect = null;
    areaBounds = L.latLngBounds(drawStart, e.latlng);
    drawStart = null;
    areaRect.setStyle({ color: '#64b5f6', weight: 2, dashArray: null, fillColor: '#64b5f6', fillOpacity: 0.08 });
    if (currentFrame) render(currentFrame);
    window.App && window.App.onAreaSet();
  }

  function setFocusNode(nodeId) {
    focusNode = nodeId;
    if (currentFrame) render(currentFrame);
  }

  function clearFocus() {
    focusNode = null;
    if (currentFrame) render(currentFrame);
  }

  function render(frame) {
    currentFrame = frame;
    _renderNodes(frame.nodes, frame.links);
    _renderLinks(frame.nodes, frame.links);
  }

  // ── METRIC COLOR ────────────────────────────────────────────────────────────

  function _linkColor(link) {
    let val = link[selectedMetric];
    const t = thresholds[selectedMetric];
    if (!t || val == null) return '#888';
    // Convert throughput from kbps to Mbps for threshold comparison
    if (selectedMetric === 'throughput_kbps') {
      val = val / 1000;
    }
    const [c0, c1, c2, c3] = QUALITY_COLORS;
    if (selectedMetric === 'bler') {
      // Lower is better
      return val <= t[0] ? c0 : val <= t[1] ? c1 : val <= t[2] ? c2 : c3;
    }
    // Higher is better (RSSI, SINR, Throughput)
    return val >= t[0] ? c0 : val >= t[1] ? c1 : val >= t[2] ? c2 : c3;
  }

  // ── NODES ───────────────────────────────────────────────────────────────────

  function _renderNodes(nodes, links) {
    const seen = new Set();

    for (const [id, data] of Object.entries(nodes)) {
      seen.add(id);
      const latlng = metersToLatLon(data.x, data.y, settings);
      const inArea = !areaBounds || areaBounds.contains(L.latLng(latlng));
      const opacity = inArea ? 0.85 : 0.25;

      if (nodeMarkers[id]) {
        nodeMarkers[id].setLatLng(latlng);
        if (data.type !== 'rsu') {
          nodeMarkers[id].setStyle({ fillOpacity: opacity, opacity: inArea ? 1 : 0.3 });
        } else {
          nodeMarkers[id].setOpacity(opacity);
        }
      } else {
        let marker;
        if (data.type === 'rsu') {
          marker = L.marker(latlng, { icon: rsuIcon(), zIndexOffset: 100, opacity });
        } else {
          marker = L.circleMarker(latlng, {
            radius: 7, color: '#2980b9', fillColor: '#3498db',
            fillOpacity: opacity, weight: 2, zIndexOffset: 200,
          });
        }
        marker.addTo(map);
        marker.bindTooltip(shortLabel(id), {
          permanent: true, direction: 'top',
          offset: [0, data.type === 'rsu' ? -10 : -8],
          className: 'node-label',
        });
        marker.on('click', () => {
          if (focusNode === id) window.App && window.App.clearNodeFilter();
          else window.App && window.App.setNodeFilter(id);
        });
        marker.on('mouseover', function () {
          this.bindPopup(buildNodeTooltip(id, data, links), { autoPan: false }).openPopup();
        });
        marker.on('mouseout', function () { this.closePopup(); });
        nodeMarkers[id] = marker;
      }
    }

    for (const id of Object.keys(nodeMarkers)) {
      if (!seen.has(id)) { nodeMarkers[id].remove(); delete nodeMarkers[id]; }
    }
  }

  // ── LINKS ───────────────────────────────────────────────────────────────────

  function _filterLinks(links, nodes) {
    let filtered = links;

    if (hideOutage) {
      filtered = filtered.filter(l => l.modulation !== 'OUTAGE');
    }

    if (focusNode) {
      filtered = filtered.filter(l => l.tx === focusNode || l.rx === focusNode);
    }

    if (areaBounds && nodes) {
      filtered = filtered.filter(l => {
        const txNode = nodes[l.tx];
        const rxNode = nodes[l.rx];
        if (!txNode || !rxNode) return false;
        const txLL = metersToLatLon(txNode.x, txNode.y, settings);
        const rxLL = metersToLatLon(rxNode.x, rxNode.y, settings);
        return areaBounds.contains(L.latLng(txLL)) && areaBounds.contains(L.latLng(rxLL));
      });
    }

    if (linkDirection === 'tx_only') {
      filtered = filtered.filter(l => l.tx === focusNode || focusNode === null);
      if (!focusNode) filtered = _dedupeDirection(filtered);
    } else if (linkDirection === 'rx_only') {
      if (!focusNode) filtered = _dedupeDirection(filtered);
    } else if (linkDirection === 'worst') {
      filtered = _dedupeByQuality(filtered, 'worst');
    } else if (linkDirection === 'best') {
      filtered = _dedupeByQuality(filtered, 'best');
    }
    // 'both': keep all — will produce split lines

    return filtered;
  }

  function _dedupeDirection(links) {
    const seen = new Set();
    const result = [];
    for (const l of links) {
      const key = [l.tx, l.rx].sort().join('|');
      if (seen.has(key)) continue;
      seen.add(key);
      result.push(l);
    }
    return result;
  }

  function _dedupeByQuality(links, prefer) {
    const pairs = {};
    for (const l of links) {
      const key = [l.tx, l.rx].sort().join('|');
      if (!pairs[key]) { pairs[key] = l; continue; }
      const better = l.mcs_index > pairs[key].mcs_index;
      if ((prefer === 'best' && better) || (prefer === 'worst' && !better)) pairs[key] = l;
    }
    return Object.values(pairs);
  }

  function _renderLinks(nodes, links) {
    const filtered = _filterLinks(links, nodes);
    const seen = new Set();

    // Group filtered links by unordered pair
    const pairMap = {};
    for (const link of filtered) {
      const key = [link.tx, link.rx].sort().join('|');
      if (!pairMap[key]) pairMap[key] = [];
      pairMap[key].push(link);
    }

    for (const [pairKey, pairLinks] of Object.entries(pairMap)) {
      const [nodeAId, nodeBId] = pairKey.split('|');
      const nodeA = nodes[nodeAId];
      const nodeB = nodes[nodeBId];
      if (!nodeA || !nodeB) continue;

      const latlngA = metersToLatLon(nodeA.x, nodeA.y, settings);
      const latlngB = metersToLatLon(nodeB.x, nodeB.y, settings);

      const linkAB = pairLinks.find(l => l.tx === nodeAId) || null;
      const linkBA = pairLinks.find(l => l.tx === nodeBId) || null;
      const repr = linkAB || linkBA;
      const dashArray = repr.is_los ? null : '8,5';

      const keyA = pairKey + ':a';
      const keyB = pairKey + ':b';

      if (linkAB && linkBA) {
        // Two full-length parallel lines, offset perpendicularly — no midpoint gap
        seen.add(keyA);
        seen.add(keyB);
        _upsertLine(keyA, _offsetLine(latlngA, latlngB, +OFFSET_METERS), _linkColor(linkAB), dashArray, linkAB, linkBA);
        _upsertLine(keyB, _offsetLine(latlngA, latlngB, -OFFSET_METERS), _linkColor(linkBA), dashArray, linkAB, linkBA);
      } else {
        // Only one direction known — single centred line
        const link = linkAB || linkBA;
        const latlngs = (link === linkAB) ? [latlngA, latlngB] : [latlngB, latlngA];
        seen.add(keyA);
        _upsertLine(keyA, latlngs, _linkColor(link), dashArray, link, null);
      }
    }

    for (const key of Object.keys(linkLines)) {
      if (!seen.has(key)) { linkLines[key].remove(); delete linkLines[key]; }
    }
  }

  // Shift a line segment by `meters` perpendicular to its direction
  function _offsetLine(a, b, meters) {
    const dLat = b[0] - a[0];
    const dLon = b[1] - a[1];
    const len  = Math.sqrt(dLat * dLat + dLon * dLon) || 1;
    const sc   = (meters / R_EARTH) * (180 / Math.PI);
    const oLat = -dLon / len * sc;
    const oLon =  dLat / len * sc;
    return [[a[0] + oLat, a[1] + oLon], [b[0] + oLat, b[1] + oLon]];
  }

  function _upsertLine(key, latlngs, color, dashArray, linkAB, linkBA) {
    const weight = 4;
    if (linkLines[key]) {
      linkLines[key].setLatLngs(latlngs);
      linkLines[key].setStyle({ color, weight, dashArray, opacity: 0.85 });
      linkLines[key]._pairData = { linkAB, linkBA };
    } else {
      const pl = L.polyline(latlngs, { color, weight, dashArray, opacity: 0.85 }).addTo(map);
      pl._pairData = { linkAB, linkBA };
      pl.on('click', function (e) {
        L.popup({ autoPan: false })
          .setLatLng(e.latlng)
          .setContent(buildPairTooltip(this._pairData.linkAB, this._pairData.linkBA))
          .openOn(map);
      });
      pl.on('mouseover', function (e) {
        this.setStyle({ opacity: 1, weight: weight + 2 });
        L.popup({ autoPan: false })
          .setLatLng(e.latlng)
          .setContent(buildPairTooltip(this._pairData.linkAB, this._pairData.linkBA))
          .openOn(map);
      });
      pl.on('mouseout', function () {
        this.setStyle({ opacity: 0.85, weight });
        map.closePopup();
      });
      linkLines[key] = pl;
    }
  }

  function clearAll() {
    for (const m of Object.values(nodeMarkers)) m.remove();
    for (const l of Object.values(linkLines)) l.remove();
    nodeMarkers = {};
    linkLines = {};
    currentFrame = null;
  }

  function getMap() { return map; }

  function setLinksVisible(visible) {
    for (const l of Object.values(linkLines)) {
      if (visible) l.addTo(map); else l.remove();
    }
  }

  return {
    init, render, updateSettings,
    setMetric, setThresholds, setLinkDirection, setHideOutage,
    startAreaSelectMode, clearArea, getAreaBoundingBox,
    setFocusNode, clearFocus, clearAll, getMap, setLinksVisible,
  };
})();
