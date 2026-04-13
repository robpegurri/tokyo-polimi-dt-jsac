import socket
from antennas.custom_antenna import extract_custom_pattern
from sionna.rt import PathSolver, Camera, PlanarArray, load_scene, load_mesh, SceneObject, ITURadioMaterial, Receiver, Transmitter
from poc.filters import MovingAverageFilter
import numpy as np
import math
import csv
import time
import os

sionna_structure = dict()
ray_tracing_time_ms = 0
frame_num = 0

sionna_structure["run_type"] = "real-time" # or "simulation"

def setup_scenario(file_name, frequency, bandwidth, verbose=False, time_checker=False):
    '''
    Sets up the Sionna RT scene by loading the 3D model and applying the specified frequency and bandwidth. 
    Also initializes verbose and time checker settings in the sionna_structure for later use in other functions.

    Takes the following parameters as input:
        - **file_name**: the path to .xml file for the Mitsuba3 scenario
        - **frequency**: the carrier frequency in Hz (e.g., 28e9 for 28 GHz)
        - **bandwidth**: the bandwidth in Hz (e.g., 100e6 for 100 MHz)
        - **verbose**: whether to enable verbose logging (default: False)
        - **time_checker**: whether to enable timing measurements for performance analysis (default: False)

    Returns the loaded _sionna.rt.Scene_ object.
    '''
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


def setup_coordinate_systems(ref_sionna_x=162.396, ref_sionna_y=85.782,
                             ref_external_x=-13524.5, ref_external_y=-43817.64):
    '''
    Sets up the coordinate systems by defining the offset between the Sionna RT coordinates and the external coordinates 
    (e.g., Tokyo Mobility DT) based on a reference point. This allows to convert positions between the two coordinate systems.
    
    For the _ookayama_full_flat.xml_ and the Tokyo Mobility DT, taking as reference the righ corner of the porch of the main 
    building (facing north)

            North (toward trees)
           - - - - - - - - - -  X (height around 7 meters)
          |                     |               
          |                     |               Sionna RT = (162.396, 85.782, 7.310)
    - - - - - - - - - - - - - - - - - -         Tokyo Mobility DT = (-13524.5, z=3817.64)
                  South
    
    '''

    off_x = ref_sionna_x - ref_external_x # Tokyo Mobility DT calls this "x"
    off_y = ref_sionna_y - ref_external_y # Tokyo Mobility DT calls this "z"

    # Usage: sionna_position = (external_x + off_x, external_y + off_y, external_z)
    sionna_structure["coordinate_offset"] = [off_x, off_y]

    return


def setup_antenna_type(transmitters, receivers,
                       num_rows=1, num_cols=1, vertical_spacing=0.5, horizontal_spacing=0.5, 
                       pattern="dipole", polarization="VH", elevation_csv=None, azimuth_csv=None,
                       simulate_perfect_beamforming=True, use_look_at_ideal_pointing=False, beam_sweeping_angle=60):
    '''
    Sets up the antenna type and parameters for the transmitters and receivers in the scenario.
    
    Takes the following parameters as input:
        - **transmitters**: list of antenna IDs to be set as transmitters (e.g., [30, 31, 5, 6])
        - **receivers**: list of antenna IDs to be set as receivers (e.g., [1, 2, 40, 7])
        - **num_rows**: number of rows in the planar array (default: 1)
        - **num_cols**: number of columns in the planar array (default: 1)
        - **vertical_spacing**: vertical spacing between elements in wavelengths (default: 0.5)
        - **horizontal_spacing**: horizontal spacing between elements in wavelengths (default: 0.5)
        - **pattern**: antenna pattern to use (default: "dipole", use "load_custom" for custom pattern defined by _elevation_csv_ and _azimuth_csv_)
        - **polarization**: polarization of the antenna (default: "VH", other options: "H", "V")
        - **elevation_csv**: path to CSV file containing elevation pattern values (required if pattern is "load_custom")
        - **azimuth_csv**: path to CSV file containing azimuth pattern values (required if pattern is "load_custom")
        - **simulate_perfect_beamforming**: whether to simulate perfect beamforming by dynamically updating antenna orientations to point toward their peer (default: True)
        - **use_look_at_ideal_pointing**: whether to use the look_at() property of the Radio Device object to point antennas toward their ideal peer position for perfect beamforming simulation, instead of manually calculating the angles on the sole sweeping plane (default: False)
        - **beam_sweeping_angle**: the beam sweeping angle in degrees defined as [-beam_sweeping_angle, beam_sweeping_angle] used for perfect beamforming simulation (default: 60, meaning [-60°, +60°])
        '''

    sionna_structure["transmitters"] = transmitters
    sionna_structure["receivers"] = receivers
    sionna_structure["simulate_perfect_beamforming"] = simulate_perfect_beamforming
    sionna_structure["use_look_at_ideal_pointing"] = use_look_at_ideal_pointing
    sionna_structure["beam_sweeping_angle"] = beam_sweeping_angle

    # Custom antenna pattern - Panasonic 60 GHz WiGig RSU
    if pattern == "load_custom":
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


