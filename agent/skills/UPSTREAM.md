# Research skill provenance

These MBForge skills are original, compact workflows adapted from public guidance checked on 2026-10-14. No upstream skill files or executable scripts are copied into the product.

| Source | Revision checked | License | Guidance used |
|---|---|---|---|
| [K-Dense scientific-agent-skills: paper-lookup](https://github.com/K-Dense-AI/scientific-agent-skills/blob/a1043ef544e3a100c28e70a736b6cf32554d0677/skills/paper-lookup/SKILL.md) | `a1043ef544e3a100c28e70a736b6cf32554d0677` | MIT | Biomedical source routing, identifier checks, and the distinction between records, abstracts and full text. |
| [K-Dense scientific-agent-skills: citation-management](https://github.com/K-Dense-AI/scientific-agent-skills/blob/a1043ef544e3a100c28e70a736b6cf32554d0677/skills/citation-management/SKILL.md) | `a1043ef544e3a100c28e70a736b6cf32554d0677` | MIT | Conservative DOI/PMID verification and duplicate handling. |
| [djfksjd patent-search-skill](https://github.com/djfksjd/patent-search-skill/blob/6d238d4bf351863a5343d686dc5cdff71dbc1395/skills/patent-search/SKILL.md) | `6d238d4bf351863a5343d686dc5cdff71dbc1395` | MIT | Public patent discovery, identifier preservation, family checks, and research/legal boundary. |
| [USPTO ODP Natural Language Search](https://github.com/LeonardHope/USPTO-ODP-Natural-Language-Search/blob/bfccbe94df637277ea3403c7869fc384b793da6d/SKILL.md) | `bfccbe94df637277ea3403c7869fc384b793da6d` | Apache-2.0 | Reminder to distinguish public discovery from official record and legal-status verification. No ODP API integration is included. |
| [Tavily Pi extension](https://github.com/tavily-ai/skills/tree/778122e5f9c680f541eeceda5a5b36405eb7980c/skills) | `778122e5f9c680f541eeceda5a5b36405eb7980c` | MIT | Search, select returned URLs, fetch, then cite. MBForge uses its already installed official Pi extension rather than adding another Tavily client. |

MBForge-specific changes: removed shell, arbitrary file access, direct database/API claims and upstream provider assumptions; tied activation to user intent and evidence gaps; retained the application's existing `search_library`, `web_search` and `web_fetch` permission boundaries. Recheck source revisions and license files before copying upstream material in a future change.
