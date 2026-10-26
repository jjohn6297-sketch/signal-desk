import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from snapshot_jobs import classify, counts, diff  # noqa: E402


class ClassifyTest(unittest.TestCase):
    def test_role_groups(self):
        self.assertEqual(classify("Customer Support Specialist")[0], "customer_support")
        self.assertEqual(classify("Senior Product Manager, Payments")[0], "product_management")
        self.assertEqual(classify("Staff Software Engineer")[0], "software_engineering")
        self.assertEqual(classify("Machine Learning Engineer")[0], "data_ai")
        self.assertEqual(classify("Paralegal")[0], "legal")
        self.assertEqual(classify("Tax Accountant")[0], "accounting_finance")
        self.assertEqual(classify("Office Plant Waterer")[0], "other")

    def test_seniority(self):
        self.assertEqual(classify("Senior Software Engineer")[1], "senior")
        self.assertEqual(classify("Junior Accountant")[1], "junior")
        self.assertEqual(classify("Software Engineering Intern")[1], "intern")
        self.assertEqual(classify("Software Engineer")[1], "mid_or_unknown")


class DiffTest(unittest.TestCase):
    def test_opened_and_closed(self):
        before = [{"job_id": "1", "title": "A"}, {"job_id": "2", "title": "B"}]
        now = [{"job_id": "2", "title": "B"}, {"job_id": "3", "title": "C"}]
        events = diff("acme", "2026-10-26", before, now)
        self.assertEqual({(e["event"], e["job_id"]) for e in events}, {("opened", "3"), ("closed", "1")})

    def test_counts(self):
        rows = [{"role_group": "legal", "seniority": "junior"}] * 2 + [{"role_group": "legal", "seniority": "senior"}]
        out = {(r["role_group"], r["seniority"]): r["open_roles"] for r in counts("acme", "2026-10-26", rows)}
        self.assertEqual(out, {("legal", "junior"): 2, ("legal", "senior"): 1})


if __name__ == "__main__":
    unittest.main()
