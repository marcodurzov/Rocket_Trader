#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Offline tests for the manual read-only Paper activity audit runner."""

import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import alpaca_paper_activity_reconciliation_audit as audit


class FakeAuditClient:
    instances = []

    def __init__(self, api_key, api_secret, paper):
        self.paper = paper
        self.orders = [
            SimpleNamespace(
                id="broker-order-1", client_order_id="rt-order-1",
                symbol="BTC/USD", side="buy", status="filled", filled_qty="0.1",
                filled_avg_price="100",
            )
        ]
        self.activities = {
            "FILL": [{
                "id": "audit-fill-1", "activity_type": "FILL",
                "order_id": "broker-order-1", "order_status": "filled",
                "type": "fill", "symbol": "BTC/USD", "side": "buy",
                "qty": "0.1", "price": "100", "cum_qty": "0.1",
                "leaves_qty": "0", "transaction_time": "2026-11-11T12:00:00Z",
            }],
            "CFEE": [],
        }
        self.instances.append(self)

    def get_account(self):
        return SimpleNamespace(
            status="ACTIVE", currency="USD", crypto_status="ACTIVE",
            trading_blocked=False, multiplier="1", shorting_enabled=False,
        )

    def get_account_configurations(self):
        return SimpleNamespace(
            max_margin_multiplier="1", no_shorting=True,
            max_options_trading_level=0,
        )

    def get_orders(self, filter=None):
        self.order_filter = filter
        return self.orders

    def get(self, path, params):
        if path != "/account/activities":
            raise AssertionError("unexpected endpoint")
        return self.activities.get(params["activity_types"], [])


class PaperActivityAuditRunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.report = os.path.join(self.tmp.name, "report.json")
        self.ledger = os.path.join(self.tmp.name, "ledger.sqlite3")
        os.environ.update({
            "ALPACA_PAPER": "true",
            "ALPACA_LIVE_ENABLED": "false",
            "ALPACA_API_KEY": "paper-key",
            "ALPACA_SECRET_KEY": "paper-secret",
            "AUDIT_SYMBOL": "BTC/USD",
            "AUDIT_ORDERS_AFTER": "2026-11-11T11:59:00Z",
            "AUDIT_ORDERS_UNTIL": "2026-11-11T12:01:00Z",
            "AUDIT_FEES_AFTER": "2026-11-11T00:00:00Z",
            "AUDIT_FEES_UNTIL": "2026-11-13T00:00:00Z",
            "ROCKET_TRADER_ACTIVITY_REPORT": self.report,
            "ROCKET_TRADER_ACTIVITY_AUDIT_DB": self.ledger,
        })
        FakeAuditClient.instances = []

    def tearDown(self):
        for key in (
            "ALPACA_PAPER", "ALPACA_LIVE_ENABLED", "ALPACA_API_KEY",
            "ALPACA_SECRET_KEY", "AUDIT_SYMBOL", "AUDIT_ORDERS_AFTER",
            "AUDIT_ORDERS_UNTIL", "AUDIT_FEES_AFTER", "AUDIT_FEES_UNTIL",
            "ROCKET_TRADER_ACTIVITY_REPORT", "ROCKET_TRADER_ACTIVITY_AUDIT_DB",
        ):
            os.environ.pop(key, None)
        self.tmp.cleanup()

    def test_read_only_paper_audit_matches_fill_and_preserves_fee_unknown(self):
        with patch.object(audit, "TradingClient", FakeAuditClient):
            result = audit.main()
        self.assertEqual(result, 0)
        client = FakeAuditClient.instances[-1]
        self.assertTrue(client.paper)
        report = json.loads(Path(self.report).read_text(encoding="utf-8"))
        self.assertEqual(report["status"], "SUCCESS")
        self.assertEqual(report["matched_order_count"], 1)
        self.assertEqual(report["fee_evidence_status"], "NO_RECORDS_FEES_UNKNOWN")

    def test_average_price_mismatch_prevents_success_status(self):
        class WrongAveragePriceClient(FakeAuditClient):
            def __init__(self, api_key, api_secret, paper):
                super().__init__(api_key, api_secret, paper)
                self.orders[0].filled_avg_price = "101"

        with patch.object(audit, "TradingClient", WrongAveragePriceClient):
            result = audit.main()
        self.assertEqual(result, 1)
        report = json.loads(Path(self.report).read_text(encoding="utf-8"))
        self.assertEqual(report["status"], "RECONCILIATION_REQUIRES_REVIEW")
        self.assertEqual(report["unmatched_order_count"], 1)
        self.assertFalse(report["orders"][0]["average_price_match"])

    def test_missing_average_price_prevents_success_for_filled_order(self):
        class MissingAveragePriceClient(FakeAuditClient):
            def __init__(self, api_key, api_secret, paper):
                super().__init__(api_key, api_secret, paper)
                self.orders[0].filled_avg_price = None

        with patch.object(audit, "TradingClient", MissingAveragePriceClient):
            result = audit.main()
        self.assertEqual(result, 1)
        report = json.loads(Path(self.report).read_text(encoding="utf-8"))
        self.assertEqual(report["status"], "RECONCILIATION_REQUIRES_REVIEW")
        self.assertEqual(report["orders"][0]["reconciliation_status"], "ORDER_AVERAGE_PRICE_MISSING")

    def test_live_or_non_paper_configuration_is_rejected_before_client_creation(self):
        os.environ["ALPACA_LIVE_ENABLED"] = "true"
        with patch.object(audit, "TradingClient", FakeAuditClient):
            result = audit.main()
        self.assertEqual(result, 1)
        self.assertEqual(FakeAuditClient.instances, [])
        report = json.loads(open(self.report, encoding="utf-8").read())
        self.assertEqual(report["status"], "FAILED")

    def test_safe_reconciliation_error_is_reported_without_sdk_details(self):
        class InvalidActivityClient(FakeAuditClient):
            def get(self, path, params):
                if params["activity_types"] == "FILL":
                    return [{"activity_type": "FILL"}]
                return []

        stderr = StringIO()
        with patch.object(audit, "TradingClient", InvalidActivityClient):
            with redirect_stderr(stderr):
                result = audit.main()
        self.assertEqual(result, 1)
        report = json.loads(Path(self.report).read_text(encoding="utf-8"))
        self.assertEqual(report["error_type"], "AlpacaActivityReconciliationError")
        self.assertEqual(report["error_message"], "Account activity is missing its immutable id.")
        self.assertIn("Account activity is missing its immutable id.", stderr.getvalue())
        self.assertNotIn("paper-secret", stderr.getvalue())

    def test_account_cash_only_policy_is_verified_read_only(self):
        class UnsafeAccountClient(FakeAuditClient):
            def get_account_configurations(self):
                return SimpleNamespace(
                    max_margin_multiplier="2", no_shorting=False,
                    max_options_trading_level=1,
                )

        with patch.object(audit, "TradingClient", UnsafeAccountClient):
            result = audit.main()
        self.assertEqual(result, 1)
        report = json.loads(open(self.report, encoding="utf-8").read())
        self.assertEqual(report["status"], "FAILED")
        self.assertEqual(report.get("order_count", 0), 0)


    def test_account_wide_unclassifiable_cfee_does_not_fail_matched_order_audit(self):
        class AccountWideFeeClient(FakeAuditClient):
            def get(self, path, params):
                if params["activity_types"] == "CFEE":
                    return [{
                        "id": "fee-account-wide-unclassified",
                        "activity_type": "CFEE",
                        "symbol": "USD",
                        "net_amount": "-0.25",
                        "currency": "USD",
                        "created_at": "2026-11-12T00:00:00Z",
                    }]
                return super().get(path, params)

        with patch.object(audit, "TradingClient", AccountWideFeeClient):
            result = audit.main()
        self.assertEqual(result, 0)
        report = json.loads(Path(self.report).read_text(encoding="utf-8"))
        self.assertEqual(report["status"], "SUCCESS")
        self.assertEqual(report["matched_order_count"], 1)
        self.assertEqual(report["unclassified_fee_activity_count"], 1)
        self.assertEqual(report["fee_evidence_status"], "UNCLASSIFIED_OR_INCOMPLETE_RECORDS")
        self.assertEqual(
            report["unclassified_fee_activities"][0]["activity_id"],
            "fee-account-wide-unclassified",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
