import csv
import io
from typing import Any

HEADER = [
    "timestamp", "tx_id", "rx_id", "is_los",
    "rssi_dbm", "sinr_eff_db", "mcs_index", "modulation",
    "bler", "throughput_kbps",
    "tx_x", "tx_y", "rx_x", "rx_y",
]


def parse_row(row: dict) -> dict:
    return {
        "timestamp": float(row["timestamp"]),
        "tx_id": row["tx_id"],
        "rx_id": row["rx_id"],
        "is_los": int(row["is_los"]),
        "rssi_dbm": float(row["rssi_dbm"]),
        "sinr_eff_db": float(row["sinr_eff_db"]),
        "mcs_index": int(row["mcs_index"]),
        "modulation": row["modulation"],
        "bler": float(row["bler"]),
        "throughput_kbps": float(row["throughput_kbps"]),
        "tx_x": float(row["tx_x"]),
        "tx_y": float(row["tx_y"]),
        "rx_x": float(row["rx_x"]),
        "rx_y": float(row["rx_y"]),
    }


def node_type(node_id: str) -> str:
    return "rsu" if node_id.startswith("rsu") else "car"


def rows_to_frame(rows: list[dict]) -> dict[str, Any]:
    """Convert a list of parsed rows (same timestamp) into a frame dict."""
    nodes: dict[str, dict] = {}
    links = []
    for r in rows:
        nodes[r["tx_id"]] = {"x": r["tx_x"], "y": r["tx_y"], "type": node_type(r["tx_id"])}
        nodes[r["rx_id"]] = {"x": r["rx_x"], "y": r["rx_y"], "type": node_type(r["rx_id"])}
        links.append({
            "tx": r["tx_id"],
            "rx": r["rx_id"],
            "is_los": r["is_los"],
            "rssi_dbm": r["rssi_dbm"],
            "sinr_eff_db": r["sinr_eff_db"],
            "mcs_index": r["mcs_index"],
            "modulation": r["modulation"],
            "bler": r["bler"],
            "throughput_kbps": r["throughput_kbps"],
        })
    return {"nodes": nodes, "links": links}


def stream_csv_frames(path: str):
    """
    Generator: yields (ts_key, frame_dict) for each timestamp group, then
    ("__done__", {"count": N}).  Assumes the CSV is sorted by timestamp.
    """
    current_ts: str | None = None
    current_rows: list[dict] = []
    total = 0

    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for raw in reader:
            try:
                row = parse_row(raw)
            except (ValueError, KeyError):
                continue
            ts_key = f"{row['timestamp']:.6g}"
            if ts_key != current_ts:
                if current_ts is not None:
                    total += 1
                    yield current_ts, rows_to_frame(current_rows)
                current_ts = ts_key
                current_rows = [row]
            else:
                current_rows.append(row)

    if current_ts and current_rows:
        total += 1
        yield current_ts, rows_to_frame(current_rows)
    yield "__done__", {"count": total}


def parse_csv_file(path: str) -> dict[str, Any]:
    """Parse an entire CSV file and return {timestamps: [...], frames: {...}}."""
    buckets: dict[str, list[dict]] = {}
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for raw in reader:
            try:
                row = parse_row(raw)
            except (ValueError, KeyError):
                continue
            ts_key = f"{row['timestamp']:.6g}"
            buckets.setdefault(ts_key, []).append(row)

    timestamps = sorted(buckets.keys(), key=float)
    frames = {ts: rows_to_frame(buckets[ts]) for ts in timestamps}
    return {"timestamps": timestamps, "frames": frames}


def parse_lines(lines: list[str], header: list[str] | None) -> tuple[list[dict], list[str] | None]:
    """Parse raw text lines (no header included). Returns (parsed_rows, detected_header).

    If header is None, tries to detect it from the first line.
    """
    if not lines:
        return [], header

    rows = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        # Detect header line (non-numeric first field)
        try:
            float(line.split(",")[0])
        except ValueError:
            if header is None:
                header = [c.strip() for c in line.split(",")]
            continue

        if header is None:
            header = HEADER  # fall back to known schema

        parts = line.split(",")
        if len(parts) != len(header):
            continue
        raw = dict(zip(header, parts))
        try:
            rows.append(parse_row(raw))
        except (ValueError, KeyError):
            continue

    return rows, header
