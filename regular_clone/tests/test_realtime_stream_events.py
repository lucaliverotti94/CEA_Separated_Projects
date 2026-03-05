import tempfile
import unittest
from pathlib import Path

from core.realtime_io import (
    is_source_event_payload,
    iter_jsonl_file,
    source_event_kind,
)


class RealtimeStreamEventTests(unittest.TestCase):
    def test_jsonl_empty_stream_emits_idle_event(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "stream.jsonl"
            path.write_text("", encoding="utf-8")

            gen = iter_jsonl_file(path=path, poll_s=0.0, emit_source_events=True)
            try:
                payload = next(gen)
            finally:
                gen.close()

            self.assertTrue(is_source_event_payload(payload))
            self.assertEqual(source_event_kind(payload), "idle")
            self.assertEqual(payload.get("_source"), "jsonl_file")

    def test_jsonl_invalid_line_emits_error_event(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "stream.jsonl"
            path.write_text("{invalid-json}\n", encoding="utf-8")

            gen = iter_jsonl_file(path=path, poll_s=0.0, emit_source_events=True)
            try:
                payload = next(gen)
            finally:
                gen.close()

            self.assertTrue(is_source_event_payload(payload))
            self.assertEqual(source_event_kind(payload), "error")
            self.assertEqual(payload.get("_source"), "jsonl_file")
            self.assertIn("invalid_json", str(payload.get("message", "")))

    def test_jsonl_valid_line_passes_payload_through(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "stream.jsonl"
            path.write_text('{"t_air_c": 25.0, "ph": 5.9}\n', encoding="utf-8")

            gen = iter_jsonl_file(path=path, poll_s=0.0, emit_source_events=True)
            try:
                payload = next(gen)
            finally:
                gen.close()

            self.assertFalse(is_source_event_payload(payload))
            self.assertEqual(float(payload["t_air_c"]), 25.0)
            self.assertEqual(float(payload["ph"]), 5.9)


if __name__ == "__main__":
    unittest.main()
