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

    transmitters = [30, 31, 5, 6]
    receivers = [1, 2, 40, 7]

    tx_to_idx = {tx_id: i for i, tx_id in enumerate(transmitters)}
    rx_to_idx = {rx_id: i for i, rx_id in enumerate(receivers)}

    # path_coefficients shape: [num_rx, num_rx_ant, num_tx, num_tx_ant, num_paths]
    links = [(30, 1), (30, 7), (6, 40), (5, 2)]

    if "rays_cache" not in sionna_structure:
        sionna_structure["rays_cache"] = {}

    for tx_id, rx_id in links:
        ti = tx_to_idx[tx_id]
        ri = rx_to_idx[rx_id]
        coeffs = path_coefficients[ri, 0, ti, 0, :]
        active = coeffs[coeffs != 0]
        #print(f"Tx {tx_id} -> Rx {rx_id}: {len(active)} active paths out of {len(coeffs)}")
        #print(f"  Coefficients: {active}\n")

        if tx_id not in sionna_structure["rays_cache"]:
            sionna_structure["rays_cache"][tx_id] = {}
        sionna_structure["rays_cache"][tx_id][rx_id] = {"path_coefficients": active}

    return sionna_structure["rays_cache"]


def compute_rssi(tx_id, rx_id, sionna_structure):

    #print(f"Calculating path loss for object {tx_id} -> object {rx_id} in get_path_loss()...")

    t = time.time()
    rc = sionna_structure["rays_cache"]
    path_coefficients = []
    total_cir = 0

    if not (tx_id in rc and rx_id in rc[tx_id]) and not (rx_id in rc and tx_id in rc[rx_id]):
        print(f"    [WARN] No cached rays for {tx_id}-{rx_id}, calling compute_rays()...")
        compute_rays(sionna_structure)
        rc = sionna_structure["rays_cache"]  # re-read after recompute

    print(f"    [TIME] Ray retrieval for {tx_id}-{rx_id} took {(time.time() - t) * 1000:.2f} ms")

    # Retrieve from cache unconditionally — covers both the cache-hit path and the
    # freshly-computed path (including reciprocal lookup for Rx-only nodes like RSUs).
    if tx_id in rc and rx_id in rc[tx_id]:
        path_coefficients = rc[tx_id][rx_id].get("path_coefficients", [])
    elif rx_id in rc and tx_id in rc[rx_id]:
        path_coefficients = rc[rx_id][tx_id].get("path_coefficients", [])

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
            #print(f"    [WARN] Not enough rays for {tx_id}-{rx_id}. Returning 300 dB.")
        path_loss = 404

    if tx_id in sionna_structure["object_and_antennas"]:
        ant_data = sionna_structure["object_and_antennas"][tx_id]
        ant_id = list(ant_data.keys())[0]
        tx_power_dbm = ant_data[ant_id].get("tx_power_dbm", 0)
    else:
        tx_power_dbm = 0
    print("Tx power for {}: {}".format(tx_id, tx_power_dbm))
    rssi = tx_power_dbm - path_loss

    return rssi