"""
file_index.py — fast CSV byte-offset indexer for on-demand frame retrieval.

build_index(): single pass through the file, records the byte offset of the
first row of each timestamp group.  Only the timestamp column is parsed —
everything else is skipped — so it runs at near-raw I/O speed.

fetch_frame(): seeks directly to the stored offset and parses only the rows
that belong to the requested timestamp.  Cost is proportional to the size of
one frame (typically a few KB), not the whole file.

get_index(): wrapper that caches the result in memory and reuses it as long as
the file's mtime has not changed.
"""

import os
from typing import Optional

from data_parser import parse_row, rows_to_frame

# path -> (mtime, timestamps, offset_index, ts_to_idx, header)
_cache: dict[str, tuple] = {}


def _build(path: str) -> tuple[list[str], dict[str, int], list[str]]:
    """
    Single-pass scan.  Returns (timestamps, {ts_key: byte_offset}, header).
    Assumes the file is sorted by timestamp (simulation output always is).
    """
    timestamps: list[str] = []
    offset_index: dict[str, int] = {}
    current_key: Optional[str] = None

    with open(path, "rb") as f:
        header_raw = f.readline()
        header = header_raw.decode("utf-8", errors="replace").strip().split(",")
        try:
            ts_col = header.index("timestamp")
        except ValueError:
            ts_col = 0

        while True:
            pos = f.tell()
            line = f.readline()
            if not line:
                break
            try:
                fields = line.split(b",")
                ts_val = float(fields[ts_col])
                ts_key = f"{ts_val:.6g}"
            except (ValueError, IndexError):
                continue

            if ts_key != current_key:
                timestamps.append(ts_key)
                offset_index[ts_key] = pos
                current_key = ts_key

    return timestamps, offset_index, header


def get_index(path: str) -> tuple[list[str], dict[str, int], dict[str, int], list[str]]:
    """Return (timestamps, offset_index, ts_to_idx, header), rebuilding if stale."""
    mtime = os.path.getmtime(path)
    cached = _cache.get(path)
    if cached and cached[0] == mtime:
        _, ts, oi, t2i, hdr = cached
        return ts, oi, t2i, hdr

    timestamps, offset_index, header = _build(path)
    ts_to_idx = {ts: i for i, ts in enumerate(timestamps)}
    _cache[path] = (mtime, timestamps, offset_index, ts_to_idx, header)
    return timestamps, offset_index, ts_to_idx, header


def fetch_frame(
    path: str,
    offset_index: dict[str, int],
    ts_to_idx: dict[str, int],
    timestamps: list[str],
    header: list[str],
    ts_key: str,
) -> Optional[dict]:
    """Parse and return the frame for a single timestamp key."""
    if ts_key not in offset_index:
        return None

    ts_idx = ts_to_idx[ts_key]
    start = offset_index[ts_key]
    end = offset_index[timestamps[ts_idx + 1]] if ts_idx + 1 < len(timestamps) else None

    rows = []
    with open(path, "rb") as f:
        f.seek(start)
        while True:
            if end is not None and f.tell() >= end:
                break
            line = f.readline()
            if not line:
                break
            try:
                decoded = line.decode("utf-8", errors="replace").strip()
                if not decoded:
                    continue
                parts = decoded.split(",")
                if len(parts) != len(header):
                    continue
                raw = dict(zip(header, parts))
                row = parse_row(raw)
                if f"{row['timestamp']:.6g}" != ts_key:
                    break
                rows.append(row)
            except (ValueError, KeyError):
                continue

    return rows_to_frame(rows) if rows else None
