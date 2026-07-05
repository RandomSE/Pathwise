"""Resolution-aware menu layout for candidate and recruiter screens."""

from __future__ import annotations

from dataclasses import dataclass

from pathwise.geom import Rect

MENU_FOOTER_HEIGHT = 28


def _gap(height: int) -> int:
    return max(10, height // 52)


def _compact_scale(height: int) -> float:
    if height >= 960:
        return 1.0
    if height >= 720:
        return 0.88
    if height >= 600:
        return 0.66
    return max(0.58, height / 960)


def _fit_stack_heights(heights: list[int], *, max_height: int, gap: int) -> list[int]:
    total = sum(heights) + gap * max(0, len(heights) - 1)
    if total <= max_height:
        return heights
    scale = max_height / total
    fitted = [max(20, int(h * scale)) for h in heights]
    while sum(fitted) + gap * max(0, len(fitted) - 1) > max_height:
        tallest = max(range(len(fitted)), key=lambda i: fitted[i])
        if fitted[tallest] <= 20:
            break
        fitted[tallest] -= 1
    return fitted


def _scaled(value: int, height: int) -> int:
    return max(24, int(round(value * _compact_scale(height))))


def _centered_start(height: int, stack_height: int, *, top_margin: int) -> int:
    bottom_margin = MENU_FOOTER_HEIGHT + 8
    available = height - top_margin - bottom_margin
    if stack_height >= available:
        return top_margin
    return top_margin + (available - stack_height) // 2


def _stack_tops(start: int, heights: list[int], gap: int) -> list[int]:
    tops: list[int] = []
    y = start
    for index, block_h in enumerate(heights):
        tops.append(y)
        y += block_h
        if index < len(heights) - 1:
            y += gap
    return tops


@dataclass(frozen=True)
class CandidateLayout:
    title_top: int
    subtitle_top: int
    error_label_top: int
    seed_label_top: int
    seed_field_rect: Rect
    paste_rect: Rect
    play_rect: Rect
    configure_rect: Rect


@dataclass(frozen=True)
class RecruiterLayout:
    title_top: int
    subtitle_top: int
    rounds_label_top: int
    minus_rect: Rect
    plus_rect: Rect
    rounds_value_top: int
    rounds_hint_top: int | None
    difficulty_label_top: int
    preset_rects: dict[str, Rect]
    modifiers_label_top: int
    modifiers_hint_top: int
    stale_hint_top: int
    generated_label_top: int
    seed_display_rect: Rect
    copy_rect: Rect
    copy_feedback_top: int
    generate_rect: Rect
    start_rect: Rect
    back_rect: Rect


def layout_candidate(width: int, height: int) -> CandidateLayout:
    cx = width // 2
    gap = _gap(height)
    scale = _compact_scale(height)
    title_top = max(32, int(height * 0.065))
    subtitle_top = title_top + _scaled(52, height)
    error_h = _scaled(22, height)
    label_h = _scaled(20, height)
    seed_h = _scaled(44, height)
    play_h = _scaled(48, height)
    configure_h = _scaled(40, height)
    stack_h = error_h + gap + label_h + gap + seed_h + gap + play_h + gap + configure_h
    top_margin = subtitle_top + int(24 * scale)
    start = max(_centered_start(height, stack_h, top_margin=top_margin), top_margin)
    tops = _stack_tops(start, [error_h, label_h, seed_h, play_h, configure_h], gap)
    seed_top = tops[2]
    return CandidateLayout(
        title_top=title_top,
        subtitle_top=subtitle_top,
        error_label_top=tops[0] + error_h // 2,
        seed_label_top=tops[1] + label_h // 2,
        seed_field_rect=Rect(cx - 210, seed_top, 268, seed_h),
        paste_rect=Rect(cx + 70, seed_top, 80, seed_h),
        play_rect=Rect(cx - 120, tops[3], 240, play_h),
        configure_rect=Rect(cx - 120, tops[4], 240, configure_h),
    )


def layout_recruiter(
    width: int,
    height: int,
    *,
    num_rounds: int,
    show_stale_hint: bool,
) -> RecruiterLayout:
    cx = width // 2
    gap = _gap(height)
    title_top = max(32, int(height * 0.065))
    subtitle_top = title_top + _scaled(52, height)
    rounds_label_h = _scaled(18, height)
    rounds_h = _scaled(40, height)
    rounds_hint_h = _scaled(18, height) if num_rounds > 1 else 0
    difficulty_label_h = _scaled(18, height)
    preset_h = _scaled(48, height)
    modifiers_label_h = _scaled(16, height)
    modifiers_hint_h = _scaled(16, height)
    stale_h = _scaled(18, height) if show_stale_hint else 0
    generated_label_h = _scaled(16, height)
    seed_h = _scaled(34, height)
    action_h = _scaled(34, height)
    start_h = _scaled(38, height)
    back_h = _scaled(30, height)

    heights = [
        rounds_label_h,
        rounds_h,
        rounds_hint_h,
        difficulty_label_h,
        preset_h,
        preset_h,
        preset_h,
        modifiers_label_h,
        modifiers_hint_h,
        stale_h,
        generated_label_h,
        seed_h,
        action_h,
        start_h,
        back_h,
    ]
    heights = [h for h in heights if h > 0]
    top_margin = subtitle_top + int(20 * _compact_scale(height))
    max_stack = height - top_margin - MENU_FOOTER_HEIGHT - 8
    heights = _fit_stack_heights(heights, max_height=max_stack, gap=gap)
    stack_h = sum(heights) + gap * (len(heights) - 1)
    start = max(_centered_start(height, stack_h, top_margin=top_margin), top_margin)
    tops = _stack_tops(start, heights, gap)

    index = 0
    rounds_label_top = tops[index] + rounds_label_h // 2
    index += 1
    rounds_top = tops[index]
    index += 1
    rounds_hint_top: int | None = None
    if num_rounds > 1:
        rounds_hint_top = tops[index] + rounds_hint_h // 2
        index += 1
    difficulty_top = tops[index] + difficulty_label_h // 2
    index += 1

    preset_rects: dict[str, Rect] = {}
    for preset_id in ("easy", "normal", "hard"):
        preset_rects[preset_id] = Rect(cx - 200, tops[index], 400, preset_h)
        index += 1

    modifiers_top = tops[index] + modifiers_label_h // 2
    index += 1
    modifiers_hint_top = tops[index] + modifiers_hint_h // 2
    index += 1

    stale_top = 0
    if show_stale_hint:
        stale_top = tops[index] + stale_h // 2
        index += 1

    generated_top = tops[index] + generated_label_h // 2
    index += 1
    seed_top = tops[index]
    index += 1
    generate_top = tops[index]
    index += 1
    start_top = tops[index]
    index += 1
    back_top = tops[index]

    return RecruiterLayout(
        title_top=title_top,
        subtitle_top=subtitle_top,
        rounds_label_top=rounds_label_top,
        minus_rect=Rect(cx - 120, rounds_top, 44, rounds_h),
        plus_rect=Rect(cx + 76, rounds_top, 44, rounds_h),
        rounds_value_top=rounds_top + rounds_h // 2,
        rounds_hint_top=rounds_hint_top,
        difficulty_label_top=difficulty_top,
        preset_rects=preset_rects,
        modifiers_label_top=modifiers_top,
        modifiers_hint_top=modifiers_hint_top,
        stale_hint_top=stale_top,
        generated_label_top=generated_top,
        seed_display_rect=Rect(cx - 210, seed_top, 268, seed_h),
        copy_rect=Rect(cx + 70, seed_top, 80, seed_h),
        copy_feedback_top=seed_top - 6,
        generate_rect=Rect(cx - 120, generate_top, 240, action_h),
        start_rect=Rect(cx - 120, start_top, 240, start_h),
        back_rect=Rect(cx - 120, back_top, 240, back_h),
    )


def layout_vertical_spans(layout: CandidateLayout | RecruiterLayout) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    if isinstance(layout, CandidateLayout):
        spans.extend(
            [
                (layout.title_top - 20, layout.title_top + 20),
                (layout.subtitle_top - 14, layout.subtitle_top + 14),
                (layout.error_label_top - 11, layout.error_label_top + 11),
                (layout.seed_label_top - 11, layout.seed_label_top + 11),
                (layout.seed_field_rect.top, layout.seed_field_rect.bottom),
                (layout.play_rect.top, layout.play_rect.bottom),
                (layout.configure_rect.top, layout.configure_rect.bottom),
            ]
        )
        return spans

    spans.append((layout.title_top - 20, layout.title_top + 20))
    spans.append((layout.subtitle_top - 14, layout.subtitle_top + 14))
    spans.append((layout.rounds_label_top - 10, layout.rounds_label_top + 10))
    spans.append((layout.minus_rect.top, layout.minus_rect.bottom))
    if layout.rounds_hint_top is not None:
        spans.append((layout.rounds_hint_top - 9, layout.rounds_hint_top + 9))
    spans.append((layout.difficulty_label_top - 10, layout.difficulty_label_top + 10))
    spans.extend((rect.top, rect.bottom) for rect in layout.preset_rects.values())
    spans.append((layout.modifiers_label_top - 9, layout.modifiers_label_top + 9))
    spans.append((layout.modifiers_hint_top - 9, layout.modifiers_hint_top + 9))
    if layout.stale_hint_top > 0:
        spans.append((layout.stale_hint_top - 9, layout.stale_hint_top + 9))
    spans.append((layout.generated_label_top - 9, layout.generated_label_top + 9))
    spans.extend(
        [
            (layout.seed_display_rect.top, layout.seed_display_rect.bottom),
            (layout.generate_rect.top, layout.generate_rect.bottom),
            (layout.start_rect.top, layout.start_rect.bottom),
            (layout.back_rect.top, layout.back_rect.bottom),
        ]
    )
    return spans


def layouts_do_not_overlap(spans: list[tuple[int, int]], *, window_height: int) -> bool:
    ordered = sorted(spans, key=lambda span: span[0])
    for (_, bottom_a), (top_b, _) in zip(ordered, ordered[1:]):
        if bottom_a > top_b:
            return False
    if ordered and ordered[-1][1] > window_height - MENU_FOOTER_HEIGHT:
        return False
    return True
