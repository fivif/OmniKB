---
name: github_repo
url_pattern: ^https?://github\.com/[^/]+/[^/]+/?$
description: Fetch GitHub repository overview via REST API instead of HTML
---

## Why API not HTML
github.com page is heavily client-rendered (React) so http_get returns thin content.
The REST API gives clean JSON with name, description, stars, language, topics, etc.

## Recipe
1. Parse owner/repo from URL: https://github.com/{owner}/{repo}
2. http_get https://api.github.com/repos/{owner}/{repo}
   -> returns repo metadata (description, stars, language, default_branch, homepage)
3. http_get https://api.github.com/repos/{owner}/{repo}/readme
   -> returns README (base64-decode content field, or fetch download_url)
4. (Optional) http_get https://api.github.com/repos/{owner}/{repo}/releases?per_page=5
   -> recent releases for changelog context
5. Synthesize as markdown with:
   - Title (full_name)
   - Description
   - Stars / language / homepage
   - README content
   - Recent releases

## Stop condition
After step 3 (or step 4 if version history matters for the user intent).
