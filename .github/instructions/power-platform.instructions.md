---
applyTo: "shared/power-platform/**,companies/*/power-platform/**"
---

# Power Platform Development

- Decide first whether an app, flow, connector, or shared contract serves the
  customer group or one subsidiary. Put reusable group-wide assets in
  `shared/power-platform/`; keep company sources, policies, and business rules
  in `companies/<company>/power-platform/`. Shared code does not grant access
  to another company's data.
- Organize assets under `power-apps/` and `power-automate/`. Prefer solution-aware
  components and supported source-control/unpack formats; preserve required
  solution metadata and document anything that cannot be safely represented in
  source control. Do not commit exported customer data or environment backups.
- Use environment variables for non-secret target-specific values and connection
  references for connectors. Keep credentials in platform-managed connections
  or approved secret stores; never commit connection secrets, access tokens,
  passwords, or personal connection exports.
- Document app/flow purpose, owner, trigger, inputs/outputs, dependencies,
  connectors, data classification, company scope, licensing assumptions, and
  operational support. Use descriptive kebab-case solution/component names.
- Review connector and data movement against tenant DLP policies. Use least
  privilege, approved service identities where suitable, and explicit company
  boundaries. Do not use personal connections as production ownership.
- Validate flow trigger conditions, retries, concurrency, idempotency, error
  paths, and sanitized run history. Validate app roles, data permissions,
  accessibility, and failure/loading states. A hidden control is not authorization.
- Promote the same reviewed solution through DEV/TEST/PROD using supported ALM
  tooling, environment variables, connection-reference bindings, and approvals.
  Test imports, connector availability, permissions, smoke cases, and rollback
  or forward-recovery steps per environment. Do not hardcode environment IDs.
- Document platform limits and licensing/capacity prerequisites; do not assume
  a connector or feature is available in every target environment.