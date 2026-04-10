import socket
from antennas.custom_antenna import extract_custom_pattern
from sionna.rt import PathSolver, Camera, PlanarArray, load_scene, load_mesh, SceneObject, ITURadioMaterial, Receiver, Transmitter
from core.filters import RSSIKalmanFilter, AdaptiveBiasFilter
import numpy as np

sionna_structure = dict()
ray_tracing_time_ms = 0
frame_num = 0

sionna_structure["run_type"] = "real-time" # or "simulation"

def setup_scene(file_name, frequency, bandwidth, verbose=False, time_checker=False):
    # Import scene
    sionna_structure["scene"] = load_scene(filename=file_name, merge_shapes=True, merge_shapes_exclude_regex="car")

    # Set propagation settings
    sionna_structure["scene"].frequency = frequency
    sionna_structure["frequency"] = frequency
    sionna_structure["scene"].bandwidth = bandwidth
    sionna_structure["bandwidth"] = bandwidth

    # Set verbose
    sionna_structure["verbose"] = verbose
    sionna_structure["time_checker"] = time_checker
    if verbose:
        print(f"    [INFO] Verbose mode is enabled.")
    if time_checker:
        print(f"    [INFO] Time checker is enabled.")

    print(f"    [INFO] Loaded scene with frequency {frequency/1e9} GHz, bandwidth {bandwidth/1e6} MHz.")

    return sionna_structure["scene"]


def setup_antenna_type(transmitters, receivers,
                       num_rows=1, num_cols=1, vertical_spacing=0.5, horizontal_spacing=0.5, 
                       pattern="dipole", polarization="VH", elevation_csv=None, azimuth_csv=None,
                       simulate_perfect_beamforming=False):

    sionna_structure["transmitters"] = transmitters
    sionna_structure["receivers"] = receivers
    sionna_structure["simulate_perfect_beamforming"] = simulate_perfect_beamforming

    # Custom antenna pattern - Panasonic 60 GHz WiGig RSU
    if pattern == "panasonic_wigig_rsu":
        if elevation_csv is None or azimuth_csv is None:
            print("     [ERROR] Custom pattern selected but elevation or azimuth CSV files not provided.")
        else:
            extract_custom_pattern(elevation_csv=elevation_csv, azimuth_csv=azimuth_csv)

        sionna_structure["planar_array"] = PlanarArray(num_rows=num_rows, num_cols=num_cols, vertical_spacing=vertical_spacing, horizontal_spacing=horizontal_spacing, pattern="panasonic_wigig_rsu", elevation_csv=elevation_csv, azimuth_csv=azimuth_csv)
   
    else:
        sionna_structure["planar_array"] = PlanarArray(num_rows=num_rows, num_cols=num_cols, vertical_spacing=vertical_spacing, horizontal_spacing=horizontal_spacing, pattern=pattern, polarization=polarization)
    
    # Apply to the scene
    sionna_structure["scene"].rx_array = sionna_structure["planar_array"]
    sionna_structure["scene"].tx_array = sionna_structure["planar_array"]

    return


def setup_rt(rt_max_depth=5,
                 rt_max_num_paths_per_src=1e10,
                 rt_samples_per_src=1e10,
                 rt_los=True,
                 rt_specular_reflection=True,
                 rt_diffuse_reflection=True,
                 rt_refraction=True,
                 rt_diffraction=False,
                 rt_corner_diffraction=False,
                 rt_sbr_seed=42,
                 rt_synthetic_array=False):
    
    sionna_structure["path_solver"] = PathSolver()

    sionna_structure["max_depth"] = rt_max_depth
    sionna_structure["max_num_paths_per_src"] = rt_max_num_paths_per_src
    sionna_structure["samples_per_src"] = rt_samples_per_src
    sionna_structure["los"] = rt_los
    sionna_structure["specular_reflection"] = rt_specular_reflection
    sionna_structure["diffuse_reflection"] = rt_diffuse_reflection
    sionna_structure["refraction"] = rt_refraction
    sionna_structure["diffraction"] = rt_diffraction
    sionna_structure["corner_diffraction"] = rt_corner_diffraction
    sionna_structure["seed"] = rt_sbr_seed
    sionna_structure["synthetic_array"] = rt_synthetic_array

    return


