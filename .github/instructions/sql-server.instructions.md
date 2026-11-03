---
applyTo: "shared/sql-server/**,companies/*/sql-server/**"
---

# SQL Server Development

- Decide shared versus company ownership before writing SQL. Keep company source
  mappings and business exceptions local; reuse shared contracts.
- Organize DDL by object type under `database/`: `schemas/`, `tables/`, `views/`,
  `stored-procedures/`, and `functions/`. Use `etl/` for load logic and
  `deployment/` for ordered, versioned migrations and verification.
- Choose schemas by domain/responsibility (for example `core`, `sales`, `etl`),
  not by environment. Define schemas explicitly; do not assume default `dbo`.
- Use singular PascalCase tables such as `sales.Customer`, descriptive PascalCase
  columns, and descriptive `vw_`, `usp_`, and `ufn_` prefixes for views,
  procedures, and functions. Never use the system-reserved `sp_` procedure prefix.
  Name files after their qualified objects, for example `sales.Customer.sql`.
- Schema-qualify all object references. Specify column lists in queries and
  inserts; avoid `SELECT *`. Use appropriate types, nullability, primary/foreign
  keys, constraints, and indexes driven by actual access patterns.
- Prefer set-based operations over cursors/row loops. For functions, prefer
  inline table-valued functions where suitable; evaluate scalar-function costs
  against the target SQL Server version.
- Use parameterized queries; validate/quote identifiers with appropriate APIs
  when dynamic SQL is necessary. Never interpolate untrusted SQL fragments.
- Procedures normally use `SET NOCOUNT ON`; for transactional writes consider
  `SET XACT_ABORT ON`, `TRY/CATCH`, `THROW`, and correct transaction ownership.
  Do not hide errors or commit a caller-owned transaction accidentally.
- Make ETL retry-safe, document watermarks and duplicate handling, and record
  load/audit outcomes without logging sensitive values. Define data quality rules.
- Explain complex business rules, join grain, financial/time-zone assumptions,
  dependencies, and performance constraints in adjacent documentation.
- Test representative edge cases, permissions, execution plans, migration order,
  and data reconciliation using synthetic or approved anonymized data.
- Separate object source from applied migration history. Do not rewrite applied
  migrations. Declare minimum SQL Server version and compatibility requirements.
- DEV/TEST/PROD use the same versioned source and separate secure targets.
  Resolve server/database names from non-secret environment inputs. Resolve
  credentials via secure identity/secret mechanisms, never SQL literals.
- Flag destructive DDL and data-loss risks; require approved backup/restore or
  forward-recovery plans and environment gates before deployment.