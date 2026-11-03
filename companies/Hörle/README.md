# <COMPANY_NAME>

Starter subsidiary `company-c` in `<CUSTOMER_NAME>` / `<PROJECT_NAME>`.
Rename this directory to the agreed company slug or remove it if unused.

- `sql-server/`: Company schemas, source mappings, ETL, and migrations.
- `power-platform/`: Company Power Apps, Power Automate flows, and solution bindings.
- `fabric/`: Company ingestion, transformations, definitions, and bindings.
- `powerbi/`: Company model rules, RLS, reports, and presentation.
- `ai/`: Company policies, prompts, agents, and scoped integrations.

Reuse shared implementations through explicit contracts. Before implementation,
record the owner, approved sources, access boundaries, shared dependencies,
environment mapping, tests, and recovery requirements in the
[company registry](../../docs/companies/README.md). No customer data or secrets
belong in this directory.