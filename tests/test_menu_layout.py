"""Layout overlap checks for menu screens at common resolutions."""

import unittest

from pathwise.menu_layout import (
    layout_candidate,
    layout_recruiter,
    layout_recruiter_auth,
    layout_recruiter_register,
    layout_vertical_spans,
    layouts_do_not_overlap,
)


class TestMenuLayout(unittest.TestCase):
    def _assert_clean(self, width: int, height: int) -> None:
        candidate = layout_candidate(width, height)
        self.assertTrue(
            layouts_do_not_overlap(layout_vertical_spans(candidate), window_height=height)
        )
        recruiter = layout_recruiter(width, height, num_rounds=1, show_stale_hint=False)
        self.assertTrue(
            layouts_do_not_overlap(layout_vertical_spans(recruiter), window_height=height)
        )
        recruiter_stale = layout_recruiter(width, height, num_rounds=3, show_stale_hint=True)
        self.assertTrue(
            layouts_do_not_overlap(layout_vertical_spans(recruiter_stale), window_height=height)
        )
        login = layout_recruiter_auth(width, height)
        self.assertTrue(
            layouts_do_not_overlap(layout_vertical_spans(login), window_height=height)
        )
        register = layout_recruiter_register(width, height)
        self.assertTrue(
            layouts_do_not_overlap(layout_vertical_spans(register), window_height=height)
        )

    def test_windowed_resolution(self):
        self._assert_clean(800, 600)

    def test_full_hd_resolution(self):
        self._assert_clean(1920, 1080)

    def test_candidate_name_row_is_below_seed_and_overlap_clean(self):
        for width, height in ((800, 600), (1920, 1080)):
            layout = layout_candidate(width, height, show_name=True)
            self.assertGreater(layout.name_field_rect.height, 0)
            self.assertGreater(layout.name_label_top, 0)
            self.assertGreaterEqual(layout.name_field_rect.top, layout.seed_field_rect.bottom)
            self.assertTrue(
                layouts_do_not_overlap(layout_vertical_spans(layout), window_height=height)
            )

    def test_candidate_name_row_omitted_when_hidden(self):
        for width, height in ((800, 600), (1920, 1080)):
            hidden = layout_candidate(width, height, show_name=False)
            shown = layout_candidate(width, height, show_name=True)
            self.assertEqual(hidden.name_field_rect.height, 0)
            self.assertLess(hidden.play_rect.top, shown.play_rect.top)
            self.assertTrue(
                layouts_do_not_overlap(layout_vertical_spans(hidden), window_height=height)
            )

    def test_copy_aligns_with_seed_row(self):
        layout = layout_recruiter(800, 600, num_rounds=1, show_stale_hint=False)
        self.assertEqual(layout.copy_rect.top, layout.seed_display_rect.top)
        self.assertEqual(layout.copy_rect.bottom, layout.seed_display_rect.bottom)


if __name__ == "__main__":
    unittest.main()
