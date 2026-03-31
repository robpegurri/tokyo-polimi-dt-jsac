/* tooltip.js — popup HTML builders for links and nodes */

function shortLabel(id) {
  return id.replace(/^(car_|rsu_)/, '');
}

const MOD_COLORS = {
  'OUTAGE': '#e74c3c',
  'QPSK':   '#e67e22',
  '16QAM':  '#f1c40f',
  '64QAM':  '#2ecc71',
};

function fmtNum(v, dec = 1) {
  if (v == null || isNaN(v)) return '—';
  return Number(v).toFixed(dec);
}

function fmtKbps(kbps) {
  if (kbps == null || isNaN(kbps)) return '—';
  if (kbps >= 1000) return (kbps / 1000).toFixed(1) + ' Mbps';
  return kbps.toFixed(0) + ' kbps';
}

function _linkBlock(link) {
  if (!link) return '';
  const mod = link.modulation || 'OUTAGE';
  const badgeClass = `mod-${mod.replace('/', '').replace(' ', '')}`;
  return `
    <div class="link-popup">
      <strong>${shortLabel(link.tx)} &rarr; ${shortLabel(link.rx)}</strong>
      &nbsp;<span class="mod-badge ${badgeClass}">${mod}</span>
      &nbsp;MCS&nbsp;<strong>${link.mcs_index >= 0 ? link.mcs_index : '—'}</strong><br>
      RSSI:&nbsp;<strong>${fmtNum(link.rssi_dbm)} dBm</strong>
      &nbsp;&nbsp;SINR:&nbsp;<strong>${fmtNum(link.sinr_eff_db)} dB</strong><br>
      BLER:&nbsp;<strong>${fmtNum(link.bler, 3)}</strong>
      &nbsp;&nbsp;Tput:&nbsp;<strong>${fmtKbps(link.throughput_kbps)}</strong><br>
      LOS:&nbsp;<strong>${link.is_los ? 'Yes' : 'No'}</strong>
    </div>`;
}

function buildPairTooltip(linkAB, linkBA) {
  if (linkAB && linkBA) {
    return `<div class="pair-popup">${_linkBlock(linkAB)}<hr class="popup-sep">${_linkBlock(linkBA)}</div>`;
  }
  return `<div class="pair-popup">${_linkBlock(linkAB || linkBA)}</div>`;
}

function buildNodeTooltip(nodeId, nodeData, links) {
  const type = nodeData.type === 'rsu' ? 'RSU' : 'Vehicle';
  const activeLinks = links.filter(l =>
    l.modulation !== 'OUTAGE' && (l.tx === nodeId || l.rx === nodeId)
  );
  return `
    <div class="node-popup">
      <strong>${shortLabel(nodeId)}</strong> (${type})<br>
      x = ${fmtNum(nodeData.x, 1)} m, y = ${fmtNum(nodeData.y, 1)} m<br>
      Active links: <strong>${activeLinks.length}</strong>
    </div>`;
}
