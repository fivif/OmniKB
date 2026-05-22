---
title: Schema
kind: meta
updated_at: ""
---

# Schema

> **The rules of this wiki.** Read this file before writing or editing
> any wiki page. Co-evolves with `purpose.md` — if something below
> isn't working for the domain, propose an edit and discuss with the
> human before changing it.

## Page types

Every page lives in exactly one of:

| Type       | Folder            | What it captures                                  |
|------------|-------------------|---------------------------------------------------|
| `entity`   | `entities/`       | A person, organisation, product, or named system. |
| `concept`  | `concepts/`       | An abstract idea, technique, theory, principle.   |
| `source`   | `sources/`        | One page per ingested source — summary + sources back-ref. |
| `query`    | `queries/`        | A user-saved good answer worth keeping.           |
| `overview` | (root)            | The single global synthesis. Regenerated.         |

## Required frontmatter

```yaml
---
title: <human-readable title>
type: <entity | concept | source | query | overview>
sources: [<source.id>, ...]   # raw sources that contributed to this page
tags: [<freeform tag>, ...]
created_at: <ISO 8601>
updated_at: <ISO 8601>
---
```

## Body conventions

- **Headings**: a top-level `# Title` matches the frontmatter title.
- **Cross-references**: use `[[entity:karpathy]]` / `[[concept:llm-wiki]]`
  syntax (type prefix optional inside the same folder).
  When the LLM mentions any other wiki entity for the first time in a
  page, it MUST link to it.
- **Citations**: every claim that came from a source must end with a
  parenthetical citation `(s-001)` referring to a value in the page's
  `sources:` frontmatter list. The LLM never invents sources.
- **Contradictions**: when a new source contradicts an existing claim,
  add a `> ⚠ Contradicts:` block with both versions and a
  `[[wikilink]]` to the page that disagrees. Do not silently overwrite.
- **Stale claims**: if a claim is superseded, append a `> 🕒 Superseded
  by …` block instead of deleting — the history is part of the value.

## Workflow rules

| Operation | Owner | What happens |
|-----------|-------|--------------|
| Ingest    | LLM   | Two-step: (1) analyse source → JSON plan, (2) write/update wiki pages, append to `log.md`, refresh `index.md`. |
| Query     | LLM   | Read `purpose.md` + `index.md` first; pull only the wiki pages required; answer with citations. |
| Lint      | LLM   | Walk the wiki: find orphans, contradictions, stale claims, missing back-references; produce a report — do NOT auto-edit pages, propose changes for human review. |
| Save-to-wiki | User | Mark a chat answer as worth keeping; LLM then files it under `queries/<slug>.md` and updates `index.md`. |

## Index & log

- `index.md` is the **content catalog**. Every page MUST appear in it
  with a one-line summary. The LLM regenerates it after every ingest.
- `log.md` is the **chronological event stream**. Format:
  `## [<ISO date>] <kind> | <one-line summary>`. Append-only; never
  rewrite history.

---

*Edit this file as the wiki grows. The LLM will follow whatever this
document says.*
