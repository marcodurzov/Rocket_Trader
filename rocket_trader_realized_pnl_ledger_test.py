#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Offline accounting and capital-policy tests; no broker calls or orders."""

import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from decimal import Decimal

from rocket_trader_realized_pnl_ledger import (
    LedgerError, LedgerFX, RealizedPnLLedger,
)


NOW = datetime(2026, 11, 9, 16, 0, tzinfo=timezone.utc)
FX = LedgerFX(Decimal("18.00"), NOW, "OFFLINE_TEST_FIXTURE")


class RealizedPnLLedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "ledger.sqlite3")
        self.ledger = RealizedPnLLedger(self.db)

    def tearDown(self):
        self.tmp.cleanup()

    def fill(self, fill_id, side, qty, price, fee="0.00", month_time=NOW):
        return self.ledger.record_fill(
            fill_id=fill_id, symbol="BTC/USD", side=side,
            quantity=qty, price_usd=price, fee_usd=fee,
            fx=FX, occurred_at=month_time, asset_class="CRYPTO_SPOT",
        )

    def test_seed_capital_and_no_virtual_paper_buying_power(self):
        s = self.ledger.snapshot()
        self.assertEqual(s.initial_capital_mxn, Decimal("1000.00"))
        self.assertEqual(s.operating_capital_mxn, Decimal("1000.00"))
        self.assertEqual(s.earned_growth_capital_mxn, Decimal("1000.00"))
        self.assertEqual(s.realized_net_pnl_mxn, Decimal("0.00"))

    def test_fifo_realized_net_pnl_includes_entry_and_exit_fees(self):
        self.fill("buy-1", "BUY", "0.01", "10000", "1.00")
        self.fill("buy-2", "BUY", "0.01", "12000", "1.00")
        self.fill("sell-1", "SELL", "0.015", "13000", "2.00")
        s = self.ledger.snapshot()
        # FIFO cost: 0.01*(10000+100) + 0.005*(12000+100) = 161.50 USD
        # Net proceeds: 195.00 - 2.00 = 193.00 USD; net P&L = 31.50 USD * 18.
        self.assertEqual(s.realized_net_pnl_mxn, Decimal("567.00"))
        self.assertEqual(s.operating_capital_mxn, Decimal("1567.00"))
        self.assertEqual(s.earned_growth_capital_mxn, Decimal("1567.00"))
        self.assertEqual(s.open_positions["BTC/USD"]["quantity"], "0.005")

    def test_crypto_buy_fee_withheld_in_base_asset_reduces_owned_quantity(self):
        self.ledger.record_fill(
            fill_id="crypto-buy-with-base-fee", symbol="BTC/USD", side="BUY",
            quantity="0.01", price_usd="10000", fee_usd="0",
            fee_asset_qty="-0.0001", fx=FX, occurred_at=NOW,
            asset_class="CRYPTO_SPOT",
        )
        self.assertEqual(
            self.ledger.snapshot().open_positions["BTC/USD"]["quantity"], "0.0099"
        )
        self.ledger.record_fill(
            fill_id="crypto-sell-after-base-fee", symbol="BTC/USD", side="SELL",
            quantity="0.0099", price_usd="11000", fee_usd="0.01",
            fx=FX, occurred_at=NOW, asset_class="CRYPTO_SPOT",
        )
        snap = self.ledger.snapshot()
        self.assertEqual(snap.realized_net_pnl_mxn, Decimal("160.02"))
        self.assertEqual(snap.open_positions, {})

    def test_crypto_sell_rejects_base_asset_fee_field_for_usd_pair(self):
        with self.assertRaisesRegex(LedgerError, "fee_asset_qty must be zero"):
            self.ledger.record_fill(
                fill_id="crypto-sell-invalid-fee", symbol="BTC/USD", side="SELL",
                quantity="0.001", price_usd="10000", fee_usd="0",
                fee_asset_qty="-0.00001", fx=FX, occurred_at=NOW,
                asset_class="CRYPTO_SPOT",
            )
        self.assertEqual(self.ledger.snapshot().event_count, 1)

    def test_sub_cent_crypto_fees_are_not_erased(self):
        self.ledger.record_fill(
            fill_id="small-buy", symbol="BTC/USD", side="BUY",
            quantity="0.0001", price_usd="10000", fee_usd="0.0025",
            fx=FX, occurred_at=NOW, asset_class="CRYPTO_SPOT",
        )
        self.ledger.record_fill(
            fill_id="small-sell", symbol="BTC/USD", side="SELL",
            quantity="0.0001", price_usd="10000", fee_usd="0.0025",
            fx=FX, occurred_at=NOW, asset_class="CRYPTO_SPOT",
        )
        snapshot = self.ledger.snapshot()
        # Both $0.0025 fees are below one cent but together cost $0.005 USD.
        self.assertEqual(snapshot.realized_net_pnl_mxn, Decimal("-0.09"))

    def test_partial_fill_pnl_is_aggregated_before_cent_rounding(self):
        self.ledger.record_fill(
            fill_id="partial-buy", symbol="BTC/USD", side="BUY",
            quantity="0.001", price_usd="10000", fee_usd="0",
            fx=FX, occurred_at=NOW, asset_class="CRYPTO_SPOT",
        )
        for index in range(10):
            self.ledger.record_fill(
                fill_id=f"partial-sell-{index}", symbol="BTC/USD", side="SELL",
                quantity="0.0001", price_usd="10010", fee_usd="0",
                fx=FX, occurred_at=NOW, asset_class="CRYPTO_SPOT",
            )
        snapshot = self.ledger.snapshot()
        # Each partial fill earns MXN 0.018; rounding each fill first loses 0.008 each.
        self.assertEqual(snapshot.realized_net_pnl_mxn, Decimal("0.18"))
        self.assertEqual(snapshot.open_positions, {})

    def test_short_sell_is_blocked(self):
        with self.assertRaisesRegex(LedgerError, "exceeds FIFO inventory"):
            self.fill("sell-no-inventory", "SELL", "0.001", "10000")

    def test_duplicate_fill_is_idempotent_and_payload_mismatch_rejected(self):
        self.fill("buy-idem", "BUY", "0.01", "10000")
        self.assertFalse(self.fill("buy-idem", "BUY", "0.01", "10000"))
        with self.assertRaisesRegex(LedgerError, "different event payload"):
            self.fill("buy-idem", "BUY", "0.02", "10000")
        self.assertEqual(self.ledger.snapshot().event_count, 2)

    def test_event_journal_is_immutable(self):
        self.fill("buy-immutable", "BUY", "0.01", "10000")
        with sqlite3.connect(self.db) as conn:
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    "UPDATE ledger_events SET payload_json='{}' WHERE event_id='buy-immutable'"
                )
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("DELETE FROM ledger_events WHERE event_id='buy-immutable'")

    def test_deposits_and_withdrawals_are_explicit_mxn_events(self):
        self.ledger.record_deposit(event_id="deposit-1", amount_mxn="500", occurred_at=NOW)
        self.ledger.record_withdrawal(event_id="withdrawal-1", amount_mxn="100", occurred_at=NOW)
        self.assertEqual(self.ledger.snapshot().operating_capital_mxn, Decimal("1400.00"))
        self.assertEqual(self.ledger.snapshot().earned_growth_capital_mxn, Decimal("1000.00"))

    def test_post_milestone_withdrawal_cannot_breach_operating_floor(self):
        self.fill("floor-buy", "BUY", "1", "10000")
        self.fill("floor-sell", "SELL", "1", "15550")
        snapshot = self.ledger.snapshot()
        self.assertTrue(snapshot.milestone_reached)
        self.assertEqual(snapshot.operating_capital_mxn, Decimal("100900.00"))
        with self.assertRaisesRegex(LedgerError, "protected MXN 100,000"):
            self.ledger.record_withdrawal(
                event_id="floor-breach", amount_mxn="900.01", occurred_at=NOW
            )
        self.ledger.record_withdrawal(
            event_id="floor-safe", amount_mxn="900.00", occurred_at=NOW
        )
        self.assertEqual(
            self.ledger.snapshot().operating_capital_mxn, Decimal("100000.00")
        )

    def test_duplicate_withdrawal_is_idempotent_before_capital_guard(self):
        self.ledger.record_deposit(
            event_id="funding-for-idempotent-withdrawal",
            amount_mxn="500", occurred_at=NOW,
        )
        self.assertTrue(self.ledger.record_withdrawal(
            event_id="withdrawal-idempotent", amount_mxn="100", occurred_at=NOW
        ))
        # Simulate a retry after the withdrawal was committed. It must not
        # re-run the balance guard or deduct the same movement twice.
        self.assertFalse(self.ledger.record_withdrawal(
            event_id="withdrawal-idempotent", amount_mxn="100", occurred_at=NOW
        ))
        with self.assertRaisesRegex(LedgerError, "different event payload"):
            self.ledger.record_withdrawal(
                event_id="withdrawal-idempotent", amount_mxn="101", occurred_at=NOW
            )
        self.assertEqual(self.ledger.snapshot().withdrawals_mxn, Decimal("100.00"))

    def test_withdrawal_cannot_exceed_operating_capital(self):
        with self.assertRaisesRegex(LedgerError, "exceeds operating capital"):
            self.ledger.record_withdrawal(
                event_id="withdrawal-too-large", amount_mxn="1001", occurred_at=NOW
            )

    def test_100_percent_compounding_before_milestone(self):
        self.fill("buy-profit", "BUY", "0.1", "10000")
        self.fill("sell-profit", "SELL", "0.1", "11000")
        close = self.ledger.close_month("2026-11")
        self.assertEqual(close["realized_net_pnl_mxn"], "1800.00")
        self.assertEqual(close["reinvestment_mxn"], "1800.00")
        self.assertEqual(close["reserve_mxn"], "0.00")
        self.assertEqual(close["personal_distribution_mxn"], "0.00")
        self.assertFalse(close["milestone_reached"])

    def test_milestone_latches_permanently_and_payout_floor_is_protected(self):
        # Capital rises from MXN 1,000 to MXN 100,900 through a realized gain.
        self.fill("buy-hit", "BUY", "1", "1000")
        self.fill("sell-hit", "SELL", "1", "6500")
        self.assertTrue(self.ledger.snapshot().milestone_reached)
        # A later loss takes capital below 100k, but does not reverse the milestone.
        self.fill("buy-loss", "BUY", "1", "10000")
        self.fill("sell-loss", "SELL", "1", "9900")
        snap = self.ledger.snapshot()
        self.assertTrue(snap.milestone_reached)
        self.assertLess(snap.operating_capital_mxn, Decimal("100000"))
        close = self.ledger.close_month("2026-11")
        self.assertTrue(close["milestone_reached"])
        self.assertTrue(close["payouts_suspended"])
        self.assertEqual(close["personal_distribution_mxn"], "0.00")
        self.assertEqual(close["reserve_mxn"], "0.00")

    def test_monthly_close_is_immutable_and_idempotent(self):
        self.fill("buy-close", "BUY", "0.1", "10000")
        self.fill("sell-close", "SELL", "0.1", "11000")
        first = self.ledger.close_month("2026-11")
        second = self.ledger.close_month("2026-11")
        self.assertEqual(first, second)
        with self.assertRaises(sqlite3.IntegrityError):
            with sqlite3.connect(self.db) as conn:
                conn.execute("UPDATE monthly_closes SET close_json='{}' WHERE period='2026-11'")

    def test_external_deposit_does_not_fake_the_100k_growth_milestone(self):
        self.ledger.record_deposit(
            event_id="large-external-deposit", amount_mxn="150000", occurred_at=NOW
        )
        snap = self.ledger.snapshot()
        self.assertEqual(snap.operating_capital_mxn, Decimal("151000.00"))
        self.assertFalse(snap.milestone_reached)

    def test_monthly_realized_loss_is_not_reported_as_negative_reinvestment(self):
        self.fill("buy-losing-trade", "BUY", "0.1", "10000")
        self.fill("sell-losing-trade", "SELL", "0.1", "9000")
        close = self.ledger.close_month("2026-11")
        self.assertLess(Decimal(close["realized_net_pnl_mxn"]), Decimal("0"))
        self.assertEqual(close["reinvestment_mxn"], "0.00")
        self.assertEqual(close["personal_distribution_mxn"], "0.00")
        self.assertEqual(close["reserve_mxn"], "0.00")

    def test_fifo_replay_uses_fill_timestamps_not_arrival_order(self):
        later = datetime(2026, 11, 10, 16, 0, tzinfo=timezone.utc)
        earlier = datetime(2026, 11, 9, 15, 0, tzinfo=timezone.utc)
        later_fx = LedgerFX(Decimal("18.00"), later, "LATER_TEST_FIXTURE")
        earlier_fx = LedgerFX(Decimal("18.00"), earlier, "EARLIER_TEST_FIXTURE")
        # Deliberately insert the later fill first; event-time order is authoritative.
        self.ledger.record_fill(
            fill_id="later-buy", symbol="BTC/USD", side="BUY",
            quantity="0.01", price_usd="12000", fee_usd="0",
            fx=later_fx, occurred_at=later, asset_class="CRYPTO_SPOT",
        )
        self.ledger.record_fill(
            fill_id="earlier-buy", symbol="BTC/USD", side="BUY",
            quantity="0.01", price_usd="10000", fee_usd="0",
            fx=earlier_fx, occurred_at=earlier, asset_class="CRYPTO_SPOT",
        )
        self.ledger.record_fill(
            fill_id="fifo-sell", symbol="BTC/USD", side="SELL",
            quantity="0.01", price_usd="11000", fee_usd="0",
            fx=later_fx, occurred_at=later, asset_class="CRYPTO_SPOT",
        )
        self.assertEqual(self.ledger.snapshot().realized_net_pnl_mxn, Decimal("180.00"))

    def test_fill_rejects_stale_or_future_fx(self):
        stale_fx = LedgerFX(
            Decimal("18"), datetime(2026, 11, 8, 15, 59, tzinfo=timezone.utc),
            "STALE_TEST_FIXTURE",
        )
        with self.assertRaisesRegex(LedgerError, "stale"):
            self.ledger.record_fill(
                fill_id="stale-fx-buy", symbol="BTC/USD", side="BUY",
                quantity="0.01", price_usd="10000", fee_usd="0",
                fx=stale_fx, occurred_at=NOW, asset_class="CRYPTO_SPOT",
            )
        future_fx = LedgerFX(
            Decimal("18"), datetime(2026, 11, 9, 16, 1, tzinfo=timezone.utc),
            "FUTURE_TEST_FIXTURE",
        )
        with self.assertRaisesRegex(LedgerError, "after the fill"):
            self.ledger.record_fill(
                fill_id="future-fx-buy", symbol="BTC/USD", side="BUY",
                quantity="0.01", price_usd="10000", fee_usd="0",
                fx=future_fx, occurred_at=NOW, asset_class="CRYPTO_SPOT",
            )
        self.assertEqual(self.ledger.snapshot().event_count, 1)

    def test_fx_timestamp_must_be_aware_and_source_present(self):
        with self.assertRaises(LedgerError):
            LedgerFX(Decimal("18"), datetime(2026, 11, 9), "fixture")
        with self.assertRaises(LedgerError):
            LedgerFX(Decimal("18"), NOW, " ")

    def test_integrity_check(self):
        self.fill("buy-integrity", "BUY", "0.01", "10000")
        self.assertTrue(self.ledger.verify_integrity()["ok"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
