import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from snapshot_jobs import ai_related, classify, counts, diff, region  # noqa: E402


class ClassifyTest(unittest.TestCase):
    def test_role_groups(self):
        self.assertEqual(classify("Customer Support Specialist")[0], "customer_support")
        self.assertEqual(classify("Senior Product Manager, Payments")[0], "product_management")
        self.assertEqual(classify("Staff Software Engineer")[0], "software_engineering")
        self.assertEqual(classify("Machine Learning Engineer")[0], "data_ai")
        self.assertEqual(classify("Paralegal")[0], "legal")
        self.assertEqual(classify("Tax Accountant")[0], "accounting_finance")
        self.assertEqual(classify("Office Plant Waterer")[0], "other")

    def test_product_family(self):
        pm = "product_management"
        for t in ("Product Manager", "Technical Product Manager, Payments", "Group Product Manager",
                  "Product Owner", "Head of Product", "Director of Product", "VP, Product",
                  "Chief Product Officer", "Product Operations Manager", "Product Manager, Customer Support Tools"):
            self.assertEqual(classify(t)[0], pm, t)
        for t in ("Product Marketing Manager", "Product Designer", "Director of Product Marketing",
                  "Head of Product Design", "Product Analyst", "Software Engineer, Product"):
            self.assertNotEqual(classify(t)[0], pm, t)

    def test_product_ladder(self):
        self.assertEqual(classify("Product Manager")[1], "mid_or_unknown")
        self.assertEqual(classify("Senior Product Manager")[1], "senior")
        self.assertEqual(classify("Principal Product Manager")[1], "senior")
        self.assertEqual(classify("Associate Product Manager")[1], "junior")
        self.assertEqual(classify("Senior Director of Product")[1], "leadership")
        self.assertEqual(classify("Product Manager Intern")[1], "intern")

    def test_region_and_ai(self):
        self.assertEqual(region("Dublin, Ireland"), "dublin")
        self.assertEqual(region("Remote - Ireland"), "ireland_other")
        self.assertEqual(region("London, UK"), "uk")
        self.assertEqual(region("San Francisco, CA"), "us")
        self.assertEqual(region("Remote"), "remote")
        self.assertEqual(region("Singapore"), "other")
        self.assertTrue(ai_related("Senior Product Manager, AI Agents"))
        self.assertTrue(ai_related("Product Manager, Machine Learning Platform"))
        self.assertFalse(ai_related("Customer Support Agent"))
        self.assertFalse(ai_related("Product Manager, Payments"))

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
        rows = ([{"role_group": "legal", "seniority": "junior", "region": "dublin", "ai_related": True}] * 2
                + [{"role_group": "legal", "seniority": "senior", "region": "us", "ai_related": False}])
        out = {(r["role_group"], r["seniority"], r["region"]): (r["open_roles"], r["ai_roles"]) for r in counts("acme", "2026-10-26", rows)}
        self.assertEqual(out, {("legal", "junior", "dublin"): (2, 2), ("legal", "senior", "us"): (1, 0)})


if __name__ == "__main__":
    unittest.main()
