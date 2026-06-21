"""Fixed traffic regression seeds (10 distinct ints, ≥60s spectate each)."""

BASELINE_SEEDS: tuple[int, ...] = (
    215728416,  # user-reported: red entry, 360° turn, dual-turn chaos, green+green
    516524632,
    1999655641,
    42,
    253410532,
    1890416619,
    12345,
    901337221,
    1847293055,
    77319428,
)

REGRESSION_GUARD_SEEDS: tuple[int, ...] = BASELINE_SEEDS[1:7]

SPECTATE_FRAMES_60S = 60 * 60
