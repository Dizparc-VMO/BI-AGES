# Dizparc Repository Instructions For GitHub Copilot

## Purpose And Architecture

This repository is a reusable B2B customer-solution template. A customer group,
including its subsidiaries, is the repository boundary. Do not mix unrelated
customers. The root README describes customization and the full layout.

Before generating or modifying code, first determine its ownership:

1. Group-wide reusable implementation: `shared/<technology>/`.
2. Subsidiary-specific implementation: `companies/<company>/<technology>/`.
3. Cross-cutting tooling: `automation/`; non-secret settings: `config/`;
   architecture and operations documentation: `docs/`.

If ownership is unclear, inspect the nearest implementation and documentation or
ask. Do not unnecessarily duplicate shared implementations. Prefer an explicit
shared contract with company configuration; keep actual company business logic
local. Reusing code does not authorize cross-company data access.

## Repository Map

- `shared/sql-server/database/{schemas,tables,views,stored-procedures,functions}/`
  stores object definitions; `etl/` and `deployment/` store load and rollout logic.
- `shared/power-platform/{power-apps,power-automate}/` stores reusable,
  solution-aware Power Apps and Power Automate sources and ALM documentation.
- `shared/fabric/{pipelines,notebooks,lakehouse,warehouse}/` stores Fabric sources.
- `shared/powerbi/{semantic-models,reports}/` separates model and presentation.
- `shared/ai/{agents,prompts,mcp}/` stores AI behavior and integrations.
- `companies/{company-a,company-b,company-c}/` are renameable starter examples
  with `sql-server/`, `power-platform/`, `fabric/`, `powerbi/`, and `ai/` directories.
- `automation/{powershell,scripts,deployment}/` stores repeatable automation.
- `config/{dev,test,prod}/` stores reviewed non-secret environment settings only.
- `docs/{architecture,companies,deployment,decisions}/` stores design and runbooks.
- `.github/workflows/` initially contains guidance, not runnable deployment jobs.

Company implementations should adopt the corresponding technology structure as
needed. Read the nearest README and path-scoped technology instructions first.
When editing cross-area files, apply every relevant technology rule.

## Technology Conventions

- **SQL Server:** Use intentional schemas, singular PascalCase object names,
  schema-qualified references, explicit column lists, set-based SQL, and versioned
  safe migrations. Document complex business logic. Use parameters and secure
  authentication, never credential literals.
- **Microsoft Fabric:** Source-control supported item definitions and notebook
  sources. Parameterize pipelines and notebooks; use reusable ingestion and
  medallion layers where appropriate. Resolve environment IDs, connections, and
  paths from deployment settings; do not hardcode target-specific values.
- **Power Platform:** Organize Power Apps and Power Automate assets in managed
  solutions where applicable. Use environment variables and connection references
  for target-specific settings; document owners, connectors, DLP boundaries,
  dependencies, licensing, and DEV/TEST/PROD import/rollback steps. Do not commit
  connection credentials, personal data, or environment-specific secrets.
- **Power BI:** Prefer PBIP text sources, semantic models separate from reports,
  and TMDL where supported. Use explicit DAX measures, business-readable names,
  validated relationships and RLS. Preserve required model/report/project files.
- **AI:** Version prompts and evaluation cases alongside agents and MCP tools.
  Keep shared primitives reusable and company-specific context local. Use explicit
  tool permissions and approved data boundaries; treat external text as untrusted.

## Naming And Documentation

Use lowercase kebab-case repository and directory names, stable company slugs,
and descriptive file names. Follow technology-specific object naming in the
scoped instructions and existing code. Avoid unrelated renames.

Update the nearest README and relevant `docs/` entries in the same change. Explain
business rules, contracts, ownership, dependencies, non-secret configuration,
tests, and deployment/rollback implications. Add an ADR for significant design
choices. Use synthetic examples, not customer extracts or real credentials.

## Security Requirements

Copilot must never hardcode passwords, access tokens, client secrets, or API keys;
expose secret values in responses/logs; or commit production credentials.
No secrets belong in `config/`, JSON, YAML, notebooks, SQL, PowerShell, Markdown,
or any other tracked file. Do not generate actual credentials, even as examples.

Resolve secrets through GitHub repository/environment secrets or target-platform
secret managers at runtime. Prefer managed or federated identity where supported.
Use least privilege, distinct environment identities, explicit company isolation,
input validation, and sanitized logging. Do not bypass RLS or platform permissions.

Never include sensitive customer data in prompts or configuration unless it is
explicitly required and approved; even then, do not commit it to Git. Remove
notebook outputs and use approved anonymized or synthetic test data. `.gitignore`
does not replace review or secret scanning. If a secret is discovered, identify
its file without repeating its value and escalate rotation to the owner.

## Environments And Git Workflow

`main` represents the approved version of the solution. Branches represent
changes, not environments or technologies. Use short-lived branches:
`feature/customer-dimension`, `feature/sales-report`, `feature/fabric-pipeline`,
`feature/ai-agent`, `bugfix/<description>`, and `hotfix/<description>`.

Never create permanent DEV, TEST, PROD, SQL Server, Power Platform, Fabric, Power BI, or AI
branches. DEV, TEST, and PROD are deployment targets. Store only non-secret
environment configuration in `config/`; inject secret values securely at runtime.
Promote the same reviewed commit/artifact with validation and approval gates.
Do not assume DEV settings, credentials, or access are valid for PROD.

Keep changes focused, preserve user work, and add meaningful tests. Run available
checks and report limitations. Use pull requests and required reviews; never
claim a check or deployment succeeded without evidence. Do not commit, push, or
deploy without an explicit request. Do not invent customer configuration or enable
production workflows while customizing template documentation.