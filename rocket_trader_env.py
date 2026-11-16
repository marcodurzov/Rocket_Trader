#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Strict, shared environment-flag parsing for Rocket Trader."""

from __future__ import annotations

import os
from typing import Optional

_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
_FALSE_VALUES = frozenset({"0", "false", "no", "off", ""})


def env_bool(name: str, default: Optional[bool] = None) -> bool:
    """Parse a boolean environment variable; reject ambiguous values.

    Accepted true values: 1/true/yes/on.
    Accepted false values: 0/false/no/off/empty.
    Missing variables use default; an unset variable without a default
    and any unrecognized value raise ValueError (fail closed).
    """
    raw = os.getenv(name)
    if raw is None:
        if default is None:
            raise ValueError(f"{name} is not set and has no default")
        return bool(default)

    value = raw.strip().lower()
    if value in _TRUE_VALUES:
        return True
    if value in _FALSE_VALUES:
        return False
    raise ValueError(f"{name} contains an unsupported boolean value")
