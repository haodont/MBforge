---
name: literature-search
description: Find and assess public scientific literature and experimental protein structures when the user asks to find papers, check a DOI or PMID, compare published evidence, locate a PDB entry, or needs current information that the local library does not contain.
version: 1.2.0
---

# Literature search

Use this skill for public literature discovery and citation checks. Do not load it just because a question mentions a paper, DOI, target or assay when the user only asks about material already in the local library.

## 1. Scope the question

Identify the biological entity, synonyms, species, question or endpoint, date range and evidence depth needed (citation, abstract or full text). Keep user-specified limits separate from optional search refinements. For a request about existing library content, use local evidence; for explicit recent/external literature discovery, use public search. Never describe a Tavily query as a PubMed or Europe PMC database search.

## 2. Build a compact search plan

Prefer exact DOI, PMID or PMCID lookup when supplied. Otherwise make a high-precision query from the target/name plus the biological relationship or assay. Prepare one alternate query using a meaningful synonym, full target name or endpoint. Add species, date or study-type terms only when they help answer the stated question. Search the bound library first only when local deduplication or comparison is useful.

## 3. Retrieve and refine

1. Use `search_papers` for biomedical database discovery in Europe PMC. Treat its identifiers and metadata as database records; it searches Europe PMC, not every publication source.
2. For a protein structure question, use `search_structures` to query RCSB PDB. Check the polymer entity, organism, experimental method, resolution, non-polymer component IDs and InChIKeys. A PDB title, component name or short ligand code alone does not establish that the structure contains the user's exact compound. For an example label such as E23, first find a source-backed SMILES or InChIKey, then compare the deposited component identity. Return the direct PDB and mmCIF links and distinguish cryo-EM from X-ray crystallography and predicted models.
3. Use `web_search` with short public terms for sources outside Europe PMC/RCSB, and use `web_fetch` on the best primary-source pages or accessible full text. Load `biomedical-sources` when source type or access level is unclear; load `citation-rules` when identifiers, versions or citation metadata conflict.
4. Check whether each candidate matches the target, species, endpoint and requested period. If the first result set is weak, change one query dimension once; do not repeat the same query with cosmetic wording changes.
5. Distinguish a database record, search snippet, indexed abstract and accessible full text. If fetching fails or text is truncated, say exactly what could be inspected.

## 4. Stop and report

Stop when reliable sources answer the user's question, the available search/fetch budget is reached, or source access blocks further verification. Return title, authors when available, year, DOI/PMID/PMCID only when verified, actual source URL, retrieval date and relevance. Preserve species, assay system, endpoint, comparator, value, operator and unit. Keep human MRGPRX2 separate from mouse Mrgprb2, and do not combine incompatible activity measurements. State the search scope and remaining gap; never invent metadata or claim exhaustive coverage.

If web search is disabled or unavailable, use local evidence only and state the external gap. Never send private library text, unpublished structures, credentials or local paths to a search service.
