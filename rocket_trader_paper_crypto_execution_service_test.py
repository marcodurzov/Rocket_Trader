#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Offline tests for the fail-closed Paper crypto execution startup gate."""

import unittest
from unittest.mock import Mock

from rocket_trader_paper_crypto_execution_service import (
    PaperCryptoExecutionService,
    PaperExecutionStartupError,
)


def successful_recovery():
    return {
        "mode": "PAPER",
        "read_only": True,
        "orders_scanned": 2,
        "orders_reconciled": 2,
        "orders_unresolved": 0,
        "orders_failed": 0,
        "status": "SUCCESS",
        "orders": [],
    }


class PaperCryptoExecutionServiceTests(unittest.TestCase):
    def setUp(self):
        self.adapter = Mock()
        self.adapter.verify_account.return_value = {"mode": "PAPER"}
        self.adapter.recover_journaled_orders.return_value = successful_recovery()
        self.adapter.submit.return_value = {
            "accepted": True, "mode": "PAPER", "order_id": "paper-order-1",
        }
        self.service = PaperCryptoExecutionService(self.adapter)

    def test_submission_is_blocked_before_startup_recovery(self):
        with self.assertRaisesRegex(PaperExecutionStartupError, "gate is closed"):
            self.service.submit(object())
        self.adapter.submit.assert_not_called()
        self.adapter.verify_account.assert_not_called()

    def test_start_verifies_account_and_recovers_before_opening_gate(self):
        result = self.service.start()
        self.assertTrue(result["ready"])
        self.assertEqual(result["mode"], "PAPER")
        self.adapter.verify_account.assert_called_once_with()
        self.adapter.recover_journaled_orders.assert_called_once_with()
        self.assertTrue(self.service.health()["ready"])

    def test_successful_start_allows_paper_submission(self):
        self.service.start()
        result = self.service.submit("intent")
        self.assertTrue(result["accepted"])
        self.adapter.submit.assert_called_once_with("intent")

    def test_unresolved_journal_keeps_gate_closed(self):
        recovery = successful_recovery()
        recovery.update({
            "status": "REQUIRES_REVIEW",
            "orders_reconciled": 1,
            "orders_unresolved": 1,
        })
        self.adapter.recover_journaled_orders.return_value = recovery
        with self.assertRaisesRegex(PaperExecutionStartupError, "incomplete"):
            self.service.start()
        self.assertFalse(self.service.health()["ready"])
        with self.assertRaises(PaperExecutionStartupError):
            self.service.submit("intent")
        self.adapter.submit.assert_not_called()

    def test_malformed_recovery_counts_fail_closed_even_with_success_status(self):
        recovery = successful_recovery()
        recovery["orders_scanned"] = "2"
        self.adapter.recover_journaled_orders.return_value = recovery
        with self.assertRaisesRegex(PaperExecutionStartupError, "malformed"):
            self.service.start()
        self.assertFalse(self.service.health()["ready"])

    def test_recovery_must_be_read_only_paper_and_fully_reconciled(self):
        for field, value in (
            ("mode", "LIVE"),
            ("read_only", False),
            ("orders_failed", 1),
            ("orders_unresolved", 1),
            ("orders_reconciled", 1),
        ):
            with self.subTest(field=field):
                self.setUp()
                recovery = successful_recovery()
                recovery[field] = value
                self.adapter.recover_journaled_orders.return_value = recovery
                with self.assertRaises(PaperExecutionStartupError):
                    self.service.start()
                self.assertFalse(self.service.health()["ready"])

    def test_account_preflight_exception_keeps_gate_closed(self):
        self.adapter.verify_account.side_effect = RuntimeError("offline fake")
        with self.assertRaisesRegex(PaperExecutionStartupError, "verification/recovery failed"):
            self.service.start()
        self.adapter.recover_journaled_orders.assert_not_called()
        self.adapter.submit.assert_not_called()
        self.assertFalse(self.service.health()["ready"])

    def test_adapter_error_closes_gate_until_a_new_recovery_pass(self):
        self.service.start()
        self.adapter.submit.side_effect = RuntimeError("offline fake")
        with self.assertRaisesRegex(PaperExecutionStartupError, "gate closed"):
            self.service.submit("first")
        self.assertFalse(self.service.health()["ready"])
        with self.assertRaises(PaperExecutionStartupError):
            self.service.submit("second")
        self.adapter.submit.assert_called_once_with("first")
        self.adapter.submit.side_effect = None
        self.service.start()
        self.assertTrue(self.service.health()["ready"])

    def test_stop_closes_gate_without_calling_broker(self):
        self.service.start()
        self.service.stop()
        self.assertFalse(self.service.health()["ready"])
        self.assertTrue(self.service.health()["closed"])
        self.adapter.submit.assert_not_called()
        with self.assertRaises(PaperExecutionStartupError):
            self.service.start()

    def test_start_is_idempotent_while_ready(self):
        first = self.service.start()
        second = self.service.start()
        self.assertTrue(first["ready"] and second["ready"])
        self.adapter.verify_account.assert_called_once_with()
        self.adapter.recover_journaled_orders.assert_called_once_with()


if __name__ == "__main__":
    unittest.main(verbosity=2)
