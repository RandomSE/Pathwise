"""Regression: replay lights align with deduped map_layout crosswalks."""
from __future__ import annotations

import unittest

from analytics.frame_recorder import FrameRecorder
from analytics.map_snapshot import serialize_lights_for_replay, serialize_map_layout
from analytics.traffic_lights import FORBIDDEN_PERPENDICULAR_PAIRS
import main as game
from map_generation.difficulty import DifficultyProfile
from pathwise.geom import Rect


def _forbidden_perp_count(crosswalks, lights):
    count = 0
    for i, cw_i in enumerate(crosswalks):
        for j, cw_j in enumerate(crosswalks):
            if i >= j or cw_i["direction"] == cw_j["direction"]:
                continue
            li = lights[i] if i < len(lights) else "green"
            lj = lights[j] if j < len(lights) else "green"
            if (li, lj) in FORBIDDEN_PERPENDICULAR_PAIRS or (
                lj,
                li,
            ) in FORBIDDEN_PERPENDICULAR_PAIRS:
                count += 1
    return count


class TestReplayLightsAlignment(unittest.TestCase):
    def setUp(self):
        game.session_base_seed = 332556754
        game.session_use_adaptive_map = False
        profile = DifficultyProfile.for_menu_preset("normal")
        game.start_round(1, profile, "normal")
        self.road_states = game.road_states
        self.layout = serialize_map_layout(
            game.current_map, self.road_states, game.world_bounds
        )
        game.update_light_timers(self.road_states, 12.0)

    def test_live_signals_never_show_forbidden_perpendicular_pairs(self):
        lights = [e["s"] for e in serialize_lights_for_replay(self.road_states)]
        crosswalks = self.layout["crosswalks"]
        self.assertEqual(len(lights), len(crosswalks))
        self.assertEqual(
            _forbidden_perp_count(crosswalks, lights),
            0,
            "deduped live lights must not show forbidden perpendicular pairs",
        )

    def test_frame_recorder_lights_match_map_layout_crosswalks(self):
        recorder = FrameRecorder(game.PEDESTRIAN_SIZE)
        player = Rect(0, 0, 28, 28)
        recorder.capture(
            1.0, player, [], self.road_states, force=True, game_time=1.0
        )
        frame_lights = recorder.frames[0]["lights"]
        crosswalks = self.layout["crosswalks"]
        self.assertEqual(len(frame_lights), len(crosswalks))
        colors = [e["s"] for e in frame_lights]
        self.assertEqual(
            _forbidden_perp_count(crosswalks, colors),
            0,
            "recorder lights must not produce forbidden pairs in replay",
        )


class TestInBoxRedClearance(unittest.TestCase):
    @staticmethod
    def _westbound_state(zone: Rect, light: str) -> dict:
        crosswalk = Rect(zone.right - 22, zone.centery - 30, 22, 60)
        return {
            "approach_rect": zone.inflate(180, 180),
            "crosswalk": crosswalk,
            "light_state": light,
            "seconds_to_change": 5.0,
            "direction": "horizontal",
            "approach": "west",
        }

    def test_inside_intersection_red_does_not_block_advance(self):
        import main as game

        zone = Rect(200, 200, 100, 100)
        car = game.Car(245, 240, 8.0, vertical=False, spawn_id=18, road_index=0)
        car.direction = -1
        car._sync_collision_shell(force=True)
        states = [self._westbound_state(zone, "red")]
        next_rect = car.rect.copy()
        next_rect.x -= 6
        self.assertFalse(
            car._intersection_advance_blocked_on_red(next_rect, states, [zone])
        )

    def test_post_turn_inside_ix_with_reservation_not_blocked(self):
        import main as game

        zone = Rect(200, 200, 100, 100)
        crosswalk = Rect(zone.right - 22, zone.centery - 30, 22, 60)
        car = game.Car(245, 240, 8.0, vertical=False, spawn_id=19, road_index=0)
        car.direction = 1
        car._turn_phase = "none"
        car._turn_reservation_frames = 12
        car._sync_collision_shell(force=True)
        states = [
            {
                "approach_rect": zone.inflate(180, 180),
                "crosswalk": crosswalk,
                "light_state": "red",
                "seconds_to_change": 5.0,
                "direction": "vertical",
                "approach": "north",
            }
        ]
        next_rect = car.rect.copy()
        next_rect.y -= 6
        self.assertFalse(
            car._intersection_advance_blocked_on_red(next_rect, states, [zone])
        )


if __name__ == "__main__":
    unittest.main()
