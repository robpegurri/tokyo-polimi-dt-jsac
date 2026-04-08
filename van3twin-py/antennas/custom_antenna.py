import numpy as np
from scipy.interpolate import interp1d
from sionna.rt import AntennaPattern, register_antenna_pattern
import mitsuba as mi
import drjit as dr

def extract_custom_pattern(elevation_csv: str, azimuth_csv: str):

    def make_interp(csv_filepath):
        data = np.loadtxt(csv_filepath, delimiter=',')
        angles_rad = np.deg2rad(data[:, 0])
        field_linear = np.power(10, data[:, 1] / 20.0)  # dBi to amplitude
        idx = np.argsort(angles_rad)
        return interp1d(angles_rad[idx], field_linear[idx],
                        bounds_error=False, fill_value=0.0)

    class CsvPattern(AntennaPattern):
        def __init__(self, elevation_csv, azimuth_csv):
            self.elev_interp = make_interp(elevation_csv)
            self.azim_interp = make_interp(azimuth_csv)

            def pattern_func(theta, phi):
                gain_theta = self.elev_interp(theta.numpy()) # Not used, Horizontal Polarization
                gain_phi = self.azim_interp(phi.numpy())

                c_phi = mi.Complex2f(gain_phi, 0)
                c_theta = dr.zeros(mi.Complex2f, dr.width(c_phi))

                return c_theta, c_phi

            self.patterns = [pattern_func]

    def factory(elevation_csv, azimuth_csv):
        return CsvPattern(elevation_csv, azimuth_csv)

    #print("     [INFO] Registering custom antenna pattern...")
    register_antenna_pattern("panasonic_wigig_rsu", factory)