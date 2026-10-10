import base64
import json
import os
import re

import httpx

GENERIC = {"image", "figure", "photo", "picture", "graphic", "logo", "img", "chart", "diagram", "screenshot"}
MODEL = "claude-haiku-4-5-20251001"


def ai_available():
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def heuristic_alt(alt):
    text = alt.strip()
    if not text:
        return "Failed", "Alternative text is empty."
    words = re.findall(r"\w+", text.lower())
    if len(text) < 4 or (len(words) <= 2 and all(w in GENERIC for w in words)):
        return "Failed", "Alternative text is too generic to describe the image."
    if re.search(r"\.(png|jpe?g|gif|bmp|tiff?)$", text.lower()) or re.match(r"^(img|dsc|image)[_\- ]?\d+", text.lower()):
        return "Failed", "Alternative text looks like a file name."
    if len(text) > 300:
        return "Cannot Tell", "Alternative text is very long, consider moving detail into the body text."
    return "Passed", "Alternative text is present and not obviously generic."


def _call_llm(alt, page_png):
    body = {
        "model": MODEL,
        "max_tokens": 200,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                              "data": base64.b64encode(page_png).decode()}},
                {"type": "text", "text": (
                    "This is one page of a PDF. The document author gave this alternative text for an image "
                    "on the page:\n\n" + alt + "\n\nJudge whether it is a useful description for a blind reader. "
                    "Reply with JSON only: {\"label\": \"Passed\" | \"Failed\" | \"Cannot Tell\", \"reason\": \"one sentence\"}")},
            ],
        }],
    }
    headers = {"x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01",
               "content-type": "application/json"}
    r = httpx.post("https://api.anthropic.com/v1/messages", json=body, headers=headers, timeout=30)
    r.raise_for_status()
    text = "".join(b.get("text", "") for b in r.json()["content"])
    return json.loads(re.search(r"\{.*\}", text, re.S).group(0))


def rate_alt_text(alt, page_png=None, use_ai=False):
    label, reason = heuristic_alt(alt)
    if label == "Failed" or not (use_ai and ai_available() and page_png):
        return label, reason, "rule"
    try:
        out = _call_llm(alt, page_png)
        if out.get("label") in ("Passed", "Failed", "Cannot Tell"):
            return out["label"], out.get("reason", ""), "ai"
    except Exception:
        pass
    return label, reason, "rule"
