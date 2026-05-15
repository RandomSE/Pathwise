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

    return {
        "map_id": current_map.__class__.__name__,
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
        "crosswalks": crosswalks,
    }
