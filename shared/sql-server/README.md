# SQL Server

Store group-wide SQL Server sources here; company-owned objects and mappings
belong under `companies/<company>/sql-server/` using the same layout as needed.

| Directory | Contents |
| --- | --- |
| `database/schemas/` | Explicit domain schema definitions and permissions |
| `database/tables/` | Tables, keys, constraints, and indexes |
| `database/views/` | Views with documented grain and explicit column lists |
| `database/stored-procedures/` | Parameterized procedures and transaction contracts |
| `database/functions/` | Functions with documented cost and determinism |
| `etl/` | Retry-safe loads, watermarks, reconciliation, audit logic |
| `deployment/` | Ordered versioned migrations, verification, recovery guidance |

Use schema-qualified names, singular PascalCase tables, and descriptive `vw_`,
`usp_`, and `ufn_` prefixes. Name files after qualified objects, such as
`sales.Customer.sql`. Prefer set-based SQL and explicit columns; avoid `SELECT *`.
Document complex rules, dependencies, and minimum SQL Server compatibility.

Keep desired object definitions separate from migration history. Never rewrite
applied migrations. Test constraints, edge cases, transaction ownership, execution
plans, reruns, and permissions on synthetic data. Destructive changes require
explicit approval and a tested backup/restore or forward-recovery plan.

Promote the same source through DEV/TEST/PROD with target names supplied by
non-secret environment settings and authentication supplied securely at runtime.
See [deployment guidance](../../docs/deployment/README.md) and the
[SQL instructions](../../.github/instructions/sql-server.instructions.md).