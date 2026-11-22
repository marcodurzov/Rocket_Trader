#!/usr/bin/env python3
"""Print only booleans and integer counts from a JSON health document.

Workflow logs of a public repository are public: strings (IDs, URLs, messages)
are dropped; only key paths with bool values and int values are printed.
"""
import json
import sys


def flatten(node, prefix=""):
    if isinstance(node, dict):
        for k, v in node.items():
            yield from flatten(v, f"{prefix}.{k}" if prefix else str(k))
    elif isinstance(node, bool):
        yield prefix, node
    elif isinstance(node, int):
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
