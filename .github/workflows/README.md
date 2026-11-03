# GitHub Actions Workflows

This starter intentionally contains no runnable workflow or customer-specific
production deployment. Add workflows only after selecting the toolchain and
establishing target identities, permissions, and approval policies.

## CI Blueprint

On pull requests, run scoped formatting/linting, source-definition validation,
Power Platform solution validation where configured, unit/data-contract tests,
AI evaluations, and available secret scanning. Validate
changed shared components against their company consumers. Treat generated
reports/logs as potentially sensitive before uploading artifacts.

Use minimal `GITHUB_TOKEN` permissions, pin third-party actions to reviewed full
commit SHAs, and pin tool versions. Do not expose secrets to fork PRs or run
untrusted PR code in a privileged `pull_request_target` context. Assess self-hosted
runner isolation before allowing untrusted changes to execute there.

## Deployment Blueprint

Build/package once from an approved `main` commit and record its immutable
identity. Deploy through GitHub Environments `DEV`, `TEST`, and `PROD` with
restricted branches, separate identities, and approvals where available. Configure
these controls in GitHub settings; YAML alone does not create approval policies.

Prefer supported federated/managed authentication. Otherwise inject GitHub
environment secrets or resolve platform secrets at runtime without logging them.
Read non-secret target settings from `config/`, validate them, and explicitly
rebind platform connections. Use per-target deployment concurrency to prevent
overlapping releases, smoke tests, and documented recovery procedures.

See [deployment guidance](../../docs/deployment/README.md). Do not enable PROD
jobs until target-specific safety checks and recovery have been reviewed.