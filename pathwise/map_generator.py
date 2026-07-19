"""Backward-compatible entry point for procedural maps."""

from map_generation import (
    DifficultyProfile,
    ProceduralMap,
    adaptive_difficulty,
    generate_map,
    generate_map_layout,
)

__all__ = [
    "DifficultyProfile",
    "ProceduralMap",
    "adaptive_difficulty",
    "generate_map",
    "generate_map_layout",
]

if __name__ == "__main__":
    import sys

    count = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    presets = ["easy", "normal", "hard"]
    for seed in range(count):
        preset = presets[seed % len(presets)]
        profile = DifficultyProfile.for_menu_preset(preset)
        layout = generate_map_layout(seed, difficulty=profile)
        roads = len(layout["roads"])
        blocks = len(layout.get("city_blocks", []))
        assert 12 <= roads <= 120, f"seed {seed}: {roads} road segments"
        assert blocks >= 4, f"seed {seed}: {blocks} city blocks"
        pe = layout["path_estimate_s"]
        tl = layout["time_limit"]
        margin = profile.route_time_margin
        assert tl == max(28, int(pe * margin + 0.999)), (
            f"seed {seed}: time_limit {tl} vs path {pe} margin {margin}"
        )
    print(f"OK: generated {count} procedural maps (easy/normal/hard presets)")
