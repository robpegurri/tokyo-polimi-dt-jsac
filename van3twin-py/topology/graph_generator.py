"""
graph_generator.py

Generate NetworkX graphs for vehicle-RSU network analysis from timestamped CSV link data.

Key features:
- Load CSV link data grouped by timestamp
- Filter links by quality metrics (RSSI, SINR, throughput, etc.)
- Filter nodes by geographic area (bounding box)
- Construct directed graphs with multi-hop reachability constraints
- Separate uplink (vehicles→RSU) and downlink (RSU→vehicles) subgraphs
- Store all link metrics as edge attributes for downstream cost computation

"""

from dataclasses import dataclass
from typing import Callable, Optional, Tuple, Dict, Set, List, Any
import networkx as nx
import pandas as pd
import numpy as np


# ============================================================================
# Data Structures
# ============================================================================

@dataclass
class LinkRecord:
    """Parsed representation of a single directional link from CSV."""
    timestamp: float
    tx_id: str
    rx_id: str
    is_los: int
    rssi_dbm: float
    sinr_eff_db: float
    mcs_index: int
    modulation: str
    bler: float
    throughput_kbps: float
    tx_x: float
    tx_y: float
    rx_x: float
    rx_y: float

    @classmethod
    def from_dict(cls, row: dict) -> "LinkRecord":
        """Create LinkRecord from a parsed CSV row dict."""
        return cls(
            timestamp=float(row["timestamp"]),
            tx_id=row["tx_id"],
            rx_id=row["rx_id"],
            is_los=int(row["is_los"]),
            rssi_dbm=float(row["rssi_dbm"]),
            sinr_eff_db=float(row["sinr_eff_db"]),
            mcs_index=int(row["mcs_index"]),
            modulation=row["modulation"],
            bler=float(row["bler"]),
            throughput_kbps=float(row["throughput_kbps"]),
            tx_x=float(row["tx_x"]),
            tx_y=float(row["tx_y"]),
            rx_x=float(row["rx_x"]),
            rx_y=float(row["rx_y"]),
        )

    def to_edge_attributes(self) -> dict:
        """Convert to edge attribute dict (excludes node coordinates)."""
        return {
            "is_los": self.is_los,
            "rssi_dbm": self.rssi_dbm,
            "sinr_eff_db": self.sinr_eff_db,
            "mcs_index": self.mcs_index,
            "modulation": self.modulation,
            "bler": self.bler,
            "throughput_kbps": self.throughput_kbps,
        }


# ============================================================================
# Utility Functions: Geometric & Node Classification
# ============================================================================

def is_in_bbox(x: float, y: float, bbox: Optional[Tuple[float, float, float, float]]) -> bool:
    """
    Check if a point (x, y) is within a bounding box.
    
    Args:
        x, y: coordinates
        bbox: (min_x, max_x, min_y, max_y) or None (no filter)
    
    Returns:
        True if point is inside bbox, or bbox is None; False otherwise.
    """
    if bbox is None:
        return True
    min_x, max_x, min_y, max_y = bbox
    return min_x <= x <= max_x and min_y <= y <= max_y


def node_type(node_id: str) -> str:
    """Classify node as 'rsu' or 'car' based on ID prefix."""
    return "rsu" if node_id.startswith("rsu") else "car"


def extract_node_positions(links: List[LinkRecord]) -> Dict[str, Dict[str, Any]]:
    """
    Extract unique nodes and their latest positions from a list of links.
    
    Returns:
        {node_id: {"type": "rsu"|"car", "x": float, "y": float}}
    """
    nodes = {}
    for link in links:
        if link.tx_id not in nodes:
            nodes[link.tx_id] = {
                "type": node_type(link.tx_id),
                "x": link.tx_x,
                "y": link.tx_y,
            }
        if link.rx_id not in nodes:
            nodes[link.rx_id] = {
                "type": node_type(link.rx_id),
                "x": link.rx_x,
                "y": link.rx_y,
            }
    return nodes


# ============================================================================
# Utility Functions: Link Quality Filtering
# ============================================================================

def default_link_reachability(link: LinkRecord) -> bool:
    """
    Default link reachability predicate: RSSI > -75 dB.
    
    This is a starting point; users may pass custom predicates to generate_graphs().
    """
    return link.rssi_dbm > -75.0


def create_rssi_filter(threshold: float) -> Callable[[LinkRecord], bool]:
    """Create a link filter based on RSSI threshold."""
    return lambda link: link.rssi_dbm > threshold


