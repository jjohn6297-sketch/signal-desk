import datetime as dt
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from smart_money import action, deadline, fund_moves, matches, norm  # noqa: E402
from snapshot_sec import parse_form4, parse_info_table  # noqa: E402

INFO = b"""<?xml version="1.0"?>
<informationTable xmlns="http://www.sec.gov/edgar/document/thirteenf/informationtable">
  <infoTable><nameOfIssuer>ALPHABET INC</nameOfIssuer><titleOfClass>CAP STK CL A</titleOfClass><cusip>02079K305</cusip>
    <value>1000000</value><shrsOrPrnAmt><sshPrnamt>5000</sshPrnamt><sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt>
    <investmentDiscretion>SOLE</investmentDiscretion></infoTable>
  <infoTable><nameOfIssuer>ALPHABET INC</nameOfIssuer><titleOfClass>CAP STK CL A</titleOfClass><cusip>02079K305</cusip>
    <value>200000</value><shrsOrPrnAmt><sshPrnamt>1000</sshPrnamt><sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt>
    <investmentDiscretion>DFND</investmentDiscretion></infoTable>
  <infoTable><nameOfIssuer>NVIDIA CORPORATION</nameOfIssuer><titleOfClass>COM</titleOfClass><cusip>67066G104</cusip>
    <value>300000</value><shrsOrPrnAmt><sshPrnamt>2000</sshPrnamt><sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt>
    <putCall>Put</putCall><investmentDiscretion>SOLE</investmentDiscretion></infoTable>
</informationTable>"""

FORM4 = b"""<?xml version="1.0"?>
<ownershipDocument>
  <reportingOwner><reportingOwnerId><rptOwnerName>DOE JANE</rptOwnerName></reportingOwnerId>
    <reportingOwnerRelationship><isDirector>0</isDirector><isOfficer>1</isOfficer><officerTitle>Chief Executive Officer</officerTitle></reportingOwnerRelationship></reportingOwner>
  <nonDerivativeTable>
    <nonDerivativeTransaction><transactionDate><value>2026-10-19</value></transactionDate>
      <transactionCoding><transactionCode>P</transactionCode></transactionCoding>
      <transactionAmounts><transactionShares><value>1000</value></transactionShares><transactionPricePerShare><value>50.5</value></transactionPricePerShare>
        <transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode></transactionAmounts></nonDerivativeTransaction>
    <nonDerivativeTransaction><transactionDate><value>2026-10-20</value></transactionDate>
      <transactionCoding><transactionCode>S</transactionCode></transactionCoding>
      <transactionAmounts><transactionShares><value>300</value></transactionShares><transactionPricePerShare><value>52</value></transactionPricePerShare>
        <transactionAcquiredDisposedCode><value>D</value></transactionAcquiredDisposedCode></transactionAmounts></nonDerivativeTransaction>
  </nonDerivativeTable>
</ownershipDocument>"""


class ParseTest(unittest.TestCase):
    def test_info_table_aggregates_lots(self):
        rows = parse_info_table(INFO)
        goog = next(r for r in rows if r["issuer"] == "ALPHABET INC")
        self.assertEqual((goog["value_usd"], goog["shares"]), (1200000, 6000))
        self.assertEqual(next(r for r in rows if r["issuer"].startswith("NVIDIA"))["put_call"], "Put")

    def test_form4_keeps_open_market_purchases_only(self):
        t = parse_form4(FORM4)
        self.assertEqual(len(t), 1)
        self.assertEqual((t[0]["insider"], t[0]["role"], t[0]["shares"], t[0]["value_usd"]),
                         ("DOE JANE", "Chief Executive Officer", 1000, 50500))


class MovesTest(unittest.TestCase):
    def test_names(self):
        self.assertEqual(norm("AMAZON COM INC"), "AMAZON")
        self.assertEqual(norm("Meta Platforms, Inc. Class A"), "META PLATFORMS")
        self.assertTrue(matches(norm("TAIWAN SEMICONDUCTOR MFG LTD"), norm("TSMC")))
        self.assertTrue(matches(norm("NVIDIA CORPORATION"), norm("Nvidia")))
        self.assertFalse(matches(norm("METALLA ROYALTY"), norm("Meta Platforms")))

    def test_actions(self):
        self.assertEqual(action(None, {"shares": 5}, 0.1), "new")
        self.assertEqual(action({"shares": 5}, None, 0.1), "exited")
        self.assertEqual(action({"shares": 100}, {"shares": 130}, 0.1), "added")
        self.assertEqual(action({"shares": 100}, {"shares": 80}, 0.1), "trimmed")
        self.assertEqual(action({"shares": 100}, {"shares": 105}, 0.1), "held")

    def test_fund_moves(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d) / "holdings" / "x"
            base.mkdir(parents=True)
            head = "issuer,title_of_class,cusip,put_call,value_usd,shares,share_type\n"
            (base / "2026-03-31.csv").write_text(head + "AMAZON COM INC,COM,1,,100,10,SH\nORACLE CORP,COM,2,,50,5,SH\n")
            (base / "2026-06-30.csv").write_text(head + "AMAZON COM INC,COM,1,,300,20,SH\nNVIDIA CORP,COM,3,,100,4,SH\nNVIDIA CORP,COM,3,Call,999,9,SH\n")
            m = {x["issuer_norm"]: x["action"] for x in fund_moves("x", ["2026-03-31", "2026-06-30"], 0.1, Path(d))}
            self.assertEqual(m, {"AMAZON": "added", "ORACLE": "exited", "NVIDIA": "new"})

    def test_deadline(self):
        self.assertEqual(deadline(dt.date(2026, 10, 26)), ("2026-11-16", "2026-09-30"))
        self.assertEqual(deadline(dt.date(2026, 11, 17)), ("2027-02-16", "2026-12-31"))


if __name__ == "__main__":
    unittest.main()
