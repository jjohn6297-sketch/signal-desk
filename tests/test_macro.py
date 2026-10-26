import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from macro_regime import as_of, config, history, regime, state  # noqa: E402

HY = {"direction": "above", "watch": 4.5, "stress": 6.0}
CURVE = {"direction": "below", "watch": 0.25, "stress": 0.0}


class StateTest(unittest.TestCase):
    def test_above(self):
        self.assertEqual(state(3.9, HY), "normal")
        self.assertEqual(state(4.5, HY), "watch")
        self.assertEqual(state(6.2, HY), "stress")
        self.assertIsNone(state(None, HY))

    def test_below(self):
        self.assertEqual(state(0.6, CURVE), "normal")
        self.assertEqual(state(0.1, CURVE), "watch")
        self.assertEqual(state(-0.3, CURVE), "stress")


class RegimeTest(unittest.TestCase):
    def test_labels(self):
        self.assertEqual(regime({"a": "normal", "b": "watch"}, 3.5, 3.6, False)[0], "Risk-on")
        self.assertEqual(regime({"a": "watch", "b": "watch", "c": "watch"}, 3.5, 3.6, False)[0], "Late cycle")
        self.assertEqual(regime({"a": "stress", "b": "normal"}, 3.5, 3.6, False)[0], "Late cycle")
        self.assertEqual(regime({"a": "stress", "b": "stress"}, 7.0, 6.0, False)[0], "Risk-off")
        self.assertEqual(regime({"a": "stress", "b": "watch"}, 5.0, 6.5, True)[0], "Recovery")

    def test_as_of_ignores_stale_values(self):
        obs = [("2026-01-01", 1.0), ("2026-06-01", 2.0)]
        self.assertEqual(as_of(obs, "2026-06-15"), 2.0)
        self.assertIsNone(as_of(obs, "2025-12-31"))
        self.assertIsNone(as_of(obs, "2027-01-01"))

    def test_history_runs_weekly(self):
        cfg = config()
        # Spreads and volatility spike in March, then spreads ease below their level 3 months earlier.
        hy = [("2026-01-02", 3.0), ("2026-03-06", 7.0), ("2026-06-05", 5.0)]
        vix = [("2026-01-02", 15.0), ("2026-03-06", 35.0), ("2026-06-05", 18.0)]
        curve = [("2026-01-02", 0.5), ("2026-04-03", 0.5)]
        brent = [("2026-01-02", 70.0), ("2026-04-03", 70.0)]
        series = {"hy_spread": hy, "vix": vix, "curve_10y2y": curve, "brent": brent}
        h = history(cfg, series, "2026-01-02", "2026-06-12")
        labels = {r["date"]: r["regime"] for r in h}
        self.assertEqual(labels["2026-01-02"], "Risk-on")
        self.assertEqual(labels["2026-03-06"], "Risk-off")
        self.assertEqual(labels["2026-06-05"], "Recovery")


class ConfigTest(unittest.TestCase):
    def test_config_is_well_formed(self):
        cfg = config()
        ids = [i["id"] for i in cfg["indicators"]]
        self.assertEqual(len(ids), len(set(ids)))
        for i in cfg["indicators"]:
            self.assertIn(i["direction"], ("above", "below"), i["id"])
            self.assertIn(i["source"], ("fred", "manual"), i["id"])
            if i["direction"] == "above":
                self.assertLess(i["watch"], i["stress"], i["id"])
            else:
                self.assertGreater(i["watch"], i["stress"], i["id"])
        self.assertEqual(set(cfg["regime"]["size_limits"]), {"Risk-on", "Late cycle", "Risk-off", "Recovery"})


if __name__ == "__main__":
    unittest.main()
