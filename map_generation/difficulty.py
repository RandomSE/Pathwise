"""Difficulty profiles and adaptive scaling from prior runs."""

from dataclasses import dataclass, asdict, replace


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
    stride_scale: float = 1.0
    target_play_time_s: int = 120
    route_time_margin: float = 1.05
    round_escalation: float = 0.0

    @classmethod
    def from_level(cls, level: float) -> "DifficultyProfile":
        level = max(0.0, min(1.0, level))
        min_crossings = 5 + int(level * 5)
        max_crossings = min(14, min_crossings + 2 + int(level * 4))
        return cls(
            level=round(level, 3),
            car_speed_mult=round(0.85 + level * 0.35, 3),
            spawn_rate_mult=round(0.55 + level * 0.45, 3),
            min_crossings=min_crossings,
            max_crossings=max_crossings,
            light_cycle_scale=round(1.05 - level * 0.25, 3),
            traffic_density=round(0.45 + level * 0.55, 3),
            unpredictability=round(0.15 + level * 0.45, 3),
            stride_scale=round(1.10 + level * 0.38, 3),
            target_play_time_s=int(110 + level * 190),
        )

    @classmethod
    def default(cls) -> "DifficultyProfile":
        return cls.from_level(0.45)

    @classmethod
    def for_menu_preset(cls, preset: str) -> "DifficultyProfile":
        levels = {"easy": 0.28, "normal": 0.45, "hard": 0.62}
        profile = cls.from_level(levels.get(preset.lower(), 0.45))
        preset_targets = {
            "easy": {
                "target_play_time_s": 50,
                "route_time_margin": 1.05,
                "min_crossings": 4,
                "max_crossings": 6,
                "stride_scale": 1.32,
                "traffic_density": round(min(1.0, profile.traffic_density * 2.0), 3),
                "spawn_rate_mult": round(min(1.35, profile.spawn_rate_mult * 2.0), 3),
            },
            "normal": {
                "target_play_time_s": 65,
                "route_time_margin": 1.10,
                "min_crossings": 5,
                "max_crossings": 7,
                "stride_scale": 1.42,
                "traffic_density": round(min(1.0, profile.traffic_density * 2.0), 3),
                "spawn_rate_mult": round(min(1.35, profile.spawn_rate_mult * 2.0), 3),
            },
            "hard": {
                "target_play_time_s": 80,
                "route_time_margin": 1.15,
                "min_crossings": 6,
                "max_crossings": 9,
                "stride_scale": 1.52,
                "traffic_density": round(
                    min(1.0, profile.traffic_density * 2.0 * 1.5), 3
                ),
                "spawn_rate_mult": round(
                    min(1.35, profile.spawn_rate_mult * 2.0 * 1.5), 3
                ),
            },
        }
        overrides = preset_targets.get(preset.lower())
        if overrides:
            for key, value in overrides.items():
                setattr(profile, key, value)
        return profile

    @classmethod
    def for_round(
        cls,
        base: "DifficultyProfile",
        round_index: int,
        total_rounds: int = 3,
    ) -> "DifficultyProfile":
        """
        Scale up from the menu preset each round (round_index 0 = first round).
        Later rounds: more roads, faster/denser traffic, tighter lights, larger map.
        """
        if total_rounds <= 1:
            t = 0.0
        else:
            t = max(0.0, min(1.0, round_index / (total_rounds - 1)))

        level = min(1.0, base.level + 0.24 * t)
        profile = cls.from_level(level)

        profile.min_crossings = min(14, base.min_crossings + int(round(2.5 * t)))
        profile.max_crossings = min(
            14,
            max(profile.min_crossings + 1, base.max_crossings + int(round(2.0 * t))),
        )
        profile.stride_scale = round(base.stride_scale + 0.10 * t, 3)
        profile.target_play_time_s = int(base.target_play_time_s * (1.0 + 0.06 * t))
        profile.route_time_margin = round(base.route_time_margin + 0.04 * t, 3)
        profile.car_speed_mult = round(min(1.35, base.car_speed_mult + 0.14 * t), 3)
        profile.spawn_rate_mult = round(min(1.35, base.spawn_rate_mult + 0.22 * t), 3)
        profile.light_cycle_scale = round(max(0.72, base.light_cycle_scale - 0.14 * t), 3)
        profile.traffic_density = round(min(1.0, base.traffic_density + 0.18 * t), 3)
        profile.unpredictability = round(min(0.9, base.unpredictability + 0.15 * t), 3)
        profile.round_escalation = round(t, 3)
        profile.level = round(level, 3)
        return profile

    def to_dict(self) -> dict:
        return asdict(self)

    def with_adaptive_traffic(self, prior_session: dict | None) -> "DifficultyProfile":
        """
        Keep preset map size and route timer; tune traffic/lights from prior run only.

        When adaptive_map is on, map generation must not replace the menu preset with
        a bare from_level() profile (that inflates crossings and ignores route_time_margin).
        """
        if not prior_session:
            return self
        adapted = adaptive_difficulty(prior_session)
        return replace(
            self,
            level=adapted.level,
            car_speed_mult=adapted.car_speed_mult,
            spawn_rate_mult=adapted.spawn_rate_mult,
            light_cycle_scale=adapted.light_cycle_scale,
            traffic_density=min(
                1.0, (self.traffic_density + adapted.traffic_density) * 0.5
            ),
            unpredictability=adapted.unpredictability,
        )


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
