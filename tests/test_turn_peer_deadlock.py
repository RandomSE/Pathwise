import unittest

from pathwise.geom import Rect, rects_overlap


class TestTurnPeerPriority(unittest.TestCase):
    def test_lower_spawn_id_blocked_by_overlapping_turn_peer_for_path(self):
        import main as game

        zone = Rect(100, 100, 80, 80)
        leader = game.Car(120, 130, 3.0, vertical=False, spawn_id=3)
        leader._turn_phase = "to_hub"
        leader._turn_exit = (0, 1, True)
        leader._turn_hub = (zone.centerx, zone.centery)
        leader.rect.center = (zone.centerx - 4, zone.centery)
        leader._sync_collision_shell(force=True)

        follower = game.Car(118, 128, 3.0, vertical=False, spawn_id=9)
        follower._turn_phase = "to_hub"
        follower._turn_exit = (0, -1, True)
        follower._turn_hub = (zone.centerx, zone.centery)
        follower.rect.center = (zone.centerx + 2, zone.centery + 2)
        follower._sync_collision_shell(force=True)

        self.assertTrue(rects_overlap(leader._collision_shell, follower._collision_shell))
        shell = leader._turn_probe_shell(
            float(leader.rect.centerx), float(leader.rect.centery)
        )
        self.assertTrue(
            leader._shell_blocks_turn_path(
                shell, [follower], Rect(0, 0, 1, 1), True, [zone]
            )
        )
        self.assertTrue(
            follower._shell_blocks_turn_path(
                follower._turn_probe_shell(
                    float(follower.rect.centerx), float(follower.rect.centery)
                ),
                [leader],
                Rect(0, 0, 1, 1),
                True,
                [zone],
            )
        )

    def test_higher_spawn_id_replans_after_peer_yield_frames(self):
        import main as game

        zone = Rect(100, 100, 80, 80)
        leader = game.Car(120, 130, 3.0, vertical=False, spawn_id=2)
        leader._turn_phase = "to_hub"
        leader._turn_exit = (0, 1, True)
        leader.rect.center = (zone.centerx, zone.centery)
        leader._sync_collision_shell(force=True)

        follower = game.Car(118, 128, 3.0, vertical=False, spawn_id=11)
        follower._turn_phase = "to_hub"
        follower._turn_exit = (0, -1, True)
        follower.turn_signal = -1
        follower.current_speed = 0.0
        follower.rect.center = (zone.centerx + 1, zone.centery + 1)
        follower._sync_collision_shell(force=True)

        follower.rect.center = (zone.centerx + 1, zone.centery + 1)
        follower._sync_collision_shell(force=True)
        follower._turn_peer_stall_frames = game.TURN_PEER_YIELD_FRAMES
        follower._mitigate_turn_peer_deadlock([leader], [zone], [])
        self.assertEqual(follower._turn_peer_stall_frames, 0)
        self.assertEqual(follower.turn_signal, -1)
        self.assertEqual(follower._turn_phase, "to_hub")
        self.assertGreater(follower._turn_hold_frames, 0)
        self.assertEqual(follower.current_speed, 0.0)


class TestDualTurnerSpectateBudget(unittest.TestCase):
    def test_no_pair_stuck_in_same_intersection_over_two_seconds(self):
        import main as game
        from map_generation.difficulty import DifficultyProfile
        from pathwise.geom import collide
        from pathwise.input_keys import KeyState

        game.session_base_seed = 1890416619
        game.session_use_adaptive_map = False
        profile = DifficultyProfile.for_menu_preset("normal")
        game.start_round(1, profile, "normal")

        pair_streak: dict[tuple[int, int], int] = {}
        max_pair_streak = 0
        for _ in range(180):
            game.update_round_frame(KeyState())
            stuck_pair = None
            for zone in game.intersection_zones:
                in_ix = [
                    c
                    for c in game.cars.sprites()
                    if c.alive()
                    and c._turn_phase in ("to_hub", "turning", "settling")
                    and collide(c.rect, zone)
                    and c.current_speed < 0.2
                ]
                if len(in_ix) >= 2:
                    ids = tuple(sorted(c.spawn_id for c in in_ix[:2]))
                    stuck_pair = ids
                    break
            if stuck_pair:
                pair_streak[stuck_pair] = pair_streak.get(stuck_pair, 0) + 1
                max_pair_streak = max(max_pair_streak, pair_streak[stuck_pair])
            else:
                pair_streak.clear()

        self.assertLess(
            max_pair_streak,
            120,
            msg=f"two turners gridlocked in intersection for {max_pair_streak} frames",
        )


if __name__ == "__main__":
    unittest.main()
