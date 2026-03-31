import asyncio
import glob as glob_module
import json
import os
import sys
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

# Allow imports from this directory when run as __main__
sys.path.insert(0, os.path.dirname(__file__))

from csv_watcher import CsvWatcher  # noqa: E402
from data_parser import parse_csv_file, stream_csv_frames  # noqa: E402
from file_index import fetch_frame as _fetch_frame, get_index  # noqa: E402
from settings import AppSettings, load_settings, save_settings  # noqa: E402

BASE_DIR = Path(__file__).parent
STATIC_DIR = BASE_DIR / "static"

# Working directory for CSV resolution (project root, one level up)
PROJECT_DIR = BASE_DIR.parent

# Graph generation (import after PROJECT_DIR is defined)
sys.path.insert(0, str(PROJECT_DIR))
from topology.graph_generator import generate_graphs, create_rssi_filter, create_sinr_filter, create_throughput_filter, create_composite_filter  # noqa: E402

current_settings: AppSettings = load_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global current_settings
    current_settings = load_settings()
    yield


app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def resolve_csv_path(path: str) -> str:
    """Resolve a CSV path: absolute or relative to project dir."""
    if os.path.isabs(path):
        return path
    # Try relative to project dir first, then cwd
    candidate = os.path.join(PROJECT_DIR, path)
    if os.path.exists(candidate):
        return candidate
    return os.path.join(os.getcwd(), path)


@app.get("/")
async def index():
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.get("/api/settings")
async def get_settings():
    return current_settings.model_dump()


@app.post("/api/settings")
async def post_settings(body: AppSettings):
    global current_settings
    current_settings = body
    save_settings(current_settings)
    return current_settings.model_dump()


@app.get("/api/file/list")
async def list_files():
    """List CSV files in the project directory."""
    pattern = str(PROJECT_DIR / "**" / "*.csv")
    files = glob_module.glob(pattern, recursive=True)
    # Return relative paths from project dir
    rel = []
    for f in sorted(files):
        try:
            rel.append(os.path.relpath(f, PROJECT_DIR))
        except ValueError:
            rel.append(f)
    return {"files": rel}


@app.get("/api/file/load")
async def load_file(path: str = "simulation_dataset.csv"):
    resolved = resolve_csv_path(path)
    if not os.path.exists(resolved):
        return JSONResponse(status_code=404, content={"error": f"File not found: {path}"})
    try:
        data = parse_csv_file(resolved)
        return data
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/file/open")
async def open_file(path: str = "simulation_dataset.csv"):
    """
    Build (or return cached) byte-offset index.  Returns the timestamp list
    immediately so the UI can become interactive; frame data is fetched later
    via /api/file/frame.
    """
    resolved = resolve_csv_path(path)
    if not os.path.exists(resolved):
        return JSONResponse(status_code=404, content={"error": f"File not found: {path}"})
    try:
        timestamps, _, _, _ = await asyncio.to_thread(get_index, resolved)
        return {"timestamps": timestamps, "frame_count": len(timestamps)}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/file/frame")
async def get_frame(path: str = "simulation_dataset.csv", ts: str = ""):
    """Return a single frame by timestamp key using the byte-offset index."""
    resolved = resolve_csv_path(path)
    if not os.path.exists(resolved):
        return JSONResponse(status_code=404, content={"error": "File not found"})
    try:
        timestamps, oi, t2i, hdr = await asyncio.to_thread(get_index, resolved)
        frame = await asyncio.to_thread(_fetch_frame, resolved, oi, t2i, timestamps, hdr, ts)
        if frame is None:
            return JSONResponse(status_code=404, content={"error": f"Timestamp '{ts}' not found"})
        return frame
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/file/stream")
async def stream_file(path: str = "simulation_dataset.csv"):
    """Stream CSV frames as NDJSON so the browser can render while loading."""
    resolved = resolve_csv_path(path)
    if not os.path.exists(resolved):
        return JSONResponse(status_code=404, content={"error": f"File not found: {path}"})

    loop = asyncio.get_event_loop()
    queue: asyncio.Queue = asyncio.Queue(maxsize=200)
    SENTINEL = object()

    def _producer():
        try:
            for ts_key, data in stream_csv_frames(resolved):
                if ts_key == "__done__":
                    line = json.dumps({"type": "done", "total": data["count"]}) + "\n"
                else:
                    line = json.dumps({"type": "frame", "timestamp": ts_key, **data}) + "\n"
                asyncio.run_coroutine_threadsafe(queue.put(line), loop).result()
        except Exception as exc:
            err = json.dumps({"type": "error", "message": str(exc)}) + "\n"
            asyncio.run_coroutine_threadsafe(queue.put(err), loop).result()
        finally:
            asyncio.run_coroutine_threadsafe(queue.put(SENTINEL), loop).result()

    threading.Thread(target=_producer, daemon=True).start()

    async def _generate():
        while True:
            item = await queue.get()
            if item is SENTINEL:
                break
            yield item

    return StreamingResponse(_generate(), media_type="application/x-ndjson")


# ============================================================================
# Graph Generation Endpoint
# ============================================================================

