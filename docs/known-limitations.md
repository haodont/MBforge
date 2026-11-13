# Known limitations (declared, not scheduled)

A limitation is listed here when the source documents do something MBForge
deliberately does not represent yet. Readings that fall into one are reported
under their own `unattributed_by_reason` code, so the backlog never hides them
inside a recoverable-work bucket such as `label_not_read`.

## `designation_group_caption` — one caption names several designations

**What the documents do.** A CN patent prints a stereoisomer family as one
caption over four drawings:

```
1-P1 or 1-P2 or 1-P3 or 1-P4
```

and a fractionated example as one sentence naming a set:

```
组分1浓缩冻干得化合物I-233-A、I-233-B、I-233-C、I-233-D中的一个或两个
```

Example: CN120943813A p50 draws four stereoisomers of one constitution
(`…N[C@@H]2CCCC[C@H](…)…`, `…[C@H]2CCCC[C@@H](…)…`, `…[C@H]2CCCC[C@H](…)…`,
`…[C@@H]2CCCC[C@@H](…)…`) and captions each with a four-way list whose leading
token is that drawing's own designation.

**Why MBForge does not bind them.** The structures are drawn and read correctly.
What is missing is a representation: `1-P1` is not owned by one drawing, it is one
member of a set the document declares interchangeable, and choosing a member would
be an invention. Two existing rules are deliberately the opposite of what this
notation needs — a caption must be a bare token, and one designation names one
drawing — so the readings stay unattributed and are labelled
`designation_group_caption`.

**Status.** Declared unsupported. Supporting it needs, in this order: a
set-valued designation type in `domain/`, an "or-list" caption parser that takes
the leading token as the drawing's own designation and the rest as accepted
alternates, and a product decision on how an activity reading attached to a set
should be stored and queried (one row per member, or one row on the set).
