import math
import os
import random
import json
import time
from dataclasses import dataclass
from pathwise import commonUtils
from pathwise import map_generator
from pathwise import map_visuals
from pathwise import pre_game
from pathwise.traffic_signal_layout import (
    APPROACH_EAST,
    APPROACH_NORTH,
    APPROACH_SOUTH,
    APPROACH_WEST,
    approach_sign_rect,
)
from pathwise import sprites
from pathwise.entity_group import Entity, EntityGroup
from pathwise.input_keys import KEY_DOWN, KEY_LEFT, KEY_RIGHT, KEY_UP, KeyState, key_labels_from_state
from pathwise.session_seed import resolve_session_seed
from map_generation.difficulty import DifficultyProfile
from map_generation.intersection_routing import (
    choose_exit,
    pick_turn_side,
    pivot_center_at_intersection,
    travel_vector,
    turn_side_from_exit,
)
from map_generation.turn_clearance import bezier_point as _bezier_xy
from map_generation.turn_clearance import corridor_bounds as _turn_corridor_bounds
from map_generation.turn_clearance import sample_bezier as _sample_bezier_xy
from map_generation.lane_geometry import lane_center_xy
from map_generation.traffic_schedule import (
    INTERSECTION_SPAWN_PAD,
    MIN_ALONG_GAP,
    RECT_COLLIDE_PAD,
    TrafficSpawn,
    build_intersection_rects,
    edge_spawn_lane_allowed,
    generate_traffic_schedule,
    lane_spawn_allowed,
    PHASE_ONGOING,
    pose_overlaps_intersection_rects,
    spawn_poses_for_event,
)
from analytics.decision_logger import DecisionLogger
from analytics.archetype_scoring import score_session
from analytics.dashboard import build_dashboard_html
from analytics.map_snapshot import serialize_map_layout
from analytics.frame_recorder import FrameRecorder
from analytics.traffic_lights import (
    cycle_durations,
    light_state_at,
    perpendicular_phase_offsets,
    protected_turn_light_at,
)
from analytics.car_diagnostics import car_diagnostics
from analytics.perf_profiler import PerfProfiler, perf_profile_enabled
from pathwise.geom import Rect, collide, clip_rect, contains_rect, rect_overlap_area, rects_overlap

# --- Config ---
utils = commonUtils
WIDTH, HEIGHT = utils.WIDTH, utils.HEIGHT
ROAD_Y = utils.ROAD_Y
ROAD_HEIGHT = utils.ROAD_HEIGHT
CAR_WIDTH, CAR_HEIGHT = utils.CAR_WIDTH, utils.CAR_HEIGHT
PEDESTRIAN_SIZE = utils.PEDESTRIAN_SIZE
PEDESTRIAN_SPEED = utils.PEDESTRIAN_SPEED
CAR_SPEED = utils.CAR_SPEED
SIM_FPS = 60.0
ROUND_TIME_LIMIT = 30
HUD_TEXT_COLOR = (20, 20, 20)
RISK_COOLDOWN_SECONDS = 1.5
# Perpendicular signals: 45% green / 10% yellow / 45% red per approach arm
LIGHT_CYCLE_SECONDS = 20.0
LIGHT_GREEN_DURATION, LIGHT_YELLOW_DURATION, LIGHT_RED_DURATION = cycle_durations(
    LIGHT_CYCLE_SECONDS
)
YELLOW_COMMIT_DISTANCE = 85
INTERSECTION_CLEAR_BUFFER_S = 0.6
STOP_LINE_GAP = 6
CAR_SPAWN_CLEARANCE = 20
CROSSWALK_THICKNESS = 14
INTERSECTION_GAP_MIN = 6
NEAR_MISS_DISTANCE = 56
TOO_CLOSE_DISTANCE = 82
PLAYER_AVOIDANCE_CHANCE = 0.8
CAR_FOLLOW_LANE_GAP = 40
CAR_BLOCK_LANE_GAP = 38
CAR_CREEP_SPEED = 1.1
# Same-lane: minimum clear gap between car AABBs (no sharing interior)
CAR_FOLLOW_SEP = 5
# Perpendicular: block only on real rect overlap, not edge padding (avoids gridlock)
PERP_OVERLAP_SHRINK = 2
STUCK_BEHIND_FRAMES = 240
INTERSECTION_STUCK_CREEP_FRAMES = 45
INTERSECTION_GRIDLOCK_FRAMES = 180
INTERSECTION_APPROACH_SPAWN_PAD = INTERSECTION_SPAWN_PAD
MAX_DRAW_RECORD_CARS = 28
SIM_UPDATE_VIEW_PAD = 280
OFFSCREEN_UPDATE_STRIDE = 2
CAR_SPAWN_RAMP_FRAMES = 90
ROAD_EXIT_PAD = 28
PLAYER_SPAWN_PAD = 280
SPAWN_MIN_ROAD_FRAC = 0.42
SPAWN_MAX_BLOCK_FRAC = 0.06
TURN_CHANCE = 0.22
TURN_HUB_DIST = 28
TURN_HUB_HOLD_DIST = 8
TURN_OVERSHOOT_ABORT = 22
TURN_PIVOT_SPEED_FRAC = 0.42
TURN_DRIFT_SPEED_FRAC = 0.82
TURN_SETTLE_FRAMES = 8
TURN_MIN_STEP_FRAC = 0.42
TURN_MIN_ARC_LEN = 48.0
TURN_SIGNAL_LEAD_DIST = max(CAR_WIDTH, CAR_HEIGHT) * 2 + 24
TURN_ABORT_FRAMES = 150
TURN_SIGNAL_STUCK_FRAMES = 54
TURN_PATH_BLOCKED_ABORT_FRAMES = 45
TURN_PATH_SAMPLES = 9
TURN_CORRIDOR_PAD = 44
TURN_RESERVE_PAD = 18
TURN_OVERLAP_ABORT_FRAMES = 12
TURN_STALL_ABORT_FRAMES = 18
TURN_HOLD_ZONE_RESET_FRAMES = 2
TURN_HOLD_RETRY_FRAMES = 18
TURN_TO_HUB_WAIT_ABORT_FRAMES = 15
TURN_TO_HUB_ABORT_FRAMES = 30
# Higher spawn_id aborts after this many stalled overlap frames (arc uses half, min 8).
# Swept across seeds 42, 12345, 1890416619, 999999 — 20 keeps dual-turn overlap < 6 frames.
TURN_PEER_YIELD_FRAMES = 20
TURN_ABORT_COOLDOWN_FRAMES = 90
SHELL_PENETRATION_MAX_NUDGE = 10
SHELL_PENETRATION_PASSES = 4
INTERSECTION_SHELL_PAD = 32
OFF_ROAD_REMOVE_FRAMES = 72
NETWORK_ROAD_PAD = 64
NETWORK_IX_PAD = 32
STREET_CORRIDOR_PAD = 40
ROAD_SURFACE_PAD = 6
MIN_ON_ROAD_FRAC = 0.10
CAR_EXIT_DESPAWN_MARGIN = 36
EXIT_CORRIDOR_LATERAL = 72
MAX_SPAWN_DEFER_FRAMES = 240
SPAWN_RETRY_SLOTS = 48
EDGE_SPAWN_QUEUE_CAP = 2
RESPAWN_PENDING_CAP = 48
RESPAWN_EVENT_ID_BASE = 900_000
MAX_RESPAWNS_PER_FRAME = 4
RESPAWN_DELAY_FRAMES = 36
RESPAWN_RETRY_FRAMES = 20
RESPAWN_POSE_TRIES = 2
CAR_NEARBY_PAD = 96
SPATIAL_CELL = 128
LANE_BUCKET_SIZE = 52
SURFACE_CHECK_INTERVAL = 4
IX_QUERY_PAD = 100
PLAYER_CAR_QUERY_PAD = 220
FRAME_RECORD_VIEW_PAD = 120
REPLAY_RECORD_EXTRA_PAD = 400
REPLAY_MAX_CARS = 56
HONK_CHECK_INTERVAL = 3
ENABLE_CAR_DIAGNOSTICS = os.environ.get("PATHWISE_CAR_DIAGNOSTICS", "").lower() in (
    "1",
    "true",
    "yes",
)
ENABLE_PERF_PROFILE = perf_profile_enabled()
perf_profiler = PerfProfiler(enabled=ENABLE_PERF_PROFILE)
# Hard stop / gridlock rules (intersection locks). Keep off for flowing traffic.
ENABLE_CAR_CAR_COLLISION = False
# Slow, cap movement, and nudge apart so cars do not ghost through each other.
ENABLE_CAR_CAR_SOFT_AVOIDANCE = True
CAR_SOFT_FOLLOW_RANGE = 150
CAR_SOFT_STOP_GAP = 14
CAP_ALL_CARS_ITERATIONS = 4
TURN_PEER_QUERY_PAD = 48
SPAWN_RETRY_BUDGET_PER_FRAME = 2
TRAFFIC_DRAW_TIMER_BAR = False

