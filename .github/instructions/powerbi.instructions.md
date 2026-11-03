---
applyTo: "shared/powerbi/**,companies/*/powerbi/**"
---

# Power BI Development

- Decide whether models/reports are group-wide or company-owned first. Reuse a
  shared semantic model when appropriate without weakening company access rules.
- Prefer PBIP projects and supported text definitions. Keep required `.pbip`,
  `.pbir`, `.pbism`, `.platform`, JSON, and TMDL files tracked. Use TMDL where the
  model/tool version supports it; do not convert formats without validation.
- Put reusable semantic model projects in `semantic-models/` and report projects
  in `reports/`. Put project entry files where relative references resolve; do not
  duplicate models to make folder layout convenient. Document independent report
  model bindings and test opening the full PBIP project after moving files.
- Keep model relationships, transformations, DAX, formats, and RLS in the model;
  keep visual layout, navigation, and presentation in report definitions. Avoid
  hiding reusable business calculations in report-only visual calculations.
- Prefer star schemas, explicit grain, appropriate data types, a deliberate date
  table, and single-direction relationships unless a documented exception applies.
- Use explicit DAX measures with meaningful business names and format strings,
  rather than implicit aggregation. Explain complex filter context and business
  assumptions; test totals, blanks, zero denominators, and slicer behavior.
- Use business-readable table/column/measure names, consistent casing and display
  folders, and descriptive model/report project names such as `Sales.SemanticModel`
  and `Sales.Report`. Hide technical fields that users should not aggregate.
- Parameterize non-secret source bindings and document Import, DirectQuery, or
  Direct Lake choices, refresh requirements, gateway/connection dependencies,
  and capacity assumptions. Never store credentials in M, DAX, or project files.
- DEV/TEST/PROD require explicit source/semantic-model rebinding and validation of
  refresh, relationships, RLS/OLS, permissions, and report connections. Do not
  hardcode production workspace/model IDs in portable source.
- Test positive and negative company-access scenarios; report filters are not a
  security boundary. Validate accessibility, visual interactions, and performance.
- Keep local `.pbi` caches/settings and binary `.pbix`/`.pbit` exports out of Git
  under the default policy. Inspect generated sources for embedded sensitive data,
  endpoints, or credentials before committing; ignore rules do not sanitize them.