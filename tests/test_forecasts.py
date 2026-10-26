import datetime as dt
import sys
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from resolve_forecasts import evaluate  # noqa: E402
from score_forecasts import brier, calibrate, fit  # noqa: E402

DATA = {"2026-10-27": 5.00, "2026-11-10": 5.20, "2026-12-01": 5.35, "2027-01-30": 4.90}


class RuleTest(unittest.TestCase):
    def test_never_close_above_breaks_early(self):
        rule = {"kind": "never_close_above", "threshold": 5.31, "start": "2026-10-27", "end": "2027-01-31"}
        self.assertEqual(evaluate(rule, DATA, dt.date(2026, 12, 2))[0], 0)

    def test_never_close_above_waits_for_end(self):
        rule = {"kind": "never_close_above", "threshold": 5.40, "start": "2026-10-27", "end": "2027-01-31"}
        self.assertIsNone(evaluate(rule, DATA, dt.date(2026, 12, 2))[0])
        self.assertEqual(evaluate(rule, DATA, dt.date(2027, 2, 1))[0], 1)

    def test_touch_below(self):
        rule = {"kind": "touch_below", "threshold": 4.95, "start": "2026-10-27", "end": "2027-01-31"}
        self.assertEqual(evaluate(rule, DATA, dt.date(2027, 1, 30))[0], 1)

    def test_value_on_date_uses_last_observation(self):
        rule = {"kind": "value_on_date", "date": "2027-01-31", "op": "<=", "threshold": 4.95}
        self.assertIsNone(evaluate(rule, DATA, dt.date(2027, 1, 31))[0])
        self.assertEqual(evaluate(rule, DATA, dt.date(2027, 2, 1))[0], 1)

    def test_release_value(self):
        rule = {"kind": "release_value", "period": "2026-12-01", "op": ">=", "threshold": 5.3}
        self.assertEqual(evaluate(rule, DATA, dt.date(2027, 1, 10))[0], 1)


class ScoreTest(unittest.TestCase):
    def test_brier(self):
        self.assertAlmostEqual(brier([(0.5, 1), (0.5, 0)]), 0.25)

    def test_fit_softens_overconfidence(self):
        # Says 90% but is right only 60% of the time: the fit should pull forecasts towards 50%.
        pairs = [(0.9, 1)] * 12 + [(0.9, 0)] * 8 + [(0.1, 0)] * 12 + [(0.1, 1)] * 8
        k, b = fit(pairs)
        self.assertLess(k, 1.0)
        self.assertLess(calibrate(0.9, k, b), 0.8)


class RegistryTest(unittest.TestCase):
    def test_registry_is_well_formed(self):
        doc = yaml.safe_load((ROOT / "forecasts" / "forecasts.yaml").read_text())
        ids = [f["id"] for f in doc["forecasts"]]
        self.assertEqual(len(ids), len(set(ids)), "forecast ids must be unique")
        for f in doc["forecasts"]:
            self.assertTrue(0 < float(f["probability"]) < 1, f["id"])
            self.assertIn(f["resolution"]["method"], ("auto", "judged"), f["id"])
            self.assertTrue(f.get("reasoning"), f["id"])


if __name__ == "__main__":
    unittest.main()
