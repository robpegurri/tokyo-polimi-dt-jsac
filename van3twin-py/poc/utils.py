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

    # Note: heading_angle arrives in the form of a heading (0 = facing north) but in Sionna, 0 faces east
    car_angle = heading_angle + 90
    car_angle_rad = np.radians(car_angle)

    antenna_angle = heading_angle
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
                        peer_antenna_object = scene.get(f"ant_{antenna['peer_antenna_id']}")
                        pos_diff = np.array(peer_antenna_object.position) - np.array(antenna_object.position)
                        antenna_heading = float(np.arctan2(pos_diff[0], pos_diff[1]))
                        
                        # Apply to the current antenna...
                        antenna_object.orientation = [antenna_heading, antenna["orientation"][1], antenna["orientation"][2]]
                        # ... and to the peer antenna to maintain alignment
                        peer_antenna_object.orientation = [antenna_heading + np.pi, peer_antenna_object.orientation[1], peer_antenna_object.orientation[2]]
                        
                        if verbose:
                            print(f"     [DEBUG] Applied beamforming: ant_{antenna['ant_id']} heading={np.degrees(antenna_heading):.2f}°, ant_{antenna['peer_antenna_id']} heading={np.degrees(antenna_heading + np.pi):.2f}°")
                    else:
                        if verbose:
                            print(f"     [DEBUG] Out of beamforming range for ant_{antenna['ant_id']} -> ant_{antenna['peer_antenna_id']}")
                        
                else:
                    if verbose:
                        print(f"     [INFO] Applying fixed orientation for antenna {antenna['ant_id']} with angle offset {antenna_angle} degrees.")
                    antenna_object.orientation = np.array([antenna_angle_rad, 0, 0])

    return


def can_beamform(ant_1_id, ant_2_id, sionna_structure, beam_range=360):
    
    def check_direction(from_id, to_id):
        # Find antenna data
        for obj_id, antennas in sionna_structure["object_and_antennas"].items():
            if from_id in antennas:
                ant_data = antennas[from_id]
                break
        
        pos_from = np.array(sionna_structure["scene"].get(f"ant_{from_id}").position)
        pos_to = np.array(sionna_structure["scene"].get(f"ant_{to_id}").position)
        heading = np.degrees(ant_data["orientation"][0])
        target_az = np.degrees(np.arctan2(pos_to[0] - pos_from[0], pos_to[1] - pos_from[1]))
        
        # Normalize angle diff to [-180, 180]
        rel_az = (target_az - heading + 180) % 360 - 180
        return abs(rel_az) <= beam_range
        
    return check_direction(ant_1_id, ant_2_id) and check_direction(ant_2_id, ant_1_id)