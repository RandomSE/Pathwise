"""Difficulty profiles and adaptive scaling from prior runs."""

from dataclasses import dataclass, asdict


@dataclass
class DifficultyProfile:
    level: float
    car_speed_mult: float
    spawn_rate_mult: float
    min_crossings: int
    max_crossings: int
    light_cycle_scale: float
    traffic_density: float
    unpredictability: float

    @classmethod
    def from_level(cls, level: float) -> "DifficultyProfile":
        level = max(0.0, min(1.0, level))
        return cls(
            level=round(level, 3),
            car_speed_mult=round(0.85 + level * 0.35, 3),
            spawn_rate_mult=round(0.55 + level * 0.45, 3),
            min_crossings=3 + int(level > 0.55),
            max_crossings=4 + int(level > 0.75),
            light_cycle_scale=round(1.05 - level * 0.25, 3),
            traffic_density=round(0.45 + level * 0.55, 3),
            unpredictability=round(0.15 + level * 0.45, 3),
        )

    @classmethod
    def default(cls) -> "DifficultyProfile":
        return cls.from_level(0.45)

    @classmethod
    def for_menu_preset(cls, preset: str) -> "DifficultyProfile":
        levels = {"easy": 0.28, "normal": 0.45, "hard": 0.62}
        return cls.from_level(levels.get(preset.lower(), 0.45))

    @classmethod
    def for_round(cls, base_level: float, round_index: int, total_rounds: int = 3) -> "DifficultyProfile":
        """Round 1 uses base; each later round steps up (~15% level per round)."""
        if total_rounds <= 1:
            step = 0.0
        else:
            step = 0.15 * (round_index / (total_rounds - 1))
        return cls.from_level(min(1.0, base_level + step))

    def to_dict(self) -> dict:
        return asdict(self)


def adaptive_difficulty(prior_session: dict | None) -> DifficultyProfile:
    """Tune next map from previous candidate performance."""
    if not prior_session:
        return DifficultyProfile.default()

    outcome = prior_session.get("outcome", "")
    duration = float(prior_session.get("duration_s", 30))
    time_limit = float(prior_session.get("time_limit", 30) or 30)
    risks = int(prior_session.get("risk_events", 0))
    collisions = int(prior_session.get("collisions", 0))

    level = 0.45
    if outcome == "success":
        if duration < time_limit * 0.55 and risks <= 1:
            level = 0.72
        elif duration < time_limit * 0.75 and risks <= 2:
            level = 0.58
        else:
            level = 0.5
    elif outcome == "timeout":
        level = 0.32
    elif outcome == "collision":
        level = 0.28
    else:
        level = 0.4

    if risks >= 5:
        level -= 0.12
    if collisions > 0:
        level -= 0.08

    return DifficultyProfile.from_level(level)
