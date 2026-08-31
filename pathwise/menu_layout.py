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
    fitted = [max(14, int(h * scale)) for h in heights]
    while sum(fitted) + gap * max(0, len(fitted) - 1) > max_height:
        tallest = max(range(len(fitted)), key=lambda i: fitted[i])
        if fitted[tallest] <= 14:
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
    name_label_top: int
    name_field_rect: Rect
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
    modifier_toggle_rects: dict[str, Rect]
    modifier_action_rects: dict[str, Rect]
    modifier_info_label_top: int
    modifier_explain_rect: Rect
    stale_hint_top: int
    generated_label_top: int
    seed_display_rect: Rect
    copy_rect: Rect
    copy_feedback_top: int
    generate_error_top: int
    generate_rect: Rect
    start_rect: Rect
    back_rect: Rect


@dataclass(frozen=True)
class RecruiterAuthLayout:
    title_top: int
    subtitle_top: int
    error_label_top: int
    email_label_top: int
    email_field_rect: Rect
    password_label_top: int
    password_field_rect: Rect
    login_rect: Rect
    register_rect: Rect
    back_rect: Rect


@dataclass(frozen=True)
class RecruiterRegisterLayout:
    title_top: int
    subtitle_top: int
    error_label_top: int
    email_label_top: int
    email_field_rect: Rect
    password_label_top: int
    password_field_rect: Rect
    confirm_label_top: int
    confirm_field_rect: Rect
    create_rect: Rect
    back_rect: Rect


def layout_candidate(
    width: int,
    height: int,
    *,
    show_name: bool = True,
) -> CandidateLayout:
    cx = width // 2
    gap = _gap(height)
    scale = _compact_scale(height)
    title_top = max(32, int(height * 0.065))
    subtitle_top = title_top + _scaled(52, height)
    error_h = _scaled(22, height)
    label_h = _scaled(20, height)
    seed_h = _scaled(44, height)
    name_h = _scaled(40, height)
    play_h = _scaled(48, height)
    configure_h = _scaled(40, height)
    top_margin = subtitle_top + int(24 * scale)
    bottom_margin = MENU_FOOTER_HEIGHT + 8
    max_height = max(80, height - top_margin - bottom_margin)
    blocks: list[int] = [error_h, label_h, seed_h]
    if show_name:
        blocks.extend([label_h, name_h])
    blocks.extend([play_h, configure_h])
    block_heights = _fit_stack_heights(blocks, max_height=max_height, gap=gap)
    stack_h = sum(block_heights) + gap * max(0, len(block_heights) - 1)
    start = max(_centered_start(height, stack_h, top_margin=top_margin), top_margin)
    tops = _stack_tops(start, block_heights, gap)
    seed_top = tops[2]
    if show_name:
        name_label_top = tops[3] + block_heights[3] // 2
        name_top = tops[4]
        name_h_fit = block_heights[4]
        play_top = tops[5]
        configure_top = tops[6]
        play_h_fit = block_heights[5]
        configure_h_fit = block_heights[6]
    else:
        name_label_top = 0
        name_top = 0
        name_h_fit = 0
        play_top = tops[3]
        configure_top = tops[4]
        play_h_fit = block_heights[3]
        configure_h_fit = block_heights[4]
    return CandidateLayout(
        title_top=title_top,
        subtitle_top=subtitle_top,
        error_label_top=tops[0] + block_heights[0] // 2,
        seed_label_top=tops[1] + block_heights[1] // 2,
        seed_field_rect=Rect(cx - 210, seed_top, 268, block_heights[2]),
        paste_rect=Rect(cx + 70, seed_top, 80, block_heights[2]),
        name_label_top=name_label_top,
        name_field_rect=Rect(cx - 210, name_top, 420 if show_name else 0, name_h_fit),
        play_rect=Rect(cx - 120, play_top, 240, play_h_fit),
        configure_rect=Rect(cx - 120, configure_top, 240, configure_h_fit),
    )