def setup_wireless_links(wireless_links=None):
    '''
    Sets up the links between transmitters and receivers.

    Takes the following parameters as input:
        - **wireless_links**: list of tuples (tx_ant_id, rx_ant_id) representing the wireless links between transmitters and receivers
    '''

    # Safety check to ensure specified links are between defined transmitters and receivers
    for tx_id, rx_id in wireless_links:
        if tx_id not in sionna_structure["transmitters"]:
            print(f"     [ERROR] Tx antenna {tx_id} in wireless_links was not defined as a transmitter in setup_antenna_type()!")
            return
        if rx_id not in sionna_structure["receivers"]:
            print(f"     [ERROR] Rx antenna {rx_id} in wireless_links was not defined as a receiver in setup_antenna_type()!")
            return

    sionna_structure["links"] = wireless_links

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
                 rt_synthetic_array=True):
    '''
    Sets up the ray tracing parameters for the scenario.

    Takes the following parameters as input:
        - **rt_max_depth**: maximum ray tracing depth (default: 5)
        - **rt_max_num_paths_per_src**: maximum number of paths per source (default: 1e10)
        - **rt_samples_per_src**: number of samples per source (default: 1e10)
        - **rt_los**: whether to consider line-of-sight paths (default: True)
        - **rt_specular_reflection**: whether to consider specular reflection (default: True)
        - **rt_diffuse_reflection**: whether to consider diffuse reflection (default: True)
        - **rt_refraction**: whether to consider refraction (default: True)
        - **rt_diffraction**: whether to consider diffraction (default: False)
        - **rt_corner_diffraction**: whether to consider corner diffraction (default: False)
        - **rt_sbr_seed**: seed for the SBR (default: 42)
        - **rt_synthetic_array**: whether to use a synthetic array approximation (default: True)
    '''
    
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
                      use_moving_average_filter=False,
                      moving_average_window_size=10):
    
    if use_moving_average_filter == False:
        print("     [WARNING] No filter selected. RT predictions will be used as-is without any filtering.")
    
    sionna_structure["filters"] = {}
                
    if use_moving_average_filter:
        sionna_structure["use_moving_average_filter"] = True
        sionna_structure["moving_average_window_size"] = moving_average_window_size
        for tx in transmitters:
            for rx in receivers:
                if sionna_structure["verbose"]:
                    print(f"     [INFO] Setting up Moving Average Filter with window size {moving_average_window_size} for ('{tx}', '{rx}')")
                sionna_structure["filters"][(f"{tx}", f"{rx}")] = MovingAverageFilter(window_size=moving_average_window_size)
    return


def mount_antenna_on_object (ref_obj_id, ant_id, displacement, orientation, mounted_vertically=False, tx_power_dbm=None):
    '''
    Adds an antenna to the scenario and mounts it on a reference object (e.g., a car) with a specified displacement and orientation relative to the object's reference point, defined as 
    the position you can get from _scene.get(f"obj_{ref_obj_id}").position_.
    
    Takes the following parameters as input:
        - **ant_id**: the numerical antenna ID
        - **displacement**: the 3D displacement of the antenna from the reference point on the object `[dx, dy, dz]`
        - **orientation**: the orientation of the antenna relative to the object `[alpha, theta, phi]`
        - **mounted_vertically**: whether the antenna is mounted vertically or not (necessary for proper beam sweeping simulation, default: False, meaning the antenna is mounted horizontally with the main lobe sweeping in the horizontal plane parallel to the ground)
        - **tx_power_dbm**: the transmit power in dBm (required if the antenna is a transmitter)

    It results in the creation of the following structure in `sionna_structure`:

    ```python
    sionna_structure["object_and_antennas"] = {
        ref_obj_id: {
            ant_id: {
                "ant_id": ant_id,
                "peer_antenna_id": peer_antenna_id, # as defined with setup_wireless_links()
                "displacement": [dx, dy, dz],
                "orientation": [alpha, theta, phi],
                "tx_power_dbm": tx_power_dbm,
                "mounted_vertically": mounted_vertically
            },
            # ...
        },
        # ...
    }
    ```
    '''

    links = sionna_structure.get("links", [])
    peer_antenna_id = None
    for tx_id, rx_id in links:
        if ant_id == tx_id:
            print(f"     [INFO] Found peer antenna for Tx {ant_id} in wireless_links: its Rx is {rx_id}. Perfect beamforming simulation will be applied between these two antennas.")
            peer_antenna_id = rx_id
            break
        elif ant_id == rx_id:
            print(f"     [INFO] Found peer antenna for Rx {ant_id} in wireless_links: its Tx is {tx_id}. Perfect beamforming simulation will be applied between these two antennas.")
            peer_antenna_id = tx_id
            break

    # Safety checks
    if sionna_structure["simulate_perfect_beamforming"] and peer_antenna_id is None:
        print(f"     [ERROR] This antenna has no peer antenna defined in the wireless links. Check the wireless_links parameter in setup_wireless_links() to ensure all antennas have their peer defined for perfect beamforming simulation.")
        return
    
    if sionna_structure["simulate_perfect_beamforming"] == False and orientation is None:
        print(f"     [ERROR] Fixed antenna orientation must be specified for {ant_id} when not simulating perfect beamforming.")
        return

    if ant_id in sionna_structure["transmitters"] and tx_power_dbm is None:
        print(f"     [ERROR] {ant_id} is defined as a Transmitter: Tx power (dBm) must be provided!")
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
            "initial_orientation": list(orientation),  # body-frame original, never overwritten
            "orientation": list(orientation),          # current world-frame orientation, updated on each move
            "tx_power_dbm": tx_power_dbm,
            "mounted_vertically": mounted_vertically
        }

    if ant_id in sionna_structure["transmitters"]:
        scene.tx_array = sionna_structure["planar_array"]
        scene.add(Transmitter(f"ant_{ant_id}", position=ant_position, orientation=orientation, display_radius=0.3))

    if ant_id in sionna_structure["receivers"]:
        scene.rx_array = sionna_structure["planar_array"]
        scene.add(Receiver(f"ant_{ant_id}", position=ant_position, orientation=orientation, display_radius=0.3))


