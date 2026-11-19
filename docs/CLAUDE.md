# docs — agent guide

- `design.md` is the architecture: components, ownership, trust boundaries, environments,
  and how the local slice maps onto AWS. Diagrams are Mermaid so they render on GitHub
  and stay diffable. Do not add images.
- `journeys/` has one file per developer journey (new, update, decommission) with a
  sequence diagram and the exact commands/skills involved.
- `adr/` holds Architecture Decision Records: `NNNN-kebab-title.md` with *Context /
  Decision / Consequences / Alternatives considered*. ADRs are append-only. To change a
  decision, write a new ADR that supersedes the old one, and mark the old one superseded.

When a change alters behaviour described here (a new chart option, a new gate, a changed
journey step), update the matching doc in the same PR, and update `README.md` if the
quickstart or the journeys table changes.
