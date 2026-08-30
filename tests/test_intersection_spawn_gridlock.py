import unittest

from pathwise.geom import Rect, rects_overlap
from pathwise.input_keys import KeyState
from map_generation.difficulty import DifficultyProfile
from map_generation.traffic_schedule import (
    INTERSECTION_SPAWN_PAD,
    build_intersection_rects,
    generate_traffic_schedule,
    pose_overlaps_intersection_rects,
    spawn_poses_for_event,
)


MAP_SEED = 1890426592
SESSION_SEED = 1890416619
INTERSECTION_GRIDLOCK_FRAMES = 90


class TestIntersectionSpawnRejection(unittest.TestCase):
    def test_no_schedule_pose_spawns_in_intersection_approach(self):
        import main as game

        game.session_base_seed = SESSION_SEED
        profile = DifficultyProfile.for_menu_preset("normal")
        game.start_round(1, profile, "normal")
        self.assertEqual(getattr(game.current_map, "seed", None), MAP_SEED)

        roads = game.current_map.roads
        ix_rects = build_intersection_rects(roads)
        schedule = generate_traffic_schedule(
            MAP_SEED,
            roads,
            getattr(game.current_map, "traffic_weights", None),
            profile,
            game.ROUND_TIME_LIMIT,
        )

        for event in schedule:
            road = roads[event.road_index]
            poses = spawn_poses_for_event(
                road, event, ix_rects, game.world_bounds
            )
            for x, y, direction_sign, vertical in poses:
                rect, shell = game._spawn_probe_geometry(x, y, vertical)
                direction = 1 if direction_sign >= 0 else -1
                if game._spawn_probe_blocked(
                    shell,
                    rect,
                    vertical,
                    direction,
                    event.road_index,
                    game.cars,
                    roads,
                    game.intersection_zones,
                    game.player.rect,
                    game._round_city_block_rects,
                    game.world_bounds,
                ):
                    continue
                self.assertFalse(
                    pose_overlaps_intersection_rects(x, y, vertical, ix_rects),
                    msg=(
                        f"event {event.event_id} road {event.road_index} "
                        f"pose ({x},{y}) overlaps intersection"
                    ),
                )
                for zone in game.intersection_zones:
                    approach = zone.inflate(
                        INTERSECTION_SPAWN_PAD, INTERSECTION_SPAWN_PAD
                    )
                    self.assertFalse(
                        rects_overlap(approach, shell),
                        msg=(
                            f"event {event.event_id} road {event.road_index} "
                            f"pose ({x},{y}) allowed in intersection approach"
                        ),
                    )

    def test_spawn_poses_never_overlap_intersection_boxes(self):
        import main as game

        game.session_base_seed = SESSION_SEED
        profile = DifficultyProfile.for_menu_preset("normal")
        game.start_round(1, profile, "normal")
        roads = game.current_map.roads
        ix_rects = build_intersection_rects(roads)
        schedule = generate_traffic_schedule(
            getattr(game.current_map, "seed", None),
            roads,
            getattr(game.current_map, "traffic_weights", None),
            profile,
            game.ROUND_TIME_LIMIT,
        )
        for event in schedule:
            road = roads[event.road_index]
            poses = spawn_poses_for_event(
                road, event, ix_rects, game.world_bounds
            )
            for x, y, _direction_sign, vertical in poses:
                self.assertFalse(
                    pose_overlaps_intersection_rects(x, y, vertical, ix_rects),
                    msg=(
                        f"event {event.event_id} phase {event.phase} "
                        f"pose ({x},{y}) inside intersection"
                    ),
                )


class TestIntersectionGridlockRecovery(unittest.TestCase):
    def setUp(self):
        import main as game

        self.game = game
        game.session_base_seed = SESSION_SEED
        game.session_use_adaptive_map = False
        game.session_num_rounds = 1
        game.app_running = True
        profile = DifficultyProfile.for_menu_preset("normal")
        game.start_round(1, profile, "normal")

    def test_no_car_frozen_in_intersection_over_three_seconds(self):
        frozen_streak: dict[int, int] = {}
        max_streak: dict[int, int] = {}

        for _ in range(INTERSECTION_GRIDLOCK_FRAMES + 30):
            self.game.update_round_frame(KeyState())
            seen: set[int] = set()
            for car in self.game.cars:
                if not car.alive():
                    continue
                if not car._rect_in_intersection(
                    car.rect, self.game.intersection_zones
                ):
                    continue
                if (
                    car.current_speed >= 0.1
                    or car.turn_signal != 0
                    or car._turn_phase != "none"
                ):
                    continue
                sid = car.spawn_id
                seen.add(sid)
                frozen_streak[sid] = frozen_streak.get(sid, 0) + 1
                max_streak[sid] = max(max_streak.get(sid, 0), frozen_streak[sid])
            for sid in list(frozen_streak):
                if sid not in seen:
                    frozen_streak[sid] = 0

        offenders = [
            (sid, streak)
            for sid, streak in max_streak.items()
            if streak > INTERSECTION_GRIDLOCK_FRAMES
        ]
        self.assertEqual(
            offenders,
            [],
            msg=f"cars frozen in intersection >3s: {offenders}",
        )


if __name__ == "__main__":
    unittest.main()
