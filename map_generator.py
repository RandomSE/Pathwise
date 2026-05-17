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
    for seed in range(count):
        layout = generate_map_layout(seed)
        assert 3 <= len(layout["roads"]) <= 5
    print(f"OK: generated {count} procedural maps")
