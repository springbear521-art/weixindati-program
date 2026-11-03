import queue
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import app
from desktop_capture import WindowFrame
from quiz_helper import QuizResult


class MonitorTests(unittest.TestCase):
    def test_start_screen_is_baseline_and_first_question_triggers_once(self):
        start = WindowFrame(b"", 200, 200, bytes([0, 100]) * 64)
        question = WindowFrame(b"", 200, 200, bytes([100, 0]) * 64)
        frames = iter([start, start, question, question, question])
        stop = threading.Event()
        fake_app = type("Monitor", (), {
            "monitor_events": queue.Queue(),
            "force_capture": threading.Event(),
        })()

        def read_frame(_hwnd):
            try:
                return next(frames)
            except StopIteration:
                stop.set()
                return question

        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            screenshot = Path(directory) / "frame.png"
            screenshot.write_bytes(b"test")
            result = QuizResult("功亏___篑", ("二", "一", "三"), "一", 2)
            with patch("app.read_window_frame", side_effect=read_frame), \
                 patch("app.save_frame", return_value=screenshot) as save, \
                 patch("app.analyze_image", return_value=result) as analyze, \
                 patch.object(app, "MONITOR_INTERVAL_SECONDS", 0):
                app.QuizApp._monitor_loop(fake_app, 1, stop, 123, "test-key", "deepseek-flash")
            self.assertEqual(save.call_count, 1)
            self.assertEqual(analyze.call_count, 1)
            self.assertEqual(analyze.call_args.kwargs["seen_questions"], set())
            kinds = [event[1] for event in list(fake_app.monitor_events.queue)]
            self.assertEqual(kinds, ["analyzing", "answer"])


if __name__ == "__main__":
    unittest.main()