def setup_filters(transmitters, 
                      receivers,
                      use_kalman_filter=False,        # Kalman filter parameters
                      kalman_process_var=0.3, 
                      kalman_meas_var=0.8, 
                      kalman_rt_var=3,
                      use_adaptive_bias_filter=False, # Adaptive bias filter parameters
                      adaptive_bias_alpha_signal=0.1, 
                      adaptive_bias_alpha_bias=0.05):
    
    if use_kalman_filter == use_adaptive_bias_filter == False:
        print("     [WARNING] No filter selected. RT predictions will be used as-is without any filtering.")

    if use_kalman_filter and use_adaptive_bias_filter:
        print("     [ERROR] A single filter can be used at a time.")
        return
    
    sionna_structure["filters"] = {}
    
    if use_kalman_filter:
        sionna_structure["use_kalman_filter"] = True

        for tx in transmitters:
            for rx in receivers:
                sionna_structure["filters"][(f"{tx}", f"{rx}")] = RSSIKalmanFilter(process_var=kalman_process_var, 
                                                                         meas_var=kalman_meas_var, 
                                                                         rt_var=kalman_rt_var)
                sionna_structure["filters"][(f"{rx}", f"{tx}")] = RSSIKalmanFilter(process_var=kalman_process_var, 
                                                                         meas_var=kalman_meas_var, 
                                                                         rt_var=kalman_rt_var)
                
    
    if use_adaptive_bias_filter:
        sionna_structure["use_adaptive_bias_filter"] = True

        for tx in transmitters:
            for rx in receivers:
                sionna_structure["filters"][(f"{tx}", f"{rx}")] = AdaptiveBiasFilter(alpha_signal=adaptive_bias_alpha_signal, 
                                                                                     alpha_bias=adaptive_bias_alpha_bias)
                sionna_structure["filters"][(f"{rx}", f"{tx}")] = AdaptiveBiasFilter(alpha_signal=adaptive_bias_alpha_signal, 
                                                                                     alpha_bias=adaptive_bias_alpha_bias)
    
    return


def setup_antenna_on_object (ref_obj_id, ant_id, peer_antenna_id, displacement, orientation, mounted_vertically=False, tx_power_dbm=None):

    '''
        Parameters:
        - ref_obj_id: the reference numerical object ID
        - ant_id: the numerical antenna ID
        - peer_antenna_id: the id of the other antenna to which it is bounded
        - displacement: the 3D displacement of the antenna from the reference point on the object [dx, dy, dz]
        - orientation: the orientation of the antenna relative to the object [alpha, theta, phi]
        - mounted_vertically: whether the antenna is mounted vertically

        - tx_power_dbm: the transmit power in dBm (required if the antenna is a transmitter)

        Output:
        sionna_structure["object_and_antennas"] = {
            ref_obj_id: {
                ant_id: {
                    "ant_id": ant_id,
                    "peer_antenna_id": peer_antenna_id,
                    "displacement": [dx, dy, dz],
                    "orientation": [alpha, theta, phi],
                    "tx_power_dbm": tx_power_dbm,
                    "mounted_vertically": mounted_vertically
                },
                ...
            },
            ...
        }
    '''

    if sionna_structure["simulate_perfect_beamforming"] and peer_antenna_id is None:
        print(f"     [ERROR] Perfect beamforming simulation requires a peer antenna ID to be specified for {ant_id}.")
        return
    
    if sionna_structure["simulate_perfect_beamforming"] == False and orientation is None:
        print(f"     [ERROR] Fixed antenna orientation must be specified for {ant_id} when not simulating perfect beamforming.")
        return

    if ant_id in sionna_structure["transmitters"] and tx_power_dbm is None:
        print(f"     [ERROR] {ant_id} is defined as a Transmitter: Tx power (dBm) must be provided.")
        return
    
    if "object_and_antennas" not in sionna_structure:
        sionna_structure["object_and_antennas"] = {}

    if ref_obj_id not in sionna_structure["object_and_antennas"]:
        sionna_structure["object_and_antennas"][ref_obj_id] = {}

    scene = sionna_structure["scene"]
    car_position = scene.get(f"obj_{ref_obj_id}").position
    ant_position = [car_position[0] + displacement[0], car_position[1] + displacement[1], car_position[2] + displacement[2]]

    if mounted_vertically:
        # Roll the array 90° around its boresight (+X axis) so the elements stand upright.
        # Pitch (orientation[1]) steers elevation during beamforming — do not touch it here.
        orientation = [orientation[0], orientation[1], orientation[2] + np.pi / 2]

    if ant_id not in sionna_structure["object_and_antennas"][ref_obj_id]:
        sionna_structure["object_and_antennas"][ref_obj_id][ant_id] = {
            "ant_id": ant_id,
            "peer_antenna_id": peer_antenna_id,
            "displacement": displacement,
            "orientation": orientation,   # stored AFTER roll correction so point_toward_peer preserves it
            "tx_power_dbm": tx_power_dbm,
            "mounted_vertically": mounted_vertically
        }

    if ant_id in sionna_structure["transmitters"]:
        scene.tx_array = sionna_structure["planar_array"]
        scene.add(Transmitter(f"ant_{ant_id}", position=ant_position, orientation=orientation, display_radius=1))

    if ant_id in sionna_structure["receivers"]:
        scene.rx_array = sionna_structure["planar_array"]
        scene.add(Receiver(f"ant_{ant_id}", position=ant_position, orientation=orientation, display_radius=1))


