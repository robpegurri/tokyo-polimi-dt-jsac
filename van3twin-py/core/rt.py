import math
import numpy as np
import time
import json
import csv
import os
from scipy.spatial import cKDTree
from sionna.rt import Transmitter, Receiver
import poc.setup as poc

def manage_location_message(message, sionna_structure):
    t = time.time()
    try:
        # Parse the message        
        data = message[len("LOC_UPDATE:"):]
        parts = data.split(",")
        obj_id = int(parts[0].replace("obj", "")) # Numerical ID
        new_x = float(parts[1])
        new_y = float(parts[2])
        new_z = float(parts[3])
        new_angle = -float(parts[4])
        new_v_x = float(parts[5])
        new_v_y = float(parts[6])
        new_v_z = float(parts[7])

        # Save the latest received update data for this object
        sionna_structure["SUMO_live_location_db"][obj_id] = {"x": new_x, "y": new_y, "z": new_z, "angle": new_angle, "v_x": new_v_x, "v_y": new_v_y, "v_z": new_v_z}

        # Potentially, here we could implement some logic
        position_changed = True
        angle_changed = True
        
        #If needed, update Sionna scenario
        if position_changed or angle_changed:

            # Set the current scenario details for object to the just-received one
            sionna_structure["sionna_location_db"][obj_id] = sionna_structure["SUMO_live_location_db"][obj_id]

            # Clear caches upon scenario update
            sionna_structure["path_loss_cache"] = {}
            sionna_structure["rays_cache"] = {}

            # Apply change to the scene
            from_sionna = sionna_structure["scene"].get(f"obj_{obj_id}")
            if from_sionna:
                # Apply updates
                new_orientation = new_angle*np.pi/180
                from_sionna.position = [new_x, new_y, new_z]
                from_sionna.orientation = [new_orientation, 0, 0]
                #from_sionna.velocity = [new_v_x, new_v_y, new_v_z]

                # Compute the new antenna positions
                new_antenna_x = new_x + sionna_structure["antenna_displacement"][obj_id][0]
                new_antenna_y = new_y + sionna_structure["antenna_displacement"][obj_id][1]
                new_antenna_z = new_z + sionna_structure["antenna_displacement"][obj_id][2]

                # Is it a transmitter?
                if obj_id in sionna_structure["transmitters"]:
                    from_sionna_tx_antenna = sionna_structure["scene"].get(f"obj_{obj_id}_tx_antenna")

                    if from_sionna_tx_antenna: # Already in the scene, just move it
                        from_sionna_tx_antenna.position = [new_antenna_x, new_antenna_y, new_antenna_z]
                        from_sionna_tx_antenna.orientation = [new_orientation, 0, 0]
                        #from_sionna_tx_antenna.velocity = [new_v_x, new_v_y, new_v_z]
                    
                    else: # Not in the scene, add it
                        tx_antenna_name = f"obj_{obj_id}_tx_antenna"
                        sionna_structure["scene"].tx_array = sionna_structure["planar_array"]
                        sionna_structure["scene"].rx_array = sionna_structure["planar_array"]
                        sionna_structure["scene"].add(Transmitter(tx_antenna_name, position=[new_antenna_x, new_antenna_y, new_antenna_z], orientation=[0, 0, 0], display_radius=2))
                        sionna_structure["scene"].tx_array = sionna_structure["scene"].tx_array
                        
                # Is it a receiver?
                if obj_id in sionna_structure["receivers"]:
                    from_sionna_rx_antenna = sionna_structure["scene"].get(f"obj_{obj_id}_rx_antenna")

                    if from_sionna_rx_antenna: # Already in the scene, just move it
                        from_sionna_rx_antenna.position = [new_antenna_x, new_antenna_y, new_antenna_z]
                        from_sionna_rx_antenna.orientation = [new_orientation, 0, 0]
                        #from_sionna_rx_antenna.velocity = [new_v_x, new_v_y, new_v_z]

                    else: # Not in the scene, add it
                        rx_antenna_name = f"obj_{obj_id}_rx_antenna"
                        sionna_structure["scene"].tx_array = sionna_structure["planar_array"]
                        sionna_structure["scene"].rx_array = sionna_structure["planar_array"]
                        sionna_structure["scene"].add(Receiver(rx_antenna_name, position=[new_antenna_x, new_antenna_y, new_antenna_z], orientation=[0, 0, 0], display_radius=2))
                        sionna_structure["scene"].rx_array = sionna_structure["scene"].rx_array
            else:
                print(f"ERROR: no obj_{obj_id} in the scene")
                return None
        return obj_id

    except (IndexError, ValueError) as e:
        print(f"EXCEPTION - Location parsing failed: {e}")
        return None
    
