"""Carbon arithmetic: turning a finding into the energy it stands for."""

from __future__ import annotations

# ----------------------------------------------------- carbon arithmetic ---

# Order-of-magnitude steers for which findings are worth fixing first — not
# measurements. Two anchors make them checkable rather than plausible-sounding:
#
#   1 gCO2e ~= 500 seconds of one busy CPU core   (see core_seconds_per_gram)
#   1 GB transferred ~= 15 gCO2e                  (~0.03 kWh/GB x grid)
#
# Where a rule saves a real physical quantity — an instance-day, a GB pulled,
# a GB-month stored — the hint is a number. Where it saves a few microseconds
# per call, it is *not*: a function call costs nanojoules, so any per-call gram
# figure is fiction. Those hints state the scaling instead, which is the thing
# that actually decides whether the rule is worth acting on.
#
# Everything here is wildly workload-dependent. Treat as relative, not exact.
#
# Every figure below is one of these constants times a stated assumption, and
# each hint carries that arithmetic as a comment. Where a constant is published
# the source is linked; where it is derived the derivation is the whole of it.
#
#   480 gCO2e/kWh — published. World average power-sector intensity for 2023:
#     "CO2 intensity reached a new record low of 480 gCO2/kWh, down 1.2% from
#     486 gCO2/kWh in 2022" — Ember, Global Electricity Review 2024. It is on
#     the "Electricity transition in 2023" chapter, not the report landing page:
#     https://ember-energy.org/latest-insights/global-electricity-review-2024/electricity-transition-in-2023/
#     The figure drifts a few percent a year (486 in 2022, 480 in 2023, 473 in
#     2024), which is far inside the error bars on everything below. 480 is also
#     what the sibling carbon-badge tool uses, and the two agreeing matters more
#     here than either tracking the latest annual revision.
#   0.03 kWh/GB transferred — derived. Aslan et al. 2018 measured 0.06 kWh/GB
#     for 2015 fixed-line transmission, halving roughly every 2 years, which
#     puts the network alone well under 0.01 today; 0.03 is that plus its share
#     of data-centre and CDN energy. https://doi.org/10.1111/jiec.12630
#   0.65 Wh/TBh stored — published. "0.65 Watt-Hours per Terabyte-Hour for HDD"
#     — Cloud Carbon Footprint (CCF below), methodology, under "Storage"; CCF is
#     an open-source cloud-emissions estimator. They follow Etsy's
#     Cloud Jewels method but re-derive the coefficient for 2020 from the 2016
#     U.S. Data Center Usage Report. (Cloud Jewels' own older HDD figure is
#     higher; this is the one on the page linked.)
#     https://www.cloudcarbonfootprint.org/docs/methodology/
#   1.135-1.56 PUE — published. Hyperscale is the low end (Cloud Carbon
#     Footprint quotes 1.135 for AWS, 1.1 for GCP, 1.125 for Azure); the
#     industry-wide average is 1.56, flat for five years (Uptime Institute,
#     Global Data Center Survey 2024).
#     https://uptimeinstitute.com/resources/research-and-reports/uptime-institute-global-data-center-survey-results-2024
#   15 W per busy core — derived from the two above. Cloud Carbon Footprint's
#     AWS coefficient is 3.5 W per vCPU at 100% CPU; a vCPU is one hyperthread,
#     so a fully loaded physical core is ~7 W of silicon. x PUE that is 8 W
#     hyperscale, 11 W at the industry average, and the core's share of memory,
#     storage, network and idle host draw is on top — CCF meters those
#     separately, we do not. 15 W is the round number above that band, chosen
#     deliberately: it makes every compute figure below the generous end of
#     plausible rather than the mean.
#     The sibling carbon-badge tool prices a busy core at ~4.7 W, which looks
#     like the two disagreeing 3x. They do not. It starts from Eco-CI's
#     SPECpower curve for the one machine GitHub runs CI on (2.05 W/vCPU
#     against CCF's cross-fleet 3.5 — a 1.7x spread between two published
#     sources), and it knows those jobs ran on Azure, so it takes the
#     hyperscale PUE and no safety margin. It is measuring a known machine; we
#     are bounding an unknown one. Do not port its constant here, or ours
#     there. See its docs/assumptions.md, "Reconciling with greenlint".
# A swap and a two-name unpack are both exactly two targets.
PAIR = 2

