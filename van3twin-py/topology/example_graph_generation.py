"""
example_graph_generation.py

Demonstration script showing how to use the graph_generator module.
This can be copied into a Jupyter notebook cell or run standalone.

"""

import sys
sys.path.insert(0, '/home/rpegurri/Tokyo JSAC/van3twin-py')

import graph_generator as gg
import networkx as nx
import matplotlib.pyplot as plt

# ============================================================================
# Configuration
# ============================================================================

CSV_PATH = "/home/rpegurri/Tokyo JSAC/van3twin-py/simulation_dataset.csv"  
# Adjust to your actual CSV path
# E.g., "simulation_dataset_merged.csv" or "simulation_dataset_1_SUMO_*.csv"

RSU_ID = "rsu_1"  # Target RSU
TIMESTAMP = None  # Will be auto-detected; set to specific value if desired
MAX_HOPS = 3
BBOX = None  # Full map; or set to (min_x, max_x, min_y, max_y)

# ============================================================================
# Example 1: Basic Graph Generation with Default RSSI Filter
# ============================================================================

print("=" * 70)
print("Example 1: Generate graphs with default RSSI > -75 dB filter")
print("=" * 70)

try:
    # Load a single timestamp first to see available data
    links = gg.load_csv_links(CSV_PATH)
    if links:
        # Use first timestamp with links
        ts = links[0].timestamp
        print(f"Using timestamp: {ts}")
        
        uplink, downlink, meta = gg.generate_graphs(
            csv_path=CSV_PATH,
            timestamp=ts,
            rsu_id=RSU_ID,
            bbox=BBOX,
            max_hops=MAX_HOPS,
        )
        
        print(f"\n--- Metadata ---")
        for key, val in meta.items():
            print(f"  {key}: {val}")
        
        print(f"\n--- Uplink Graph ---")
        print(f"  Nodes: {uplink.number_of_nodes()}")
        print(f"  Edges: {uplink.number_of_edges()}")
        if uplink.number_of_nodes() > 0:
            print(f"  Node list: {list(uplink.nodes())[:5]}...")
        
        print(f"\n--- Downlink Graph ---")
        print(f"  Nodes: {downlink.number_of_nodes()}")
        print(f"  Edges: {downlink.number_of_edges()}")
        if downlink.number_of_nodes() > 0:
            print(f"  Node list: {list(downlink.nodes())[:5]}...")

except FileNotFoundError:
    print(f"ERROR: CSV file not found at {CSV_PATH}")
except Exception as e:
    print(f"ERROR: {e}")

# ============================================================================
# Example 2: Custom Link Quality Filter (SINR-based)
# ============================================================================

print("\n" + "=" * 70)
print("Example 2: Generate graphs with custom SINR > 5 dB filter")
print("=" * 70)

try:
    links = gg.load_csv_links(CSV_PATH)
    if links:
        ts = links[0].timestamp
        
        # Create a custom SINR-based filter
        custom_filter = gg.create_sinr_filter(threshold=5.0)
        
        uplink, downlink, meta = gg.generate_graphs(
            csv_path=CSV_PATH,
            timestamp=ts,
            rsu_id=RSU_ID,
            bbox=BBOX,
            max_hops=MAX_HOPS,
            link_reachability_fn=custom_filter,
        )
        
        print(f"Links filtered out by SINR > 5: {meta['links_filtered_out']}")
        print(f"Uplink edges: {uplink.number_of_edges()}")
        print(f"Downlink edges: {downlink.number_of_edges()}")

except Exception as e:
    print(f"ERROR: {e}")

# ============================================================================
# Example 3: Composite Filter (RSSI AND SINR AND Throughput)
# ============================================================================

print("\n" + "=" * 70)
print("Example 3: Composite filter (RSSI > -75 AND SINR > 3 AND Thput > 1 Mbps)")
print("=" * 70)

