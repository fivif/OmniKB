---
name: docs_site
url_pattern: ^https?://(docs|developer|dev|api|reference)\.[\w.\-]+
description: Multi-page docs site — map structure first, then batch-fetch relevant pages
---

## Why two-step
Documentation sites have many pages. Fetching only the landing page misses 90%
of the content. Use get_links to discover structure, then http_get_batch.

## Recipe
1. http_get the entry URL -> get the landing/overview content
2. get_links on the same URL with max_links=60
3. From the returned links, pick 5-10 most relevant to user intent:
   - "getting started" / "quickstart" / "introduction" -> include
   - "api reference" sub-pages matching intent topics -> include
   - "blog" / "release notes" / "changelog" -> include only if intent matches
   - "login" / "sign up" / "pricing" -> skip
4. http_get_batch on the chosen URLs (cap at 10)
5. Synthesize as: overview (from step 1) + summarised key sections (from step 4)

## Stop condition
After step 4. Do not recurse into 3rd-level pages unless intent demands it.
