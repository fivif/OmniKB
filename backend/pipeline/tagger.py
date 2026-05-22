"""Auto-tagger — extract 3-5 topic tags from document content via LLM.

Non-blocking: returns an empty list on any failure so the ingest pipeline
is never interrupted by tagging errors.
"""
from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)

_SYSTEM = (
    "You are a document tagger. "
    "Extract 3-5 concise topic tags from the given text. "
    "Return ONLY a JSON array of lowercase strings. "
    'Example: ["machine learning", "Python", "tutorial"]. '
    "No explanation — only the JSON array."
)


async def auto_tag(content: str, max_chars: int = 1200) -> list[str]:
    """Generate tags for *content* using the configured LLM.

    Parameters
    ----------
    content:
        The document text to analyse.
    max_chars:
        Max characters of content to send to the LLM (cost control).

    Returns
    -------
    list[str]
        Up to 5 lowercase tag strings.  Empty list on any failure.
    """
    preview = content[:max_chars].strip()
    if not preview:
        return []

    try:
        from langchain_core.messages import HumanMessage, SystemMessage
        from agents.llm import get_llm

        # Use the central factory so reasoning_content patches, extra_body
        # (e.g. enable_thinking=false) and provider normalisation all apply.
        llm = get_llm(temperature=0, max_tokens=120)

        resp = await llm.ainvoke([
            SystemMessage(content=_SYSTEM),
            HumanMessage(content=f"Text:\n{preview}"),
        ])

        raw = resp.content.strip()
        start, end = raw.find("["), raw.rfind("]") + 1
        if 0 <= start < end:
            tags = json.loads(raw[start:end])
            if isinstance(tags, list):
                return [str(t).strip().lower() for t in tags if t][:5]
    except Exception as exc:
        logger.warning("auto_tag failed: %s", exc)

    return []
