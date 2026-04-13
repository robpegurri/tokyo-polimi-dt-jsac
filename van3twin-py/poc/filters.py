"""
RSSI filters for the Showtime prediction loop.

The core mismatch to keep in mind:
  - rt_prediction  : computed at the vehicle's FUTURE position (after move_object)
  - measurement    : field RSSI at the vehicle's CURRENT position

They are not measuring the same thing, so they cannot be directly fused.
The only honest comparison is lagged: the RT prediction made LAST step
(for the position the car is at NOW) vs. the measurement arriving NOW.

All classes share the same interface:

    filtered = filter.step(rt_prediction, measurement=None)  ->  float

Call .step() once per time interval, in order.
measurement=None means the field value was unavailable this step (RSSI == 0).
"""

from collections import deque


class EWMAFilter:
    """
    Smooths the RT prediction with an exponential moving average.
    Does NOT try to fuse field measurements — RT and field are for different
    positions, so fusing them directly would bias the result.

    When a field measurement is available it is used only to initialize the
    state on the very first call (so we start from a sensible value instead
    of the first noisy RT sample).

    Parameters
    ----------
    alpha : smoothing factor.
            0.0 → output never changes (infinite memory, useless).
            1.0 → raw RT, no smoothing.
            0.2 → good default: slow, stable response.
    """

    def __init__(self, alpha=0.2):
        self.alpha  = alpha
        self._state = None

    def step(self, rt_prediction, measurement=None):
        if self._state is None:
            # Seed with the field measurement if available, otherwise RT
            self._state = measurement if measurement is not None else rt_prediction
            return self._state

        self._state = self.alpha * rt_prediction + (1 - self.alpha) * self._state
        return self._state


class LaggedBiasFilter:
    """
    Estimates and corrects the structural offset between RT and reality using
    a LAGGED comparison — the only position-consistent one available.

    Timeline:
      step t-1 : RT predicts RSSI at position P_t   → stored as prev_rt
      step t   : field measurement arrives at P_t   → bias = meas_t - prev_rt
                 RT predicts RSSI at position P_t+1 → corrected = RT + bias

    The bias is smoothed slowly (alpha_bias is small) because structural
    RT offsets change gradually with environment, not step-to-step.

    The RT prediction is also smoothed before the bias is applied, so that
    positional noise in the RT does not contaminate the bias estimate.

    Parameters
    ----------
    alpha_rt   : smoothing for the raw RT output      (default 0.2 — slow)
    alpha_bias : how fast the bias tracks new evidence (default 0.1 — very slow)
    """

    def __init__(self, alpha_rt=0.2, alpha_bias=0.1):
        self.alpha_rt   = alpha_rt
        self.alpha_bias = alpha_bias
        self._rt_state  = None      # smoothed RT running estimate
        self._prev_rt   = None      # RT prediction stored from previous step
        self._bias      = 0.0       # learned offset: reality - RT

    def step(self, rt_prediction, measurement=None):
        # --- Smooth the RT prediction ---
        if self._rt_state is None:
            self._rt_state = measurement if measurement is not None else rt_prediction
        else:
            self._rt_state = self.alpha_rt * rt_prediction + (1 - self.alpha_rt) * self._rt_state

        # --- Update bias using LAGGED comparison ---
        # prev_rt was the prediction for the position the car is at NOW.
        # measurement is the field reading at that same position NOW.
        if measurement is not None and self._prev_rt is not None:
            new_bias   = measurement - self._prev_rt
            self._bias = self.alpha_bias * new_bias + (1 - self.alpha_bias) * self._bias

        # Store current smoothed RT for the next step's bias update
        self._prev_rt = self._rt_state

        return self._rt_state + self._bias


class KalmanFilter:
    """
    Scalar Kalman filter that treats RT as the only direct observation,
    and uses field measurements only for lagged bias correction (same logic
    as LaggedBiasFilter) rather than fusing them as a simultaneous measurement.

    This avoids the "cheating" problem where a low R_meas causes the filter
    to simply track the field measurement and ignore RT entirely.

    Parameters
    ----------
    Q    : process noise — how much RSSI drifts between steps.
    R_rt : observation noise of the (already bias-corrected) RT prediction.
           Tuned lower than before because we correct bias separately.
    alpha_bias : how fast the lagged bias estimate tracks new evidence.
    """

    def __init__(self, Q=1.0, R_rt=8.0, alpha_bias=0.1):
        self.Q          = Q
        self.R_rt       = R_rt
        self.alpha_bias = alpha_bias
        self._x         = None      # Kalman state
        self._P         = None      # state uncertainty
        self._prev_rt   = None      # raw RT from previous step (for bias)
        self._bias      = 0.0

    def step(self, rt_prediction, measurement=None):
        # --- Update lagged bias ---
        if measurement is not None and self._prev_rt is not None:
            new_bias   = measurement - self._prev_rt
            self._bias = self.alpha_bias * new_bias + (1 - self.alpha_bias) * self._bias

        # Bias-corrected RT is our observation
        z = rt_prediction + self._bias
        self._prev_rt = rt_prediction   # store raw RT for next step's bias update

        # --- Initialize on first call ---
        if self._x is None:
            self._x = measurement if measurement is not None else z
            self._P = self.R_rt
            return self._x

        # --- Predict ---
        P = self._P + self.Q

        # --- Update with bias-corrected RT ---
        K       = P / (P + self.R_rt)
        self._x = self._x + K * (z - self._x)
        self._P = (1 - K) * P

        return self._x


class MovingAverageFilter:
    """
    Sliding window over on-field measurements, averaged together with the
    current RT prediction to produce the filtered RSSI.

    On each step the filter does one of two things with the measurement slot:
      - measurement provided  → push it into the window.
      - measurement=None      → recycle: the most recent stored value is
                                repeated (assumes RSSI did not change).

    The output is the mean of every value currently in the window plus the
    RT prediction for the current step.  While the window is still empty
    (no field measurements received yet) the output degrades to the raw RT
    prediction alone.

    Parameters
    ----------
    window_size : int
        Maximum number of on-field measurements to retain.  Older entries
        are evicted as new ones arrive.
    """

    def __init__(self, window_size=5):
        self.window_size = window_size
        self._window: deque = deque(maxlen=window_size)

    @property
    def measurements(self):
        """Current field-measurement window as a list (oldest → newest)."""
        return list(self._window)

    def step(self, rt_prediction, measurement=None):
        if measurement is not None:
            self._window.append(measurement)
        elif self._window:
            # No reading this step: repeat the last known value
            self._window.append(self._window[-1])
        # else: window still empty — leave it alone

        values = list(self._window) + [rt_prediction]
        return sum(values) / len(values)