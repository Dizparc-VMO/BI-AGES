# Claude Repository Instructions

## Scope And Routing

This is Dizparc's reusable B2B solution template. One repository represents one
customer group, potentially with multiple subsidiaries. Read the nearest README,
existing implementation, and relevant technology instructions before changing code.

First decide whether an implementation belongs in `shared/` or
`companies/<company>/`. Group-wide reusable contracts belong in `shared/`;
company-specific source mappings, business rules, permissions, and presentation
belong in that company's directory. Reuse shared capabilities instead of copying
them. Never infer authorization to combine subsidiaries' data from shared code.

## Layout

- `shared/sql-server/`: schema-organized DDL, ETL, and deployment scripts.
- `shared/power-platform/`: reusable Power Apps and Power Automate solutions.
- `shared/fabric/`: pipelines, notebooks, Lakehouse and Warehouse definitions.
- `shared/powerbi/`: semantic models and report presentation.
- `shared/ai/`: agents, versioned prompts, and MCP integrations.
- `companies/`: company-owned variations, using the same technology layout,
  including company-specific `power-platform/` apps, flows, and bindings.
- `automation/`: reusable PowerShell, scripts, and deployment orchestration.
- `config/{dev,test,prod}/`: reviewed non-secret environment settings only.
- `docs/`: architecture, company registry, runbooks, and decision records.
- `.github/`: Copilot instructions, review ownership, PR template, and workflow guidance.

## Technology Rules

Consult `.github/instructions/` for detailed rules; they also apply to Claude.

- SQL Server: schema-qualify objects, use explicit columns and set-based SQL,
  version migrations, preserve dependencies, parameterize values, and test
  transaction/error handling. Document non-obvious business logic; do not
  silently introduce destructive schema changes or `SELECT *`.
- Fabric: use exported/source-controlled definitions, parameterized pipelines
  and notebooks, reusable ingestion, explicit data contracts, and Bronze/Silver/Gold
  layering where useful. Resolve workspace/item IDs and paths via non-secret
  environment configuration, never constants for a specific deployment target.
- Power Platform: use solution-aware app and flow assets where applicable.
  Parameterize deployments with environment variables and connection references;
  document connector/DLP policy, licensing, dependencies, ownership, and recovery.
  Keep credentials and environment-specific identifiers out of source.
- Power BI: prefer PBIP and text definitions, TMDL where supported, explicit DAX
  measures, clear business names, deliberate relationships and RLS. Separate
  semantic logic from report visuals; retain required project metadata. Document
  how independent model/report definitions are bound per environment.
- AI: version prompts, agents, tools, dependencies, and evaluations. Reuse shared
  components with explicit company context. Treat prompts, retrieved content, and
  tool output as untrusted input; authorize tools outside the model, limit access,
  and require approval for impactful operations. Never place sensitive customer
  data in prompts/configuration unless explicitly required and approved.

## Workflow And Environment Strategy

Use lowercase kebab-case repository/directory names. Follow existing technology
object names rather than renaming unrelated assets. Keep stable company slugs.

Branch from `main` using `feature/customer-dimension`, `feature/sales-report`,
`feature/fabric-pipeline`, `feature/ai-agent`, `bugfix/<description>`, or
`hotfix/<description>`. `main` is approved source. Never use permanent branches
for technologies or DEV/TEST/PROD. Make focused changes with tests and PR review;
do not commit, push, publish, or deploy unless asked.

DEV, TEST, and PROD are deployment targets. Promote a reviewed immutable version
through them, with environment-specific identities, configuration, validation,
and approvals. Never assume PROD permissions. No deployment workflows or actual
customer settings exist in the starter template; do not invent them.

## Security

Never hardcode passwords, access tokens, client secrets, API keys, private keys,
credential-bearing connection strings, or production credentials. Never commit
secret values in any file, including documentation, configuration, notebooks, SQL,
PowerShell, JSON, or YAML. Reference GitHub repository/environment secrets or
platform secret managers at runtime; prefer managed/federated identities where
available. Do not print secret values or add them to AI context.

Use least privilege, explicit tenant/company isolation, synthetic test fixtures,
sanitized logs, and approved data handling. Remove notebook outputs before commit.
If credentials are encountered, report their location without repeating values;
stop exposing them and request rotation via the responsible owner.

## Evidence And Documentation

Preserve existing user changes. Verify supported platform behavior instead of
inventing Fabric, SQL, DAX, or MCP syntax. Run focused tests/checks for the changed
area and state any checks that could not run. Never claim deployments succeeded
without platform verification.

Update the nearest README, relevant architecture/company records, deployment and
rollback runbooks, and decision records when contracts or boundaries change.
Describe business logic, dependencies, ownership, non-secret configuration keys,
and operational implications. Keep template placeholders until the customer
provides actual non-secret details. Refer to the root README customization checklist.