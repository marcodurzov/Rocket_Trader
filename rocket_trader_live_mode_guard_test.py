#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regression test: live mode must remain impossible in this project phase."""

import os
import unittest
from unittest.mock import patch

from rocket_trader_core import AlpacaExecutionAdapter, ExecutionMode


class LiveModeGuardTests(unittest.TestCase):
    def test_live_mode_is_blocked_even_when_env_flag_is_true(self):
        with patch.dict(os.environ, {"ALPACA_LIVE_ENABLED": "true"}, clear=False):
            with self.assertRaisesRegex(RuntimeError, "LIVE está deshabilitado"):
                AlpacaExecutionAdapter(
                    api_key="not-a-real-key",
                    api_secret="not-a-real-secret",
                    mode=ExecutionMode.LIVE,
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)
