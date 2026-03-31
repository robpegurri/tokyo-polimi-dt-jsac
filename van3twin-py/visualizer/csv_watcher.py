import asyncio
import os
from typing import Any

from data_parser import parse_lines, rows_to_frame


class CsvWatcher:
    """Polls a CSV file for new rows using byte-offset tracking.

    Buffers rows belonging to an incomplete (still-being-written) timestamp
    across poll boundaries, emitting only complete frames.
    """

    def __init__(self, path: str):
        self.path = path
        self.byte_offset: int = 0
        self.header: list[str] | None = None
        self._pending_rows: list[dict] = []  # rows of the last seen, possibly incomplete timestamp

    def reset(self) -> None:
        self.byte_offset = 0
        self.header = None
        self._pending_rows = []

    async def poll(self, interval_ms: int = 500) -> list[dict[str, Any]]:
        """Return a list of complete frame dicts ready to send.

        Each frame dict: {"timestamp": float, "nodes": {...}, "links": [...]}
        """
        await asyncio.sleep(interval_ms / 1000)

        if not os.path.exists(self.path):
            return []

        try:
            with open(self.path, "rb") as f:
                f.seek(self.byte_offset)
                chunk = f.read()
                self.byte_offset = f.tell()
        except OSError:
            return []

        if not chunk:
            return []

        text = chunk.decode("utf-8", errors="replace")
        lines = text.splitlines()

        new_rows, self.header = parse_lines(lines, self.header)

        if not new_rows:
            return []

        all_rows = self._pending_rows + new_rows

        # Group by timestamp
        buckets: dict[str, list[dict]] = {}
        order: list[str] = []
        for r in all_rows:
            k = f"{r['timestamp']:.6g}"
            if k not in buckets:
                buckets[k] = []
                order.append(k)
            buckets[k].append(r)

        # All timestamps except the last one are considered complete
        complete_keys = order[:-1]
        last_key = order[-1]

        frames = []
        for k in complete_keys:
            frame = rows_to_frame(buckets[k])
            frame["timestamp"] = float(k)
            frames.append(frame)

        # Keep last timestamp pending (may receive more rows in next poll)
        self._pending_rows = buckets[last_key]

        return frames

    def flush_pending(self) -> list[dict[str, Any]]:
        """Flush any remaining buffered rows as a final frame."""
        if not self._pending_rows:
            return []
        frame = rows_to_frame(self._pending_rows)
        ts = self._pending_rows[0]["timestamp"]
        frame["timestamp"] = ts
        self._pending_rows = []
        return [frame]
