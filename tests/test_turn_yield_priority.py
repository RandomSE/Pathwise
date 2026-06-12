import unittest

from pathwise.geom import Rect, rects_overlap


class TestTurnYieldPriority(unittest.TestCase):
    def test_straight_yields_to_committed_turner(self):
        import main as game

        zone = Rect(80, 80, 80, 80)
        turner = game.Car(100, 100, 3.0, vertical=False, spawn_id=1)
        turner.turn_signal = 1
        turner._turn_phase = "to_hub"
        turner._turn_exit = (0, 1, True)
        turner.current_speed = 1.5
        turner.rect.center = (zone.centerx, zone.centery)
        turner._sync_collision_shell(force=True)

        straight = game.Car(100, 100, 3.0, vertical=False, spawn_id=2)
        straight.direction = 1
        straight._turn_phase = "none"
        straight.turn_signal = 0
        straight.rect.center = (zone.centerx - 8, zone.centery)
        straight._sync_collision_shell(force=True)

        self.assertTrue(rects_overlap(straight._collision_shell, turner._collision_shell))
        self.assertTrue(straight._conflicts_with_committed_turner(turner, [zone]))
        self.assertTrue(turner._ix_creep_has_priority(straight, [zone]))
        self.assertFalse(straight._ix_creep_has_priority(turner, [zone]))

    def test_committed_turner_blocks_entry(self):
        import main as game

        zone = Rect(80, 80, 80, 80)
        turner = game.Car(100, 100, 3.0, vertical=False, spawn_id=3)
        turner.turn_signal = 1
        turner._turn_phase = "to_hub"
        turner._turn_exit = (0, 1, True)
        turner.current_speed = 1.5
        turner.rect.center = (zone.centerx, zone.centery)
        turner._sync_collision_shell(force=True)

        eastbound = game.Car(100, 100, 3.0, vertical=False, spawn_id=4)
        eastbound.direction = 1
        eastbound.rect.center = (zone.left - 55, zone.centery)
        eastbound._sync_collision_shell(force=True)
        next_rect = eastbound.rect.copy()
        next_rect.x += 70

        self.assertTrue(
            eastbound._entry_blocks_moving_cross_traffic(
                next_rect, [turner], [zone]
            )
        )


if __name__ == "__main__":
    unittest.main()