def _smoothstep(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return t * t * (3.0 - 2.0 * t)


def _lerp_angle_deg(a: float, b: float, t: float) -> float:
    delta = (b - a + 180.0) % 360.0 - 180.0
    return a + delta * t


# --- Init (display/fonts owned by PathwiseWindow) ---
HONK_DURATION = 0.55
HONK_COOLDOWN = 1.1
HONK_CLOSE_PAD = 72


def player_on_car_red_crosswalk_body(player_body_rect, road_states):
    for state in road_states:
        if collide(state["crosswalk"], player_body_rect) and state["light_state"] == "red":
            return True
    return False


def player_on_car_red_crosswalk(player_rect, road_states):
    return player_on_car_red_crosswalk_body(
        sprites.player_body_hitbox(player_rect), road_states
    )


def player_mostly_on_legal_crosswalk(body_rect, road_states, min_frac=0.45):
    """True when most of the body overlap is on crosswalks where cars have red (legal ped crossing)."""
    a = body_rect.width * body_rect.height
    if a <= 0:
        return False
    on_red = 0
    for state in road_states:
        if state["light_state"] != "red":
            continue
        inter = clip_rect(body_rect, state["crosswalk"])
        on_red += inter.width * inter.height
    on_red = min(on_red, a)
    return on_red >= a * min_frac


def player_hits_any_car(player, cars_group, spatial=None, scratch: list | None = None):
    pb = sprites.player_body_hitbox(player.rect)
    if spatial is not None and scratch is not None:
        for car in spatial.nearby(pb, PLAYER_CAR_QUERY_PAD, scratch):
            if collide(car._collision_shell, pb):
                return True
        return False
    for car in cars_group:
        if collide(car._collision_shell, pb):
            return True
    return False


def _cars_near_player(player_body: Rect, spatial, scratch: list) -> list:
    return spatial.nearby(player_body, PLAYER_CAR_QUERY_PAD, scratch)


def _view_rect_for_camera(camera_offset: tuple[int, int]) -> Rect:
    return Rect(
        camera_offset[0] - FRAME_RECORD_VIEW_PAD,
        camera_offset[1] - FRAME_RECORD_VIEW_PAD,
        WIDTH + FRAME_RECORD_VIEW_PAD * 2,
        HEIGHT + FRAME_RECORD_VIEW_PAD * 2,
    )


def _replay_view_rect_for_camera(camera_offset: tuple[int, int]) -> Rect:
    """Wider than draw view so replay shows cars before they enter the screen."""
    return _view_rect_for_camera(camera_offset).inflate(
        REPLAY_RECORD_EXTRA_PAD, REPLAY_RECORD_EXTRA_PAD
    )


def _cars_in_view(car_list, view_rect: Rect) -> list:
    return [c for c in car_list if c.alive() and collide(view_rect, c.rect)]


def _cars_for_replay(car_list, player_center: tuple[int, int]) -> list:
    """Record the full active fleet for replay (nearest first when capped)."""
    alive = [c for c in car_list if c.alive()]
    if len(alive) <= REPLAY_MAX_CARS:
        return alive
    px, py = player_center
    alive.sort(
        key=lambda car: (car.rect.centerx - px) ** 2 + (car.rect.centery - py) ** 2
    )
    return alive[:REPLAY_MAX_CARS]


def _cap_cars_near_player(
    car_list,
    view_rect: Rect,
    player_center: tuple[int, int],
    max_cars: int,
) -> list:
    """Emergency cap when too many cars share the viewport (draw perf safety)."""
    in_view = _cars_in_view(car_list, view_rect)
    if len(in_view) <= max_cars:
        return in_view
    px, py = player_center
    in_view.sort(
        key=lambda car: (car.rect.centerx - px) ** 2 + (car.rect.centery - py) ** 2
    )
    return in_view[:max_cars]


def cars_should_respect_player(player_on_road, player_on_crosswalk, on_car_red: bool):
    """Yield / stop for player only when they occupy the road or cross legally on red-for-cars."""
    if player_on_crosswalk:
        return on_car_red
    return player_on_road


def player_feet_on_road(player_rect, roads):
    """Lower body footprint must overlap pavement (visual on road, not sidewalk)."""
    feet = Rect(
        int(player_rect.x + player_rect.width * 0.18),
        int(player_rect.centery - player_rect.height * 0.05),
        int(player_rect.width * 0.64),
        int(player_rect.height * 0.42),
    )
    return any(collide(road.rect, feet) for road in roads)


def should_honk_at_player_precomputed(
    feet_on_road: bool,
    mostly_on_legal_crosswalk: bool,
    on_crosswalk: bool,
    on_car_red_crosswalk: bool,
) -> bool:
    """Honk policy using values computed once per frame (avoid O(cars * roads) work)."""
    if not feet_on_road:
        return False
    if mostly_on_legal_crosswalk:
        return False
    if on_crosswalk and on_car_red_crosswalk:
        return False
    return True


def update_light_timers(road_states, elapsed):
    cycle = _LIGHT_GREEN + _LIGHT_YELLOW + _LIGHT_RED
    for state in road_states:
        t = (elapsed + state["phase_offset"]) % cycle
        light = state["light_state"]
        if light == "green":
            state["seconds_to_change"] = _LIGHT_GREEN - t
            state["next_light"] = "yellow"
        elif light == "yellow":
            state["seconds_to_change"] = _LIGHT_GREEN + _LIGHT_YELLOW - t
            state["next_light"] = "red"
        else:
            state["seconds_to_change"] = cycle - t
            state["next_light"] = "green"
        turn_state, turn_secs = protected_turn_light_at(
            elapsed,
            state["phase_offset"],
            _LIGHT_GREEN,
            _LIGHT_YELLOW,
            _LIGHT_RED,
        )
        state["turn_light_state"] = turn_state
        state["turn_seconds_to_change"] = turn_secs
        state["next_turn_light"] = "red" if turn_state == "green" else "green"


def serialize_lights_for_frame(road_states):
    return [
        {
            "s": state["light_state"],
            "ts": state.get("turn_light_state", "red"),
            "in": round(state.get("seconds_to_change", 0), 1),
            "tin": round(state.get("turn_seconds_to_change", 0), 1),
            "next": state.get("next_light", "green"),
            "tnext": state.get("next_turn_light", "green"),
        }
        for state in road_states
    ]


@dataclass(frozen=True)
class CarSpawnOrigin:
    """Entry point for respawn when a car is removed (unchanged after turns)."""
    road_index: int
    direction: int
    along_frac: float
    phase: str


@dataclass(frozen=True)
class RespawnRequest:
    origin: CarSpawnOrigin
    due_frame: int


class CarSpatialIndex:
    """Uniform grid so each car only checks nearby peers (not the full fleet)."""

    __slots__ = ("cell", "_cells", "_stamp", "_rebuild_counter")

    def __init__(self, cell_size: int = SPATIAL_CELL):
        self.cell = cell_size
        self._cells: dict[tuple[int, int], list] = {}
        self._stamp = 0
        self._rebuild_counter = 0

    def clear(self) -> None:
        self._cells.clear()

    def _cell_keys_for_shell(self, shell: Rect) -> list[tuple[int, int]]:
        cs = self.cell
        x0 = shell.left // cs
        x1 = shell.right // cs
        y0 = shell.top // cs
        y1 = shell.bottom // cs
        keys: list[tuple[int, int]] = []
        for cx in range(x0, x1 + 1):
            for cy in range(y0, y1 + 1):
                keys.append((cx, cy))
        return keys

    def _remove_car_from_cells(self, car) -> None:
        keys = getattr(car, "_spatial_cell_keys", ())
        if not keys:
            return
        cells = self._cells
        for key in keys:
            bucket = cells.get(key)
            if bucket is not None:
                while car in bucket:
                    bucket.remove(car)
                if not bucket:
                    del cells[key]
        car._spatial_cell_keys = ()
        car._spatial_stamp = 0

    def _insert_car_into_cells(self, car) -> None:
        if not car.alive():
            self._remove_car_from_cells(car)
            return
        shell = car._collision_shell
        cells = self._cells
        keys = self._cell_keys_for_shell(shell)
        for key in keys:
            bucket = cells.get(key)
            if bucket is None:
                cells[key] = [car]
            elif car not in bucket:
                bucket.append(car)
        car._spatial_cell_keys = tuple(keys)

    def relocate_car(self, car) -> None:
        self._remove_car_from_cells(car)
        self._insert_car_into_cells(car)

    def rebuild(self, car_list) -> None:
        self._rebuild_counter += 1
        cells = self._cells
        for bucket in cells.values():
            bucket.clear()
        for car in car_list:
            if not car.alive():
                car._spatial_cell_keys = ()
                continue
            self._insert_car_into_cells(car)

    def _gather(self, rect: Rect, pad: int, out: list) -> list:
        out.clear()
        self._stamp += 1
        if self._stamp > 1_000_000_000:
            self._stamp = 1
        stamp = self._stamp
        cs = self.cell
        r = rect.inflate(pad, pad)
        x0 = r.left // cs
        x1 = r.right // cs
        y0 = r.top // cs
        y1 = r.bottom // cs
        cells = self._cells
        for cx in range(x0, x1 + 1):
            for cy in range(y0, y1 + 1):
                for car in cells.get((cx, cy), ()):
                    if car._spatial_stamp == stamp:
                        continue
                    car._spatial_stamp = stamp
                    out.append(car)
        return out

    def nearby(self, rect: Rect, pad: int, scratch: list) -> list:
        return self._gather(rect, pad, scratch)


_frame_car_spatial = CarSpatialIndex()
_frame_nearby_scratch: list = []
_frame_player_car_scratch: list = []
_frame_lane_scratch: list = []
_frame_car_list_scratch: list = []
_frame_draw_sprites_scratch: list = []


def _resolve_all_shell_overlaps(car_list: list) -> None:
    """One deterministic separation pass after all cars move."""
    if not ENABLE_CAR_CAR_SOFT_AVOIDANCE:
        return
    alive = sorted((c for c in car_list if c.alive()), key=lambda c: c.spawn_id)
    for car in alive:
        # Arc turners stay on the Bezier; post-frame nudging causes visible path jitter.
        if car._turn_phase in ("turning", "settling"):
            continue
        car._resolve_shell_penetration(
            alive,
            max_nudge=SHELL_PENETRATION_MAX_NUDGE,
            passes=SHELL_PENETRATION_PASSES,
        )


# --- Entities ---
class Car(Entity):
    def __init__(
        self,
        x,
        y,
        speed,
        vertical=False,
        archetype_index=None,
        spawn_id=0,
        road_index=None,
        spawn_origin: CarSpawnOrigin | None = None,
    ):
        super().__init__()
        self.direction = 1 if speed >= 0 else -1
        self.vertical = vertical
        self.spawn_id = spawn_id
        self.road_index = road_index
        self._spawn_origin = spawn_origin
        if archetype_index is None:
            archetype_index = sprites.pick_random_archetype_index()
        self.archetype_index = archetype_index
        self.image = sprites.make_car_surface(
            vertical=vertical,
            direction=self.direction,
            archetype_index=self.archetype_index,
        )
        self.rect = Rect(x, y, self.image.get_width(), self.image.get_height())
        self.base_speed = abs(speed)
        self.acceleration = 0.16
        self.brake_strength = 0.42
        self.honk_until = 0.0
        self._last_honk_time = -999.0
        self.honk_risk_pending = False
        self.honk_reason = None
        self._stopped_frames = 0
        self._intersection_stuck_frames = 0
        self._gridlock_frames = 0
        self._turn_wait_frames = 0
        self._turn_overlap_frames = 0
        self._turn_hold_frames = 0
        self._spawn_age = 0
        self.turn_signal = 0
        self._turn_zone_key = None
        self._turn_exit = None
        self._turn_hub = None
        self._turn_phase = "none"
        self._turn_blend = 0.0
        self._turn_px = 0.0
        self._turn_py = 0.0
        self._turn_side = max(CAR_WIDTH, CAR_HEIGHT)
        self._turn_arc_len = 0.0
        self._turn_arc_travel = 0.0
        self._turn_angle_start = 0.0
        self._turn_angle_end = 0.0
        self._turn_angle_draw_q = -999
        self._turn_display_angle = 0.0
        self._turn_arc_start = (0.0, 0.0)
        self._turn_arc_mid = (0.0, 0.0)
        self._turn_arc_end = (0.0, 0.0)
        self._turn_settle_blend = 0.0
        self._turn_settle_target = (0.0, 0.0)
        self._turn_entry_vertical = vertical
        self._turn_entry_direction = self.direction
        self._turn_blocked_frames = 0
        self._turn_stall_frames = 0
        self._turn_stall_center = None
        self._turn_peer_stall_frames = 0
        self._turn_abort_cooldown = 0
        self._off_road_frames = 0
        self._spatial_stamp = 0
        self._spatial_cell_keys: tuple = ()
        self._shell_sync_key = None
        self._body_rect_scratch = Rect(0, 0, self.rect.width, self.rect.height)
        self._frame_move_peers: list | None = None
        self._collision_shell = sprites.car_collision_rect(self.rect, self.vertical)
        self._last_good_center = self.rect.center
        self.current_speed = 0.0
        self.speed = 0.0

    def _effective_travel(self) -> tuple[bool, int]:
        if self._turn_phase in ("to_hub", "turning", "settling") and self._turn_exit:
            return self._turn_entry_vertical, self._turn_entry_direction
        return self.vertical, self.direction

    def _sync_collision_shell(self, force: bool = False):
        if self._turn_phase in ("turning", "settling"):
            cx, cy = round(self._turn_px), round(self._turn_py)
            key = (cx, cy, self._turn_side, 2)
            if not force and key == self._shell_sync_key:
                return
            self._shell_sync_key = key
            body = Rect(0, 0, self._turn_side, self._turn_side)
            body.center = (cx, cy)
            self._collision_shell = sprites.car_collision_rect_turn(body)
            return
        key = (self.rect.x, self.rect.y, 0, self.vertical)
        if not force and key == self._shell_sync_key:
            return
        self._shell_sync_key = key
        self._collision_shell = sprites.car_collision_rect(self.rect, self.vertical)

    def _snap_center_to_left_lane(self, roads, max_nudge: int | None = 8):
        """Align to keep-left lane center on the axis perpendicular to travel."""
        if max_nudge == 0:
            return
        if self.road_index is None or self.road_index >= len(roads):
            return
        road = roads[self.road_index]
        tcx, tcy = lane_center_xy(road, self.direction)
        if road.direction == "vertical":
            if max_nudge is None:
                self.rect.centery = tcy
            else:
                dy = max(-max_nudge, min(max_nudge, tcy - self.rect.centery))
                self.rect.centery += dy
        else:
            if max_nudge is None:
                self.rect.centerx = tcx
            else:
                dx = max(-max_nudge, min(max_nudge, tcx - self.rect.centerx))
                self.rect.centerx += dx

    def _shell_hits_any_car(self, rect, vertical, peers, shell: Rect | None = None) -> bool:
        if shell is None:
            shell = sprites.car_collision_rect_into(rect, vertical, self._body_rect_scratch)
        for other in peers:
            if other is self:
                continue
            if collide(shell, other._collision_shell):
                return True
        return False

    def is_honking(self, game_time):
        return game_time < self.honk_until

    def trigger_honk(self, game_time, reason):
        if game_time - self._last_honk_time < HONK_COOLDOWN:
            return False
        self.honk_until = game_time + HONK_DURATION
        self._last_honk_time = game_time
        self.honk_reason = reason
        return True

    def _player_in_travel_lane(self, player_body_rect):
        if self.vertical:
            lane_gap = abs(player_body_rect.centerx - self.rect.centerx)
            ahead = (player_body_rect.centery - self.rect.centery) * self.direction
        else:
            lane_gap = abs(player_body_rect.centery - self.rect.centery)
            ahead = (player_body_rect.centerx - self.rect.centerx) * self.direction
        return lane_gap < 55 and 0 < ahead < 250

    def _player_blocking_lane(self, player_body_rect):
        if collide(self._collision_shell, player_body_rect):
            return True
        if self.vertical:
            lane_gap = abs(player_body_rect.centerx - self.rect.centerx)
            ahead = (player_body_rect.centery - self.rect.centery) * self.direction
        else:
            lane_gap = abs(player_body_rect.centery - self.rect.centery)
            ahead = (player_body_rect.centerx - self.rect.centerx) * self.direction
        return lane_gap < 50 and 0 <= ahead < 130

    def evaluate_honk(
        self, player_body_rect, player_on_crosswalk: bool, honk_allowed: bool, game_time
    ):
        self.honk_risk_pending = False
        if not honk_allowed:
            return

        too_close = collide(
            self._collision_shell.inflate(HONK_CLOSE_PAD, HONK_CLOSE_PAD),
            player_body_rect,
        )
        blocked_by_player = (
            self.current_speed < self.base_speed * 0.25
            and self._player_blocking_lane(player_body_rect)
        )
        jaywalking = (
            not player_on_crosswalk
            and self._player_in_travel_lane(player_body_rect)
            and self.current_speed >= self.base_speed * 0.15
        )

        if too_close and self.trigger_honk(game_time, "close"):
            self.honk_risk_pending = True
        elif blocked_by_player and self.trigger_honk(game_time, "blocked"):
            self.honk_risk_pending = True
        elif jaywalking and self.trigger_honk(game_time, "jaywalk"):
            self.honk_risk_pending = True

    def _distance_to_other(self, other):
        v, d = self._effective_travel()
        my = self._collision_shell
        ot = other._collision_shell
        if v:
            ahead = (ot.centery - my.centery) * d
            lane_gap = abs(ot.centerx - my.centerx)
        else:
            ahead = (ot.centerx - my.centerx) * d
            lane_gap = abs(ot.centery - my.centery)
        return ahead, lane_gap

    def _apply_lane_follow_speed(self, lane_peers, desired_speed: float) -> float:
        """Match speed to slower traffic ahead in-lane (no hard stop)."""
        for other in lane_peers:
            if other is self or other.vertical != self.vertical or other.direction != self.direction:
                continue
            if not self._same_lane(other):
                continue
            ahead, _lane_gap = self._distance_to_other(other)
            if ahead <= 0 or ahead > CAR_SOFT_FOLLOW_RANGE:
                continue
            if ahead < 20:
                follow_cap = 0.0 if other.current_speed < 0.4 else other.current_speed * 0.65
                desired_speed = min(desired_speed, follow_cap)
            else:
                follow_cap = other.current_speed * max(0.45, (ahead - 16) / 80)
                desired_speed = min(desired_speed, max(follow_cap, CAR_CREEP_SPEED))
        return desired_speed

    def _other_in_active_turn(self, other) -> bool:
        """Only committed turn phases block peers — blinkers alone must not gridlock."""
        return other._turn_phase in ("to_hub", "turning", "settling")

    def _committed_intersection_turn(self, intersection_zones) -> bool:
        """Turn plan committed only when executing the arc or signaling inside the box."""
        if self._turn_phase in ("turning", "settling"):
            return True
        if not intersection_zones:
            return False
        if self._turn_phase == "to_hub":
            if self._rect_in_intersection(self.rect, intersection_zones):
                return self.current_speed >= 0.12
            if self._turn_hub is not None and self.current_speed >= 0.12:
                hx, hy = self._turn_hub
                dist = math.hypot(self.rect.centerx - hx, self.rect.centery - hy)
                lead = TURN_HUB_DIST + TURN_SIGNAL_LEAD_DIST // 3
                return dist <= lead + 8
            return False
        return (
            self.turn_signal != 0
            and self._rect_in_intersection(self.rect, intersection_zones)
        )

    def _conflicts_with_committed_turner(
        self, other, intersection_zones, *, pad: int = 10
    ) -> bool:
        if not other._committed_intersection_turn(intersection_zones):
            return False
        if intersection_zones and not self._approaching_or_in_intersection(
            intersection_zones
        ):
            return False
        if rects_overlap(self._collision_shell, other._collision_shell):
            return True
        return rects_overlap(
            self._collision_shell.inflate(pad, pad),
            other._collision_shell.inflate(pad, pad),
        )

    def _planned_move_conflicts_active_turn(
        self, next_rect, peers, intersection_zones
    ) -> bool:
        """Block on turner shells; corridor reservation only for same-axis + active arc."""
        if self._turn_phase in ("to_hub", "turning", "settling"):
            return False
        my = sprites.car_collision_rect_into(
            next_rect, self.vertical, self._body_rect_scratch
        )
        for other in peers:
            if other is self:
                continue
            oc = other._collision_shell
            if other._committed_intersection_turn(intersection_zones):
                if rects_overlap(my.inflate(28, 28), oc):
                    return True
                if other._turn_phase in ("turning", "settling") and intersection_zones:
                    reserved = other._turn_reserved_rect(intersection_zones)
                    if reserved is not None and rects_overlap(my, reserved):
                        return True
                continue
            if rects_overlap(my, oc):
                if other._turn_phase in ("to_hub", "turning", "settling"):
                    return True
                continue
            if other._turn_phase not in ("turning", "settling"):
                continue
            if other.vertical != self.vertical:
                continue
            if intersection_zones:
                reserved = other._turn_reserved_rect(intersection_zones)
                if reserved is not None and rects_overlap(my, reserved):
                    return True
        return False

    def _both_active_turn_peers_at_intersection(
        self, other, intersection_zones
    ) -> bool:
        if self._turn_phase not in ("to_hub", "turning", "settling"):
            return False
        if other._turn_phase not in ("to_hub", "turning", "settling"):
            return False
        if not intersection_zones:
            return True
        self_ix = self._rect_in_intersection(self.rect, intersection_zones) or (
            self._approaching_or_in_intersection(intersection_zones)
        )
        other_ix = other._rect_in_intersection(other.rect, intersection_zones) or (
            other._approaching_or_in_intersection(intersection_zones)
        )
        return self_ix and other_ix

    def _turn_shell_overlaps_peer(
        self, peers, intersection_zones=None
    ) -> bool:
        shell = self._collision_shell
        for other in peers:
            if other is self or not other.alive():
                continue
            if collide(shell, other._collision_shell):
                return True
        return False

    def _mitigate_turn_peer_deadlock(
        self, peers, intersection_zones, roads
    ) -> None:
        """Higher spawn_id yields when two turners overlap in the same intersection."""
        if self._turn_phase not in ("to_hub", "turning", "settling"):
            self._turn_peer_stall_frames = 0
            return
        blocked_by_priority_peer = False
        for other in peers:
            if other is self or not other.alive():
                continue
            if not self._both_active_turn_peers_at_intersection(
                other, intersection_zones
            ):
                continue
            if not rects_overlap(self._collision_shell, other._collision_shell):
                continue
            if other.spawn_id < self.spawn_id:
                blocked_by_priority_peer = True
                break
        if blocked_by_priority_peer:
            self._turn_peer_stall_frames += 1
        elif self.current_speed >= 0.45:
            self._turn_peer_stall_frames = max(0, self._turn_peer_stall_frames - 2)
        else:
            self._turn_peer_stall_frames = 0
        yield_frames = TURN_PEER_YIELD_FRAMES
        if self._turn_phase in ("turning", "settling"):
            yield_frames = max(8, TURN_PEER_YIELD_FRAMES // 2)
        if self._turn_peer_stall_frames >= yield_frames:
            self._hold_turn_and_replan(
                intersection_zones,
                roads,
                peers,
            )
            self._turn_peer_stall_frames = 0

    def _soft_overlap_creep_cap(
        self, next_rect, move_peers, lane_peers, intersection_zones=None
    ) -> float | None:
        """Max creep speed when the planned move still overlaps another car shell."""
        ix_creep = self._intersection_stuck_frames >= INTERSECTION_STUCK_CREEP_FRAMES
        if intersection_zones and self._planned_move_conflicts_active_turn(
            next_rect, move_peers, intersection_zones
        ):
            if ix_creep:
                return CAR_CREEP_SPEED * 0.45
            return 0.0
        if not self._shell_hits_any_car(next_rect, self.vertical, move_peers):
            return None
        my = sprites.car_collision_rect(next_rect, self.vertical)
        for other in move_peers:
            if other is self:
                continue
            if self._other_in_active_turn(other) and rects_overlap(
                my, other._collision_shell
            ):
                return 0.0
        min_gap = 1e9
        for other in lane_peers:
            if other is self:
                continue
            if other.vertical != self.vertical or other.direction != self.direction:
                continue
            if not self._same_lane(other, CAR_BLOCK_LANE_GAP):
                continue
            gap, _ = self._distance_to_other(other)
            if gap > 0:
                min_gap = min(min_gap, gap)
        if min_gap <= CAR_SOFT_STOP_GAP:
            if ix_creep:
                return CAR_CREEP_SPEED * 0.3
            return 0.0
        if min_gap < 28:
            return CAR_CREEP_SPEED * 0.35
        if min_gap < 52:
            return CAR_CREEP_SPEED * 0.7
        return CAR_CREEP_SPEED

    def _same_lane(self, other, max_lane_gap=CAR_FOLLOW_LANE_GAP):
        sv, sd = self._effective_travel()
        ov, od = other._effective_travel()
        if sv != ov or sd != od:
            return False
        _, lane_gap = self._distance_to_other(other)
        return lane_gap < max_lane_gap

    def _in_crosswalk_lane(self, state):
        if self.vertical:
            return abs(self.rect.centerx - state["crosswalk"].centerx) < 50
        return abs(self.rect.centery - state["crosswalk"].centery) < 50

    def _distance_to_intersection_entry(self, zone):
        """Distance along travel to intersection entry; None if past or wrong side."""
        if self.vertical:
            if self.direction > 0:
                if self.rect.top >= zone.bottom:
                    return None
                return zone.top - self.rect.bottom
            if self.rect.bottom <= zone.top:
                return None
            return self.rect.top - zone.bottom
        if self.direction > 0:
            if self.rect.left >= zone.right:
                return None
            return zone.left - self.rect.right
        if self.rect.right <= zone.left:
            return None
        return self.rect.left - zone.right

    def _zone_on_entry_route(self, zone, roads) -> bool:
        if self.road_index is not None and 0 <= self.road_index < len(roads):
            return collide(roads[self.road_index].rect, zone)
        for road in roads:
            if self._matches_road_travel(road) and collide(road.rect, zone):
                return True
        return False

    def _intersection_zone_for_turn_planning(self, intersection_zones, roads):
        if not intersection_zones:
            return None
        in_zone = self._intersection_zone_at(intersection_zones)
        if in_zone is not None:
            return in_zone
        best = None
        best_d = 1e9
        for zone in intersection_zones:
            if not self._zone_on_entry_route(zone, roads):
                continue
            d = self._distance_to_intersection_entry(zone)
            if d is None or d < 0 or d > TURN_SIGNAL_LEAD_DIST:
                continue
            if d < best_d:
                best_d = d
                best = zone
        return best

    def _approaching_or_in_intersection(self, intersection_zones, extra: int = 0) -> bool:
        if not intersection_zones:
            return False
        if self._rect_in_intersection(self.rect, intersection_zones):
            return True
        lead = TURN_SIGNAL_LEAD_DIST + extra
        for zone in intersection_zones:
            d = self._distance_to_intersection_entry(zone)
            if d is not None and 0 <= d < lead:
                return True
        return False

    def _pivot_exit_clear(
        self,
        roads,
        zone,
        exit_plan,
        peers,
        player_body_rect,
        ped_legal_crossing: bool,
    ) -> bool:
        idx, d, vertical = exit_plan
        px, py = pivot_center_at_intersection(roads, zone, idx, d, vertical)
        if vertical:
            pw, ph = CAR_HEIGHT, CAR_WIDTH
        else:
            pw, ph = CAR_WIDTH, CAR_HEIGHT
        probe = Rect(0, 0, pw, ph)
        probe.center = (px, py)
        probe_shell = sprites.car_collision_rect(probe, vertical)
        if ENABLE_CAR_CAR_COLLISION:
            for other in peers:
                if other is self:
                    continue
                if collide(probe_shell, other._collision_shell):
                    return False
            if not ped_legal_crossing and collide(probe_shell, player_body_rect):
                return False
        return True

    def _planned_turn_is_protected(self) -> bool:
        if self.turn_signal != 0:
            return True
        if not self._turn_exit:
            return False
        idx, d, exit_vertical = self._turn_exit
        entry_v = (
            self._turn_entry_vertical
            if self._turn_phase in ("turning", "settling")
            else self.vertical
        )
        entry_d = (
            self._turn_entry_direction
            if self._turn_phase in ("turning", "settling")
            else self.direction
        )
        return turn_side_from_exit(entry_v, entry_d, exit_vertical, d) != 0

    def _uses_turn_approach_light(self) -> bool:
        if self.turn_signal != 0:
            return True
        if self._turn_phase in ("to_hub", "turning", "settling"):
            return self._planned_turn_is_protected()
        return False

    def _effective_approach_light(self, state: dict) -> str:
        if self._uses_turn_approach_light():
            return state.get("turn_light_state", state.get("light_state", "green"))
        return state.get("light_state", "green")

    def _effective_seconds_to_change(self, state: dict) -> float:
        if self._uses_turn_approach_light():
            return float(state.get("turn_seconds_to_change", 0.0))
        return float(state.get("seconds_to_change", 0.0))

    def _maintain_turn_plan(
        self,
        roads,
        intersection_zones,
        peers,
        player_body_rect,
        ped_legal_crossing: bool,
        road_states=None,
    ) -> None:
        """Drop stale turn plans that block traffic or never start."""
        if self._turn_phase == "to_hub":
            self._turn_wait_frames += 1
            if self._turn_wait_frames >= TURN_TO_HUB_WAIT_ABORT_FRAMES:
                self._turn_phase = "none"
                self._turn_hub = None
                self._turn_wait_frames = 0
                self._turn_blocked_frames = 0
                self._hold_turn_and_replan(
                    intersection_zones,
                    roads,
                    peers,
                    player_body_rect,
                    ped_legal_crossing,
                )
                return
            if self._turn_exit and not self._turn_path_clear(
                peers,
                player_body_rect,
                ped_legal_crossing,
                intersection_zones=intersection_zones,
            ):
                if self._turn_wait_frames >= TURN_PATH_BLOCKED_ABORT_FRAMES:
                    self._hold_turn_and_replan(
                        intersection_zones,
                        roads,
                        peers,
                        player_body_rect,
                        ped_legal_crossing,
                    )
                return
            return
        if self._turn_phase in ("turning", "settling"):
            if self._turn_shell_overlaps_peer(peers, intersection_zones):
                self._turn_overlap_frames += 1
            elif self._turn_overlap_frames > 0:
                self._turn_overlap_frames = max(0, self._turn_overlap_frames - 2)
            if not self._turn_path_clear(
                peers,
                player_body_rect,
                ped_legal_crossing,
                t_max=0.35,
                intersection_zones=intersection_zones,
            ):
                self._turn_overlap_frames += 1
            if self._turn_overlap_frames >= TURN_OVERLAP_ABORT_FRAMES:
                self._turn_overlap_frames = max(
                    0, self._turn_overlap_frames - 2
                )
            return
        if self.turn_signal == 0 and self._turn_exit is None:
            self._turn_wait_frames = 0
            return
        if self.current_speed >= 0.35:
            self._turn_wait_frames = 0
            return
        if road_states and self._uses_turn_approach_light():
            approach = self._nearest_approach_state(road_states)
            if (
                approach is not None
                and self._effective_approach_light(approach) == "green"
                and self._turn_path_clear(
                    peers,
                    player_body_rect,
                    ped_legal_crossing,
                    intersection_zones=intersection_zones,
                )
            ):
                self._turn_wait_frames = max(0, self._turn_wait_frames - 3)
                return
        self._turn_wait_frames += 1
        if self._turn_exit and not self._turn_path_clear(
            peers,
            player_body_rect,
            ped_legal_crossing,
            intersection_zones=intersection_zones,
        ):
            if self._turn_wait_frames >= TURN_PATH_BLOCKED_ABORT_FRAMES:
                self._hold_turn_and_replan(
                    intersection_zones,
                    roads,
                    peers,
                    player_body_rect,
                    ped_legal_crossing,
                )
            return
        if self._turn_wait_frames >= TURN_SIGNAL_STUCK_FRAMES:
            self._hold_turn_and_replan(
                intersection_zones,
                roads,
                peers,
                player_body_rect,
                ped_legal_crossing,
            )

    def _hold_turn_and_replan(
        self,
        intersection_zones,
        roads,
        peers=None,
        player_body_rect=None,
        ped_legal_crossing: bool = True,
    ) -> None:
        """Blocked turn: stop and wait — keep blinker/plan, retry when path may clear."""
        peers = peers or []
        if player_body_rect is None:
            player_body_rect = Rect(0, 0, 1, 1)
        zone = self._intersection_zone_for_turn_planning(intersection_zones, roads)
        if zone is None:
            zone = self._intersection_zone_at(intersection_zones)
        in_ix = zone is not None and rects_overlap(self.rect, zone)
        committed_turn = self._turn_phase in ("turning", "settling") or (
            self._turn_phase == "to_hub" and in_ix
        )
        if committed_turn and in_ix:
            self._freeze_blocked_turn_in_intersection(
                intersection_zones,
                roads,
                peers,
                player_body_rect,
                ped_legal_crossing,
                zone,
            )
            return

        intended_signal = self.turn_signal
        intended_exit = self._turn_exit
        was_visual_turn = self._turn_phase in ("turning", "settling")
        if was_visual_turn:
            self._cancel_turn_visual()
        if self._turn_phase == "to_hub":
            self._turn_phase = "none"
            self._turn_hub = None
        self._turn_wait_frames = 0
        self._turn_overlap_frames = 0
        self._turn_blocked_frames = 0
        self._turn_stall_frames = 0
        self._turn_stall_center = None
        self._turn_hold_frames += 1
        if self._turn_hold_frames >= TURN_HOLD_ZONE_RESET_FRAMES:
            self._turn_zone_key = None
        self.turn_signal = intended_signal
        self._turn_exit = intended_exit
        if zone is not None:
            self._clamp_before_intersection(zone)
        if zone is not None and (
            self._turn_hold_frames == 1
            or self._turn_hold_frames % TURN_HOLD_RETRY_FRAMES == 0
        ):
            key = (zone.x, zone.y, zone.w, zone.h)
            preferred = intended_signal if intended_signal != 0 else 0
            sides = self._turn_side_candidates(preferred)
            if preferred != 0:
                sides = [side for side in sides if side != 0] or sides
            for turn_side in sides:
                if self._apply_turn_plan_for_side(
                    roads,
                    zone,
                    key,
                    turn_side,
                    peers,
                    player_body_rect,
                    ped_legal_crossing,
                ):
                    break
        self.current_speed = 0.0
        self.speed = 0.0

    def _freeze_blocked_turn_in_intersection(
        self,
        intersection_zones,
        roads,
        peers,
        player_body_rect,
        ped_legal_crossing,
        zone,
    ) -> None:
        """Pause mid-turn inside the intersection without snapping back to the stop line."""
        intended_signal = self.turn_signal
        intended_exit = self._turn_exit
        self._turn_hold_frames += 1
        self._turn_wait_frames = 0
        self._turn_blocked_frames = max(0, self._turn_blocked_frames - 2)
        self._turn_stall_frames = 0
        self._turn_stall_center = None
        self._turn_overlap_frames = max(0, self._turn_overlap_frames - 2)
        self.turn_signal = intended_signal
        self._turn_exit = intended_exit
        self.speed = 0.0
        self.current_speed = 0.0
        if self._turn_phase == "turning" and self._turn_arc_len > 0:
            t = self._turn_arc_travel / max(1e-6, self._turn_arc_len)
            ease = _smoothstep(min(1.0, t))
            angle = _lerp_angle_deg(
                self._turn_angle_start, self._turn_angle_end, ease
            )
            self._set_turn_visual(angle, self._turn_px, self._turn_py)
        elif self._turn_phase == "settling":
            self._set_turn_visual(
                self._turn_display_angle, self._turn_px, self._turn_py
            )
        self._sync_collision_shell(force=True)
        if self._turn_hold_frames % TURN_HOLD_RETRY_FRAMES == 0:
            key = (zone.x, zone.y, zone.w, zone.h)
            preferred = intended_signal if intended_signal != 0 else 0
            sides = self._turn_side_candidates(preferred)
            if preferred != 0:
                sides = [side for side in sides if side != 0] or sides
            for turn_side in sides:
                if self._apply_turn_plan_for_side(
                    roads,
                    zone,
                    key,
                    turn_side,
                    peers,
                    player_body_rect,
                    ped_legal_crossing,
                ):
                    break

    def _cancel_turn_visual(self) -> None:
        px = float(self._turn_px) if self._turn_phase in ("turning", "settling") else float(
            self.rect.centerx
        )
        py = float(self._turn_py) if self._turn_phase in ("turning", "settling") else float(
            self.rect.centery
        )
        self._turn_phase = "none"
        self._turn_hub = None
        self._turn_blend = 0.0
        self._turn_arc_len = 0.0
        self._turn_arc_travel = 0.0
        self._turn_angle_start = 0.0
        self._turn_angle_end = 0.0
        self._turn_angle_draw_q = -999
        self._turn_settle_blend = 0.0
        self._turn_entry_vertical = self.vertical
        self._turn_entry_direction = self.direction
        self._refresh_car_sprite()
        self.rect.center = (round(px), round(py))
        self._sync_collision_shell(force=True)

    def _abort_turn(self):
        was_visual_turn = self._turn_phase in ("turning", "settling")
        self.turn_signal = 0
        self._turn_wait_frames = 0
        self._turn_overlap_frames = 0
        self._turn_hold_frames = 0
        self._turn_exit = None
        self._turn_phase = "none"
        self._turn_hub = None
        self._turn_zone_key = None
        self._turn_blend = 0.0
        self._turn_arc_len = 0.0
        self._turn_arc_travel = 0.0
        self._turn_angle_start = 0.0
        self._turn_angle_end = 0.0
        self._turn_angle_draw_q = -999
        self._turn_settle_blend = 0.0
        self._turn_entry_vertical = self.vertical
        self._turn_entry_direction = self.direction
        self._turn_blocked_frames = 0
        self._turn_stall_frames = 0
        self._turn_stall_center = None
        self._turn_peer_stall_frames = 0
        self._turn_abort_cooldown = TURN_ABORT_COOLDOWN_FRAMES
        if was_visual_turn:
            self._refresh_car_sprite()
            self._sync_collision_shell(force=True)

    def _clamp_before_intersection(self, zone):
        if self.vertical:
            if self.direction > 0:
                self.rect.bottom = zone.top - STOP_LINE_GAP
            else:
                self.rect.top = zone.bottom + STOP_LINE_GAP
        else:
            if self.direction > 0:
                self.rect.right = zone.left - STOP_LINE_GAP
            else:
                self.rect.left = zone.right + STOP_LINE_GAP

    def _cap_next_rect_same_lane(self, next_rect, peers):
        """
        Never allow next_rect to overlap a same-direction car ahead in-lane.
        Uses shell hitboxes (matches drawn car body).
        """
        g = CAR_FOLLOW_SEP
        my = sprites.car_collision_rect_into(
            next_rect, self.vertical, self._body_rect_scratch
        )
        for other in peers:
            if other is self:
                continue
            if other.vertical != self.vertical or other.direction != self.direction:
                continue
            if not self._same_lane(other, CAR_FOLLOW_LANE_GAP):
                continue
            ahead, _ = self._distance_to_other(other)
            if ahead <= 0:
                continue
            oc = other._collision_shell
            if self.vertical:
                if self.direction > 0:
                    if my.bottom > oc.top - g:
                        next_rect.y -= my.bottom - (oc.top - g)
                else:
                    if my.top < oc.bottom + g:
                        next_rect.y += (oc.bottom + g) - my.top
            else:
                if self.direction > 0:
                    if my.right > oc.left - g:
                        next_rect.x -= my.right - (oc.left - g)
                else:
                    if my.left < oc.right + g:
                        next_rect.x += (oc.right + g) - my.left
        return next_rect

    def _cap_next_rect_all_cars(self, next_rect, peers):
        """Never advance into any car shell (all orientations) along our travel axis."""
        g = CAR_FOLLOW_SEP
        for _ in range(CAP_ALL_CARS_ITERATIONS):
            my = sprites.car_collision_rect_into(
                next_rect, self.vertical, self._body_rect_scratch
            )
            nudged = False
            for other in peers:
                if other is self:
                    continue
                oc = other._collision_shell
                if not collide(my, oc):
                    continue
                if self.vertical:
                    if self.direction > 0:
                        limit = oc.top - g
                        if my.bottom > limit:
                            next_rect.y -= my.bottom - limit
                            nudged = True
                    else:
                        limit = oc.bottom + g
                        if my.top < limit:
                            next_rect.y += limit - my.top
                            nudged = True
                else:
                    if self.direction > 0:
                        limit = oc.left - g
                        if my.right > limit:
                            next_rect.x -= my.right - limit
                            nudged = True
                    else:
                        limit = oc.right + g
                        if my.left < limit:
                            next_rect.x += limit - my.left
                            nudged = True
            if not nudged:
                break
        return next_rect

    def _hard_shell_overlap(self, rect, vertical, other, body_rect: Rect | None = None) -> bool:
        my = (
            body_rect
            if body_rect is not None
            else sprites.car_collision_rect_into(rect, vertical, self._body_rect_scratch)
        )
        oc = other._collision_shell.inflate(-PERP_OVERLAP_SHRINK, -PERP_OVERLAP_SHRINK)
        if oc.width < 3 or oc.height < 3:
            return False
        return collide(my, oc)

    def _ix_creep_has_priority(self, other, intersection_zones=None) -> bool:
        """Committed turners beat straight traffic; else alternate stuck creep."""
        self_turn = self._committed_intersection_turn(intersection_zones)
        other_turn = other._committed_intersection_turn(intersection_zones)
        if self_turn and not other_turn:
            return True
        if other_turn and not self_turn:
            return False
        if self._intersection_stuck_frames < INTERSECTION_STUCK_CREEP_FRAMES:
            return False
        if other._intersection_stuck_frames < INTERSECTION_STUCK_CREEP_FRAMES:
            return True
        return (self.spawn_id % 2) <= (other.spawn_id % 2)

    def _hard_block_after_cap(
        self,
        next_rect,
        peers,
        intersection_creep: bool,
        intersection_zones=None,
    ) -> bool:
        for other in peers:
            if other is self:
                continue
            if not self._hard_shell_overlap(next_rect, self.vertical, other):
                continue
            if other.vertical != self.vertical:
                if intersection_creep and self._ix_creep_has_priority(
                    other, intersection_zones
                ):
                    continue
                return True
            if other.direction == self.direction and self._same_lane(other, CAR_BLOCK_LANE_GAP):
                return True
        return False

    def _nudge_car_position(self, dx: int, dy: int) -> None:
        if dx == 0 and dy == 0:
            return
        self.rect.x += dx
        self.rect.y += dy
        if self._turn_phase in ("turning", "settling"):
            self._turn_px += dx
            self._turn_py += dy
        self._shell_sync_key = None

    def _resolve_shell_penetration(
        self,
        peers,
        *,
        max_nudge: int = SHELL_PENETRATION_MAX_NUDGE,
        passes: int = SHELL_PENETRATION_PASSES,
    ) -> None:
        """Push apart when collision shells overlap (any orientation)."""
        if not ENABLE_CAR_CAR_SOFT_AVOIDANCE:
            return
        g = CAR_FOLLOW_SEP
        for _ in range(passes):
            self._sync_collision_shell()
            my = self._collision_shell
            moved = False
            for other in peers:
                if other is self or not other.alive():
                    continue
                other._sync_collision_shell()
                oc = other._collision_shell
                if not collide(my, oc):
                    continue
                overlap_x = min(my.right, oc.right) - max(my.left, oc.left)
                overlap_y = min(my.bottom, oc.bottom) - max(my.top, oc.top)
                if overlap_x <= 0 or overlap_y <= 0:
                    continue
                dx = dy = 0
                if overlap_x <= overlap_y:
                    half = min(max_nudge, int(overlap_x * 0.55 + g))
                    dx = -half if my.centerx <= oc.centerx else half
                else:
                    half = min(max_nudge, int(overlap_y * 0.55 + g))
                    dy = -half if my.centery <= oc.centery else half
                if dx or dy:
                    self._nudge_car_position(dx, dy)
                    moved = True
                    self._sync_collision_shell()
                    my = self._collision_shell
            if not moved:
                break

    def _resolve_same_lane_penetration(self, peers):
        """If shells overlap a car ahead, push back (fixes frame-order / spawn glitches)."""
        g = CAR_FOLLOW_SEP
        my = sprites.car_collision_rect_into(
            self.rect, self.vertical, self._body_rect_scratch
        )
        for other in peers:
            if other is self:
                continue
            if other.vertical != self.vertical or other.direction != self.direction:
                continue
            if not self._same_lane(other, CAR_FOLLOW_LANE_GAP):
                continue
            ahead, _ = self._distance_to_other(other)
            if ahead <= 0:
                continue
            oc = other._collision_shell
            if not collide(my, oc):
                continue
            if self.vertical:
                if self.direction > 0:
                    if my.bottom > oc.top - g:
                        self.rect.y -= my.bottom - (oc.top - g)
                else:
                    if my.top < oc.bottom + g:
                        self.rect.y += (oc.bottom + g) - my.top
            else:
                if self.direction > 0:
                    if my.right > oc.left - g:
                        self.rect.x -= my.right - (oc.left - g)
                else:
                    if my.left < oc.right + g:
                        self.rect.x += (oc.right + g) - my.left

    def _rect_in_intersection(self, rect, intersection_zones):
        for zone in intersection_zones:
            if rects_overlap(zone, rect):
                return True
        return False

    def _near_intersection_bbox(self, intersection_zones, margin: int = 120) -> bool:
        if not intersection_zones:
            return False
        cx, cy = self.rect.centerx, self.rect.centery
        for zone in intersection_zones:
            if (
                zone.left - margin <= cx <= zone.right + margin
                and zone.top - margin <= cy <= zone.bottom + margin
            ):
                return True
        return False

    def _shell_overlaps_intersection(self, intersection_zones, pad: int = 0) -> bool:
        if not intersection_zones:
            return False
        shell = self._collision_shell
        if pad == INTERSECTION_SHELL_PAD and intersection_zones_shell:
            zones = intersection_zones_shell
        elif pad:
            for zone in intersection_zones:
                if rects_overlap(zone.inflate(pad, pad), shell):
                    return True
            return False
        else:
            zones = intersection_zones
        for zone in zones:
            if rects_overlap(zone, shell):
                return True
        return False

    def _matches_road_travel(self, road) -> bool:
        return (road.direction == "vertical" and not self.vertical) or (
            road.direction == "horizontal" and self.vertical
        )

    def _in_street_corridor(self, roads) -> bool:
        """Segment gaps between intersections — center can miss thin road rects."""
        cx, cy = self.rect.centerx, self.rect.centery
        for road in roads:
            if not self._matches_road_travel(road):
                continue
            band = road.rect.inflate(STREET_CORRIDOR_PAD, STREET_CORRIDOR_PAD)
            if band.collidepoint(cx, cy):
                return True
        return False

    def _corridor_lane_roads(self, roads) -> list:
        lane = self._lane_corridor_roads(roads)
        if lane:
            return lane
        if self.road_index is not None and 0 <= self.road_index < len(roads):
            r = roads[self.road_index]
            if self._matches_road_travel(r):
                return [r]
        return []

    def _lane_corridor_roads(self, roads) -> list:
        """Road segments on the same street row/column as this car (travel-matched)."""
        cx, cy = self.rect.centerx, self.rect.centery
        out = []
        for road in roads:
            if not self._matches_road_travel(road):
                continue
            band = road.rect.inflate(STREET_CORRIDOR_PAD, STREET_CORRIDOR_PAD)
            if band.collidepoint(cx, cy):
                out.append(road)
        return out

    def _far_extent_on_route(self, roads):
        """Leading edge of the last asphalt segment along current travel."""
        lane = self._corridor_lane_roads(roads)
        if not lane:
            return None
        if self.vertical:
            if self.direction > 0:
                return max(r.rect.bottom for r in lane)
            return min(r.rect.top for r in lane)
        if self.direction > 0:
            return max(r.rect.right for r in lane)
        return min(r.rect.left for r in lane)

    def _entry_corridor_rect(self, roads, world_rect):
        """Driveable strip from map edge to first road segment (ongoing edge spawns)."""
        lane = self._corridor_lane_roads(roads)
        if not lane:
            return None
        if self.vertical:
            cx = int(sum(r.rect.centerx for r in lane) / len(lane))
            half = max(EXIT_CORRIDOR_LATERAL, max(r.rect.width for r in lane) // 2 + 12)
            if self.direction > 0:
                bottom = min(r.rect.top for r in lane)
                h = bottom - (world_rect.top - CAR_EXIT_DESPAWN_MARGIN)
                if h <= 4:
                    return None
                return Rect(
                    cx - half, world_rect.top - CAR_EXIT_DESPAWN_MARGIN, half * 2, h
                )
            top = max(r.rect.bottom for r in lane)
            h = world_rect.bottom + CAR_EXIT_DESPAWN_MARGIN - top
            if h <= 4:
                return None
            return Rect(cx - half, top, half * 2, h)
        cy = int(sum(r.rect.centery for r in lane) / len(lane))
        half = max(EXIT_CORRIDOR_LATERAL, max(r.rect.height for r in lane) // 2 + 12)
        if self.direction > 0:
            right = min(r.rect.left for r in lane)
            w = right - (world_rect.left - CAR_EXIT_DESPAWN_MARGIN)
            if w <= 4:
                return None
            return Rect(
                world_rect.left - CAR_EXIT_DESPAWN_MARGIN, cy - half, w, half * 2
            )
        left = max(r.rect.right for r in lane)
        w = world_rect.right + CAR_EXIT_DESPAWN_MARGIN - left
        if w <= 4:
            return None
        return Rect(left, cy - half, w, half * 2)

    def _exit_corridor_rect(self, roads, world_rect):
        """Driveable strip from last road segment to the map edge (segmented maps)."""
        lane = self._corridor_lane_roads(roads)
        if not lane:
            return None
        if self.vertical:
            cx = int(sum(r.rect.centerx for r in lane) / len(lane))
            half = max(EXIT_CORRIDOR_LATERAL, max(r.rect.width for r in lane) // 2 + 12)
            if self.direction > 0:
                top = max(r.rect.bottom for r in lane)
                h = world_rect.bottom + CAR_EXIT_DESPAWN_MARGIN - top
                if h <= 4:
                    return None
                return Rect(cx - half, top, half * 2, h)
            bottom = min(r.rect.top for r in lane)
            h = bottom - world_rect.top + CAR_EXIT_DESPAWN_MARGIN
            if h <= 4:
                return None
            return Rect(cx - half, world_rect.top - CAR_EXIT_DESPAWN_MARGIN, half * 2, h)
        cy = int(sum(r.rect.centery for r in lane) / len(lane))
        half = max(EXIT_CORRIDOR_LATERAL, max(r.rect.height for r in lane) // 2 + 12)
        if self.direction > 0:
            left = max(r.rect.right for r in lane)
            w = world_rect.right + CAR_EXIT_DESPAWN_MARGIN - left
            if w <= 4:
                return None
            return Rect(left, cy - half, w, half * 2)
        right = min(r.rect.left for r in lane)
        w = right - world_rect.left + CAR_EXIT_DESPAWN_MARGIN
        if w <= 4:
            return None
        return Rect(world_rect.left - CAR_EXIT_DESPAWN_MARGIN, cy - half, w, half * 2)

    def _shell_asphalt_overlap_frac(
        self, roads, intersection_zones, road_subset: list | None = None
    ) -> float:
        """Strict overlap with real road/intersection geometry (no huge inflate)."""
        shell = self._collision_shell
        area = max(1, shell.width * shell.height)
        on = 0
        pad = ROAD_SURFACE_PAD
        check = road_subset if road_subset is not None else roads
        for road in check:
            r = road.rect
            if (
                shell.right < r.left - pad
                or shell.left > r.right + pad
                or shell.bottom < r.top - pad
                or shell.top > r.bottom + pad
            ):
                continue
            on += _rect_overlap_area(shell, r.inflate(pad, pad))
            if on / area >= MIN_ON_ROAD_FRAC:
                return min(1.0, on / area)
        for zone in intersection_zones or []:
            if not collide(shell, zone):
                continue
            on += _rect_overlap_area(shell, zone)
            if on / area >= MIN_ON_ROAD_FRAC:
                return min(1.0, on / area)
        return min(1.0, on / area)

    def _is_on_drivable_surface(self, roads, intersection_zones, world_rect) -> bool:
        """True only when shell actually touches asphalt, an intersection, or exit lane."""
        if self._shell_overlaps_intersection(
            intersection_zones, INTERSECTION_SHELL_PAD
        ):
            return True
        if self._in_street_corridor(roads):
            return True
        if self._shell_asphalt_overlap_frac(roads, intersection_zones) >= MIN_ON_ROAD_FRAC:
            return True
        if world_rect is not None and self._off_road_frames > 0:
            for corridor in (
                self._entry_corridor_rect(roads, world_rect),
                self._exit_corridor_rect(roads, world_rect),
            ):
                if corridor is not None and collide(corridor, self._collision_shell):
                    return True
        return False

    def _on_traffic_network(self, roads, intersection_zones, world_rect=None) -> bool:
        """Generous check for anchoring only (segment gaps); not used for despawn."""
        shell = self._collision_shell
        for road in roads:
            if collide(road.rect.inflate(NETWORK_ROAD_PAD, NETWORK_ROAD_PAD), shell):
                return True
        if self._in_street_corridor(roads):
            return True
        if world_rect is not None:
            for corridor in (
                self._entry_corridor_rect(roads, world_rect),
                self._exit_corridor_rect(roads, world_rect),
            ):
                if corridor is not None and collide(corridor, shell):
                    return True
        if intersection_zones:
            for zone in intersection_zones:
                z = zone.inflate(NETWORK_IX_PAD, NETWORK_IX_PAD)
                if collide(z, shell):
                    return True
        return False

    def _anchor_network_position(self, roads, intersection_zones, world_rect=None):
        if self._is_on_drivable_surface(roads, intersection_zones, world_rect):
            self._last_good_center = self.rect.center

    def _restore_if_orphaned(self, roads, intersection_zones, world_rect=None):
        if self._is_on_drivable_surface(roads, intersection_zones, world_rect):
            return
        # Off road: do not snap back; removal runs in _should_remove_car.

    def _refresh_car_sprite(self):
        center = self.rect.center
        self.image = sprites.make_car_surface(
            vertical=self.vertical,
            direction=self.direction,
            archetype_index=self.archetype_index,
        )
        self.rect = Rect(0, 0, self.image.get_width(), self.image.get_height())
        self.rect.center = center
        self._shell_sync_key = None

    def _hub_travel_offset(self) -> float:
        """Signed distance from hub along entry travel (+ = past hub)."""
        if self._turn_hub is None:
            return 0.0
        hx, hy = self._turn_hub
        fx, fy = travel_vector(self.vertical, self.direction)
        return (self.rect.centerx - hx) * fx + (self.rect.centery - hy) * fy

    def _snap_to_hub_approach(self, max_past: float = 0.0):
        """Pull back if the car rolled past the hub while waiting to turn."""
        if self._turn_hub is None:
            return
        off = self._hub_travel_offset()
        if off <= max_past:
            return
        hx, hy = self._turn_hub
        fx, fy = travel_vector(self.vertical, self.direction)
        self.rect.center = (
            round(self.rect.centerx - (off - max_past) * fx),
            round(self.rect.centery - (off - max_past) * fy),
        )

    def _cap_next_rect_to_hub(self, next_rect: Rect) -> Rect:
        """While approaching the hub, do not drive through before the turn starts."""
        if self._turn_phase != "to_hub" or self._turn_hub is None:
            return next_rect
        hx, hy = self._turn_hub
        fx, fy = travel_vector(self.vertical, self.direction)
        cx, cy = next_rect.center
        off = (cx - hx) * fx + (cy - hy) * fy
        if off > TURN_HUB_HOLD_DIST:
            cx -= (off - TURN_HUB_HOLD_DIST) * fx
            cy -= (off - TURN_HUB_HOLD_DIST) * fy
            next_rect.center = (round(cx), round(cy))
        return next_rect

    def _turn_arc_midpoint(
        self, roads, zone, exit_x: float, exit_y: float
    ) -> tuple[float, float]:
        """Bezier control point: hub when approaching, corner-biased if already at hub."""
        hx, hy = self._turn_hub or (zone.centerx, zone.centery)
        off = self._hub_travel_offset()
        if off <= 2:
            return float(hx), float(hy)
        px, py = self.rect.centerx, self.rect.centery
        return (px * 0.55 + exit_x * 0.45), (py * 0.55 + exit_y * 0.45)

    def _bezier_point(self, t: float) -> tuple[float, float]:
        return _bezier_xy(t, self._turn_arc_start, self._turn_arc_mid, self._turn_arc_end)

    def _turn_probe_rect(self, px: float, py: float) -> Rect:
        body = Rect(0, 0, self._turn_side, self._turn_side)
        body.center = (round(px), round(py))
        return body

    def _turn_probe_shell(self, px: float, py: float) -> Rect:
        return sprites.car_collision_rect_turn(self._turn_probe_rect(px, py))

    def _prime_turn_arc_geometry(self, roads, zone):
        if not self._turn_exit:
            return
        idx, d, _exit_vertical = self._turn_exit
        ex, ey = lane_center_xy(roads[idx], d)
        mx, my = self._turn_arc_midpoint(roads, zone, float(ex), float(ey))
        self._turn_arc_start = (float(self.rect.centerx), float(self.rect.centery))
        self._turn_arc_mid = (mx, my)
        self._turn_arc_end = (float(ex), float(ey))

    def _turn_path_points(self, t_max: float = 1.0) -> list[tuple[float, float]]:
        count = max(2, TURN_PATH_SAMPLES)
        if t_max >= 1.0:
            pts = _sample_bezier_xy(
                self._turn_arc_start, self._turn_arc_mid, self._turn_arc_end, count
            )
            return pts
        return [
            self._bezier_point((i / (count - 1)) * t_max) for i in range(count)
        ]

    def _turn_reserved_rect(self, intersection_zones) -> Rect | None:
        if not self._turn_exit or self._turn_hub is None:
            return None
        if self._turn_phase not in ("turning", "settling"):
            return None
        pts = self._turn_path_points(1.0)
        left, top, right, bottom = _turn_corridor_bounds(pts, TURN_RESERVE_PAD)
        return Rect(
            int(left),
            int(top),
            max(1, int(right - left)),
            max(1, int(bottom - top)),
        )

    def _shell_blocks_turn_path(
        self,
        shell: Rect,
        peers,
        player_body_rect,
        ped_legal_crossing: bool,
        intersection_zones=None,
    ) -> bool:
        for other in peers:
            if other is self:
                continue
            if collide(shell, other._collision_shell):
                return True
        if not ENABLE_CAR_CAR_COLLISION:
            if not ped_legal_crossing and collide(shell, player_body_rect):
                return True
        return False

    def _turn_path_clear(
        self,
        peers,
        player_body_rect,
        ped_legal_crossing: bool,
        t_max: float = 1.0,
        intersection_zones=None,
    ) -> bool:
        for px, py in self._turn_path_points(t_max):
            if self._shell_blocks_turn_path(
                self._turn_probe_shell(px, py),
                peers,
                player_body_rect,
                ped_legal_crossing,
                intersection_zones,
            ):
                return False
        return True

    def _turn_segment_clear(
        self,
        peers,
        player_body_rect,
        ped_legal_crossing: bool,
        t_from: float,
        t_to: float,
        intersection_zones=None,
    ) -> bool:
        t0 = max(0.0, min(1.0, t_from))
        t1 = max(0.0, min(1.0, t_to))
        if t1 < t0:
            t0, t1 = t1, t0
        samples = max(3, int((t1 - t0) * TURN_PATH_SAMPLES) + 1)
        for i in range(samples):
            t = t0 + (t1 - t0) * (i / max(1, samples - 1))
            cx, cy = self._bezier_point(t)
            if self._shell_blocks_turn_path(
                self._turn_probe_shell(cx, cy),
                peers,
                player_body_rect,
                ped_legal_crossing,
                intersection_zones,
            ):
                return False
        return True

    def _estimate_turn_arc_len(self) -> float:
        pts = [self._bezier_point(i / 8.0) for i in range(9)]
        total = 0.0
        for i in range(1, len(pts)):
            total += math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1])
        return max(TURN_MIN_ARC_LEN, total)

    def _set_turn_visual(self, angle_deg: float, px: float, py: float):
        self._turn_px = px
        self._turn_py = py
        self._turn_display_angle = angle_deg
        angle_q = int(round(angle_deg / 2.0) * 2) % 360
        if angle_q != self._turn_angle_draw_q:
            self._turn_angle_draw_q = angle_q
            self.image = sprites.make_car_rotated_in_box(
                self.archetype_index, angle_q, self._turn_side, self._turn_side
            )
        self.rect = Rect(0, 0, self._turn_side, self._turn_side)
        self.rect.center = (round(px), round(py))
        self._shell_sync_key = None

    def _intersection_zone_at(self, intersection_zones):
        for zone in intersection_zones:
            if collide(zone, self.rect):
                return zone
        return None

    def _turn_side_candidates(self, preferred: int) -> list[int]:
        if preferred == 0:
            return [0, -1, 1]
        return [preferred, -preferred, 0]

    def _apply_turn_plan_for_side(
        self,
        roads,
        zone,
        key: tuple[int, int, int, int],
        turn_side: int,
        peers,
        player_body_rect,
        ped_legal_crossing: bool,
    ) -> bool:
        if turn_side == 0:
            self._turn_zone_key = key
            self.turn_signal = 0
            self._turn_exit = None
            self._turn_hub = None
            self._turn_hold_frames = 0
            return True
        exit_plan = choose_exit(
            roads,
            zone,
            self.vertical,
            self.direction,
            turn_side,
            self.rect.center,
            self.road_index,
        )
        if exit_plan is None:
            return False
        if not self._pivot_exit_clear(
            roads, zone, exit_plan, peers, player_body_rect, ped_legal_crossing
        ):
            return False
        self._turn_hub = (zone.centerx, zone.centery)
        self._turn_exit = exit_plan
        self._prime_turn_arc_geometry(roads, zone)
        if not self._turn_path_clear(
            peers,
            player_body_rect,
            ped_legal_crossing,
            intersection_zones=[zone],
        ):
            self._turn_hub = None
            self._turn_exit = None
            return False
        self._turn_zone_key = key
        idx, d, exit_vertical = exit_plan
        self.turn_signal = turn_side_from_exit(
            self.vertical, self.direction, exit_vertical, d
        )
        self._turn_hold_frames = 0
        return True

    def _plan_turn_at_intersection(
        self,
        roads,
        intersection_zones,
        peers,
        player_body_rect,
        ped_legal_crossing: bool,
    ):
        if not intersection_zones or self._turn_phase in ("to_hub", "turning", "settling"):
            return
        if self._turn_abort_cooldown > 0:
            return
        if self.turn_signal == 0 and not self._approaching_or_in_intersection(
            intersection_zones
        ):
            return
        zone = self._intersection_zone_for_turn_planning(intersection_zones, roads)
        if zone is None:
            if self._turn_phase == "none":
                self.turn_signal = 0
                self._turn_exit = None
            self._turn_zone_key = None
            return
        key = (zone.x, zone.y, zone.w, zone.h)
        if key == self._turn_zone_key and self.turn_signal != 0:
            return
        rng = random.Random((traffic_map_seed + self.spawn_id * 31) & 0xFFFFFFFF)
        preferred = pick_turn_side(rng, TURN_CHANCE)
        for turn_side in self._turn_side_candidates(preferred):
            if self._apply_turn_plan_for_side(
                roads,
                zone,
                key,
                turn_side,
                peers,
                player_body_rect,
                ped_legal_crossing,
            ):
                return
        self._hold_turn_and_replan(
            intersection_zones,
            roads,
            peers,
            player_body_rect,
            ped_legal_crossing,
        )

    def _arm_turn_through_hub(
        self,
        roads,
        intersection_zones,
        peers=None,
        player_body_rect=None,
        ped_legal_crossing: bool = True,
    ):
        """Commit to hub turn once a planned turn is near or inside the box."""
        if self.turn_signal == 0 or not self._turn_exit or not intersection_zones:
            return
        if self._turn_hold_frames > 0:
            return
        if not self._approaching_or_in_intersection(intersection_zones):
            return
        if peers is not None and player_body_rect is not None:
            if not self._turn_path_clear(
                peers,
                player_body_rect,
                ped_legal_crossing,
                intersection_zones=intersection_zones,
            ):
                return
        zone = self._intersection_zone_for_turn_planning(intersection_zones, roads)
        if zone is None:
            zone = self._intersection_zone_at(intersection_zones)
        if zone is None:
            return
        if self._turn_phase == "none":
            in_ix = self._rect_in_intersection(self.rect, intersection_zones)
            if not in_ix:
                hx, hy = zone.centerx, zone.centery
                dist = math.hypot(self.rect.centerx - hx, self.rect.centery - hy)
                lead = TURN_HUB_DIST + TURN_SIGNAL_LEAD_DIST // 3
                if dist > lead + 10:
                    return
            self._turn_phase = "to_hub"
            self._turn_hub = (zone.centerx, zone.centery)

    def _begin_turn_steer(
        self,
        roads,
        zone,
        peers,
        player_body_rect,
        ped_legal_crossing: bool,
        intersection_zones=None,
    ) -> bool:
        self._prime_turn_arc_geometry(roads, zone)
        ix = intersection_zones if intersection_zones is not None else [zone]
        if not self._turn_path_clear(
            peers,
            player_body_rect,
            ped_legal_crossing,
            intersection_zones=ix,
        ):
            return False
        self._snap_to_hub_approach(max_past=0.0)
        self._turn_entry_vertical = self.vertical
        self._turn_entry_direction = self.direction
        self._turn_blend = 0.0
        self._turn_arc_travel = 0.0
        self._turn_arc_len = 0.0
        self._turn_angle_draw_q = -999
        self._turn_side = max(CAR_WIDTH, CAR_HEIGHT)
        self._turn_px = float(self.rect.centerx)
        self._turn_py = float(self.rect.centery)
        idx, d, exit_vertical = self._turn_exit
        exit_dir = 1 if d >= 0 else -1
        self._turn_angle_start = sprites.car_travel_angle_deg(
            self._turn_entry_vertical, self._turn_entry_direction
        )
        self._turn_angle_end = sprites.car_travel_angle_deg(exit_vertical, exit_dir)
        ex, ey = lane_center_xy(roads[idx], d)
        mx, my = self._turn_arc_midpoint(roads, zone, float(ex), float(ey))
        self._turn_arc_start = (self._turn_px, self._turn_py)
        self._turn_arc_mid = (mx, my)
        self._turn_arc_end = (float(ex), float(ey))
        self._turn_arc_len = self._estimate_turn_arc_len()
        self._turn_phase = "turning"
        self._set_turn_visual(self._turn_angle_start, self._turn_px, self._turn_py)
        self.current_speed = max(self.current_speed, self.base_speed * TURN_DRIFT_SPEED_FRAC * 0.5)
        self._sync_collision_shell(force=True)
        return True

    def _steer_through_turn(
        self,
        roads,
        intersection_zones,
        peers,
        player_body_rect,
        ped_legal_crossing: bool,
    ) -> bool:
        """Bezier path + gradual sprite rotation; returns True when arc is done."""
        if self._turn_phase != "turning" or not self._turn_exit:
            return False

        if self._turn_arc_len < 1.0:
            self._turn_arc_len = self._estimate_turn_arc_len()

        drift_floor = self.base_speed * TURN_MIN_STEP_FRAC
        step = max(drift_floor, self.current_speed) * TURN_DRIFT_SPEED_FRAC
        t_now = self._turn_arc_travel / max(1e-6, self._turn_arc_len)
        next_travel = min(self._turn_arc_len, self._turn_arc_travel + step)
        t_next = next_travel / max(1e-6, self._turn_arc_len)
        if not self._turn_segment_clear(
            peers,
            player_body_rect,
            ped_legal_crossing,
            t_now,
            t_next,
            intersection_zones=intersection_zones,
        ):
            self.speed = 0.0
            self.current_speed = max(
                self.base_speed * TURN_DRIFT_SPEED_FRAC * 0.55,
                self.current_speed * 0.92,
            )
            self._turn_overlap_frames += 1
            self._turn_stall_frames += 1
            self._sync_collision_shell()
            return False

        prev_px, prev_py = self._turn_px, self._turn_py
        prev_travel = self._turn_arc_travel
        self._turn_arc_travel = next_travel
        ease = _smoothstep(t_next)
        angle = _lerp_angle_deg(self._turn_angle_start, self._turn_angle_end, ease)
        cx, cy = self._bezier_point(ease)

        self._set_turn_visual(angle, cx, cy)
        self._sync_collision_shell()
        if self._turn_shell_overlaps_peer(peers, intersection_zones):
            self._turn_arc_travel = prev_travel
            self._set_turn_visual(
                _lerp_angle_deg(
                    self._turn_angle_start,
                    self._turn_angle_end,
                    _smoothstep(prev_travel / max(1e-6, self._turn_arc_len)),
                ),
                prev_px,
                prev_py,
            )
            self.speed = 0.0
            self.current_speed = max(
                self.base_speed * TURN_DRIFT_SPEED_FRAC * 0.55,
                self.current_speed * 0.92,
            )
            self._turn_overlap_frames += 1
            self._turn_stall_frames += 1
            self._sync_collision_shell()
            return False

        self.current_speed = max(
            self.current_speed, self.base_speed * TURN_DRIFT_SPEED_FRAC * 0.65
        )
        self.speed = self.current_speed * self._turn_entry_direction

        if ease >= 1.0:
            idx, d, exit_vertical = self._turn_exit
            exit_dir = 1 if d >= 0 else -1
            tcx, tcy = lane_center_xy(roads[idx], d)
            self._turn_settle_target = (float(tcx), float(tcy))
            self._turn_settle_blend = 0.0
            self._turn_phase = "settling"
            self._sync_collision_shell(force=True)
        else:
            self._sync_collision_shell()
        return False

    def _settle_turn_exit(
        self, roads, peers=None, intersection_zones=None
    ) -> bool:
        """Ease position onto the exit lane and swap back to axis-aligned sprite."""
        if self._turn_phase != "settling" or not self._turn_exit:
            return False
        if peers and self._turn_shell_overlaps_peer(peers, intersection_zones):
            self._turn_stall_frames += 1
            self.speed = 0.0
            self.current_speed = 0.0
            self._sync_collision_shell()
            return False
        idx, d, exit_vertical = self._turn_exit
        exit_dir = 1 if d >= 0 else -1
        self._turn_settle_blend += 1.0 / TURN_SETTLE_FRAMES
        t = _smoothstep(min(1.0, self._turn_settle_blend))
        tx, ty = self._turn_settle_target
        px = self._turn_px + (tx - self._turn_px) * t
        py = self._turn_py + (ty - self._turn_py) * t
        end_angle = sprites.car_travel_angle_deg(exit_vertical, exit_dir)
        angle = _lerp_angle_deg(self._turn_angle_end, end_angle, t)
        self._set_turn_visual(angle, px, py)
        self.current_speed = max(self.current_speed, self.base_speed * TURN_DRIFT_SPEED_FRAC * 0.35)
        if t < 1.0:
            self._sync_collision_shell()
            return False
        self.road_index = idx
        self.vertical = exit_vertical
        self.direction = exit_dir
        center = (round(px), round(py))
        self._refresh_car_sprite()
        self.rect.center = center
        self._snap_center_to_left_lane(roads, max_nudge=2)
        self.turn_signal = 0
        self._turn_phase = "none"
        self._turn_exit = None
        self._turn_hub = None
        self._turn_blend = 0.0
        self._turn_arc_len = 0.0
        self._turn_arc_travel = 0.0
        self._turn_angle_draw_q = -999
        self._last_good_center = self.rect.center
        self._sync_collision_shell(force=True)
        return True

    def _try_start_turn_at_hub(
        self,
        roads,
        intersection_zones,
        peers,
        player_body_rect,
        ped_legal_crossing: bool,
    ) -> bool:
        if self._turn_phase != "to_hub" or not self._turn_exit or not self._turn_hub:
            return False
        zone = self._intersection_zone_for_turn_planning(intersection_zones, roads)
        if zone is None:
            zone = self._intersection_zone_at(intersection_zones)
        if zone is None:
            return False
        hx, hy = self._turn_hub
        dist = math.hypot(self.rect.centerx - hx, self.rect.centery - hy)
        past = self._hub_travel_offset()
        if past > TURN_OVERSHOOT_ABORT:
            self._hold_turn_and_replan(
                intersection_zones,
                roads,
                peers,
                player_body_rect,
                ped_legal_crossing,
            )
            return False
        lead = TURN_HUB_DIST + TURN_SIGNAL_LEAD_DIST // 3
        if dist > lead and past <= 0:
            return False
        if not self._turn_path_clear(
            peers,
            player_body_rect,
            ped_legal_crossing,
            intersection_zones=intersection_zones,
        ):
            return False
        return self._begin_turn_steer(
            roads,
            zone,
            peers,
            player_body_rect,
            ped_legal_crossing,
            intersection_zones=intersection_zones,
        )

    def _spawn_ramp_cap(self) -> float:
        if self._spawn_age >= CAR_SPAWN_RAMP_FRAMES:
            return self.base_speed
        t = self._spawn_age / CAR_SPAWN_RAMP_FRAMES
        ease = t * t * (3.0 - 2.0 * t)
        return self.base_speed * ease

    def _has_exited_map_along_route(
        self, roads, intersection_zones, world_rect
    ) -> bool:
        """Despawn only after the car fully leaves the map (exit corridor handles segment ends)."""
        if self._spawn_age < CAR_SPAWN_RAMP_FRAMES:
            return False
        if self._near_intersection_bbox(intersection_zones) and self._shell_overlaps_intersection(
            intersection_zones, INTERSECTION_SHELL_PAD
        ):
            return False
        shell = self._collision_shell
        edge_m = CAR_EXIT_DESPAWN_MARGIN
        if self.vertical:
            if self.direction > 0:
                return shell.top > world_rect.bottom + edge_m
            return shell.bottom < world_rect.top - edge_m
        if self.direction > 0:
            return shell.left > world_rect.right + edge_m
        return shell.right < world_rect.left - edge_m

    def _removal_reason(
        self, roads, intersection_zones, world_rect, frame_index: int = 0
    ) -> str | None:
        """Why this car should despawn; None = keep."""
        if self._spawn_age < CAR_SPAWN_RAMP_FRAMES:
            return None
        if (
            self._gridlock_frames >= INTERSECTION_GRIDLOCK_FRAMES
            and self._turn_phase == "none"
            and self.turn_signal == 0
            and intersection_zones
            and self._rect_in_intersection(self.rect, intersection_zones)
            and self.current_speed < 0.35
        ):
            return "gridlock"
        if self._turn_phase in ("to_hub", "turning", "settling") or self.turn_signal != 0:
            return None
        if self._near_intersection_bbox(intersection_zones) and self._shell_overlaps_intersection(
            intersection_zones, INTERSECTION_SHELL_PAD
        ):
            self._off_road_frames = 0
            return None
        if self._has_exited_map_along_route(roads, intersection_zones, world_rect):
            return "exit"
        if (
            self._off_road_frames == 0
            and (frame_index + self.spawn_id) % SURFACE_CHECK_INTERVAL != 0
        ):
            return None
        if self._is_on_drivable_surface(roads, intersection_zones, world_rect):
            self._off_road_frames = 0
            return None
        self._off_road_frames += 1
        if self._off_road_frames >= OFF_ROAD_REMOVE_FRAMES:
            return "off_road"
        return None

    def _in_or_entering_intersection(self, next_rect, intersection_zones) -> bool:
        if not intersection_zones:
            return False
        return any(
            collide(z, self.rect) or collide(z, next_rect) for z in intersection_zones
        )

    def _entry_blocks_moving_cross_traffic(
        self, next_rect, peers, intersection_zones
    ) -> bool:
        """Do not enter the box if we'd cut in front of cross traffic or a committed turn."""
        my_n = sprites.car_collision_rect(next_rect, self.vertical)
        for zone in intersection_zones:
            entering = collide(next_rect, zone) and not collide(self.rect, zone)
            if not entering:
                continue
            for other in peers:
                if other is self:
                    continue
                if other._committed_intersection_turn(intersection_zones):
                    if zone.collidepoint(other.rect.center) and collide(
                        my_n, other._collision_shell
                    ):
                        return True
                    continue
                if other.vertical == self.vertical:
                    continue
                if other.current_speed < other.base_speed * 0.2:
                    continue
                if not zone.collidepoint(other.rect.center):
                    continue
                orect = other._collision_shell.inflate(-6, -6)
                if orect.width > 2 and orect.height > 2 and collide(my_n, orect):
                    return True
        return False

    def _distance_to_clear_zone(self, zone: Rect) -> float:
        """Along-travel distance from the leading edge to the far side of a zone."""
        if self.vertical:
            if self.direction > 0:
                return max(0.0, float(zone.bottom - self.rect.bottom))
            return max(0.0, float(self.rect.top - zone.top))
        if self.direction > 0:
            return max(0.0, float(zone.left - self.rect.right))
        return max(0.0, float(self.rect.left - zone.right))

    def _clear_distance_through_zone(self, zone: Rect) -> float:
        """Distance needed to fully exit the zone along current travel."""
        if collide(zone, self.rect):
            return self._distance_to_clear_zone(zone)
        entry = self._distance_to_intersection_entry(zone)
        if entry is None or entry < 0:
            return 0.0
        depth = zone.height if self.vertical else zone.width
        return float(entry) + float(depth)

    def _nearest_approach_state(self, road_states):
        best = None
        best_d = 1e9
        for state in road_states:
            if not rects_overlap(self.rect, state["approach_rect"]):
                continue
            if self.vertical:
                stop_distance = (state["stop_axis"] - self.rect.centery) * self.direction
                in_lane = abs(self.rect.centerx - state["crosswalk"].centerx) < 50
            else:
                stop_distance = (state["stop_axis"] - self.rect.centerx) * self.direction
                in_lane = abs(self.rect.centery - state["crosswalk"].centery) < 50
            if not in_lane or stop_distance <= -STOP_LINE_GAP:
                continue
            if stop_distance < best_d:
                best_d = stop_distance
                best = state
        return best

    def _can_clear_signal_in_time(self, state, zone: Rect) -> bool:
        clear_dist = self._clear_distance_through_zone(zone)
        if clear_dist <= 0:
            return True
        speed_px_per_frame = max(self.current_speed, CAR_CREEP_SPEED * 0.45, 0.8)
        speed_px_per_s = speed_px_per_frame * SIM_FPS
        time_needed = clear_dist / speed_px_per_s
        time_left = self._effective_seconds_to_change(state)
        light = self._effective_approach_light(state)
        if light == "green":
            return time_needed <= time_left + INTERSECTION_CLEAR_BUFFER_S
        if light == "yellow":
            return time_needed <= time_left + INTERSECTION_CLEAR_BUFFER_S * 0.5
        return False

    def _exit_blocked_by_active_turn(
        self, next_rect, peers, intersection_zones
    ) -> bool:
        my_n = sprites.car_collision_rect(next_rect, self.vertical)
        for other in peers:
            if other is self:
                continue
            if other._turn_phase in ("turning", "settling"):
                if rects_overlap(my_n, other._collision_shell):
                    return True
                reserved = other._turn_reserved_rect(intersection_zones)
                if reserved is not None and rects_overlap(my_n, reserved):
                    return True
            elif other._committed_intersection_turn(intersection_zones):
                if rects_overlap(my_n.inflate(16, 16), other._collision_shell):
                    return True
        return False

    def _intersection_entry_blocked(
        self,
        next_rect,
        road_states,
        intersection_zones,
        peers,
        move_peers,
    ) -> bool:
        """Do not enter the box unless the approach is green/yellow-clearable and exit is open."""
        if not intersection_zones:
            return False
        target_zone = None
        entering = False
        for zone in intersection_zones:
            if collide(next_rect, zone) and not collide(self.rect, zone):
                target_zone = zone
                entering = True
                break
        if target_zone is None:
            for zone in intersection_zones:
                entry = self._distance_to_intersection_entry(zone)
                if entry is not None and 0 <= entry <= 48:
                    target_zone = zone
                    break
        if target_zone is None:
            return False

        approach = self._nearest_approach_state(road_states)
        if approach is not None:
            light = self._effective_approach_light(approach)
            if light == "red":
                return True
            if light in ("green", "yellow") and not self._can_clear_signal_in_time(
                approach, target_zone
            ):
                return True

        if not entering:
            return False

        if self._entry_blocks_moving_cross_traffic(
            next_rect, move_peers or peers, intersection_zones
        ):
            return True
        if self._exit_blocked_by_active_turn(
            next_rect, move_peers or peers, intersection_zones
        ):
            return True
        return False

    def _intersection_move_blocked(
        self, next_rect, peers, intersection_zones, allow_perp_creep=False
    ):
        if not ENABLE_CAR_CAR_COLLISION:
            return False
        if not intersection_zones:
            return False
        if not self._in_or_entering_intersection(next_rect, intersection_zones):
            return False
        if not allow_perp_creep and self._entry_blocks_moving_cross_traffic(
            next_rect, peers, intersection_zones
        ):
            return True
        my_n = sprites.car_collision_rect(next_rect, self.vertical)
        for other in peers:
            if other is self:
                continue
            same_lane = (
                other.vertical == self.vertical
                and other.direction == self.direction
                and self._same_lane(other, CAR_BLOCK_LANE_GAP)
            )
            if same_lane:
                if not collide(my_n, other._collision_shell):
                    continue
                gap, _ = self._distance_to_other(other)
                if gap <= 0 or gap < 22:
                    return True
                continue
            if other._turn_phase in ("turning", "settling"):
                if collide(my_n, other._collision_shell):
                    return True
                continue
            if other.vertical == self.vertical:
                continue
            if not collide(my_n, other._collision_shell):
                continue
            if allow_perp_creep:
                if not self._hard_shell_overlap(next_rect, self.vertical, other):
                    continue
                if self._ix_creep_has_priority(other, intersection_zones):
                    continue
                return True
            return True
        return False

    def update(
        self,
        road_states,
        world_rect,
        intersection_zones,
        player_body_rect,
        roads,
        lane_peers,
        move_peers,
        frame_index=0,
        player_on_road=False,
        player_on_crosswalk=False,
        player_feet_road=False,
        ped_legal_crossing=False,
        respect_player=False,
        honk_allowed=False,
        player_body_block=None,
        game_time=0,
    ):
        desired_speed = self.base_speed
        blocking_controls = []
        yield_roll = (traffic_map_seed + self.spawn_id * 17) % 100
        will_yield_to_player = yield_roll < int(PLAYER_AVOIDANCE_CHANCE * 100)
        if ped_legal_crossing:
            will_yield_to_player = True

        inside_intersection = bool(intersection_zones) and self._rect_in_intersection(
            self.rect, intersection_zones
        )
        if inside_intersection and self.current_speed < 0.35:
            self._intersection_stuck_frames += 1
        else:
            self._intersection_stuck_frames = 0
        if (
            inside_intersection
            and self._turn_phase == "none"
            and self.turn_signal == 0
            and self.current_speed < 0.3
        ):
            self._gridlock_frames += 1
        else:
            self._gridlock_frames = 0
        intersection_creep = (
            inside_intersection
            and self._intersection_stuck_frames >= INTERSECTION_STUCK_CREEP_FRAMES
        )
        self._spawn_age += 1
        if self._turn_abort_cooldown > 0:
            self._turn_abort_cooldown -= 1
        ramp_cap = self._spawn_ramp_cap()
        plan_turn = self.turn_signal != 0 or self._approaching_or_in_intersection(
            intersection_zones
        )
        plan_stride = 2 if plan_turn else 0
        if plan_stride and (frame_index + self.spawn_id) % plan_stride == 0:
            self._plan_turn_at_intersection(
                roads,
                intersection_zones,
                move_peers,
                player_body_rect,
                ped_legal_crossing,
            )
        self._maintain_turn_plan(
            roads,
            intersection_zones,
            move_peers,
            player_body_rect,
            ped_legal_crossing,
            road_states,
        )
        self._arm_turn_through_hub(
            roads,
            intersection_zones,
            move_peers,
            player_body_rect,
            ped_legal_crossing,
        )
        if self._turn_hold_frames > 0 and (self.turn_signal != 0 or self._turn_exit):
            desired_speed = 0.0
        if self._turn_phase in ("to_hub", "turning", "settling"):
            desired_speed = min(desired_speed, self.base_speed * TURN_PIVOT_SPEED_FRAC)
        if self._turn_phase == "to_hub" and self._turn_hub is not None:
            hub_off = self._hub_travel_offset()
            if hub_off >= -TURN_HUB_DIST:
                desired_speed = min(desired_speed, self.base_speed * TURN_PIVOT_SPEED_FRAC * 0.65)
            if -6 <= hub_off <= TURN_HUB_HOLD_DIST:
                desired_speed = 0.0

        if ENABLE_CAR_CAR_SOFT_AVOIDANCE:
            if self._turn_phase not in ("turning", "settling"):
                self._resolve_same_lane_penetration(lane_peers)
                if self._spawn_age < CAR_SPAWN_RAMP_FRAMES:
                    self._resolve_same_lane_penetration(lane_peers)
            self._resolve_shell_penetration(move_peers)
        self._sync_collision_shell()

        for state in road_states:
            approach = state["approach_rect"]
            if not rects_overlap(self.rect, approach):
                continue

            if self.vertical:
                stop_distance = (state["stop_axis"] - self.rect.centery) * self.direction
                in_crossing_lane = abs(self.rect.centerx - state["crosswalk"].centerx) < 50
            else:
                stop_distance = (state["stop_axis"] - self.rect.centerx) * self.direction
                in_crossing_lane = abs(self.rect.centery - state["crosswalk"].centery) < 50

            if in_crossing_lane:
                # Do not hold at lights while already in the intersection box — clear it.
                if not inside_intersection:
                    approach_light = self._effective_approach_light(state)
                    red_stop_range = 195
                    if (
                        approach_light == "red"
                        and collide(state["crosswalk"], player_body_rect)
                    ):
                        red_stop_range = 235
                    if (
                        approach_light == "red"
                        and -STOP_LINE_GAP <= stop_distance < red_stop_range
                    ):
                        desired_speed = 0
                        blocking_controls.append(state)
                    elif (
                        approach_light == "yellow"
                        and -STOP_LINE_GAP <= stop_distance < 150
                    ):
                        zone = self._intersection_zone_at(intersection_zones)
                        if zone is None and intersection_zones:
                            best_d = 1e9
                            for z in intersection_zones:
                                d = self._distance_to_intersection_entry(z)
                                if d is not None and 0 <= d < best_d:
                                    best_d = d
                                    zone = z
                        if zone is None or not self._can_clear_signal_in_time(
                            state, zone
                        ):
                            desired_speed = 0
                            blocking_controls.append(state)
                        elif stop_distance >= YELLOW_COMMIT_DISTANCE:
                            desired_speed = min(desired_speed, self.base_speed * 0.45)

                    if state["stop_active"] and 0 < stop_distance < 85:
                        desired_speed = min(desired_speed, self.base_speed * 0.25)

        # Strong player-avoidance behavior: brake early when player is in/near lane ahead.
        if self.vertical:
            player_ahead = (player_body_rect.centery - self.rect.centery) * self.direction
            player_lane_gap = abs(player_body_rect.centerx - self.rect.centerx)
        else:
            player_ahead = (player_body_rect.centerx - self.rect.centerx) * self.direction
            player_lane_gap = abs(player_body_rect.centery - self.rect.centery)

        if ped_legal_crossing and respect_player and player_lane_gap < 58:
            for state in road_states:
                if not collide(state["crosswalk"], player_body_rect):
                    continue
                if not self._in_crosswalk_lane(state):
                    continue
                if self.vertical:
                    ped_stop_dist = (state["stop_axis"] - self.rect.centery) * self.direction
                else:
                    ped_stop_dist = (state["stop_axis"] - self.rect.centerx) * self.direction
                if 0 < ped_stop_dist < 200:
                    desired_speed = 0
                    break
        elif respect_player and 0 < player_ahead < 220 and player_lane_gap < 52:
            if will_yield_to_player:
                if player_ahead < 70:
                    desired_speed = 0
                elif player_ahead < 120:
                    desired_speed = min(desired_speed, self.base_speed * 0.22)
                else:
                    desired_speed = min(desired_speed, self.base_speed * 0.45)
            else:
                desired_speed = min(desired_speed, self.base_speed * 0.78)

        if ENABLE_CAR_CAR_SOFT_AVOIDANCE and self._turn_phase not in (
            "turning",
            "settling",
        ):
            desired_speed = self._apply_lane_follow_speed(lane_peers, desired_speed)

        if self._turn_phase not in ("turning", "settling"):
            for other in move_peers:
                if other is self:
                    continue
                if self._conflicts_with_committed_turner(other, intersection_zones):
                    desired_speed = 0.0
                    break
                if other._turn_phase in ("turning", "settling") and rects_overlap(
                    self._collision_shell.inflate(32, 32),
                    other._collision_shell,
                ):
                    desired_speed = 0.0
                    break
                if not self._other_in_active_turn(other):
                    continue
                if rects_overlap(
                    self._collision_shell.inflate(28, 28),
                    other._collision_shell,
                ):
                    desired_speed = min(desired_speed, self.base_speed * 0.22)
                    break

        desired_speed = min(desired_speed, ramp_cap)
        if self._spawn_age < CAR_SPAWN_RAMP_FRAMES:
            accel = self.base_speed / CAR_SPAWN_RAMP_FRAMES
        else:
            accel = self.acceleration

        if self.current_speed < desired_speed:
            self.current_speed = min(desired_speed, self.current_speed + accel)
        else:
            self.current_speed = max(desired_speed, self.current_speed - self.brake_strength)

        signed_speed = self.current_speed * self.direction

        blocked_by_line = False
        if signed_speed != 0:
            for state in blocking_controls:
                stop_axis = state["stop_axis"]
                if self.vertical:
                    if self.direction > 0 and self.rect.bottom + signed_speed >= stop_axis - STOP_LINE_GAP:
                        self.rect.bottom = stop_axis - STOP_LINE_GAP
                        blocked_by_line = True
                    elif self.direction < 0 and self.rect.top + signed_speed <= stop_axis + STOP_LINE_GAP:
                        self.rect.top = stop_axis + STOP_LINE_GAP
                        blocked_by_line = True
                else:
                    if self.direction > 0 and self.rect.right + signed_speed >= stop_axis - STOP_LINE_GAP:
                        self.rect.right = stop_axis - STOP_LINE_GAP
                        blocked_by_line = True
                    elif self.direction < 0 and self.rect.left + signed_speed <= stop_axis + STOP_LINE_GAP:
                        self.rect.left = stop_axis + STOP_LINE_GAP
                        blocked_by_line = True
                if blocked_by_line:
                    break

        if self._turn_phase == "turning":
            self._steer_through_turn(
                roads,
                intersection_zones,
                move_peers,
                player_body_rect,
                ped_legal_crossing,
            )
        elif self._turn_phase == "settling":
            self._settle_turn_exit(roads, move_peers, intersection_zones)
        elif blocked_by_line:
            self.current_speed = 0
            self.speed = 0
        else:
            next_rect = self.rect.copy()
            if self.vertical:
                next_rect.y += signed_speed
            else:
                next_rect.x += signed_speed

            if self._turn_phase == "to_hub":
                next_rect = self._cap_next_rect_to_hub(next_rect)

            if ENABLE_CAR_CAR_SOFT_AVOIDANCE:
                next_rect = self._cap_next_rect_same_lane(next_rect, lane_peers)
                next_rect = self._cap_next_rect_all_cars(next_rect, move_peers)
                if self._planned_move_conflicts_active_turn(
                    next_rect, move_peers, intersection_zones
                ):
                    if not intersection_creep:
                        next_rect = self.rect.copy()

            entry_blocked = (
                signed_speed != 0
                and self._turn_phase not in ("turning", "settling")
                and self._intersection_entry_blocked(
                    next_rect,
                    road_states,
                    intersection_zones,
                    lane_peers,
                    move_peers,
                )
            )
            if entry_blocked:
                next_rect = self.rect.copy()

            blocked = False
            creep_cap = None
            my_n = sprites.car_collision_rect_into(
                next_rect, self.vertical, self._body_rect_scratch
            )
            in_ix_move = self._in_or_entering_intersection(next_rect, intersection_zones)
            if signed_speed != 0:
                if ENABLE_CAR_CAR_COLLISION:
                    blocked = self._intersection_move_blocked(
                        next_rect,
                        move_peers if in_ix_move else lane_peers,
                        intersection_zones,
                        allow_perp_creep=intersection_creep,
                    )
                    if not blocked and self._shell_hits_any_car(
                        next_rect, self.vertical, move_peers, shell=my_n
                    ):
                        if in_ix_move and intersection_creep and not self._hard_block_after_cap(
                            next_rect, move_peers, True, intersection_zones
                        ):
                            creep_cap = CAR_CREEP_SPEED
                        else:
                            blocked = True
                    if not blocked:
                        for other in lane_peers:
                            if other is self:
                                continue
                            if other.vertical != self.vertical or other.direction != self.direction:
                                continue
                            if not self._same_lane(other, CAR_BLOCK_LANE_GAP):
                                continue
                            if not collide(my_n, other._collision_shell):
                                continue
                            gap, _ = self._distance_to_other(other)
                            if gap <= 0:
                                blocked = True
                                break
                            if gap < 26:
                                blocked = True
                                break
                            if gap < 52 and other.current_speed < 1.2:
                                creep_cap = CAR_CREEP_SPEED
                                break
                elif ENABLE_CAR_CAR_SOFT_AVOIDANCE:
                    if (
                        in_ix_move
                        and not intersection_creep
                        and self._entry_blocks_moving_cross_traffic(
                            next_rect, move_peers, intersection_zones
                        )
                    ):
                        creep_cap = CAR_CREEP_SPEED * 0.4
                    soft_cap = self._soft_overlap_creep_cap(
                        next_rect, move_peers, lane_peers, intersection_zones
                    )
                    if soft_cap is not None:
                        creep_cap = (
                            soft_cap
                            if creep_cap is None
                            else min(creep_cap, soft_cap)
                        )
                pbb = (
                    player_body_block
                    if player_body_block is not None
                    else player_body_rect.inflate(4, 4)
                )
                if (
                    not blocked
                    and not ped_legal_crossing
                    and player_feet_road
                    and collide(my_n, pbb)
                ):
                    blocked = True

            if blocked or entry_blocked:
                self.current_speed = 0
                self.speed = 0
            elif creep_cap is not None and signed_speed != 0:
                creep = min(abs(signed_speed), creep_cap) * self.direction
                self.speed = creep
                self.current_speed = abs(creep)
                if self.vertical:
                    self.rect.y += int(creep)
                else:
                    self.rect.x += int(creep)
            elif signed_speed != 0:
                self.speed = signed_speed
                self.rect = next_rect

        self.rect.clamp_ip(world_rect.inflate(300, 300))
        if self._turn_phase == "to_hub":
            self._snap_to_hub_approach(max_past=TURN_HUB_HOLD_DIST)
            self._try_start_turn_at_hub(
                roads,
                intersection_zones,
                move_peers,
                player_body_rect,
                ped_legal_crossing,
            )
        turn_stall_zone = (
            self._turn_phase == "to_hub"
            or inside_intersection
            or (
                self._turn_phase in ("turning", "settling")
                and intersection_zones
                and self._approaching_or_in_intersection(intersection_zones)
            )
        )
        if self._turn_phase in ("to_hub", "turning", "settling") and turn_stall_zone:
            if self.current_speed < 0.35:
                self._turn_blocked_frames += 1
            elif self._turn_blocked_frames > 0:
                self._turn_blocked_frames = max(0, self._turn_blocked_frames - 2)
        else:
            self._turn_blocked_frames = 0
        if self._turn_phase == "turning":
            stall_center = (round(self._turn_px), round(self._turn_py))
            if stall_center == self._turn_stall_center:
                self._turn_stall_frames += 1
            else:
                self._turn_stall_frames = 0
                self._turn_stall_center = stall_center
            if (
                self._turn_stall_frames >= TURN_STALL_ABORT_FRAMES
                and intersection_zones
                and self._rect_in_intersection(self.rect, intersection_zones)
            ):
                zone = self._intersection_zone_for_turn_planning(
                    intersection_zones, roads
                )
                if zone is None:
                    zone = self._intersection_zone_at(intersection_zones)
                if zone is not None:
                    self._freeze_blocked_turn_in_intersection(
                        intersection_zones,
                        roads,
                        move_peers,
                        player_body_rect,
                        ped_legal_crossing,
                        zone,
                    )
            elif self._turn_stall_frames >= TURN_STALL_ABORT_FRAMES:
                self._hold_turn_and_replan(
                    intersection_zones,
                    roads,
                    move_peers,
                    player_body_rect,
                    ped_legal_crossing,
                )
        if self._turn_phase in ("to_hub", "turning", "settling"):
            self._mitigate_turn_peer_deadlock(
                move_peers, intersection_zones, roads
            )
        if self._turn_phase == "turning":
            turn_abort_limit = TURN_PATH_BLOCKED_ABORT_FRAMES
        elif self._turn_phase == "to_hub":
            turn_abort_limit = TURN_TO_HUB_ABORT_FRAMES
        else:
            turn_abort_limit = TURN_ABORT_FRAMES
        if self._turn_blocked_frames >= turn_abort_limit:
            self._hold_turn_and_replan(
                intersection_zones,
                roads,
                move_peers,
                player_body_rect,
                ped_legal_crossing,
            )

        if (frame_index + self.spawn_id) % SURFACE_CHECK_INTERVAL == 0:
            self._anchor_network_position(roads, intersection_zones, world_rect)
        removal = self._removal_reason(
            roads, intersection_zones, world_rect, frame_index
        )
        if removal is not None:
            _queue_car_respawn(self)
            self.kill()
        self._sync_collision_shell()
        in_ix_rect = bool(intersection_zones) and self._rect_in_intersection(
            self.rect, intersection_zones
        )
        if (
            self.road_index is not None
            and self._turn_phase not in ("to_hub", "turning", "settling")
            and not in_ix_rect
        ):
            if self.current_speed < 0.25 and self._stopped_frames > 8:
                snap_nudge = 0
            elif self._spawn_age < CAR_SPAWN_RAMP_FRAMES:
                snap_nudge = 4
            else:
                snap_nudge = None
            self._snap_center_to_left_lane(roads, max_nudge=snap_nudge)

        if self.current_speed < 0.25:
            self._stopped_frames += 1
        else:
            self._stopped_frames = 0
        if self.alive() and honk_allowed:
            if (frame_index + self.spawn_id) % HONK_CHECK_INTERVAL == 0:
                pb = player_body_rect
                if (
                    abs(self.rect.centerx - pb.centerx) < PLAYER_CAR_QUERY_PAD
                    and abs(self.rect.centery - pb.centery) < PLAYER_CAR_QUERY_PAD
                ):
                    self.evaluate_honk(
                        player_body_rect,
                        player_on_crosswalk,
                        honk_allowed,
                        game_time,
                    )


def _lane_bucket_key(car) -> tuple:
    if car.vertical:
        return (1, car.direction, car.rect.centerx // LANE_BUCKET_SIZE)
    return (0, car.direction, car.rect.centery // LANE_BUCKET_SIZE)


def _build_lane_buckets(car_list) -> dict:
    buckets: dict[tuple, list] = {}
    for car in car_list:
        if not car.alive():
            continue
        key = _lane_bucket_key(car)
        lane = buckets.get(key)
        if lane is None:
            buckets[key] = [car]
        else:
            lane.append(car)
    return buckets


def _lane_peers_for(car, buckets: dict, out: list) -> list:
    out.clear()
    k = _lane_bucket_key(car)
    for delta in (-1, 0, 1):
        lane = buckets.get((k[0], k[1], k[2] + delta))
        if lane:
            out.extend(lane)
    return out


class Pedestrian(Entity):
    def __init__(self, start_pos):
        super().__init__()
        self.image = sprites.make_pedestrian_surface(PEDESTRIAN_SIZE)
        self.rect = Rect(0, 0, self.image.get_width(), self.image.get_height())
        self.rect.center = start_pos

    def update(self, keys):
        dx = dy = 0
        if keys.pressed(KEY_LEFT):
            dx -= PEDESTRIAN_SPEED
        if keys.pressed(KEY_RIGHT):
            dx += PEDESTRIAN_SPEED
        if keys.pressed(KEY_UP):
            dy -= PEDESTRIAN_SPEED
        if keys.pressed(KEY_DOWN):
            dy += PEDESTRIAN_SPEED
        self.rect.x += dx
        self.rect.y += dy


def _load_prior_session():
    try:
        with open("logs.json", encoding="utf-8") as handle:
            payload = json.load(handle)
        return payload.get("session") or payload
    except (OSError, json.JSONDecodeError, AttributeError):
        return None


def _map_seed_for_round(session_seed: int, round_index: int) -> int:
    """One session seed; each round gets a stable derived map seed."""
    return (int(session_seed) + round_index * 9973) & 0x7FFFFFFF


def _effective_light_durations(scale: float):
    """Scale full cycle length; preserve 45/10/45 green/yellow/red ratio."""
    cycle = LIGHT_CYCLE_SECONDS * max(0.88, scale)
    return cycle_durations(cycle)


def _rect_overlap_area(a: Rect, b: Rect) -> int:
    return rect_overlap_area(a, b)


def _city_block_rects_from(city_blocks) -> tuple[Rect, ...]:
    if not city_blocks:
        return ()
    return tuple(
        Rect(int(block["x"]), int(block["y"]), int(block["w"]), int(block["h"]))
        for block in city_blocks
    )


def _spawn_probe_geometry(x: int, y: int, vertical: bool) -> tuple[Rect, Rect]:
    if vertical:
        w, h = CAR_HEIGHT, CAR_WIDTH
    else:
        w, h = CAR_WIDTH, CAR_HEIGHT
    rect = Rect(x, y, w, h)
    return rect, sprites.car_collision_rect(rect, vertical)


def _blocks_player_spawn_shell(shell: Rect, player_rect) -> bool:
    if player_rect is None:
        return False
    pb = sprites.player_body_hitbox(player_rect)
    zone = player_rect.inflate(PLAYER_SPAWN_PAD, PLAYER_SPAWN_PAD)
    return rects_overlap(shell, pb) or rects_overlap(shell, zone)


def _blocks_player_spawn(candidate: Car, player_rect) -> bool:
    return _blocks_player_spawn_shell(candidate._collision_shell, player_rect)


def _car_matches_travel(road, vertical: bool) -> bool:
    return (road.direction == "vertical" and not vertical) or (
        road.direction == "horizontal" and vertical
    )


def _spawn_probe_pose_valid(
    shell: Rect,
    rect: Rect,
    vertical: bool,
    roads,
    *,
    road_index: int | None = None,
    block_rects: tuple[Rect, ...] | None = None,
) -> bool:
    """Reject spawns mostly on sidewalks / blocks or barely on the lane."""
    area = max(1, shell.width * shell.height)
    if block_rects:
        block_limit = area * SPAWN_MAX_BLOCK_FRAC
        for br in block_rects:
            if _rect_overlap_area(shell, br) > block_limit:
                return False

    road_list: list
    if road_index is not None and 0 <= road_index < len(roads):
        road_list = [roads[road_index]]
    else:
        road_list = [r for r in roads if _car_matches_travel(r, vertical)]

    on_road = 0
    for road in road_list:
        if not _car_matches_travel(road, vertical):
            continue
        on_road += _rect_overlap_area(shell, road.rect)
    if on_road >= area * SPAWN_MIN_ROAD_FRAC:
        return True

    for road in road_list:
        if not _car_matches_travel(road, vertical):
            continue
        if road.direction == "vertical":
            if not (
                road.rect.top <= shell.centery <= road.rect.bottom
                and shell.centerx >= road.rect.left - CAR_WIDTH - 48
                and shell.centerx <= road.rect.right + CAR_WIDTH + 48
            ):
                continue
        else:
            if not (
                road.rect.left <= shell.centerx <= road.rect.right
                and shell.centery >= road.rect.top - CAR_HEIGHT - 48
                and shell.centery <= road.rect.bottom + CAR_HEIGHT + 48
            ):
                continue
        return True
    return False


def _car_spawn_pose_valid(candidate: Car, roads, city_blocks=None) -> bool:
    block_rects = _city_block_rects_from(city_blocks)
    return _spawn_probe_pose_valid(
        candidate._collision_shell,
        candidate.rect,
        candidate.vertical,
        roads,
        road_index=candidate.road_index,
        block_rects=block_rects,
    )


def _spawn_forward_lane_clear(
    rect: Rect,
    vertical: bool,
    direction: int,
    peers,
) -> bool:
    """True when no same-lane car is too close along the travel axis."""
    along_len = CAR_HEIGHT if vertical else CAR_WIDTH
    need_gap = along_len + MIN_ALONG_GAP + 6
    for other in peers:
        if other.vertical != vertical or other.direction != direction:
            continue
        if vertical:
            ahead = (other.rect.centery - rect.centery) * direction
            lane_gap = abs(other.rect.centerx - rect.centerx)
        else:
            ahead = (other.rect.centerx - rect.centerx) * direction
            lane_gap = abs(other.rect.centery - rect.centery)
        if lane_gap >= CAR_FOLLOW_LANE_GAP:
            continue
        if abs(ahead) < need_gap:
            return False
    return True


def _spawn_probe_blocked(
    shell: Rect,
    rect: Rect,
    vertical: bool,
    direction: int,
    road_index: int,
    cars_group,
    roads,
    intersection_zones=None,
    player_rect=None,
    block_rects: tuple[Rect, ...] | None = None,
    world_rect=None,
    spatial: CarSpatialIndex | None = None,
    scratch: list | None = None,
) -> bool:
    if _blocks_player_spawn_shell(shell, player_rect):
        return True
    if not _spawn_probe_pose_valid(
        shell,
        rect,
        vertical,
        roads,
        road_index=road_index,
        block_rects=block_rects,
    ):
        return True
    if intersection_zones:
        for zone in intersection_zones:
            if rects_overlap(zone, shell):
                return True
            if rects_overlap(
                zone.inflate(INTERSECTION_APPROACH_SPAWN_PAD, INTERSECTION_APPROACH_SPAWN_PAD),
                shell,
            ):
                return True
    pad = RECT_COLLIDE_PAD + CAR_NEARBY_PAD
    if spatial is not None and scratch is not None:
        peers = spatial.nearby(shell, pad, scratch)
    else:
        peers = cars_group
    padded = shell.inflate(RECT_COLLIDE_PAD, RECT_COLLIDE_PAD)
    for other in peers:
        oc = other._collision_shell
        if rects_overlap(padded, oc):
            return True
        if other.turn_signal != 0 or other._turn_phase != "none":
            reserved = other._turn_reserved_rect(intersection_zones)
            if reserved is not None and rects_overlap(shell, reserved):
                return True
        if other.vertical == vertical and other.direction == direction:
            if vertical:
                ahead = (other.rect.centery - rect.centery) * direction
                lane_gap = abs(other.rect.centerx - rect.centerx)
            else:
                ahead = (other.rect.centerx - rect.centerx) * direction
                lane_gap = abs(other.rect.centery - rect.centery)
            along_len = CAR_HEIGHT if vertical else CAR_WIDTH
            if lane_gap < CAR_FOLLOW_LANE_GAP and abs(ahead) < along_len + MIN_ALONG_GAP:
                return True
    return False


def _car_blocks_spawn(
    candidate: Car,
    cars_group,
    roads,
    intersection_zones=None,
    player_rect=None,
    city_blocks=None,
    world_rect=None,
    spatial: CarSpatialIndex | None = None,
    scratch: list | None = None,
    block_rects: tuple[Rect, ...] | None = None,
) -> bool:
    if block_rects is None:
        block_rects = _city_block_rects_from(city_blocks)
    road_index = candidate.road_index if candidate.road_index is not None else -1
    return _spawn_probe_blocked(
        candidate._collision_shell,
        candidate.rect,
        candidate.vertical,
        candidate.direction,
        road_index,
        cars_group,
        roads,
        intersection_zones,
        player_rect,
        block_rects,
        world_rect,
        spatial,
        scratch,
    )


def _spawn_car_from_event(
    event: TrafficSpawn,
    roads,
    cars_group,
    all_sprites_group,
    intersection_zones=None,
    player_rect=None,
    city_blocks=None,
    world_rect=None,
    ix_rects=None,
    max_pose_tries: int | None = None,
    for_respawn: bool = False,
    spatial: CarSpatialIndex | None = None,
    scratch: list | None = None,
) -> bool:
    road = roads[event.road_index]
    if event.phase == PHASE_ONGOING:
        queue_cap = 3 if for_respawn else EDGE_SPAWN_QUEUE_CAP
        if not edge_spawn_lane_allowed(
            cars_group,
            road,
            event.direction,
            world_rect,
            max_queue=queue_cap,
        ):
            return False
    elif not lane_spawn_allowed(cars_group, road, event.direction, event.phase):
        return False
    if ix_rects is None:
        ix_rects = build_intersection_rects(roads)
    poses = spawn_poses_for_event(road, event, ix_rects, world_rect)
    if max_pose_tries is not None:
        poses = poses[:max_pose_tries]
    block_rects = _round_city_block_rects or _city_block_rects_from(city_blocks)
    for x, y, direction_sign, vertical in poses:
        if pose_overlaps_intersection_rects(x, y, vertical, ix_rects):
            continue
        probe_rect, probe_shell = _spawn_probe_geometry(x, y, vertical)
        direction = 1 if direction_sign >= 0 else -1
        if _spawn_probe_blocked(
            probe_shell,
            probe_rect,
            vertical,
            direction,
            event.road_index,
            cars_group,
            roads,
            intersection_zones,
            player_rect,
            block_rects,
            world_rect,
            spatial,
            scratch,
        ):
            continue
        if spatial is not None and scratch is not None:
            lane_peers = spatial.nearby(probe_shell, CAR_NEARBY_PAD, scratch)
        else:
            lane_peers = cars_group
        if not _spawn_forward_lane_clear(probe_rect, vertical, direction, lane_peers):
            continue
        speed = CAR_SPEED * CAR_SPEED_MULT * direction_sign
        candidate = Car(
            x,
            y,
            speed,
            vertical=vertical,
            archetype_index=event.archetype_index,
            spawn_id=event.event_id,
            road_index=event.road_index,
        )
        candidate._spawn_origin = CarSpawnOrigin(
            event.road_index,
            1 if direction_sign >= 0 else -1,
            event.along_frac,
            event.phase,
        )
        cars_group.add(candidate)
        all_sprites_group.add(candidate)
        return True
    return False


def _queue_car_respawn(car: Car) -> None:
    global traffic_respawn_pending, round_frame
    origin = car._spawn_origin
    if origin is None:
        return
    if len(traffic_respawn_pending) >= RESPAWN_PENDING_CAP:
        traffic_respawn_pending.pop(0)
    traffic_respawn_pending.append(
        RespawnRequest(origin, round_frame + RESPAWN_DELAY_FRAMES)
    )


def _cached_intersection_rects(roads, frame_id: int):
    global _ix_rects_cache, _ix_rects_cache_frame
    if _ix_rects_cache_frame != frame_id:
        _ix_rects_cache = build_intersection_rects(roads)
        _ix_rects_cache_frame = frame_id
    return _ix_rects_cache


def _process_car_respawns(
    target_frame: int,
    roads,
    cars,
    all_sprites,
    intersection_zones=None,
    player_rect=None,
    city_blocks=None,
    world_rect=None,
    ix_rects=None,
    spatial: CarSpatialIndex | None = None,
    scratch: list | None = None,
):
    global traffic_respawn_pending, traffic_respawn_event_id

    if not traffic_respawn_pending:
        return

    ready: list[RespawnRequest] = []
    waiting: list[RespawnRequest] = []
    for req in traffic_respawn_pending:
        if req.due_frame <= target_frame:
            ready.append(req)
        else:
            waiting.append(req)

    spawned = 0
    deferred: list[RespawnRequest] = []
    for req in ready:
        if spawned >= MAX_RESPAWNS_PER_FRAME:
            deferred.append(req)
            continue
        origin = req.origin
        traffic_respawn_event_id += 1
        event = TrafficSpawn(
            frame=0,
            road_index=origin.road_index,
            along_frac=origin.along_frac,
            direction=origin.direction,
            archetype_index=sprites.pick_random_archetype_index(),
            event_id=traffic_respawn_event_id,
            phase=origin.phase,
        )
        if _spawn_car_from_event(
            event,
            roads,
            cars,
            all_sprites,
            intersection_zones,
            player_rect,
            city_blocks,
            world_rect,
            ix_rects=ix_rects,
            max_pose_tries=RESPAWN_POSE_TRIES,
            for_respawn=True,
            spatial=spatial,
            scratch=scratch,
        ):
            spawned += 1
        else:
            deferred.append(
                RespawnRequest(origin, target_frame + RESPAWN_RETRY_FRAMES)
            )

    traffic_respawn_pending = waiting + deferred
    if len(traffic_respawn_pending) > RESPAWN_PENDING_CAP:
        traffic_respawn_pending = traffic_respawn_pending[-RESPAWN_PENDING_CAP:]


def _process_traffic_spawns_through_frame(
    target_frame: int,
    roads,
    cars,
    all_sprites,
    intersection_zones=None,
    player_rect=None,
    city_blocks=None,
    world_rect=None,
):
    global traffic_spawn_cursor, traffic_spawn_retry

    spawn_scratch = _frame_nearby_scratch
    ix_rects = _cached_intersection_rects(roads, target_frame)
    backlog = len(traffic_spawn_retry)
    spawn_budget = 6
    if backlog >= 16:
        spawn_budget = 2
    elif backlog >= 8:
        spawn_budget = 4
    retry_budget = SPAWN_RETRY_BUDGET_PER_FRAME
    if backlog >= 24:
        retry_budget = 1

    _process_car_respawns(
        target_frame,
        roads,
        cars,
        all_sprites,
        intersection_zones,
        player_rect,
        city_blocks,
        world_rect,
        ix_rects=ix_rects,
        spatial=_frame_car_spatial,
        scratch=spawn_scratch,
    )

    still_retry: list[TrafficSpawn] = []
    for event in traffic_spawn_retry:
        if spawn_budget <= 0 or retry_budget <= 0:
            still_retry.append(event)
            continue
        if event.frame > target_frame:
            still_retry.append(event)
            continue
        if target_frame - event.frame > MAX_SPAWN_DEFER_FRAMES:
            continue
        if _spawn_car_from_event(
            event,
            roads,
            cars,
            all_sprites,
            intersection_zones,
            player_rect,
            city_blocks,
            world_rect,
            ix_rects=ix_rects,
            spatial=_frame_car_spatial,
            scratch=spawn_scratch,
        ):
            spawn_budget -= 1
            retry_budget -= 1
            continue
        still_retry.append(event)
    traffic_spawn_retry = still_retry[:SPAWN_RETRY_SLOTS]

    while traffic_spawn_cursor < len(traffic_schedule) and spawn_budget > 0:
        event = traffic_schedule[traffic_spawn_cursor]
        if event.frame > target_frame:
            break
        lag = target_frame - event.frame
        if lag > MAX_SPAWN_DEFER_FRAMES:
            traffic_spawn_cursor += 1
            continue
        if _spawn_car_from_event(
            event,
            roads,
            cars,
            all_sprites,
            intersection_zones,
            player_rect,
            city_blocks,
            world_rect,
            ix_rects=ix_rects,
            spatial=_frame_car_spatial,
            scratch=spawn_scratch,
        ):
            traffic_spawn_cursor += 1
            spawn_budget -= 1
            continue
        if (
            lag < MAX_SPAWN_DEFER_FRAMES
            and len(still_retry) < SPAWN_RETRY_SLOTS
            and len(still_retry) < 32
        ):
            still_retry.append(event)
        traffic_spawn_cursor += 1


# --- Per-round state (initialized in start_round) ---
current_map = None
ROUND_TIME_LIMIT = 30
CAR_SPEED_MULT = 1.0
SPAWN_RATE_MULT = 1.0
LIGHT_CYCLE_SCALE = 1.0
_LIGHT_GREEN = LIGHT_GREEN_DURATION
_LIGHT_YELLOW = LIGHT_YELLOW_DURATION
_LIGHT_RED = LIGHT_RED_DURATION
cars = EntityGroup()
player = None
all_sprites = EntityGroup()
start_time = 0.0
crossings = 0
collisions = 0
risk_events = 0
last_risk_time = 0
failure_reason = "none"
round_active = False
app_running = True
current_round_index = 1
current_difficulty_profile = None
base_preset_id = "normal"
session_num_rounds = pre_game.DEFAULT_ROUNDS
session_base_seed = 0
session_seed_source = "random"
session_use_adaptive_map = False
round_results = []
world_bounds = None
road_states = []
road_states_h: list = []
road_states_by_index: list[list] = []
_round_city_block_rects: tuple[Rect, ...] = ()
road_states_v: list = []
intersection_zones = []
intersection_zones_shell: list[Rect] = []
wall_rects = []
frame_recorder = None
decision_logger = None
traffic_schedule: list[TrafficSpawn] = []
traffic_spawn_cursor = 0
traffic_spawn_retry: list[TrafficSpawn] = []
traffic_respawn_pending: list[RespawnRequest] = []
traffic_respawn_event_id = RESPAWN_EVENT_ID_BASE
_ix_rects_cache = None
_ix_rects_cache_frame = -1
traffic_map_seed = 0
round_frame = 0


def _apply_difficulty_globals(profile: DifficultyProfile):
    global CAR_SPEED_MULT, SPAWN_RATE_MULT, LIGHT_CYCLE_SCALE
    global _LIGHT_GREEN, _LIGHT_YELLOW, _LIGHT_RED
    CAR_SPEED_MULT = profile.car_speed_mult
    SPAWN_RATE_MULT = profile.spawn_rate_mult
    LIGHT_CYCLE_SCALE = profile.light_cycle_scale
    _LIGHT_GREEN, _LIGHT_YELLOW, _LIGHT_RED = _effective_light_durations(LIGHT_CYCLE_SCALE)


def start_round(round_index: int, difficulty_profile: DifficultyProfile, preset_id: str):
    global current_map, ROUND_TIME_LIMIT, cars, player, all_sprites
    global start_time, crossings, collisions, risk_events, last_risk_time, failure_reason
    global round_active, current_round_index, current_difficulty_profile, base_preset_id
    global world_bounds, road_states, road_states_h, road_states_v, road_states_by_index
    global _round_city_block_rects
    global intersection_zones, intersection_zones_shell, wall_rects
    global frame_recorder, decision_logger
    global traffic_schedule, traffic_spawn_cursor, traffic_spawn_retry
    global traffic_respawn_pending, traffic_respawn_event_id
    global _ix_rects_cache, _ix_rects_cache_frame, traffic_map_seed, round_frame
    global session_base_seed, session_use_adaptive_map

    current_round_index = round_index
    current_difficulty_profile = difficulty_profile
    base_preset_id = preset_id
    _apply_difficulty_globals(difficulty_profile)

    map_seed = _map_seed_for_round(session_base_seed, round_index)
    prior_session = _load_prior_session() if session_use_adaptive_map else None
    map_difficulty = None if session_use_adaptive_map else difficulty_profile

    current_map = map_generator.generate_map(
        seed=map_seed,
        prior_session=prior_session,
        difficulty=map_difficulty,
    )
    ROUND_TIME_LIMIT = current_map.time_limit

    cars = EntityGroup()
    player = Pedestrian(current_map.start_pos)
    all_sprites = EntityGroup(player)
    start_time = time.time()
    crossings = 0
    collisions = 0
    risk_events = 0
    last_risk_time = 0
    failure_reason = "none"

    frame_recorder = FrameRecorder(PEDESTRIAN_SIZE)
    decision_logger = DecisionLogger(
        current_map.start_pos,
        current_map.goal_rect.center,
        current_map.map_id,
        len(current_map.roads),
        frame_recorder=frame_recorder,
        analytics_zones=getattr(current_map, "analytics_zones", None),
    )

    world_bounds = build_world_bounds(current_map.roads, current_map.start_pos, current_map.goal_rect)
    road_states = build_road_states(current_map.roads)
    road_states_h = [s for s in road_states if s["direction"] == "horizontal"]
    road_states_v = [s for s in road_states if s["direction"] == "vertical"]
    road_states_by_index = _build_road_states_by_index(road_states, len(current_map.roads))
    _round_city_block_rects = _city_block_rects_from(
        getattr(current_map, "city_blocks", None)
    )
    intersection_zones = build_intersection_zones(current_map.roads)
    intersection_zones_shell = [
        zone.inflate(INTERSECTION_SHELL_PAD, INTERSECTION_SHELL_PAD)
        for zone in intersection_zones
    ]
    wall_rects = [
        Rect(world_bounds.left - 4000, world_bounds.top - 4000, 4000, world_bounds.height + 8000),
        Rect(world_bounds.right, world_bounds.top - 4000, 4000, world_bounds.height + 8000),
        Rect(world_bounds.left, world_bounds.top - 4000, world_bounds.width, 4000),
        Rect(world_bounds.left, world_bounds.bottom, world_bounds.width, 4000),
    ]

    traffic_map_seed = current_map.seed
    weights = getattr(current_map, "traffic_weights", None)
    traffic_schedule = generate_traffic_schedule(
        traffic_map_seed,
        current_map.roads,
        weights,
        difficulty_profile,
        ROUND_TIME_LIMIT,
    )
    traffic_spawn_cursor = 0
    traffic_spawn_retry = []
    traffic_respawn_pending = []
    traffic_respawn_event_id = RESPAWN_EVENT_ID_BASE
    _ix_rects_cache = None
    _ix_rects_cache_frame = -1
    round_frame = 0

    car_diagnostics.begin_round(
        current_round_index,
        session_seed=session_base_seed,
        map_seed=getattr(current_map, "seed", None),
        traffic_map_seed=traffic_map_seed,
    )

    round_active = True

    if ENABLE_PERF_PROFILE:
        perf_profiler.begin_round(
            round_index,
            map_id=str(getattr(current_map, "map_id", map_seed)),
            map_seed=map_seed,
            preset=preset_id,
            roads=len(current_map.roads),
            time_limit_s=ROUND_TIME_LIMIT,
        )

    current_map.bake(
        city_blocks=getattr(current_map, "city_blocks", None),
        decorations=getattr(current_map, "decorations", None),
        world_bounds=world_bounds,
        map_id=str(getattr(current_map, "map_id", map_seed)),
        road_states=road_states,
    )


def build_world_bounds(roads, start_pos, goal_rect):
    min_left = min([r.rect.left for r in roads] + [start_pos[0] - 80, goal_rect.left]) - 120
    max_right = max([r.rect.right for r in roads] + [start_pos[0] + 80, goal_rect.right]) + 120
    min_top = min([r.rect.top for r in roads] + [start_pos[1] - 80, goal_rect.top]) - 120
    max_bottom = max([r.rect.bottom for r in roads] + [start_pos[1] + 80, goal_rect.bottom]) + 120
    return Rect(min_left, min_top, max_right - min_left, max_bottom - min_top)


def build_road_states(roads):
    road_id_to_index = {id(road): idx for idx, road in enumerate(roads)}

    def add_state(
        collector, road, direction, crosswalk, sign_rect, phase_offset, approach
    ):
        collector.append(
            {
                "road_rect": road.rect,
                "approach_rect": road.rect.inflate(180, 180),
                "direction": direction,
                "approach": approach,
                "crosswalk": crosswalk,
                "stop_axis": crosswalk.centerx if direction == "vertical" else crosswalk.centery,
                "sign_rect": sign_rect,
                "phase_offset": phase_offset,
                "road_index": road_id_to_index[id(road)],
                "light_state": "green",
                "turn_light_state": "red",
                "turn_seconds_to_change": 0.0,
                "next_turn_light": "green",
                "player_waiting": False,
                "stop_active": True,
            }
        )

    road_states = []
    cycle = _LIGHT_GREEN + _LIGHT_YELLOW + _LIGHT_RED
    vertical_roads = [r for r in roads if r.direction == "vertical"]
    horizontal_roads = [r for r in roads if r.direction == "horizontal"]
    intersection_by_road = {id(road): [] for road in roads}

    for v_road in vertical_roads:
        for h_road in horizontal_roads:
            intersection_rect = clip_rect(v_road.rect, h_road.rect)
            if intersection_rect.width <= 0 or intersection_rect.height <= 0:
                continue
            intersection_by_road[id(v_road)].append(intersection_rect)
            intersection_by_road[id(h_road)].append(intersection_rect)

            base_offset = ((intersection_rect.centerx + intersection_rect.centery) % 31) / 31.0 * cycle
            v_phase, h_phase = perpendicular_phase_offsets(
                base_offset, _LIGHT_GREEN, _LIGHT_YELLOW
            )

            # Crossing across the horizontal road (left and right approaches).
            left_space = intersection_rect.left - v_road.rect.left
            right_space = v_road.rect.right - intersection_rect.right
            left_thickness = min(CROSSWALK_THICKNESS, max(0, left_space - INTERSECTION_GAP_MIN - 2))
            right_thickness = min(CROSSWALK_THICKNESS, max(0, right_space - INTERSECTION_GAP_MIN - 2))
            if left_thickness >= 4:
                left_x = intersection_rect.left - INTERSECTION_GAP_MIN - left_thickness
                left_crosswalk = Rect(left_x, v_road.rect.top, left_thickness, v_road.rect.height)
                left_housing = map_visuals.traffic_housing_rect(
                    left_crosswalk, "vertical", APPROACH_WEST
                )
                add_state(
                    road_states,
                    v_road,
                    "vertical",
                    left_crosswalk,
                    approach_sign_rect(left_housing, "vertical", APPROACH_WEST),
                    v_phase,
                    APPROACH_WEST,
                )
            if right_thickness >= 4:
                right_x = intersection_rect.right + INTERSECTION_GAP_MIN
                right_crosswalk = Rect(right_x, v_road.rect.top, right_thickness, v_road.rect.height)
                right_housing = map_visuals.traffic_housing_rect(
                    right_crosswalk, "vertical", APPROACH_EAST
                )
                add_state(
                    road_states,
                    v_road,
                    "vertical",
                    right_crosswalk,
                    approach_sign_rect(right_housing, "vertical", APPROACH_EAST),
                    v_phase,
                    APPROACH_EAST,
                )

            # Crossing across the vertical road (top and bottom approaches).
            top_space = intersection_rect.top - h_road.rect.top
            bottom_space = h_road.rect.bottom - intersection_rect.bottom
            top_thickness = min(CROSSWALK_THICKNESS, max(0, top_space - INTERSECTION_GAP_MIN - 2))
            bottom_thickness = min(CROSSWALK_THICKNESS, max(0, bottom_space - INTERSECTION_GAP_MIN - 2))
            if top_thickness >= 4:
                top_y = intersection_rect.top - INTERSECTION_GAP_MIN - top_thickness
                top_crosswalk = Rect(h_road.rect.left, top_y, h_road.rect.width, top_thickness)
                top_housing = map_visuals.traffic_housing_rect(
                    top_crosswalk, "horizontal", APPROACH_NORTH
                )
                add_state(
                    road_states,
                    h_road,
                    "horizontal",
                    top_crosswalk,
                    approach_sign_rect(top_housing, "horizontal", APPROACH_NORTH),
                    h_phase,
                    APPROACH_NORTH,
                )
            if bottom_thickness >= 4:
                bottom_y = intersection_rect.bottom + INTERSECTION_GAP_MIN
                bottom_crosswalk = Rect(h_road.rect.left, bottom_y, h_road.rect.width, bottom_thickness)
                bottom_housing = map_visuals.traffic_housing_rect(
                    bottom_crosswalk, "horizontal", APPROACH_SOUTH
                )
                add_state(
                    road_states,
                    h_road,
                    "horizontal",
                    bottom_crosswalk,
                    approach_sign_rect(bottom_housing, "horizontal", APPROACH_SOUTH),
                    h_phase,
                    APPROACH_SOUTH,
                )

    # Roads without intersections get one center crossing.
    for idx, road in enumerate(roads):
        if intersection_by_road[id(road)]:
            continue
        phase_offset = (idx * 3.7) % cycle
        if road.direction == "vertical":
            crosswalk = Rect(road.rect.centerx - CROSSWALK_THICKNESS // 2, road.rect.top, CROSSWALK_THICKNESS, road.rect.height)
            approach = APPROACH_WEST
            housing = map_visuals.traffic_housing_rect(crosswalk, "vertical", approach)
            sign_rect = approach_sign_rect(housing, "vertical", approach)
        else:
            crosswalk = Rect(road.rect.left, road.rect.centery - CROSSWALK_THICKNESS // 2, road.rect.width, CROSSWALK_THICKNESS)
            approach = APPROACH_NORTH
            housing = map_visuals.traffic_housing_rect(crosswalk, "horizontal", approach)
            sign_rect = approach_sign_rect(housing, "horizontal", approach)
        add_state(
            road_states, road, road.direction, crosswalk, sign_rect, phase_offset, approach
        )

    return road_states


def _build_road_states_by_index(road_states: list, road_count: int) -> list[list]:
    grouped = [[] for _ in range(road_count)]
    for state in road_states:
        road_index = state.get("road_index")
        if road_index is None or road_index < 0 or road_index >= road_count:
            continue
        grouped[road_index].append(state)
    return grouped


def _road_states_for_car(car, fallback_states: list) -> list:
    if car.road_index is None:
        return fallback_states
    if car.road_index < 0 or car.road_index >= len(road_states_by_index):
        return fallback_states
    tagged = road_states_by_index[car.road_index]
    return tagged if tagged else fallback_states


def build_intersection_zones(roads):
    zones = []
    vertical_roads = [r for r in roads if r.direction == "vertical"]
    horizontal_roads = [r for r in roads if r.direction == "horizontal"]
    for v_road in vertical_roads:
        for h_road in horizontal_roads:
            zone = clip_rect(v_road.rect, h_road.rect)
            if zone.width > 0 and zone.height > 0:
                zones.append(zone)
    return zones


def lane_center_for_road(road, direction, vertical):
    cx, cy = lane_center_xy(road, direction)
    if road.direction == "vertical":
        return cy
    return cx


def get_light_state(elapsed_seconds):
    return light_state_at(elapsed_seconds, _LIGHT_GREEN, _LIGHT_YELLOW, _LIGHT_RED)


def get_player_light_state(player_rect, states):
    body = sprites.player_body_hitbox(player_rect)
    for state in states:
        if collide(state["crosswalk"], body):
            return state["light_state"]
    return "none"


def get_pressed_keys(key_state: KeyState):
    return key_labels_from_state(key_state)


def _perf_counter_snapshot(
    *,
    car_list: list,
    replay_cars: list,
    draw_sprites: list,
) -> dict[str, int | float]:
    spatial = _frame_car_spatial
    bucket_entries = sum(len(b) for b in spatial._cells.values())
    replay_frames = len(frame_recorder.frames) if frame_recorder else 0
    decisions = len(decision_logger.decisions) if decision_logger else 0
    heat_samples = len(decision_logger.heat_samples) if decision_logger else 0
    return {
        "cars_alive": sum(1 for c in car_list if c.alive()),
        "cars_in_group": len(cars),
        "draw_sprites": len(draw_sprites),
        "record_cars": len(replay_cars),
        "cars_in_view": len(replay_cars),
        "replay_frames": replay_frames,
        "decisions": decisions,
        "heat_samples": heat_samples,
        "spawn_retry_queue": len(traffic_spawn_retry),
        "spawn_cursor": traffic_spawn_cursor,
        "spawn_schedule_len": len(traffic_schedule),
        "spatial_cells": len(spatial._cells),
        "spatial_bucket_entries": bucket_entries,
        "road_states": len(road_states),
    }


def end_round(collided, timed_out=False) -> str:
    global crossings, collisions, round_active, risk_events, failure_reason, round_results
    car_diagnostics.end_round()
    end_time = time.time()
    duration = round(end_time - start_time, 2)
    if collided:
        collisions += 1
        failure_reason = "collision"
        outcome = "collision"
    elif timed_out:
        failure_reason = "timeout"
        outcome = "timeout"
    else:
        failure_reason = "goal_reached"
        outcome = "success"

    camera_offset = (
        player.rect.centerx - WIDTH // 2,
        player.rect.centery - HEIGHT // 2,
    )
    end_cars = _cars_for_replay(
        [c for c in cars.sprites() if c.alive()],
        player.rect.center,
    )
    frame_recorder.capture_end(
        duration, player.rect, end_cars, road_states, game_time=duration
    )

    session = decision_logger.finalize(
        outcome=outcome,
        duration=duration,
        crossings=crossings,
        collisions=collisions,
        risk_events=risk_events,
        failure_reason=failure_reason,
    )
    session["map_layout"] = serialize_map_layout(current_map, road_states, world_bounds)
    session["map_seed"] = getattr(current_map, "seed", None)
    session["session_seed"] = session_base_seed
    session["time_limit"] = ROUND_TIME_LIMIT
    session["difficulty"] = getattr(current_map, "difficulty", None)
    session["round_index"] = current_round_index
    session["rounds_total"] = session_num_rounds
    session["base_preset"] = base_preset_id
    session["analytics_zones"] = getattr(current_map, "analytics_zones", [])
    session["path_estimate_s"] = getattr(current_map, "path_estimate_s", None)
    session["generation_meta"] = getattr(current_map, "generation_meta", None)
    session["car_archetypes"] = sprites.serialize_archetypes_for_log()
    archetypes = score_session(session)

    round_results.append(
        {
            "round": current_round_index,
            "outcome": outcome,
            "duration_s": duration,
            "crossings": crossings,
            "collisions": collisions,
            "risk_events": risk_events,
            "session": session,
            "archetypes": archetypes,
        }
    )
    round_active = False
    print(f"Round {current_round_index} complete:", outcome, f"({duration}s)")
    if ENABLE_PERF_PROFILE:
        report_path = perf_profiler.end_round(outcome, duration)
        print(f"Perf log: {perf_profiler.jsonl_path}")
        if report_path:
            print(f"Perf report: {report_path}")
        print("Share perf_profile.jsonl + perf_report.html for lag diagnosis.")
    return outcome


def save_session_log():
    if not round_results:
        return None
    last = round_results[-1]
    log = {
        "time": last["duration_s"],
        "crossings": last["crossings"],
        "collisions": last["collisions"],
        "risks_taken": last["risk_events"],
        "failure_reason": last["session"].get("failure_reason"),
        "outcome": last["outcome"],
        "min_crossings": len(last["session"].get("map_layout", {}).get("roads", [])) or 0,
        "avg_time_per_crossing": last["duration_s"] / max(1, last["crossings"]),
        "session": last["session"],
        "archetypes": last["archetypes"],
        "num_rounds": session_num_rounds,
        "session_seed": session_base_seed,
        "seed_source": session_seed_source,
        "pathwise_seed_env": os.environ.get("PATHWISE_SEED"),
        "adaptive_map": session_use_adaptive_map,
        "base_difficulty_preset": base_preset_id,
        "rounds": round_results,
    }
    with open("logs.json", "w", encoding="utf-8") as f:
        json.dump(log, f, indent=2)
    return build_dashboard_html("logs.json")


def record_risk(reason, cooldown=None, **context):
    global risk_events, last_risk_time
    local_cooldown = RISK_COOLDOWN_SECONDS if cooldown is None else cooldown
    if (time.time() - last_risk_time) > local_cooldown:
        risk_events += 1
        last_risk_time = time.time()
        decision_logger.note_risk(reason, **context)


def is_car_approaching_player(car, player_rect):
    body = sprites.player_body_hitbox(player_rect)
    if car.vertical:
        dx = abs(car.rect.centerx - body.centerx)
        if dx > 48:
            return False
        ahead = (body.centery - car.rect.centery) * car.direction
        return 0 < ahead < 220 and car.current_speed > car.base_speed * 0.35
    dy = abs(car.rect.centery - body.centery)
    if dy > 48:
        return False
    ahead = (body.centerx - car.rect.centerx) * car.direction
    return 0 < ahead < 220 and car.current_speed > car.base_speed * 0.35

def update_round_frame(keys: KeyState, *, before_shell_separation=None):
    """Advance simulation one frame; returns draw kwargs when the round is still active."""
    global round_frame, crossings, risk_events, last_risk_time
    elapsed = time.time() - start_time
    time_left = max(0, ROUND_TIME_LIMIT - elapsed)

    previous_pos = player.rect.topleft

    with perf_profiler.section("lights_and_crossings"):
        for state in road_states:
            state["light_state"] = get_light_state(elapsed + state["phase_offset"])
            state["player_waiting"] = False
            road_rect = state["road_rect"]
            crosswalk = state["crosswalk"]
            wait_zone = crosswalk.inflate(80, 80)
            if collide(wait_zone, player.rect) and not collide(road_rect, player.rect):
                state["player_waiting"] = True
        update_light_timers(road_states, elapsed)

        for road_index, road in enumerate(current_map.roads):
            approach_zone = road.rect.inflate(120, 120)
            if not road.crossed and collide(approach_zone, player.rect):
                decision_logger.note_road_approach(road_index)

            if collide(road.rect, player.rect) and not road.crossed:
                if road.direction == "vertical":
                    if player.rect.top < road.rect.top:
                        crossings += 1
                        road.crossed = True
                        decision_logger.note_road_crossed(
                            road_index, get_player_light_state(player.rect, road_states)
                        )
                elif road.direction == "horizontal":
                    if player.rect.left > road.rect.left:
                        crossings += 1
                        road.crossed = True
                        decision_logger.note_road_crossed(
                            road_index, get_player_light_state(player.rect, road_states)
                        )

    with perf_profiler.section("traffic_spawns"):
        _process_traffic_spawns_through_frame(
            round_frame,
            current_map.roads,
            cars,
            all_sprites,
            intersection_zones,
            player.rect,
            getattr(current_map, "city_blocks", None),
            world_bounds,
        )
    round_frame += 1

    with perf_profiler.section("player_update"):
        player.update(keys)
        if not contains_rect(world_bounds, player.rect):
            player.rect.topleft = previous_pos

    with perf_profiler.section("player_context"):
        player_body = sprites.player_body_hitbox(player.rect)
        player_on_crosswalk = any(
            collide(state["crosswalk"], player_body) for state in road_states
        )
        player_on_road = any(
            collide(road.rect, player_body) for road in current_map.roads
        )
        player_feet_road = player_feet_on_road(player.rect, current_map.roads)
        player_mostly_legal = player_mostly_on_legal_crosswalk(player_body, road_states)
        player_on_car_red = player_on_car_red_crosswalk_body(player_body, road_states)
        ped_legal_crossing = player_on_crosswalk and player_on_car_red
        respect_player = cars_should_respect_player(
            player_on_road, player_on_crosswalk, player_on_car_red
        )
        honk_allowed = should_honk_at_player_precomputed(
            player_feet_road,
            player_mostly_legal,
            player_on_crosswalk,
            player_on_car_red,
        )
        player_body_block = player_body.inflate(4, 4)

    camera_offset = (
        player.rect.centerx - WIDTH // 2,
        player.rect.centery - HEIGHT // 2,
    )
    view_rect = _view_rect_for_camera(camera_offset)
    replay_view = _replay_view_rect_for_camera(camera_offset)
    sim_view = view_rect.inflate(SIM_UPDATE_VIEW_PAD, SIM_UPDATE_VIEW_PAD)

    car_list = cars.sprites_into(_frame_car_list_scratch)
    with perf_profiler.section("cars_spatial"):
        _frame_car_spatial.rebuild(car_list)
        lane_buckets = _build_lane_buckets(car_list)
    move_scratch = _frame_nearby_scratch
    lane_scratch = _frame_lane_scratch
    with perf_profiler.section("cars_update"):
        for car in car_list:
            if not car.alive():
                continue
            in_intersection = bool(intersection_zones) and car._rect_in_intersection(
                car.rect, intersection_zones
            )
            in_active_turn = (
                car._turn_phase in ("to_hub", "turning", "settling")
                or car.turn_signal != 0
            )
            if (
                not in_intersection
                and not in_active_turn
                and not collide(sim_view, car._collision_shell)
                and (round_frame + car.spawn_id) % OFFSCREEN_UPDATE_STRIDE != 0
            ):
                car._spawn_age += 1
                signed = car.current_speed * car.direction
                if signed != 0:
                    if car.vertical:
                        car.rect.y += int(signed)
                    else:
                        car.rect.x += int(signed)
                car._sync_collision_shell()
                _frame_car_spatial.relocate_car(car)
                continue
            _lane_peers_for(car, lane_buckets, lane_scratch)
            peer_pad = IX_QUERY_PAD
            if car._turn_phase in ("to_hub", "turning", "settling") or car.turn_signal != 0:
                peer_pad += TURN_PEER_QUERY_PAD
            move_peers = _frame_car_spatial.nearby(
                car._collision_shell, peer_pad, move_scratch
            )
            car._frame_move_peers = move_peers
            car.update(
                _road_states_for_car(
                    car, road_states_v if car.vertical else road_states_h
                ),
                world_bounds,
                intersection_zones,
                player_body,
                current_map.roads,
                lane_scratch,
                move_peers,
                round_frame,
                player_on_road,
                player_on_crosswalk,
                player_feet_road,
                ped_legal_crossing,
                respect_player,
                honk_allowed,
                player_body_block,
                elapsed,
            )
            _frame_car_spatial.relocate_car(car)

    with perf_profiler.section("car_shell_separation"):
        if before_shell_separation is not None:
            before_shell_separation(car_list)
        _resolve_all_shell_overlaps(car_list)

    with perf_profiler.section("car_diagnostics"):
        if ENABLE_CAR_DIAGNOSTICS:
            player_center = player_body.center
            for car in car_list:
                if not car.alive():
                    continue
                car_diagnostics.observe(
                    car,
                    game_time=elapsed,
                    round_frame=round_frame,
                    intersection_zones=intersection_zones,
                    move_peers=car._frame_move_peers or (),
                    player_center=player_center,
                )

    with perf_profiler.section("risk_checks"):
        near_player_cars = _cars_near_player(
            player_body, _frame_car_spatial, _frame_player_car_scratch
        )
        replay_cars = _cars_for_replay(car_list, player_body.center)
        draw_cars = replay_cars
        if len(draw_cars) > MAX_DRAW_RECORD_CARS:
            draw_cars = _cap_cars_near_player(
                car_list,
                view_rect,
                player_body.center,
                MAX_DRAW_RECORD_CARS,
            )
        draw_sprites = _frame_draw_sprites_scratch
        draw_sprites.clear()
        draw_sprites.append(player)
        draw_sprites.extend(draw_cars)

        for car in cars:
            if car.honk_risk_pending:
                honk_reason = car.honk_reason or "honk"
                local_cooldown = 0.85
                if (time.time() - last_risk_time) > local_cooldown:
                    risk_events += 1
                    last_risk_time = time.time()
                decision_logger._record(
                    "car_honk",
                    reason=honk_reason,
                    risk=f"car_honk_{honk_reason}",
                )
                car.honk_risk_pending = False
        nearby_fast_cars = [
            car
            for car in near_player_cars
            if collide(car._collision_shell.inflate(170, 170), player_body)
            and car.current_speed > car.base_speed * 0.65
        ]
        approaching_cars = [
            car
            for car in near_player_cars
            if is_car_approaching_player(car, player.rect)
        ]

        if player_on_road and not player_on_crosswalk and nearby_fast_cars:
            record_risk("fast_traffic_on_road")
        if player_on_crosswalk and approaching_cars:
            crosswalk_red = player_on_car_red
            dangerous_cars = [
                car
                for car in approaching_cars
                if car.current_speed > car.base_speed * 0.25
            ]

            if not crosswalk_red or dangerous_cars:
                record_risk(
                    "crosswalk_vehicle_conflict",
                    on_crosswalk=True,
                    light=get_player_light_state(player.rect, road_states),
                )
            if any(
                collide(
                    car._collision_shell.inflate(TOO_CLOSE_DISTANCE, TOO_CLOSE_DISTANCE),
                    player_body,
                )
                for car in near_player_cars
            ):
                record_risk("vehicle_too_close", cooldown=0.7)
            if any(
                collide(
                    car._collision_shell.inflate(NEAR_MISS_DISTANCE, NEAR_MISS_DISTANCE),
                    player_body,
                )
                and car.current_speed > car.base_speed * 0.75
                for car in near_player_cars
            ):
                record_risk("near_miss")

    with perf_profiler.section("decision_logger"):
        decision_logger.update(
            player_body.center,
            get_pressed_keys(keys),
            player_on_crosswalk,
            player_on_road,
            get_player_light_state(player.rect, road_states),
            False,
        )

    with perf_profiler.section("frame_recorder"):
        if not frame_recorder.frames:
            frame_recorder.capture_start(
                elapsed, player.rect, replay_cars, road_states, game_time=elapsed
            )
        else:
            frame_recorder.capture(
                elapsed, player.rect, replay_cars, road_states, game_time=elapsed
            )

    with perf_profiler.section("round_end_checks"):
        if player_hits_any_car(
            player, cars, spatial=_frame_car_spatial, scratch=_frame_player_car_scratch
        ):
            end_round(True, timed_out=False)
        elif collide(player.rect, current_map.goal_rect):
            end_round(False, timed_out=False)

        if time_left <= 0 and round_active:
            end_round(False, timed_out=True)

    if not round_active:
        return None

    esc = (
        getattr(current_difficulty_profile, "round_escalation", 0.0)
        if current_difficulty_profile
        else 0.0
    )
    hud_lines = [
        f"Round {current_round_index}/{session_num_rounds} · intensity {esc * 100:.0f}%",
        f"Time left: {time_left:05.1f}s",
        f"Crossings: {crossings}/{len(current_map.roads)} · "
        f"traffic {sum(1 for c in car_list if c.alive())} "
        f"({max(0, len(draw_sprites) - 1)} on screen)",
        f"Risky moves: {risk_events}",
    ]
    if ENABLE_PERF_PROFILE:
        hud_lines.append(f"Perf log: {perf_profiler.jsonl_path}")
    perf_profiler.finish_update(
        round_frame=round_frame,
        elapsed_s=elapsed,
        counters=_perf_counter_snapshot(
            car_list=car_list,
            replay_cars=replay_cars,
            draw_sprites=draw_sprites,
        ),
    )
    return {
        "camera_offset": camera_offset,
        "view_rect": view_rect,
        "record_cars": draw_cars,
        "draw_sprites": draw_sprites,
        "elapsed": elapsed,
        "hud_lines": hud_lines,
    }


def draw_round_frame(window_height: int, draw_state: dict) -> None:
    from pathwise.game_draw import draw_round_scene

    draw_round_scene(
        window_height,
        current_map=current_map,
        player=player,
        world_bounds=world_bounds,
        road_states=road_states,
        wall_rects=wall_rects,
        draw_sprites=draw_state["draw_sprites"],
        record_cars=draw_state["record_cars"],
        camera_offset=draw_state["camera_offset"],
        view_rect=draw_state["view_rect"],
        elapsed=draw_state["elapsed"],
        hud_lines=draw_state["hud_lines"],
        light_green_duration=_LIGHT_GREEN,
        draw_traffic_timer_bar=TRAFFIC_DRAW_TIMER_BAR,
    )


def main():
    from pathwise.pathwise_window import PathwiseWindow

    PathwiseWindow().run()


if __name__ == "__main__":
    main()
