"""
Visualizer server manager — start/stop the FastAPI server in background thread.
"""

import socket
import sys
import threading
import time
from pathlib import Path

_SERVER_THREAD = None


def is_port_open(host="127.0.0.1", port=8000, timeout=0.3):
    """Check if a port is open and listening."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        return sock.connect_ex((host, port)) == 0


def start_server(host="0.0.0.0", port=8000):
    """
    Start the visualizer server in a background daemon thread.
    Safe to call multiple times; reuses existing server if already running.
    
    Args:
        host: Server host (default: 0.0.0.0)
        port: Server port (default: 8000)
    """
    global _SERVER_THREAD
    
    # Case 1: Port already in use (server running)
    if is_port_open("127.0.0.1", port):
        print(f"✓ Visualizer already running on http://localhost:{port}")
        return
    
    # Case 2: Thread already active
    if _SERVER_THREAD is not None and _SERVER_THREAD.is_alive():
        print("✓ Visualizer thread already active")
        return
    
    # Case 3: Start the server
    try:
        import uvicorn
        from visualizer.server import app
        
        def run_server():
            """Run uvicorn server in background thread."""
            uvicorn.run(
                app,
                host=host,
                port=port,
                log_level="warning",
            )
        
        _SERVER_THREAD = threading.Thread(target=run_server, daemon=True)
        _SERVER_THREAD.start()
        
        # Wait for server to bind
        time.sleep(1.5)
        if is_port_open("127.0.0.1", port):
            print(f"✓ Visualizer started at http://localhost:{port}")
        else:
            print(f"⚠ Visualizer start requested, but port {port} is not open yet.")
    
    except Exception as e:
        print(f"⚠ Failed to start visualizer: {e}")


def stop_server():
    """
    Stop the visualizer server (if running).
    Note: In a Jupyter daemon thread, forceful termination is limited.
    Consider for future enhancement if needed.
    """
    global _SERVER_THREAD
    
    if _SERVER_THREAD is None or not _SERVER_THREAD.is_alive():
        print("✓ Visualizer is not running")
        return
    
    print("⚠ Stopping daemon threads from Jupyter is not straightforward.")
    print("   The visualizer thread will stop when the kernel is shut down.")