def manage_online_reconfiguration(msg_entries, sionna_structure, is_manual_override=False):

    print(" ")
    print("  - - - - - - - - - - - - - - - - -   CONFIGURATION REQUEST   - - - - - - - - - - - - - - - - -  ")
    print(" ")

    cfg_keys = [
        "max_depth", "max_num_paths_per_src", "samples_per_src",
        "los", "specular_reflection", "diffuse_reflection",
        "refraction", "diffraction", "corner_diffraction", "seed", 
        "kalman_process_var", "kalman_meas_var", "kalman_rt_var", 
        "montecarlo_realizations", "montecarlo_max_position_jitter", 
        "use_kalman_filter", "use_adaptive_bias_filter", 
        "adaptive_bias_alpha_signal", "adaptive_bias_alpha_bias", 
        "restart_log", "new_log_name"
    ]
    bool_keys = {
        "los", "specular_reflection", "diffuse_reflection",
        "refraction", "diffraction", "corner_diffraction", 
        "restart_log"
    }

    applied_changes = []
    config_dicts = []
    response = [{}]
    filter = None
    restart_log = None
    new_log_name = None

    for entry in msg_entries:
        if not isinstance(entry, dict):
            continue
        if "data" in entry and isinstance(entry["data"], list):
            for d in entry["data"]:
                if isinstance(d, dict) and any(k in d for k in cfg_keys):
                    config_dicts.append(d)
        if any(k in entry for k in cfg_keys):
            config_dicts.append(entry)

    for cfg in config_dicts:
        for k in cfg_keys:
            if k not in cfg:
                continue
            v = cfg[k]
            if v == -1:
                continue
            if k in bool_keys:
                if isinstance(v, (int, float)):
                    new_v = bool(int(v))
                elif isinstance(v, str):
                    new_v = v.lower() in ("1", "true", "yes")
                else:
                    new_v = bool(v)
            else:
                new_v = v
            
            print(f"        Changing RT config: k={k} from {sionna_structure[k]} to new_v={new_v}")
            sionna_structure[k] = new_v

            if k in {"use_kalman_filter"} and new_v:
                filter = "kalman"
            
            if k in {"use_adaptive_bias_filter"} and new_v:
                filter = "adaptive_bias"

            if k == "restart_log" and new_v:
                restart_log = new_v
            
            if k == "new_log_name" and isinstance(new_v, str) and new_v.strip() != "":
                new_log_name = new_v.strip()

            applied_changes.append((k, new_v))

    if applied_changes:
        print("        Applied RT configuration changes:")
        response[0]["response"] = "200 OK"
        for k, v in applied_changes: 
            print(f"        - {k} = {v}")
            if k in {"kalman_process_var", "kalman_meas_var", "kalman_rt_var"} and filter == "kalman":
                print("        Reconfiguring Kalman filters with new parameters.")
                poc.configure_filters(transmitters=sionna_structure["transmitters"], 
                                      receivers=sionna_structure["receivers"], 
                                      use_kalman_filter=True, 
                                      kalman_process_var=sionna_structure["kalman_process_var"], 
                                      kalman_meas_var=sionna_structure["kalman_meas_var"], 
                                      kalman_rt_var=sionna_structure["kalman_rt_var"])
                
            if k in {"adaptive_bias_alpha_signal", "adaptive_bias_alpha_bias"} and filter == "adaptive_bias":
                print("        Reconfiguring Adaptive Bias filters with new parameters.")
                poc.configure_filters(transmitters=sionna_structure["transmitters"], 
                                      receivers=sionna_structure["receivers"], 
                                      use_adaptive_bias_filter=True, 
                                      adaptive_bias_alpha_signal=sionna_structure["adaptive_bias_alpha_signal"], 
                                      adaptive_bias_alpha_bias=sionna_structure["adaptive_bias_alpha_bias"])
    else:
        print("        No RT configuration changes applied (all fields were -1 or none provided).")
        response[0]["response"] = "304 Not Modified"

    if not is_manual_override:
        response = json.dumps(response, default=lambda o: float(o) if isinstance(o, np.float32) else o)
        sionna_structure["udp_socket"].sendto(response.encode(), sionna_structure["latest_msg_address"])
    
    print(" ")
    print(f"  - - - - - - - - - - - - - - - - -   Configuration Handled   - - - - - - - - - - - - - - - - -  ")

    if restart_log:
        t_for_log = math.trunc(time.time())
        sionna_structure["log_file"] = f"tokyo-poc-sionna-{new_log_name}_{t_for_log}.csv"
        if new_log_name is not None:  
            sionna_structure["log_file"] = f"{new_log_name}.csv"

        log_columns = [
            "local_unix_timestamp", "dt_current_clock", "prediction_clock",
            "json_payload",
        "car_1_predicted_x", "car_1_predicted_y", "car_1_predicted_yaw",
        "car_2_predicted_x", "car_2_predicted_y", "car_2_predicted_yaw",
        "car_3_predicted_x", "car_3_predicted_y", "car_3_predicted_yaw",
        "raw_predicted_rssi_1_2", "raw_predicted_rssi_1_3", "raw_predicted_rssi_2_3",
        "filtered_predicted_rssi_1_2", "filtered_predicted_rssi_1_3", "filtered_predicted_rssi_2_3",
        "location_update_time_ms", "rssi_prediction_time_ms", "total_elapsed_time_ms", "los_1_2", "los_1_3", "los_2_3"
    ]
    if not os.path.exists(sionna_structure["log_file"]):
        with open(sionna_structure["log_file"], mode="w", newline="") as file:
            writer = csv.writer(file)
            writer.writerow(log_columns)
    
    return

