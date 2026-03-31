from __future__ import annotations
import numpy as np
from scipy.special import erfc
import bisect
from typing import Optional
from network.lena_lookup_tables import BLER_TABLE, MAX_MCS, get_mcs_params

"""
nr.py
---------
Computes the SINR estimation, the suitable NR MCS index using the EESM BG1
lookup tables from 5G-LENA (nr-eesm-t1.cc, CTTC) and the MAC-layer goodput.

"""

# ---------------------------------------------------------------------------
# Helper: linear interpolation on the SINR→BLER curve
# ---------------------------------------------------------------------------

def _interpolate_bler(sinr_db: float,
                      sinr_pts: list[float],
                      bler_pts: list[float]) -> float:
    """
    Return the BLER predicted at sinr_db by linearly interpolating between
    the sampled (sinr, bler) points.
 
    Edge cases:
      - sinr_db below the lowest sample  → return 1.0  (always fails)
      - sinr_db above the highest sample → return 0.0  (always succeeds)
    """
    if sinr_db <= sinr_pts[0]:
        return 1.0
    if sinr_db >= sinr_pts[-1]:
        return 0.0
 
    # bisect_right gives the insertion point i such that sinr_pts[i-1] <= x < sinr_pts[i]
    i = bisect.bisect_right(sinr_pts, sinr_db) - 1
    i = max(0, min(i, len(sinr_pts) - 2))
 
    t = (sinr_db - sinr_pts[i]) / (sinr_pts[i + 1] - sinr_pts[i])
    return bler_pts[i] + t * (bler_pts[i + 1] - bler_pts[i])


# ---------------------------------------------------------------------------
# Helper: find the nearest CBS available for a given MCS
# ---------------------------------------------------------------------------

def _nearest_cbs(mcs: int, cbs: int) -> Optional[int]:
    """
    Return the CBS key in BLER_TABLE[mcs] closest to the requested cbs value.
    Returns None if the MCS entry is empty (no BG1 data).
    """
    available = list(BLER_TABLE[mcs].keys())
    if not available:
        return None
    return min(available, key=lambda c: abs(c - cbs))


# ---------------------------------------------------------------------------
# Main functions
# ---------------------------------------------------------------------------

