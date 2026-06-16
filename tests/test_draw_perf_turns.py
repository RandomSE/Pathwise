import unittest
from unittest.mock import patch

from pathwise.geom import Rect


class TestTrafficLightDrawBudget(unittest.TestCase):
    @patch("pathwise.game_draw.draw_sim_rect_outline")
    @patch("pathwise.game_draw.arcade.Text")
    @patch("pathwise.game_draw.draw_sim_circle_filled_world")
    @patch("pathwise.game_draw.draw_sim_rect_filled")
    def test_timer_text_skipped_when_timer_bars_disabled(
        self, _rect_fill, _circle, text_cls, _outline
    ):
        from pathwise import game_draw

        states = []
        for i in range(40):
            crosswalk = Rect(100 + i * 120, 200, 14, 90)
            states.append(
                {
                    "direction": "vertical",
                    "crosswalk": crosswalk,
                    "light_state": "green",
                    "seconds_to_change": 10.0,
                    "next_light": "yellow",
                }
            )
        view_rect = Rect(0, 0, 4000, 4000)
        game_draw.draw_traffic_light_overlays(
            600,
            states,
            (0, 0),
            light_green_duration=20.0,
            view_rect=view_rect,
            draw_timer_bar=False,
        )
        text_cls.assert_not_called()

    @patch("pathwise.game_draw.draw_sim_rect_outline")
    @patch("pathwise.game_draw.arcade.Text")
    @patch("pathwise.game_draw.draw_sim_circle_filled_world")
    @patch("pathwise.game_draw.draw_sim_rect_filled")
    def test_all_in_view_traffic_lights_drawn(
        self, _rect_fill, circle_world, _text_cls, _outline
    ):
        from pathwise import game_draw

        states = []
        for i in range(40):
            crosswalk = Rect(100 + i * 80, 200, 14, 90)
            states.append(
                {
                    "direction": "vertical",
                    "crosswalk": crosswalk,
                    "light_state": "red",
                    "seconds_to_change": 3.0,
                    "next_light": "green",
                }
            )
        view_rect = Rect(0, 0, 4000, 4000)
        game_draw.draw_traffic_light_overlays(
            600,
            states,
            (0, 0),
            light_green_duration=20.0,
            view_rect=view_rect,
            draw_timer_bar=False,
        )
        # Every in-view signal gets three R/Y/G bulbs (no arbitrary draw cap).
        self.assertEqual(circle_world.call_count, 40 * 3)

    def test_visible_traffic_light_states_include_every_crosswalk_in_view(self):
        from pathwise import game_draw

        states = []
        for i in range(25):
            crosswalk = Rect(50 + i * 100, 300, 14, 90)
            states.append(
                {
                    "direction": "horizontal",
                    "crosswalk": crosswalk,
                    "light_state": "green",
                }
            )
        view_rect = Rect(0, 0, 3000, 800)
        visible = game_draw._visible_traffic_light_states(states, view_rect)
        self.assertEqual(len(visible), 25)


class TestTurnSignalGridlock(unittest.TestCase):
    def test_signal_only_car_does_not_block_straight_traffic(self):
        import main as game

        signaling = game.Car(0, 0, 3.0, vertical=False, spawn_id=1)
        signaling._turn_phase = "none"
        signaling.turn_signal = 1
        signaling._turn_exit = (0, 1, False)
        signaling.current_speed = 0.0
        signaling._sync_collision_shell(force=True)

        straight = game.Car(80, 0, 3.0, vertical=False, spawn_id=2)
        straight._turn_phase = "none"
        straight.turn_signal = 0
        next_rect = straight.rect.copy()
        next_rect.x += 10

        self.assertFalse(
            straight._planned_move_conflicts_active_turn(next_rect, [signaling], [])
        )
        cap = straight._soft_overlap_creep_cap(
            next_rect, [signaling], [], intersection_zones=[]
        )
        self.assertIsNone(cap)

    def test_turning_phase_aborts_faster_than_hub_wait(self):
        import main as game

        self.assertLess(
            game.TURN_PATH_BLOCKED_ABORT_FRAMES, game.TURN_ABORT_FRAMES
        )

    def test_stuck_turn_signal_holds_instead_of_going_straight(self):
        import main as game

        car = game.Car(100, 100, 3.0, vertical=True, spawn_id=9)
        car.turn_signal = 1
        car._turn_exit = (0, 1, False)
        car._turn_hub = (120, 120)
        car.current_speed = 0.0
        car.speed = 0.0
        car._turn_wait_frames = game.TURN_SIGNAL_STUCK_FRAMES
        car._maintain_turn_plan([], [], [], Rect(0, 0, 1, 1), True)
        self.assertEqual(car.turn_signal, 1)
        self.assertIsNotNone(car._turn_exit)
        self.assertEqual(car.current_speed, 0.0)
        self.assertGreater(car._turn_hold_frames, 0)


class TestDecisionLoggerBudget(unittest.TestCase):
    def test_advance_not_recorded_every_frame(self):
        from analytics.decision_logger import DecisionLogger, MAX_HEAT_SAMPLES

        logger = DecisionLogger((0, 0), (100, 0), "test", 4)
        for i in range(200):
            logger.update((i * 5, 0), ["right"], False, True, "green", False)
        advance_count = sum(1 for d in logger.decisions if d.get("action") == "advance")
        self.assertEqual(advance_count, 0)
        self.assertLessEqual(len(logger.heat_samples), MAX_HEAT_SAMPLES)

    def test_advance_recorded_on_meaningful_progress(self):
        from analytics.decision_logger import BACKTRACK_MIN_PX, DecisionLogger

        logger = DecisionLogger((0, 0), (200, 0), "test", 4)
        logger.update((BACKTRACK_MIN_PX + 2, 0), ["right"], False, True, "green", False)
        advances = [d for d in logger.decisions if d.get("action") == "advance"]
        self.assertEqual(len(advances), 1)
        self.assertGreater(advances[0]["delta_px"], BACKTRACK_MIN_PX)


if __name__ == "__main__":
    unittest.main()
