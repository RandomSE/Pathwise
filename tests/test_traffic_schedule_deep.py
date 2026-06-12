"""Deep unit tests for map_generation.traffic_schedule placement helpers."""

import unittest

from map_generation.difficulty import DifficultyProfile
from map_generation import traffic_schedule as ts
from pathwise.geom import Rect
from pathwise.map import Road


class TestTrafficScheduleDeep(unittest.TestCase):
    def _roads(self):
        v = Road(Rect(100, 0, 60, 500), "vertical")
        h = Road(Rect(0, 220, 500, 60), "horizontal")
        return [v, h]

    def test_along_coord_narrow_spans(self):
        narrow_v = Road(Rect(0, 0, 25, 200), "vertical")
        narrow_h = Road(Rect(0, 0, 200, 25), "horizontal")
        self.assertIsInstance(ts._along_coord(narrow_v, 0.5), int)
        self.assertIsInstance(ts._along_coord(narrow_h, 0.5), int)

    def test_edge_entry_both_directions(self):
        v, h = self._roads()
        ts.car_pose_edge_entry(v, 1, queue_index=2.0)
        ts.car_pose_edge_entry(v, -1, queue_index=0.0)
        ts.car_pose_edge_entry(h, 1, queue_index=1.0)
        ts.car_pose_edge_entry(h, -1, queue_index=0.5)

    def test_intersection_frac_pipeline(self):
        roads = self._roads()
        ix = ts.build_intersection_rects(roads)
        self.assertTrue(ix)
        ts._spawn_rect_overlaps_intersection(roads[0], 0.5, 1, ix)
        forbidden = ts._intersection_frac_ranges(roads[0], ix)
        self.assertIsInstance(forbidden, list)
        safe = ts._safe_initial_fracs(roads[0], forbidden, 4)
        self.assertTrue(safe)
        self.assertTrue(ts._frac_in_ranges(0.5, [(0.4, 0.6)]))
        self.assertFalse(ts._frac_in_ranges(0.1, [(0.4, 0.6)]))
        ts._same_lane_along_conflict(roads[0], 1, 0.2, 0.25)
        ts._lane_placements_conflict(roads[0], 1, 0.5, [(1, 0.52)])
        lane_fracs: dict[int, list[tuple[int, float]]] = {0: [(1, 0.3)]}
        occupied: list[tuple[int, int, int, int]] = []
        ts._frac_clear_at_spawn(roads[0], 0, 1, 0.5, lane_fracs, occupied, ix, forbidden)
        alts = ts._alternate_fracs(0.5, 7, count=5)
        self.assertGreater(len(alts), 1)
        boost = ts._road_centrality_boost(roads)
        self.assertEqual(len(boost), 2)
        anchors = ts._intersection_along_fracs(roads)
        self.assertGreater(len(anchors), 0)
        self.assertGreater(ts._weight(roads, [2.0, 1.0], 0), 0)

    def test_opening_and_ongoing_schedules(self):
        roads = self._roads()
        profile = DifficultyProfile.for_menu_preset("hard")
        sched = ts.generate_traffic_schedule(99, roads, [1.0, 2.0], profile, 120, fps=60)
        phases = {e.phase for e in sched}
        self.assertIn(ts.PHASE_OPENING, phases)
        self.assertIn(ts.PHASE_ONGOING, phases)


if __name__ == "__main__":
    unittest.main()
