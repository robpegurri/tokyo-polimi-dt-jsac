import socket
from antennas.custom_antenna import extract_custom_pattern
from sionna.rt import PathSolver, Camera, PlanarArray, load_scene, load_mesh, SceneObject, ITURadioMaterial
#from core.rt import manage_online_reconfiguration
from core.filters import RSSIKalmanFilter, AdaptiveBiasFilter

sionna_structure = dict()
ray_tracing_time_ms = 0
frame_num = 0

sionna_structure["run_type"] = "real-time" # or "simulation"

def setup_scene(file_name, frequency, bandwidth):
    # Import scene
    sionna_structure["scene"] = load_scene(filename=file_name, merge_shapes=True, merge_shapes_exclude_regex="car")

    # Set propagation settings
    sionna_structure["scene"].frequency = frequency
    sionna_structure["frequency"] = frequency
    sionna_structure["scene"].bandwidth = bandwidth
    sionna_structure["bandwidth"] = bandwidth

    return sionna_structure["scene"]


def setup_antennas(transmitters, receivers,
                   num_rows=1, num_cols=1, vertical_spacing=0.5, horizontal_spacing=0.5, 
                   pattern="dipole", polarization="VH", elevation_csv=None, azimuth_csv=None):

    sionna_structure["transmitters"] = transmitters
    sionna_structure["receivers"] = receivers

    # Custom antenna pattern - Panasonic 60 GHz WiGig RSU
    if pattern == "panasonic_wigig_rsu":
        if elevation_csv is None or azimuth_csv is None:
            print("     [ERROR] Custom pattern selected but elevation or azimuth CSV files not provided.")
        else:
            extract_custom_pattern(elevation_csv=elevation_csv, azimuth_csv=azimuth_csv)

        sionna_structure["planar_array"] = PlanarArray(num_rows=num_rows, num_cols=num_cols, vertical_spacing=vertical_spacing, horizontal_spacing=horizontal_spacing, pattern="panasonic_wigig_rsu", elevation_csv=elevation_csv, azimuth_csv=azimuth_csv)
   
    else:
        sionna_structure["planar_array"] = PlanarArray(num_rows=num_rows, num_cols=num_cols, vertical_spacing=vertical_spacing, horizontal_spacing=horizontal_spacing, pattern=pattern, polarization=polarization)

    return


def set_antenna_displacement(car_id, displacement):

    if "antenna_displacement" not in sionna_structure:
        sionna_structure["antenna_displacement"] = {}

    sionna_structure["antenna_displacement"][car_id] = displacement
    return


def set_tx_power(car_id, tx_power_dbm):
    if "tx_powers" not in sionna_structure:
        sionna_structure["tx_powers"] = {}

    sionna_structure["tx_powers"][car_id] = tx_power_dbm
    return


def add_network_object(id, mesh_path=None, antenna_displacement=None, tx_power_dbm=None):

    scene = sionna_structure["scene"]

    if scene.get(f"obj_{id}") is not None:
        print(f"Object {id} (obj_{id}) already exists in the scene.")
        return scene.get(f"obj_{id}")
    
    mesh = load_mesh(mesh_path)
    set_antenna_displacement(id, antenna_displacement)

    car_obj = SceneObject(mi_mesh=mesh,
                          name=f"obj_{id}",
                          radio_material=ITURadioMaterial(f"itu_metal_{id}",
                                                        "metal",
                                                        thickness=0.01,
                                                        color=(0.8, 0.1, 0.1)))
    scene.edit(add=car_obj)

    # Set the car transmit power
    set_tx_power(id, tx_power_dbm)

    return car_obj

def add_tree(id=None, mesh_path=None, position=None):

    tree_mesh = load_mesh(mesh_path)
    tree_obj = SceneObject(mi_mesh=tree_mesh,
                        name=f"tree_{id}",
                        radio_material=ITURadioMaterial(f"itu_wood_{id}",
                                                    "wood",
                                                    thickness=0.01,
                                                    color=(0.6, 0.3, 0.1)))
    sionna_structure["scene"].edit(add=tree_obj)

    x = position[0]
    y = position[1]
    z = position[2]

    sionna_structure["scene"].get(f"tree_{id}").position = [x, y, z]

    return

def configure_rt(verbose=False,
                 time_checker=False,
                 rt_max_depth=5,
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
    
    sionna_structure["verbose"] = verbose
    sionna_structure["time_checker"] = time_checker

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

def configure_filters(transmitters, 
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
        print(f"Expecting UDP messages from Tokyo Digital Twin on UDP/{port}")
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

    print(f'Setup complete. Working at {sionna_structure["scene"].frequency / 1e9} GHz, bandwidth {sionna_structure["scene"].bandwidth / 1e6} MHz.')

    return sionna_structure