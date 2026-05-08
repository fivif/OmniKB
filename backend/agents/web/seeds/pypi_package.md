---
name: pypi_package
url_pattern: ^https?://pypi\.org/(project|p)/[\w.\-]+
description: Fetch PyPI package metadata via JSON API
---

## Why API
pypi.org renders project pages dynamically; the JSON API has everything in one call.

## Recipe
1. Extract package name from URL
2. http_get https://pypi.org/pypi/{name}/json
   -> all releases, current version, dependencies, project_urls, classifiers
3. (Optional) follow project_urls.Source / Homepage to GitHub repo
   -> if it goes to github.com, recurse with github_repo skill
4. Synthesize: latest version + summary + dependencies + links

## Stop condition
After step 2 for simple metadata; step 3 if user wants implementation details.
