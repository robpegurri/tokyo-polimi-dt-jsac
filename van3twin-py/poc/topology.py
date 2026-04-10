import poc.rt as rt

def evaluate_best_topology(sionna_structure=None, margin_dbm=5):

    '''
    Possible routes:

    (a) Car 2 -> Car 1:
        - 5 -> 2 (V2V)
        - 6 -> 40 -- 30 -> 1 (V2I + I2V)

    (b) RSU -> Car 1:
        - 30 -> 1 (I2V)
        - 31 -> 7 -- 5 -> 2 (I2V + V2V)

    '''

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
    
    out = 300.0
    
    if min_rssi_v2i_i2v != out and rssi_5_2 != out:
        if min_rssi_v2i_i2v >= rssi_5_2 + margin_dbm:
            suggestion = {
                "Suggested_Topology": "6->40->30->1",
                "Type": "V2I2V"
            }
            topologies["Topology_Vehicle2_1"].update(suggestion)
        else:
            suggestion = {
                "Suggested_Topology": "5->2",
                "Type": "V2V"
            }
            topologies["Topology_Vehicle2_1"].update(suggestion)
    else:
        suggestion = {
            "Suggested_Topology": "OUTAGE",
            "Type": "OUTAGE"
        }
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
    
    if min_rssi_i2v_v2v != out and rssi_30_1 != out:
        if min_rssi_i2v_v2v >= rssi_30_1 + margin_dbm:
            suggestion = {
                "Suggested_Topology": "31->7->5->2",
                "Type": "I2V2V"
            }
            topologies["Topology_RSU_Vehicle1"].update(suggestion)
        else:
            suggestion = {
                "Suggested_Topology": "30->1",
                "Type": "I2V"
            }
            topologies["Topology_RSU_Vehicle1"].update(suggestion)
    else:
        suggestion = {
            "Suggested_Topology": "OUTAGE",
            "Type": "OUTAGE"
        }
        topologies["Topology_RSU_Vehicle1"].update(suggestion)

    return topologies