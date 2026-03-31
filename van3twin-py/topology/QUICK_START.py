"""
QUICK START: Graph Generator

Copy-paste snippets to get started immediately.
"""

# ============================================================================
# Setup (one-time)
# ============================================================================

import sys
sys.path.insert(0, '/home/rpegurri/Tokyo JSAC/van3twin-py')
import graph_generator as gg


# ============================================================================
# Single Graph Generation
# ============================================================================

# Basic usage
uplink, downlink, metadata = gg.generate_graphs(
    csv_path="/home/rpegurri/Tokyo JSAC/van3twin-py/simulation_dataset_1_SUMO_0s-162.6s.csv",
    timestamp=0.1,           # Specific timestamp
    rsu_id="rsu_1",          # Target RSU
)

# With all options
uplink, downlink, metadata = gg.generate_graphs(
    csv_path="/path/to/data.csv",
    timestamp=100.0,
    rsu_id="rsu_5",
    bbox=(0, 200, 0, 200),           # Bounding box filter (optional)
    max_hops=3,                      # Multi-hop limit
    link_reachability_fn=None,       # Use default RSSI > -75
)

# Access results
print(f"Uplink edges: {uplink.number_of_edges()}")
print(f"Downlink edges: {downlink.number_of_edges()}")
print(f"Nodes: {uplink.number_of_nodes()}")
print(metadata['links_filtered_out'], "poor-quality links filtered")


# ============================================================================
# Custom Link Quality Filters
# ============================================================================

# Single condition filters
rssi_filter = gg.create_rssi_filter(threshold=-75.0)
sinr_filter = gg.create_sinr_filter(threshold=5.0)
thput_filter = gg.create_throughput_filter(threshold=1000.0)  # kbps

# Use custom filter
uplink, downlink, meta = gg.generate_graphs(
    csv_path="data.csv",
    timestamp=100.0,
    rsu_id="rsu_1",
    link_reachability_fn=sinr_filter,
)

# Composite filter (AND logic)
strict = gg.create_composite_filter(
    gg.create_rssi_filter(-70.0),
    gg.create_sinr_filter(10.0),
    gg.create_throughput_filter(5000.0),
)

uplink, downlink, meta = gg.generate_graphs(
    csv_path="data.csv",
    timestamp=100.0,
    rsu_id="rsu_1",
    link_reachability_fn=strict,
)

# Custom lambda filter
uplink, downlink, meta = gg.generate_graphs(
    csv_path="data.csv",
    timestamp=100.0,
    rsu_id="rsu_1",
    link_reachability_fn=lambda link: link.rssi_dbm > -80 and link.bler < 0.1,
)


# ============================================================================
# Explore Graph Structure
# ============================================================================

# Nodes
print("Nodes:", uplink.nodes())
print("Node attributes:", uplink.nodes(data=True))
for node, attrs in uplink.nodes(data=True):
    print(f"  {node}: type={attrs['type']}, pos=({attrs['x']:.1f}, {attrs['y']:.1f})")

# Edges
print("Edges:", uplink.edges())
for u, v, attrs in uplink.edges(data=True):
    print(f"  {u} → {v}:")
    print(f"    RSSI: {attrs['rssi_dbm']:.1f} dB")
    print(f"    SINR: {attrs['sinr_eff_db']:.1f} dB")
    print(f"    Throughput: {attrs['throughput_kbps']:.0f} kbps")
    print(f"    LoS: {bool(attrs['is_los'])}")


# ============================================================================
# Assign Costs for Routing
# ============================================================================

# Simple cost based on RSSI (lower RSSI = higher cost)
for u, v, attrs in uplink.edges(data=True):
    attrs['cost'] = max(0, -attrs['rssi_dbm'])  # Invert RSSI to cost

# Or: throughput-based (lower throughput = higher cost)
for u, v, attrs in uplink.edges(data=True):
    attrs['cost'] = 1.0 / (attrs['throughput_kbps'] + 1.0)  # Lower throughput = higher cost

# Or: BLER-based (higher BLER = higher cost)
for u, v, attrs in uplink.edges(data=True):
    attrs['cost'] = 100 * attrs['bler']  # BLER in [0, 1]

# Or: Composite cost function
def cost_function(rssi, sinr, bler, throughput):
    return (-rssi) + (1.0 / (sinr + 1.0)) + (100 * bler)

for u, v, attrs in uplink.edges(data=True):
    attrs['cost'] = cost_function(
        attrs['rssi_dbm'],
        attrs['sinr_eff_db'],
        attrs['bler'],
        attrs['throughput_kbps']
    )


# ============================================================================
# Routing with NetworkX
# ============================================================================

import networkx as nx

# Shortest path (with costs)
try:
    path = nx.shortest_path(uplink, source="car_1", target="rsu_1", weight='cost')
    print(f"Shortest path: {' → '.join(path)}")
except nx.NetworkXNoPath:
    print("No path exists")

# All shortest paths
paths = list(nx.all_shortest_paths(uplink, source="car_1", target="rsu_1", weight='cost'))
for i, path in enumerate(paths):
    print(f"Path {i+1}: {' → '.join(path)}")

