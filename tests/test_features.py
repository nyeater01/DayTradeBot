import unittest
from datetime import datetime, time
from zoneinfo import ZoneInfo

from daytradebot.features.pivots import classic_pivots, near_level
from daytradebot.features.volume_profile import session_volume_profile
from daytradebot.features.vwap import session_vwap, vwap_side
from daytradebot.session_policy import active_killzones, should_flat_for_session

import pandas as pd

NY = ZoneInfo("America/New_York")


class PivotTests(unittest.TestCase):
    def test_classic_pivots(self) -> None:
        p = classic_pivots(110.0, 90.0, 100.0)
        self.assertAlmostEqual(p["P"], 100.0)
        self.assertAlmostEqual(p["R1"], 110.0)
        self.assertAlmostEqual(p["S1"], 90.0)

    def test_near_level(self) -> None:
        self.assertTrue(near_level(100.0, 100.1, 0.002))
        self.assertFalse(near_level(100.0, 105.0, 0.001))


class VwapTests(unittest.TestCase):
    def test_session_vwap(self) -> None:
        df = pd.DataFrame(
            {
                "high": [10.0, 12.0],
                "low": [9.0, 11.0],
                "close": [10.0, 12.0],
                "volume": [100.0, 100.0],
            }
        )
        v = session_vwap(df)
        self.assertIsNotNone(v)
        assert v is not None
        self.assertAlmostEqual(v, 10.5)
        self.assertEqual(vwap_side(11.0, v), "above")


class VolumeProfileTests(unittest.TestCase):
    def test_poc_in_range(self) -> None:
        df = pd.DataFrame(
            {
                "high": [101, 102, 103, 104],
                "low": [99, 100, 101, 102],
                "close": [100, 101, 102, 103],
                "volume": [10, 20, 30, 40],
            }
        )
        vp = session_volume_profile(df, n_bins=20)
        self.assertIsNotNone(vp)
        assert vp is not None
        self.assertGreater(vp["VAH"], vp["VAL"])


class KillzoneTests(unittest.TestCase):
    def test_ny_am_active(self) -> None:
        now = datetime(2026, 5, 27, 10, 0, tzinfo=NY)
        zones = active_killzones(now, ("ny_am", "ny_pm"))
        self.assertIn("ny_am", zones)

    def test_flat_outside_killzone(self) -> None:
        now = datetime(2026, 5, 27, 12, 0, tzinfo=NY)
        flat, reason = should_flat_for_session(
            now, ("ny_am", "ny_pm"), True, False, time(16, 0)
        )
        self.assertTrue(flat)
        self.assertEqual(reason, "outside_killzone")


if __name__ == "__main__":
    unittest.main()