def match_rays_to_meshes(paths, sionna_structure):
    t = time.time()
    matched_paths = {}
    
    # Extract and transpose source and target positions
    targets = paths._tgt_positions.numpy().T
    sources = paths._src_positions.numpy().T 

    # Path parameters
    a_real, a_imag = paths.a
    path_coefficients = a_real.numpy() + 1j * a_imag.numpy()
    delays = paths.tau.numpy()
    interactions = paths.interactions.numpy()
    valid = paths.valid.numpy()

    # Adjust car positions for antenna displacement
    adjusted_car_locs = {
        car_id: {
            "x": car_loc["x"] + sionna_structure["antenna_displacement"][car_id][0],
            "y": car_loc["y"] + sionna_structure["antenna_displacement"][car_id][1],
            "z": car_loc["z"] + sionna_structure["antenna_displacement"][car_id][2],
        }
        for car_id, car_loc in sionna_structure["sionna_location_db"].items()
    }

    car_ids = list(adjusted_car_locs.keys()) # Numerical IDs
    car_positions = np.array([[v["x"], v["y"], v["z"]] for v in adjusted_car_locs.values()])
    car_tree = cKDTree(car_positions)

    # Match sources and targets
    source_dists, source_indices = car_tree.query(sources, distance_upper_bound=sionna_structure["position_threshold"])
    target_dists, target_indices = car_tree.query(targets, distance_upper_bound=sionna_structure["position_threshold"])

    for tx_idx, src_idx in enumerate(source_indices):
        if src_idx == len(car_ids):
            if sionna_structure["verbose"]:
                print(f"Warning - No car within tolerance for source {tx_idx}")
            continue

        #print(f"Matching source {tx_idx} to obj_{car_ids[src_idx]} with distance {source_dists[tx_idx]:.2f}")
        if car_ids[src_idx] not in matched_paths:
            matched_paths[car_ids[src_idx]] = {}
        #print(f"  - Found {len(target_indices)} potential targets for source {tx_idx} (obj_{car_ids[src_idx]})")

        for rx_idx, tgt_idx in enumerate(target_indices):
            if tgt_idx == len(car_ids):
                if sionna_structure["verbose"]:
                    print(f"Warning - No car within tolerance for target {rx_idx} (for source {tx_idx})")
                continue
            #print(f"  - Matching target {rx_idx} to obj_{car_ids[tgt_idx]} with distance {target_dists[rx_idx]:.2f}")
            if car_ids[tgt_idx] not in matched_paths[car_ids[src_idx]]:
                matched_paths[car_ids[src_idx]][car_ids[tgt_idx]] = {
                    'path_coefficients': [],
                    'delays': [],
                    'is_los': []
                }

            try:
                coeff = path_coefficients[rx_idx, 0, tx_idx, 0, :]
                delay = delays[rx_idx, 0, tx_idx, 0, :]
                valid_mask = valid[rx_idx, 0, tx_idx, 0, :].astype(bool)
                # Extract
                interaction_types = interactions[:, rx_idx, 0, tx_idx, 0, :]
                interaction_types_masked = interaction_types[:, valid_mask]  # shape: (5, <=12)
                is_los = np.any(interaction_types_masked[0] == 0) # 0 is NONE interaction
                # Store
                matched_paths[car_ids[src_idx]][car_ids[tgt_idx]]['path_coefficients'].append(coeff)
                matched_paths[car_ids[src_idx]][car_ids[tgt_idx]]['delays'].append(delay)
                matched_paths[car_ids[src_idx]][car_ids[tgt_idx]]['is_los'].append(bool(is_los))

            except Exception as e:
                print(f"Error encountered for source {tx_idx}, target {rx_idx}: {e}")
                continue
    return matched_paths

