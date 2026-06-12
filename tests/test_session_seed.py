import os
import random
import unittest

from pathwise.session_seed import (
    SEED_SOURCE_ENV,
    SEED_SOURCE_MENU,
    SEED_SOURCE_RANDOM,
    parse_seed_value,
    pathwise_seed_from_env,
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
