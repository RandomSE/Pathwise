"""Direction-agnostic road crossing detection."""

import unittest

import main as game
from pathwise.map import Road, make_rectangle
from pathwise import commonUtils
from pathwise.crosswalk_rules import road_midline_crossed
from pathwise.geom import collide, Rect
from pathwise.pedestrian import Pedestrian
from pathwise.input_keys import KEY_LEFT
from pathwise.modifiers.registry import ModifierContext
from pathwise.modifiers import time_pressure


class TestRoadCrossing(unittest.TestCase):
    def test_vertical_road_counts_crossing_from_bottom(self):
        road = Road(make_rectangle(100, 200, 110, 400), commonUtils.VERTICAL)
        prev = (155, 500)
        curr = (155, 300)
        self.assertTrue(game.road_midline_crossed(prev, curr, road))

    def test_vertical_road_counts_crossing_from_top(self):
        road = Road(make_rectangle(100, 200, 110, 400), commonUtils.VERTICAL)
        prev = (155, 300)
        curr = (155, 500)
        self.assertTrue(game.road_midline_crossed(prev, curr, road))

    def test_vertical_road_ignores_parallel_motion(self):
        road = Road(make_rectangle(100, 200, 110, 400), commonUtils.VERTICAL)
        prev = (120, 300)
        curr = (180, 300)
        self.assertFalse(game.road_midline_crossed(prev, curr, road))

    def test_horizontal_road_counts_crossing_from_left(self):
        road = Road(make_rectangle(200, 100, 400, 110), commonUtils.HORIZONTAL)
        prev = (300, 155)
        curr = (500, 155)
        self.assertTrue(game.road_midline_crossed(prev, curr, road))

    def test_horizontal_road_counts_crossing_from_right(self):
        road = Road(make_rectangle(200, 100, 400, 110), commonUtils.HORIZONTAL)
        prev = (450, 155)
        curr = (350, 155)
        self.assertTrue(game.road_midline_crossed(prev, curr, road))

    def test_one_pixel_step_onto_midline_counts(self):
        """Integer 1px walks land on mid exactly; must still count as a crossing."""
        road = Road(make_rectangle(1130, 1662, 110, 867), commonUtils.HORIZONTAL)
        mid = road.rect.centerx
        self.assertTrue(road_midline_crossed((mid + 1, 2150), (mid, 2150), road))
        self.assertTrue(road_midline_crossed((mid - 1, 2150), (mid, 2150), road))
        self.assertFalse(road_midline_crossed((mid, 2150), (mid, 2150), road))

    def test_pedestrian_left_walk_awards_time_pressure_bonus(self):
        from pathwise.map_generator import generate_map
        from map_generation.difficulty import DifficultyProfile
        from pathwise.session_seed import decode_recruiter_seed

        payload = decode_recruiter_seed("912016928223")
        assert payload is not None
        map_seed = (payload.map_seed + 9973) & 0x7FFFFFFF
        game_map = generate_map(
            seed=map_seed, difficulty=DifficultyProfile.for_menu_preset("hard")
        )
        time_pressure.install_for_round(
            ModifierContext(frozenset({"time_pressure"}), session_base_seed=1, round_index=1),
            preset_id="hard",
        )
        self.addCleanup(lambda: time_pressure.install_for_round(ModifierContext(frozenset())))

        player = Pedestrian(game_map.start_pos)
        prev = (player.rect.centerx, player.rect.centery)
        limit = 10.0
        crossings = 0

        class _LeftKeys:
            def pressed(self, key):
                return key == KEY_LEFT

        keys = _LeftKeys()
        for frame in range(400):
            player.update(keys, elapsed=frame / 60)
            curr = (player.rect.centerx, player.rect.centery)
            for road in game_map.roads:
                if road.crossed:
                    continue
                if not road_midline_crossed(prev, curr, road):
                    continue
                if not collide(road.rect, player.rect):
                    continue
                road.crossed = True
                crossings += 1
                bonus = time_pressure.apply_crossing_bonus(
                    time_pressure.TIER_UNSAFE_ROAD, elapsed=frame / 60
                )
                limit += bonus
            prev = curr

        self.assertGreaterEqual(crossings, 1)
        self.assertGreater(limit, 10.0)


if __name__ == "__main__":
    unittest.main()
