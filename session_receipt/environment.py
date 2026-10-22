"""Optional environmental scenarios (--env). Ported from the prototype compute.py.

These are ILLUSTRATIVE SCENARIOS, not measurements and not bounds.  Citation keys
(GOOGLE, EPOCH, JEGHAM, ...) resolve in SOURCES.md next to this file.
[ASSUMPTION] = our own number with no source.
"""
import math

LEVELS = ("low", "central", "high")

# Wall-socket energy per token in milli-watt-hours (mWh), incl. datacentre overhead
# (the anchor studies already include PUE, so it is NOT applied again).
E_OUT = dict(
    low=0.20,      # EPOCH: 0.1 Wh low end / 500 output tokens
    central=1.00,  # ASSUMPTION: between EPOCH 0.6 mWh/tok and JEGHAM Claude 3.7 Sonnet ~3.2 mWh/tok
    high=3.20,     # JEGHAM: Claude 3.7 Sonnet short query 0.95 Wh / 300 output tokens
)
E_IN = dict(       # fresh input tokens + cache-write tokens (prefill)
    low=0.03,      # ASSUMPTION: ~1/7 of LOW output; prefill is batched/compute-bound (EPOCH)
    central=0.10,  # ASSUMPTION: 1/10 of CENTRAL output; cross-check EPOCH ~0.21 mWh/tok at 10k ctx
    high=0.25,     # EPOCH: ~0.21 mWh/input token at 10k context, rounded up
)
E_CR = dict(       # cache-READ tokens
    low=0.003,     # ASSUMPTION: 1/10 of LOW fresh input (mirrors the 0.1x cache-read PRICE ratio, not an energy figure)
    central=0.01,  # ASSUMPTION: 1/10 of CENTRAL fresh input
    high=0.25,     # ASSUMPTION (pessimistic): no cache discount at all. Weakest assumption.
)

W_ONSITE_LOW = 1.08   # GOOGLE: 0.26 mL / 0.24 Wh (cooling only)
W_OFFSITE_LOW = 1.0   # ASSUMPTION: low-water grid mix, weak
W_PER_KWH = dict(     # litres per kWh, on-site cooling + off-site generation water
    low=W_ONSITE_LOW + W_OFFSITE_LOW,                          # 2.08
    central=math.sqrt((W_ONSITE_LOW + W_OFFSITE_LOW) * 5.3),   # ASSUMPTION: geometric mean
    high=5.3,                                                  # JEGHAM: 0.18/1.14 + 5.11 = 5.27, rounded
)
C_PER_KWH = dict(     # kg CO2e per kWh
    low=0.125,        # GOOGLE: 0.03 g / 0.24 Wh
    central=0.287,    # JEGHAM: AWS carbon intensity factor
    high=0.50,        # ASSUMPTION: fossil-leaning mix (EGRID US avg 0.37, non-baseload 0.64)
)

SOURCE_KEYS = ("GOOGLE", "EPOCH", "JEGHAM")
CAVEAT = "Illustrative scenarios, not measurements"
NOT_BOUNDS = "None measured, not bounds."


def energy_kwh(t, level):
    """t: dict with output, input (fresh), cache_write, cache_read token counts."""
    return (t.get("output", 0) * E_OUT[level]
            + (t.get("input", 0) + t.get("cache_write", 0)) * E_IN[level]
            + t.get("cache_read", 0) * E_CR[level]) / 1e6   # mWh -> kWh


def scenarios(t):
    """Return {level: {kwh, litres, kg_co2e}} for one source's token totals."""
    out = {}
    for lv in LEVELS:
        e = energy_kwh(t, lv)
        out[lv] = {"kwh": e, "litres": e * W_PER_KWH[lv], "kg_co2e": e * C_PER_KWH[lv]}
    return out