# To be checked
def old_compute_sinr(rssi_dbm, bandwidth_hz, interferer_rssis=None,
                 noise_figure_db=7, numerology=1,
                 subchannel_size_prb=10, slot_reservation_period_ms=100,
                 seed=None):
    """
    Per-RB SINR with Rayleigh fading on the desired signal.

    Follows the ns-3 NR narrowband-per-RB model: the wideband signal power is
    distributed across RBs via i.i.d. Exp(1) (Rayleigh power fading) coefficients,
    while interference and thermal noise are flat across RBs (wideband assumption).

    Interference model: NR sidelink Mode 2 Sensing-Based SPS (3GPP TS 38.321 §5.22.1.1).
    The caller passes only hidden-node interferers — those the TX cannot sense above
    sl-ThreshS-RSRP (TS 38.321 §5.22.1.1). Their aggregate power is scaled by the
    collision probability 1/pool_size, where pool_size = N_subchannels × N_slots is
    derived from the resource pool configuration (TS 38.214 §8.1.4).

    Activity model: the caller is responsible for pre-filtering interferer_rssis to
    only the nodes that are active at the current timestep (Channel Busy Ratio model,
    TS 38.321 §5.22.1.3). Node activity must be sampled once per timestep and shared
    across all link evaluations in that timestep — not per call — to ensure that
    uplink and downlink see the same interferer set.

    Args:
        rssi_dbm                  : Received signal power from the desired TX [dBm].
        bandwidth_hz              : Channel bandwidth [Hz].
        interferer_rssis          : Received powers of active hidden-node interferers at
                                    this RX [dBm]. The caller must pre-filter to:
                                    (1) hidden nodes only (below sl-ThreshS-RSRP), and
                                    (2) nodes active at this timestep (CBR model).
        noise_figure_db           : Receiver noise figure [dB]. Default: 7 dB.
        numerology                : NR numerology µ — SCS = 15·2^µ kHz. Default: 1.
        subchannel_size_prb       : PRBs per sidelink subchannel (sl-SubchannelSize,
                                    TS 38.214 §8.1.4). Default: 10 PRBs.
        slot_reservation_period_ms: Resource reservation period [ms] (TS 38.321 §5.22.1).
                                    Default: 100 ms → 200 slots for µ=1.
        seed                      : RNG seed for reproducible fading realizations.

    Returns:
        sinr_per_rb_db  : Per-RB SINR [dB], shape (n_rbs,).
        sinr_eff_db     : Effective SINR [dB] (arithmetic mean in linear scale).
        n_rbs           : Number of resource blocks in the channel bandwidth.
    """
    if interferer_rssis is None:
        interferer_rssis = []

    rng = np.random.default_rng(seed)

    # Resource block layout: 1 RB = 12 subcarriers × SCS
    scs_hz   = 15e3 * (2 ** numerology)
    rb_bw_hz = 12 * scs_hz
    n_rbs    = max(1, int(bandwidth_hz / rb_bw_hz))

    # NR sidelink Mode 2 resource pool (TS 38.214 §8.1.4):
    #   pool_size = N_subchannels × N_slots_per_period
    # Each hidden-node interferer collides with probability 1/pool_size.
    n_subchannels = max(1, n_rbs // subchannel_size_prb)
    n_slots       = max(1, int(slot_reservation_period_ms * (2 ** numerology)))
    pool_size     = n_subchannels * n_slots

    # Thermal noise per RB: N₀ · B_rb · NF  [mW]
    noise_per_rb_dbm = -174 + 10 * np.log10(rb_bw_hz) + noise_figure_db
    N_rb = 10 ** (noise_per_rb_dbm / 10)

    # Signal distributed across RBs with Rayleigh fading:
    #   g_k ~ Exp(1),  E[g_k] = 1  →  E[S_k] = S_total / n_rbs
    S_total  = 10 ** (rssi_dbm / 10)           # mW
    g        = rng.exponential(1.0, size=n_rbs)
    S_per_rb = (S_total / n_rbs) * g           # mW, shape (n_rbs,)

    # Interference from active hidden-node collisions: I_k × (1/pool_size)
    # per TS 38.321 §5.22.1.1 random resource selection model.
    I_total  = (1.0 / pool_size) * sum(10 ** (i / 10) for i in interferer_rssis)  # mW
    I_per_rb = I_total / n_rbs                 # mW

    sinr_per_rb    = S_per_rb / (N_rb + I_per_rb)
    sinr_per_rb_db = 10 * np.log10(sinr_per_rb)

    # Effective SINR: arithmetic mean of per-RB linear values → scalar [dB]
    sinr_eff_db = float(10 * np.log10(np.mean(sinr_per_rb)))

    return sinr_per_rb_db, sinr_eff_db, n_rbs

def compute_sinr(
    rssi_dbm: float,
    bandwidth_hz: float,
    interferer_rssis: list[float] | None = None,
    noise_figure_db: float = 7.0,
    numerology: int = 2,
    subchannel_size_prb: int = 10,
    seed: int | None = None,
) -> tuple[np.ndarray, float, int]:
    """
    Per-RB SINR for an NR sidelink link, with Rayleigh fading on the desired
    signal and frequency-expectation interference (Option 2).
 
    Desired signal
    --------------
    Rayleigh fading is applied across all allocated RBs: each RB gets an
    i.i.d. Exp(1) power coefficient so that the mean equals the wideband
    received power. This reflects the per-RB power variation due to
    multipath in a frequency-selective channel.
 
    Interference model (Option 2)
    ------------------------------
    Each active interferer independently occupies one uniformly random
    subchannel (TS 38.214 §8.1.4). The probability that it overlaps with
    any given RB of the desired signal is 1/n_subchannels. Within the
    subchannel it lands on, its power is uniform across subchannel_size_prb
    RBs. Taking the expectation over subchannel placement:
 
        E[I_rb] = P_i * (1/n_sc) * (1/subchannel_size_prb)
                = P_i / n_rbs
 
    i.e. each interferer's power is spread uniformly in expectation across
    all n_rbs resource blocks. This is *not* an arbitrary flat-spreading
    assumption — it follows directly from the subchannel geometry and the
    uniform random resource selection in NR sidelink Mode 2.
 
    The caller is responsible for time-domain filtering: only active
    interferers (nodes transmitting in the same slot) should be passed.
    This function handles only the frequency-domain collision probability.
 
    Effective SINR
    --------------
    Returns the arithmetic mean of per-RB linear SINRs as sinr_eff_db.
    This is consistent with a wideband MCS selection model and is the
    value to pass to compute_nr_mcs(). For strict EESM consistency, apply
    the EESM formula externally on sinr_per_rb_db:
        SINR_eff = -β * ln(mean(exp(-SINR_k / β)))
    with the MCS-appropriate β from the 5G-LENA beta table (nr-eesm-t1.cc).
 
    Parameters
    ----------
    rssi_dbm : float
        Wideband received power of the desired signal [dBm].
    bandwidth_hz : float
        Channel bandwidth [Hz].
    interferer_rssis : list of float, optional
        Wideband received powers of active interferers [dBm].
        Pre-filter to nodes that are transmitting in the current slot.
        Default: no interference (noise-limited).
    noise_figure_db : float
        Receiver noise figure [dB]. Default: 7 dB.
    numerology : int
        NR numerology µ. SCS = 15 * 2^µ kHz.
        Default: 2 (60 kHz SCS, standard for FR3 / μ=2).
    subchannel_size_prb : int
        PRBs per sidelink subchannel (sl-SubchannelSize, TS 38.214 §8.1.4).
        Default: 10 PRB (TR 38.885 Table A-1 highway evaluation default).
    seed : int, optional
        RNG seed for reproducible fading realizations.
 
    Returns
    -------
    sinr_per_rb_db : np.ndarray, shape (n_rbs,)
        Per-RB SINR [dB]. Use this for EESM compression if needed.
    sinr_eff_db : float
        Arithmetic-mean effective SINR [dB].
        Ready for direct input to compute_nr_mcs().
    n_subchannels : int
        Number of subchannels in the band (= n_rbs // subchannel_size_prb).
        Returned for reference / logging.
    """
    if interferer_rssis is None:
        interferer_rssis = []
 
    rng = np.random.default_rng(seed)
 
    # --- RB layout -----------------------------------------------------------
    scs_hz   = 15e3 * (2 ** numerology)         # subcarrier spacing [Hz]
    rb_bw_hz = 12 * scs_hz                       # 1 RB = 12 subcarriers
    n_rbs    = max(1, int(bandwidth_hz / rb_bw_hz))
    n_sc     = max(1, n_rbs // subchannel_size_prb)
 
    # --- Thermal noise per RB [mW] -------------------------------------------
    # N_rb = k*T*B_rb * NF  →  -174 dBm/Hz + 10log10(B_rb) + NF
    noise_per_rb_dbm = -174.0 + 10 * np.log10(rb_bw_hz) + noise_figure_db
    N_rb = 10 ** (noise_per_rb_dbm / 10)        # mW
 
    # --- Desired signal: Rayleigh fading across RBs [mW] --------------------
    S_total  = 10 ** (rssi_dbm / 10)            # mW
    g        = rng.exponential(1.0, size=n_rbs)  # Exp(1) fading coefficients
    S_per_rb = (S_total / n_rbs) * g            # mW, E[S_per_rb] = S_total/n_rbs
 
    # --- Interference: frequency-expectation model [mW] ---------------------
    # E[I_rb] = P_i / n_rbs  (derived above from subchannel geometry)
    I_total  = sum(10 ** (i / 10) for i in interferer_rssis)  # mW
    I_per_rb = I_total / n_rbs                  # mW, flat across RBs
 
    # --- Per-RB SINR ---------------------------------------------------------
    sinr_per_rb    = S_per_rb / (N_rb + I_per_rb)
    sinr_per_rb_db = 10 * np.log10(sinr_per_rb)
 
    # --- Effective SINR: arithmetic mean in linear → dB ---------------------
    sinr_eff_db = float(10 * np.log10(np.mean(sinr_per_rb)))
 
    return sinr_per_rb_db, sinr_eff_db, n_sc


def compute_nr_mcs(
    sinr_db: float,
    target_bler: float = 0.1,
    cbs: int = 5504,
) -> dict:
    """
    Select the highest NR MCS index whose predicted BLER does not exceed
    target_bler for the given SINR and CBS, using the EESM BG1 lookup
    tables from 5G-LENA (nr-eesm-t1.cc). Also returns spectral efficiency,
    modulation order and code rate from 3GPP TS 38.214 Table 5.1.3.1-1.
 
    Parameters
    ----------
    sinr_db : float
        Effective SINR in dB (output of the EESM mapping in a real simulator,
        or instantaneous SINR in a flat-fading channel).
    target_bler : float
        Maximum acceptable Block Error Rate. Default = 0.1 (10 %).
    cbs : int
        Code Block Size in bits. Default = 5504. If the exact CBS is not in the 
        table for a given MCS, the nearest available CBS is used automatically.
 
    Returns
    -------
    dict with keys:
        mcs              : int   – selected MCS index, or -1 if infeasible
        predicted_bler   : float – BLER at the selected MCS (-1.0 if infeasible)
        modulation       : str   – modulation scheme (e.g. "16QAM"), or "N/A"
        modulation_order : int   – Q_m bits per symbol (2/4/6/8), or -1
        code_rate        : float – effective code rate R, or -1.0
        spectral_eff     : float – SE = Q_m * R [bits/s/Hz], or -1.0
        used_cbs         : int   – CBS entry actually used for the lookup
        sinr_db          : float – input SINR (passed through)
        target_bler      : float – input target BLER (passed through)
        feasible         : bool  – False when SINR is too low for any MCS
 
    Examples
    --------
    >>> compute_nr_mcs(8.5)
    {'mcs': 11, 'predicted_bler': 0.07..., 'spectral_eff': 1.6953, ...}
 
    >>> compute_nr_mcs(2.0, target_bler=0.1, cbs=3840)
    {'mcs': 4, 'spectral_eff': 0.6016, ...}
 
    >>> compute_nr_mcs(-5.0)
    {'mcs': -1, 'feasible': False, ...}
    """
    if not (0.0 < target_bler <= 1.0):
        raise ValueError(f"target_bler must be in (0, 1], got {target_bler}")
 
    best_mcs = -1
    best_bler = -1.0
    best_used_cbs = cbs
 
    # Iterate from highest to lowest MCS
    for mcs in range(MAX_MCS, -1, -1):
        entry = BLER_TABLE.get(mcs, {})
        if not entry:
            # No BG1 data for this MCS (e.g. MCS 0-3); skip
            continue
 
        used_cbs = _nearest_cbs(mcs, cbs)
        sinr_pts, bler_pts = entry[used_cbs]
 
        predicted = _interpolate_bler(sinr_db, sinr_pts, bler_pts)
 
        if predicted <= target_bler:
            best_mcs = mcs
            best_bler = predicted
            best_used_cbs = used_cbs
            break  # highest feasible MCS found
 
    # Attach physical-layer parameters from MCS Table 1
    if best_mcs >= 0:
        params = get_mcs_params(best_mcs)
    else:
        params = {
            "modulation_order": -1,
            "modulation":       "OUTAGE",
            "code_rate":        -1.0,
            "spectral_eff":     -1.0,
        }
 
    return {
        "mcs":              best_mcs,
        "predicted_bler":   round(best_bler, 6),
        "modulation":       params["modulation"],
        "modulation_order": params["modulation_order"],
        "code_rate":        params["code_rate"],
        "spectral_eff":     params["spectral_eff"],
        "used_cbs":         best_used_cbs,
        "sinr_db":          sinr_db,
        "target_bler":      target_bler,
        "feasible":         best_mcs != -1,
    }


def compute_nr_thput(spectral_efficiency, bandwidth_hz, num_streams=1, eta=0.73):
    """
    Estimated MAC-layer throughput per user.

    MAC throughput is estimated by applying a fixed overhead factor of 0.73 to 
    the PHY throughput, accounting for DMRS (2 symbols) and PSCCH (2 symbols) out 
    of 14 per slot, consistent with the NR sidelink slot structure defined in 
    3GPP TS 38.211 §8.4.1.

    Args:
        spectral_efficiency : Bits/s/Hz from MCS selection.
        bandwidth_hz        : Channel bandwidth [Hz].
        num_streams         : Number of spatial MIMO streams. Default: 1 (SISO).
                              Set to 2 for 2x2 MIMO rank-2 approximation.
        eta                 : MAC-layer overhead factor. Default: 0.73.

    Returns:
        mac_rate : Per-user MAC goodput [bit/s].
    """
    phy_rate = spectral_efficiency * bandwidth_hz * num_streams
    mac_rate = phy_rate * eta

    return mac_rate