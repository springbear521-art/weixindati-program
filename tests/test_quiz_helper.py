import base64
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import quiz_helper


ONE_PIXEL_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/lXcAAAAASUVORK5CYII="
)


class FakeResponse:
    def __init__(self, text="建议：第2项（一）", searched=True):
        self.text = text
        self.searched = searched

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def read(self):
        output = ([{"type": "web_search_call", "status": "completed", "action": {
            "sources": [{"url": "https://example.org/source"}]
        }}] if self.searched else [])
        output.append({"type": "message", "content": [
            {"type": "output_text", "text": self.text}
        ]})
        return json.dumps({"output": output}).encode()


class QuizHelperTests(unittest.TestCase):
    def test_vision_request_and_response(self):
        with tempfile.TemporaryDirectory() as directory:
            screenshot = Path(directory) / "question.png"
            screenshot.write_bytes(ONE_PIXEL_PNG)

            def fake_urlopen(request, timeout):
                self.assertEqual(request.full_url, quiz_helper.API_URL)
                self.assertEqual(request.get_header("Authorization"), "Bearer test-key")
                payload = json.loads(request.data)
                self.assertEqual(payload["model"], quiz_helper.DEFAULT_MODEL)
                self.assertEqual(payload["tool_choice"], "required")
                self.assertEqual(payload["tools"][0]["type"], "web_search")
                self.assertIn("web_search_call.action.sources", payload["include"])
                image = payload["input"][0]["content"][1]
                self.assertEqual(image["type"], "input_image")
                self.assertTrue(image["image_url"].startswith("data:image/png;base64,"))
                self.assertEqual(timeout, 25)
                return FakeResponse()

            with patch("quiz_helper.urllib.request.urlopen", side_effect=fake_urlopen):
                self.assertEqual(
                    quiz_helper.analyze_image(screenshot, api_key="test-key"),
                    "建议：第2项（一）\n搜索来源：\nhttps://example.org/source",
                )

    def test_rejects_missing_key_before_network(self):
        with self.assertRaisesRegex(ValueError, "OPENAI_API_KEY"):
            quiz_helper.analyze_image("question.png", api_key="")

    def test_quick_mode_only_returns_choice_number(self):
        with tempfile.TemporaryDirectory() as directory:
            screenshot = Path(directory) / "question.png"
            screenshot.write_bytes(ONE_PIXEL_PNG)

            def fake_urlopen(request, timeout):
                payload = json.loads(request.data)
                self.assertEqual(payload["max_output_tokens"], 150)
                self.assertIn("限时 12 秒", payload["input"][0]["content"][0]["text"])
                self.assertEqual(timeout, 7)
                return FakeResponse("2")

            with patch("quiz_helper.urllib.request.urlopen", side_effect=fake_urlopen):
                answer = quiz_helper.analyze_image(screenshot, api_key="test-key", quick=True, timeout=7)
            self.assertEqual(answer, "第2项")

    def test_rejects_empty_model_response(self):
        with self.assertRaisesRegex(RuntimeError, "没有返回"):
            quiz_helper.extract_text({"output": []})

    def test_rejects_response_without_completed_search(self):
        with tempfile.TemporaryDirectory() as directory:
            screenshot = Path(directory) / "question.png"
            screenshot.write_bytes(ONE_PIXEL_PNG)
            with patch("quiz_helper.urllib.request.urlopen", return_value=FakeResponse(searched=False)):
                with self.assertRaisesRegex(RuntimeError, "没有完成网页搜索"):
                    quiz_helper.analyze_image(screenshot, api_key="test-key")


if __name__ == "__main__":
    unittest.main()
