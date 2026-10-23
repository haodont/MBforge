---
name: patent-search
description: Discover public patent documents or patent families for a scientific target, technology, company or known publication number. Use for external patent discovery, not for extracting facts from an already imported document or making legal/FTO conclusions.
version: 1.1.0
---

# Patent search

Use this skill when the user asks to find patents, patent families, an applicant's patent publications, or a known public patent number. The normal Patent analysis of an imported PDF is document-local and does not use this skill.

## 1. Scope and route the question

Clarify the research purpose and scope: target or technology, alternate names, applicant, date range, jurisdiction, known publication number, and whether the user needs publication documents, family leads or an official status check. Existing imported-patent analysis is document-local and does not use this skill.

## 2. Build a compact search plan

Use an exact publication number first when supplied. Otherwise form a precise query from target/technology plus its disclosed use, activity, assay or application. Prepare one alternate query using an applicant name or useful synonym. Add jurisdiction and dates only when they are part of the question. Search the local library when it helps identify an already imported document or compare evidence.

## 3. Retrieve and refine

1. Use `web_search` to find public pages. Prefer official patent-office records for bibliographic or legal details; established publication pages such as Google Patents can help discover documents and family leads. This is web discovery, not a complete patent database query.
2. Check each candidate's target/technology, applicant, jurisdiction and dates against the user's scope. If results are weak, change one query dimension once; do not repeat the same broad query.
3. Use `web_fetch` on the best publication or official-register pages. Load `identifiers-and-families` when publication/application numbers, kind codes, dates or family membership need checking.
4. Keep each country publication visible. Group records only when a displayed family identifier or verified priority relationship supports it.

## 4. Stop and report

Stop when the available records answer the discovery question, the tool budget is reached, or source access prevents further checking. Return jurisdiction, complete publication number including kind code, applicant and publication date when available, actual source URL, retrieval date, matching rationale and unresolved fields. Do not infer missing values. State that Tavily public-web discovery can miss records and is not exhaustive.

Do not conclude validity, ownership, enforceability, freedom to operate, infringement or legal status from a search snippet or a third-party page. For a legal-status question, locate an official register and report only what was checked and when. If the relevant official record is unavailable, say so.

If web search is disabled or unavailable, use local evidence only and state the external gap. Never send private library text, unpublished structures, credentials or local paths to a search service.
