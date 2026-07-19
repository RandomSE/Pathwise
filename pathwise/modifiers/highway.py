"""Highway modifier: one wide multi-lane road, no lights or painted crossings."""

from __future__ import annotations

from map_generation.difficulty import DifficultyProfile
from pathwise.geom import Rect
from pathwise.map import BASE_SIZE, VERTICAL, MapBase, Road, make_rectangle
from pathwise.modifiers.registry import ModifierContext

# Crossing distance grows with difficulty (more lanes of asphalt).
_LANE_PX = 55
# Total painted lanes (both directions). Easy used to feel like 2 travel tracks.
_LANES_BY_PRESET = {"easy": 8, "normal": 12, "hard": 16}
# Harder presets get more clock time for denser, wider highways.
_TIME_LIMIT_BY_PRESET = {"easy": 60, "normal": 85, "hard": 110}
# Base weights; schedule also applies traffic_density_mult (~5x vs prior highway).
_TRAFFIC_WEIGHT_BY_PRESET = {"easy": 11.0, "normal": 15.0, "hard": 20.0}
_TRAFFIC_DENSITY_MULT = 8.0
_MAX_LANE_ACTIVE_BY_PRESET = {"easy": 48, "normal": 56, "hard": 64}
_EDGE_QUEUE_BY_PRESET = {"easy": 6, "normal": 8, "hard": 10}
_OPENING_FLEET_BY_PRESET = {"easy": 28, "normal": 36, "hard": 44}
# Highway cruise matches city base speed; wet highway is an extra 1/3 slower.
_RAIN_SPEED_MULT = 2.0 / 3.0

_ctx: ModifierContext | None = None
_active = False
_rain_combo = False
_preset_id = "normal"


def install_for_round(ctx: ModifierContext, *, preset_id: str = "normal") -> None:
    global _ctx, _active, _rain_combo, _preset_id
    _ctx = ctx
    _active = ctx.has("highway")
    _rain_combo = _active and ctx.has("rainy_roads")
    _preset_id = preset_id if preset_id in _LANES_BY_PRESET else "normal"


def is_active() -> bool:
    return _active


def rain_combo_active() -> bool:
    return _rain_combo


def signals_enabled() -> bool:
    return not _active


def crosswalks_enabled() -> bool:
    return not _active


def should_emit_crosswalk_risks() -> bool:
    return not _active


def highway_lane_count(preset_id: str | None = None) -> int:
    return int(_LANES_BY_PRESET.get(preset_id or _preset_id, 12))


def highway_time_limit(preset_id: str | None = None) -> int:
    return int(_TIME_LIMIT_BY_PRESET.get(preset_id or _preset_id, 85))


def highway_max_lane_active() -> int | None:
    if not _active:
        return None
    return int(_MAX_LANE_ACTIVE_BY_PRESET.get(_preset_id, 56))


def edge_spawn_queue_cap() -> int | None:
    """Per-lane edge queue when highway is active (None = use city default)."""
    if not _active:
        return None
    return int(_EDGE_QUEUE_BY_PRESET.get(_preset_id, 8))


def car_speed_mult() -> float:
    """Highway cars use normal speed; with rain they are 1/3 slower."""
    if not _active:
        return 1.0
    if _rain_combo:
        return _RAIN_SPEED_MULT
    return 1.0


def opening_fleet_target(preset_id: str | None = None) -> int:
    return int(_OPENING_FLEET_BY_PRESET.get(preset_id or _preset_id, 36))


def should_emit_highway_crossing_risk(*, on_road: bool, moved: bool) -> bool:
    return _active and on_road and moved


def should_disable_player_yield() -> bool:
    """Highway traffic does not brake for the pedestrian (still collides)."""
    return _active


def should_skip_player_body_block() -> bool:
    return _active


def spawn_ramp_frames() -> int:
    """Off-screen highway cars reach cruise speed quickly."""
    return 16 if _active else 90


