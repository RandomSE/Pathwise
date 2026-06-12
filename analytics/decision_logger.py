import math
import time


HESITATION_THRESHOLD_S = 0.45
BACKTRACK_MIN_PX = 8
POSITION_SAMPLE_INTERVAL_S = 0.12
MAX_HEAT_SAMPLES = 150
MAX_DECISION_LOG_ENTRIES = 96


class DecisionLogger:
    """Captures movement decisions, hesitation, backtracking, and commit timing."""

    def __init__(self, start_pos, goal_pos, map_id, road_count, frame_recorder=None, analytics_zones=None):
        self.start_time = time.time()
        self.map_id = map_id
        self.road_count = road_count
        self.goal_pos = goal_pos
        self.decisions = []
        self.heat_samples = []
        self.hesitation_events = []
        self.crossing_attempts = []
        self.analytics_zones = list(analytics_zones or [])
        self._active_zone_ids = set()

        self._last_pos = start_pos
        self._last_move_time = self.start_time
        self._still_since = self.start_time
        self._last_sample_time = 0.0
        self._net_progress_axis = None
        self._approach_start = {}
        self._active_hesitation = None
        self._total_backtracks = 0
        self._total_hesitation_s = 0.0
        self._quick_commits = 0
        self._slow_commits = 0
        self._frame_recorder = frame_recorder
        self._decision_seq = 0

    def set_frame_recorder(self, frame_recorder):
        self._frame_recorder = frame_recorder

    def _elapsed(self):
        return round(time.time() - self.start_time, 3)

    def _goal_vector(self, pos):
        gx, gy = self.goal_pos
        return gx - pos[0], gy - pos[1]

    def _progress_along_goal(self, pos, prev_pos):
        gvx, gvy = self._goal_vector(prev_pos)
        length = math.hypot(gvx, gvy) or 1.0
        ux, uy = gvx / length, gvy / length
        dx = pos[0] - prev_pos[0]
        dy = pos[1] - prev_pos[1]
        return dx * ux + dy * uy

    def _next_decision_id(self):
        self._decision_seq += 1
        return f"d_{self._decision_seq:04d}"

    def _record(self, action, **context):
        decision_id = self._next_decision_id()
        entry = {"id": decision_id, "t": self._elapsed(), "action": action}
        entry.update(context)
        self.decisions.append(entry)
        if len(self.decisions) > MAX_DECISION_LOG_ENTRIES:
            del self.decisions[: len(self.decisions) - MAX_DECISION_LOG_ENTRIES]
        if self._frame_recorder:
            self._frame_recorder.queue_decision(action, decision_id=decision_id, **context)

    def note_risk(self, reason, **context):
        from analytics.frame_recorder import RISK_LABELS

        risk_label = RISK_LABELS.get(reason, reason.replace("_", " "))
        self._record("risk_event", risk=reason, risk_label=risk_label, **context)

    def _grid_cell(self, pos, cell_size=40):
        return [int(pos[0] // cell_size), int(pos[1] // cell_size)]

    def update(self, pos, keys_pressed, on_crosswalk, on_road, light_state, risk_flag):
        now = time.time()
        moved = abs(pos[0] - self._last_pos[0]) + abs(pos[1] - self._last_pos[1]) > 0.5

        if now - self._last_sample_time >= POSITION_SAMPLE_INTERVAL_S:
            self.heat_samples.append(
                {
                    "t": self._elapsed(),
                    "x": round(pos[0], 1),
                    "y": round(pos[1], 1),
                    "cell": self._grid_cell(pos),
                    "on_crosswalk": on_crosswalk,
                    "on_road": on_road,
                    "light": light_state,
                }
            )
            if len(self.heat_samples) > MAX_HEAT_SAMPLES:
                del self.heat_samples[: len(self.heat_samples) - MAX_HEAT_SAMPLES]
            self._last_sample_time = now

        if moved:
            progress = self._progress_along_goal(pos, self._last_pos)
            if progress < -BACKTRACK_MIN_PX:
                self._total_backtracks += 1
                self._record(
                    "backtrack",
                    delta_px=round(progress, 1),
                    on_crosswalk=on_crosswalk,
                    on_road=on_road,
                )
            if on_crosswalk and light_state == "red":
                self._record("cross_on_red", light=light_state)
            elif on_crosswalk and light_state == "green":
                self._record("cross_on_green", light=light_state)

            self._last_move_time = now
            self._still_since = now
            if self._active_hesitation:
                duration = now - self._active_hesitation["start"]
                if duration >= HESITATION_THRESHOLD_S:
                    event = {
                        "start_t": round(self._active_hesitation["start"] - self.start_time, 3),
                        "end_t": self._elapsed(),
                        "duration_s": round(duration, 2),
                        "near_crosswalk": self._active_hesitation["near_crosswalk"],
                        "light": self._active_hesitation["light"],
                    }
                    self.hesitation_events.append(event)
                    self._total_hesitation_s += duration
                    self._record(
                        "hesitation_end",
                        duration_s=event["duration_s"],
                        near_crosswalk=event["near_crosswalk"],
                    )
                self._active_hesitation = None
        else:
            idle_duration = now - self._still_since
            near_crosswalk = on_crosswalk or on_road
            if idle_duration >= HESITATION_THRESHOLD_S and self._active_hesitation is None:
                self._active_hesitation = {
                    "start": self._still_since,
                    "near_crosswalk": near_crosswalk,
                    "light": light_state,
                }
                self._record(
                    "hesitation_start",
                    near_crosswalk=near_crosswalk,
                    light=light_state,
                )

        if keys_pressed and not moved:
            self._record("input_while_still", keys=list(keys_pressed))

        self._track_analytics_zones(pos)

        self._last_pos = pos

    def _track_analytics_zones(self, pos):
        px, py = pos
        for zone in self.analytics_zones:
            rect = zone.get("rect")
            if not rect or len(rect) < 4:
                continue
            x, y, w, h = rect
            inside = x <= px <= x + w and y <= py <= y + h
            zone_id = zone.get("id", "")
            if inside and zone_id not in self._active_zone_ids:
                self._active_zone_ids.add(zone_id)
                self._record(
                    "zone_enter",
                    zone_id=zone_id,
                    zone_type=zone.get("type"),
                    challenge=zone.get("challenge"),
                    label=zone.get("label"),
                )
            elif not inside and zone_id in self._active_zone_ids:
                self._active_zone_ids.discard(zone_id)

    def note_road_approach(self, road_index):
        if road_index not in self._approach_start:
            self._approach_start[road_index] = time.time()
            self._record("approach_road", road_index=road_index)

    def note_road_crossed(self, road_index, light_state):
        started = self._approach_start.pop(road_index, None)
        commit_s = round(time.time() - started, 2) if started else None
        attempt = {
            "road_index": road_index,
            "commit_time_s": commit_s,
            "light_at_cross": light_state,
            "t": self._elapsed(),
        }
        self.crossing_attempts.append(attempt)
        if commit_s is not None:
            if commit_s < 1.2:
                self._quick_commits += 1
                self._record("quick_commit", road_index=road_index, commit_time_s=commit_s)
            elif commit_s > 4.0:
                self._slow_commits += 1
                self._record("deliberate_commit", road_index=road_index, commit_time_s=commit_s)
            else:
                self._record("commit", road_index=road_index, commit_time_s=commit_s)

    def finalize(self, outcome, duration, crossings, collisions, risk_events, failure_reason):
        if self._active_hesitation:
            now = time.time()
            duration_h = now - self._active_hesitation["start"]
            if duration_h >= HESITATION_THRESHOLD_S:
                self.hesitation_events.append(
                    {
                        "start_t": round(self._active_hesitation["start"] - self.start_time, 3),
                        "end_t": self._elapsed(),
                        "duration_s": round(duration_h, 2),
                        "near_crosswalk": self._active_hesitation["near_crosswalk"],
                        "light": self._active_hesitation["light"],
                    }
                )
                self._total_hesitation_s += duration_h

        return {
            "outcome": outcome,
            "duration_s": duration,
            "crossings": crossings,
            "collisions": collisions,
            "risk_events": risk_events,
            "failure_reason": failure_reason,
            "map_id": self.map_id,
            "decision_sequence": self.decisions,
            "hesitation_events": self.hesitation_events,
            "crossing_attempts": self.crossing_attempts,
            "heat_samples": self.heat_samples,
            "replay_frames": (
                list(self._frame_recorder.frames) if self._frame_recorder else []
            ),
            "decision_marks": (
                self._frame_recorder.decision_marks() if self._frame_recorder else []
            ),
            "risk_marks": (
                self._frame_recorder.risk_marks() if self._frame_recorder else []
            ),
            "analytics_zones": self.analytics_zones,
            "summary": {
                "total_backtracks": self._total_backtracks,
                "total_hesitation_s": round(self._total_hesitation_s, 2),
                "hesitation_count": len(self.hesitation_events),
                "quick_commits": self._quick_commits,
                "slow_commits": self._slow_commits,
                "decision_count": len(self.decisions),
            },
        }
