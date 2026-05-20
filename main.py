import math
import pygame
import random
import json
import time
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
)
from map_generation.lane_geometry import lane_center_xy
from map_generation.traffic_schedule import (
    MIN_ALONG_GAP,
    RECT_COLLIDE_PAD,
    TrafficSpawn,
    build_intersection_rects,
    generate_traffic_schedule,
    lane_spawn_allowed,
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
INTERSECTION_STUCK_CREEP_FRAMES = 75
CAR_SPAWN_RAMP_FRAMES = 90
ROAD_EXIT_PAD = 28
PLAYER_SPAWN_PAD = 280
SPAWN_MIN_ROAD_FRAC = 0.42
SPAWN_MAX_BLOCK_FRAC = 0.06
TURN_CHANCE = 0.38
TURN_HUB_DIST = 28
TURN_PIVOT_SPEED_FRAC = 0.35

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


def player_hits_any_car(player, cars_group):
    pb = sprites.player_body_hitbox(player.rect)
    for car in cars_group:
        if car._collision_shell.colliderect(pb):
            return True
    return False


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
    ):
        super().__init__()
        self.direction = 1 if speed >= 0 else -1
        self.vertical = vertical
        self.spawn_id = spawn_id
        self.road_index = road_index
        self._entered_road = False
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
        self._collision_shell = sprites.car_collision_rect(self.rect, self.vertical)
        self.current_speed = 0.0
        self.speed = 0.0

    def _sync_collision_shell(self):
        self._collision_shell = sprites.car_collision_rect(self.rect, self.vertical)

    def _snap_center_to_left_lane(self, roads, max_nudge: int = 4):
        if self.road_index is None or self.road_index >= len(roads):
            return
        road = roads[self.road_index]
        tcx, tcy = lane_center_xy(road, self.direction)
        if road.direction == "vertical":
            dy = max(-max_nudge, min(max_nudge, tcy - self.rect.centery))
            self.rect.centery += dy
        else:
            dx = max(-max_nudge, min(max_nudge, tcx - self.rect.centerx))
            self.rect.centerx += dx

    def _shell_hits_any_car(self, rect, vertical, all_cars) -> bool:
        shell = sprites.car_collision_rect(rect, vertical)
        for other in all_cars:
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
        if self.vertical:
            ahead = (other.rect.centery - self.rect.centery) * self.direction
            lane_gap = abs(other.rect.centerx - self.rect.centerx)
        else:
            ahead = (other.rect.centerx - self.rect.centerx) * self.direction
            lane_gap = abs(other.rect.centery - self.rect.centery)
        return ahead, lane_gap

    def _same_lane(self, other, max_lane_gap=CAR_FOLLOW_LANE_GAP):
        _, lane_gap = self._distance_to_other(other)
        return lane_gap < max_lane_gap

    def _in_crosswalk_lane(self, state):
        if self.vertical:
            return abs(self.rect.centerx - state["crosswalk"].centerx) < 50
        return abs(self.rect.centery - state["crosswalk"].centery) < 50

    def _distance_to_intersection_entry(self, zone):
        if self.vertical:
            if self.direction > 0:
                return zone.top - self.rect.bottom
            return self.rect.top - zone.bottom
        if self.direction > 0:
            return zone.left - self.rect.right
        return self.rect.left - zone.right

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

    def _cap_next_rect_same_lane(self, next_rect, all_cars):
        """
        Never allow next_rect to overlap a same-direction car ahead in-lane.
        Uses shell hitboxes (matches drawn car body).
        """
        g = CAR_FOLLOW_SEP
        for other in all_cars:
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

    def _resolve_same_lane_penetration(self, all_cars):
        """If shells overlap a car ahead, push back (fixes frame-order / spawn glitches)."""
        g = CAR_FOLLOW_SEP
        for other in all_cars:
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

    def _matches_road_travel(self, road) -> bool:
        return (road.direction == "vertical" and not self.vertical) or (
            road.direction == "horizontal" and self.vertical
        )

    def _on_traffic_network(self, roads, intersection_zones) -> bool:
        """On any lane-aligned segment or in an intersection (not only the spawn segment)."""
        shell = self._collision_shell
        for road in roads:
            if not self._matches_road_travel(road):
                continue
            if road.rect.inflate(28, 28).colliderect(shell):
                return True
        if intersection_zones:
            if any(shell.colliderect(zone) for zone in intersection_zones):
                return True
        return False

    def _refresh_car_sprite(self):
        center = self.rect.center
        self.image = sprites.make_car_surface(
            vertical=self.vertical,
            direction=self.direction,
            archetype_index=self.archetype_index,
        )
        self.rect = self.image.get_rect(center=center)

    def _intersection_zone_at(self, intersection_zones):
        for zone in intersection_zones:
            if zone.collidepoint(self.rect.center):
                return zone
        return None

    def _plan_turn_at_intersection(self, roads, intersection_zones):
        if not intersection_zones or self._turn_phase == "to_hub":
            return
        zone = self._intersection_zone_at(intersection_zones)
        if zone is None:
            if self._turn_phase != "to_hub":
                self.turn_signal = 0
                self._turn_exit = None
            self._turn_zone_key = None
            return
        key = (zone.x, zone.y, zone.w, zone.h)
        if key == self._turn_zone_key:
            return
        self._turn_zone_key = key
        rng = random.Random((traffic_map_seed + self.spawn_id * 31) & 0xFFFFFFFF)
        turn_side = pick_turn_side(rng, TURN_CHANCE)
        if turn_side == 0:
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
            self.turn_signal = 0
            self._turn_exit = None
            return
        self.turn_signal = turn_side
        self._turn_exit = exit_plan

    def _arm_turn_through_hub(self, intersection_zones):
        """Keep driving straight on entry road; pivot when hub is reached."""
        if self.turn_signal == 0 or not self._turn_exit or not intersection_zones:
            return
        zone = self._intersection_zone_at(intersection_zones)
        if zone is None:
            return
        if self._turn_phase == "none":
            self._turn_phase = "to_hub"
            self._turn_hub = (zone.centerx, zone.centery)

    def _pivot_turn_at_hub(
        self,
        roads,
        intersection_zones,
        all_cars,
        player_body_rect,
        ped_legal_crossing,
    ) -> bool:
        """Snap to exit lane orientation at intersection center (90° turn, not diagonal slide)."""
        if self._turn_phase != "to_hub" or not self._turn_exit or not self._turn_hub:
            return False
        zone = self._intersection_zone_at(intersection_zones)
        if zone is None:
            return False
        hx, hy = self._turn_hub
        dist = math.hypot(self.rect.centerx - hx, self.rect.centery - hy)
        fx, fy = travel_vector(self.vertical, self.direction)
        past_hub = (self.rect.centerx - hx) * fx + (self.rect.centery - hy) * fy > 14
        if dist > TURN_HUB_DIST and not past_hub:
            return False

        idx, d, vertical = self._turn_exit
        px, py = pivot_center_at_intersection(roads, zone, idx, d, vertical)
        old_v, old_d = self.vertical, self.direction
        new_dir = 1 if d >= 0 else -1
        if vertical:
            pw, ph = CAR_HEIGHT, CAR_WIDTH
        else:
            pw, ph = CAR_WIDTH, CAR_HEIGHT
        probe = pygame.Rect(0, 0, pw, ph)
        probe.center = (px, py)
        probe_shell = sprites.car_collision_rect(probe, vertical)
        clear = True
        for other in all_cars:
            if other is self:
                continue
            if probe_shell.colliderect(other._collision_shell):
                clear = False
                break
        if clear and not ped_legal_crossing and probe_shell.colliderect(player_body_rect):
            clear = False
        if not clear:
            self.current_speed = 0.0
            return False

        self.road_index = idx
        self.vertical = vertical
        self.direction = new_dir
        self.rect.center = (px, py)
        self._refresh_car_sprite()
        self.rect.center = (px, py)
        self._snap_center_to_left_lane(roads)
        self.turn_signal = 0
        self._turn_phase = "none"
        self._turn_exit = None
        self._turn_hub = None
        self.current_speed = min(self.current_speed, self.base_speed * TURN_PIVOT_SPEED_FRAC)
        self._sync_collision_shell()
        return True

    def _spawn_ramp_cap(self) -> float:
        if self._spawn_age >= CAR_SPAWN_RAMP_FRAMES:
            return self.base_speed
        t = self._spawn_age / CAR_SPAWN_RAMP_FRAMES
        ease = t * t * (3.0 - 2.0 * t)
        return self.base_speed * ease

    def _should_despawn(self, roads, intersection_zones=None) -> bool:
        if not roads:
            return False
        if self._turn_phase == "to_hub" or self.turn_signal != 0:
            self._entered_road = True
            return False
        shell = self._collision_shell
        if intersection_zones and any(
            shell.colliderect(z.inflate(40, 40)) for z in intersection_zones
        ):
            self._entered_road = True
            return False
        if self._on_traffic_network(roads, intersection_zones):
            self._entered_road = True
            return False
        return self._entered_road

    def _in_or_entering_intersection(self, next_rect, intersection_zones) -> bool:
        if not intersection_zones:
            return False
        return any(
            z.colliderect(self.rect) or z.colliderect(next_rect) for z in intersection_zones
        )

    def _entry_blocks_moving_cross_traffic(
        self, next_rect, all_cars, intersection_zones
    ) -> bool:
        """Do not enter the box if we'd cut in front of moving perpendicular traffic."""
        my_n = sprites.car_collision_rect(next_rect, self.vertical)
        for zone in intersection_zones:
            if not (next_rect.colliderect(zone) and not self.rect.colliderect(zone)):
                continue
            for other in all_cars:
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
        self, next_rect, all_cars, intersection_zones, allow_perp_overlap=False
    ):
        if not intersection_zones:
            return False
        if not self._in_or_entering_intersection(next_rect, intersection_zones):
            return False
        if not allow_perp_overlap and self._entry_blocks_moving_cross_traffic(
            next_rect, all_cars, intersection_zones
        ):
            return True
        if self._shell_hits_any_car(next_rect, self.vertical, all_cars):
            if not allow_perp_overlap:
                return True
            my_n = sprites.car_collision_rect(next_rect, self.vertical)
            for other in all_cars:
                if other is self:
                    continue
                if other.vertical != self.vertical or other.direction != self.direction:
                    continue
                if not self._same_lane(other, CAR_BLOCK_LANE_GAP):
                    continue
                if my_n.colliderect(other._collision_shell):
                    gap, _ = self._distance_to_other(other)
                    if gap <= 0 or gap < 20:
                        return True
        return False

    def update(
        self,
        all_cars,
        road_states,
        world_rect,
        intersection_zones,
        player_body_rect,
        roads,
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
        self._plan_turn_at_intersection(roads, intersection_zones)
        self._arm_turn_through_hub(intersection_zones)
        if self._turn_phase == "to_hub":
            desired_speed = min(desired_speed, self.base_speed * TURN_PIVOT_SPEED_FRAC)

        self._resolve_same_lane_penetration(all_cars)
        self._sync_collision_shell()

        for state in road_states:
            if state["direction"] != ("horizontal" if self.vertical else "vertical"):
                continue
            if not self.rect.colliderect(state["road_rect"].inflate(180, 180)):
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
                if state["direction"] != ("horizontal" if self.vertical else "vertical"):
                    continue
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

        for other in all_cars:
            if other == self or other.vertical != self.vertical or other.direction != self.direction:
                continue
            if not self._same_lane(other):
                continue
            ahead, _lane_gap = self._distance_to_other(other)
            if ahead <= 0 or ahead > 150:
                continue
            if ahead < 20:
                follow_cap = 0.0 if other.current_speed < 0.4 else other.current_speed * 0.65
                desired_speed = min(desired_speed, follow_cap)
            else:
                follow_cap = other.current_speed * max(0.45, (ahead - 16) / 80)
                desired_speed = min(desired_speed, max(follow_cap, CAR_CREEP_SPEED))

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

        if blocked_by_line:
            self.current_speed = 0
            self.speed = 0
        else:
            next_rect = self.rect.copy()
            if self.vertical:
                next_rect.y += signed_speed
            else:
                next_rect.x += signed_speed

            next_rect = self._cap_next_rect_same_lane(next_rect, all_cars)

            blocked = False
            creep_cap = None
            my_n = sprites.car_collision_rect(next_rect, self.vertical)
            if signed_speed != 0:
                blocked = self._intersection_move_blocked(
                    next_rect,
                    all_cars,
                    intersection_zones,
                    allow_perp_overlap=intersection_creep,
                )
                if not blocked and self._shell_hits_any_car(
                    next_rect, self.vertical, all_cars
                ):
                    blocked = True
                if not blocked:
                    for other in all_cars:
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
        self._pivot_turn_at_hub(
            roads,
            intersection_zones,
            all_cars,
            player_body_rect,
            ped_legal_crossing,
        )
        if self._should_despawn(roads, intersection_zones):
            self.kill()
        elif not world_rect.inflate(320, 320).colliderect(self.rect):
            self.kill()

        self._sync_collision_shell()
        if self.road_index is not None and self._turn_phase != "to_hub":
            self._snap_center_to_left_lane(roads)

        if self.current_speed < 0.25:
            self._stopped_frames += 1
        else:
            self._stopped_frames = 0
        if (
            self._stopped_frames >= STUCK_BEHIND_FRAMES
            and not inside_intersection
        ):
            for other in all_cars:
                if other is self:
                    continue
                if other.vertical != self.vertical or other.direction != self.direction:
                    continue
                if not self._same_lane(other, CAR_FOLLOW_LANE_GAP):
                    continue
                ahead, _ = self._distance_to_other(other)
                if 0 < ahead < 120:
                    self.kill()
                    break

        if self.alive():
            self.evaluate_honk(
                player_body_rect,
                player_on_crosswalk,
                honk_allowed,
                game_time,
            )

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
) -> bool:
    if _blocks_player_spawn(candidate, player_rect):
        return True
    if not _car_spawn_pose_valid(candidate, roads, city_blocks):
        return True
    cc = candidate._collision_shell
    if intersection_zones:
        if any(z.colliderect(cc) for z in intersection_zones):
            return True
    for other in cars_group:
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
):
    road = roads[event.road_index]
    if not lane_spawn_allowed(cars_group, road, event.direction):
        return
    ix_rects = build_intersection_rects(roads)
    for x, y, direction_sign, vertical in spawn_poses_for_event(road, event, ix_rects):
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
        ):
            continue
        cars_group.add(candidate)
        all_sprites_group.add(candidate)
        return


