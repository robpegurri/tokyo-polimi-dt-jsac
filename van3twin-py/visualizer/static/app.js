/* app.js — application controller */

const METRIC_META = {
  rssi_dbm:        { label: 'RSSI',       unit: 'dBm',  lowerBetter: false },
  sinr_eff_db:     { label: 'SINR',       unit: 'dB',   lowerBetter: false },
  throughput_kbps: { label: 'Throughput', unit: 'kbps', lowerBetter: false },
  bler:            { label: 'BLER',       unit: '',     lowerBetter: true  },
};
const QUALITY_LABELS = ['Good', 'OK', 'Poor', 'Bad'];

// Fallback thresholds used when server settings don't include them yet
const DEFAULT_THRESHOLDS = {
  rssi_dbm:        [-70, -85, -100],
  sinr_eff_db:     [20, 10, 0],
  throughput_kbps: [1000, 500, 100],
  bler:            [0.05, 0.15, 0.3],
};

const App = (() => {
  let appSettings = {};
  let currentMode = 'replay';
  let ws = null;
  let focusNode = null;
  let currentMetric = 'rssi_dbm';
  let graphModeActive = false;

  // DOM refs
  const btnReplay   = document.getElementById('btn-replay');
  const btnLive     = document.getElementById('btn-live');
  const openBtn     = document.getElementById('open-btn');
  const fileInput   = document.getElementById('file-path-input');
  const liveInd     = document.getElementById('live-indicator');
  const statusBar   = document.getElementById('status-bar');
  const loading     = document.getElementById('loading-overlay');
  const loadingMsg  = document.getElementById('loading-msg');
  const filterNotice  = document.getElementById('filter-notice');
  const filterLabel   = document.getElementById('filter-node-label');
  const clearFilter   = document.getElementById('clear-filter-btn');
  const hideOutageBtn = document.getElementById('hide-outage-btn');
  const areaSelectBtn = document.getElementById('area-select-btn');
  const areaClearBtn  = document.getElementById('area-clear-btn');
  const areaCopyBtn   = document.getElementById('area-copy-btn');

  // Graph view controls
  const tabMapBtn      = document.getElementById('tab-map');
  const tabGraphBtn    = document.getElementById('tab-graph');
  const rsuSelector   = document.getElementById('rsu-selector');
  const areaDisplay   = document.getElementById('area-display');
  const maxHopsInput  = document.getElementById('max-hops');
  const rssiThresholdInput = document.getElementById('rssi-threshold');
  const sinrThresholdInput = document.getElementById('sinr-threshold');
  const throughputThresholdInput = document.getElementById('throughput-threshold');
  const directionSelector = document.getElementById('direction-selector');
  const generateGraphBtn = document.getElementById('generate-graph-btn');

  async function init() {
    console.log('📱 App.init() starting...');
    try {
      const resp = await fetch('/api/settings');
      appSettings = await resp.json();
      console.log('✓ Settings loaded:', appSettings);

      fileInput.value = appSettings.watch_path || '';

      console.log('🗺️ Initializing MapLayer...');
      MapLayer.init({ settings: appSettings });
      console.log('✓ MapLayer initialized');

      console.log('⏱️ Initializing Timeline...');
      Timeline.init(_onFrameChange);
      console.log('✓ Timeline initialized');

      console.log('⚙️ Initializing SettingsPanel...');
      SettingsPanel.init(_onSettingsApply);
      SettingsPanel.populate(appSettings);
      console.log('✓ SettingsPanel initialized');

      console.log('📊 Initializing GraphVisualization...');
      GraphVisualization.init({ settings: appSettings });
      console.log('✓ GraphVisualization initialized');

      // Restore metric button state
      if (appSettings.metric) {
        currentMetric = appSettings.metric;
        document.querySelectorAll('[data-metric]').forEach(b =>
          b.classList.toggle('active', b.dataset.metric === currentMetric));
      }
      _updateLegend(currentMetric);
      console.log('✓ Legend updated');

      console.log('🔌 Attaching event listeners...');
      btnReplay.addEventListener('click', () => _setMode('replay'));
      btnLive.addEventListener('click', () => _setMode('live'));
      openBtn.addEventListener('click', _onOpen);
      fileInput.addEventListener('keydown', e => { if (e.key === 'Enter') _onOpen(); });
      clearFilter.addEventListener('click', () => clearNodeFilter());

      hideOutageBtn.addEventListener('click', () => {
        const active = hideOutageBtn.classList.toggle('active');
        MapLayer.setHideOutage(active);
      });

      areaSelectBtn.addEventListener('click', () => {
        areaSelectBtn.classList.add('active');
        areaSelectBtn.textContent = '✎ Drawing…';
        MapLayer.startAreaSelectMode();
      });

      areaClearBtn.addEventListener('click', () => {
        MapLayer.clearArea();
        areaClearBtn.style.display = 'none';
        areaCopyBtn.style.display = 'none';
        areaSelectBtn.style.display = 'inline-block';
        areaSelectBtn.classList.remove('active');
        areaSelectBtn.textContent = '■ Area';
      });

      areaCopyBtn.addEventListener('click', () => {
        const bbox = MapLayer.getAreaBoundingBox();
        if (!bbox) {
          alert('No area selected');
          return;
        }
        const text = `(${bbox.minX.toFixed(2)}, ${bbox.maxX.toFixed(2)}, ${bbox.minY.toFixed(2)}, ${bbox.maxY.toFixed(2)})`;
        navigator.clipboard.writeText(text).then(() => {
          areaCopyBtn.textContent = '✓ Copied';
          setTimeout(() => { areaCopyBtn.textContent = '📋 Copy'; }, 2000);
        }).catch(err => {
          alert('Failed to copy: ' + err);
        });
      });

      // Helper: switch between map and graph views
      function _switchToMap() {
        tabMapBtn.classList.add('active');
        tabGraphBtn.classList.remove('active');
        graphModeActive = false;
        document.getElementById('graph-controls').style.display = 'none';
        MapLayer.setLinksVisible(true);
        GraphVisualization.clear();
        GraphVisualization.setVisible(false);
      }

      function _switchToGraph() {
        tabGraphBtn.classList.add('active');
        tabMapBtn.classList.remove('active');
        graphModeActive = true;
        document.getElementById('graph-controls').style.display = 'flex';
        MapLayer.setLinksVisible(false);
        GraphVisualization.setVisible(true);
        // Auto-generate if RSU already selected and frame available
        if (rsuSelector.value && window.currentFrame) _generateGraph();
      }

      tabMapBtn.addEventListener('click', _switchToMap);
      tabGraphBtn.addEventListener('click', _switchToGraph);

      // Direction selector change
      directionSelector.addEventListener('change', (e) => {
        GraphVisualization.setDirection(e.target.value);
      });

      // Generate graph button
      generateGraphBtn.addEventListener('click', _generateGraph);

      document.querySelectorAll('[data-metric]').forEach(btn => {
        btn.addEventListener('click', () => {
          document.querySelectorAll('[data-metric]').forEach(b => b.classList.remove('active'));
          btn.classList.add('active');
          currentMetric = btn.dataset.metric;
          MapLayer.setMetric(currentMetric);
          _updateLegend(currentMetric);
        });
      });

      console.log('✓ Event listeners attached');
      _loadFileList();
      _setMode('replay');
      if (appSettings.watch_path) await _loadReplay(appSettings.watch_path);
      console.log('✓ App.init() complete');
    } catch (err) {
      console.error('❌ App.init() error:', err);
      throw err;
    }
  }

  // ── LEGEND ─────────────────────────────────────────────────────────────────

  function _fmtThr(v, metric) {
    if (v == null) return '?';
    if (metric === 'throughput_kbps' && Math.abs(v) >= 1000) return (v / 1000).toFixed(0) + 'k';
    if (metric === 'bler') return Number(v).toFixed(2);
    return Number.isInteger(v) ? String(v) : Number(v).toFixed(1);
  }

  function _updateLegend(metric) {
    const panel = document.getElementById('legend-panel');
    if (!panel) return;
    const meta = METRIC_META[metric] || { label: metric, unit: '', lowerBetter: false };
    // Use server thresholds if available, fall back to hardcoded defaults
    const thrMap = (appSettings && appSettings.thresholds) ? appSettings.thresholds : DEFAULT_THRESHOLDS;
    const t = thrMap[metric] || DEFAULT_THRESHOLDS[metric] || [0, 0, 0];
    const u = meta.unit ? ' ' + meta.unit : '';
    const lb = meta.lowerBetter;

    // Build 4 threshold band labels
    const f = v => _fmtThr(v, metric);
    let bands;
    if (!lb) {
      // Higher is better: ≥t[0]=green, t[1]–t[0]=yellow, t[2]–t[1]=orange, <t[2]=red
      bands = [
        `≥ ${f(t[0])}${u}`,
        `${f(t[1])}–${f(t[0])}${u}`,
        `${f(t[2])}–${f(t[1])}${u}`,
        `< ${f(t[2])}${u}`,
      ];
    } else {
      // Lower is better: ≤t[0]=green, t[0]–t[1]=yellow, t[1]–t[2]=orange, >t[2]=red
      bands = [
        `≤ ${f(t[0])}${u}`,
        `${f(t[0])}–${f(t[1])}${u}`,
        `${f(t[1])}–${f(t[2])}${u}`,
        `> ${f(t[2])}${u}`,
      ];
    }

    panel.innerHTML = `
      <h4>${meta.label} <button class="legend-cfg-btn" id="legend-cfg-btn" title="Configure thresholds">⚙</button></h4>
      ${QUALITY_COLORS.map((c, i) => `
        <div class="legend-row">
          <div class="legend-swatch" style="background:${c}"></div>
          <span>${QUALITY_LABELS[i]}: ${bands[i]}</span>
        </div>`).join('')}
      <div class="legend-row">
        <div class="legend-swatch" style="background:#e74c3c"></div>
        <span>OUTAGE</span>
      </div>
      <div class="legend-row" style="margin-top:6px">
        <div class="legend-swatch" style="background:repeating-linear-gradient(90deg,#aaa 0,#aaa 5px,transparent 5px,transparent 9px)"></div>
        <span>NLOS</span>
      </div>
      <div class="legend-row" style="margin-top:6px">
        <div class="legend-icon"></div>
        <span>Vehicle</span>
      </div>
      <div class="legend-row">
        <div class="legend-icon rsu"></div>
        <span>RSU</span>
      </div>`;

    document.getElementById('legend-cfg-btn').addEventListener('click', () => {
      SettingsPanel.expand();
    });
  }

  // ── MODE ───────────────────────────────────────────────────────────────────

  function _setMode(mode) {
    currentMode = mode;
    btnReplay.classList.toggle('active', mode === 'replay');
    btnLive.classList.toggle('active', mode === 'live');
    liveInd.style.display = mode === 'live' ? 'flex' : 'none';
    document.getElementById('jump-live-btn').style.display = mode === 'live' ? 'inline-block' : 'none';
    if (mode === 'replay') _stopLive();
    _setStatus(mode === 'live' ? 'Live mode — watching file for new data' : 'Replay mode');
  }

  async function _onOpen() {
    const path = fileInput.value.trim();
    if (!path) return;
    appSettings.watch_path = path;
    await _saveSettings({ watch_path: path });
    if (currentMode === 'replay') await _loadReplay(path);
    else _startLive(path);
  }

  // ── REPLAY ─────────────────────────────────────────────────────────────────

  async function _loadReplay(path) {
    _showLoading('Loading CSV…');
    Timeline.reset();
    MapLayer.clearAll();

    try {
      const resp = await fetch(`/api/file/load?path=${encodeURIComponent(path)}`);
      const data = await resp.json();

      if (data.error) {
        _setStatus(`Error: ${data.error}`);
        _hideLoading();
        return;
      }

      Timeline.loadAll(data.timestamps, data.frames);
      _setStatus(`Loaded ${data.timestamps.length} frames from ${path}`);
    } catch (e) {
      _setStatus(`Failed to load: ${e.message}`);
    } finally {
      _hideLoading();
    }
  }

  // ── LIVE ───────────────────────────────────────────────────────────────────

  function _startLive(path) {
    _stopLive();
    Timeline.reset();
    MapLayer.clearAll();
    Timeline.setAutoFollow(true);

    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    const url = `${proto}://${location.host}/ws/live?path=${encodeURIComponent(path)}`;
    ws = new WebSocket(url);

    ws.onopen = () => _setStatus(`Connected — watching ${path}`);
    ws.onmessage = (evt) => {
      const msg = JSON.parse(evt.data);
      if (msg.type === 'frame') Timeline.addFrame(msg.timestamp, msg);
      else if (msg.type === 'error') _setStatus(`Server error: ${msg.message}`);
      else if (msg.type === 'ping') ws.send(JSON.stringify({ type: 'pong' }));
    };
    ws.onerror = () => _setStatus('WebSocket error');
    ws.onclose = () => {
      if (currentMode === 'live') _setStatus('Connection closed — reconnecting in 3s…');
      setTimeout(() => {
        if (currentMode === 'live' && fileInput.value) _startLive(fileInput.value);
      }, 3000);
    };
  }

  function _stopLive() {
    if (ws) { ws.onclose = null; ws.close(); ws = null; }
  }

  // ── FRAME RENDER ───────────────────────────────────────────────────────────

  function _onFrameChange(tsKey, frame) {
    window.currentFrame = frame;
    window.currentTimestamp = tsKey;
    MapLayer.render(frame);
    _populateRsuList(frame);
    // Auto-update graph when timeline scrubs, if in graph mode
    if (graphModeActive && rsuSelector.value) _generateGraph();
  }

  // ── NODE FILTER ────────────────────────────────────────────────────────────

  function setNodeFilter(nodeId) {
    focusNode = nodeId;
    MapLayer.setFocusNode(nodeId);
    filterLabel.textContent = nodeId;
    filterNotice.classList.add('visible');
  }

  function onAreaSet() {
    areaSelectBtn.classList.remove('active');
    areaSelectBtn.textContent = '■ Area';
    areaSelectBtn.style.display = 'none';
    areaClearBtn.style.display = 'inline-block';
    areaCopyBtn.style.display = 'inline-block';
    _updateAreaDisplay();
  }

  // ── GRAPH VIEW FUNCTIONS ────────────────────────────────────────────────────

  function _updateAreaDisplay() {
    const bbox = MapLayer.getAreaBoundingBox();
    if (bbox) {
      areaDisplay.textContent = `(${bbox.minX.toFixed(0)}, ${bbox.maxX.toFixed(0)}, ${bbox.minY.toFixed(0)}, ${bbox.maxY.toFixed(0)})`;
    } else {
      areaDisplay.textContent = 'No filter (all vehicles)';
    }
  }

  function _populateRsuList(frame) {
    // Populate RSU dropdown from current frame's nodes
    const rsus = Object.entries(frame.nodes || {})
      .filter(([id, node]) => node.type === 'rsu')
      .map(([id]) => id);

    const currentValue = rsuSelector.value;
    rsuSelector.innerHTML = '<option value="">Select RSU...</option>';

    for (const rsu of rsus) {
      const option = document.createElement('option');
      option.value = rsu;
      option.textContent = rsu;
      rsuSelector.appendChild(option);
    }

    if (currentValue && rsus.includes(currentValue)) {
      rsuSelector.value = currentValue;
    }
  }

  function _generateGraph() {
    const rsuId = rsuSelector.value;
    if (!rsuId) {
      alert('Please select an RSU');
      return;
    }

    if (!appSettings.watch_path) {
      alert('No file loaded');
      return;
    }

    if (!window.currentFrame || !window.currentTimestamp) {
      alert('No frame data available — please load a CSV file first');
      return;
    }

    // Area is optional — null means no geographic filter (all vehicles included)
    const bbox = MapLayer.getAreaBoundingBox();

    const params = {
      rsu_id: rsuId,
      bbox: bbox ? [bbox.minX, bbox.maxX, bbox.minY, bbox.maxY] : null,
      max_hops: parseInt(maxHopsInput.value) || 3,
      rssi_threshold: parseFloat(rssiThresholdInput.value) || -100,
      sinr_threshold: parseFloat(sinrThresholdInput.value) || 0,
      throughput_threshold: parseFloat(throughputThresholdInput.value) || 0,
      direction: directionSelector.value || 'both',
      path: appSettings.watch_path,
      timestamp: parseFloat(window.currentTimestamp),  // tsKey string → float
    };

    console.log('📊 Generating graph with params:', params);
    GraphVisualization.render(window.currentFrame, params);
  }

  function clearNodeFilter() {
    focusNode = null;
    MapLayer.clearFocus();
    filterNotice.classList.remove('visible');
  }

  // ── SETTINGS ───────────────────────────────────────────────────────────────

  async function _onSettingsApply(updates) {
    Object.assign(appSettings, updates);
    await _saveSettings(updates);
    MapLayer.updateSettings(appSettings);
    if (updates.thresholds) {
      MapLayer.setThresholds(updates.thresholds);
      _updateLegend(currentMetric);
    }
  }

  async function _saveSettings(partial) {
    try {
      const merged = { ...appSettings, ...partial };
      const resp = await fetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(merged),
      });
      appSettings = await resp.json();
    } catch (e) {
      console.warn('Failed to save settings:', e);
    }
  }

  // ── FILE LIST ──────────────────────────────────────────────────────────────

  async function _loadFileList() {
    try {
      const resp = await fetch('/api/file/list');
      const data = await resp.json();
      if (data.files && data.files.length > 0) {
        const list = document.createElement('datalist');
        list.id = 'csv-files-list';
        data.files.forEach(f => {
          const opt = document.createElement('option');
          opt.value = f;
          list.appendChild(opt);
        });
        document.body.appendChild(list);
        fileInput.setAttribute('list', 'csv-files-list');
      }
    } catch (e) { /* non-critical */ }
  }

  // ── HELPERS ────────────────────────────────────────────────────────────────

  function _setStatus(msg) { statusBar.textContent = msg; }
  function _showLoading(msg) { loadingMsg.textContent = msg; loading.classList.remove('hidden'); }
  function _hideLoading() { loading.classList.add('hidden'); }

  return { init, setNodeFilter, clearNodeFilter, onAreaSet };
})();

window.App = App;
document.addEventListener('DOMContentLoaded', () => {
  App.init().catch(err => {
    console.error('❌ App.init() failed:', err);
    document.getElementById('status-bar').textContent = `ERROR: ${err.message}`;
  });
});