def create_sinr_filter(threshold: float) -> Callable[[LinkRecord], bool]:
    """Create a link filter based on SINR threshold."""
    return lambda link: link.sinr_eff_db > threshold


def create_throughput_filter(threshold: float) -> Callable[[LinkRecord], bool]:
    """Create a link filter based on throughput threshold (in kbps)."""
    return lambda link: link.throughput_kbps > threshold


def create_composite_filter(*predicates: Callable[[LinkRecord], bool]) -> Callable[[LinkRecord], bool]:
    """Create a composite filter: all predicates must be true."""
    return lambda link: all(pred(link) for pred in predicates)


# ============================================================================
# Core Graph Construction Functions
# ============================================================================

def filter_links_by_quality(
    links: List[LinkRecord],
    link_reachability_fn: Optional[Callable[[LinkRecord], bool]] = None,
) -> Tuple[List[LinkRecord], int]:
    """
    Filter links by quality metrics.
    
    Args:
        links: list of LinkRecord objects
        link_reachability_fn: callable(LinkRecord) -> bool. If None, use default.
    
    Returns:
        (filtered_links, num_filtered_out)
    """
    if link_reachability_fn is None:
        link_reachability_fn = default_link_reachability
    
    filtered = [link for link in links if link_reachability_fn(link)]
    num_filtered_out = len(links) - len(filtered)
    
    return filtered, num_filtered_out


def filter_nodes_by_area(
    nodes: Dict[str, Dict[str, Any]],
    bbox: Optional[Tuple[float, float, float, float]],
    rsu_id: str,
) -> Set[str]:
    """
    Filter nodes to those within a bounding box and reachable from CSV links.
    RSU itself is always included.
    
    Args:
        nodes: {node_id: {"type": "...", "x": float, "y": float}}
        bbox: (min_x, max_x, min_y, max_y) or None
        rsu_id: ID of the destination RSU (always included)
    
    Returns:
        Set of node IDs that pass the geographic filter
    """
    filtered_nodes = {rsu_id}  # Always include the RSU
    
    for node_id, node_info in nodes.items():
        if node_id == rsu_id:
            continue  # Already added
        x, y = node_info["x"], node_info["y"]
        if is_in_bbox(x, y, bbox):
            filtered_nodes.add(node_id)
    
    return filtered_nodes


def build_directed_graph(
    links: List[LinkRecord],
    nodes: Dict[str, Dict[str, Any]],
    filtered_node_ids: Set[str],
) -> nx.DiGraph:
    """
    Build a directed graph with nodes and edges from filtered links.
    
    Args:
        links: list of filtered LinkRecord objects
        nodes: {node_id: {"type": "...", "x": float, "y": float}}
        filtered_node_ids: set of node IDs to include in graph
    
    Returns:
        DiGraph with nodes (with "type", "x", "y" attributes) and edges
        (with link metrics as attributes)
    """
    G = nx.DiGraph()
    
    # Add nodes
    for node_id in filtered_node_ids:
        if node_id in nodes:
            node_info = nodes[node_id]
            G.add_node(node_id, **node_info)
    
    # Add edges
    for link in links:
        if link.tx_id in filtered_node_ids and link.rx_id in filtered_node_ids:
            # Avoid duplicate edges (last one wins)
            G.add_edge(
                link.tx_id,
                link.rx_id,
                **link.to_edge_attributes()
            )
    
    return G


def filter_by_multihop_reachability(
    G: nx.DiGraph,
    rsu_id: str,
    max_hops: int,
) -> nx.DiGraph:
    """
    Filter graph to include only nodes reachable from RSU within max_hops.
    
    Uses BFS from RSU to compute shortest-path distances. Nodes beyond
    max_hops are removed, along with their incident edges.
    
    Args:
        G: directed graph
        rsu_id: ID of source RSU
        max_hops: maximum hop distance
    
    Returns:
        Subgraph with only reachable nodes (and edges between them)
    """
    if rsu_id not in G:
        return G.copy()  # RSU not in graph
    
    # Compute shortest path distances from RSU
    try:
        distances = nx.single_source_shortest_path_length(G, rsu_id)
    except nx.NetworkXError:
        distances = {rsu_id: 0}
    
    # Keep nodes within max_hops
    reachable_nodes = {
        node for node, dist in distances.items()
        if dist <= max_hops
    }
    
    # Subgraph induces edges between reachable nodes
    H = G.subgraph(reachable_nodes).copy()
    return H


