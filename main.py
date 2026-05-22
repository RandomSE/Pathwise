import math
import pygame
import random
import json
import time
from dataclasses import dataclass
import commonUtils
import map_generator
import map_visuals
import pre_game
import sprites
from map_generation.difficulty import DifficultyProfile
from map_generation.intersection_routing import (
    choose_exit,
    pick_turn_side,
    pivot_center_at_intersection,
    travel_vector,
    turn_side_from_exit,
)
from map_generation.lane_geometry import lane_center_xy
from map_generation.traffic_schedule import (
    MIN_ALONG_GAP,
    RECT_COLLIDE_PAD,
    TrafficSpawn,
    build_intersection_rects,
    edge_spawn_lane_allowed,
    generate_traffic_schedule,
    lane_spawn_allowed,
    PHASE_ONGOING,
    spawn_poses_for_event,
)
from analytics.decision_logger import DecisionLogger
from analytics.archetype_scoring import score_session
from analytics.dashboard import build_dashboard_html
from analytics.map_snapshot import serialize_map_layout
from analytics.frame_recorder import FrameRecorder

# --- Config ---
utils = commonUtils
WIDTH, HEIGHT = utils.WIDTH, utils.HEIGHT
ROAD_Y = utils.ROAD_Y
ROAD_HEIGHT = utils.ROAD_HEIGHT
CAR_WIDTH, CAR_HEIGHT = utils.CAR_WIDTH, utils.CAR_HEIGHT
PEDESTRIAN_SIZE = utils.PEDESTRIAN_SIZE
PEDESTRIAN_SPEED = utils.PEDESTRIAN_SPEED
CAR_SPEED = utils.CAR_SPEED
ROUND_TIME_LIMIT = 30
HUD_TEXT_COLOR = (20, 20, 20)
RISK_COOLDOWN_SECONDS = 1.5
# Green-heavy cycle; red ~= time to walk across pavement + ~2s buffer
LIGHT_GREEN_DURATION = 20.0
LIGHT_YELLOW_DURATION = 1.0
LIGHT_RED_DURATION = 4.5
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
CAR_SPAWN_RAMP_FRAMES = 90
ROAD_EXIT_PAD = 28
PLAYER_SPAWN_PAD = 280
SPAWN_MIN_ROAD_FRAC = 0.42
SPAWN_MAX_BLOCK_FRAC = 0.06
TURN_CHANCE = 0.22
TURN_HUB_DIST = 28
TURN_PIVOT_SPEED_FRAC = 0.35
TURN_DRIFT_SPEED_FRAC = 0.55
TURN_SETTLE_FRAMES = 14
TURN_MIN_ARC_LEN = 48.0
TURN_SIGNAL_LEAD_DIST = max(CAR_WIDTH, CAR_HEIGHT) * 2 + 24
TURN_ABORT_FRAMES = 150
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
HONK_CHECK_INTERVAL = 3
# Hard stop / gridlock rules (intersection locks). Keep off for flowing traffic.
ENABLE_CAR_CAR_COLLISION = False
# Slow, cap movement, and nudge apart so cars do not ghost through each other.
ENABLE_CAR_CAR_SOFT_AVOIDANCE = True
CAR_SOFT_FOLLOW_RANGE = 150
CAR_SOFT_STOP_GAP = 14

