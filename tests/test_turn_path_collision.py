import unittest

from pathwise.geom import Rect, rects_overlap


class TestTurnPathCollision(unittest.TestCase):
    def test_turn_shell_overlap_detects_peer_regardless_of_spawn_id(self):
        import main as game

        leader = game.Car(120, 130, 3.0, vertical=False, spawn_id=3)
        leader._turn_phase = "turning"
        leader._sync_collision_shell(force=True)

        follower = game.Car(118, 128, 3.0, vertical=False, spawn_id=9)
        follower._turn_phase = "turning"
        follower._sync_collision_shell(force=True)

        self.assertTrue(rects_overlap(leader._collision_shell, follower._collision_shell))
        self.assertTrue(leader._turn_shell_overlaps_peer([follower], []))
        self.assertTrue(follower._turn_shell_overlaps_peer([leader], []))

    def test_higher_spawn_id_yields_during_arc_at_drift_speed(self):
        import main as game

        zone = Rect(100, 100, 80, 80)
        leader = game.Car(120, 130, 3.0, vertical=False, spawn_id=2)
        leader._turn_phase = "turning"
        leader._turn_exit = (0, 1, True)
        leader.rect.center = (zone.centerx, zone.centery)
        leader._sync_collision_shell(force=True)

        follower = game.Car(118, 128, 3.0, vertical=False, spawn_id=11)
        follower._turn_phase = "turning"
        follower._turn_exit = (0, -1, True)
        follower.turn_signal = -1
        follower.current_speed = 2.5
        follower.rect.center = (zone.centerx + 1, zone.centery + 1)
        follower._sync_collision_shell(force=True)

        yield_frames = max(8, game.TURN_PEER_YIELD_FRAMES // 2)
        follower._turn_peer_stall_frames = yield_frames
        follower._mitigate_turn_peer_deadlock([leader], [zone], [])
        self.assertEqual(follower._turn_peer_stall_frames, 0)
        self.assertEqual(follower._turn_phase, "turning")
        self.assertGreater(follower._turn_hold_frames, 0)
        self.assertEqual(follower.turn_signal, -1)

    def test_arc_turners_skip_global_shell_separation(self):
        import main as game

        a = game.Car(100, 100, 3.0, vertical=False, spawn_id=1)
        a._turn_phase = "turning"
        a._turn_px, a._turn_py = 100.0, 100.0
        a.rect.center = (100, 100)
        a._sync_collision_shell(force=True)

        b = game.Car(108, 100, 3.0, vertical=False, spawn_id=2)
        b._turn_phase = "turning"
        b._turn_px, b._turn_py = 108.0, 100.0
        b.rect.center = (108, 100)
        b._sync_collision_shell(force=True)

        before_a = (a._turn_px, a._turn_py)
        before_b = (b._turn_px, b._turn_py)
        game._resolve_all_shell_overlaps([a, b])
        self.assertEqual((a._turn_px, a._turn_py), before_a)
        self.assertEqual((b._turn_px, b._turn_py), before_b)

    def test_seed_has_no_sustained_dual_turner_shell_overlap(self):
        import main as game
        from map_generation.difficulty import DifficultyProfile
        from pathwise.input_keys import KeyState
        from unittest.mock import patch
        from analytics.spectate_round import SyntheticClock

        game.session_base_seed = 1890416619
        game.session_use_adaptive_map = False
        profile = DifficultyProfile.for_menu_preset("normal")
        clock = SyntheticClock(t=1_000_000.0)
        max_streak = 0
        streak = 0

        with patch.object(game.time, "time", clock.now):
            game.start_round(1, profile, "normal")
            for _ in range(451):
                game.update_round_frame(KeyState())
                clock.advance()
                dual_overlap = False
                alive = [c for c in game.cars.sprites() if c.alive()]
                for i, a in enumerate(alive):
                    if a._turn_phase not in ("turning", "settling"):
                        continue
                    for b in alive[i + 1 :]:
                        if b._turn_phase not in ("turning", "settling"):
                            continue
                        if rects_overlap(a._collision_shell, b._collision_shell):
                            dual_overlap = True
                            break
                    if dual_overlap:
                        break
                if dual_overlap:
                    streak += 1
                    max_streak = max(max_streak, streak)
                else:
                    streak = 0

        self.assertLess(
            max_streak,
            6,
            msg=f"dual arc turners overlapped shells for {max_streak} consecutive frames",
        )


    def test_turn_intent_survives_long_intersection_block(self):
        """Blocked mid-arc turn must keep blinker/plan — not straight-through abort."""
        import main as game

        zone = Rect(200, 200, 100, 100)
        blocker = game.Car(248, 248, 3.0, vertical=False, spawn_id=1)
        blocker._turn_phase = "none"
        blocker._sync_collision_shell(force=True)

        turner = game.Car(240, 240, 3.0, vertical=False, spawn_id=9)
        turner._turn_phase = "turning"
        turner._turn_exit = (0, 1, True)
        turner.turn_signal = 1
        turner._turn_arc_len = 120.0
        turner._turn_arc_travel = 40.0
        turner._turn_px = float(zone.centerx)
        turner._turn_py = float(zone.centery)
        turner._turn_angle_start = 0.0
        turner._turn_angle_end = 90.0
        turner._set_turn_visual(30.0, turner._turn_px, turner._turn_py)
        turner._sync_collision_shell(force=True)
        turner.rect.center = (int(turner._turn_px), int(turner._turn_py))

        for _ in range(game.TURN_HOLD_RETRY_FRAMES * 2 - 1):
            turner._freeze_blocked_turn_in_intersection(
                [zone],
                [],
                [blocker],
                Rect(0, 0, 1, 1),
                True,
                zone,
            )

        self.assertEqual(turner._turn_phase, "turning")
        self.assertEqual(turner.turn_signal, 1)
        self.assertIsNotNone(turner._turn_exit)
        self.assertGreater(turner._turn_hold_frames, 0)

        turner._turn_hold_frames = game.TURN_HOLD_RETRY_FRAMES * 2
        turner._pause_turn_commitment()
        self.assertEqual(turner._turn_phase, "turning")
        self.assertEqual(turner.turn_signal, 1)

        turner2 = game.Car(240, 240, 3.0, vertical=False, spawn_id=10)
        turner2._turn_phase = "turning"
        turner2._turn_exit = (0, 1, True)
        turner2.turn_signal = 1
        turner2._turn_arc_len = 120.0
        turner2._turn_arc_travel = 40.0
        turner2._turn_px = float(zone.centerx)
        turner2._turn_py = float(zone.centery)
        turner2._set_turn_visual(30.0, turner2._turn_px, turner2._turn_py)
        turner2._sync_collision_shell(force=True)
        turner2._exit_turn_visual_keep_plan()
        self.assertEqual(turner2._turn_phase, "none")
        self.assertEqual(turner2.turn_signal, 1)
        self.assertIsNotNone(turner2._turn_exit)
        self.assertEqual(turner2._turn_hold_frames, game.TURN_PEER_YIELD_FRAMES)

    def test_steer_turn_uses_eased_segment_window(self):
        import main as game

        car = game.Car(200, 200, 3.0, vertical=False, spawn_id=44, road_index=0)
        car._turn_phase = "turning"
        car._turn_exit = (0, 1, True)
        car._turn_arc_len = 100.0
        car._turn_arc_travel = 20.0
        car.current_speed = 2.4
        car._turn_angle_start = 0.0
        car._turn_angle_end = 90.0
        car._turn_arc_start = (200.0, 200.0)
        car._turn_arc_mid = (220.0, 220.0)
        car._turn_arc_end = (240.0, 240.0)
        seen = {}

        def _capture_segment(self, peers, player_body_rect, ped_legal_crossing, t_from, t_to, intersection_zones=None):
            seen["from"] = t_from
            seen["to"] = t_to
            return False

        car._turn_segment_clear = _capture_segment.__get__(car, type(car))
        car._steer_through_turn([], [], [], Rect(0, 0, 1, 1), True)

        step = max(car.base_speed * game.TURN_MIN_STEP_FRAC, 2.4) * game.TURN_DRIFT_SPEED_FRAC
        raw_from = 20.0 / 100.0
        raw_to = min(1.0, (20.0 + step) / 100.0)
        self.assertIn("from", seen)
        self.assertAlmostEqual(seen["from"], game._smoothstep(raw_from), places=5)
        self.assertAlmostEqual(seen["to"], game._smoothstep(raw_to), places=5)


if __name__ == "__main__":
    unittest.main()