def _process_traffic_spawns_through_frame(
    target_frame: int,
    roads,
    cars,
    all_sprites,
    intersection_zones=None,
    player_rect=None,
    city_blocks=None,
):
    global traffic_spawn_cursor
    while (
        traffic_spawn_cursor < len(traffic_schedule)
        and traffic_schedule[traffic_spawn_cursor].frame <= target_frame
    ):
        event = traffic_schedule[traffic_spawn_cursor]
        _spawn_car_from_event(
            event,
            roads,
            cars,
            all_sprites,
            intersection_zones,
            player_rect,
            city_blocks,
        )
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
intersection_zones = []
wall_rects = []
frame_recorder = None
decision_logger = None
traffic_schedule: list[TrafficSpawn] = []
traffic_spawn_cursor = 0
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
    global world_bounds, road_states, intersection_zones, wall_rects
    global frame_recorder, decision_logger
    global traffic_schedule, traffic_spawn_cursor, traffic_map_seed, round_frame
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
    global player, current_map, road_states, world_bounds, intersection_zones
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

        cars.update(
            cars.sprites(),
            road_states,
            world_bounds,
            intersection_zones,
            player_body,
            current_map.roads,
            player_on_road,
            player_on_crosswalk,
            player_feet_road,
            ped_legal_crossing,
            respect_player,
            honk_allowed,
            player_body_block,
            elapsed,
        )

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
            for car in cars
            if car._collision_shell.inflate(170, 170).colliderect(player_body)
            and car.current_speed > car.base_speed * 0.65
        ]
        approaching_cars = [car for car in cars if is_car_approaching_player(car, player.rect)]

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
                for car in cars
            ):
                record_risk("vehicle_too_close", cooldown=0.7)
            if any(
                car._collision_shell.inflate(NEAR_MISS_DISTANCE, NEAR_MISS_DISTANCE).colliderect(
                    player_body
                )
                and car.current_speed > car.base_speed * 0.75
                for car in cars
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
            frame_recorder.capture_start(elapsed, player.rect, list(cars.sprites()), road_states, game_time=elapsed)
        else:
            frame_recorder.capture(elapsed, player.rect, list(cars.sprites()), road_states, game_time=elapsed)

        # Collision check (tight body vs car shell)
        if player_hits_any_car(player, cars):
            end_round(True, timed_out=False)

        if player.rect.colliderect(current_map.goal_rect):
            end_round(False, timed_out=False)

        if time_left <= 0 and round_active:
            end_round(False, timed_out=True)

        camera_offset = (player.rect.centerx - WIDTH//2, player.rect.centery - HEIGHT//2)
        
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

        for sprite in all_sprites:
            shifted_rect = sprite.rect.move(-camera_offset[0], -camera_offset[1])
            screen.blit(sprite.image, shifted_rect)

        for car in cars:
            if car.turn_signal:
                blink = int(elapsed * 10) % 2 == 0
                sprites.draw_turn_signal(
                    screen,
                    car.rect,
                    car.vertical,
                    car.direction,
                    car.turn_signal,
                    blink,
                    camera_offset,
                )
            if car.is_honking(elapsed):
                sprites.draw_honk_bubble(screen, car.rect, camera_offset, honk_font)

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
