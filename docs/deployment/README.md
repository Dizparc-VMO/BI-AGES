# Deployment And Operations

This is a CI/CD blueprint, not an enabled deployment pipeline. Platform targets,
toolchain versions, identities, and customer settings must be designed and
approved before workflows are introduced. No production jobs ship in the template.

## Validation And Promotion

1. On pull requests, validate source formats, dependencies, unit/contract tests,
   secret scanning, documentation, and company isolation with synthetic fixtures.
   Do not expose secrets to untrusted pull requests or run their code with
   privileged deployment credentials.
2. After review, merge into protected `main`. Build once; record commit, artifact
   digest/version, dependency versions, and validation evidence.
3. Deploy to DEV with explicit reviewed target inputs and a dedicated identity.
   Run technology-specific smoke checks and inspect sanitized logs.
4. Promote the same immutable version to TEST. Validate integrations, access
   boundaries, reconciliation, performance, and recovery with approval evidence.
5. Promote that version to PROD only with configured environment approvals and
   least-privilege permissions. Serialize conflicting deployments per target.
6. Record target, approver, version, time, and smoke-test results. Halt promotion
   on failures; never silently substitute another environment's configuration.

Configure GitHub Environments, protection rules, required reviews, and platform
permissions outside source control. Prefer short-lived federated authentication;
otherwise retrieve secrets through approved runtime mechanisms. Set minimal
workflow permissions and review/pin third-party actions before enabling jobs.

## Technology Gates

| Area | Required validation and binding |
| --- | --- |
| SQL Server | Compatibility, migration order, constraints, transactions, reconciliation, backup/recovery |
| Power Platform | Solution unpack/validation, environment variables, connection references, connector/DLP review, app and flow smoke tests |
| Fabric | Supported definitions, target connections/attachments, reruns, quality, permissions |
| Power BI | PBIP references, source/model rebinding, refresh, RLS/OLS, report interactions |
| AI | Versioned prompts/model dependencies, evaluations, denied tool access, isolation, cost limits |

## Recovery And Operations

Before deploying, document owner/on-call routing, monitoring, prerequisites,
expected duration, failure triggers, and recovery steps. SQL changes may need
restore or a forward migration rather than reverting files; verify backups and
dependencies before destructive changes. Fabric reruns need retry-safe writes
and documented watermarks. Power BI and AI need prior supported versions plus
verified bindings and permissions. Do not claim rollback is automatic.

Exercise recovery in a safe target, define acceptable data loss/downtime, and
record evidence. For incidents, stop affected automation, preserve sanitized
audit evidence, notify owners, and rotate exposed credentials through the approved
process. Never paste secret values into logs, issues, or runbooks.