from sionna.rt import load_mesh, SceneObject, ITURadioMaterial, Receiver, Transmitter
import numpy as np

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

    # Note: heading_angle arrives in the form of a heading, meaning that:
    # 0 = North, 90 = East, 180 = South, 270 = West
    # Sionna coordinates are:
    # 0 = East, 90 = North, 180 = West, 270 = South
    sionna_angle = (-heading_angle + 90) % 360 # This works perfectly
    # HOWEVER object meshes have wrong orientation, so we need to apply a +90° rotation to align the heading with the movement direction
    car_angle = sionna_angle + 90
    car_angle_rad = np.radians(car_angle)
    # Antennas are okay, no rotation is needed like for the cars
    antenna_angle = sionna_angle
    antenna_angle_rad = np.radians(antenna_angle)

    # Move the object mesh
    obj = scene.get(f"obj_{ref_obj_id}")
    if obj is None:
        print(f"     [ERROR] Object {ref_obj_id} (obj_{ref_obj_id}) not found in the scene.")
        return
    obj.position = position
    # Car meshes are created with opposite orientation: we need to apply a 180° rotation to align the heading with the movement direction
    obj.orientation = np.array([car_angle_rad - np.pi, 0, 0])

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

                v_x = velocity * np.sin(antenna_angle_rad)
                v_y = velocity * np.cos(antenna_angle_rad)
                v_z = 0
                antenna_object.velocity = np.array([v_x, v_y, v_z])

                if sionna_structure["simulate_perfect_beamforming"]:
                    
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
                            antenna_object.orientation = np.array([antenna_angle_rad, 0, 0])
                        
                else:
                    if verbose:
                        print(f"     [INFO] Applying fixed orientation for antenna {antenna['ant_id']} with angle offset {antenna_angle} degrees.")
                    antenna_object.orientation = np.array([antenna_angle_rad, 0, 0])

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

    pos_from = np.array(ant_obj.position)
    pos_to   = np.array(peer_obj.position)
    dx, dy, dz = pos_to - pos_from

    az, el, roll = ant_data["orientation"]

    if ant_data["mounted_vertically"]:
        # Beam sweeps vertically: update elevation, keep azimuth
        el = -np.arctan2(dz, np.sqrt(dx**2 + dy**2))
    else:
        # Beam sweeps horizontally: update azimuth, keep elevation
        az = np.arctan2(dy, dx)

    ant_obj.orientation = np.array([float(az), float(el), float(roll)])


def can_beamform(ant_1_id, ant_2_id, sionna_structure, beam_range=60):
    
    def check_direction(from_id, to_id):
        # Find antenna data
        for obj_id, antennas in sionna_structure["object_and_antennas"].items():
            if from_id in antennas:
                ant_data = antennas[from_id]
                break
        
        pos_from = np.array(sionna_structure["scene"].get(f"ant_{from_id}").position)
        pos_to = np.array(sionna_structure["scene"].get(f"ant_{to_id}").position)
        heading = np.degrees(ant_data["orientation"][0])
        target_az = np.degrees(np.arctan2(pos_to[1] - pos_from[1], pos_to[0] - pos_from[0]))
        
        # Normalize angle diff to [-180, 180]
        rel_az = (target_az - heading + 180) % 360 - 180
        return abs(rel_az) <= beam_range
        
    return check_direction(ant_1_id, ant_2_id) and check_direction(ant_2_id, ant_1_id)