def extract_uplink_subgraph(G: nx.DiGraph, rsu_id: str) -> nx.DiGraph:
    """
    Extract uplink subgraph: edges where tx_id is a car and rx_id is the RSU.
    
    More generally: edges pointing toward the RSU.
    """
    H = nx.DiGraph()
    
    # Copy all nodes
    for node, attrs in G.nodes(data=True):
        H.add_node(node, **attrs)
    
    # Keep only edges where rx_id is RSU or node_type(tx) is 'car'
    # (More flexible: keep edges pointing toward RSU in multi-hop scenario)
    for u, v, attrs in G.edges(data=True):
        if v == rsu_id or node_type(u) == "car":
            H.add_edge(u, v, **attrs)
    
    # Remove isolated nodes (except RSU)
    isolated = [n for n in H.nodes() if H.degree(n) == 0 and n != rsu_id]
    H.remove_nodes_from(isolated)
    
    return H


def extract_downlink_subgraph(G: nx.DiGraph, rsu_id: str) -> nx.DiGraph:
    """
    Extract downlink subgraph: edges where tx_id is the RSU and rx_id is a car.
    
    More generally: edges originating from the RSU.
    """
    H = nx.DiGraph()
    
    # Copy all nodes
    for node, attrs in G.nodes(data=True):
        H.add_node(node, **attrs)
    
    # Keep only edges where tx_id is RSU or node_type(rx) is 'car'
    # (More flexible: keep edges originating from RSU in multi-hop scenario)
    for u, v, attrs in G.edges(data=True):
        if u == rsu_id or node_type(v) == "car":
            H.add_edge(u, v, **attrs)
    
    # Remove isolated nodes (except RSU)
    isolated = [n for n in H.nodes() if H.degree(n) == 0 and n != rsu_id]
    H.remove_nodes_from(isolated)
    
    return H


# ============================================================================
# CSV Loading
# ============================================================================

def load_csv_links(csv_path: str, timestamp: Optional[float] = None) -> List[LinkRecord]:
    """
    Load links from CSV file, optionally filtered to a specific timestamp.
    
    Args:
        csv_path: path to CSV file
        timestamp: if provided, return only links with this timestamp
    
    Returns:
        list of LinkRecord objects
    """
    df = pd.read_csv(csv_path)
    
    if timestamp is not None:
        # Allow small floating-point tolerance
        df = df[np.isclose(df["timestamp"], timestamp, rtol=1e-6)]
    
    links = [LinkRecord.from_dict(row) for _, row in df.iterrows()]
    return links


# ============================================================================
# Main API
# ============================================================================

