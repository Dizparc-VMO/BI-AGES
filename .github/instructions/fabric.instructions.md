---
applyTo: "shared/fabric/**,companies/*/fabric/**"
---

# Microsoft Fabric Development

- Route reusable group ingestion/transformation logic to `shared/fabric/` and
  company-specific sources, business rules, and bindings to the company directory.
- Keep supported item definitions and metadata in Git. Use Fabric-supported
  exports/serialization rather than inventing pipeline or item JSON schemas.
  Preserve item folders and `.platform` metadata; exclude data and local caches.
- `pipelines/` contains orchestration, dependency handling, retry policies, and
  parameters. `notebooks/` contains transformations and focused validation.
  `lakehouse/` and `warehouse/` contain design, schemas, SQL, and supported
  definitions, not exported customer datasets.
- Use Bronze (raw), Silver (validated/conformed), and Gold (business-ready) layers
  where applicable; document when a simpler architecture is justified. Define
  table grain, keys, schema evolution, retention, lineage, and quality contracts.
- Build reusable ingestion patterns with source/destination parameters, explicit
  connection references, watermarks, retry-safe writes, and audit metrics. Do not
  assume shared ingestion authorizes cross-company data movement.
- Parameterize workspace/item IDs, Lakehouse attachments, Warehouse connections,
  OneLake paths, and company scope. Resolve non-secret values from environment
  settings or supported platform variables during deployment/runtime. Never
  hardcode environment-specific IDs, URLs, or paths in source.
- Distinguish SQL Server, Spark SQL, Lakehouse SQL endpoint, and Warehouse SQL
  capabilities. Verify supported syntax and write paths against the target engine.
- Keep notebook parameters explicit; declare runtime and dependency versions.
  Avoid implicit session state, unnecessary collect-to-driver operations, and
  outputs containing data, tokens, or sensitive diagnostics. Clear outputs before
  committing. Use managed connections or supported secret management.
- Document scheduling, dependencies, concurrency, capacity assumptions, monitoring,
  ownership, and failure recovery. Test incremental loads, reruns, schema drift,
  data quality, and company isolation on safe fixtures.
- Use separate DEV/TEST/PROD workspaces/targets and secure identities. Promote
  reviewed definitions with explicit connection rebinding, permissions, and
  smoke tests; source control alone does not provision or secure resources.