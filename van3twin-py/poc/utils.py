import math
import numpy as np
import time

def move_object(ref_obj_id=None, position=None, ref_system="external", heading_angle=None, velocity=None, sionna_structure=None):
    '''
    Apply motion to a dynamic object mesh and to the corresponding antennas mounted on it. 
    
    Takes the following parameters as input:
        - **ref_obj_id**: the reference numerical object ID
        - **position**: new position of the object [x, y, z]
        - *ref_system*: the position reference coordinate system ("sionna" or "external", default is "external").
        - **heading_angle**: heading angle (in degrees)
        - **velocity**: magnitude of the speed vector (for doppler)
        - **sionna_structure**: the global structure containing the scene and object information, returned by _poc.startup()_

    And performs the following steps:
        1. Update the position and orientation of the object mesh (e.g., a car) in the Sionna RT scene
        2. Invalidate the cached rays in sionna_structure to trigger recomputation with the new positions
        3. Update the position, velocity and orientation of the antennas mounted on the object
        4. If perfect beamforming is enabled, check if the antenna can still beamform with its peer after the movement and update the orientation accordingly
    '''

    scene = sionna_structure["scene"]
    verbose = sionna_structure["verbose"]
    time_checker = sionna_structure["time_checker"]

    if time_checker:
        start_time = time.time() * 1000

    # Note: heading_angle arrives in the form of a heading, meaning that:
    # 0 = North, 90 = East, 180 = South, 270 = West (clockwise rotation)
    # Sionna coordinates are:
    # 0 = East, 90 = North, 180 = West, 270 = South (counterclockwise rotation)
    sionna_angle = (-heading_angle + 90) % 360  # This works perfectly
    # HOWEVER my object meshes have wrong orientation, so we need to apply a +90° rotation to align the heading with the movement direction
    car_angle = sionna_angle + 90
    car_angle_rad = math.radians(car_angle)
    # Antennas are okay, no rotation is needed like for the cars
    antenna_angle = sionna_angle
    antenna_angle_rad = math.radians(antenna_angle)

    if ref_system == "external":
        # Convert external position to Sionna RT coordinates using the offset
        offset = sionna_structure.get("coordinate_offset", [0, 0])
        position = [position[0] + offset[0], position[1] + offset[1], position[2]]

    # Move the object mesh
    obj = scene.get(f"obj_{ref_obj_id}")
    if obj is None:
        print(f"     [ERROR] Object {ref_obj_id} (obj_{ref_obj_id}) not found in the scene.")
        return
    obj.position = position
    # Car meshes are created with opposite orientation: we need to apply a 180° rotation to align the heading with the movement direction
    obj.orientation = [car_angle_rad - math.pi, 0, 0]

    # Invalidate cached paths
    sionna_structure["rays_cache"] = {}
    if verbose:
        print(f"     [DEBUG] Invalidated rays cache due to movement of object {ref_obj_id}.")

    # Move the antennas mounted on the object
    if ref_obj_id in sionna_structure["object_and_antennas"]:
        antennas = sionna_structure["object_and_antennas"][ref_obj_id]
        for antenna in antennas.values():
            antenna_object = scene.get(f"ant_{antenna['ant_id']}")

            if antenna_object is not None:
                # Rotate XY displacement by the car's current heading angle to keep the antenna
                # correctly positioned relative to the car body when the car turns.
                cos_a = math.cos(antenna_angle_rad)
                sin_a = math.sin(antenna_angle_rad)
                dx, dy, dz = antenna["displacement"]
                new_position = [
                    position[0] + cos_a * dx - sin_a * dy,
                    position[1] + sin_a * dx + cos_a * dy,
                    position[2] + dz
                ]
                antenna_object.position = new_position

                # Update world-frame orientation: car heading + antenna's original body-frame azimuth offset.
                # Use initial_orientation (never overwritten) so the offset is preserved across successive turns.
                initial_orient = sionna_structure["object_and_antennas"][ref_obj_id][antenna["ant_id"]]["initial_orientation"]
                new_az = antenna_angle_rad + initial_orient[0]
                sionna_structure["object_and_antennas"][ref_obj_id][antenna["ant_id"]]["orientation"] = [new_az, initial_orient[1], initial_orient[2]]

                v_x = velocity * math.sin(antenna_angle_rad)
                v_y = velocity * math.cos(antenna_angle_rad)
                v_z = 0
                antenna_object.velocity = [v_x, v_y, v_z]

                if sionna_structure["simulate_perfect_beamforming"]:
                    if time_checker:
                        start_time_bf = time.time() * 1000 if time_checker else None
                    
                    can_bf = can_beamform(antenna["ant_id"], antenna["peer_antenna_id"], sionna_structure)

                    if verbose:
                        print(f"     [DEBUG] can_beamform result: {can_bf}")
                    
                    if can_bf:
                        if sionna_structure["use_look_at_ideal_pointing"]:
                            peer_antenna_object = scene.get(f"ant_{antenna['peer_antenna_id']}")
                            # Apply to the current antenna...
                            antenna_object.look_at(peer_antenna_object)
                            # ... and to the peer antenna to maintain alignment
                            peer_antenna_object.look_at(antenna_object)
                        else:
                            # Apply to the current antenna...
                            point_toward_peer(antenna["ant_id"], antenna["peer_antenna_id"], sionna_structure)
                            # ... and to the peer antenna to maintain alignment
                            point_toward_peer(antenna["peer_antenna_id"], antenna["ant_id"], sionna_structure)
                        
                        if verbose:
                            print(f"     [DEBUG] Applied beamforming to ant_{antenna['ant_id']} and its peer ant_{antenna['peer_antenna_id']}")
                    else:
                        if verbose:
                            print(f"     [DEBUG] Out of beamforming range for ant_{antenna['ant_id']} and its peer ant_{antenna['peer_antenna_id']}.")
                        antenna_object.orientation = [antenna_angle_rad + initial_orient[0], initial_orient[1], initial_orient[2]]

                    if time_checker:
                        end_time_bf = time.time() * 1000
                        print(f"     [TIME] Time taken for beamforming check and orientation update: {end_time_bf - start_time_bf:.4f} ms")
                        
                else:
                    if verbose:
                        print(f"     [INFO] Applying fixed orientation for antenna {antenna['ant_id']} with angle offset {antenna_angle} degrees.")
                    antenna_object.orientation = [antenna_angle_rad + initial_orient[0], initial_orient[1], initial_orient[2]]

    if time_checker:
        end_time = time.time() * 1000
        print(f"    [TIME] Time taken for location updates: {end_time - start_time:.4f} ms")

    return


