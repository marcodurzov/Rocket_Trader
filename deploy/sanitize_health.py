#!/usr/bin/env python3
"""Print only booleans and integer counts from a JSON health document.

Workflow logs of a public repository are public: free-text strings (IDs, URLs,
messages) are dropped. Printed: booleans, integers and enum-like codes under
status/error_type keys.
"""
import json
import re
import sys

# Enum-like codes (e.g. RECONCILIATION_ERROR, PaperReconciliationError) are safe;
# free-text messages, IDs and URLs are not, so only these keys may show strings.
SAFE_STRING_KEYS = re.compile(r"(^|_)(status|error_type|sync_status)$")
SAFE_STRING_VALUE = re.compile(r"^[A-Za-z][A-Za-z0-9_:.]{0,80}$")


def flatten(node, prefix=""):
    if isinstance(node, dict):
        for k, v in node.items():
            yield from flatten(v, f"{prefix}.{k}" if prefix else str(k))
    elif isinstance(node, bool):
        yield prefix, node
    elif isinstance(node, int):
        yield prefix, node
    elif isinstance(node, str):
        leaf = prefix.rsplit(".", 1)[-1]
        if SAFE_STRING_KEYS.search(leaf) and SAFE_STRING_VALUE.match(node):
            yield prefix, node


def main() -> int:
    text = sys.stdin.read()
    try:
        start, end = text.index("{"), text.rindex("}") + 1
        doc = json.loads(text[start:end])
    except ValueError:
        print("HEALTH_JSON_UNPARSEABLE")
        return 0
    for key, value in flatten(doc):
        print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
