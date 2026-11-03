# Shared Components

Reusable implementation for `<CUSTOMER_NAME>` belongs here. Company-specific
source mappings, business exceptions, permissions, and presentation belong in
`companies/<company>/`. Shared code never grants cross-company data access.

| Directory | Responsibility |
| --- | --- |
| [sql-server](sql-server/README.md) | Database objects, ETL contracts, migrations |
| [power-platform](power-platform/README.md) | Reusable Power Apps and Power Automate solutions |
| [fabric](fabric/README.md) | Ingestion, orchestration, analytical data layers |
| [powerbi](powerbi/README.md) | Semantic models and report definitions |
| [ai](ai/README.md) | Agents, versioned prompts, MCP integrations |

Document each component's owner, public contract, consumers, dependencies,
configuration inputs, tests, and deployment/rollback requirements. Version
contract changes and validate affected companies before promotion. Prefer
configuration over copying implementations; keep actual company rules local.