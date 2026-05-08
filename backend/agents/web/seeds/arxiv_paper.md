---
name: arxiv_paper
url_pattern: ^https?://(www\.)?arxiv\.org/(abs|pdf)/[\w.\-]+
description: Fetch arXiv paper metadata + abstract via Atom API; PDF text optional
---

## Why API
arxiv.org HTML works but the export.arxiv.org Atom API is faster and structured.

## Recipe
1. Extract paper id from URL (e.g. 2301.12345)
2. http_get http://export.arxiv.org/api/query?id_list={id}
   -> Atom feed: title, authors, summary, categories, published, updated
3. Optional: http_get the abs page for additional comments / DOI
4. Optional (if user wants full body): http_get the .pdf URL
   -> PDF auto-extracted by http_get tool, returns up to 20K chars

## Stop condition
After step 2 unless user intent explicitly mentions "full text" / "details".
