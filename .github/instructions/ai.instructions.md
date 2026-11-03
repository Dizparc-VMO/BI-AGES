---
applyTo: "shared/ai/**,companies/*/ai/**"
---

# AI Development

- Put reusable agents, prompt templates, evaluations, and MCP primitives under
  `shared/ai/`. Put company policies, domain-specific behavior, and integrations
  under `companies/<company>/ai/`. Explicitly bind company context; do not
  duplicate a shared agent just to change a parameter.
- `agents/` owns orchestration and tool policy, `prompts/` owns version-controlled
  instructions/templates, and `mcp/` owns Model Context Protocol servers/clients,
  tool contracts, and integration guidance.
- Version prompts in reviewable text alongside code. Document purpose, inputs,
  outputs, variable contracts, model assumptions, and evaluations. Never rely on
  unrecorded portal edits as the authoritative prompt version.
- Use descriptive kebab-case component names and explicit releases/commit IDs.
  Record prompt/model/dependency versions used for evaluations and deployments.
- Treat user text, retrieved documents, prompt variables, and tool output as
  untrusted. Enforce authorization in application/tool code, not only in prompts.
  Restrict tools to least privilege; require human approval for impactful writes.
- Validate tool arguments and structured outputs against schemas. Use timeouts,
  bounded retries, concurrency limits, cost budgets, and safe error handling.
- MCP tools need documented schemas, authentication/authorization, company scope,
  and audit behavior. Do not expose unrestricted shell, SQL, filesystem, or network
  tools. Test denied access and prompt-injection attempts.
- Never hardcode passwords, tokens, client secrets, API keys, or credentials.
  Resolve them through secure runtime identity or secret managers. Redact logs,
  traces, evaluation outputs, and telemetry; never echo secrets.
- Avoid sensitive customer data in prompts/configuration unless explicitly required
  and approved. Do not commit it even when approved for runtime processing. Use
  synthetic/redacted fixtures; document consent, data residency, retention, and
  provider requirements when applicable.
- Parameterize non-secret model endpoints, deployment names, company IDs, and
  feature flags. Keep DEV/TEST/PROD identities and data access separate.
- Test correctness, groundedness, refusal/denied access, isolation, regressions,
  latency, and cost. Record acceptance thresholds before production rollout.
  Document monitoring, owner, fallback behavior, and rollback to a prior version.