def near_player_spawn_gap_px() -> int:
    """Minimum along-travel gap from player for non-initial highway spawns."""
    from pathwise.commonUtils import CAR_WIDTH

    return int(CAR_WIDTH * 4)


def min_vertical_weave_gap_px() -> int:
    """Minimum vertical clearance between highway cars so the player can weave.

    Cars that overlap along the travel (horizontal) axis must leave at least
    1.5 player bodies of vertical space so the player can slip between them.
    """
    from pathwise.map import BASE_SIZE

    return int(BASE_SIZE * 1.5)


def player_at_highway_side(player_rect, road) -> bool:
    """True when the player is on a sidewalk / curb, not mid-carriageway."""
    if player_rect is None or road is None:
        return True
    margin = 36
    cy = player_rect.centery
    # VERTICAL road = E-W strip; sides are north/south (top/bottom).
    if road.direction == "vertical":
        return cy < road.rect.top + margin or cy > road.rect.bottom - margin
    return (
        player_rect.centerx < road.rect.left + margin
        or player_rect.centerx > road.rect.right - margin
    )


class HighwayMap(MapBase):
    """Minimal map: one E-W highway strip; spawn/goal on opposite sidewalks."""

    def __init__(self, seed: int, difficulty: DifficultyProfile, preset_id: str):
        preset = preset_id if preset_id in _LANES_BY_PRESET else "normal"
        lanes = _LANES_BY_PRESET[preset]
        parallel = max(1, lanes // 2)
        thickness = max(220, lanes * _LANE_PX)
        time_limit = _TIME_LIMIT_BY_PRESET[preset]
        traffic_w = _TRAFFIC_WEIGHT_BY_PRESET[preset]
        opening_fleet = _OPENING_FLEET_BY_PRESET[preset]

        # Full playable width is asphalt edge-to-edge so the player cannot walk around.
        # Height keeps north/south sidewalk bands only (unchanged layout).
        world_left, world_top = 0, 200
        world_w = 2000
        sidewalk = 140
        world_h = thickness + sidewalk * 2 + 160
        road_top = world_top + sidewalk
        road = Road(
            make_rectangle(world_left, road_top, world_w, thickness),
            VERTICAL,
        )
        road.traffic_weight = traffic_w
        road.parallel_lanes = parallel
        road.traffic_density_mult = _TRAFFIC_DENSITY_MULT
        road.opening_fleet = opening_fleet

        sx = world_left + world_w // 2
        sy = road.rect.bottom + 80
        gx = sx
        gy = road.rect.top - 80
        goal_rect = Rect(gx - BASE_SIZE // 2, gy - BASE_SIZE // 2, BASE_SIZE, BASE_SIZE)

        self.seed = int(seed)
        self.target_crossings = 1
        self.time_limit = time_limit
        self.map_id = f"highway_{self.seed}"
        self.n_h = 0
        self.n_v = 1
        self.difficulty = difficulty.to_dict()
        self.analytics_zones = []
        self.traffic_weights = [traffic_w]
        self.path_estimate_s = float(time_limit) * 0.55
        self.route_crossings = 1
        self.light_cycle_scale = difficulty.light_cycle_scale
        self.generation_meta = {
            "mode": "highway",
            "lanes": lanes,
            "parallel_lanes": parallel,
            "thickness": thickness,
            "preset": preset,
            "traffic_density_mult": _TRAFFIC_DENSITY_MULT,
            "opening_fleet": opening_fleet,
            "car_speed_mult": 1.0,
            "rain_speed_mult": _RAIN_SPEED_MULT,
            "full_width": True,
            "spawn_edge": "south",
            "goal_edge": "north",
        }
        self.city_blocks = []
        self.decorations = []
        # Exact horizontal match to the road; vertical room for sidewalks only.
        self.world_bounds_hint = Rect(world_left, world_top, world_w, world_h)
        super().__init__([road], (sx, sy), goal_rect)


def generate_highway_map(
    *,
    seed: int,
    difficulty: DifficultyProfile,
    preset_id: str,
) -> HighwayMap:
    return HighwayMap(seed, difficulty, preset_id)
