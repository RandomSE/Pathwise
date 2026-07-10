"""Camera view rects and car culling for draw/replay."""

from __future__ import annotations

from pathwise import viewport as game_viewport
from pathwise.geom import Rect, collide
from pathwise.sim_constants import PLAYER_CAR_QUERY_PAD, REPLAY_MAX_CARS, REPLAY_RECORD_EXTRA_PAD

def _cars_near_player(player_body: Rect, spatial, scratch: list) -> list:
    return spatial.nearby(player_body, PLAYER_CAR_QUERY_PAD, scratch)


def _view_rect_for_camera(
    camera_offset: tuple[int, int],
    viewport_w: int | None = None,
    viewport_h: int | None = None,
) -> Rect:
    w, h = game_viewport.normalize_viewport_size(viewport_w, viewport_h)
    return game_viewport.view_rect_for_camera(camera_offset, w, h)


def _replay_view_rect_for_camera(
    camera_offset: tuple[int, int],
    viewport_w: int | None = None,
    viewport_h: int | None = None,
) -> Rect:
    """Wider than draw view so replay shows cars before they enter the screen."""
    return _view_rect_for_camera(camera_offset, viewport_w, viewport_h).inflate(
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

