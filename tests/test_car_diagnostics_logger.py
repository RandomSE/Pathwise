"""Coverage for CarDiagnosticsLogger session observe paths."""

import json
import tempfile
import unittest
from pathlib import Path

from pathwise.geom import Rect
from analytics.car_diagnostics import CarDiagnosticsLogger


class _StubCar:
    def __init__(self, spawn_id=1, x=100, y=100, vertical=False, direction=1):
        self.spawn_id = spawn_id
        self.rect = Rect(x, y, 60, 30)
        self.vertical = vertical
        self.direction = direction
        self.current_speed = 0.0
        self.speed = 3.0
        self.base_speed = 3.0
        self._turn_phase = "none"
        self.turn_signal = 0
        self._turn_exit = None
        self._turn_hub = None
        self._turn_hold_frames = 0
        self.road_index = 0
        self._stopped_frames = 0
        self._collision_shell = self.rect
        self._alive = True

    def alive(self):
        return self._alive

    def kill(self):
        self._alive = False

    def _rect_in_intersection(self, rect, zones):
        return any(z.colliderect(rect) for z in zones)

    def _hub_travel_offset(self):
        return 1.5


class TestCarDiagnosticsLogger(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".jsonl")
        self.tmp.close()
        self.path = self.tmp.name
        self.logger = CarDiagnosticsLogger(path=self.path, stall_seconds=0.05)

    def tearDown(self):
        Path(self.path).unlink(missing_ok=True)

    def _lines(self):
        return Path(self.path).read_text(encoding="utf-8").strip().splitlines()

    def test_begin_session_and_round(self):
        self.logger.begin_session(session_seed=1, seed_source="test", num_rounds=2)
        self.logger.begin_round(1, session_seed=1, map_seed=2, traffic_map_seed=3)
        self.logger.end_round()
        lines = self._lines()
        self.assertGreaterEqual(len(lines), 3)
        self.assertEqual(json.loads(lines[0])["event"], "session_start")

    def test_observe_first_frame_registers_track(self):
        self.logger.begin_round(1)
        car = _StubCar()
        self.logger.observe(car, game_time=0.0, round_frame=0, intersection_zones=[], move_peers=[])
        self.assertEqual(len(self.logger._tracks), 1)

    def test_backward_anomaly_logged(self):
        self.logger.begin_round(1)
        car = _StubCar()
        self.logger.observe(car, game_time=0.0, round_frame=0, intersection_zones=[], move_peers=[])
        car.rect.x -= 10
        self.logger.observe(car, game_time=1.0, round_frame=1, intersection_zones=[], move_peers=[])
        events = [json.loads(line) for line in self._lines() if '"backward"' in line or line.find('"event": "backward"') >= 0]
        self.assertTrue(any(e.get("event") == "backward" for e in events))

    def test_stall_anomaly_logged(self):
        self.logger.begin_round(1)
        car = _StubCar()
        self.logger.observe(car, game_time=0.0, round_frame=0, intersection_zones=[], move_peers=[])
        self.logger.observe(car, game_time=0.1, round_frame=1, intersection_zones=[], move_peers=[])
        self.logger.observe(car, game_time=0.2, round_frame=2, intersection_zones=[], move_peers=[])
        stalled = [json.loads(line) for line in self._lines() if '"stalled"' in line]
        self.assertTrue(any(e.get("event") == "stalled" for e in stalled))

    def test_dead_car_removed(self):
        self.logger.begin_round(1)
        car = _StubCar()
        self.logger.observe(car, game_time=0.0, round_frame=0, intersection_zones=[], move_peers=[])
        car.kill()
        self.logger.observe(car, game_time=0.1, round_frame=1, intersection_zones=[], move_peers=[])
        self.assertNotIn(car.spawn_id, self.logger._tracks)

    def test_nearby_and_intersection(self):
        self.logger.begin_round(1)
        zone = Rect(90, 90, 40, 40)
        car = _StubCar(x=95, y=95)
        peer = _StubCar(spawn_id=2, x=120, y=120)
        nearby = self.logger._nearby_snapshot(car, [car, peer], player_center=(200, 200))
        self.assertEqual(len(nearby), 1)
        self.assertTrue(self.logger._in_intersection(car, [zone]))

    def test_proximity_streak_logged_after_sustained_near_miss(self):
        self.logger.begin_round(1)
        a = _StubCar(spawn_id=1, x=100, y=100)
        b = _StubCar(spawn_id=2, x=165, y=130, vertical=True, direction=1)
        b.road_index = 1
        b._collision_shell = Rect(165, 130, 60, 30)
        zones = []
        for frame in range(35):
            self.logger.observe(
                a,
                game_time=frame * 0.016,
                round_frame=frame,
                intersection_zones=zones,
                move_peers=[a, b],
            )
            self.logger.observe(
                b,
                game_time=frame * 0.016,
                round_frame=frame,
                intersection_zones=zones,
                move_peers=[a, b],
            )
        events = [json.loads(line) for line in self._lines() if '"proximity_streak"' in line]
        self.assertTrue(any(e.get("event") == "proximity_streak" for e in events))

if __name__ == "__main__":
    unittest.main()
