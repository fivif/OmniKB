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
    from config import settings  # local import avoids circular dep at module load

    preview = content[:max_chars].strip()
    if not preview:
        return []

    try:
        from langchain_core.messages import HumanMessage, SystemMessage
        from langchain_openai import ChatOpenAI

        llm = ChatOpenAI(
            model=settings.llm_model,
            api_key=settings.llm_api_key or "none",
            base_url=settings.llm_base_url or None,
            temperature=0,
            max_tokens=120,
        )

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