def _smoothstep(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return t * t * (3.0 - 2.0 * t)


def _lerp_angle_deg(a: float, b: float, t: float) -> float:
    delta = (b - a + 180.0) % 360.0 - 180.0
    return a + delta * t


# --- Init ---
pygame.init()
screen = pygame.display.set_mode((WIDTH, HEIGHT))
pygame.display.set_caption("Pathwise MVP")
clock = pygame.time.Clock()
font = pygame.font.SysFont(None, 28)
sign_font = pygame.font.SysFont(None, 16)
honk_font = pygame.font.SysFont(None, 20)
HONK_DURATION = 0.55
HONK_COOLDOWN = 1.1
HONK_CLOSE_PAD = 72


def player_on_car_red_crosswalk_body(player_body_rect, road_states):
    for state in road_states:
        if state["crosswalk"].colliderect(player_body_rect) and state["light_state"] == "red":
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
        inter = body_rect.clip(state["crosswalk"])
        on_red += inter.width * inter.height
    on_red = min(on_red, a)
    return on_red >= a * min_frac


def player_hits_any_car(player, cars_group, spatial=None, scratch: list | None = None):
    pb = sprites.player_body_hitbox(player.rect)
    if spatial is not None and scratch is not None:
        for car in spatial.nearby(pb, PLAYER_CAR_QUERY_PAD, scratch):
            if car._collision_shell.colliderect(pb):
                return True
        return False
    for car in cars_group:
        if car._collision_shell.colliderect(pb):
            return True
    return False


def _cars_near_player(player_body: pygame.Rect, spatial, scratch: list) -> list:
    return spatial.nearby(player_body, PLAYER_CAR_QUERY_PAD, scratch)


def _view_rect_for_camera(camera_offset: tuple[int, int]) -> pygame.Rect:
    return pygame.Rect(
        camera_offset[0] - FRAME_RECORD_VIEW_PAD,
        camera_offset[1] - FRAME_RECORD_VIEW_PAD,
        WIDTH + FRAME_RECORD_VIEW_PAD * 2,
        HEIGHT + FRAME_RECORD_VIEW_PAD * 2,
    )


def _cars_in_view(car_list, view_rect: pygame.Rect) -> list:
    return [c for c in car_list if c.alive() and view_rect.colliderect(c.rect)]


def cars_should_respect_player(player_on_road, player_on_crosswalk, on_car_red: bool):
    """Yield / stop for player only when they occupy the road or cross legally on red-for-cars."""
    if player_on_crosswalk:
        return on_car_red
    return player_on_road


def player_feet_on_road(player_rect, roads):
    """Lower body footprint must overlap pavement (visual on road, not sidewalk)."""
    feet = pygame.Rect(
        int(player_rect.x + player_rect.width * 0.18),
        int(player_rect.centery - player_rect.height * 0.05),
        int(player_rect.width * 0.64),
        int(player_rect.height * 0.42),
    )
    return any(road.rect.colliderect(feet) for road in roads)


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


def serialize_lights_for_frame(road_states):
    return [
        {
            "s": state["light_state"],
            "in": round(state.get("seconds_to_change", 0), 1),
            "next": state.get("next_light", "green"),
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

    __slots__ = ("cell", "_cells", "_stamp")

    def __init__(self, cell_size: int = SPATIAL_CELL):
        self.cell = cell_size
        self._cells: dict[tuple[int, int], list] = {}
        self._stamp = 0

    def clear(self) -> None:
        self._cells.clear()

    def rebuild(self, car_list) -> None:
        self.clear()
        cells = self._cells
        cs = self.cell
        for car in car_list:
            if not car.alive():
                continue
            shell = car._collision_shell
            x0 = shell.left // cs
            x1 = shell.right // cs
            y0 = shell.top // cs
            y1 = shell.bottom // cs
            for cx in range(x0, x1 + 1):
                row_base = cx
                for cy in range(y0, y1 + 1):
                    key = (row_base, cy)
                    bucket = cells.get(key)
                    if bucket is None:
                        cells[key] = [car]
                    else:
                        bucket.append(car)

    def _gather(self, rect: pygame.Rect, pad: int, out: list) -> list:
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

    def nearby(self, rect: pygame.Rect, pad: int, scratch: list) -> list:
        return self._gather(rect, pad, scratch)


_frame_car_spatial = CarSpatialIndex()
_frame_nearby_scratch: list = []
_frame_player_car_scratch: list = []
_frame_lane_scratch: list = []


# --- Entities ---
class Car(pygame.sprite.Sprite):
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
        self.rect = self.image.get_rect(topleft=(x, y))
        self.base_speed = abs(speed)
        self.acceleration = 0.16
        self.brake_strength = 0.42
        self.honk_until = 0.0
        self._last_honk_time = -999.0
        self.honk_risk_pending = False
        self.honk_reason = None
        self._stopped_frames = 0
        self._intersection_stuck_frames = 0
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
        self._off_road_frames = 0
        self._spatial_stamp = 0
        self._shell_sync_key = None
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
            v = self._turn_entry_vertical
            w, h = (CAR_HEIGHT, CAR_WIDTH) if v else (CAR_WIDTH, CAR_HEIGHT)
            cx, cy = round(self._turn_px), round(self._turn_py)
            key = (cx, cy, w, h, 1)
            if not force and key == self._shell_sync_key:
                return
            self._shell_sync_key = key
            body = pygame.Rect(0, 0, w, h)
            body.center = (cx, cy)
            self._collision_shell = sprites.car_collision_rect(body, v)
            return
        key = (self.rect.x, self.rect.y, 0, self.vertical)
        if not force and key == self._shell_sync_key:
            return
        self._shell_sync_key = key
        self._collision_shell = sprites.car_collision_rect(self.rect, self.vertical)

    def _snap_center_to_left_lane(self, roads, max_nudge: int | None = 8):
        """Align to keep-left lane center on the axis perpendicular to travel."""
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

    def _shell_hits_any_car(self, rect, vertical, peers) -> bool:
        shell = sprites.car_collision_rect(rect, vertical)
        for other in peers:
            if other is self:
                continue
            if shell.colliderect(other._collision_shell):
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
        if self._collision_shell.colliderect(player_body_rect):
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

        too_close = self._collision_shell.inflate(HONK_CLOSE_PAD, HONK_CLOSE_PAD).colliderect(
            player_body_rect
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

    def _soft_overlap_creep_cap(
        self, next_rect, move_peers, lane_peers
    ) -> float | None:
        """Max creep speed when the planned move still overlaps another car shell."""
        if not self._shell_hits_any_car(next_rect, self.vertical, move_peers):
            return None
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
            return roads[self.road_index].rect.colliderect(zone)
        for road in roads:
            if self._matches_road_travel(road) and road.rect.colliderect(zone):
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
        probe = pygame.Rect(0, 0, pw, ph)
        probe.center = (px, py)
        probe_shell = sprites.car_collision_rect(probe, vertical)
        if ENABLE_CAR_CAR_COLLISION:
            for other in peers:
                if other is self:
                    continue
                if probe_shell.colliderect(other._collision_shell):
                    return False
        if not ped_legal_crossing and probe_shell.colliderect(player_body_rect):
            return False
        return True

    def _abort_turn(self):
        was_visual_turn = self._turn_phase in ("turning", "settling")
        self.turn_signal = 0
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
            my = sprites.car_collision_rect(next_rect, self.vertical)
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
        for _ in range(4):
            my = sprites.car_collision_rect(next_rect, self.vertical)
            nudged = False
            for other in peers:
                if other is self:
                    continue
                oc = other._collision_shell
                if not my.colliderect(oc):
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

    def _hard_shell_overlap(self, rect, vertical, other) -> bool:
        my = sprites.car_collision_rect(rect, vertical)
        oc = other._collision_shell.inflate(-PERP_OVERLAP_SHRINK, -PERP_OVERLAP_SHRINK)
        if oc.width < 3 or oc.height < 3:
            return False
        return my.colliderect(oc)

    def _ix_creep_has_priority(self, other) -> bool:
        """Alternate which axis may inch through when both are stuck in the box."""
        if self._intersection_stuck_frames < INTERSECTION_STUCK_CREEP_FRAMES:
            return False
        if other._intersection_stuck_frames < INTERSECTION_STUCK_CREEP_FRAMES:
            return True
        return (self.spawn_id % 2) <= (other.spawn_id % 2)

    def _hard_block_after_cap(self, next_rect, peers, intersection_creep: bool) -> bool:
        for other in peers:
            if other is self:
                continue
            if not self._hard_shell_overlap(next_rect, self.vertical, other):
                continue
            if other.vertical != self.vertical:
                if intersection_creep and self._ix_creep_has_priority(other):
                    continue
                return True
            if other.direction == self.direction and self._same_lane(other, CAR_BLOCK_LANE_GAP):
                return True
        return False

    def _resolve_same_lane_penetration(self, peers):
        """If shells overlap a car ahead, push back (fixes frame-order / spawn glitches)."""
        g = CAR_FOLLOW_SEP
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
            my = sprites.car_collision_rect(self.rect, self.vertical)
            oc = other._collision_shell
            if not my.colliderect(oc):
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
        return any(z.colliderect(rect) for z in intersection_zones)

    def _shell_overlaps_intersection(self, intersection_zones, pad: int = 0) -> bool:
        if not intersection_zones:
            return False
        shell = self._collision_shell
        for zone in intersection_zones:
            box = zone.inflate(pad, pad) if pad else zone
            if box.colliderect(shell):
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
                return pygame.Rect(
                    cx - half, world_rect.top - CAR_EXIT_DESPAWN_MARGIN, half * 2, h
                )
            top = max(r.rect.bottom for r in lane)
            h = world_rect.bottom + CAR_EXIT_DESPAWN_MARGIN - top
            if h <= 4:
                return None
            return pygame.Rect(cx - half, top, half * 2, h)
        cy = int(sum(r.rect.centery for r in lane) / len(lane))
        half = max(EXIT_CORRIDOR_LATERAL, max(r.rect.height for r in lane) // 2 + 12)
        if self.direction > 0:
            right = min(r.rect.left for r in lane)
            w = right - (world_rect.left - CAR_EXIT_DESPAWN_MARGIN)
            if w <= 4:
                return None
            return pygame.Rect(
                world_rect.left - CAR_EXIT_DESPAWN_MARGIN, cy - half, w, half * 2
            )
        left = max(r.rect.right for r in lane)
        w = world_rect.right + CAR_EXIT_DESPAWN_MARGIN - left
        if w <= 4:
            return None
        return pygame.Rect(left, cy - half, w, half * 2)

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
                return pygame.Rect(cx - half, top, half * 2, h)
            bottom = min(r.rect.top for r in lane)
            h = bottom - world_rect.top + CAR_EXIT_DESPAWN_MARGIN
            if h <= 4:
                return None
            return pygame.Rect(cx - half, world_rect.top - CAR_EXIT_DESPAWN_MARGIN, half * 2, h)
        cy = int(sum(r.rect.centery for r in lane) / len(lane))
        half = max(EXIT_CORRIDOR_LATERAL, max(r.rect.height for r in lane) // 2 + 12)
        if self.direction > 0:
            left = max(r.rect.right for r in lane)
            w = world_rect.right + CAR_EXIT_DESPAWN_MARGIN - left
            if w <= 4:
                return None
            return pygame.Rect(left, cy - half, w, half * 2)
        right = min(r.rect.left for r in lane)
        w = right - world_rect.left + CAR_EXIT_DESPAWN_MARGIN
        if w <= 4:
            return None
        return pygame.Rect(world_rect.left - CAR_EXIT_DESPAWN_MARGIN, cy - half, w, half * 2)

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
            if not shell.colliderect(zone):
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
                if corridor is not None and corridor.colliderect(self._collision_shell):
                    return True
        return False

    def _on_traffic_network(self, roads, intersection_zones, world_rect=None) -> bool:
        """Generous check for anchoring only (segment gaps); not used for despawn."""
        shell = self._collision_shell
        for road in roads:
            if road.rect.inflate(NETWORK_ROAD_PAD, NETWORK_ROAD_PAD).colliderect(shell):
                return True
        if self._in_street_corridor(roads):
            return True
        if world_rect is not None:
            for corridor in (
                self._entry_corridor_rect(roads, world_rect),
                self._exit_corridor_rect(roads, world_rect),
            ):
                if corridor is not None and corridor.colliderect(shell):
                    return True
        if intersection_zones:
            for zone in intersection_zones:
                z = zone.inflate(NETWORK_IX_PAD, NETWORK_IX_PAD)
                if z.colliderect(shell):
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
        self.rect = self.image.get_rect(center=center)
        self._shell_sync_key = None

    def _bezier_point(self, t: float) -> tuple[float, float]:
        sx, sy = self._turn_arc_start
        mx, my = self._turn_arc_mid
        ex, ey = self._turn_arc_end
        u = 1.0 - t
        cx = u * u * sx + 2.0 * u * t * mx + t * t * ex
        cy = u * u * sy + 2.0 * u * t * my + t * t * ey
        return cx, cy

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
        self.rect = pygame.Rect(0, 0, self._turn_side, self._turn_side)
        self.rect.center = (round(px), round(py))
        self._shell_sync_key = None

    def _intersection_zone_at(self, intersection_zones):
        for zone in intersection_zones:
            if zone.colliderect(self.rect):
                return zone
        return None

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
        if key == self._turn_zone_key:
            return
        rng = random.Random((traffic_map_seed + self.spawn_id * 31) & 0xFFFFFFFF)
        turn_side = pick_turn_side(rng, TURN_CHANCE)
        if turn_side == 0:
            self._turn_zone_key = key
            self.turn_signal = 0
            self._turn_exit = None
            return
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
            return
        self._turn_zone_key = key
        self._turn_exit = exit_plan
        idx, d, exit_vertical = exit_plan
        self.turn_signal = turn_side_from_exit(
            self.vertical, self.direction, exit_vertical, d
        )

    def _arm_turn_through_hub(self, roads, intersection_zones):
        """Commit to hub turn once a planned turn is near or inside the box."""
        if self.turn_signal == 0 or not self._turn_exit or not intersection_zones:
            return
        if not self._approaching_or_in_intersection(intersection_zones):
            return
        zone = self._intersection_zone_for_turn_planning(intersection_zones, roads)
        if zone is None:
            zone = self._intersection_zone_at(intersection_zones)
        if zone is None:
            return
        if self._turn_phase == "none":
            self._turn_phase = "to_hub"
            self._turn_hub = (zone.centerx, zone.centery)

    def _begin_turn_steer(
        self,
        roads,
        zone,
        peers,
        player_body_rect,
        ped_legal_crossing: bool,
    ) -> bool:
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
        hx, hy = self._turn_hub or (zone.centerx, zone.centery)
        ex, ey = lane_center_xy(roads[idx], d)
        self._turn_arc_start = (self._turn_px, self._turn_py)
        self._turn_arc_mid = (float(hx), float(hy))
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

        step = (
            max(0.35, self.current_speed)
            * TURN_DRIFT_SPEED_FRAC
        )
        self._turn_arc_travel = min(self._turn_arc_len, self._turn_arc_travel + step)
        ease = _smoothstep(self._turn_arc_travel / self._turn_arc_len)
        angle = _lerp_angle_deg(self._turn_angle_start, self._turn_angle_end, ease)
        cx, cy = self._bezier_point(ease)

        self._set_turn_visual(angle, cx, cy)
        self.current_speed = max(self.current_speed, self.base_speed * TURN_DRIFT_SPEED_FRAC * 0.45)
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

    def _settle_turn_exit(self, roads) -> bool:
        """Ease position onto the exit lane and swap back to axis-aligned sprite."""
        if self._turn_phase != "settling" or not self._turn_exit:
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
        fx, fy = travel_vector(self.vertical, self.direction)
        past_hub = (self.rect.centerx - hx) * fx + (self.rect.centery - hy) * fy > 10
        lead = TURN_HUB_DIST + TURN_SIGNAL_LEAD_DIST // 3
        if dist > lead and not past_hub:
            return False
        return self._begin_turn_steer(
            roads, zone, peers, player_body_rect, ped_legal_crossing
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
        if self._shell_overlaps_intersection(
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
        if self._turn_phase in ("to_hub", "turning", "settling") or self.turn_signal != 0:
            return None
        if self._shell_overlaps_intersection(
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
            z.colliderect(self.rect) or z.colliderect(next_rect) for z in intersection_zones
        )

    def _entry_blocks_moving_cross_traffic(
        self, next_rect, peers, intersection_zones
    ) -> bool:
        """Do not enter the box if we'd cut in front of moving perpendicular traffic."""
        my_n = sprites.car_collision_rect(next_rect, self.vertical)
        for zone in intersection_zones:
            if not (next_rect.colliderect(zone) and not self.rect.colliderect(zone)):
                continue
            for other in peers:
                if other is self or other.vertical == self.vertical:
                    continue
                if other.current_speed < other.base_speed * 0.2:
                    continue
                if not zone.collidepoint(other.rect.center):
                    continue
                orect = other._collision_shell.inflate(-6, -6)
                if orect.width > 2 and orect.height > 2 and my_n.colliderect(orect):
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
                if not my_n.colliderect(other._collision_shell):
                    continue
                gap, _ = self._distance_to_other(other)
                if gap <= 0 or gap < 22:
                    return True
                continue
            if other.vertical == self.vertical:
                continue
            if not my_n.colliderect(other._collision_shell):
                continue
            if allow_perp_creep:
                if not self._hard_shell_overlap(next_rect, self.vertical, other):
                    continue
                if self._ix_creep_has_priority(other):
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
        intersection_creep = (
            inside_intersection
            and self._intersection_stuck_frames >= INTERSECTION_STUCK_CREEP_FRAMES
        )
        self._spawn_age += 1
        ramp_cap = self._spawn_ramp_cap()
        plan_turn = self.turn_signal != 0 or self._approaching_or_in_intersection(
            intersection_zones
        )
        if plan_turn and (frame_index + self.spawn_id) % 2 == 0:
            self._plan_turn_at_intersection(
                roads,
                intersection_zones,
                move_peers,
                player_body_rect,
                ped_legal_crossing,
            )
        self._arm_turn_through_hub(roads, intersection_zones)
        if self._turn_phase in ("to_hub", "turning", "settling"):
            desired_speed = min(desired_speed, self.base_speed * TURN_PIVOT_SPEED_FRAC)

        if ENABLE_CAR_CAR_SOFT_AVOIDANCE and self._turn_phase not in (
            "to_hub",
            "turning",
            "settling",
        ):
            self._resolve_same_lane_penetration(lane_peers)
        self._sync_collision_shell()

        for state in road_states:
            if not self.rect.colliderect(state["approach_rect"]):
                continue

            if self.vertical:
                stop_distance = (state["stop_axis"] - self.rect.centery) * self.direction
                in_crossing_lane = abs(self.rect.centerx - state["crosswalk"].centerx) < 50
            else:
                stop_distance = (state["stop_axis"] - self.rect.centerx) * self.direction
                in_crossing_lane = abs(self.rect.centery - state["crosswalk"].centery) < 50

            if in_crossing_lane:
                # Do not hold at lights while already in the intersection box — clear it.
                # Player / collision avoidance still applies below.
                if not inside_intersection:
                    red_stop_range = 195
                    if (
                        state["light_state"] == "red"
                        and state["crosswalk"].colliderect(player_body_rect)
                    ):
                        red_stop_range = 235
                    if state["light_state"] == "red" and 0 < stop_distance < red_stop_range:
                        desired_speed = 0
                        blocking_controls.append(state)
                    elif state["light_state"] == "yellow" and 0 < stop_distance < 150:
                        if stop_distance < 80:
                            desired_speed = 0
                        else:
                            desired_speed = min(desired_speed, self.base_speed * 0.5)

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
                if not state["crosswalk"].colliderect(player_body_rect):
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
            self._settle_turn_exit(roads)
        elif blocked_by_line:
            self.current_speed = 0
            self.speed = 0
        else:
            next_rect = self.rect.copy()
            if self.vertical:
                next_rect.y += signed_speed
            else:
                next_rect.x += signed_speed

            if ENABLE_CAR_CAR_SOFT_AVOIDANCE:
                next_rect = self._cap_next_rect_same_lane(next_rect, lane_peers)
                next_rect = self._cap_next_rect_all_cars(next_rect, move_peers)

            blocked = False
            creep_cap = None
            my_n = sprites.car_collision_rect(next_rect, self.vertical)
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
                        next_rect, self.vertical, move_peers
                    ):
                        if in_ix_move and intersection_creep and not self._hard_block_after_cap(
                            next_rect, move_peers, True
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
                            if not my_n.colliderect(other._collision_shell):
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
                        next_rect, move_peers, lane_peers
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
                    and my_n.colliderect(pbb)
                ):
                    blocked = True

            if blocked:
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
            self._try_start_turn_at_hub(
                roads,
                intersection_zones,
                move_peers,
                player_body_rect,
                ped_legal_crossing,
            )
        if self._turn_phase in ("to_hub", "turning", "settling") and inside_intersection:
            if self.current_speed < 0.35:
                self._turn_blocked_frames += 1
            elif self._turn_blocked_frames > 0:
                self._turn_blocked_frames = max(0, self._turn_blocked_frames - 2)
        else:
            self._turn_blocked_frames = 0
        if self._turn_blocked_frames >= TURN_ABORT_FRAMES:
            self._abort_turn()

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
            self._snap_center_to_left_lane(roads, max_nudge=None)

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


class Pedestrian(pygame.sprite.Sprite):
    def __init__(self, start_pos):
        super().__init__()
        self.image = sprites.make_pedestrian_surface(PEDESTRIAN_SIZE)
        self.rect = self.image.get_rect(center=start_pos) 
    def update(self, keys):
        dx = dy = 0
        if keys[pygame.K_LEFT] or keys[pygame.K_a]:
            dx -= PEDESTRIAN_SPEED
        if keys[pygame.K_RIGHT] or keys[pygame.K_d]:
            dx += PEDESTRIAN_SPEED
        if keys[pygame.K_UP] or keys[pygame.K_w]:
            dy -= PEDESTRIAN_SPEED
        if keys[pygame.K_DOWN] or keys[pygame.K_s]:
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
    """Keep green long; yellow stays short; red lengthens slightly on harder cycles."""
    green = LIGHT_GREEN_DURATION * max(0.88, scale)
    yellow = max(0.7, LIGHT_YELLOW_DURATION * scale)
    red = LIGHT_RED_DURATION + max(0.0, (1.0 - scale) * 1.5)
    return green, yellow, red


def _rect_overlap_area(a: pygame.Rect, b: pygame.Rect) -> int:
    inter = a.clip(b)
    if inter.width <= 0 or inter.height <= 0:
        return 0
    return inter.width * inter.height


def _blocks_player_spawn(candidate: Car, player_rect) -> bool:
    if player_rect is None:
        return False
    pb = sprites.player_body_hitbox(player_rect)
    zone = player_rect.inflate(PLAYER_SPAWN_PAD, PLAYER_SPAWN_PAD)
    shell = candidate._collision_shell
    return shell.colliderect(pb) or shell.colliderect(zone)


def _car_matches_travel(road, vertical: bool) -> bool:
    return (road.direction == "vertical" and not vertical) or (
        road.direction == "horizontal" and vertical
    )


def _car_spawn_pose_valid(candidate: Car, roads, city_blocks=None) -> bool:
    """Reject spawns mostly on sidewalks / blocks or barely on the lane."""
    shell = candidate._collision_shell
    area = max(1, shell.width * shell.height)
    on_road = 0
    matching = []
    for road in roads:
        if not _car_matches_travel(road, candidate.vertical):
            continue
        matching.append(road)
        on_road += _rect_overlap_area(shell, road.rect)
    for block in city_blocks or []:
        br = pygame.Rect(
            int(block["x"]),
            int(block["y"]),
            int(block["w"]),
            int(block["h"]),
        )
        if _rect_overlap_area(shell, br) > area * SPAWN_MAX_BLOCK_FRAC:
            return False
    if on_road >= area * SPAWN_MIN_ROAD_FRAC:
        return True
    # Edge-queue spawn: mostly off asphalt but aligned with the lane band.
    for road in matching:
        if road.direction == "vertical":
            band = pygame.Rect(
                road.rect.left - CAR_WIDTH - 48,
                road.rect.top + 6,
                road.rect.width + (CAR_WIDTH + 48) * 2,
                road.rect.height - 12,
            )
            if not band.colliderect(shell):
                continue
            if not (road.rect.top <= shell.centery <= road.rect.bottom):
                continue
        else:
            band = pygame.Rect(
                road.rect.left + 6,
                road.rect.top - CAR_HEIGHT - 48,
                road.rect.width - 12,
                road.rect.height + (CAR_HEIGHT + 48) * 2,
            )
            if not band.colliderect(shell):
                continue
            if not (road.rect.left <= shell.centerx <= road.rect.right):
                continue
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
) -> bool:
    if _blocks_player_spawn(candidate, player_rect):
        return True
    if not _car_spawn_pose_valid(candidate, roads, city_blocks):
        return True
    cc = candidate._collision_shell
    if intersection_zones and world_rect is not None:
        if world_rect.colliderect(candidate.rect):
            if any(z.colliderect(cc) for z in intersection_zones):
                return True
    elif intersection_zones:
        if any(z.colliderect(cc) for z in intersection_zones):
            return True
    pad = RECT_COLLIDE_PAD + CAR_NEARBY_PAD
    if spatial is not None and scratch is not None:
        peers = spatial.nearby(cc, pad, scratch)
    else:
        peers = cars_group
    for other in peers:
        oc = other._collision_shell
        if cc.colliderect(oc.inflate(RECT_COLLIDE_PAD, RECT_COLLIDE_PAD)):
            return True
        if (
            candidate.vertical == other.vertical
            and candidate.direction == other.direction
        ):
            if candidate.vertical:
                ahead = (other.rect.centery - candidate.rect.centery) * candidate.direction
                lane_gap = abs(other.rect.centerx - candidate.rect.centerx)
            else:
                ahead = (other.rect.centerx - candidate.rect.centerx) * candidate.direction
                lane_gap = abs(other.rect.centery - candidate.rect.centery)
            along_len = CAR_HEIGHT if candidate.vertical else CAR_WIDTH
            if lane_gap < CAR_FOLLOW_LANE_GAP and abs(ahead) < along_len + MIN_ALONG_GAP:
                return True
    return False


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
    for x, y, direction_sign, vertical in poses:
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
        if _car_blocks_spawn(
            candidate,
            cars_group,
            roads,
            intersection_zones,
            player_rect=player_rect,
            city_blocks=city_blocks,
            world_rect=world_rect,
            spatial=spatial,
            scratch=scratch,
        ):
            continue
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
    spawn_budget = 6

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
        if spawn_budget <= 0:
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
        if lag < MAX_SPAWN_DEFER_FRAMES and len(traffic_spawn_retry) < SPAWN_RETRY_SLOTS:
            traffic_spawn_retry.append(event)
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
cars = pygame.sprite.Group()
player = None
all_sprites = pygame.sprite.Group()
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
round_results = []
world_bounds = None
road_states = []
road_states_h: list = []
road_states_v: list = []
intersection_zones = []
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
title_font = pygame.font.SysFont(None, 48)
menu_font = pygame.font.SysFont(None, 32)
menu_small_font = pygame.font.SysFont(None, 22)


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
    global world_bounds, road_states, road_states_h, road_states_v, intersection_zones, wall_rects
    global frame_recorder, decision_logger
    global traffic_schedule, traffic_spawn_cursor, traffic_spawn_retry
    global traffic_respawn_pending, traffic_respawn_event_id
    global _ix_rects_cache, _ix_rects_cache_frame, traffic_map_seed, round_frame
    global session_base_seed

    current_round_index = round_index
    current_difficulty_profile = difficulty_profile
    base_preset_id = preset_id
    _apply_difficulty_globals(difficulty_profile)

    map_seed = _map_seed_for_round(session_base_seed, round_index)

    current_map = map_generator.generate_map(
        seed=map_seed,
        prior_session=None,
        difficulty=difficulty_profile,
    )
    ROUND_TIME_LIMIT = current_map.time_limit

    cars = pygame.sprite.Group()
    player = Pedestrian(current_map.start_pos)
    all_sprites = pygame.sprite.Group(player)
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
    intersection_zones = build_intersection_zones(current_map.roads)
    wall_rects = [
        pygame.Rect(world_bounds.left - 4000, world_bounds.top - 4000, 4000, world_bounds.height + 8000),
        pygame.Rect(world_bounds.right, world_bounds.top - 4000, 4000, world_bounds.height + 8000),
        pygame.Rect(world_bounds.left, world_bounds.top - 4000, world_bounds.width, 4000),
        pygame.Rect(world_bounds.left, world_bounds.bottom, world_bounds.width, 4000),
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

    round_active = True


def build_world_bounds(roads, start_pos, goal_rect):
    min_left = min([r.rect.left for r in roads] + [start_pos[0] - 80, goal_rect.left]) - 120
    max_right = max([r.rect.right for r in roads] + [start_pos[0] + 80, goal_rect.right]) + 120
    min_top = min([r.rect.top for r in roads] + [start_pos[1] - 80, goal_rect.top]) - 120
    max_bottom = max([r.rect.bottom for r in roads] + [start_pos[1] + 80, goal_rect.bottom]) + 120
    return pygame.Rect(min_left, min_top, max_right - min_left, max_bottom - min_top)


def build_road_states(roads):
    def add_state(collector, road, direction, crosswalk, sign_rect, phase_offset):
        collector.append(
            {
                "road_rect": road.rect,
                "approach_rect": road.rect.inflate(180, 180),
                "direction": direction,
                "crosswalk": crosswalk,
                "stop_axis": crosswalk.centerx if direction == "vertical" else crosswalk.centery,
                "sign_rect": sign_rect,
                "phase_offset": phase_offset,
                "light_state": "green",
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
            intersection_rect = v_road.rect.clip(h_road.rect)
            if intersection_rect.width <= 0 or intersection_rect.height <= 0:
                continue
            intersection_by_road[id(v_road)].append(intersection_rect)
            intersection_by_road[id(h_road)].append(intersection_rect)

            base_offset = ((intersection_rect.centerx + intersection_rect.centery) % 31) / 31.0 * cycle

            # Crossing across the horizontal road (left and right approaches).
            left_space = intersection_rect.left - v_road.rect.left
            right_space = v_road.rect.right - intersection_rect.right
            left_thickness = min(CROSSWALK_THICKNESS, max(0, left_space - INTERSECTION_GAP_MIN - 2))
            right_thickness = min(CROSSWALK_THICKNESS, max(0, right_space - INTERSECTION_GAP_MIN - 2))
            if left_thickness >= 4:
                left_x = intersection_rect.left - INTERSECTION_GAP_MIN - left_thickness
                left_crosswalk = pygame.Rect(left_x, v_road.rect.top, left_thickness, v_road.rect.height)
                add_state(
                    road_states,
                    v_road,
                    "vertical",
                    left_crosswalk,
                    pygame.Rect(left_crosswalk.left - 28, left_crosswalk.top - 26, 18, 18),
                    base_offset,
                )
            if right_thickness >= 4:
                right_x = intersection_rect.right + INTERSECTION_GAP_MIN
                right_crosswalk = pygame.Rect(right_x, v_road.rect.top, right_thickness, v_road.rect.height)
                add_state(
                    road_states,
                    v_road,
                    "vertical",
                    right_crosswalk,
                    pygame.Rect(right_crosswalk.right + 10, right_crosswalk.top - 26, 18, 18),
                    base_offset + 1.3,
                )

            # Crossing across the vertical road (top and bottom approaches).
            top_space = intersection_rect.top - h_road.rect.top
            bottom_space = h_road.rect.bottom - intersection_rect.bottom
            top_thickness = min(CROSSWALK_THICKNESS, max(0, top_space - INTERSECTION_GAP_MIN - 2))
            bottom_thickness = min(CROSSWALK_THICKNESS, max(0, bottom_space - INTERSECTION_GAP_MIN - 2))
            if top_thickness >= 4:
                top_y = intersection_rect.top - INTERSECTION_GAP_MIN - top_thickness
                top_crosswalk = pygame.Rect(h_road.rect.left, top_y, h_road.rect.width, top_thickness)
                add_state(
                    road_states,
                    h_road,
                    "horizontal",
                    top_crosswalk,
                    pygame.Rect(top_crosswalk.left - 26, top_crosswalk.top - 26, 18, 18),
                    base_offset + (_LIGHT_GREEN / 2.0),
                )
            if bottom_thickness >= 4:
                bottom_y = intersection_rect.bottom + INTERSECTION_GAP_MIN
                bottom_crosswalk = pygame.Rect(h_road.rect.left, bottom_y, h_road.rect.width, bottom_thickness)
                add_state(
                    road_states,
                    h_road,
                    "horizontal",
                    bottom_crosswalk,
                    pygame.Rect(bottom_crosswalk.left - 26, bottom_crosswalk.bottom + 10, 18, 18),
                    base_offset + (_LIGHT_GREEN / 2.0) + 1.3,
                )

    # Roads without intersections get one center crossing.
    for idx, road in enumerate(roads):
        if intersection_by_road[id(road)]:
            continue
        phase_offset = (idx * 3.7) % cycle
        if road.direction == "vertical":
            crosswalk = pygame.Rect(road.rect.centerx - CROSSWALK_THICKNESS // 2, road.rect.top, CROSSWALK_THICKNESS, road.rect.height)
            sign_rect = pygame.Rect(crosswalk.left - 28, crosswalk.top - 26, 18, 18)
        else:
            crosswalk = pygame.Rect(road.rect.left, road.rect.centery - CROSSWALK_THICKNESS // 2, road.rect.width, CROSSWALK_THICKNESS)
            sign_rect = pygame.Rect(crosswalk.left - 26, crosswalk.top - 26, 18, 18)
        add_state(road_states, road, road.direction, crosswalk, sign_rect, phase_offset)

    return road_states


def build_intersection_zones(roads):
    zones = []
    vertical_roads = [r for r in roads if r.direction == "vertical"]
    horizontal_roads = [r for r in roads if r.direction == "horizontal"]
    for v_road in vertical_roads:
        for h_road in horizontal_roads:
            zone = v_road.rect.clip(h_road.rect)
            if zone.width > 0 and zone.height > 0:
                zones.append(zone)
    return zones


def lane_center_for_road(road, direction, vertical):
    cx, cy = lane_center_xy(road, direction)
    if road.direction == "vertical":
        return cy
    return cx


def get_light_state(elapsed_seconds):
    cycle_length = _LIGHT_GREEN + _LIGHT_YELLOW + _LIGHT_RED
    t = elapsed_seconds % cycle_length
    if t < _LIGHT_GREEN:
        return "green"
    if t < _LIGHT_GREEN + _LIGHT_YELLOW:
        return "yellow"
    return "red"


def get_player_light_state(player_rect, states):
    body = sprites.player_body_hitbox(player_rect)
    for state in states:
        if state["crosswalk"].colliderect(body):
            return state["light_state"]
    return "none"


def get_pressed_keys(key_state):
    labels = []
    if key_state[pygame.K_LEFT] or key_state[pygame.K_a]:
        labels.append("left")
    if key_state[pygame.K_RIGHT] or key_state[pygame.K_d]:
        labels.append("right")
    if key_state[pygame.K_UP] or key_state[pygame.K_w]:
        labels.append("up")
    if key_state[pygame.K_DOWN] or key_state[pygame.K_s]:
        labels.append("down")
    return labels


def end_round(collided, timed_out=False) -> str:
    global crossings, collisions, round_active, risk_events, failure_reason, round_results
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
    frame_recorder.capture_end(duration, player.rect, list(cars.sprites()), road_states, game_time=duration)
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

def run_round_loop():
    global app_running, round_active
    global start_time, ROUND_TIME_LIMIT, crossings, collisions, risk_events, last_risk_time
    global player, current_map, road_states, road_states_h, road_states_v, world_bounds, intersection_zones
    global cars, all_sprites, decision_logger, frame_recorder, current_round_index
    global current_difficulty_profile, round_frame
    while round_active and app_running:
        clock.tick(60)
        keys = pygame.key.get_pressed()
        elapsed = time.time() - start_time
        time_left = max(0, ROUND_TIME_LIMIT - elapsed)

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                app_running = False
                round_active = False

        previous_pos = player.rect.topleft

        for state in road_states:
            state["light_state"] = get_light_state(elapsed + state["phase_offset"])
            state["player_waiting"] = False
            road_rect = state["road_rect"]
            crosswalk = state["crosswalk"]
            wait_zone = crosswalk.inflate(80, 80)
            if wait_zone.colliderect(player.rect) and not road_rect.colliderect(player.rect):
                state["player_waiting"] = True
        update_light_timers(road_states, elapsed)

        # Crossing logic
        for road_index, road in enumerate(current_map.roads):
            approach_zone = road.rect.inflate(120, 120)
            if not road.crossed and approach_zone.colliderect(player.rect):
                decision_logger.note_road_approach(road_index)

            if road.rect.colliderect(player.rect) and not road.crossed:
                if road.direction == "vertical":
                    # Player must move vertically across
                    if player.rect.top < road.rect.top:
                        crossings += 1
                        road.crossed = True
                        decision_logger.note_road_crossed(
                            road_index, get_player_light_state(player.rect, road_states)
                        )
                elif road.direction == "horizontal":
                    # Player must move horizontally across
                    if player.rect.left > road.rect.left:
                        crossings += 1
                        road.crossed = True
                        decision_logger.note_road_crossed(
                            road_index, get_player_light_state(player.rect, road_states)
                        )
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

        # Update
        player.update(keys)
        if not world_bounds.contains(player.rect):
            player.rect.topleft = previous_pos

        player_body = sprites.player_body_hitbox(player.rect)
        player_on_crosswalk = any(
            state["crosswalk"].colliderect(player_body) for state in road_states
        )
        player_on_road = any(road.rect.colliderect(player_body) for road in current_map.roads)
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

        car_list = cars.sprites()
        _frame_car_spatial.rebuild(car_list)
        lane_buckets = _build_lane_buckets(car_list)
        move_scratch = _frame_nearby_scratch
        lane_scratch = _frame_lane_scratch
        for car in car_list:
            if not car.alive():
                continue
            _lane_peers_for(car, lane_buckets, lane_scratch)
            move_peers = _frame_car_spatial.nearby(
                car._collision_shell, IX_QUERY_PAD, move_scratch
            )
            car.update(
                road_states_h if car.vertical else road_states_v,
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

        _frame_car_spatial.rebuild(car_list)
        near_player_cars = _cars_near_player(
            player_body, _frame_car_spatial, _frame_player_car_scratch
        )
        camera_offset = (player.rect.centerx - WIDTH // 2, player.rect.centery - HEIGHT // 2)
        view_rect = _view_rect_for_camera(camera_offset)
        record_cars = _cars_in_view(car_list, view_rect)

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
            if car._collision_shell.inflate(170, 170).colliderect(player_body)
            and car.current_speed > car.base_speed * 0.65
        ]
        approaching_cars = [
            car for car in near_player_cars if is_car_approaching_player(car, player.rect)
        ]

        if player_on_road and not player_on_crosswalk and nearby_fast_cars:
            record_risk("fast_traffic_on_road")
        if player_on_crosswalk and approaching_cars:
            crosswalk_red = player_on_car_red

            # Only count as risk if it's NOT a red light for cars,
            # or if cars are still moving dangerously despite red.
            dangerous_cars = [
                car for car in approaching_cars
                if car.current_speed > car.base_speed * 0.25
            ]

            if not crosswalk_red or dangerous_cars:
                record_risk(
                    "crosswalk_vehicle_conflict",
                    on_crosswalk=True,
                    light=get_player_light_state(player.rect, road_states),
                )
            if any(
                car._collision_shell.inflate(TOO_CLOSE_DISTANCE, TOO_CLOSE_DISTANCE).colliderect(
                    player_body
                )
                for car in near_player_cars
            ):
                record_risk("vehicle_too_close", cooldown=0.7)
            if any(
                car._collision_shell.inflate(NEAR_MISS_DISTANCE, NEAR_MISS_DISTANCE).colliderect(
                    player_body
                )
                and car.current_speed > car.base_speed * 0.75
                for car in near_player_cars
            ):
                record_risk("near_miss")

        decision_logger.update(
            player_body.center,
            get_pressed_keys(keys),
            player_on_crosswalk,
            player_on_road,
            get_player_light_state(player.rect, road_states),
            False,
        )

        if not frame_recorder.frames:
            frame_recorder.capture_start(
                elapsed, player.rect, record_cars, road_states, game_time=elapsed
            )
        else:
            frame_recorder.capture(
                elapsed, player.rect, record_cars, road_states, game_time=elapsed
            )

        # Collision check (tight body vs car shell)
        if player_hits_any_car(
            player, cars, spatial=_frame_car_spatial, scratch=_frame_player_car_scratch
        ):
            end_round(True, timed_out=False)

        if player.rect.colliderect(current_map.goal_rect):
            end_round(False, timed_out=False)

        if time_left <= 0 and round_active:
            end_round(False, timed_out=True)

        # Draw
        city_blocks = getattr(current_map, "city_blocks", None)
        decorations = getattr(current_map, "decorations", None)
        current_map.draw(
            screen,
            camera_offset,
            player,
            city_blocks=city_blocks,
            world_bounds=world_bounds,
            decorations=decorations,
        )
        for state in road_states:
            shifted_crosswalk = state["crosswalk"].move(
                -camera_offset[0], -camera_offset[1]
            )
            map_visuals.draw_crosswalk(
                screen, state["crosswalk"], state["direction"], camera_offset
            )

            shifted_sign = state["sign_rect"].move(-camera_offset[0], -camera_offset[1])
            sign_color = (35, 90, 200) if state["direction"] == "vertical" else (200, 120, 25)
            sign_label = "V" if state["direction"] == "vertical" else "H"
            pygame.draw.rect(screen, sign_color, shifted_sign, border_radius=3)
            pygame.draw.rect(screen, (25, 25, 25), shifted_sign, width=1, border_radius=3)
            sign_text = sign_font.render(sign_label, True, (255, 255, 255))
            sign_text_rect = sign_text.get_rect(center=shifted_sign.center)
            screen.blit(sign_text, sign_text_rect)
            if state["direction"] == "vertical":
                housing = pygame.Rect(shifted_crosswalk.centerx - 11, shifted_crosswalk.top - 68, 22, 56)
            else:
                housing = pygame.Rect(shifted_crosswalk.left - 68, shifted_crosswalk.centery - 11, 56, 22)

            pygame.draw.rect(screen, (25, 25, 25), housing, border_radius=5)
            pygame.draw.rect(screen, (70, 70, 70), housing, width=2, border_radius=5)

            if state["direction"] == "vertical":
                bulb_positions = [
                    (housing.centerx, housing.top + 10),
                    (housing.centerx, housing.top + 28),
                    (housing.centerx, housing.top + 46),
                ]
            else:
                bulb_positions = [
                    (housing.left + 10, housing.centery),
                    (housing.left + 28, housing.centery),
                    (housing.left + 46, housing.centery),
                ]

            red_on = state["light_state"] == "red"
            yellow_on = state["light_state"] == "yellow"
            green_on = state["light_state"] == "green"
            bulb_colors = [
                (220, 30, 30) if red_on else (80, 20, 20),
                (235, 185, 40) if yellow_on else (85, 70, 20),
                (40, 200, 40) if green_on else (20, 80, 20),
            ]
            for pos, color in zip(bulb_positions, bulb_colors):
                pygame.draw.circle(screen, color, pos, 6)

            remaining = max(0.0, state.get("seconds_to_change", 0))
            next_name = state.get("next_light", "green")
            timer_label = f"{remaining:.1f}s"
            timer_color = (30, 30, 30)
            if next_name == "red":
                timer_color = (160, 40, 40)
            elif next_name == "yellow":
                timer_color = (170, 130, 30)
            elif next_name == "green":
                timer_color = (35, 120, 55)
            timer_surf = sign_font.render(timer_label, True, timer_color)
            if state["direction"] == "vertical":
                timer_rect = timer_surf.get_rect(midtop=(housing.centerx, housing.bottom + 4))
                bar_rect = pygame.Rect(housing.left, housing.bottom + 2, housing.width, 4)
            else:
                timer_rect = timer_surf.get_rect(midleft=(housing.right + 6, housing.centery))
                bar_rect = pygame.Rect(housing.right + 2, housing.top, 4, housing.height)
            pygame.draw.rect(screen, (200, 200, 200), bar_rect, border_radius=2)
            fill_frac = min(1.0, remaining / max(_LIGHT_GREEN, 0.1))
            if state["direction"] == "vertical":
                fill = bar_rect.copy()
                fill.width = max(1, int(bar_rect.width * fill_frac))
            else:
                fill = bar_rect.copy()
                fill.height = max(1, int(bar_rect.height * fill_frac))
            fill_color = (80, 200, 90) if next_name == "green" else (230, 190, 60) if next_name == "yellow" else (220, 70, 70)
            pygame.draw.rect(screen, fill_color, fill, border_radius=2)
            screen.blit(timer_surf, timer_rect)

        for wall in wall_rects:
            shifted_wall = wall.move(-camera_offset[0], -camera_offset[1])
            pygame.draw.rect(screen, (40, 40, 40), shifted_wall)

        cam_x, cam_y = camera_offset
        for sprite in all_sprites:
            if not view_rect.colliderect(sprite.rect):
                continue
            screen.blit(sprite.image, sprite.rect.move(-cam_x, -cam_y))

        for car in record_cars:
            if car.turn_signal:
                blink = int(elapsed * 10) % 2 == 0
                sig_v, sig_d = car._effective_travel()
                sig_angle = (
                    car._turn_display_angle
                    if car._turn_phase in ("turning", "settling")
                    else None
                )
                sprites.draw_turn_signal(
                    screen,
                    car.rect,
                    sig_v,
                    sig_d,
                    car.turn_signal,
                    blink,
                    (cam_x, cam_y),
                    sig_angle,
                )
            if car.is_honking(elapsed):
                sprites.draw_honk_bubble(screen, car.rect, (cam_x, cam_y), honk_font)

        esc = getattr(current_difficulty_profile, "round_escalation", 0.0) if current_difficulty_profile else 0.0
        hud_lines = [
            f"Round {current_round_index}/{session_num_rounds} · intensity {esc * 100:.0f}%",
            f"Time left: {time_left:05.1f}s",
            f"Crossings: {crossings}/{len(current_map.roads)} · traffic {len(cars)}",
            f"Risky moves: {risk_events}",
        ]
        for idx, line in enumerate(hud_lines):
            text_surface = font.render(line, True, HUD_TEXT_COLOR)
            screen.blit(text_surface, (10, 10 + idx * 24))

        pygame.display.flip()

def main():
    global app_running, base_preset_id, round_results, session_num_rounds, session_base_seed

    config = pre_game.run_pre_game_menu(screen, clock, title_font, menu_font, menu_small_font)
    if config is None:
        pygame.quit()
        return

    session_num_rounds = config.num_rounds
    session_base_seed = (
        config.seed if config.seed is not None else random.randint(0, 2**31 - 1)
    )
    base_preset_id = config.preset
    base_profile = DifficultyProfile.for_menu_preset(config.preset)
    round_results = []
    outcomes = []
    print(f"Session seed: {session_base_seed} ({session_num_rounds} round(s))")

    for round_index in range(1, session_num_rounds + 1):
        profile = DifficultyProfile.for_round(
            base_profile, round_index - 1, session_num_rounds
        )
        start_round(round_index, profile, config.preset)
        if not pre_game.run_round_intro(
            screen, clock, title_font, menu_font, round_index, session_num_rounds, profile
        ):
            break
        run_round_loop()
        if not app_running:
            break
        outcome = round_results[-1]["outcome"] if round_results else "timeout"
        outcomes.append(outcome)
        if round_index < session_num_rounds:
            if not pre_game.run_between_rounds(
                screen, clock, title_font, menu_font, round_index, session_num_rounds, outcome
            ):
                break

    if round_results:
        dashboard = save_session_log()
        print("Session complete:", {"rounds": outcomes, "dashboard": dashboard})
        pre_game.run_session_complete(
            screen,
            clock,
            title_font,
            menu_font,
            outcomes,
            session_num_rounds,
            session_seed=session_base_seed,
        )

    pygame.quit()


if __name__ == "__main__":
    main()
