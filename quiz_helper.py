"""DeepSeek vision, web search, and answer selection for the WeRead quiz."""

from __future__ import annotations

import base64
import json
import logging
import mimetypes
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path


API_URL = "https://api.deepseek.com/responses"
SEARCH_URL = "https://api.deepseek.com/v1/tools/search"
DEFAULT_MODEL = "deepseek-flash"
MAX_IMAGE_BYTES = 15 * 1024 * 1024
SUPPORTED_TYPES = {"image/png", "image/jpeg", "image/webp", "image/gif"}
LOGGER = logging.getLogger("weread_quiz")

VISION_PROMPT = """读取微信读书截图中当前一道题及从上到下的全部选项。选项可能是单字、笔画或符号，尤其要分清“一、二、三”。
只返回 JSON 对象，格式为 {"question":"题干", "options":["第一项","第二项"], "search_query":"用于搜索答案的简短中文关键词"}。
填空题的 search_query 应包含空格前后的字和“填空”或“成语”。看不清题干或选项时，对应字段留空；不要编造。"""

QUICK_PROMPT = """这是限时 12 秒的选择题。根据题干、选项和已搜索到的网页摘要，判断从上到下第几个选项正确。
只输出 1、2、3 或 4；搜索结果不足以判断时只输出 0。不要输出其他文字。"""

DETAIL_PROMPT = """根据已识别题目和网页搜索摘要给出建议。若证据不足，明确写无法判断。
严格按四行输出：
题目：<题干>
选项：<从上到下的选项>
建议：<第几个选项及原文，或无法判断>
依据：<一句话解释搜索证据>"""


@dataclass(frozen=True)
class QuizResult:
    question: str
    options: tuple[str, ...]
    answer_text: str
    answer_index: int | None = None
    details: str = ""
    duplicate: bool = False


def question_key(question: str, options: tuple[str, ...]) -> str:
    """Normalize OCR whitespace and punctuation to avoid searching one question twice."""
    return re.sub(r"[\W_]+", "", question, flags=re.UNICODE) + "|" + "|".join(options)


def image_data_url(path: str | Path) -> str:
    image_path = Path(path)
    raw = image_path.read_bytes()
    if not raw:
        raise ValueError("截图文件是空的。")
    if len(raw) > MAX_IMAGE_BYTES:
        raise ValueError("截图超过 15 MB，请裁剪到当前题目后重试。")
    mime = mimetypes.guess_type(image_path.name)[0]
    if mime not in SUPPORTED_TYPES:
        raise ValueError("只支持 PNG、JPEG、WEBP 或 GIF 截图。")
    return f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"


def extract_text(response: dict) -> str:
    parts: list[str] = []
    for item in response.get("output", []):
        if item.get("type") != "message":
            continue
        for content in item.get("content", []):
            if content.get("type") == "output_text" and isinstance(content.get("text"), str):
                parts.append(content["text"])
    result = "\n".join(parts).strip()
    if not result:
        raise RuntimeError("模型没有返回可显示的文字，请稍后重试。")
    return result


