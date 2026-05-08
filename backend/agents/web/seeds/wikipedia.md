---
name: wikipedia_article
url_pattern: ^https?://[a-z]+\.wikipedia\.org/wiki/.+
description: Fetch Wikipedia article via REST API for clean, well-structured text
---

## Why API
Wikipedia's REST API gives clean text without nav/sidebars/cite-needed clutter.

## Recipe
1. Extract title and language from URL: https://{lang}.wikipedia.org/wiki/{title}
2. http_get https://{lang}.wikipedia.org/api/rest_v1/page/summary/{title}
   -> short summary, thumbnail, description
3. http_get https://{lang}.wikipedia.org/api/rest_v1/page/mobile-sections/{title}
   -> full article structured by sections
4. Synthesize: summary at top, then sections in order.

## Notes
- title needs URL-encoding for non-ASCII characters
- mobile-sections endpoint returns lead + remaining; merge both
