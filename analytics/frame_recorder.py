"""Record discrete world-state frames for deterministic dashboard replay.

Capture policy:
- Periodic samples on a fixed time grid (smooth, predictable playback).
- Immediate sample on every decision (jump-to-decision targets).
- Start and end frames always captured.
- Each frame and decision has a stable unique id.
"""

FIXED_SAMPLE_INTERVAL_S = 1.0 / 12.0
MIN_FRAME_GAP_S = 0.02
MAX_REPLAY_GAP_S = 1.0 / 24.0
# Bound replay payload growth (~30s at 12 Hz + decision headroom).
MAX_REPLAY_FRAMES = 360
MIN_DECISION_CAPTURE_GAP_S = 0.2

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
        self._last_decision_capture_t = -999.0

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

    def capture(
        self,
        elapsed,
        player_rect,
        car_sprites,
        road_states,
        force=False,
        game_time=None,
        *,
        is_start=False,
        is_end_frame=False,
    ):
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

        if is_decision and not force:
            if elapsed - self._last_decision_capture_t < MIN_DECISION_CAPTURE_GAP_S:
                is_decision = False
                decision = None
                should_capture = periodic_due
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
                    "ts": state.get("turn_light_state", "red"),
                    "in": round(state.get("seconds_to_change", 0), 1),
                    "tin": round(state.get("turn_seconds_to_change", 0), 1),
                    "next": state.get("next_light", "green"),
                    "tnext": state.get("next_turn_light", "green"),
                }
                for state in road_states
            ],
        }
        if is_decision:
            frame["decision"] = dict(decision)
            frame["is_decision"] = True
        if is_start:
            frame["is_start"] = True
        if is_end_frame:
            frame["is_end"] = True

        self.frames.append(frame)
        self._frame_seq += 1
        self._last_capture_t = elapsed
        if is_decision:
            self._last_decision_capture_t = elapsed
        self._trim_if_needed()

    def _trim_if_needed(self) -> None:
        """Drop periodic samples in dense regions; never create large sim-time gaps."""
        while len(self.frames) > MAX_REPLAY_FRAMES:
            drop_idx = self._pick_trim_candidate()
            if drop_idx is None:
                break
            del self.frames[drop_idx]

    def _pick_trim_candidate(self) -> int | None:
        over_cap = len(self.frames) > MAX_REPLAY_FRAMES
        max_drop_gap = (
            FIXED_SAMPLE_INTERVAL_S * 4.0
            if over_cap
            else MAX_REPLAY_GAP_S * 1.25
        )
        best_idx = None
        best_score = -1.0
        for index, frame in enumerate(self.frames):
            if frame.get("is_start") or frame.get("is_decision") or frame.get("is_end"):
                continue
            if frame.get("synthetic"):
                continue
            prev_t = self.frames[index - 1]["t"]
            next_t = (
                self.frames[index + 1]["t"]
                if index + 1 < len(self.frames)
                else prev_t + FIXED_SAMPLE_INTERVAL_S
            )
            gap_if_dropped = next_t - prev_t
            if gap_if_dropped > max_drop_gap:
                continue
            if gap_if_dropped > best_score:
                best_score = gap_if_dropped
                best_idx = index
        if best_idx is None and over_cap:
            for index, frame in enumerate(self.frames):
                if frame.get("is_start") or frame.get("is_decision") or frame.get("is_end"):
                    continue
                return index
        return best_idx

    def densify_frames(self, max_gap_s: float = MAX_REPLAY_GAP_S) -> None:
        """Insert interpolated frames so playback gaps stay small."""
        if len(self.frames) < 2:
            return
        dense: list[dict] = [self.frames[0]]
        for nxt in self.frames[1:]:
            cur = dense[-1]
            gap = nxt["t"] - cur["t"]
            if gap > max_gap_s:
                steps = max(1, int(gap / max_gap_s))
                for step in range(1, steps):
                    alpha = step / steps
                    dense.append(self._interpolate_frame(cur, nxt, alpha))
            dense.append(nxt)
        if len(dense) > MAX_REPLAY_FRAMES:
            dense = self._trim_dense_frames(dense)
        self.frames = dense

    def _interpolate_frame(self, left: dict, right: dict, alpha: float) -> dict:
        t = round(left["t"] + (right["t"] - left["t"]) * alpha, 3)
        lp = left["player"]
        rp = right["player"]
        player = {
            "x": round(lp["x"] + (rp["x"] - lp["x"]) * alpha),
            "y": round(lp["y"] + (rp["y"] - lp["y"]) * alpha),
            "s": lp.get("s", self.pedestrian_size),
        }
        cars_by_id: dict[int, dict] = {c["id"]: dict(c) for c in left.get("cars", [])}
        for car in right.get("cars", []):
            cid = car["id"]
            if cid not in cars_by_id:
                if alpha >= 0.5:
                    cars_by_id[cid] = dict(car)
                continue
            merged = cars_by_id[cid]
            for key in ("x", "y", "cx", "cy"):
                if key in merged and key in car:
                    merged[key] = round(merged[key] + (car[key] - merged[key]) * alpha)
            if "ang" in merged and "ang" in car:
                merged["ang"] = round(merged["ang"] + (car["ang"] - merged["ang"]) * alpha, 1)
            if "sp" in merged and "sp" in car:
                merged["sp"] = round(merged["sp"] + (car["sp"] - merged["sp"]) * alpha, 2)
        return {
            "id": f"f_interp_{len(self.frames):05d}_{int(alpha * 1000)}",
            "seq": left.get("seq", 0),
            "t": t,
            "player": player,
            "cars": list(cars_by_id.values()),
            "lights": left.get("lights", []),
            "synthetic": True,
        }

    def _trim_dense_frames(self, frames: list[dict]) -> list[dict]:
        if len(frames) <= MAX_REPLAY_FRAMES:
            return frames
        out = list(frames)
        while len(out) > MAX_REPLAY_FRAMES:
            drop_idx = None
            best_score = -1.0
            for index, frame in enumerate(out):
                if frame.get("is_start") or frame.get("is_decision") or frame.get("is_end"):
                    continue
                if index == len(out) - 1:
                    continue
                if not frame.get("synthetic"):
                    continue
                prev_t = out[index - 1]["t"]
                next_t = out[index + 1]["t"]
                gap_if_dropped = next_t - prev_t
                if gap_if_dropped > MAX_REPLAY_GAP_S * 1.25:
                    continue
                if gap_if_dropped > best_score:
                    best_score = gap_if_dropped
                    drop_idx = index
            if drop_idx is None:
                break
            del out[drop_idx]
        return out

    def capture_start(self, elapsed, player_rect, car_sprites, road_states, game_time=None):
        self._next_periodic_t = FIXED_SAMPLE_INTERVAL_S
        self.capture(
            elapsed,
            player_rect,
            car_sprites,
            road_states,
            force=True,
            game_time=game_time,
            is_start=True,
        )

    def capture_end(self, elapsed, player_rect, car_sprites, road_states, game_time=None):
        self.capture(
            elapsed,
            player_rect,
            car_sprites,
            road_states,
            force=True,
            game_time=game_time,
            is_end_frame=True,
        )
        self.densify_frames()
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
    from pathwise import commonUtils

    rect = car.rect
    vertical = bool(car.vertical)
    draw_w, draw_h = rect.w, rect.h
    turn_phase = getattr(car, "_turn_phase", "none")
    payload = {
        "id": int(getattr(car, "spawn_id", 0)),
        "x": rect.x,
        "y": rect.y,
        "w": draw_w,
        "h": draw_h,
        "v": 1 if vertical else 0,
        "a": getattr(car, "archetype_index", 0),
        "sp": round(float(getattr(car, "current_speed", 0)), 2),
        "dir": int(getattr(car, "direction", 1)),
        "ts": int(getattr(car, "turn_signal", 0)),
    }
    if turn_phase in ("turning", "settling"):
        # Replay draws the same east-facing base sprite as make_car_rotated_in_box.
        draw_w, draw_h = commonUtils.CAR_WIDTH, commonUtils.CAR_HEIGHT
        entry_vertical = bool(getattr(car, "_turn_entry_vertical", vertical))
        payload["w"] = draw_w
        payload["h"] = draw_h
        payload["v"] = 0
        payload["tv"] = 1 if entry_vertical else 0
        payload["tp"] = turn_phase
        payload["ang"] = round(float(getattr(car, "_turn_display_angle", 0.0)), 1)
        payload["cx"] = round(float(getattr(car, "_turn_px", rect.centerx)))
        payload["cy"] = round(float(getattr(car, "_turn_py", rect.centery)))
        payload["x"] = payload["cx"] - draw_w // 2
        payload["y"] = payload["cy"] - draw_h // 2
    if getattr(car, "is_honking", None) and car.is_honking(game_time):
        payload["honk"] = 1
    return payload
