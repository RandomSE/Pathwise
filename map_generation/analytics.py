"""Recruiter analytics zones tied to cognitive challenge locations."""

from __future__ import annotations


def build_analytics_zones(roads, h_ys: list[int], v_xs: list[int], start_pos, goal_rect) -> list[dict]:
    zones: list[dict] = []
    vertical = [r for r in roads if r.direction == "vertical"]
    horizontal = [r for r in roads if r.direction == "horizontal"]

    for i, v_road in enumerate(vertical):
        for j, h_road in enumerate(horizontal):
            intersection = v_road.rect.clip(h_road.rect)
            if intersection.width <= 0 or intersection.height <= 0:
                continue
            zones.append(
                {
                    "id": f"intersection_{i}_{j}",
                    "type": "intersection",
                    "label": f"Intersection {i + 1}-{j + 1}",
                    "rect": [
                        intersection.x,
                        intersection.y,
                        intersection.w,
                        intersection.h,
                    ],
                    "challenge": "multi_signal_timing",
                }
            )

    for idx, road in enumerate(roads):
        cx, cy = road.rect.centerx, road.rect.centery
        if road.direction == "vertical":
            rect = [
                road.rect.centerx - 55,
                road.rect.top + 20,
                110,
                max(40, road.rect.height - 40),
            ]
        else:
            rect = [
                road.rect.left + 20,
                road.rect.centery - 55,
                max(40, road.rect.width - 40),
                110,
            ]
        zones.append(
            {
                "id": f"crossing_road_{idx}",
                "type": "crossing",
                "label": f"Road {idx + 1} crossing",
                "rect": rect,
                "road_index": idx,
                "challenge": "gap_acceptance",
            }
        )

    if len(vertical) >= 2 and len(horizontal) >= 2:
        mid_x = (v_xs[0] + v_xs[-1]) // 2
        mid_y = (h_ys[0] + h_ys[-1]) // 2
        zones.append(
            {
                "id": "choke_center",
                "type": "choke",
                "label": "Central choke zone",
                "rect": [mid_x - 70, mid_y - 70, 140, 140],
                "challenge": "traffic_density",
            }
        )

    zones.append(
        {
            "id": "spawn",
            "type": "spawn",
            "label": "Start",
            "rect": [start_pos[0] - 50, start_pos[1] - 50, 100, 100],
            "challenge": "route_planning",
        }
    )
    gr = goal_rect
    zones.append(
        {
            "id": "goal",
            "type": "goal",
            "label": "Goal",
            "rect": [gr.x - 20, gr.y - 20, gr.w + 40, gr.h + 40],
            "challenge": "goal_completion",
        }
    )
    return zones