def compute_rays(sionna_structure):
    t = time.time()

    # Compute paths
    paths = sionna_structure["path_solver"](scene=sionna_structure["scene"],
                                            max_depth=sionna_structure["max_depth"],
                                            los=sionna_structure["los"],
                                            specular_reflection=sionna_structure["specular_reflection"],
                                            diffuse_reflection=sionna_structure["diffuse_reflection"],
                                            refraction=sionna_structure["refraction"],
                                            synthetic_array=sionna_structure["synthetic_array"],
                                            seed=sionna_structure["seed"],
                                            diffraction=sionna_structure["diffraction"],
                                            edge_diffraction=sionna_structure["corner_diffraction"])
    paths.normalize_delays = False

    # Save raw paths (for debugging and analysis)
    sionna_structure["paths"] = paths

    # Computation time handler
    global ray_tracing_time_ms
    ray_tracing_time_ms = (time.time() - t) * 1000
    if sionna_structure["time_checker"]:
        print(f"        Ray tracing took: {ray_tracing_time_ms} ms")
    
    # Match paths to object pairs
    matched_paths = match_rays_to_meshes(paths, sionna_structure)

    #print(f"        [OK] Matched paths for {len(matched_paths)} sources. Starting caching...")

    # Iterate over valid sources in matched_paths
    for src_car_id in matched_paths:
        
        #print(f"    [DEBUG] Processing source {src_car_id} for caching...")
        matched_paths_for_source = matched_paths[src_car_id]

        # Iterate over targets for the current source
        for trg_car_id in matched_paths_for_source:
            #print(f"        [DEBUG] Checking target {trg_car_id}...")

            if trg_car_id != src_car_id:  # Skip case where source == target
                
                if src_car_id not in sionna_structure["rays_cache"]:
                    # Create new entry
                    #print(f"        [DEBUG] No cache entry for source {src_car_id}, initializing...")
                    sionna_structure["rays_cache"][src_car_id] = {}
                    
                # Cache the matched paths for this source-target pair
                #print(f"        [DEBUG] Caching rays for {src_car_id} -> {trg_car_id} with {len(matched_paths_for_source[trg_car_id]['path_coefficients'])} paths")
                sionna_structure["rays_cache"][src_car_id][trg_car_id] = matched_paths_for_source[trg_car_id]
    return None

def get_path_loss(car1_id, car2_id, sionna_structure):
    
    #print(f"Calculating path loss for object {car1_id} -> object {car2_id} in get_path_loss()...")

    t = time.time()
    rc = sionna_structure["rays_cache"]
    path_coefficients = []
    total_cir = 0

    if not (car1_id in rc and car2_id in rc[car1_id]) and not (car2_id in rc and car1_id in rc[car2_id]):
        #print(f"    [WARN] No cached rays for {car1_id}-{car2_id}, calling compute_rays()...")
        compute_rays(sionna_structure)

    # Retrieve from cache unconditionally — covers both the cache-hit path and the
    # freshly-computed path (including reciprocal lookup for Rx-only nodes like RSUs).
    if car1_id in rc and car2_id in rc[car1_id]:
        path_coefficients = rc[car1_id][car2_id].get("path_coefficients", [])
    elif car2_id in rc and car1_id in rc[car2_id]:
        path_coefficients = rc[car2_id][car1_id].get("path_coefficients", [])

    if len(path_coefficients) > 0:
        # Uncoherent paths summation
        sum_coeffs = np.sum(path_coefficients)
        abs_coeffs = np.abs(sum_coeffs)
        square = abs_coeffs ** 2
        total_cir = square

    # Calculate path loss in dB
    if total_cir > 0:
        path_loss = -10 * np.log10(total_cir)
    else:
        # Handle the case where path loss calculation is not valid
        #if sionna_structure["verbose"]:
            #print(f"    [WARN] Not enough rays for {car1_id}-{car2_id}. Returning 300 dB.")
        path_loss = 404

    return path_loss

def get_los(car1_id, car2_id, sionna_structure):
    t = time.time()
    rc = sionna_structure["rays_cache"]
    if not (car1_id in rc and car2_id in rc[car1_id]) and not (car2_id in rc and car1_id in rc[car2_id]):
        compute_rays(sionna_structure)

    is_los = False

    if car1_id in rc and car2_id in rc[car1_id]:
        is_los = any(rc[car1_id][car2_id].get("is_los", []))
    elif car2_id in rc and car1_id in rc[car2_id]:
        is_los = any(rc[car2_id][car1_id].get("is_los", []))
    else:
        print(f"    [WARN] No rays found for {car1_id}-{car2_id} after compute_rays()")
        is_los = None
    
    #print(f"    [DEBUG] LoS Status between {car1_id} and {car2_id}: {is_los}")

    return is_los