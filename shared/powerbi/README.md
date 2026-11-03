# Power BI

Keep reusable semantic logic separate from report presentation. Company models,
security policies, and presentation variations belong under
`companies/<company>/powerbi/` when not genuinely shared.

| Directory | Contents |
| --- | --- |
| `semantic-models/` | PBIP semantic model sources, TMDL where supported, DAX, relationships, RLS |
| `reports/` | Report definitions, visuals, navigation, supported PBIP entry files |

Preserve required `.pbip`, `.pbir`, `.pbism`, `.platform`, JSON, and TMDL sources.
Place PBIP entry files so relative model/report references resolve; document the
binding for independently deployed reports. Do not duplicate a model to fit the
directory layout. Open the complete project to validate references after moves.

Use explicit DAX measures, business-readable names, documented grain, deliberate
relationships, and appropriate formats. Keep calculations and access rules in
models, layout in reports. Report filters are not a security boundary.

Document refresh modes, source parameters, gateways, dependencies, and owners.
For DEV/TEST/PROD, rebind sources and models explicitly and test refresh, totals,
blank handling, relationships, positive/negative RLS access, accessibility, and
performance. No credentials belong in M, DAX, or project definitions. Local
caches and binary exports are ignored; source definitions remain tracked.
See [Power BI instructions](../../.github/instructions/powerbi.instructions.md).