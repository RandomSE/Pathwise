import math
from typing import TYPE_CHECKING

import arcade

from . import commonUtils
from .geom import Rect

if TYPE_CHECKING:
    from . import map_visuals

WIDTH = commonUtils.WIDTH
VERTICAL = commonUtils.VERTICAL
HORIZONTAL = commonUtils.HORIZONTAL
BASE_SIZE = 40
ROAD_THICKNESS = 90
ROAD_SPAN = int(WIDTH * 1.35)
ROAD_GAP = 240


class Road:
    def __init__(self, rect, direction):
        self.rect = rect
        self.crossed = False
        self.direction = direction


def make_rectangle(left, top, width, height):
    return Rect(left, top, width, height)


class MapBase:
    def __init__(self, roads, start_pos, goal_rect):
        self.roads = roads
        self.start_pos = start_pos
        self.goal_rect = goal_rect
        self.baked_layer = None

    def bake(
        self,
        city_blocks=None,
        decorations=None,
        world_bounds=None,
        map_id: str = "map",
        road_states=None,
    ):
        from . import map_visuals

        if world_bounds is None:
            return
        self.baked_layer = map_visuals.bake_static_map(
            self.roads,
            city_blocks or [],
            decorations or [],
            world_bounds,
            self.goal_rect,
            map_id=map_id,
            road_states=road_states,
        )

    def draw(
        self,
        window_height: int,
        camera_offset,
        player,
        city_blocks=None,
        world_bounds=None,
        decorations=None,
        view_rect=None,
    ):
        from . import map_visuals

        if self.baked_layer is not None:
            map_visuals.draw_baked_map(
                self.baked_layer, camera_offset, window_height, view_rect
            )
        draw_arrow(window_height, player, self.goal_rect, camera_offset)


def draw_arrow(window_height: int, player, goal_rect: Rect, camera_offset):
    from .pathwise_render import sim_point_to_arcade

    base_x = player.rect.centerx - camera_offset[0]
    base_y = player.rect.top - 50 - camera_offset[1]
    goal_cx = goal_rect.centerx - camera_offset[0]
    goal_cy = goal_rect.centery - camera_offset[1]

    dx = goal_cx - (player.rect.centerx - camera_offset[0])
    dy = goal_cy - (player.rect.centery - camera_offset[1])
    length = math.hypot(dx, dy)
    if length == 0:
        return
    dx /= length
    dy /= length

    tip_x = base_x + dx * BASE_SIZE
    tip_y = base_y + dy * BASE_SIZE

    bx, by = sim_point_to_arcade(base_x, base_y, window_height)
    tx, ty = sim_point_to_arcade(tip_x, tip_y, window_height)
    arcade.draw_line(bx, by, tx, ty, (0, 0, 0), 3)

    left_dx = dx * math.cos(math.pi / 6) - dy * math.sin(math.pi / 6)
    left_dy = dx * math.sin(math.pi / 6) + dy * math.cos(math.pi / 6)
    right_dx = dx * math.cos(-math.pi / 6) - dy * math.sin(-math.pi / 6)
    right_dy = dx * math.sin(-math.pi / 6) + dy * math.cos(-math.pi / 6)

    lx, ly = sim_point_to_arcade(tip_x - left_dx * 15, tip_y - left_dy * 15, window_height)
    rx, ry = sim_point_to_arcade(tip_x - right_dx * 15, tip_y - right_dy * 15, window_height)
    arcade.draw_line(tx, ty, lx, ly, (0, 0, 0), 3)
    arcade.draw_line(tx, ty, rx, ry, (0, 0, 0), 3)
