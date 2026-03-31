/* timeline.js — timestamp store, slider control, playback engine */

const Timeline = (() => {
  let timestamps  = [];
  let frames      = {};      // ts_key -> frame (cache for on-demand mode)
  let frameIndex  = 0;
  let playing     = false;
  let autoFollow  = false;
  let speed       = 1.0;
  let timer       = null;
  let onFrameChange = null;

  // On-demand mode: set by openAsync()
  let _fetchFn    = null;    // async (tsKey) -> frame | null
  let _inflight   = new Set(); // ts_keys currently being fetched
  const PREFETCH  = 25;      // frames to pre-fetch ahead of current position

  const slider   = document.getElementById('time-slider');
  const tsLabel  = document.getElementById('ts-label');
  const playBtn  = document.getElementById('play-btn');
  const prevBtn  = document.getElementById('prev-btn');
  const nextBtn  = document.getElementById('next-btn');
  const speedSel = document.getElementById('speed-select');
  const jumpBtn  = document.getElementById('jump-live-btn');

  function init(callback) {
    onFrameChange = callback;

    slider.addEventListener('input', () => {
      autoFollow = false;
      jumpBtn.style.display = 'none';
      _seekTo(parseInt(slider.value));
    });
    slider.addEventListener('mousedown', () => { if (playing) pause(); });

    playBtn.addEventListener('click', () => playing ? pause() : play());
    prevBtn.addEventListener('click', () => { pause(); _seekTo(frameIndex - 1); });
    nextBtn.addEventListener('click', () => { pause(); _seekTo(frameIndex + 1); });

    speedSel.addEventListener('change', () => {
      speed = parseFloat(speedSel.value);
      if (playing) { pause(); play(); }
    });

    jumpBtn.addEventListener('click', () => {
      autoFollow = true;
      jumpBtn.style.display = 'none';
      _seekTo(timestamps.length - 1);
    });
  }

  // ── Replay: pre-loaded mode (kept for compatibility) ────────────────────────

  function loadAll(tsList, framesMap) {
    _fetchFn = null;
    timestamps = tsList;
    frames = framesMap;
    frameIndex = 0;
    playing = false;
    autoFollow = false;
    playBtn.textContent = '▶';
    jumpBtn.style.display = 'none';
    _updateSlider();
    _updateLabel();
    // Directly emit first frame — frames dict is fully populated
    if (timestamps.length > 0) {
      const key = timestamps[0];
      if (frames[key] && onFrameChange) onFrameChange(key, frames[key]);
    }
  }

  // ── Replay: on-demand mode ───────────────────────────────────────────────────

  function openAsync(tsList, fetchFn) {
    _fetchFn = fetchFn;
    timestamps = tsList;
    frames = {};
    _inflight.clear();
    frameIndex = 0;
    playing = false;
    autoFollow = false;
    playBtn.textContent = '▶';
    jumpBtn.style.display = 'none';
    _updateSlider();
    _updateLabel();
    _seekTo(0);  // triggers async fetch of first frame
  }

  // ── Live mode ────────────────────────────────────────────────────────────────

  function addFrame(ts, frame) {
    const key = String(ts);
    if (!frames[key]) {
      let i = timestamps.length;
      while (i > 0 && parseFloat(timestamps[i - 1]) > parseFloat(key)) i--;
      timestamps.splice(i, 0, key);
      _updateSlider();
    }
    frames[key] = frame;

    if (autoFollow) {
      frameIndex = timestamps.length - 1;
      slider.value = frameIndex;
      _emit(frameIndex);
      _updateLabel();
    }
  }

  function setAutoFollow(val) {
    autoFollow = val;
    jumpBtn.style.display = autoFollow ? 'none' : 'inline-block';
    if (val) _seekTo(timestamps.length - 1);
  }

  // ── Playback ─────────────────────────────────────────────────────────────────

  function play() {
    if (timestamps.length < 2) return;
    playing = true;
    playBtn.textContent = '⏸';
    _tick();
  }

  function pause() {
    playing = false;
    playBtn.textContent = '▶';
    clearTimeout(timer);
    timer = null;
  }

  function reset() {
    pause();
    timestamps = [];
    frames = {};
    _inflight.clear();
    _fetchFn = null;
    frameIndex = 0;
    autoFollow = false;
    jumpBtn.style.display = 'none';
    _updateSlider();
    tsLabel.textContent = 't = —';
  }

  // ── Internal ─────────────────────────────────────────────────────────────────

  function _tick() {
    if (!playing) return;
    if (frameIndex >= timestamps.length - 1) { pause(); return; }

    const nextIdx = frameIndex + 1;
    const nextKey = timestamps[nextIdx];
    const curTs   = parseFloat(timestamps[frameIndex]);
    const nextTs  = parseFloat(nextKey);
    const delay   = Math.max(16, (nextTs - curTs) * 1000 / speed);

    if (frames[nextKey]) {
      // Frame cached — advance immediately
      _seekTo(nextIdx);
      timer = setTimeout(_tick, delay);
    } else {
      // Frame not yet cached — wait 50ms and retry (prefetch should fill it)
      timer = setTimeout(_tick, 50);
    }
  }

  function _seekTo(i) {
    if (timestamps.length === 0) return;
    frameIndex = Math.max(0, Math.min(timestamps.length - 1, i));
    slider.value = frameIndex;
    _updateLabel();
    _emit(frameIndex);
  }

  function _emit(i) {
    const key = timestamps[i];
    if (!key) return;

    if (frames[key]) {
      onFrameChange && onFrameChange(key, frames[key]);
      _prefetch(i);
    } else if (_fetchFn) {
      // Fetch this frame then re-emit
      _fetchOne(key).then(frame => {
        if (frame) {
          frames[key] = frame;
          // Only fire callback if we're still on the same frame
          if (timestamps[frameIndex] === key) {
            onFrameChange && onFrameChange(key, frame);
          }
        }
        _prefetch(i);
      });
    }
  }

  function _prefetch(fromIdx) {
    if (!_fetchFn) return;
    for (let j = 1; j <= PREFETCH; j++) {
      const k = timestamps[fromIdx + j];
      if (k && !frames[k] && !_inflight.has(k)) {
        _fetchOne(k).then(f => { if (f) frames[k] = f; });
      }
    }
  }

  function _fetchOne(key) {
    _inflight.add(key);
    return _fetchFn(key).then(f => {
      _inflight.delete(key);
      return f;
    }).catch(() => {
      _inflight.delete(key);
      return null;
    });
  }

  function _updateSlider() {
    slider.max = Math.max(0, timestamps.length - 1);
    slider.value = frameIndex;
  }

  function _updateLabel() {
    const key = timestamps[frameIndex];
    tsLabel.textContent = key ? `t = ${parseFloat(key).toFixed(2)} s` : 't = —';
  }

  return { init, loadAll, openAsync, addFrame, setAutoFollow, play, pause, reset };
})();
