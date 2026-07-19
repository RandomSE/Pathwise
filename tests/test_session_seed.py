import os
import random
import unittest

from pathwise.session_seed import (
    SEED_SOURCE_ENV,
    SEED_SOURCE_MENU,
    SEED_SOURCE_RANDOM,
    classify_seed_input,
    decode_recruiter_seed,
    encode_recruiter_seed,
    parse_seed_value,
    pathwise_seed_from_env,
    resolve_candidate_play_seed,
    resolve_session_seed,
)


class TestParseSeedValue(unittest.TestCase):
    def test_none_and_empty(self):
        self.assertIsNone(parse_seed_value(None))
        self.assertIsNone(parse_seed_value(""))
        self.assertIsNone(parse_seed_value("   "))

    def test_digits(self):
        self.assertEqual(parse_seed_value("12345"), 12345)

    def test_rejects_non_digits(self):
        self.assertIsNone(parse_seed_value("12abc"))

    def test_wraps_large_values(self):
        huge = str(2**31 + 99)
        self.assertEqual(parse_seed_value(huge), 99)


class TestResolveSessionSeed(unittest.TestCase):
    def setUp(self):
        self._env = os.environ.pop("PATHWISE_SEED", None)

    def tearDown(self):
        if self._env is None:
            os.environ.pop("PATHWISE_SEED", None)
        else:
            os.environ["PATHWISE_SEED"] = self._env

    def test_menu_overrides_env(self):
        os.environ["PATHWISE_SEED"] = "999"
        seed, source, adaptive = resolve_session_seed(42)
        self.assertEqual((seed, source, adaptive), (42, SEED_SOURCE_MENU, False))

    def test_env_when_menu_empty(self):
        os.environ["PATHWISE_SEED"] = "777"
        seed, source, adaptive = resolve_session_seed(None)
        self.assertEqual((seed, source, adaptive), (777, SEED_SOURCE_ENV, False))

    def test_random_when_unset(self):
        rng = random.Random(0)
        expected = rng.randint(0, 2**31 - 1)
        seed, source, adaptive = resolve_session_seed(None, rng=random.Random(0))
        self.assertEqual(source, SEED_SOURCE_RANDOM)
        self.assertTrue(adaptive)
        self.assertEqual(seed, expected)

    def test_pathwise_seed_from_env(self):
        os.environ["PATHWISE_SEED"] = "555"
        self.assertEqual(pathwise_seed_from_env(), 555)


class TestClassifySeedInput(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(classify_seed_input(""), "empty")
        self.assertEqual(classify_seed_input("  \t "), "empty")

    def test_valid_plain_seed(self):
        self.assertEqual(classify_seed_input("0"), "valid")
        self.assertEqual(classify_seed_input("42"), "valid")

    def test_valid_recruiter_encoded(self):
        encoded = encode_recruiter_seed(123456, "normal", 3)
        self.assertEqual(classify_seed_input(encoded), "valid")

    def test_invalid_malformed_recruiter_length(self):
        self.assertEqual(classify_seed_input("1234567890"), "invalid")

    def test_invalid(self):
        self.assertEqual(classify_seed_input("x"), "invalid")
        self.assertEqual(classify_seed_input("12a"), "invalid")


class TestResolveCandidatePlaySeed(unittest.TestCase):
    def setUp(self):
        self._env = os.environ.pop("PATHWISE_SEED", None)

    def tearDown(self):
        if self._env is None:
            os.environ.pop("PATHWISE_SEED", None)
        else:
            os.environ["PATHWISE_SEED"] = self._env

    def test_uses_menu_when_valid(self):
        seed, source, adaptive = resolve_candidate_play_seed(42)
        self.assertEqual((seed, source, adaptive), (42, SEED_SOURCE_MENU, False))

    def test_random_when_menu_empty_ignores_env(self):
        os.environ["PATHWISE_SEED"] = "777"
        rng = random.Random(0)
        expected = rng.randint(0, 2**31 - 1)
        seed, source, adaptive = resolve_candidate_play_seed(None, rng=random.Random(0))
        self.assertEqual(source, SEED_SOURCE_RANDOM)
        self.assertTrue(adaptive)
        self.assertEqual(seed, expected)
        self.assertNotEqual(seed, 777)


class TestRecruiterSeedEncoding(unittest.TestCase):
    def test_round_trip(self):
        encoded = encode_recruiter_seed(123456, "normal", 3)
        self.assertEqual(len(encoded), 13)
        payload = decode_recruiter_seed(encoded)
        self.assertIsNotNone(payload)
        self.assertEqual(payload.map_seed, 123456)
        self.assertEqual(payload.preset, "normal")
        self.assertEqual(payload.num_rounds, 3)

    def test_v8_round_trip(self):
        encoded = encode_recruiter_seed(123456, "normal", 3, version=8)
        self.assertEqual(len(encoded), 10)
        payload = decode_recruiter_seed(encoded)
        self.assertIsNotNone(payload)
        self.assertEqual(payload.map_seed, 123456)

    def test_decode_rejects_plain_short_seed(self):
        self.assertIsNone(decode_recruiter_seed("42"))
        self.assertIsNone(decode_recruiter_seed("1234567890"))

    def test_encode_wraps_large_map_seed(self):
        encoded = encode_recruiter_seed(99_999_999, "hard", 5)
        payload = decode_recruiter_seed(encoded)
        self.assertEqual(payload.map_seed, 99_999_999 % 1_000_000)
        self.assertEqual(payload.preset, "hard")
        self.assertEqual(payload.num_rounds, 5)
