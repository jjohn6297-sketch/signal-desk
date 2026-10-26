import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class DashboardBuildTest(unittest.TestCase):
    def test_build_writes_row_files(self):
        subprocess.run([sys.executable, str(ROOT / "scripts" / "build_dashboard.py")], check=True, capture_output=True)
        for name in ("insights", "forecasts", "theses", "scores", "calibration", "score_groups",
                     "labour_summary", "labour_trend", "ai_share", "career_boards", "board_status"):
            rows = json.loads((ROOT / "dashboard" / f"{name}.json").read_text())
            self.assertIsInstance(rows, list, name)
        fc = json.loads((ROOT / "dashboard" / "forecasts.json").read_text())
        ids = [f["id"] for f in fc]
        self.assertEqual(len(ids), len(set(ids)))
        scores = json.loads((ROOT / "dashboard" / "scores.json").read_text())[0]
        self.assertEqual(scores["total"], len(fc))


if __name__ == "__main__":
    unittest.main()