try:
    links = gg.load_csv_links(CSV_PATH)
    if links:
        ts = links[0].timestamp
        
        # Create composite filter
        filters = [
            gg.create_rssi_filter(-75.0),
            gg.create_sinr_filter(3.0),
            gg.create_throughput_filter(1000.0),  # 1 Mbps = 1000 kbps
        ]
        composite_filter = gg.create_composite_filter(*filters)
        
        uplink, downlink, meta = gg.generate_graphs(
            csv_path=CSV_PATH,
            timestamp=ts,
            rsu_id=RSU_ID,
            bbox=BBOX,
            max_hops=MAX_HOPS,
            link_reachability_fn=composite_filter,
        )
        
        print(f"Links after quality filters: {meta['links_after_quality_filter']}")
        print(f"Links filtered out: {meta['links_filtered_out']}")
        print(f"Uplink edges surviving all filters: {uplink.number_of_edges()}")
        print(f"Downlink edges surviving all filters: {downlink.number_of_edges()}")

except Exception as e:
    print(f"ERROR: {e}")

# ============================================================================
# Example 4: Geographic Filtering (Bounding Box)
# ============================================================================

print("\n" + "=" * 70)
print("Example 4: Generate graphs with geographic bounding box filter")
print("=" * 70)

try:
    links = gg.load_csv_links(CSV_PATH)
    if links:
        ts = links[0].timestamp
        
        # Define a bounding box (min_x, max_x, min_y, max_y)
        bbox = (0, 200, 0, 200)  # Adjust based on your coordinate system
        
        uplink, downlink, meta = gg.generate_graphs(
            csv_path=CSV_PATH,
            timestamp=ts,
            rsu_id=RSU_ID,
            bbox=bbox,
            max_hops=MAX_HOPS,
        )
        
        print(f"Bounding box: {bbox}")
        print(f"Nodes in area: {meta['nodes_in_area']}")
        print(f"Nodes within {MAX_HOPS} hops: {meta['nodes_within_hops']}")
        print(f"Uplink graph: {uplink.number_of_nodes()} nodes, {uplink.number_of_edges()} edges")
        print(f"Downlink graph: {downlink.number_of_nodes()} nodes, {downlink.number_of_edges()} edges")

except Exception as e:
    print(f"ERROR: {e}")

# ============================================================================
# Example 5: Inspect Edge Attributes
# ============================================================================

print("\n" + "=" * 70)
print("Example 5: Inspect edge attributes (metrics stored on edges)")
print("=" * 70)

try:
    links = gg.load_csv_links(CSV_PATH)
    if links:
        ts = links[0].timestamp
        
        uplink, downlink, meta = gg.generate_graphs(
            csv_path=CSV_PATH,
            timestamp=ts,
            rsu_id=RSU_ID,
            bbox=None,
            max_hops=MAX_HOPS,
        )
        
        if uplink.number_of_edges() > 0:
            # Sample first edge
            u, v, attrs = next(iter(uplink.edges(data=True)))
            print(f"\nSample uplink edge: {u} → {v}")
            print(f"  Attributes (ready for cost computation):")
            for key, value in attrs.items():
                print(f"    {key}: {value}")

except Exception as e:
    print(f"ERROR: {e}")

# ============================================================================
# Example 6: Multiple Timestamps (Batch Processing)
# ============================================================================

print("\n" + "=" * 70)
print("Example 6: Batch processing all timestamps")
print("=" * 70)

try:
    agg = gg.generate_all_timestamps(
        csv_path=CSV_PATH,
        rsu_id=RSU_ID,
        bbox=None,
        max_hops=MAX_HOPS,
        link_reachability_fn=None,  # use default
        output_dir=None,  # Don't save to disk; set to a path to save
    )
    
    print(f"\n--- Aggregated Statistics ---")
    for key, val in agg.items():
        if isinstance(val, float):
            print(f"  {key}: {val:.2f}")
        else:
            print(f"  {key}: {val}")

except Exception as e:
    print(f"ERROR: {e}")

print("\n" + "=" * 70)
print("Examples completed!")
print("=" * 70)
