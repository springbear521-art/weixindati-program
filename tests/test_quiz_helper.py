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
    def __init__(self, data):
        self.data = data

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def read(self):
        return json.dumps(self.data, ensure_ascii=False).encode()


def model_response(text):
    return FakeResponse({"output": [{"type": "message", "content": [
        {"type": "output_text", "text": text}
    ]}]})


class QuizHelperTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.addCleanup(self.directory.cleanup)
        self.screenshot = Path(self.directory.name) / "question.png"
        self.screenshot.write_bytes(ONE_PIXEL_PNG)

    def test_deepseek_vision_search_and_quick_answer(self):
        calls = []

        def fake_urlopen(request, timeout):
            calls.append(request.full_url)
            self.assertEqual(request.get_header("Authorization"), "Bearer test-key")
            self.assertGreater(timeout, 0)
            payload = json.loads(request.data)
            if len(calls) == 1:
                self.assertEqual(request.full_url, quiz_helper.API_URL)
                self.assertEqual(payload["model"], "deepseek-flash")
                self.assertEqual(payload["reasoning"]["effort"], "none")
                self.assertEqual(payload["text"]["format"]["type"], "json_object")
                image = payload["input"][0]["content"][1]
                self.assertTrue(image["image_url"].startswith("data:image/png;base64,"))
                return model_response(json.dumps({
                    "question": "功亏___篑", "options": ["二", "一", "三"],
                    "search_query": "功亏 篑 成语 填空",
                }, ensure_ascii=False))
            if len(calls) == 2:
                self.assertEqual(request.full_url, quiz_helper.SEARCH_URL)
                self.assertEqual(payload["query"], "功亏 篑 成语 填空")
                return FakeResponse({"results": [{"title": "成语解释", "snippet": "功亏一篑", "url": "https://example.org/idiom"}]})
            self.assertEqual(request.full_url, quiz_helper.API_URL)
            self.assertIn("功亏一篑", payload["input"][0]["content"][0]["text"])
            return model_response("2")

        with patch("quiz_helper.urllib.request.urlopen", side_effect=fake_urlopen):
            answer = quiz_helper.analyze_image(self.screenshot, api_key="test-key", quick=True, timeout=7)
        self.assertEqual(answer, "第2项")
        self.assertEqual(calls, [quiz_helper.API_URL, quiz_helper.SEARCH_URL, quiz_helper.API_URL])

    def test_rejects_missing_key_before_network(self):
        with self.assertRaisesRegex(ValueError, "DEEPSEEK_API_KEY"):
            quiz_helper.analyze_image(self.screenshot, api_key="")

    def test_no_search_results_returns_no_answer(self):
        responses = [
            model_response('{"question":"功亏___篑","options":["二","一","三"],"search_query":"功亏篑"}'),
            FakeResponse({"results": []}),
        ]
        with patch("quiz_helper.urllib.request.urlopen", side_effect=responses) as urlopen:
            answer = quiz_helper.analyze_image(self.screenshot, api_key="test-key", quick=True)
        self.assertEqual(answer, "无法判断")
        self.assertEqual(urlopen.call_count, 2)

    def test_unreadable_question_skips_search(self):
        with patch("quiz_helper.urllib.request.urlopen", return_value=model_response(
            '{"question":"","options":[],"search_query":""}'
        )) as urlopen:
            answer = quiz_helper.analyze_image(self.screenshot, api_key="test-key", quick=True)
        self.assertEqual(answer, "无法判断")
        self.assertEqual(urlopen.call_count, 1)

    def test_rejects_empty_model_response(self):
        with self.assertRaisesRegex(RuntimeError, "没有返回"):
            quiz_helper.extract_text({"output": []})

    def test_rejects_non_flash_model_with_image(self):
        with self.assertRaisesRegex(ValueError, "deepseek-flash"):
            quiz_helper.analyze_image(self.screenshot, api_key="test-key", model="deepseek-v4-pro")


if __name__ == "__main__":
    unittest.main()