# Path with metrics
path = nx.shortest_path(uplink, source="car_1", target="rsu_1", weight='cost')
total_cost = 0
for i in range(len(path) - 1):
    u, v = path[i], path[i+1]
    cost = uplink[u][v]['cost']
    rssi = uplink[u][v]['rssi_dbm']
    total_cost += cost
    print(f"{u} → {v}: cost={cost:.2f}, RSSI={rssi:.1f} dB")
print(f"Total cost: {total_cost:.2f}")


# ============================================================================
# Batch Processing: Multiple Timestamps
# ============================================================================

# Simple: iterate over timestamps
import pandas as pd
df = pd.read_csv("data.csv")
for timestamp in df['timestamp'].unique()[:10]:  # First 10 timestamps
    ul, dl, meta = gg.generate_graphs(
        csv_path="data.csv",
        timestamp=timestamp,
        rsu_id="rsu_1",
    )
    print(f"t={timestamp}: {ul.number_of_edges()} uplink edges")

# Or use batch function
stats = gg.generate_all_timestamps(
    csv_path="data.csv",
    rsu_id="rsu_1",
    max_hops=3,
    link_reachability_fn=None,
    output_dir="/tmp/graphs/",  # Save to disk (optional)
)
print(f"Processed {stats['timestamps_processed']} timestamps")
print(f"Avg uplink edges: {stats['avg_uplink_edges']:.1f}")


# ============================================================================
# Visualization: Static (Matplotlib)
# ============================================================================

# Basic visualization (RSSI-colored edges)
fig, ax, pos = gg.visualize_graph(
    uplink,
    title=f"Uplink Graph (RSU: {rsu_id})",
    figsize=(14, 10),
    rsu_color="red",
    car_color="lightblue",
    edge_color_attr="rssi_dbm",  # Color edges by RSSI
    show_labels=True,
    layout="spring",
)
plt.show()

# Save to file
fig.savefig("uplink_graph.png", dpi=150, bbox_inches='tight')


# ============================================================================
# Visualization: Side-by-Side Comparison
# ============================================================================

# Compare uplink vs downlink
fig, axes, positions = gg.visualize_comparison(
    uplink, downlink,
    title1=f"Uplink Graph (→ {rsu_id})",
    title2=f"Downlink Graph (← {rsu_id})",
    figsize=(18, 8),
)
plt.show()

# Save comparison
fig.savefig("uplink_downlink_comparison.png", dpi=150, bbox_inches='tight')


# ============================================================================
# Visualization: Different Metrics
# ============================================================================

# Visualize with throughput coloring
fig, ax, pos = gg.visualize_graph(
    downlink,
    title="Downlink Graph (Throughput)",
    figsize=(14, 10),
    edge_color_attr="throughput_kbps",  # Color by throughput
    layout="kamada_kawai",
)
plt.show()

# Multiple views of same graph with different colorings
metrics = ['rssi_dbm', 'sinr_eff_db', 'throughput_kbps', 'bler']
for metric in metrics:
    fig, ax, pos = gg.visualize_graph(
        uplink,
        title=f"Uplink Graph ({metric})",
        figsize=(10, 8),
        edge_color_attr=metric,
    )
    plt.show()


# ============================================================================
# Visualization: Interactive (Plotly)
# ============================================================================

# Install plotly: pip install plotly

try:
    # Create interactive graph (hover to see edge details)
    fig_interactive = gg.visualize_interactive(
        uplink,
        title=f"Interactive Uplink Graph: {rsu_id}",
        edge_color_attr="rssi_dbm",
    )
    fig_interactive.show()
    
    # Save interactive HTML
    fig_interactive.write_html("interactive_uplink.html")
    
except ImportError:
    print("Plotly not installed. Install with: pip install plotly")


# ============================================================================
# Filter Comparison
# ============================================================================

# Compare different quality thresholds
filters = [
    ("RSSI > -75 (default)", None),
    ("RSSI > -70", gg.create_rssi_filter(-70.0)),
    ("RSSI > -80", gg.create_rssi_filter(-80.0)),
    ("SINR > 5", gg.create_sinr_filter(5.0)),
]

for name, filt in filters:
    ul, dl, meta = gg.generate_graphs(
        csv_path="data.csv",
        timestamp=100.0,
        rsu_id="rsu_1",
        link_reachability_fn=filt,
    )
    print(f"{name:25} → UL:{ul.number_of_edges():3} DL:{dl.number_of_edges():3} nodes:{meta['nodes_within_hops']}")


# ============================================================================
# Metadata Inspection
# ============================================================================

uplink, downlink, meta = gg.generate_graphs(
    csv_path="data.csv",
    timestamp=100.0,
    rsu_id="rsu_1",
)

for key, value in meta.items():
    print(f"{key:30} = {value}")

# Key metrics
print(f"\nFiltering Summary:")
print(f"  Links filtered by quality: {meta['links_filtered_out']}/{meta['total_links_in_csv']}")
print(f"  Links in area: {meta['links_after_quality_filter']}")
print(f"  Nodes in area: {meta['nodes_in_area']}")
print(f"  Nodes reachable within {meta['max_hops']} hops: {meta['nodes_within_hops']}")
