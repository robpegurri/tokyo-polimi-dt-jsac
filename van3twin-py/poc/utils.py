import math
import numpy as np
import time

def move_object(ref_obj_id=None, position=None, heading_angle=None, velocity=None, sionna_structure=None):

    '''
    Apply motion to n object and corresponding antennas mounted on it.

    Parameters:
    - ref_obj_id: the reference numerical object ID
    - position: new position of the object [x, y, z]
    - angle: heading angle (in degrees)
    - velocity: magnitude of the speed vector (for doppler)
    - sionna_structure: the global structure containing the scene and object information
    '''

    scene = sionna_structure["scene"]
    verbose = sionna_structure["verbose"]
    time_checker = sionna_structure["time_checker"]

    if time_checker:
        start_time = time.time() * 1000

    # Note: heading_angle arrives in the form of a heading, meaning that:
    # 0 = North, 90 = East, 180 = South, 270 = West
    # Sionna coordinates are:
    # 0 = East, 90 = North, 180 = West, 270 = South
    sionna_angle = (-heading_angle + 90) % 360 # This works perfectly
    # HOWEVER my object meshes have wrong orientation, so we need to apply a +90° rotation to align the heading with the movement direction
    car_angle = sionna_angle + 90
    car_angle_rad = math.radians(car_angle)
    # Antennas are okay, no rotation is needed like for the cars
    antenna_angle = sionna_angle
    antenna_angle_rad = math.radians(antenna_angle)

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
                new_position = [position[0] + antenna["displacement"][0], 
                                position[1] + antenna["displacement"][1], 
                                position[2] + antenna["displacement"][2]]
                antenna_object.position = new_position
                
                # Car heading update, need to update its global orientation too
                original = sionna_structure["object_and_antennas"][ref_obj_id][antenna["ant_id"]]["orientation"]
                sionna_structure["object_and_antennas"][ref_obj_id][antenna["ant_id"]]["orientation"] = [antenna_angle_rad, original[1], original[2]]

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
                        #peer_antenna_object = scene.get(f"ant_{antenna['peer_antenna_id']}")
                        # Apply to the current antenna...
                        #antenna_object.look_at(peer_antenna_object)
                        point_toward_peer(antenna["ant_id"], antenna["peer_antenna_id"], sionna_structure)
                        # ... and to the peer antenna to maintain alignment
                        point_toward_peer(antenna["peer_antenna_id"], antenna["ant_id"], sionna_structure)
                        #peer_antenna_object.look_at(antenna_object)
                        
                        if verbose:
                            print(f"     [DEBUG] Applied beamforming to ant_{antenna['ant_id']} and its peer ant_{antenna['peer_antenna_id']}")
                    else:
                        if verbose:
                            print(f"     [DEBUG] Out of beamforming range for ant_{antenna['ant_id']} and its peer ant_{antenna['peer_antenna_id']}")
                            antenna_object.orientation = [antenna_angle_rad, 0, 0]

                    if time_checker:
                        end_time_bf = time.time() * 1000
                        print(f"     [TIME] Time taken for beamforming check and orientation update: {end_time_bf - start_time_bf:.4f} ms")
                        
                else:
                    if verbose:
                        print(f"     [INFO] Applying fixed orientation for antenna {antenna['ant_id']} with angle offset {antenna_angle} degrees.")
                    antenna_object.orientation = [antenna_angle_rad, 0, 0]

    if time_checker:
        end_time = time.time() * 1000
        print(f"    [TIME] Time taken for location updates: {end_time - start_time:.4f} ms")

    return


def point_toward_peer(from_id, to_id, sionna_structure):
    '''
    Rotate an antenna toward its peer along its sweep plane only.
    - Horizontally mounted antennas: update azimuth only (orientation[0])
    - Vertically mounted antennas: update elevation only (orientation[1])
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


def can_beamform(ant_1_id, ant_2_id, sionna_structure, beam_range=60):
    
    def check_direction(from_id, to_id):
        # Find antenna data
        for obj_id, antennas in sionna_structure["object_and_antennas"].items():
            if from_id in antennas:
                ant_data = antennas[from_id]
                break
        
        p_from = np.array(sionna_structure["scene"].get(f"ant_{from_id}").position)
        p_to = np.array(sionna_structure["scene"].get(f"ant_{to_id}").position)
        heading = math.degrees(ant_data["orientation"][0])
        target_az = math.degrees(math.atan2(p_to[1] - p_from[1], p_to[0] - p_from[0]))
        
        # Normalize angle diff to [-180, 180]
        rel_az = (target_az - heading + 180) % 360 - 180
        return abs(rel_az) <= beam_range
        
    return check_direction(ant_1_id, ant_2_id) and check_direction(ant_2_id, ant_1_id)