def layout_recruiter(
    width: int,
    height: int,
    *,
    num_rounds: int,
    show_stale_hint: bool,
    modifier_ids: tuple[str, ...] = (),
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
    toggle_h = _scaled(34, height)
    stale_h = _scaled(18, height) if show_stale_hint else 0
    generated_label_h = _scaled(16, height)
    seed_h = _scaled(34, height)
    error_h = _scaled(16, height)
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
    ]
    heights.extend([toggle_h] * max(1, len(modifier_ids)))
    heights.extend([stale_h, generated_label_h, seed_h, error_h, action_h, start_h, back_h])
    heights = [h for h in heights if h > 0]
    top_margin = subtitle_top + int(28 * _compact_scale(height))
    max_stack = height - top_margin - MENU_FOOTER_HEIGHT - 8
    # Prefer a slightly tighter gap when the stack is dense.
    pack_gap = gap if sum(heights) + gap * (len(heights) - 1) <= max_stack else max(6, gap - 2)
    heights = _fit_stack_heights(heights, max_height=max_stack, gap=pack_gap)
    stack_h = sum(heights) + pack_gap * (len(heights) - 1)
    start = max(_centered_start(height, stack_h, top_margin=top_margin), top_margin)
    tops = _stack_tops(start, heights, pack_gap)

    index = 0
    rounds_label_top = tops[index] + heights[index] // 2
    index += 1
    rounds_top = tops[index]
    fitted_rounds_h = heights[index]
    index += 1
    rounds_hint_top: int | None = None
    if num_rounds > 1:
        rounds_hint_top = tops[index] + heights[index] // 2
        index += 1
    difficulty_top = tops[index] + heights[index] // 2
    index += 1

    preset_rects: dict[str, Rect] = {}
    for preset_id in ("easy", "normal", "hard"):
        preset_rects[preset_id] = Rect(cx - 200, tops[index], 400, heights[index])
        index += 1

    modifiers_top = tops[index] + heights[index] // 2
    index += 1

    modifier_toggle_rects: dict[str, Rect] = {}
    modifier_action_rects: dict[str, Rect] = {}
    toggle_ids = modifier_ids or ("rainy_roads",)
    first_toggle_top = tops[index] if toggle_ids else modifiers_top
    action_w = 44
    for modifier_id in toggle_ids:
        row_top = tops[index]
        row_h = heights[index]
        modifier_toggle_rects[modifier_id] = Rect(
            cx - 200, row_top, 400 - action_w - 8, row_h
        )
        modifier_action_rects[modifier_id] = Rect(
            cx + 200 - action_w, row_top, action_w, row_h
        )
        index += 1

    stale_top = 0
    if show_stale_hint:
        stale_top = tops[index] + heights[index] // 2
        index += 1

    generated_top = tops[index] + heights[index] // 2
    index += 1
    seed_top = tops[index]
    fitted_seed_h = heights[index]
    index += 1
    generate_error_top = tops[index] + heights[index] // 2
    index += 1
    generate_top = tops[index]
    fitted_action_h = heights[index]
    index += 1
    start_top = tops[index]
    fitted_start_h = heights[index]
    index += 1
    back_top = tops[index]
    fitted_back_h = heights[index]

    # Side panel: ~4x the old 400x40 explain slot, right of the centered controls.
    panel_w = max(360, min(520, width // 3 + 40))
    panel_h = max(180, min(280, int(height * 0.32)))
    panel_left = width - panel_w - 24
    # Keep panel clear of the centered 400px control column.
    min_left = cx + 200 + 24
    if panel_left < min_left:
        panel_left = min_left
        panel_w = max(280, width - panel_left - 16)
    panel_top = max(subtitle_top + 8, first_toggle_top - 28)
    if panel_top + panel_h > height - MENU_FOOTER_HEIGHT - 8:
        panel_top = max(8, height - MENU_FOOTER_HEIGHT - 8 - panel_h)
    info_label_top = panel_top
    explain_rect = Rect(panel_left, panel_top + 28, panel_w, panel_h - 28)

    return RecruiterLayout(
        title_top=title_top,
        subtitle_top=subtitle_top,
        rounds_label_top=rounds_label_top,
        minus_rect=Rect(cx - 120, rounds_top, 44, fitted_rounds_h),
        plus_rect=Rect(cx + 76, rounds_top, 44, fitted_rounds_h),
        rounds_value_top=rounds_top + fitted_rounds_h // 2,
        rounds_hint_top=rounds_hint_top,
        difficulty_label_top=difficulty_top,
        preset_rects=preset_rects,
        modifiers_label_top=modifiers_top,
        modifier_toggle_rects=modifier_toggle_rects,
        modifier_action_rects=modifier_action_rects,
        modifier_info_label_top=info_label_top,
        modifier_explain_rect=explain_rect,
        stale_hint_top=stale_top,
        generated_label_top=generated_top,
        seed_display_rect=Rect(cx - 210, seed_top, 268, fitted_seed_h),
        copy_rect=Rect(cx + 70, seed_top, 80, fitted_seed_h),
        copy_feedback_top=seed_top - 6,
        generate_error_top=generate_error_top,
        generate_rect=Rect(cx - 120, generate_top, 240, fitted_action_h),
        start_rect=Rect(cx - 120, start_top, 240, fitted_start_h),
        back_rect=Rect(cx - 120, back_top, 240, fitted_back_h),
    )


def _auth_field_width(width: int) -> int:
    return min(420, max(280, width // 2 + 40))


def layout_recruiter_auth(width: int, height: int) -> RecruiterAuthLayout:
    cx = width // 2
    gap = _gap(height)
    scale = _compact_scale(height)
    title_top = max(32, int(height * 0.065))
    subtitle_top = title_top + max(36, _scaled(52, height))
    error_h = _scaled(22, height)
    label_h = _scaled(18, height)
    field_h = _scaled(40, height)
    login_h = _scaled(44, height)
    register_h = _scaled(38, height)
    back_h = _scaled(32, height)
    heights = [error_h, label_h, field_h, label_h, field_h, login_h, register_h, back_h]
    top_margin = subtitle_top + int(24 * scale)
    max_stack = height - top_margin - MENU_FOOTER_HEIGHT - 8
    pack_gap = gap if sum(heights) + gap * (len(heights) - 1) <= max_stack else max(6, gap - 2)
    heights = _fit_stack_heights(heights, max_height=max_stack, gap=pack_gap)
    stack_h = sum(heights) + pack_gap * (len(heights) - 1)
    start = max(_centered_start(height, stack_h, top_margin=top_margin), top_margin)
    tops = _stack_tops(start, heights, pack_gap)
    field_w = _auth_field_width(width)
    left = cx - field_w // 2
    return RecruiterAuthLayout(
        title_top=title_top,
        subtitle_top=subtitle_top,
        error_label_top=tops[0] + heights[0] // 2,
        email_label_top=tops[1] + heights[1] // 2,
        email_field_rect=Rect(left, tops[2], field_w, heights[2]),
        password_label_top=tops[3] + heights[3] // 2,
        password_field_rect=Rect(left, tops[4], field_w, heights[4]),
        login_rect=Rect(cx - 120, tops[5], 240, heights[5]),
        register_rect=Rect(cx - 120, tops[6], 240, heights[6]),
        back_rect=Rect(cx - 120, tops[7], 240, heights[7]),
    )


def layout_recruiter_register(width: int, height: int) -> RecruiterRegisterLayout:
    cx = width // 2
    gap = _gap(height)
    scale = _compact_scale(height)
    title_top = max(28, int(height * 0.05))
    subtitle_top = title_top + max(34, _scaled(52, height))
    error_h = _scaled(20, height)
    label_h = _scaled(16, height)
    field_h = _scaled(36, height)
    create_h = _scaled(42, height)
    back_h = _scaled(30, height)
    heights = [
        error_h,
        label_h,
        field_h,
        label_h,
        field_h,
        label_h,
        field_h,
        create_h,
        back_h,
    ]
    top_margin = subtitle_top + int(20 * scale)
    max_stack = height - top_margin - MENU_FOOTER_HEIGHT - 8
    pack_gap = gap if sum(heights) + gap * (len(heights) - 1) <= max_stack else max(6, gap - 2)
    heights = _fit_stack_heights(heights, max_height=max_stack, gap=pack_gap)
    stack_h = sum(heights) + pack_gap * (len(heights) - 1)
    start = max(_centered_start(height, stack_h, top_margin=top_margin), top_margin)
    tops = _stack_tops(start, heights, pack_gap)
    field_w = _auth_field_width(width)
    left = cx - field_w // 2
    return RecruiterRegisterLayout(
        title_top=title_top,
        subtitle_top=subtitle_top,
        error_label_top=tops[0] + heights[0] // 2,
        email_label_top=tops[1] + heights[1] // 2,
        email_field_rect=Rect(left, tops[2], field_w, heights[2]),
        password_label_top=tops[3] + heights[3] // 2,
        password_field_rect=Rect(left, tops[4], field_w, heights[4]),
        confirm_label_top=tops[5] + heights[5] // 2,
        confirm_field_rect=Rect(left, tops[6], field_w, heights[6]),
        create_rect=Rect(cx - 120, tops[7], 240, heights[7]),
        back_rect=Rect(cx - 120, tops[8], 240, heights[8]),
    )


def layout_vertical_spans(
    layout: CandidateLayout | RecruiterLayout | RecruiterAuthLayout | RecruiterRegisterLayout,
) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    if isinstance(layout, CandidateLayout):
        spans.extend(
            [
                (layout.title_top - 20, layout.title_top + 20),
                (layout.subtitle_top - 14, layout.subtitle_top + 14),
                (layout.error_label_top - 11, layout.error_label_top + 11),
                (layout.seed_label_top - 11, layout.seed_label_top + 11),
                (layout.seed_field_rect.top, layout.seed_field_rect.bottom),
            ]
        )
        if layout.name_field_rect.height > 0:
            spans.extend(
                [
                    (layout.name_label_top - 11, layout.name_label_top + 11),
                    (layout.name_field_rect.top, layout.name_field_rect.bottom),
                ]
            )
        spans.extend(
            [
                (layout.play_rect.top, layout.play_rect.bottom),
                (layout.configure_rect.top, layout.configure_rect.bottom),
            ]
        )
        return spans

    if isinstance(layout, RecruiterAuthLayout):
        spans.extend(
            [
                (layout.title_top - 20, layout.title_top + 20),
                (layout.subtitle_top - 14, layout.subtitle_top + 14),
                (layout.error_label_top - 11, layout.error_label_top + 11),
                (layout.email_label_top - 9, layout.email_label_top + 9),
                (layout.email_field_rect.top, layout.email_field_rect.bottom),
                (layout.password_label_top - 9, layout.password_label_top + 9),
                (layout.password_field_rect.top, layout.password_field_rect.bottom),
                (layout.login_rect.top, layout.login_rect.bottom),
                (layout.register_rect.top, layout.register_rect.bottom),
                (layout.back_rect.top, layout.back_rect.bottom),
            ]
        )
        return spans

    if isinstance(layout, RecruiterRegisterLayout):
        spans.extend(
            [
                (layout.title_top - 18, layout.title_top + 18),
                (layout.subtitle_top - 12, layout.subtitle_top + 12),
                (layout.error_label_top - 10, layout.error_label_top + 10),
                (layout.email_label_top - 8, layout.email_label_top + 8),
                (layout.email_field_rect.top, layout.email_field_rect.bottom),
                (layout.password_label_top - 8, layout.password_label_top + 8),
                (layout.password_field_rect.top, layout.password_field_rect.bottom),
                (layout.confirm_label_top - 8, layout.confirm_label_top + 8),
                (layout.confirm_field_rect.top, layout.confirm_field_rect.bottom),
                (layout.create_rect.top, layout.create_rect.bottom),
                (layout.back_rect.top, layout.back_rect.bottom),
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
    spans.extend((rect.top, rect.bottom) for rect in layout.modifier_toggle_rects.values())
    # Action +/- buttons share the toggle row; do not double-count vertical spans.
    if layout.stale_hint_top > 0:
        spans.append((layout.stale_hint_top - 9, layout.stale_hint_top + 9))
    spans.append((layout.generated_label_top - 9, layout.generated_label_top + 9))
    spans.extend(
        [
            (layout.seed_display_rect.top, layout.seed_display_rect.bottom),
            (layout.generate_error_top - 8, layout.generate_error_top + 8),
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
