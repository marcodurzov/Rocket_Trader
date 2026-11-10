#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Offline tests for conservative Alpaca cash-activity classification."""

import os
import tempfile
import unittest
from datetime import datetime, timezone
from decimal import Decimal

from rocket_trader_realized_pnl_ledger import LedgerFX, RealizedPnLLedger
from rocket_trader_alpaca_cash_activity_bridge import (
    AlpacaCashActivityBridge, AlpacaCashActivityError,
)

NOW = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)


class AlpacaCashActivityBridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ledger = RealizedPnLLedger(os.path.join(self.tmp.name, "ledger.sqlite3"))
        self.fx_calls = []
        self.bridge = AlpacaCashActivityBridge(
            db_path=os.path.join(self.tmp.name, "cash-inbox.sqlite3"),
            ledger=self.ledger,
            fx_resolver=lambda when: (
                self.fx_calls.append(when) or LedgerFX(Decimal("18.50"), NOW, "TEST_FX")
            ),
        )

    def tearDown(self):
        self.tmp.cleanup()

    def usd_csd(self, activity_id="cash-deposit-1", **extra):
        payload = {
            "id": activity_id, "activity_type": "CSD",
            "net_amount": "100", "currency": "USD",
            "transaction_time": NOW.isoformat(), "status": "executed",
        }
        payload.update(extra)
        return payload

    def test_csd_is_quarantined_until_explicit_confirmation(self):
        result = self.bridge.process_activity(self.usd_csd())
        self.assertTrue(result["manual_review"])
        self.assertEqual(self.ledger.snapshot().deposits_mxn, Decimal("0.00"))
        self.assertEqual(self.ledger.snapshot().realized_net_pnl_mxn, Decimal("0.00"))
        self.assertEqual(self.bridge.status()["pending_or_failed"], 1)

        confirmed = self.bridge.confirm_external_deposit(
            "cash-deposit-1", confirmation_reference="BANK-TRANSFER-REF-001"
        )
        snapshot = self.ledger.snapshot()
        self.assertEqual(Decimal(confirmed["deposit_mxn"]), Decimal("1850.000"))
        self.assertFalse(confirmed["counts_as_trading_profit"])
        self.assertEqual(snapshot.deposits_mxn, Decimal("1850.00"))
        self.assertEqual(snapshot.realized_net_pnl_mxn, Decimal("0.00"))
        self.assertEqual(snapshot.earned_growth_capital_mxn, Decimal("1000.00"))
        self.assertEqual(self.bridge.status()["pending_or_failed"], 0)

    def test_confirmation_is_idempotent(self):
        self.bridge.process_activity(self.usd_csd("cash-deposit-dup", net_amount="25"))
        first = self.bridge.confirm_external_deposit(
            "cash-deposit-dup", confirmation_reference="BANK-REF-DUP"
        )
        second = self.bridge.confirm_external_deposit(
            "cash-deposit-dup", confirmation_reference="BANK-REF-DUP"
        )
        self.assertFalse(first["duplicate"])
        self.assertTrue(second["duplicate"])
        self.assertEqual(self.ledger.snapshot().deposits_mxn, Decimal("462.50"))

    def test_mxn_deposit_confirmation_does_not_call_fx(self):
        bridge = AlpacaCashActivityBridge(
            db_path=os.path.join(self.tmp.name, "mxn-inbox.sqlite3"),
            ledger=self.ledger,
            fx_resolver=lambda when: (
                self.fx_calls.append(when) or LedgerFX(Decimal("18"), NOW, "TEST")
            ),
        )
        bridge.process_activity({
            "id": "cash-deposit-mxn", "activity_type": "CSD",
            "net_amount": "500", "currency": "MXN",
            "date": NOW.date().isoformat(), "status": "executed",
        })
        bridge.confirm_external_deposit(
            "cash-deposit-mxn", confirmation_reference="BANK-REF-MXN"
        )
        self.assertEqual(self.fx_calls, [])
        self.assertEqual(self.ledger.snapshot().deposits_mxn, Decimal("500.00"))

    def test_returned_withdrawal_description_cannot_be_confirmed_as_new_deposit(self):
        self.bridge.process_activity(self.usd_csd(
            "returned-cash", description="Returned withdrawal",
        ))
        with self.assertRaisesRegex(AlpacaCashActivityError, "return/reversal"):
            self.bridge.confirm_external_deposit(
                "returned-cash", confirmation_reference="USER-REF-RETURN"
            )
        self.assertEqual(self.ledger.snapshot().deposits_mxn, Decimal("0.00"))
        self.assertEqual(self.bridge.status()["pending_or_failed"], 1)

    def test_csw_and_jnlc_are_quarantined(self):
        csw = self.bridge.process_activity({
            "id": "cash-withdrawal-1", "activity_type": "CSW",
            "net_amount": "-100", "currency": "USD",
            "date": NOW.date().isoformat(), "status": "executed",
        })
        jnlc = self.bridge.process_activity({
            "id": "paper-seed-1", "activity_type": "JNLC",
            "net_amount": "100000", "currency": "USD",
            "date": "2026-09-28", "status": "executed",
        })
        self.assertTrue(csw["manual_review"])
        self.assertTrue(jnlc["manual_review"])
        self.assertEqual(self.ledger.snapshot().withdrawals_mxn, Decimal("0.00"))
        self.assertEqual(self.ledger.snapshot().deposits_mxn, Decimal("0.00"))
        self.assertEqual(self.bridge.status()["pending_or_failed"], 2)

    def test_missing_fx_keeps_csd_pending_and_can_be_confirmed_later(self):
        bridge = AlpacaCashActivityBridge(
            db_path=os.path.join(self.tmp.name, "retry-inbox.sqlite3"),
            ledger=self.ledger,
            fx_resolver=lambda _when: None,
        )
        bridge.process_activity(self.usd_csd("cash-deposit-retry", net_amount="10"))
        with self.assertRaisesRegex(AlpacaCashActivityError, "validated timestamped LedgerFX"):
            bridge.confirm_external_deposit(
                "cash-deposit-retry", confirmation_reference="BANK-REF-RETRY"
            )
        self.assertEqual(bridge.status()["pending_or_failed"], 1)
        bridge.fx_resolver = lambda _when: LedgerFX(Decimal("18.50"), NOW, "RETRY_FX")
        result = bridge.confirm_external_deposit(
            "cash-deposit-retry", confirmation_reference="BANK-REF-RETRY"
        )
        self.assertEqual(result["deposit_mxn"], "185.00")
        self.assertEqual(self.ledger.snapshot().deposits_mxn, Decimal("185.00"))

    def test_confirmed_csw_is_recorded_as_withdrawal_not_profit(self):
        self.bridge.process_activity({
            "id": "cash-withdrawal-confirmed", "activity_type": "CSW",
            "net_amount": "-100", "currency": "MXN",
            "date": NOW.date().isoformat(), "status": "executed",
        })
        result = self.bridge.confirm_external_withdrawal(
            "cash-withdrawal-confirmed", confirmation_reference="BANK-WITHDRAWAL-001"
        )
        snapshot = self.ledger.snapshot()
        self.assertEqual(snapshot.withdrawals_mxn, Decimal("100.00"))
        self.assertEqual(snapshot.realized_net_pnl_mxn, Decimal("0.00"))
        self.assertFalse(result["counts_as_trading_profit"])
        duplicate = self.bridge.confirm_external_withdrawal(
            "cash-withdrawal-confirmed", confirmation_reference="BANK-WITHDRAWAL-001"
        )
        self.assertTrue(duplicate["duplicate"])
        self.assertEqual(self.bridge.status()["pending_or_failed"], 0)

    def test_jnlc_can_only_be_resolved_with_evidence_and_has_no_ledger_effect(self):
        self.bridge.process_activity({
            "id": "paper-seed-resolved", "activity_type": "JNLC",
            "net_amount": "100000", "currency": "USD",
            "date": "2026-09-28", "status": "executed",
        })
        with self.assertRaisesRegex(AlpacaCashActivityError, "rationale"):
            self.bridge.resolve_journal_as_non_user_capital(
                "paper-seed-resolved", resolution_reference="PAPER-ACCOUNT-STATEMENT",
                rationale=" ",
            )
        result = self.bridge.resolve_journal_as_non_user_capital(
            "paper-seed-resolved",
            resolution_reference="ALPACA-PAPER-SEED-2026-09-28",
            rationale="Broker statement identifies this JNLC as the simulator's initial Paper balance.",
        )
        self.assertEqual(result["ledger_effect"], "NONE")
        self.assertEqual(self.ledger.snapshot().deposits_mxn, Decimal("0.00"))
        self.assertEqual(self.ledger.snapshot().earned_growth_capital_mxn, Decimal("1000.00"))
        self.assertEqual(self.bridge.status()["pending_or_failed"], 0)

    def test_deposit_fx_must_not_be_future_or_stale(self):
        old_fx = LedgerFX(Decimal("18.50"), NOW.replace(day=8), "OLD_FIXTURE")
        bridge = AlpacaCashActivityBridge(
            db_path=os.path.join(self.tmp.name, "old-fx.sqlite3"),
            ledger=self.ledger,
            fx_resolver=lambda _when: old_fx,
        )
        bridge.process_activity(self.usd_csd("old-fx-deposit"))
        with self.assertRaisesRegex(AlpacaCashActivityError, "no more than 24 hours old"):
            bridge.confirm_external_deposit(
                "old-fx-deposit", confirmation_reference="BANK-REF-OLD-FX"
            )
        self.assertEqual(self.ledger.snapshot().deposits_mxn, Decimal("0.00"))

    def test_non_cash_activity_is_ignored(self):
        result = self.bridge.process_activity({"activity_type": "CFEE", "id": "fee-1"})
        self.assertTrue(result["ignored"])
        self.assertEqual(self.ledger.snapshot().deposits_mxn, Decimal("0.00"))

    def test_activity_requires_unique_id_and_only_csd_can_be_confirmed(self):
        with self.assertRaisesRegex(AlpacaCashActivityError, "broker activity id"):
            self.bridge.process_activity({
                "activity_type": "CSD", "net_amount": "100", "currency": "USD",
                "date": NOW.date().isoformat(),
            })
        self.bridge.process_activity({
            "id": "csw-not-deposit", "activity_type": "CSW",
            "net_amount": "-100", "currency": "USD", "date": NOW.date().isoformat(),
        })
        with self.assertRaisesRegex(AlpacaCashActivityError, "Only CSD"):
            self.bridge.confirm_external_deposit(
                "csw-not-deposit", confirmation_reference="NOT-A-DEPOSIT"
            )

    def test_confirmation_requires_reference(self):
        self.bridge.process_activity(self.usd_csd())
        with self.assertRaisesRegex(AlpacaCashActivityError, "confirmation_reference"):
            self.bridge.confirm_external_deposit("cash-deposit-1", confirmation_reference=" ")


if __name__ == "__main__":
    unittest.main(verbosity=2)
