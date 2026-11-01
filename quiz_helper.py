"""Vision and web-search analysis for the WeRead desktop quiz helper."""

from __future__ import annotations

import base64
import json
import mimetypes
import re
import urllib.error
import urllib.request
from pathlib import Path


API_URL = "https://api.openai.com/v1/responses"
DEFAULT_MODEL = "gpt-6-luna"
MAX_IMAGE_BYTES = 15 * 1024 * 1024
SUPPORTED_TYPES = {"image/png", "image/jpeg", "image/webp", "image/gif"}

PROMPT = """你是微信读书答题辅助工具。请读取图片中当前一道题的完整题干与所有可见选项，先用网页搜索核对题目涉及的词语或知识，再给出最可能的答案。
选项可能是文字、单个字、符号或笔画图形。请按从上到下的屏幕顺序辨认，不要把“一”“二”“三”或形似的横线混淆。
填空题需要先还原完整词语，再指出对应的是第几个选项。只根据清晰可见的内容回答；不要把看不清的字猜成确定文字。若题干或选项缺失，明确写“无法判断”。
请严格按下面四行输出，不要添加其他内容：
题目：<识别到的题干或无法判断>
选项：<按屏幕顺序列出第1项、第2项等，无法判断时写无法判断>
建议：<第几个选项及选项原文，或无法判断>
依据：<一句话说明搜索依据；不确定时说明不确定点>"""

QUICK_PROMPT = """这是限时 12 秒的微信读书选择题。识别截图中的题干和从上到下排列的选项，立即搜索题目关键字验证答案；选项可能只是“一、二、三”等笔画图形。填空题先在内部还原完整词语。
只输出正确选项的序号 1、2、3 或 4，不能确定时只输出 0。不要输出理由、标点或其他文字。"""


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
        raise RuntimeError("模型没有返回可显示的文字，请更换模型或稍后重试。")
    return result


def analyze_image(
    path: str | Path, *, api_key: str, model: str = DEFAULT_MODEL,
    timeout: int = 25, quick: bool = False,
) -> str:
    if not api_key.strip():
        raise ValueError("请先设置 OPENAI_API_KEY 环境变量。")
    payload = {
        "model": model.strip() or DEFAULT_MODEL,
        "input": [{
            "role": "user",
            "content": [
                {"type": "input_text", "text": QUICK_PROMPT if quick else PROMPT},
                {"type": "input_image", "image_url": image_data_url(path), "detail": "high"},
            ],
        }],
        "reasoning": {"effort": "none"},
        "tools": [{"type": "web_search", "search_context_size": "low"}],
        "tool_choice": "required",
        "include": ["web_search_call.action.sources"],
        "max_output_tokens": 150 if quick else 450,
        "store": False,
    }
    request = urllib.request.Request(
        API_URL,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.load(response)
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode("utf-8")).get("error", {}).get("message", "")
        except (UnicodeDecodeError, json.JSONDecodeError):
            detail = ""
        raise RuntimeError(f"接口返回 HTTP {exc.code}：{detail or exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"无法连接模型接口：{exc.reason}") from exc
    searched = any(item.get("type") == "web_search_call" and item.get("status") == "completed"
                   for item in data.get("output", []))
    if not searched:
        raise RuntimeError("本次没有完成网页搜索，不能将未核对的答案显示为搜索结果。")
    answer = extract_text(data)
    if quick:
        match = re.fullmatch(r"\s*([0-4])\s*", answer)
        if not match or match.group(1) == "0":
            return "无法判断"
        return f"第{match.group(1)}项"
    sources: list[str] = []
    for item in data.get("output", []):
        if item.get("type") != "web_search_call":
            continue
        for source in item.get("action", {}).get("sources", []):
            url = source.get("url", "")
            if url.startswith(("https://", "http://")) and url not in sources:
                sources.append(url)
    if sources:
        return answer + "\n搜索来源：\n" + "\n".join(sources[:3])
    return answer
