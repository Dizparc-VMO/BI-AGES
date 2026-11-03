# Dizparc Customer Solution Template

A reusable GitHub repository template for B2B solutions delivered by Dizparc.
Customer: `<CUSTOMER_NAME>` | Project: `<PROJECT_NAME>`

## Purpose

One repository contains the approved solution for one customer group, including
shared capabilities and isolated implementations for its subsidiaries. This
	template supports SQL Server, Microsoft Fabric, Power BI, Power Apps,
	Power Automate, AI, GitHub Copilot, Claude, and automated promotion through DEV,
	TEST, and PROD.

## Architecture Overview

- **Customer group = repository boundary.** Do not combine unrelated customers.
- Put reusable group-wide implementations in `shared/`.
- Put subsidiary-specific implementations in `companies/<company>/`.
- Represent technologies with directories, changes with branches, and deployment
  environments with external targets and non-secret configuration.
- `main` is the approved source version, not a production environment branch.
- Sharing code never implies permission to share company data or credentials.

## Repository Structure

```text
dizparc-customer-solution-template/
|-- CLAUDE.md
|-- shared/
|   |-- sql-server/
|   |   |-- database/
|   |   |   |-- schemas/
|   |   |   |-- tables/
|   |   |   |-- views/
|   |   |   |-- stored-procedures/
|   |   |   `-- functions/
|   |   |-- etl/
|   |   `-- deployment/
|   |-- power-platform/
|   |   |-- power-apps/
|   |   `-- power-automate/
|   |-- fabric/
|   |   |-- pipelines/
|   |   |-- notebooks/
|   |   |-- lakehouse/
|   |   `-- warehouse/
|   |-- powerbi/
|   |   |-- semantic-models/
|   |   `-- reports/
|   `-- ai/
|       |-- agents/
|       |-- prompts/
|       `-- mcp/
|-- companies/
|   |-- company-a/{sql-server,power-platform,fabric,powerbi,ai}/
|   |-- company-b/{sql-server,power-platform,fabric,powerbi,ai}/
|   `-- company-c/{sql-server,power-platform,fabric,powerbi,ai}/
|-- automation/{powershell,scripts,deployment}/
|-- config/{dev,test,prod}/
|-- docs/{architecture,companies,deployment,decisions}/
|-- .github/
|   |-- workflows/
|   |-- instructions/
|   |   |-- sql-server.instructions.md
|   |   |-- power-platform.instructions.md
|   |   |-- fabric.instructions.md
|   |   |-- powerbi.instructions.md
|   |   `-- ai.instructions.md
|   |-- copilot-instructions.md
|   |-- CODEOWNERS
|   `-- pull_request_template.md
|-- .gitignore
`-- README.md
```

Brace notation represents separate directories. Important directories contain
starter READMEs; empty source directories contain `.gitkeep` files. No customer
assets or runnable deployment workflows are included.

## Shared Components

Use [shared/README.md](shared/README.md) for reusable schemas, Power Platform
solutions, ingestion patterns, semantic models, and AI components. Keep shared contracts parameterized and
document consumers before changing them. Avoid copying shared implementations
into every company directory.

## Company-Specific Components

Use [companies/README.md](companies/README.md) for local source systems, business
rules, access boundaries, and report or AI variations. Rename the example
companies to stable lowercase kebab-case slugs. Record their display names,
owners, dependencies, and isolation requirements in the company registry.

## Technology Areas

| Area | Source conventions |
| --- | --- |
| SQL Server | Schema-qualified, versioned SQL DDL, ETL, and migration scripts |
| Power Platform | Solution-aware Power Apps and Power Automate sources, environment variables, connection references, and ALM |
| Fabric | Source-controlled pipeline and notebook definitions; Lakehouse and Warehouse design |
| Power BI | PBIP projects, semantic model definitions, TMDL where supported, and report definitions |
| AI | Agents, versioned prompts, MCP integrations, evaluations, and access controls |
| Automation | Repeatable validation and deployment tooling with explicit environment inputs |

See technology READMEs under `shared/` and path-scoped instructions under
`.github/instructions/`. Copilot uses the repository-wide instructions; Claude
uses [CLAUDE.md](CLAUDE.md).

## Development Workflow

1. Decide whether the change is group-wide or company-specific.
2. Branch from `main`, implement the smallest change, and add relevant tests.
3. Validate in DEV with synthetic or approved anonymized data.
4. Open a pull request using the supplied template; include business impact,
	shared consumers, security, configuration, and deployment implications.
5. Obtain review, pass required checks, and merge into protected `main`.
6. Promote the same reviewed commit or immutable artifact through TEST and PROD,
	with environment approvals and a recorded rollback strategy.

## Branch Strategy

Use short-lived branches such as `feature/customer-dimension`,
`feature/sales-report`, `feature/fabric-pipeline`, `feature/ai-agent`,
`bugfix/<description>`, and `hotfix/<description>`. Do not create permanent DEV,
TEST, PROD, SQL, Power Platform, Fabric, Power BI, or AI branches. A hotfix still requires review,
validation, and traceable promotion.

## Environment Strategy

DEV, TEST, and PROD are separate deployment targets. Store only reviewed,
non-secret settings under [config/README.md](config/README.md). Resolve target
identifiers at deployment time; use separate service identities and data access
policies per environment. Configure GitHub Environments, approval gates, and
platform permissions outside this repository. Environment directories initially
contain documentation only, not customer configuration.

See [docs/deployment/README.md](docs/deployment/README.md) for the CI/CD blueprint.
The workflows directory deliberately contains guidance, not production jobs.

## Security And Secrets

Never commit passwords, tokens, client secrets, API keys, connection strings with
credentials, production credentials, or private keys. Never embed secrets in
configuration, JSON, YAML, notebooks, SQL, PowerShell, prompts, or documentation.
Use GitHub repository/environment secrets or the target platform's secret
manager; prefer managed identities or short-lived federated authentication where
supported. Keep secret values out of logs, outputs, and AI context.

Use least privilege and explicit company isolation. Keep customer data and
notebook outputs out of Git. Enable available secret scanning and push protection;
`.gitignore` is convenience, not a security boundary. If a secret is exposed,
revoke/rotate it immediately and follow the incident process before history cleanup.

## Getting Started

1. A repository administrator marks this repository as a GitHub template in
	Settings. Use **Use this template** to create the customer group's repository.
2. Choose a lowercase kebab-case name, for example `customer-name-solution`.
3. Replace `<CUSTOMER_NAME>` and `<PROJECT_NAME>` in documentation. Map each
	`<COMPANY_NAME>` to the relevant subsidiary; rename or remove `company-a`,
	`company-b`, and `company-c`, and update documentation and ownership paths.
4. Replace CODEOWNERS team placeholders, then uncomment valid ownership rules.
	Set branch protection or rulesets and require appropriate owners to review.
5. Configure DEV, TEST, and PROD targets, GitHub Environments, secure identities,
	approvals, and secret references. Add only non-secret settings to `config/`.
6. Select the actual toolchain and pin its versions. Add CI checks and deployment
	jobs following the blueprint, validating their permissions before enabling.
7. Document the architecture and company registry before implementing assets.

### Customization Checklist

| Placeholder or starter value | Replace with |
| --- | --- |
| `<CUSTOMER_NAME>` | Customer group display name |
| `<PROJECT_NAME>` | Solution/project display name |
| `<COMPANY_NAME>` | Subsidiary display name, independently for each company |
| `<GITHUB_ORG>` | GitHub organization owning the review teams |
| `<REPOSITORY_TEAM>` | Existing team responsible for the whole repository |
| `<DATA_TEAM>` | Existing SQL Server and Fabric review team |
| `<BI_TEAM>` | Existing Power BI review team |
| `<POWER_PLATFORM_TEAM>` | Existing Power Apps and Power Automate review team |
| `<AI_TEAM>` | Existing AI review team |
| `company-a`, `company-b`, `company-c` | Actual company slugs, or remove unused examples |
| `dizparc-customer-solution-template` | New repository name in documentation |

`<company>` and `<description>` are path/branch notation, not literal names to
commit. Preserve generic guidance in AI instructions when it remains applicable.

## Documentation Requirements

Maintain [docs/README.md](docs/README.md): architecture and data flows, company
ownership and boundaries, deployment/rollback runbooks, and architecture decision
records. Document complex business rules, dependencies, configuration contracts,
tests, and operational ownership alongside their implementations. Update relevant
documentation and AI instructions in the same pull request as behavior changes.
