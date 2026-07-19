"""Perimeter spawn/goal placement: deterministic and edge coverage."""

import unittest

from map_generation.difficulty import DifficultyProfile
from map_generation.generator import generate_map_layout
from map_generation.pathfinding import Cell, is_perimeter_cell, manhattan_cells, opposite_edge
from map_generation.spawn_placement import (
    BOTTOM,
    LEFT,
    RIGHT,
    TOP,
    min_spawn_goal_manhattan,
    pick_spawn_and_goal,
    placement_meets_distance,
    spawn_rng_for_attempt,
)


class TestSpawnPlacement(unittest.TestCase):
    def test_same_seed_same_cells(self):
        rng_a = spawn_rng_for_attempt(424242, 0)
        rng_b = spawn_rng_for_attempt(424242, 0)
        a = pick_spawn_and_goal(rng_a, 5, 4, 0.45)
        b = pick_spawn_and_goal(rng_b, 5, 4, 0.45)
        self.assertEqual(a.start_cell, b.start_cell)
        self.assertEqual(a.goal_cell, b.goal_cell)
        self.assertEqual(a.spawn_edge, b.spawn_edge)

    def test_spawn_covers_all_four_edges_over_seed_sweep(self):
        edges_seen = set()
        for seed in range(1, 201):
            placement = pick_spawn_and_goal(
                spawn_rng_for_attempt(seed, 0), 6, 5, 0.45
            )
            edges_seen.add(placement.spawn_edge)
        self.assertEqual(edges_seen, {TOP, RIGHT, BOTTOM, LEFT})

    def test_goal_on_opposite_edge_and_min_manhattan(self):
        n_v, n_h = 6, 5
        for seed in range(50):
            placement = pick_spawn_and_goal(
                spawn_rng_for_attempt(seed, 0), n_v, n_h, 0.55
            )
            self.assertEqual(placement.goal_edge, opposite_edge(placement.spawn_edge))
            self.assertTrue(placement_meets_distance(placement, n_v, n_h))
            self.assertGreaterEqual(
                manhattan_cells(placement.start_cell, placement.goal_cell),
                min_spawn_goal_manhattan(n_v, n_h),
            )

    def test_goal_never_interior(self):
        n_v, n_h = 7, 6
        for seed in range(100):
            placement = pick_spawn_and_goal(
                spawn_rng_for_attempt(seed, 3), n_v, n_h, 0.4
            )
            self.assertTrue(is_perimeter_cell(placement.start_cell, n_v, n_h))
            self.assertTrue(is_perimeter_cell(placement.goal_cell, n_v, n_h))

    def test_generate_map_layout_is_deterministic_for_cells(self):
        profile = DifficultyProfile.for_menu_preset("normal")
        a = generate_map_layout(9001, difficulty=profile)
        b = generate_map_layout(9001, difficulty=profile)
        meta_a = a["generation"]
        meta_b = b["generation"]
        self.assertEqual(meta_a["start_col"], meta_b["start_col"])
        self.assertEqual(meta_a["start_row"], meta_b["start_row"])
        self.assertEqual(meta_a["goal_col"], meta_b["goal_col"])
        self.assertEqual(meta_a["goal_row"], meta_b["goal_row"])

    def test_known_seed_golden_cells(self):
        profile = DifficultyProfile.for_menu_preset("normal")
        golden = {
            12345: ("bottom", "top", 0, 3, 3, 0),
            424242: ("top", "bottom", 0, 0, 2, 4),
            9001: ("top", "bottom", 0, 0, 2, 3),
        }
        for seed, expected in golden.items():
            with self.subTest(seed=seed):
                layout = generate_map_layout(seed, difficulty=profile)
                gen = layout["generation"]
                spawn_edge, goal_edge, sc, sr, gc, gr = expected
                self.assertEqual(gen["spawn_edge"], spawn_edge)
                self.assertEqual(gen["goal_edge"], goal_edge)
                self.assertEqual(gen["start_col"], sc)
                self.assertEqual(gen["start_row"], sr)
                self.assertEqual(gen["goal_col"], gc)
                self.assertEqual(gen["goal_row"], gr)


if __name__ == "__main__":
    unittest.main()
