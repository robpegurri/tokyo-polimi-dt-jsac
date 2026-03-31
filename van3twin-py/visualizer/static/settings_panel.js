/* settings_panel.js — settings form interaction */

const SettingsPanel = (() => {
  const toggle = document.getElementById('settings-toggle');
  const body = document.getElementById('settings-body');
  const applyBtn = document.getElementById('settings-apply-btn');

  const fields = {
    center_lat:        document.getElementById('s-center-lat'),
    center_lon:        document.getElementById('s-center-lon'),
    origin_x:          document.getElementById('s-origin-x'),
    origin_y:          document.getElementById('s-origin-y'),
    watch_interval_ms: document.getElementById('s-interval'),
  };

  // Threshold input IDs: metric -> [id-t0, id-t1, id-t2]
  const THR_IDS = {
    rssi_dbm:        ['thr-rssi-0', 'thr-rssi-1', 'thr-rssi-2'],
    sinr_eff_db:     ['thr-sinr-0', 'thr-sinr-1', 'thr-sinr-2'],
    throughput_kbps: ['thr-thput-0', 'thr-thput-1', 'thr-thput-2'],
    bler:            ['thr-bler-0',  'thr-bler-1',  'thr-bler-2'],
  };

  let onApply = null;
  let collapsed = false;

  function init(callback) {
    onApply = callback;

    toggle.addEventListener('click', () => {
      collapsed = !collapsed;
      body.classList.toggle('collapsed', collapsed);
      toggle.textContent = collapsed ? '⊕' : '⚙';
    });

    applyBtn.addEventListener('click', _apply);
  }

  function populate(settings) {
    for (const [key, el] of Object.entries(fields)) {
      if (settings[key] != null) el.value = settings[key];
    }
    if (settings.thresholds) {
      for (const [metric, ids] of Object.entries(THR_IDS)) {
        const t = settings.thresholds[metric];
        if (!t) continue;
        ids.forEach((id, i) => {
          const el = document.getElementById(id);
          if (el) el.value = t[i];
        });
      }
    }
  }

  function expand() {
    if (collapsed) {
      collapsed = false;
      body.classList.remove('collapsed');
      toggle.textContent = '⚙';
    }
    const thrSection = document.getElementById('threshold-section');
    if (thrSection) thrSection.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }

  function _apply() {
    const updates = {};
    for (const [key, el] of Object.entries(fields)) {
      updates[key] = parseFloat(el.value) || el.value;
    }

    // Collect thresholds
    updates.thresholds = {};
    for (const [metric, ids] of Object.entries(THR_IDS)) {
      updates.thresholds[metric] = ids.map(id => {
        const el = document.getElementById(id);
        return el ? parseFloat(el.value) : 0;
      });
    }

    if (onApply) onApply(updates);
  }

  return { init, populate, expand };
})();