def _post_json(url: str, payload: dict, api_key: str, deadline: float) -> dict:
    remaining = deadline - time.monotonic()
    if remaining < 0.5:
        raise TimeoutError("本题剩余时间不足，已停止请求。")
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=remaining) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode("utf-8")).get("error", {}).get("message", "")
        except (UnicodeDecodeError, json.JSONDecodeError):
            detail = ""
        raise RuntimeError(f"DeepSeek 接口返回 HTTP {exc.code}：{detail or exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"无法连接 DeepSeek 接口：{exc.reason}") from exc


def _read_question(image_url: str, api_key: str, model: str, deadline: float) -> dict:
    response = _post_json(API_URL, {
        "model": model,
        "input": [{"role": "user", "content": [
            {"type": "input_text", "text": VISION_PROMPT},
            {"type": "input_image", "image_url": image_url, "detail": "high"},
        ]}],
        "reasoning": {"effort": "none"},
        "text": {"format": {"type": "json_object"}},
        "max_output_tokens": 300,
    }, api_key, deadline)
    try:
        parsed = json.loads(extract_text(response))
    except json.JSONDecodeError as exc:
        raise RuntimeError("DeepSeek 没有返回可解析的题目 JSON。") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError("DeepSeek 返回的题目格式不正确。")
    return parsed


def _search_evidence(question: dict, api_key: str, deadline: float) -> list[dict]:
    query = str(question.get("search_query") or question.get("question") or "").strip()[:128]
    if not query:
        return []
    data = _post_json(SEARCH_URL, {"query": query, "count": 3, "need_content": False}, api_key, deadline)
    results = data.get("results", [])
    return [item for item in results if isinstance(item, dict) and item.get("snippet")]


def analyze_image(
    path: str | Path, *, api_key: str, model: str = DEFAULT_MODEL,
    timeout: float = 25, quick: bool = False, seen_questions: set[str] | None = None,
) -> QuizResult:
    if not api_key.strip():
        raise ValueError("请先在程序中保存 DeepSeek API 密钥。")
    if model.strip() != DEFAULT_MODEL:
        raise ValueError("当前识图流程只支持 deepseek-flash，请把模型改回 deepseek-flash。")
    deadline = time.monotonic() + timeout
    image_url = image_data_url(path)
    stage_started = time.monotonic()
    question = _read_question(image_url, api_key, model, deadline)
    LOGGER.info("Vision completed elapsed=%.2fs", time.monotonic() - stage_started)
    stem = str(question.get("question") or "").strip()
    options = question.get("options")
    if not stem or not isinstance(options, list) or not 2 <= len(options) <= 4:
        return QuizResult(stem, (), "无法判断")
    options = [str(option).strip() for option in options]
    if any(not option for option in options):
        return QuizResult(stem, tuple(options), "无法判断")
    options_tuple = tuple(options)
    key = question_key(stem, options_tuple)
    if seen_questions is not None:
        if key in seen_questions:
            return QuizResult(stem, options_tuple, "", duplicate=True)
        seen_questions.add(key)
    stage_started = time.monotonic()
    results = _search_evidence(question, api_key, deadline)
    LOGGER.info("Search completed results=%d elapsed=%.2fs", len(results), time.monotonic() - stage_started)
    if not results:
        return QuizResult(stem, options_tuple, "无法判断")
    evidence = [{"title": str(item.get("title", ""))[:120],
                 "snippet": str(item.get("snippet", ""))[:350],
                 "url": str(item.get("url", ""))}
                for item in results[:3]]
    stage_started = time.monotonic()
    response = _post_json(API_URL, {
        "model": model,
        "input": [{"role": "user", "content": [{"type": "input_text", "text":
            (QUICK_PROMPT if quick else DETAIL_PROMPT) + "\n题目和搜索结果：\n" +
            json.dumps({"question": stem, "options": options, "search_results": evidence}, ensure_ascii=False)
        }]}],
        "reasoning": {"effort": "none"},
        "max_output_tokens": 40 if quick else 350,
    }, api_key, deadline)
    LOGGER.info("Decision completed elapsed=%.2fs", time.monotonic() - stage_started)
    answer = extract_text(response)
    if quick:
        match = re.fullmatch(r"\s*([0-4])\s*", answer)
        if not match or match.group(1) == "0" or int(match.group(1)) > len(options):
            return QuizResult(stem, options_tuple, "无法判断")
        index = int(match.group(1))
        return QuizResult(stem, options_tuple, options[index - 1], index)
    sources = [item["url"] for item in evidence if item["url"].startswith(("https://", "http://"))]
    details = answer + ("\n搜索来源：\n" + "\n".join(sources) if sources else "")
    match = re.search(r"建议：第\s*([1-4])\s*个?选项", answer)
    index = int(match.group(1)) if match and int(match.group(1)) <= len(options) else None
    return QuizResult(stem, options_tuple, options[index - 1] if index else "无法判断",
                      index, details)
