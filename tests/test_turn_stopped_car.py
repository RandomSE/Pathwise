"""Turner must not complete arc into a car stopped at a red-light crossing."""

import unittest

from pathwise.car import Car
from pathwise.geom import Rect


class TestTurnStoppedCarAtCrossing(unittest.TestCase):
    def test_turner_holds_when_exit_lane_has_stopped_car(self):
        turner = Car(200, 200, 3.0, vertical=False, spawn_id=10, road_index=0)
        turner.direction = 1
        turner._turn_phase = "turning"
        turner._turn_exit = (1, 1, True)
        turner._turn_px = 220.0
        turner._turn_py = 240.0
        turner.current_speed = 2.0

        blocker = Car(218, 310, 3.0, vertical=True, spawn_id=5, road_index=1)
        blocker.direction = 1
        blocker.current_speed = 0.0
        blocker._turn_phase = "none"

        self.assertTrue(turner._stopped_car_blocks_turn_exit([turner, blocker]))

    def test_turner_proceeds_when_exit_lane_clear(self):
        turner = Car(200, 200, 3.0, vertical=False, spawn_id=10, road_index=0)
        turner._turn_phase = "turning"
        turner._turn_exit = (1, 1, True)
        turner._turn_px = 220.0
        turner._turn_py = 240.0

        far = Car(218, 450, 3.0, vertical=True, spawn_id=5, road_index=1)
        far.direction = 1
        far.current_speed = 0.0

        self.assertFalse(turner._stopped_car_blocks_turn_exit([turner, far]))

    def test_turner_blocks_on_opposing_stopped_car_in_exit_lane(self):
        turner = Car(200, 200, 3.0, vertical=False, spawn_id=10, road_index=0)
        turner._turn_phase = "turning"
        turner._turn_exit = (1, 1, True)
        turner._turn_px = 220.0
        turner._turn_py = 240.0
        turner._sync_collision_shell(force=True)

        opposing = Car(214, 242, 3.0, vertical=True, spawn_id=5, road_index=1)
        opposing.direction = -1
        opposing.current_speed = 0.0
        opposing._turn_phase = "none"
        opposing._sync_collision_shell(force=True)

        self.assertTrue(turner._stopped_car_blocks_turn_exit([turner, opposing]))

    def test_steer_through_turn_holds_on_blocked_exit(self):
        turner = Car(200, 200, 3.0, vertical=False, spawn_id=10, road_index=0)
        turner.direction = 1
        turner._turn_phase = "turning"
        turner._turn_exit = (1, 1, True)
        turner._turn_px = 220.0
        turner._turn_py = 240.0
        turner._turn_arc_len = 80.0
        turner._turn_arc_travel = 20.0
        turner.current_speed = 2.5
        turner._turn_angle_start = 0.0
        turner._turn_angle_end = 90.0
        turner._turn_arc_start = (220.0, 240.0)
        turner._turn_arc_mid = (230.0, 280.0)
        turner._turn_arc_end = (218.0, 320.0)

        blocker = Car(218, 300, 3.0, vertical=True, spawn_id=5, road_index=1)
        blocker.direction = 1
        blocker.current_speed = 0.0

        progressed = turner._steer_through_turn(
            [],
            [],
            [turner, blocker],
            Rect(0, 0, 20, 20),
            False,
        )
        self.assertFalse(progressed)
        self.assertEqual(turner.current_speed, 0.0)

    def test_turner_yields_to_incoming_straight_traffic_priority(self):
        zone = Rect(200, 200, 120, 120)
        turner = Car(220, 220, 3.0, vertical=False, spawn_id=10, road_index=0)
        turner.direction = 1
        turner._turn_phase = "turning"
        turner._turn_exit = (1, 1, True)
        turner._turn_hub = (zone.centerx, zone.centery)
        turner._turn_arc_start = (220.0, 220.0)
        turner._turn_arc_mid = (265.0, 220.0)
        turner._turn_arc_end = (265.0, 290.0)
        turner._turn_px = 230.0
        turner._turn_py = 224.0
        turner._sync_collision_shell(force=True)

        incoming = Car(262, 160, 3.0, vertical=True, spawn_id=5, road_index=1)
        incoming.direction = 1
        incoming.current_speed = 2.6
        incoming._turn_phase = "none"
        incoming.turn_signal = 0
        incoming._sync_collision_shell(force=True)

        self.assertTrue(turner._straight_priority_blocker([incoming], [zone]))

    def test_turner_priority_blocks_incoming_before_intersection_eta(self):
        zone = Rect(200, 200, 120, 120)
        turner = Car(220, 220, 3.0, vertical=False, spawn_id=10, road_index=0)
        turner.direction = 1
        turner._turn_phase = "to_hub"
        turner._turn_exit = (1, 1, True)
        turner._turn_hub = (zone.centerx, zone.centery)
        turner._turn_arc_start = (220.0, 220.0)
        turner._turn_arc_mid = (265.0, 220.0)
        turner._turn_arc_end = (265.0, 290.0)

        incoming = Car(250, 34, 3.0, vertical=True, spawn_id=5, road_index=1)
        incoming.direction = 1
        incoming.current_speed = 3.0
        incoming._turn_phase = "none"
        incoming.turn_signal = 0
        incoming._sync_collision_shell(force=True)

        self.assertTrue(turner._straight_priority_blocker([incoming], [zone]))

    def test_try_start_turn_at_hub_yields_to_incoming_straight_eta(self):
        turner = Car(250, 246, 3.0, vertical=False, spawn_id=10, road_index=0)
        turner.direction = 1
        turner._turn_phase = "to_hub"
        turner._turn_exit = (1, 1, True)
        turner._turn_hub = (260, 260)
        turner._turn_arc_start = (250.0, 246.0)
        turner._turn_arc_mid = (265.0, 240.0)
        turner._turn_arc_end = (265.0, 290.0)

        zone = Rect(200, 200, 120, 120)
        incoming = Car(250, 26, 3.0, vertical=True, spawn_id=5, road_index=1)
        incoming.direction = 1
        incoming.current_speed = 3.0
        incoming._turn_phase = "none"
        incoming.turn_signal = 0
        incoming._sync_collision_shell(force=True)
        turner._turn_path_clear = (lambda *args, **kwargs: True).__get__(turner, type(turner))
        turner._begin_turn_steer = (lambda *args, **kwargs: True).__get__(turner, type(turner))

        progressed = turner._try_start_turn_at_hub(
            [],
            [zone],
            [incoming],
            Rect(0, 0, 1, 1),
            True,
        )
        self.assertFalse(progressed)

    def test_begin_turn_steer_enters_turning_mode(self):
        turner = Car(240, 240, 3.0, vertical=False, spawn_id=7, road_index=0)
        turner.direction = 1
        turner._turn_phase = "to_hub"
        turner._turn_exit = (0, 1, True)
        zone = Rect(200, 200, 120, 120)
        roads = [type("R", (), {"rect": Rect(230, 0, 60, 500), "direction": "vertical"})()]

        progressed = turner._begin_turn_steer(
            roads,
            zone,
            [],
            Rect(0, 0, 1, 1),
            True,
            intersection_zones=[zone],
        )
        self.assertTrue(progressed)
        self.assertEqual(turner._turn_phase, "turning")

    def test_complete_turn_on_exit_lane_resumes_full_speed(self):
        turner = Car(240, 240, 3.0, vertical=False, spawn_id=8, road_index=0)
        turner._turn_phase = "settling"
        turner._turn_exit = (0, 1, True)
        turner._turn_px = 250.0
        turner._turn_py = 260.0
        turner.current_speed = 0.5
        roads = [type("R", (), {"rect": Rect(230, 0, 60, 500), "direction": "vertical"})()]

        turner._complete_turn_on_exit_lane(roads)
        self.assertEqual(turner._turn_phase, "none")
        self.assertAlmostEqual(turner.current_speed, turner.base_speed)
        self.assertEqual(turner.speed, turner.base_speed)

    def test_settle_turn_holds_when_exit_lane_blocked(self):
        turner = Car(240, 240, 3.0, vertical=False, spawn_id=7, road_index=0)
        turner._turn_phase = "settling"
        turner._turn_exit = (0, 1, True)
        turner._turn_settle_target = (260.0, 260.0)
        turner._turn_settle_blend = 0.9
        turner._turn_px = 250.0
        turner._turn_py = 250.0
        turner._turn_angle_end = 90.0
        blocker = Car(260, 300, 0.0, vertical=True, spawn_id=2, road_index=0)
        blocker.direction = 1
        blocker.current_speed = 0.0
        blocker._turn_phase = "none"
        blocker._sync_collision_shell(force=True)
        turner._sync_collision_shell(force=True)
        roads = [type("R", (), {"rect": Rect(230, 0, 60, 500), "direction": "vertical"})()]

        self.assertFalse(turner._settle_turn_exit(roads, [blocker], [Rect(200, 200, 120, 120)]))
        self.assertEqual(turner._turn_phase, "settling")


if __name__ == "__main__":
    unittest.main()
