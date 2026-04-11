import poc.rt as rt
import time

def evaluate_best_topology(sionna_structure=None, margin_dbm=5):
    '''
    Possible routes we have to compare:

    a) Car 2 -> Car 1:
        - 5 -> 2 (V2V)
        - 6 -> 40 -- 30 -> 1 (V2I + I2V)

    b) RSU -> Car 1:
        - 30 -> 1 (I2V)
        - 31 -> 7 -- 5 -> 2 (I2V + V2V)

    Takes the following parameters as input:
        - **sionna_structure**: the global structure containing the scene and object information, returned by _poc.startup()_
        - **margin_dbm**: the minimum RSSI difference (in dBm) required to prefer the multi-hop topology over the direct one. This is to still prefer direct communication over a slightly better multi-hop in case of small differences that might be within the noise margin.

    Returns a dictionary with the evaluated topologies and the suggested best topology for each Tx-Rx pair.
    The structure of the returned dictionary is as follows:
    ```python
    {
        "Topology_Vehicle2_1": {
            "RSSI_Vehicle2_1": <rssi_value>,
            "RSSI_Vehicle2_RSU": <rssi_value>,
            "RSSI_RSU_Vehicle1": <rssi_value>,
            "Suggested_Topology": <suggested_topology>,
            "Type": <topology_type>
        },
        "Topology_RSU_Vehicle1": {
            "RSSI_RSU_Vehicle1": <rssi_value>,
            "RSSI_RSU_Vehicle2": <rssi_value>,
            "RSSI_Vehicle2_Vehicle1": <rssi_value>,
            "Suggested_Topology": <suggested_topology>,
            "Type": <topology_type>
        }
    }
    ```

    Where:
        - **<rssi_value>** is the computed RSSI value for the corresponding link (in dBm)
        - **<suggested_topology>** is the suggested best topology based on the RSSI comparison (e.g., "5->2" or "6->40--30->1" with -- indicating inter-object communication)
        - **<topology_type>** indicates whether the suggested topology is direct (e.g., "V2V") or multi-hop (e.g., "V2I2V")
    '''

    # TODO: it should not be hardcoded... bad coder!

    if sionna_structure["time_checker"]:
        start_time = time.time() * 1000

    topologies = {}

    # Case a) Car 2 -> Car 1
    # V2V
    rssi_5_2 = float(rt.compute_rssi(5, 2, sionna_structure=sionna_structure))
    # V2I and I2V
    rssi_6_40 = float(rt.compute_rssi(6, 40, sionna_structure=sionna_structure))
    rssi_30_1 = float(rt.compute_rssi(30, 1, sionna_structure=sionna_structure))
    min_rssi_v2i_i2v = min(rssi_6_40, rssi_30_1)

    topologies["Topology_Vehicle2_1"] = {
            # Direct
            "RSSI_Vehicle2_1": rssi_5_2,
            # Multi hop
            "RSSI_Vehicle2_RSU": rssi_6_40,
            "RSSI_RSU_Vehicle1": rssi_30_1
        }
    
    out = -300.0

    v2v_ok    = rssi_5_2 != out
    v2i2v_ok  = min_rssi_v2i_i2v != out

    if v2v_ok and v2i2v_ok:
        if min_rssi_v2i_i2v >= rssi_5_2 + margin_dbm:
            suggestion = {"Suggested_Topology": "6->40->30->1", "Type": "V2I2V"}
        else:
            suggestion = {"Suggested_Topology": "5->2", "Type": "V2V"}
    elif v2v_ok:
        suggestion = {"Suggested_Topology": "5->2", "Type": "V2V"}
    elif v2i2v_ok:
        suggestion = {"Suggested_Topology": "6->40->30->1", "Type": "V2I2V"}
    else:
        suggestion = {"Suggested_Topology": "OUTAGE", "Type": "OUTAGE"}

    topologies["Topology_Vehicle2_1"].update(suggestion)


    # Case b) RSU -> Car 1
    # V2V
    rssi_30_1 = float(rt.compute_rssi(30, 1, sionna_structure=sionna_structure))
    # I2V and V2V
    rssi_31_7 = float(rt.compute_rssi(31, 7, sionna_structure=sionna_structure))
    min_rssi_i2v_v2v = min(rssi_31_7, rssi_5_2)

    topologies["Topology_RSU_Vehicle1"] = {
            # Direct
            "RSSI_RSU_Vehicle1": rssi_30_1,
            # Multi hop
            "RSSI_RSU_Vehicle2": rssi_31_7,
            "RSSI_Vehicle2_Vehicle1": rssi_5_2
        }
    
    i2v_ok   = rssi_30_1 != out
    i2v2v_ok = min_rssi_i2v_v2v != out

    if i2v_ok and i2v2v_ok:
        if min_rssi_i2v_v2v >= rssi_30_1 + margin_dbm:
            suggestion = {"Suggested_Topology": "31->7->5->2", "Type": "I2V2V"}
        else:
            suggestion = {"Suggested_Topology": "30->1", "Type": "I2V"}
    elif i2v_ok:
        suggestion = {"Suggested_Topology": "30->1", "Type": "I2V"}
    elif i2v2v_ok:
        suggestion = {"Suggested_Topology": "31->7->5->2", "Type": "I2V2V"}
    else:
        suggestion = {"Suggested_Topology": "OUTAGE", "Type": "OUTAGE"}

    topologies["Topology_RSU_Vehicle1"].update(suggestion)

    if sionna_structure["time_checker"]:
        end_time = time.time() * 1000
        print(f"     [TIME] Time taken for topology evaluation: {end_time - start_time:.4f} ms")

    return topologies