"""Record discrete world-state frames for dashboard replay.

Capture policy:
- Baseline sample every BASE_INTERVAL seconds (smooth scrubbing).
- Always capture on decision events (commits, hesitation, risk, backtrack, etc.).
- Always capture start and end of run.
- Skip non-decision frames that occur within MIN_GAP of the previous frame.
"""

BASE_INTERVAL_S = 0.4
MIN_GAP_S = 0.14

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
        "risky_move",
        "backtrack",
        "car_honk",
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
    "risky_move": "Risky move",
    "backtrack": "Backtrack",
    "car_honk": "Car honk",
}


class FrameRecorder:
    def __init__(self, pedestrian_size):
        self.pedestrian_size = pedestrian_size
        self.frames = []
        self._last_capture_t = -999.0
        self._queued_decision = None

    def queue_decision(self, action, **context):
        if action not in DECISION_ACTIONS:
            return
        label = DECISION_LABELS.get(action, action.replace("_", " ").title())
        if action == "approach_road" and "road_index" in context:
            label = f"Approaching road {context['road_index']}"
        elif "commit_time_s" in context:
            label = f"{label} ({context['commit_time_s']}s)"
        elif action == "car_honk" and context.get("reason") == "jaywalk":
            label = "Car honk (jaywalking)"
        elif action == "car_honk" and context.get("reason") == "close":
            label = "Car honk (too close)"
        elif action == "car_honk" and context.get("reason") == "blocked":
            label = "Car honk (blocked by player)"
        self._queued_decision = {"action": action, "label": label}

    def capture(self, elapsed, player_rect, car_sprites, road_states, force=False, game_time=None):
        decision = self._queued_decision
        self._queued_decision = None

        is_decision = decision is not None
        if not force and not is_decision:
            if elapsed - self._last_capture_t < BASE_INTERVAL_S:
                return
            if elapsed - self._last_capture_t < MIN_GAP_S:
                return

        if not force and not is_decision and self.frames:
            if elapsed - self._last_capture_t < MIN_GAP_S:
                return

        frame = {
            "t": round(elapsed, 3),
            "player": {
                "x": player_rect.centerx,
                "y": player_rect.centery,
                "s": self.pedestrian_size,
            },
            "cars": [_serialize_car(car, game_time if game_time is not None else elapsed) for car in car_sprites],
            "lights": [state["light_state"] for state in road_states],
        }
        if is_decision:
            frame["decision"] = decision
            frame["is_decision"] = True
        if force and not is_decision:
            frame["is_end"] = True

        self.frames.append(frame)
        self._last_capture_t = elapsed

    def capture_start(self, elapsed, player_rect, car_sprites, road_states, game_time=None):
        self.capture(elapsed, player_rect, car_sprites, road_states, force=True, game_time=game_time)

    def capture_end(self, elapsed, player_rect, car_sprites, road_states, game_time=None):
        self.capture(elapsed, player_rect, car_sprites, road_states, force=True, game_time=game_time)

    def decision_marks(self):
        marks = []
        for index, frame in enumerate(self.frames):
            if frame.get("is_decision") and frame.get("decision"):
                marks.append(
                    {
                        "frame": index,
                        "t": frame["t"],
                        "action": frame["decision"]["action"],
                        "label": frame["decision"]["label"],
                    }
                )
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
    }
    if getattr(car, "is_honking", None) and car.is_honking(game_time):
        payload["honk"] = 1
    return payload