GRID_INTENSITY_G_PER_KWH = 480.0
BUSY_CORE_WATTS = 15.0
KWH_PER_GB_TRANSFERRED = 0.03
G_CO2E_PER_GB = KWH_PER_GB_TRANSFERRED * GRID_INTENSITY_G_PER_KWH  # 14.4, quoted as ~15


def core_seconds_per_gram(grid_g_per_kwh: float = GRID_INTENSITY_G_PER_KWH, watts: float = BUSY_CORE_WATTS) -> float:
    """Seconds of one busy CPU core that add up to 1 gCO2e.

    The sanity check behind every hint below: at 480 gCO2e/kWh a gram is 7.5 kJ,
    which is ~500 seconds of a 15 W core. Any rule claiming ~0.001 gCO2e per
    call is therefore claiming half a core-second per call — which is why the
    per-call hints below describe scaling rather than quoting a figure.
    """
    joules_per_gram = 3_600_000 / grid_g_per_kwh
    return joules_per_gram / watts


# Shared phrasing for costs too small to quote per occurrence.
_HOT_PATH = "negligible per call; ~1 gCO2e per 500 core-seconds of work removed"

CO2E_HINTS = {
    # --- Compute left running: real instance-hours, so real numbers. ---
    # One instance model behind all of these, so they stay comparable instead of
    # each carrying its own invented watt band:
    #   busy vCPU  7.5 W = BUSY_CORE_WATTS / 2 (a vCPU is one hyperthread)
    #   idle vCPU  1.6 W = CCF's 0.74 W idle x the same ~2.1 overhead factor
    #   a typical instance here is 4-16 vCPU; a cluster node 8-32
    # Each hint is then (watts freed) x (hours) x 0.48 gCO2e/Wh.
    "GL001": "~150-200 gCO2e/day per instance (one core pegged continuously)",  # 15 W x 24 h
    # Polling denies the core its deep C-states without loading it, so the cost
    # sits inside the 1.6 -> 7.5 W idle-to-busy span; 1-3 W x 24 h.
    "GL002": "~10-40 gCO2e/day per instance (wake-ups blocking CPU idle states)",
    # Runtime / 500, so no invented band: a 2 core-second job x 1440 runs/day is
    # 2880 core-seconds, ~6 gCO2e. Widening to */5 removes 80% of that.
    "GL003": "~1 gCO2e per 500 core-seconds of runtime; a 2 s job x 1440 runs/day is ~6 gCO2e/day",
    # Downsizing frees the idle vCPUs it was paying for: 4-16 x 1.6 W x 24 h.
    "GL008": "~70-300 gCO2e/day per oversized instance (4-16 vCPU of idle capacity)",
    # One extra node is one extra 8-32 vCPU VM idling: 13-51 W x 24 h.
    "GL014": "~150-600 gCO2e/day if it forces one extra node; nothing if the cluster has slack",
    # 0.4 x a 4-16 vCPU instance at ~50% load (4.6 W/vCPU) x 24 h. AWS publishes
    # Quoting the vendor: "up to 60% less energy for the same performance".
    # (https://aws.amazon.com/ec2/graviton/); independent benchmarks land nearer
    # 45-50%, so 40% is the conservative end.
    "GL016": "~80-350 gCO2e/day per instance (ARM draws roughly 40% less for equal work)",
    # The whole 4-16 vCPU instance idling, x ~16 non-working hours.
    "GL024": "~50-200 gCO2e/day per instance left running outside working hours",
    # The one figure here with no model behind it: io1/io2 draw somewhat more per
    # IOP than gp3, but by how much is a guess. 1-10 gCO2e/day is 0.1-0.9 W.
    "GL025": "~1-10 gCO2e/day per volume (marginally higher draw per IOP; weakly grounded)",
    "GL033": "~50-200 gCO2e/day per replica left running outside working hours",  # as GL024
    "GL034": "~150-600 gCO2e/day if it forces one extra host; nothing if the host has slack",
    # --- Storage: per GB-month. ---
    # 0.65 Wh/TBh x 730 h x 0.48 gCO2e/Wh / 1000 GB = 0.23 gCO2e per GB-month of
    # spinning disk, x ~1.5 for erasure-coded durability (stored bytes, not
    # logical bytes) x ~1.5 PUE (the coefficient is drive-level) = ~0.5.
    "GL013": "~0.5 gCO2e per GB per month left in hot storage",
    "GL026": "~0.5 gCO2e per GB per month of logs retained",
    # --- Transfer: GB x 0.03 kWh x 480 gCO2e/kWh = 14.4, quoted as ~15 gCO2e/GB.
    # The size of the payload is then the whole story. ---
    "GL004": "~15 gCO2e per GB of history; a 200 MB repo is ~3 gCO2e per clone avoided",
    "GL006": "~15 gCO2e per GB not transferred, per pull",
    "GL009": "~15 gCO2e per GB of recommended packages avoided, per pull",
    "GL010": "~15 gCO2e per GB of cached wheels not baked into the image, per pull",
    "GL011": "~15 gCO2e per GB; a 200 KB unseen image is ~0.003 gCO2e per page view",  # 0.0002 GB
    "GL015": "~15 gCO2e per GB, per pull (older runtimes are usually larger)",
    # 5 MB GIF -> ~0.5 MB MP4, so 0.0045 GB saved
    "GL017": "~15 gCO2e per GB saved; a 5 MB GIF as MP4 is ~0.07 gCO2e per view",
    "GL027": "~15 gCO2e per GB re-fetched that a cache header would have avoided",
    "GL029": "~15 gCO2e per GB in the avoidable layer, per pull",
    # --- Hot-path micro-costs: scaling, not fictional per-call grams. ---
    # No per-occurrence arithmetic to give: the only number that applies is the
    # anchor, 1 gCO2e per 500 core-seconds (see core_seconds_per_gram).
    "GL005": f"~15 gCO2e per GB of columns never read; {_HOT_PATH}",
    "GL007": f"allocation and GC churn; {_HOT_PATH}",
    "GL012": f"one round trip per row instead of one per query; {_HOT_PATH}",
    "GL018": "grows as n squared; passes ~1 gCO2e once the extra work reaches ~500 core-seconds",
    "GL019": f"network wait and a remote CPU wake per call; {_HOT_PATH}",
    "GL020": f"string work done even when the level is disabled; {_HOT_PATH}",
    "GL021": f"10-100x the interpreter work of a vectorised op; {_HOT_PATH}",
    "GL022": f"reopening and rereading per iteration; {_HOT_PATH}",
    "GL023": "n squared instead of n log n; passes ~1 gCO2e once the extra work reaches ~500 core-seconds",
    "GL028": f"modules loaded and bound at every start; {_HOT_PATH}",
    "GL030": f"building and discarding half a tuple per iteration; {_HOT_PATH}",
    "GL031": f"raising and unwinding on every pass; {_HOT_PATH}",
    "GL032": f"repeated allocator overhead per iteration; {_HOT_PATH}",
    "GL035": f"full enumeration where a short-circuit would do; {_HOT_PATH}",
    "GL036": f"an O(n) scan where a hash lookup is O(1); {_HOT_PATH}",
    "GL037": f"two passes over the collection instead of one; {_HOT_PATH}",
    "GL038": f"extra allocation and a defeated memoisation per render; {_HOT_PATH}",
    # --- Added coverage for C#, Kotlin, Swift and Ruby (see docs/rules.md) ---
    "GL039": "a TLS handshake and a new connection per call, CPU on both ends",
    "GL040": f"a pool thread parked, and the pool grown to replace it; {_HOT_PATH}",
    "GL041": f"a whole collection allocated to walk it once; {_HOT_PATH}",
    "GL042": "work that outlives its caller: CPU spent on a result nobody reads",
    "GL043": f"two passes and an intermediate list instead of one pass; {_HOT_PATH}",
    "GL044": f"a real thread parked for the duration of the coroutine; {_HOT_PATH}",
    "GL045": f"two passes and an intermediate array instead of one pass; {_HOT_PATH}",
    "GL046": f"a thread blocked and idle until the block returns; {_HOT_PATH}",
    "GL047": "a dropped connection pool, so a handshake per request",
    "GL048": "quadratic in the string built; passes ~1 gCO2e once the extra work reaches ~500 core-seconds",
    "GL049": f"one round trip and one remote query plan per row; {_HOT_PATH}",
    "GL050": f"an intermediate collection allocated and discarded; {_HOT_PATH}",
}

