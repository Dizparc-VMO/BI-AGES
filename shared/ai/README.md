# AI Components

Reusable components belong here; subsidiary policies, source permissions, and
domain-specific behavior belong under `companies/<company>/ai/`.

| Directory | Contents |
| --- | --- |
| `agents/` | Orchestration, tool policy, version/dependency contracts, evaluations |
| `prompts/` | Version-controlled templates, input/output contracts, evaluation cases |
| `mcp/` | MCP integrations, tool schemas, authorization, audit contracts |

Document purpose, owner, company scope, model/dependency versions, configuration
inputs, acceptance thresholds, monitoring, fallback, and rollback. Use synthetic
evaluation fixtures and test correctness, denied access, prompt injection,
company isolation, cost, latency, and regressions.

Treat retrieved content and tool outputs as untrusted. Enforce authorization in
tool/application code, validate structured arguments, restrict permissions, and
require human approval for impactful writes. Prompts alone cannot enforce access.

Do not commit secrets or sensitive customer data. Approved runtime use of such
data still requires residency, retention, provider, and logging controls. Resolve
credentials at runtime using secure identities or secret managers; keep separate
DEV/TEST/PROD identities and bindings. See
[AI instructions](../../.github/instructions/ai.instructions.md).