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
        layout = generate_map_layout(seed, difficulty=DifficultyProfile.for_menu_preset(preset))
        roads = len(layout["roads"])
        blocks = len(layout.get("city_blocks", []))
        assert 12 <= roads <= 120, f"seed {seed}: {roads} road segments"
        assert blocks >= 4, f"seed {seed}: {blocks} city blocks"
        assert layout["time_limit"] >= 100, layout["time_limit"]
    print(f"OK: generated {count} procedural maps (easy/normal/hard presets)")