def networkx_to_json(G):
    """Convert NetworkX graph to JSON-serializable format."""
    import networkx as nx

    nodes = [
        {
            "id": str(node),
            "type": G.nodes[node].get("type", "unknown"),
            "x": float(G.nodes[node].get("x", 0)),
            "y": float(G.nodes[node].get("y", 0)),
        }
        for node in G.nodes()
    ]

    edges = [
        {
            "source": str(u),
            "target": str(v),
            "rssi_dbm": float(G[u][v].get("rssi_dbm", 0)),
            "sinr_eff_db": float(G[u][v].get("sinr_eff_db", 0)),
            "throughput_kbps": float(G[u][v].get("throughput_kbps", 0)),
            "bler": float(G[u][v].get("bler", 0)),
            "modulation": str(G[u][v].get("modulation", "UNKNOWN")),
            "is_los": int(G[u][v].get("is_los", 0)),
        }
        for u, v in G.edges()
    ]

    return {"nodes": nodes, "edges": edges}


@app.get("/api/graph/generate")
async def get_network_graph(
    rsu_id: str,
    min_x: float,
    max_x: float,
    min_y: float,
    max_y: float,
    max_hops: int = 3,
    rssi_threshold: float = -100,
    sinr_threshold: float = 0,
    throughput_threshold: float = 0,
    timestamp: float = None,
    path: str = None,
):
    """
    Generate uplink and downlink graphs for visualization.

    Returns:
        {
            "timestamp": float,
            "rsu_id": str,
            "uplink": {"nodes": [...], "edges": [...]},
            "downlink": {"nodes": [...], "edges": [...]},
            "both": {"nodes": [...], "edges": [...]},
            "metadata": {...}
        }
    """
    try:
        if not path:
            return JSONResponse(
                status_code=400,
                content={"error": "Missing 'path' parameter"}
            )

        if not rsu_id:
            return JSONResponse(
                status_code=400,
                content={"error": "Missing 'rsu_id' parameter"}
            )

        resolved_path = resolve_csv_path(path)
        if not os.path.exists(resolved_path):
            return JSONResponse(
                status_code=404,
                content={"error": f"File not found: {resolved_path}"}
            )

        # Load frame data
        import pandas as pd
        df = pd.read_csv(resolved_path)

        if timestamp is None and len(df) > 0:
            timestamp = df["timestamp"].iloc[0]

        if timestamp is None:
            return JSONResponse(
                status_code=400,
                content={"error": "No timestamp data available"}
            )

        # Get links at this timestamp
        import numpy as np
        ts_data = df[np.isclose(df["timestamp"], timestamp, rtol=1e-6)]

        if ts_data.empty:
            return JSONResponse(
                status_code=404,
                content={"error": f"No data found for timestamp {timestamp}"}
            )

        # Convert to list of dicts for links_snapshot
        links_snapshot = ts_data.to_dict("records")

        # Create composite filter from thresholds
        filters = []
        if rssi_threshold > -150:
            filters.append(create_rssi_filter(rssi_threshold))
        if sinr_threshold > -50:
            filters.append(create_sinr_filter(sinr_threshold))
        if throughput_threshold > 0:
            filters.append(create_throughput_filter(throughput_threshold * 1000))  # Convert Mbps to kbps

        link_reachability_fn = None
        if filters:
            link_reachability_fn = create_composite_filter(*filters)

        # Generate graphs
        bbox = (min_x, max_x, min_y, max_y)
        uplink_graph, downlink_graph, metadata = generate_graphs(
            rsu_id=rsu_id,
            bbox=bbox,
            max_hops=max_hops,
            link_reachability_fn=link_reachability_fn,
            links_snapshot=links_snapshot,
        )

        # Convert to JSON
        uplink_json = networkx_to_json(uplink_graph)
        downlink_json = networkx_to_json(downlink_graph)

        # Create combined graph (both uplink and downlink)
        import networkx as nx
        both_graph = nx.compose(uplink_graph, downlink_graph)
        both_json = networkx_to_json(both_graph)

        return {
            "timestamp": float(timestamp),
            "rsu_id": rsu_id,
            "uplink": uplink_json,
            "downlink": downlink_json,
            "both": both_json,
            "metadata": {
                "uplink_nodes": metadata["uplink_nodes"],
                "uplink_edges": metadata["uplink_edges"],
                "downlink_nodes": metadata["downlink_nodes"],
                "downlink_edges": metadata["downlink_edges"],
                "nodes_within_hops": metadata["nodes_within_hops"],
                "links_after_quality_filter": metadata["links_after_quality_filter"],
                "total_links": metadata["total_links_in_csv"],
            }
        }

    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )


@app.websocket("/ws/live")
async def websocket_live(ws: WebSocket, path: str = "simulation_dataset.csv"):
    await ws.accept()

    resolved = resolve_csv_path(path)
    watcher = CsvWatcher(resolved)

    # Send initial confirmation
    await ws.send_text(json.dumps({"type": "connected", "path": resolved}))

    ping_counter = 0
    try:
        while True:
            frames = await watcher.poll(current_settings.watch_interval_ms)
            for frame in frames:
                msg = {"type": "frame", **frame}
                await ws.send_text(json.dumps(msg))

            ping_counter += 1
            if ping_counter >= 30:  # ~15 s keepalive
                await ws.send_text(json.dumps({"type": "ping"}))
                ping_counter = 0

            # Handle client messages without blocking
            try:
                data = await asyncio.wait_for(ws.receive_text(), timeout=0.01)
                msg = json.loads(data)
                if msg.get("type") == "stop":
                    break
            except asyncio.TimeoutError:
                pass
            except Exception:
                pass

    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await ws.send_text(json.dumps({"type": "error", "message": str(e)}))
        except Exception:
            pass
    finally:
        # Flush any pending rows on disconnect
        pending = watcher.flush_pending()
        for frame in pending:
            try:
                msg = {"type": "frame", **frame}
                await ws.send_text(json.dumps(msg))
            except Exception:
                pass


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)