def add_object(ref_obj_id=None, mesh_path=None, position=None):
    '''
    Adds an object (e.g., a car or a RSU) to the scenario by loading its mesh and placing it at the specified position. 
    The object is identified by a reference ID that is used to link it to the antennas mounted on it for motion simulation.

    Takes the following parameters as input:
        - **ref_obj_id**: the reference numerical object ID
        - **mesh_path**: the path to the object's mesh file (e.g., .obj)
        - **position**: the initial position of the object in the scene [x, y, z]

    Returns the created _sionna.rt.SceneObject_ called **obj_{ref_obj_id}** (e.g., `obj_1`) representing the scene object.
    '''

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
    '''
    Adds a tree to the scenario by loading its mesh and placing it at the specified position. 
    The tree is identified by a reference ID.

    Takes the following parameters as input:
        - **ref_tree_id**: the reference numerical tree ID
        - **mesh_path**: the path to the tree's _.ply_ mesh file
        - **position**: the position of the tree in the scene [x, y, z]

    Creates a _sionna.rt.SceneObject_ called **tree_{ref_tree_id}** (e.g., `tree_1`) representing the tree with a radio material that simulates wood, and adds it to the scene.
    '''

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


def startup(port=None):
    '''
    Configures the initial settings for the communication with the Tokyo Digital Twin for the PoC application.

    Takes the following parameters as input:
        - **port**: the UDP port to listen to for incoming messages from the Tokyo Digital Twin

    Returns the global `sionna_structure` dictionary, necessary input for many other functions. 
    '''

    # Integration
    if port is None:
        print("     [ERROR] UDP port must be specified.")
        return
    
    sionna_structure["position_threshold"] = 0.01
    sionna_structure["angle_threshold"] = 0.01

    # Caches
    sionna_structure["path_loss_cache"] = {}
    sionna_structure["delay_cache"] = {}
    sionna_structure["last_path_loss_requested"] = None

    # Filter data
    sionna_structure["use_filter"] = None
    sionna_structure["filter_window_size"] = None

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

    # Handle logging
    t_for_log = math.trunc(time.time())
    sionna_structure["log_file"] = f"tokyo-poc-sionna-log_{t_for_log}.csv"
    log_columns = [
        "local_unix_timestamp", "dt_current_clock", "prediction_horizon",
        "json_payload", "json_reply",
        "car_1_predicted_x", "car_1_predicted_y", "car_1_predicted_yaw",
        "car_2_predicted_x", "car_2_predicted_y", "car_2_predicted_yaw",
        "raw_predicted_rssi_5_2", "raw_predicted_rssi_6_40", "raw_predicted_rssi_30_1", "raw_predicted_rssi_31_7",
        "filtered_predicted_rssi_5_2", "filtered_predicted_rssi_6_40", "filtered_predicted_rssi_30_1", "filtered_predicted_rssi_31_7",
        "los_5_2", "los_6_40", "los_30_1", "los_31_7",
        "can_bf_5_2", "can_bf_6_40", "can_bf_30_1", "can_bf_31_7",
        "location_update_time_ms", "rssi_prediction_time_ms", "total_elapsed_time_ms"
    ]

    sionna_structure["csv_log_columns"] = log_columns

    if not os.path.exists(sionna_structure["log_file"]):
        with open(sionna_structure["log_file"], mode="w", newline="") as file:
            writer = csv.writer(file)
            writer.writerow(log_columns)


    if sionna_structure["bandwidth"] is None:
        print("     [WARNING] Bandwidth not set. Defaulting to 100 MHz.")
        sionna_structure["bandwidth"] = 100e6

    if sionna_structure["frequency"] is None:
        print("     [WARNING] Frequency not set. Defaulting to 28 GHz.")
        sionna_structure["frequency"] = 28e9

    print(f"    [INFO] Setup procedure complete.")

    return sionna_structure