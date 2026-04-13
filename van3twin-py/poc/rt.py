import time
import numpy as np

def compute_rays(sionna_structure):

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

    # Save raw paths (for debugging and analysis)
    sionna_structure["paths"] = paths

    # Extract path coefficients and organize them by Tx-Rx pairs
    a_real, a_imag = paths.a
    path_coefficients = a_real.numpy() + 1j * a_imag.numpy()
    interactions = paths.interactions.numpy()
    valid = paths.valid.numpy()

    # Let us map transmitters and receivers to their indices in the path solver output
    transmitters = sionna_structure["transmitters"]
    receivers = sionna_structure["receivers"]
    tx_to_idx = {tx_id: i for i, tx_id in enumerate(transmitters)}
    rx_to_idx = {rx_id: i for i, rx_id in enumerate(receivers)}

    # path_coefficients shape: [num_rx, num_rx_ant, num_tx, num_tx_ant, num_paths]
    links = sionna_structure["links"] 

    if "rays_cache" not in sionna_structure:
        sionna_structure["rays_cache"] = {}

    for tx_id, rx_id in links:
        ti = tx_to_idx[tx_id]
        ri = rx_to_idx[rx_id]
        coeffs = path_coefficients[ri, 0, ti, 0, :]
        active = coeffs[coeffs != 0]

        if sionna_structure["synthetic_array"]:
            valid_mask = valid[ri, ti, :].astype(bool)
            interaction_types = interactions[:, ri, ti, :]
            interaction_types_masked = interaction_types[:, valid_mask]
            is_los = np.any(interaction_types_masked[0] == 0)

        else:
            valid_mask = valid[ri, 0, ti, 0, :].astype(bool)
            interaction_types = interactions[:, ri, 0, ti, 0, :]
            interaction_types_masked = interaction_types[:, valid_mask]
            is_los = np.any(interaction_types_masked[0] == 0)

        
        if sionna_structure["verbose"]:
            print(f"     [DEBUG] Path Solver found {len(active)} active paths for Tx {tx_id} -> Rx {rx_id}.")

        if tx_id not in sionna_structure["rays_cache"]:
            sionna_structure["rays_cache"][tx_id] = {}

        sionna_structure["rays_cache"][tx_id][rx_id] = {"path_coefficients": active, 
                                                        "is_los": is_los}

    return sionna_structure["rays_cache"]


def compute_rssi(ant_id_tx, ant_id_rx, sionna_structure):

    t = time.time()

    verbose = sionna_structure["verbose"]
    time_checker = sionna_structure["time_checker"]

    if verbose:
        print(f"    [DEBUG] Calculating path loss for object {ant_id_tx} -> object {ant_id_rx} in get_path_loss()...")

    # Safety checks
    if ant_id_tx not in sionna_structure["transmitters"]:
        print(f"    [ERROR] Transmitter antenna {ant_id_tx} not set as a transmitter.")
        return None
    if ant_id_rx not in sionna_structure["receivers"]:
        print(f"    [ERROR] Receiver antenna {ant_id_rx} not set as a receiver.")
        return None

    rc = sionna_structure["rays_cache"]
    path_coefficients = []
    total_cir = 0

    if ant_id_tx not in rc.keys():
        if verbose:
            print(f"    [DEBUG] No cached rays for {ant_id_tx}-{ant_id_rx}, calling compute_rays()...")
        compute_rays(sionna_structure)
        rc = sionna_structure["rays_cache"]  # re-read after recompute

    if time_checker:
        print(f"    [TIME] Ray retrieval for {ant_id_tx}-{ant_id_rx} took {(time.time() - t) * 1000:.2f} ms")

    # Retrieve from cache
    if ant_id_tx in rc and ant_id_rx in rc[ant_id_tx]:
        if verbose:
            print(f"    [DEBUG] Retrieved path coefficients from cache for {ant_id_tx}-{ant_id_rx}.")
        path_coefficients = rc[ant_id_tx][ant_id_rx].get("path_coefficients", [])

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
        if verbose:
            print(f"    [WARN] Not enough rays for {ant_id_tx}-{ant_id_rx}. Returning 300 dB.")
        path_loss = 404

    for obj_id in sionna_structure["object_and_antennas"]:
        if ant_id_tx in sionna_structure["object_and_antennas"][obj_id]:
            ant_data = sionna_structure["object_and_antennas"][obj_id][ant_id_tx]
            tx_power_dbm = ant_data.get("tx_power_dbm")
            break

    if verbose:
        print(f"    [DEBUG] Retrieved tx power for {ant_id_tx}, is: {tx_power_dbm} dBm")

    if path_loss != 404:
        rssi = tx_power_dbm - path_loss
    else:
        rssi = -300 

    return rssi


def compute_los_status (ant_id_tx, ant_id_rx, sionna_structure):

    rays_cache = sionna_structure["rays_cache"]

    if ant_id_tx in rays_cache and ant_id_rx in rays_cache[ant_id_tx]:
        is_los = rays_cache[ant_id_tx][ant_id_rx].get("is_los", False)
        return is_los
    return False