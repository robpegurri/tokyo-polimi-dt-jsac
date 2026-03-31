import numpy as np

class RSSIKalmanFilter:
    def __init__(self, process_var, meas_var, rt_var):
        """
        Fusion Kalman filter for RSSI smoothing.

        process_var: How much the true RSSI naturally drifts over time.
        meas_var:    Trust in Real RSSI (Lower = trust measurement more).
        rt_var:      Trust in Ray Tracer (High = treat RT as a "noisy suggestion" 
                     to filter out the fast-fading spikes).
        """
        print(f"Initializing a RSSI Kalman Filter with process_var={process_var}, meas_var={meas_var}, rt_var={rt_var}")

        self.x = None  # Filter state (best estimate)
        self.P = 1.0   # Initial uncertainty
        self.Q = process_var
        self.R_meas = meas_var
        self.R_rt = rt_var  # New variance specifically for Ray Tracer

    def predict(self):
        """Time update (project filter state forward)."""
        if self.x is None:
            return None
        self.P = self.P + self.Q
        return self.x

    def update(self, z_meas, z_rt=None):
        """
        Measurement update.
        z_meas: The real physical RSSI measurement (can be None)
        z_rt:   The Ray Tracer predicted RSSI (can be None)
        """
        # 1. Initialization (if filter hasn't started yet)
        if self.x is None:
            if z_meas is not None:
                self.x = z_meas
            elif z_rt is not None:
                self.x = z_rt
            return self.x

        # 2. Update with Real Measurement (The Anchor)
        # This keeps the values realistic to the physical world
        if z_meas is not None:
            K = self.P / (self.P + self.R_meas)
            self.x = self.x + K * (z_meas - self.x)
            self.P = (1 - K) * self.P

        # 3. Update with Ray Tracer (The Trend/Future Hint)
        if z_rt is not None:
            K_rt = self.P / (self.P + self.R_rt)
            self.x = self.x + K_rt * (z_rt - self.x)
            self.P = (1 - K_rt) * self.P

        return self.x

class AdaptiveBiasFilter:
    def __init__(self, alpha_signal=0.1, alpha_bias=0.05):
        self.alpha_signal = alpha_signal
        self.alpha_bias = alpha_bias
        
        # State variables
        self.ema_mW = None           # Current smoothed RT level (in mW)
        self.current_bias = 0.0      # The learned offset
        self.prev_rt_smoothed = None # Last smoothed RT value
        self.is_initialized = False

    def step(self, predicted_rt, current_meas=None):
        """
        predicted_rt:       Ray Tracer prediction at t+1
        current_meas:       Real measurement at t
        """
        # Smoothing
        predicted_rt_mW = 10**(predicted_rt / 10.0)
        
        if self.ema_mW is None:
            self.ema_mW = predicted_rt_mW
        else:
            self.ema_mW = (self.alpha_signal * predicted_rt_mW) + \
                          ((1 - self.alpha_signal) * self.ema_mW)
        
        rt_smoothed_t = 10 * np.log10(self.ema_mW)

        # Bias update
        if (current_meas is not None) and (self.prev_rt_smoothed is not None):
            past_error = current_meas - self.prev_rt_smoothed
            
            if not self.is_initialized:
                self.current_bias = past_error
                self.is_initialized = True
            else:
                self.current_bias = (self.alpha_bias * past_error) + \
                                    ((1 - self.alpha_bias) * self.current_bias)

        # Output
        output = rt_smoothed_t + self.current_bias
        
        # Memory update
        self.prev_rt_smoothed = rt_smoothed_t
        
        return output