def generate_graphs(
    rsu_id: str,
    bbox: Optional[Tuple[float, float, float, float]] = None,
    max_hops: int = 3,
    link_reachability_fn: Optional[Callable[[LinkRecord], bool]] = None,
    csv_path: Optional[str] = None,
    timestamp: Optional[float] = None,
    links_snapshot: Optional[List[Any]] = None,
) -> Tuple[nx.DiGraph, nx.DiGraph, Dict[str, Any]]:
    """
    Generate uplink and downlink graphs for a given RSU and area.
    
    This is the main entry point. It orchestrates all filtering and graph
    construction steps:
    1. Load/receive link data from CSV or live snapshot
    2. Filter by link quality (RSSI, SINR, etc.)
    3. Filter nodes by geographic area (bbox)
    4. Build directed graph with multi-hop reachability
    5. Extract uplink and downlink subgraphs
    
    Args:
        rsu_id: ID of the destination RSU (e.g., "rsu_1")
        bbox: (min_x, max_x, min_y, max_y) geographic filter, or None for full map
        max_hops: maximum hop distance from RSU; only include nodes ≤ max_hops away
        link_reachability_fn: callable(LinkRecord) -> bool to filter usable links
                             If None, uses default (RSSI > -75 dB)
        csv_path: path to CSV file with link data (required if links_snapshot is None)
        timestamp: specific timestamp to process from CSV (used only if links_snapshot is None)
        links_snapshot: list of LinkRecord objects or dicts with link data for immediate processing.
                       If provided, csv_path and timestamp are ignored (for "live" usage).
                       Each dict must have keys: timestamp, tx_id, rx_id, is_los, rssi_dbm,
                       sinr_eff_db, mcs_index, modulation, bler, throughput_kbps, tx_x, tx_y, rx_x, rx_y
    
    Returns:
        (uplink_graph, downlink_graph, metadata)
        where metadata is a dict with:
        {
            "timestamp": float or None,
            "rsu_id": str,
            "bbox": optional tuple,
            "max_hops": int,
            "total_links_in_csv": int,
            "links_after_quality_filter": int,
            "links_filtered_out": int,
            "nodes_in_area": int,
            "nodes_within_hops": int,
            "uplink_nodes": int,
            "uplink_edges": int,
            "downlink_nodes": int,
            "downlink_edges": int,
        }
    
    Raises:
        ValueError: if neither (csv_path + timestamp) nor links_snapshot is provided
    
    Examples:
        # From CSV file
        ul, dl, meta = generate_graphs(
            csv_path="data.csv",
            timestamp=0.5,
            rsu_id="rsu_1",
        )
        
        # From live data snapshot
        links = [
            {"timestamp": 0.5, "tx_id": "car_1", "rx_id": "rsu_1", ...},
            {"timestamp": 0.5, "tx_id": "car_2", "rx_id": "rsu_1", ...},
        ]
        ul, dl, meta = generate_graphs(
            rsu_id="rsu_1",
            links_snapshot=links,
        )
    """
    # Step 1: Load or receive links
    if links_snapshot is not None:
        # Live mode: convert dicts to LinkRecord objects if needed
        all_links = []
        for item in links_snapshot:
            if isinstance(item, LinkRecord):
                all_links.append(item)
            elif isinstance(item, dict):
                all_links.append(LinkRecord.from_dict(item))
            else:
                raise TypeError(f"Each item in links_snapshot must be LinkRecord or dict, got {type(item)}")
    elif csv_path is not None and timestamp is not None:
        # CSV mode: load from file
        all_links = load_csv_links(csv_path, timestamp=timestamp)
    else:
        raise ValueError(
            "Must provide either (csv_path + timestamp) OR links_snapshot. "
            "CSV mode: generate_graphs(csv_path='...', timestamp=0.5, rsu_id='...')\n"
            "Live mode: generate_graphs(links_snapshot=[...], rsu_id='...')"
        )
    total_links = len(all_links)
    
    # Step 2: Filter by link quality
    filtered_links, links_filtered_out = filter_links_by_quality(
        all_links, link_reachability_fn
    )
    
    # Step 3: Extract all nodes from filtered links
    all_nodes = extract_node_positions(filtered_links)
    
    # Step 4: Filter nodes by area
    filtered_node_ids = filter_nodes_by_area(all_nodes, bbox, rsu_id)
    
    # Step 5: Build directed graph
    G = build_directed_graph(filtered_links, all_nodes, filtered_node_ids)
    
    # Step 6: Apply multi-hop reachability
    G = filter_by_multihop_reachability(G, rsu_id, max_hops)
    
    # Step 7: Extract uplink and downlink
    uplink_graph = extract_uplink_subgraph(G, rsu_id)
    downlink_graph = extract_downlink_subgraph(G, rsu_id)
    
    # Extract timestamp from links if not provided (for live mode)
    extracted_timestamp = timestamp
    if extracted_timestamp is None and all_links:
        extracted_timestamp = all_links[0].timestamp
    
    # Metadata
    metadata = {
        "timestamp": extracted_timestamp,
        "rsu_id": rsu_id,
        "bbox": bbox,
        "max_hops": max_hops,
        "total_links_in_csv": total_links,
        "links_after_quality_filter": len(filtered_links),
        "links_filtered_out": links_filtered_out,
        "nodes_in_area": len(filtered_node_ids),
        "nodes_within_hops": G.number_of_nodes(),
        "uplink_nodes": uplink_graph.number_of_nodes(),
        "uplink_edges": uplink_graph.number_of_edges(),
        "downlink_nodes": downlink_graph.number_of_nodes(),
        "downlink_edges": downlink_graph.number_of_edges(),
    }
    
    return uplink_graph, downlink_graph, metadata


# ============================================================================
# Batch Processing
# ============================================================================

