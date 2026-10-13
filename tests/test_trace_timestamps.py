"""Offline timestamp checks; never import upload/client/experiment entry points."""

import ast
import math
import unittest
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SOURCE = Path(__file__).resolve().parents[1] / "scripts/upload_jsonl_to_langfuse.py"


def load_timestamp_converter():
    tree = ast.parse(SOURCE.read_text())
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_to_ns"]
    if len(nodes) != 1:
        raise AssertionError("Expected exactly one timestamp converter")
    module = ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[]))
    namespace = {"Any": Any, "datetime": datetime, "timezone": timezone, "math": math}
    exec(compile(module, str(SOURCE), "exec"), namespace)
    return namespace["_to_ns"]


class TraceTimestampTests(unittest.TestCase):
    def setUp(self):
        self.to_ns = load_timestamp_converter()

    def test_nonfinite_numbers_are_missing(self):
        for value in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=value):
                self.assertIsNone(self.to_ns(value))

    def test_numeric_overflow_is_missing(self):
        self.assertIsNone(self.to_ns(1e308))

    def test_booleans_are_not_timestamps(self):
        for value in (True, False):
            with self.subTest(value=value):
                self.assertIsNone(self.to_ns(value))

    def test_valid_unix_numbers(self):
        self.assertEqual(self.to_ns(0), 0)
        self.assertEqual(self.to_ns(1.5), 1_500_000_000)

    def test_rfc3339_offset(self):
        self.assertEqual(self.to_ns("1970-01-01T01:00:01+01:00"), 1_000_000_000)

    def test_aware_datetime(self):
        self.assertEqual(self.to_ns(datetime(1970, 1, 1, tzinfo=timezone.utc)), 0)

    def test_naive_string_is_utc(self):
        self.assertEqual(self.to_ns("1970-01-01T00:00:01"), 1_000_000_000)

    def test_invalid_values_are_missing(self):
        for value in (None, "invalid", [], {}):
            with self.subTest(value=value):
                self.assertIsNone(self.to_ns(value))


if __name__ == "__main__":
    unittest.main()