def point_toward_peer(from_id, to_id, sionna_structure):
    '''
    Rotates an antenna toward its peer along its sweep plane only.
        - **Horizontally mounted antennas**: update azimuth only (orientation[0])
        - **Vertically mounted antennas**: update elevation only (orientation[1])
    '''
    scene = sionna_structure["scene"]

    for antennas in sionna_structure["object_and_antennas"].values():
        if from_id in antennas:
            ant_data = antennas[from_id]
            break

    ant_obj = scene.get(f"ant_{from_id}")
    peer_obj = scene.get(f"ant_{to_id}")

    p_from = np.array(ant_obj.position)
    p_to   = np.array(peer_obj.position)
    dx = p_to[0] - p_from[0]
    dy = p_to[1] - p_from[1]
    dz = p_to[2] - p_from[2]

    az, el, roll = ant_data["orientation"]

    if ant_data["mounted_vertically"]:
        # Beam sweeps vertically: update elevation, keep azimuth
        el = -math.atan2(dz, math.sqrt(dx**2 + dy**2))
    else:
        # Beam sweeps horizontally: update azimuth, keep elevation
        az = math.atan2(dy, dx)

    ant_obj.orientation = [float(az), float(el), float(roll)]


def can_beamform(ant_1_id, ant_2_id, sionna_structure):
    '''
    Checks if two antennas can beamform with each other based on their orientation and the angle to their peer. Takes into account the beam sweeping angle defined in the setup.
    Returns **True** if both antennas can align with each other (i.e., the angle between their orientations is within the beam sweeping angle), **False** otherwise.
    Note: this function assumes that the antennas are already mounted on their respective objects and that the object positions and orientations are updated, so it should be called after move_object() when simulating perfect beamforming.
    '''
    
    def check_direction(from_id, to_id):
        # Find antenna data
        for obj_id, antennas in sionna_structure["object_and_antennas"].items():
            if from_id in antennas:
                ant_data = antennas[from_id]
                break

        p_from = np.array(sionna_structure["scene"].get(f"ant_{from_id}").position)
        p_to = np.array(sionna_structure["scene"].get(f"ant_{to_id}").position)
        dx = p_to[0] - p_from[0]
        dy = p_to[1] - p_from[1]
        dz = p_to[2] - p_from[2]

        if ant_data["mounted_vertically"]:
            # Beam sweeps in elevation: check if peer is within elevation sweep range
            target_el = math.degrees(-math.atan2(dz, math.sqrt(dx**2 + dy**2)))
            current_el = math.degrees(ant_data["orientation"][1])
            rel_el = target_el - current_el
            return abs(rel_el) <= sionna_structure["beam_sweeping_angle"]
        else:
            # Beam sweeps in azimuth: check if peer is within azimuth sweep range
            heading = math.degrees(ant_data["orientation"][0])
            target_az = math.degrees(math.atan2(dy, dx))
            # Normalize angle diff to [-180, 180]
            rel_az = (target_az - heading + 180) % 360 - 180
            return abs(rel_az) <= sionna_structure["beam_sweeping_angle"]
        
    # It must be true for both
    return check_direction(ant_1_id, ant_2_id) and check_direction(ant_2_id, ant_1_id)