def add_object(ref_obj_id=None, mesh_path=None, position=None):

    scene = sionna_structure["scene"]

    if scene.get(f"obj_{ref_obj_id}") is not None:
        print(f"Object {ref_obj_id} (obj_{ref_obj_id}) already exists in the scene.")
        return scene.get(f"obj_{ref_obj_id}")
    
    mesh = load_mesh(mesh_path)

    obj = SceneObject(mi_mesh=mesh,
                      name=f"obj_{ref_obj_id}",
                      radio_material=ITURadioMaterial(f"itu_metal_{ref_obj_id}",
                                                        "metal",
                                                        thickness=0.01,
                                                        color=(0.8, 0.1, 0.1)))
    scene.edit(add=obj)
    # Apply position
    scene.get(f"obj_{ref_obj_id}").position = position
    scene.get(f"obj_{ref_obj_id}").orientation = [-0.5*np.pi, 0, 0]

    return obj


def add_tree(ref_tree_id=None, mesh_path=None, position=None):

    tree_mesh = load_mesh(mesh_path)
    tree_obj = SceneObject(mi_mesh=tree_mesh,
                        name=f"tree_{ref_tree_id}",
                        radio_material=ITURadioMaterial(f"itu_wood_{ref_tree_id}",
                                                    "wood",
                                                    thickness=0.01,
                                                    color=(0.6, 0.3, 0.1)))
    sionna_structure["scene"].edit(add=tree_obj)

    x = position[0]
    y = position[1]
    z = position[2]

    sionna_structure["scene"].get(f"tree_{ref_tree_id}").position = [x, y, z]

    return


def startup():

    # Integration
    port = 35944
    sionna_structure["position_threshold"] = 0.01
    sionna_structure["angle_threshold"] = 0.01

    # Caches
    sionna_structure["path_loss_cache"] = {}
    sionna_structure["delay_cache"] = {}
    sionna_structure["last_path_loss_requested"] = None

    # Set up UDP socket
    if sionna_structure["run_type"] == "real-time":
        udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        udp_socket.bind(("0.0.0.0", port))  # External server configuration
        print(f"    [INFO] Expecting UDP messages from Tokyo Digital Twin on UDP/{port}")
    else:
        udp_socket = None
    sionna_structure["udp_socket"] = udp_socket

    # Location databases and caches
    sionna_structure["SUMO_live_location_db"] = {}  # Real-time vehicle locations in SUMO
    sionna_structure["sionna_location_db"] = {}  # Vehicle locations in Sionna
    sionna_structure["rays_cache"] = {}  # Cache for ray information
    sionna_structure["path_loss_cache"] = {}  # Cache for path loss values

    # Remote log settings
    sionna_structure["restart_log"] = None
    sionna_structure["new_log_name"] = None

    sionna_structure["my_cam"] = Camera(position=[-50,30,100], look_at=[-39.4388, 45.5538, 0.541952])

    '''
    # Handle logging
    t_for_log = math.trunc(time.time())
    sionna_structure["log_file"] = f"tokyo-poc-sionna-log_{t_for_log}.csv"
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
    '''

    # Manual override of the configuration!
    configuration = {"data": []}
    configuration["data"].append({
        "type": "RT_CONFIGURATION_MESSAGE",
        "max_depth": 30,
        "max_num_paths_per_src": 10e10,
        "samples_per_src": 10e10,
        "los": True,
        "specular_reflection": True,
        "diffuse_reflection": True,
        "refraction": True,
        "diffraction": True,
        "corner_diffraction": True,
        "seed": 42,
        # Kalman filter parameters
        "use_kalman_filter": True,
        "kalman_process_var": 0.3, # 
        "kalman_meas_var": 0.8,    # Lower = trust measurement more
        "kalman_rt_var": 3,       # Higher = trust RT less
        # Monte Carlo parameters
        "montecarlo_realizations": 0,
        "montecarlo_max_position_jitter": 0,
        # Adaptive bias filter parameters
        "use_adaptive_bias_filter": False,
        "adaptive_bias_alpha_signal": 0.5,
        "adaptive_bias_alpha_bias": 0.6,
        "restart_log": False,
        "new_log_name": ""
    })
    
    #manage_online_reconfiguration(configuration["data"], sionna_structure, is_manual_override=True)

    if sionna_structure["bandwidth"] is None:
        print("     [WARNING] Bandwidth not set. Defaulting to 100 MHz.")
        sionna_structure["bandwidth"] = 100e6

    if sionna_structure["frequency"] is None:
        print("     [WARNING] Frequency not set. Defaulting to 28 GHz.")
        sionna_structure["frequency"] = 28e9

    print(f"    [INFO] Setup procedure complete.")

    return sionna_structure