def generate_all_timestamps(
    csv_path: str,
    rsu_id: str,
    bbox: Optional[Tuple[float, float, float, float]] = None,
    max_hops: int = 3,
    link_reachability_fn: Optional[Callable[[LinkRecord], bool]] = None,
    output_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Generate graphs for all unique timestamps in the CSV.
    
    Optionally saves graphs to files (pickle or GraphML format).
    
    Args:
        csv_path: path to CSV file
        rsu_id: ID of the destination RSU
        bbox: geographic filter or None
        max_hops: multi-hop constraint
        link_reachability_fn: link quality predicate
        output_dir: if provided, save graphs to this directory
    
    Returns:
        aggregated statistics dict
    """
    import os
    
    df = pd.read_csv(csv_path)
    unique_timestamps = df["timestamp"].unique()
    
    results = []
    for ts in sorted(unique_timestamps):
        try:
            uplink, downlink, meta = generate_graphs(
                csv_path, ts, rsu_id,
                bbox=bbox, max_hops=max_hops,
                link_reachability_fn=link_reachability_fn
            )
            results.append(meta)
            
            if output_dir is not None:
                os.makedirs(output_dir, exist_ok=True)
                ts_str = f"{ts:.6g}".replace(".", "_")
                uplink_path = os.path.join(output_dir, f"uplink_{ts_str}.graphml")
                downlink_path = os.path.join(output_dir, f"downlink_{ts_str}.graphml")
                nx.write_graphml(uplink, uplink_path)
                nx.write_graphml(downlink, downlink_path)
        
        except Exception as e:
            print(f"Error processing timestamp {ts}: {e}")
            continue
    
    # Aggregate statistics
    if results:
        agg = {
            "timestamps_processed": len(results),
            "avg_uplink_nodes": np.mean([r["uplink_nodes"] for r in results]),
            "avg_uplink_edges": np.mean([r["uplink_edges"] for r in results]),
            "avg_downlink_nodes": np.mean([r["downlink_nodes"] for r in results]),
            "avg_downlink_edges": np.mean([r["downlink_edges"] for r in results]),
            "avg_links_filtered_out": np.mean([r["links_filtered_out"] for r in results]),
            "total_graphs": 2 * len(results),  # uplink + downlink per timestamp
        }
    else:
        agg = {
            "timestamps_processed": 0,
            "total_graphs": 0,
        }
    
    return agg


# ============================================================================
# Visualization Functions
# ============================================================================

def visualize_graph(
    G: nx.DiGraph,
    title: str = "Network Graph",
    figsize: tuple = (14, 10),
    rsu_color: str = "red",
    car_color: str = "lightblue",
    edge_color_attr: str = "rssi_dbm",
    edge_width_attr: str = None,
    show_labels: bool = True,
    show_edge_labels: bool = False,
    node_size: int = 800,
    font_size: int = 8,
    arrows: bool = True,
    arrowsize: int = 20,
    layout: str = "spring",
    seed: int = 42,
    save_path: str = None,
) -> tuple:
    """
    Visualize a NetworkX directed graph using matplotlib.
    
    Args:
        G: directed graph to visualize
        title: figure title
        figsize: (width, height) in inches
        rsu_color: node color for RSUs
        car_color: node color for cars
        edge_color_attr: edge attribute for coloring edges ("rssi_dbm", "throughput_kbps", etc.)
                        or None to use uniform gray
        edge_width_attr: edge attribute for line width (None = uniform 2.0)
        show_labels: whether to show node labels
        show_edge_labels: whether to show edge metrics as labels
        node_size: size of nodes
        font_size: size of node labels
        arrows: whether to show directional arrows
        arrowsize: size of arrow heads
        layout: layout algorithm ("spring", "circular", "kamada_kawai", "shell")
        seed: random seed for layout
        save_path: if provided, save figure to this path
    
    Returns:
        (fig, ax, pos) — matplotlib figure, axes, node positions dict
    """
    import matplotlib.pyplot as plt
    from matplotlib.colors import Normalize
    import matplotlib.cm as cm
    
    if len(G) == 0:
        print("Graph is empty; nothing to visualize")
        return None, None, {}
    
    # Create figure
    fig, ax = plt.subplots(figsize=figsize)
    
    # Choose layout algorithm
    if layout == "spring":
        pos = nx.spring_layout(G, k=2, iterations=50, seed=seed)
    elif layout == "circular":
        pos = nx.circular_layout(G)
    elif layout == "kamada_kawai":
        pos = nx.kamada_kawai_layout(G)
    elif layout == "shell":
        pos = nx.shell_layout(G)
    else:
        pos = nx.spring_layout(G, k=2, iterations=50, seed=seed)
    
    # Separate nodes by type
    rsu_nodes = [n for n in G.nodes() if G.nodes[n].get("type") == "rsu"]
    car_nodes = [n for n in G.nodes() if G.nodes[n].get("type") == "car"]
    
    # Draw RSUs
    nx.draw_networkx_nodes(
        G, pos, nodelist=rsu_nodes, node_color=rsu_color, node_size=node_size,
        label="RSU", ax=ax
    )
    
    # Draw cars
    nx.draw_networkx_nodes(
        G, pos, nodelist=car_nodes, node_color=car_color, node_size=node_size,
        label="Car", ax=ax
    )
    
    # Edge coloring based on attribute
    edge_colors = "gray"
    edge_widths = 2.0
    
    if edge_color_attr and len(G.edges()) > 0:
        # Get edge attribute values for coloring
        edge_values = [G[u][v].get(edge_color_attr, 0) for u, v in G.edges()]
        if edge_values and any(v != 0 for v in edge_values):
            # Normalize and color
            norm = Normalize(vmin=min(edge_values), vmax=max(edge_values))
            cmap = cm.get_cmap("RdYlGn" if edge_color_attr == "throughput_kbps" else "RdYlGn_r")
            edge_colors = [cmap(norm(val)) for val in edge_values]
    
    if edge_width_attr and len(G.edges()) > 0:
        # Get edge attribute values for width
        edge_widths = [
            0.5 + 4.0 * (G[u][v].get(edge_width_attr, 1.0) / max(
                [G[uu][vv].get(edge_width_attr, 1.0) for uu, vv in G.edges()], default=1.0
            ))
            for u, v in G.edges()
        ]
    
    # Draw edges
    nx.draw_networkx_edges(
        G, pos, edge_color=edge_colors, width=edge_widths,
        arrows=arrows, arrowsize=arrowsize, ax=ax, connectionstyle="arc3,rad=0.1"
    )
    
    # Draw labels
    if show_labels:
        nx.draw_networkx_labels(G, pos, font_size=font_size, ax=ax)
    
    # Draw edge labels (optional, can be cluttered)
    if show_edge_labels and len(G.edges()) < 30:  # Only if not too many edges
        edge_labels = {}
        for u, v, attrs in G.edges(data=True):
            if edge_color_attr and edge_color_attr in attrs:
                edge_labels[(u, v)] = f"{attrs[edge_color_attr]:.1f}"
        nx.draw_networkx_edge_labels(G, pos, edge_labels, font_size=6, ax=ax)
    
    # Title and legend
    ax.set_title(title, fontsize=14, fontweight="bold")
    ax.legend(scatterpoints=1, loc="upper left", fontsize=10)
    ax.axis("off")
    
    plt.tight_layout()
    
    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches="tight")
        print(f"✓ Figure saved to {save_path}")
    
    return fig, ax, pos


def visualize_comparison(
    G1: nx.DiGraph,
    G2: nx.DiGraph,
    title1: str = "Uplink Graph",
    title2: str = "Downlink Graph",
    figsize: tuple = (18, 8),
    rsu_color: str = "red",
    car_color: str = "lightblue",
    save_path: str = None,
) -> tuple:
    """
    Visualize two graphs side-by-side (e.g., uplink vs downlink).
    
    Args:
        G1, G2: graphs to compare
        title1, title2: titles for each subplot
        figsize: figure size
        rsu_color: RSU node color
        car_color: car node color
        save_path: if provided, save to this path
    
    Returns:
        (fig, (ax1, ax2), (pos1, pos2))
    """
    import matplotlib.pyplot as plt
    
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=figsize)
    
    # Use same seed for consistent layout positioning
    seed = 42
    
    for idx, (G, ax, title) in enumerate([
        (G1, ax1, title1),
        (G2, ax2, title2),
    ]):
        pos = nx.spring_layout(G, k=2, iterations=50, seed=seed)
        
        rsu_nodes = [n for n in G.nodes() if G.nodes[n].get("type") == "rsu"]
        car_nodes = [n for n in G.nodes() if G.nodes[n].get("type") == "car"]
        
        nx.draw_networkx_nodes(
            G, pos, nodelist=rsu_nodes, node_color=rsu_color, node_size=500, ax=ax
        )
        nx.draw_networkx_nodes(
            G, pos, nodelist=car_nodes, node_color=car_color, node_size=500, ax=ax
        )
        nx.draw_networkx_edges(
            G, pos, edge_color="gray", arrows=True, arrowsize=15, ax=ax,
            connectionstyle="arc3,rad=0.1"
        )
        nx.draw_networkx_labels(G, pos, font_size=7, ax=ax)
        
        ax.set_title(f"{title}\n({G.number_of_nodes()} nodes, {G.number_of_edges()} edges)",
                     fontsize=12, fontweight="bold")
        ax.axis("off")
    
    plt.tight_layout()
    
    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches="tight")
        print(f"✓ Comparison figure saved to {save_path}")
    
    return fig, (ax1, ax2), (nx.spring_layout(G1, seed=seed), nx.spring_layout(G2, seed=seed))


def visualize_interactive(
    G: nx.DiGraph,
    title: str = "Interactive Network Graph",
    edge_color_attr: str = "rssi_dbm",
    save_path: str = None,
) -> "plotly.graph_objs.Figure":
    """
    Create an interactive visualization using Plotly.
    
    Requires: pip install plotly
    
    Args:
        G: directed graph to visualize
        title: figure title
        edge_color_attr: attribute to use for edge coloring
        save_path: if provided, save to this HTML file
    
    Returns:
        plotly Figure
    """
    try:
        import plotly.graph_objects as go
    except ImportError:
        print("ERROR: plotly not installed. Install with: pip install plotly")
        return None
    
    if len(G) == 0:
        print("Graph is empty; nothing to visualize")
        return None
    
    # Use spring layout for positioning
    pos = nx.spring_layout(G, k=2, iterations=50, seed=42)
    
    # Extract edge information
    edge_x = []
    edge_y = []
    edge_colors = []
    edge_labels = []
    
    for u, v in G.edges():
        x0, y0 = pos[u]
        x1, y1 = pos[v]
        edge_x.append(x0)
        edge_x.append(x1)
        edge_x.append(None)
        edge_y.append(y0)
        edge_y.append(y1)
        edge_y.append(None)
        
        # Get edge color attribute
        color_val = G[u][v].get(edge_color_attr, 0)
        edge_colors.append(color_val)
        
        # Create hover text with edge attributes
        attrs = G[u][v]
        hover_text = f"{u} → {v}<br>"
        hover_text += f"RSSI: {attrs.get('rssi_dbm', 'N/A'):.1f} dB<br>"
        hover_text += f"SINR: {attrs.get('sinr_eff_db', 'N/A'):.1f} dB<br>"
        hover_text += f"Throughput: {attrs.get('throughput_kbps', 'N/A'):.0f} kbps<br>"
        hover_text += f"LoS: {'Yes' if attrs.get('is_los') else 'No'}"
        edge_labels.append(hover_text)
    
    edge_trace = go.Scatter(
        x=edge_x, y=edge_y,
        mode="lines",
        line=dict(width=2, color="gray"),
        hoverinfo="text",
        text=edge_labels,
        showlegend=False,
    )
    
    # Extract node information
    node_x = []
    node_y = []
    node_colors = []
    node_labels = []
    
    for node in G.nodes():
        x, y = pos[node]
        node_x.append(x)
        node_y.append(y)
        
        node_type = G.nodes[node].get("type", "unknown")
        node_colors.append("red" if node_type == "rsu" else "blue")
        
        # Create hover text with node attributes
        attrs = G.nodes[node]
        hover_text = f"<b>{node}</b><br>"
        hover_text += f"Type: {node_type}<br>"
        hover_text += f"Position: ({attrs.get('x', 'N/A'):.2f}, {attrs.get('y', 'N/A'):.2f})"
        node_labels.append(hover_text)
    
    node_trace = go.Scatter(
        x=node_x, y=node_y,
        mode="markers+text",
        text=[n for n in G.nodes()],
        textposition="top center",
        hoverinfo="text",
        hovertext=node_labels,
        marker=dict(
            size=15,
            color=node_colors,
            line=dict(width=2, color="white"),
        ),
        showlegend=False,
    )
    
    # Create figure
    fig = go.Figure(data=[edge_trace, node_trace])
    
    fig.update_layout(
        title=title,
        showlegend=False,
        hovermode="closest",
        margin=dict(b=20, l=5, r=5, t=40),
        xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
        yaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
        plot_bgcolor="white",
        height=800,
    )
    
    if save_path:
        fig.write_html(save_path)
        print(f"✓ Interactive figure saved to {save_path}")
    
    return fig
