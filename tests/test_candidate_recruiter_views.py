"""Pure helpers for candidate home and recruiter config views."""

import unittest

from pathwise.pre_game import (
    build_candidate_session_config,
    build_recruiter_session_config,
    candidate_name_field_visible,
    candidate_play_button_label,
    candidate_play_disabled,
    normalize_pasted_seed,
    recruiter_copy_enabled,
    recruiter_seed_stale,
    recruiter_settings_fingerprint,
)
from pathwise.session_seed import classify_seed_input, encode_recruiter_seed


class TestClassifySeedInput(unittest.TestCase):
    def test_empty_and_whitespace(self):
        self.assertEqual(classify_seed_input(""), "empty")
        self.assertEqual(classify_seed_input("   "), "empty")

    def test_valid_digits(self):
        self.assertEqual(classify_seed_input("12345"), "valid")
        self.assertEqual(classify_seed_input(" 42 "), "valid")

    def test_invalid_non_empty(self):
        self.assertEqual(classify_seed_input("12abc"), "invalid")
        self.assertEqual(classify_seed_input("abc"), "invalid")
        self.assertEqual(classify_seed_input("12-34"), "invalid")


class TestCandidatePlayHelpers(unittest.TestCase):
    def test_play_button_label(self):
        self.assertEqual(candidate_play_button_label("empty"), "Play random seed")
        self.assertEqual(candidate_play_button_label("invalid"), "Play random seed")
        self.assertEqual(candidate_play_button_label("valid"), "Play set seed")

    def test_name_field_hidden_until_seed_has_chars(self):
        self.assertFalse(candidate_name_field_visible(""))
        self.assertFalse(candidate_name_field_visible("   "))
        self.assertTrue(candidate_name_field_visible("42"))
        self.assertTrue(candidate_name_field_visible("12x"))
        self.assertTrue(candidate_name_field_visible(encode_recruiter_seed(1, "normal", 1)))

    def test_play_disabled_when_invalid_non_empty(self):
        self.assertFalse(candidate_play_disabled("empty", name_text="", recruiter_logged_in=False))
        self.assertTrue(
            candidate_play_disabled("valid", name_text="", recruiter_logged_in=False)
        )
        self.assertTrue(candidate_play_disabled("invalid", name_text="Ada", recruiter_logged_in=False))

    def test_play_enabled_with_name_on_valid_seed(self):
        self.assertFalse(
            candidate_play_disabled("valid", name_text="Ada Lovelace", recruiter_logged_in=False)
        )

    def test_random_empty_seed_needs_no_name(self):
        self.assertFalse(
            candidate_play_disabled("empty", name_text="", recruiter_logged_in=False)
        )
        self.assertFalse(
            candidate_play_disabled("empty", name_text="   ", recruiter_logged_in=False)
        )

    def test_logged_in_recruiter_needs_no_name(self):
        self.assertFalse(
            candidate_play_disabled("valid", name_text="", recruiter_logged_in=True)
        )

    def test_whitespace_only_name_blocks_valid_seed(self):
        self.assertTrue(
            candidate_play_disabled("valid", name_text="   ", recruiter_logged_in=False)
        )

    def test_candidate_session_config_quick_play(self):
        cfg = build_candidate_session_config("")
        self.assertEqual(cfg.preset, "normal")
        self.assertEqual(cfg.num_rounds, 1)
        self.assertIsNone(cfg.seed)
        self.assertIsNone(cfg.recruiter_seed_code)
        self.assertIsNone(cfg.candidate_label)

        cfg = build_candidate_session_config("99", candidate_label="Ada")
        self.assertEqual(cfg.preset, "normal")
        self.assertEqual(cfg.num_rounds, 1)
        self.assertEqual(cfg.seed, 99)
        self.assertIsNone(cfg.recruiter_seed_code)
        self.assertEqual(cfg.candidate_label, "Ada")

    def test_candidate_session_config_decodes_recruiter_seed(self):
        encoded = encode_recruiter_seed(424242, "hard", 4)
        cfg = build_candidate_session_config(encoded, candidate_label="Ada")
        self.assertEqual(cfg.preset, "hard")
        self.assertEqual(cfg.num_rounds, 4)
        self.assertEqual(cfg.seed, 424242)
        self.assertEqual(cfg.recruiter_seed_code, encoded)
        self.assertEqual(cfg.candidate_label, "Ada")

    def test_normalize_pasted_seed_strips_whitespace(self):
        self.assertEqual(normalize_pasted_seed("  12 34 \n"), "1234")

    def test_recruiter_copy_enabled(self):
        self.assertFalse(recruiter_copy_enabled(""))
        self.assertFalse(recruiter_copy_enabled("   "))
        self.assertTrue(recruiter_copy_enabled("8123456789"))

    def test_recruiter_seed_stale(self):
        fp = recruiter_settings_fingerprint("normal", 2)
        encoded = encode_recruiter_seed(1, "normal", 2)
        self.assertFalse(
            recruiter_seed_stale(
                encoded,
                current_fingerprint=fp,
                generated_fingerprint=fp,
            )
        )
        self.assertTrue(
            recruiter_seed_stale(
                encoded,
                current_fingerprint=recruiter_settings_fingerprint("hard", 2),
                generated_fingerprint=fp,
            )
        )


class TestRecruiterSessionConfig(unittest.TestCase):
    def test_build_from_generated_seed(self):
        encoded = encode_recruiter_seed(100, "easy", 2)
        cfg = build_recruiter_session_config(
            encoded,
            preset="normal",
            num_rounds=1,
            candidate_label="ok@example.com",
        )
        self.assertEqual(cfg.preset, "easy")
        self.assertEqual(cfg.num_rounds, 2)
        self.assertEqual(cfg.seed, 100)
        self.assertEqual(cfg.recruiter_seed_code, encoded)
        self.assertEqual(cfg.candidate_label, "ok@example.com")

    def test_build_requires_generated_seed(self):
        with self.assertRaises(ValueError):
            build_recruiter_session_config("", preset="normal", num_rounds=1)


if __name__ == "__main__":
    unittest.main()
