import json
import socket
import time
import math
import csv
import os
from antennas.custom_antenna import extract_custom_pattern

from sionna.rt import PathSolver, Camera, PlanarArray, load_scene
from core.rt import manage_online_reconfiguration

sionna_structure = dict()
ray_tracing_time_ms = 0
frame_num = 0

def startup():

    # Scenario
    file_name = "/home/rpegurri/Tokyo NDT Integration/tokyo-poc-notrees/tokyo-poc-notrees.xml"
    frequency = 60e9
    bandwidth = 1e9
    tx_power = 18
    correction = 11

    # Antennas per car
    sionna_structure["transmitters"] = [2, 3] # Mark the cars with transmitters on board
    sionna_structure["receivers"] = [1, 2] # Mark the cars with receivers on board

    # Integration
    port = 35944

    # Ray tracing
    position_threshold = 0.5 # unused here
    angle_threshold = 30 # unused here
    max_depth = 30
    max_num_paths_per_src = 1e10
    samples_per_src = 1e10
    los = True
    specular_reflection = True
    diffuse_reflection = True
    refraction = True
    seed = 42
    syntetic_array = False
    diffraction = True
    corner_diffraction = True

    # Other
    verbose = True
    time_checker = False
    
    sionna_structure["verbose"] = verbose
    sionna_structure["time_checker"] = time_checker

    # Load scene and configure radio settings
    sionna_structure["scene"] = load_scene(filename=file_name, merge_shapes=True, merge_shapes_exclude_regex="car")
    sionna_structure["scene"].frequency = frequency
    sionna_structure["scene"].bandwidth = bandwidth

    # Edit here the settings for the antennas
    element_spacing = 0.5 * (3e8 / frequency)

    # Custom antenna pattern - Panasonic 60 GHz WiGig RSU
    extract_custom_pattern(elevation_csv="elevation_beam_16.csv", azimuth_csv="azimuth_beam_16.csv")
    #sionna_structure["planar_array"] = PlanarArray(num_rows=1, num_cols=1, vertical_spacing=element_spacing, horizontal_spacing=element_spacing, pattern="panasonic_wigig_rsu", elevation_csv="elevation_beam_16.csv", azimuth_csv="azimuth_beam_16.csv")
    sionna_structure["planar_array"] = PlanarArray(num_rows=1, num_cols=1, vertical_spacing=element_spacing, horizontal_spacing=element_spacing, pattern="tr38901", polarization="VH") # Uncomment to use pre-defined antenna pattern if the Panasonic one has issues

    # Set here the relative position of the antenna w.r.t. the car position
    sionna_structure["antenna_displacement"] = {}
    sionna_structure["antenna_displacement"][1] = [-0.941999, 0.157001, 0.791505] # TOYOTA COMS
    sionna_structure["antenna_displacement"][2] = [-0.281679, 0.477371, 0.975445] # TOYOTA ESTIMA
    sionna_structure["antenna_displacement"][3] = [0.280998, -0.0470009, 0.818048] # CARRETTO POVERETTO

    # Scenario update frequency settings (not used for the PoC)
    sionna_structure["position_threshold"] = position_threshold
    sionna_structure["angle_threshold"] = angle_threshold

    # Powers
    sionna_structure["tx_power"] = tx_power
    sionna_structure["correction"] = correction

    # Ray tracing settings
    sionna_structure["path_solver"] = PathSolver()
    sionna_structure["synthetic_array"] = syntetic_array
    sionna_structure["max_depth"] = max_depth
    sionna_structure["max_num_paths_per_src"] = max_num_paths_per_src
    sionna_structure["samples_per_src"] = samples_per_src
    sionna_structure["los"] = los
    sionna_structure["specular_reflection"] = specular_reflection
    sionna_structure["diffuse_reflection"] = diffuse_reflection
    sionna_structure["refraction"] = refraction
    sionna_structure["diffraction"] = diffraction
    sionna_structure["corner_diffraction"] = corner_diffraction
    sionna_structure["seed"] = seed

    # Caches
    sionna_structure["path_loss_cache"] = {}
    sionna_structure["delay_cache"] = {}
    sionna_structure["last_path_loss_requested"] = None

    # Set up UDP socket
    udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp_socket.bind(("0.0.0.0", port))  # External server configuration
    if verbose:
        print(f"Expecting UDP messages from Tokyo Digital Twin on UDP/{port}")

    sionna_structure["udp_socket"] = udp_socket

    # Location databases and caches
    sionna_structure["SUMO_live_location_db"] = {}  # Real-time vehicle locations in SUMO
    sionna_structure["sionna_location_db"] = {}  # Vehicle locations in Sionna
    sionna_structure["rays_cache"] = {}  # Cache for ray information
    sionna_structure["path_loss_cache"] = {}  # Cache for path loss values

    # Kalman filter settings
    sionna_structure["use_kalman_filter"] = False
    sionna_structure["kalman_process_var"] = 0.1
    sionna_structure["kalman_meas_var"] = 4.0
    sionna_structure["kalman_rt_var"] = 25.0

    # Adaptive bias filter settings
    sionna_structure["use_adaptive_bias_filter"] = True
    sionna_structure["adaptive_bias_alpha_signal"] = 0.1
    sionna_structure["adaptive_bias_alpha_bias"] = 0.05

    # Monte Carlo settings
    sionna_structure["montecarlo_realizations"] = 5
    sionna_structure["montecarlo_max_position_jitter"] = 0.05

    # Remote log settings
    sionna_structure["restart_log"] = None
    sionna_structure["new_log_name"] = None

    sionna_structure["my_cam"] = Camera(position=[-50,30,100], look_at=[-39.4388, 45.5538, 0.541952])

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
    
    manage_online_reconfiguration(configuration["data"], sionna_structure, is_manual_override=True)

    print(f"Setup complete. Working at {frequency / 1e9} GHz, bandwidth {bandwidth / 1e6} MHz.")

    return sionna_structure