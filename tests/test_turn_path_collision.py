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


if __name__ == "__main__":
    unittest.main()
