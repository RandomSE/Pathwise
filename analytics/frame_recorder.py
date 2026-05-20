"""Record discrete world-state frames for deterministic dashboard replay.

Capture policy:
- Periodic samples on a fixed time grid (smooth, predictable playback).
- Immediate sample on every decision (jump-to-decision targets).
- Start and end frames always captured.
- Each frame and decision has a stable unique id.
"""

FIXED_SAMPLE_INTERVAL_S = 1.0 / 12.0
MIN_FRAME_GAP_S = 0.02

DECISION_ACTIONS = frozenset(
    {
        "hesitation_start",
        "hesitation_end",
        "approach_road",
        "commit",
        "quick_commit",
        "deliberate_commit",
        "cross_on_red",
        "cross_on_green",
        "risk_event",
        "backtrack",
        "car_honk",
        "zone_enter",
    }
)

DECISION_LABELS = {
    "hesitation_start": "Hesitation start",
    "hesitation_end": "Hesitation end",
    "approach_road": "Approaching road",
    "commit": "Crossing commit",
    "quick_commit": "Quick commit",
    "deliberate_commit": "Deliberate commit",
    "cross_on_red": "Cross on red",
    "cross_on_green": "Cross on green",
    "risk_event": "Risk",
    "backtrack": "Backtrack",
    "car_honk": "Car honk",
    "zone_enter": "Challenge zone",
}

RISK_LABELS = {
    "fast_traffic_on_road": "Fast traffic while on road",
    "crosswalk_vehicle_conflict": "Vehicle conflict at crosswalk",
    "vehicle_too_close": "Vehicle too close",
    "near_miss": "Near miss with moving vehicle",
    "car_honk_close": "Honk — too close",
    "car_honk_blocked": "Honk — blocked lane",
    "car_honk_jaywalk": "Honk — jaywalking",
}


class FrameRecorder:
    def __init__(self, pedestrian_size):
        self.pedestrian_size = pedestrian_size
        self.frames = []
        self._last_capture_t = -999.0
        self._next_periodic_t = 0.0
        self._queued_decision = None
        self._frame_seq = 0

    def queue_decision(self, action, decision_id=None, **context):
        if action not in DECISION_ACTIONS:
            return
        label = DECISION_LABELS.get(action, action.replace("_", " ").title())
        if action == "approach_road" and "road_index" in context:
            label = f"Approaching road {context['road_index']}"
        elif "commit_time_s" in context:
            label = f"{label} ({context['commit_time_s']}s)"
        elif action == "risk_event":
            risk_key = context.get("risk") or context.get("risk_label") or "unknown"
            risk_text = context.get("risk_label") or RISK_LABELS.get(risk_key, str(risk_key))
            label = f"Risk: {risk_text}"
        elif action == "car_honk":
            reason = context.get("reason") or "honk"
            risk_key = context.get("risk") or f"car_honk_{reason}"
            risk_text = RISK_LABELS.get(risk_key, f"Car honk ({reason})")
            label = f"Risk: {risk_text}"
        elif action == "zone_enter" and context.get("label"):
            label = context["label"]

        if decision_id is None:
            decision_id = f"pending_{action}"

        payload = {
            "id": decision_id,
            "action": action,
            "label": label,
        }
        if action == "risk_event":
            payload["risk"] = context.get("risk")
            payload["risk_label"] = context.get("risk_label") or RISK_LABELS.get(
                context.get("risk", ""), context.get("risk", "")
            )
        elif action == "car_honk":
            risk_key = context.get("risk") or f"car_honk_{context.get('reason', 'honk')}"
            payload["risk"] = risk_key
            payload["risk_label"] = RISK_LABELS.get(risk_key, risk_key)
        self._queued_decision = payload

    def capture(self, elapsed, player_rect, car_sprites, road_states, force=False, game_time=None):
        decision = self._queued_decision
        self._queued_decision = None
        is_decision = decision is not None

        periodic_due = elapsed >= self._next_periodic_t and not force
        if periodic_due:
            while self._next_periodic_t <= elapsed:
                self._next_periodic_t += FIXED_SAMPLE_INTERVAL_S

        should_capture = force or is_decision or periodic_due
        if not should_capture:
            return

        if (
            not force
            and not is_decision
            and self.frames
            and (elapsed - self._last_capture_t) < MIN_FRAME_GAP_S
        ):
            return

        game_t = game_time if game_time is not None else elapsed
        frame = {
            "id": f"f_{self._frame_seq:05d}",
            "seq": self._frame_seq,
            "t": round(elapsed, 3),
            "player": {
                "x": player_rect.centerx,
                "y": player_rect.centery,
                "s": self.pedestrian_size,
            },
            "cars": [_serialize_car(car, game_t) for car in car_sprites],
            "lights": [
                {
                    "s": state["light_state"],
                    "in": round(state.get("seconds_to_change", 0), 1),
                    "next": state.get("next_light", "green"),
                }
                for state in road_states
            ],
        }
        if is_decision:
            frame["decision"] = dict(decision)
            frame["is_decision"] = True
        if force and not is_decision:
            frame["is_end"] = True

        self.frames.append(frame)
        self._frame_seq += 1
        self._last_capture_t = elapsed

    def capture_start(self, elapsed, player_rect, car_sprites, road_states, game_time=None):
        self._next_periodic_t = FIXED_SAMPLE_INTERVAL_S
        self.capture(elapsed, player_rect, car_sprites, road_states, force=True, game_time=game_time)

    def capture_end(self, elapsed, player_rect, car_sprites, road_states, game_time=None):
        self.capture(elapsed, player_rect, car_sprites, road_states, force=True, game_time=game_time)
        self._ensure_monotonic_times()

    def _ensure_monotonic_times(self):
        last_t = -1.0
        for frame in self.frames:
            t = frame["t"]
            if t <= last_t:
                t = round(last_t + MIN_FRAME_GAP_S, 3)
                frame["t"] = t
            last_t = t

    @staticmethod
    def _is_risk_decision(decision):
        if not decision:
            return False
        return (
            decision.get("action") in ("risk_event", "car_honk")
            or bool(decision.get("risk"))
        )

    def decision_marks(self):
        return [m for m in self._all_marks() if not self._is_risk_decision({"action": m.get("action"), "risk": m.get("risk")})]

    def risk_marks(self):
        return [m for m in self._all_marks() if self._is_risk_decision({"action": m.get("action"), "risk": m.get("risk")})]

    def _all_marks(self):
        marks = []
        for index, frame in enumerate(self.frames):
            decision = frame.get("decision")
            if not frame.get("is_decision") or not decision:
                continue
            mark = {
                "id": decision.get("id"),
                "frame": index,
                "frame_id": frame.get("id"),
                "seq": frame.get("seq", index),
                "t": frame["t"],
                "action": decision.get("action"),
                "label": decision.get("label"),
            }
            if decision.get("risk"):
                mark["risk"] = decision["risk"]
            if decision.get("risk_label"):
                mark["risk_label"] = decision["risk_label"]
            marks.append(mark)
        return marks


def _serialize_car(car, game_time):
    rect = car.rect
    payload = {
        "x": rect.x,
        "y": rect.y,
        "w": rect.w,
        "h": rect.h,
        "v": 1 if car.vertical else 0,
        "a": getattr(car, "archetype_index", 0),
        "sp": round(float(getattr(car, "current_speed", 0)), 2),
        "dir": int(getattr(car, "direction", 1)),
        "ts": int(getattr(car, "turn_signal", 0)),
    }
    if getattr(car, "is_honking", None) and car.is_honking(game_time):
        payload["honk"] = 1
    return payload
