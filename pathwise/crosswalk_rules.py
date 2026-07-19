"""Pedestrian crosswalk interaction and collision rules."""

from __future__ import annotations

from pathwise import sprites
from pathwise.geom import Rect, clip_rect, collide
from pathwise.sim_constants import PLAYER_CAR_QUERY_PAD

# Pedestrian risk: feet must be overwhelmingly on pavement (not a sidewalk graze).
FEET_RISK_ON_ROAD_FRAC = 0.85
# Honks / car reactions use the same bar so grazes do not become risk events.
FEET_HONK_ON_ROAD_FRAC = FEET_RISK_ON_ROAD_FRAC

def player_dominant_crosswalk_state(player_body_rect, road_states):
    best_area = 0
    best_state = None
    for state in road_states:
        inter = clip_rect(player_body_rect, state["crosswalk"])
        area = inter.width * inter.height
        if area > best_area:
            best_area = area
            best_state = state
    return best_state


def player_crossing_cars_have_red(player_body_rect, road_states) -> bool:
    """True when the crosswalk the player is mainly on shows red for car traffic."""
    state = player_dominant_crosswalk_state(player_body_rect, road_states)
    if state is not None:
        return state["light_state"] == "red"
    return player_on_car_red_crosswalk_body(player_body_rect, road_states)


def player_dominant_road_light_state(player_body_rect, road_states) -> str | None:
    """Car signal color for the road pavement the body overlaps most (None if off-road)."""
    best_area = 0
    best_light = None
    for state in road_states:
        inter = clip_rect(player_body_rect, state["road_rect"])
        area = inter.width * inter.height
        if area > best_area:
            best_area = area
            best_light = state["light_state"]
    return best_light if best_area > 0 else None


def player_jaywalking_off_crosswalk(player_body_rect, road_states, *, on_crosswalk: bool) -> bool:
    """On road pavement away from crosswalk while cars have red (wrong place, cars stopped)."""
    if on_crosswalk:
        return False
    return player_dominant_road_light_state(player_body_rect, road_states) == "red"


def update_legal_crossing_commit(
    was_active: bool,
    on_crosswalk: bool,
    cars_have_red: bool,
    *,
    on_road: bool = False,
    unsignalized: bool = False,
) -> bool:
    """Latch on car-red (or any crosswalk when unsignalized); hold until sidewalk."""
    if on_crosswalk and (cars_have_red or unsignalized):
        return True
    if was_active and on_road:
        return True
    if not on_crosswalk and not on_road:
        return False
    return was_active


def crosswalk_crossing_is_legal(on_car_red: bool, legal_commit_active: bool) -> bool:
    return on_car_red or legal_commit_active


def car_is_traffic_threat(car, *, min_speed_frac: float = 0.25) -> bool:
    return car.current_speed > car.base_speed * min_speed_frac


def player_on_car_red_crosswalk_body(player_body_rect, road_states):
    for state in road_states:
        if collide(state["crosswalk"], player_body_rect) and state["light_state"] == "red":
            return True
    return False


def player_on_car_red_crosswalk(player_rect, road_states):
    return player_on_car_red_crosswalk_body(
        sprites.player_body_hitbox(player_rect), road_states
    )


def player_conflicting_car_vertical(player_body_rect, road_states, roads) -> bool | None:
    """Which car.vertical value can conflict with the player (None if unknown).

    Horizontal roads carry vertically-moving cars (vertical=True).
    Vertical roads carry horizontally-moving cars (vertical=False).
    """
    best_area = 0
    dominant_direction = None
    for state in road_states:
        inter = clip_rect(player_body_rect, state["crosswalk"])
        area = inter.width * inter.height
        if area > best_area:
            best_area = area
            dominant_direction = state["direction"]
    if dominant_direction is not None:
        return dominant_direction == "horizontal"

    for road in roads:
        if collide(road.rect, player_body_rect):
            return road.direction == "horizontal"
    return None


def car_shares_crossing_plane(car, conflict_car_vertical: bool | None) -> bool:
    if conflict_car_vertical is None:
        return True
    return car.vertical == conflict_car_vertical


def cars_on_crossing_plane(cars, conflict_car_vertical: bool | None) -> list:
    if conflict_car_vertical is None:
        return list(cars)
    return [car for car in cars if car.vertical == conflict_car_vertical]


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

def cars_should_respect_player(player_on_road, player_on_crosswalk, on_car_red: bool):
    """Yield / stop for player only when they occupy the road or cross legally on red-for-cars."""
    if player_on_crosswalk:
        return on_car_red
    return player_on_road


def player_feet_road_overlap_frac(player_rect, roads) -> float:
    """Fraction of the feet hitbox overlapping road pavement (0..1)."""
    feet = Rect(
        int(player_rect.x + player_rect.width * 0.18),
        int(player_rect.centery - player_rect.height * 0.05),
        int(player_rect.width * 0.64),
        int(player_rect.height * 0.42),
    )
    feet_area = feet.width * feet.height
    if feet_area <= 0:
        return 0.0
    overlap = 0
    for road in roads:
        inter = clip_rect(feet, road.rect)
        overlap += inter.width * inter.height
    return min(1.0, overlap / feet_area)


def player_feet_on_road(
    player_rect,
    roads,
    *,
    min_overlap_frac: float = FEET_HONK_ON_ROAD_FRAC,
):
    """Feet overlap pavement by at least min_overlap_frac (default: full road occupancy)."""
    return player_feet_road_overlap_frac(player_rect, roads) >= min_overlap_frac


def player_feet_fully_on_road(player_rect, roads) -> bool:
    """True when feet are fully on road pavement: used for pedestrian risk events."""
    return player_feet_on_road(player_rect, roads, min_overlap_frac=FEET_RISK_ON_ROAD_FRAC)


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
def road_midline_crossed(
    prev_center: tuple[int, int],
    curr_center: tuple[int, int],
    road,
) -> bool:
    """True when the player centroid crosses the road midline between frames.

    Includes frames that land exactly on the midline so 1px integer walks count.
    """
    prev_cx, prev_cy = prev_center
    curr_cx, curr_cy = curr_center

    def _crossed(prev_v: float, curr_v: float, mid: float) -> bool:
        if prev_v == curr_v:
            return False
        lo, hi = (prev_v, curr_v) if prev_v < curr_v else (curr_v, prev_v)
        return lo <= mid <= hi

    if road.direction == "vertical":
        return _crossed(prev_cy, curr_cy, road.rect.centery)
    return _crossed(prev_cx, curr_cx, road.rect.centerx)
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
