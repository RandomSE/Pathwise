"""Serialize the played map layout for dashboard replay."""


def serialize_map_layout(current_map, road_states, world_bounds):
    crosswalks = []
    seen = set()
    for state in road_states:
        cw = state["crosswalk"]
        key = (cw.x, cw.y, cw.w, cw.h)
        if key in seen:
            continue
        seen.add(key)
        sign = state["sign_rect"]
        if state["direction"] == "vertical":
            housing = [
                cw.centerx - 11,
                cw.top - 68,
                22,
                56,
            ]
        else:
            housing = [
                cw.left - 68,
                cw.centery - 11,
                56,
                22,
            ]
        crosswalks.append(
            {
                "x": cw.x,
                "y": cw.y,
                "w": cw.w,
                "h": cw.h,
                "direction": state["direction"],
                "sign": [sign.x, sign.y, sign.w, sign.h],
                "housing": housing,
            }
        )

    map_id = getattr(current_map, "map_id", current_map.__class__.__name__)
    layout = {
        "map_id": map_id,
        "bounds": {
            "x": world_bounds.x,
            "y": world_bounds.y,
            "w": world_bounds.w,
            "h": world_bounds.h,
        },
        "start": list(current_map.start_pos),
        "goal": {
            "x": current_map.goal_rect.x,
            "y": current_map.goal_rect.y,
            "w": current_map.goal_rect.w,
            "h": current_map.goal_rect.h,
        },
        "roads": [
            {
                "x": road.rect.x,
                "y": road.rect.y,
                "w": road.rect.w,
                "h": road.rect.h,
                "direction": road.direction,
            }
            for road in current_map.roads
        ],
        "city_blocks": getattr(current_map, "city_blocks", []),
        "decorations": getattr(current_map, "decorations", []),
        "crosswalks": crosswalks,
    }
    if getattr(current_map, "seed", None) is not None:
        layout["seed"] = current_map.seed
    if getattr(current_map, "time_limit", None) is not None:
        layout["time_limit"] = current_map.time_limit
    if getattr(current_map, "difficulty", None) is not None:
        layout["difficulty"] = current_map.difficulty
    if getattr(current_map, "analytics_zones", None):
        layout["analytics_zones"] = current_map.analytics_zones
    if getattr(current_map, "generation_meta", None) is not None:
        layout["generation"] = current_map.generation_meta
    return layout
