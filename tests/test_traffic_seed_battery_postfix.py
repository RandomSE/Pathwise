import json
import os
import unittest

import pytest

from analytics.replay_traffic_audit import (
    CUSTOM_ZERO_KINDS,
    DIAG_ZERO_KINDS,
    REQUIRED_ZERO_KINDS,
    run_traffic_audit,
)
from tests.fixtures.traffic_seed_battery import BASELINE_SEEDS, SPECTATE_FRAMES_60S

pytestmark = pytest.mark.skipif(
    os.environ.get("PATHWISE_RUN_SLOW_BATTERY") != "1",
    reason="slow battery: set PATHWISE_RUN_SLOW_BATTERY=1",
)


@unittest.skipUnless(
    os.environ.get("PATHWISE_RUN_SLOW_BATTERY") == "1",
    "slow battery: set PATHWISE_RUN_SLOW_BATTERY=1",
)
class TestTrafficSeedBatteryPostfix(unittest.TestCase):
    def test_all_seeds_zero_anomalies_60s(self):
        for seed in BASELINE_SEEDS:
            with self.subTest(seed=seed):
                result = run_traffic_audit(seed=seed, seconds=SPECTATE_FRAMES_60S / 60.0)
                by_kind = result.get("by_kind", {})
                for kind in REQUIRED_ZERO_KINDS:
                    self.assertEqual(
                        by_kind.get(kind, 0),
                        0,
                        msg=f"seed {seed} spectate {kind}",
                    )
                custom = result.get("custom", {})
                for kind in CUSTOM_ZERO_KINDS:
                    self.assertEqual(
                        custom.get(kind, 0),
                        0,
                        msg=f"seed {seed} custom {kind}",
                    )
                diag = result.get("diagnostics_by_kind", {})
                for kind in DIAG_ZERO_KINDS:
                    self.assertEqual(
                        diag.get(kind, 0),
                        0,
                        msg=f"seed {seed} diag {kind}",
                    )


class TestTrafficSeedBatteryFixture(unittest.TestCase):
    def test_battery_has_ten_distinct_seeds(self):
        self.assertEqual(len(BASELINE_SEEDS), 10)
        self.assertEqual(len(set(BASELINE_SEEDS)), 10)


if __name__ == "__main__":
    unittest.main()
