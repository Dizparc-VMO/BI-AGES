## Summary

Describe the change, business outcome, and linked issue or decision record.

## Ownership And Impact

- Scope: shared / company-specific (identify company) / automation / documentation
- Technologies and shared consumers affected:
- Data contracts, dependencies, or breaking changes:

## Validation

List commands/checks, results, environment, and safe test data used. Explain any
checks not run. Include SQL migration/reconciliation, Power Platform solution
import/app/flow/connector tests, Fabric rerun/quality checks, Power BI
DAX/RLS/report tests, or AI evaluations as applicable.

## Deployment And Recovery

- Commit/artifact and DEV -> TEST -> PROD promotion approach:
- Non-secret configuration changes and secure runtime secret references:
- Required approvals, permission changes, downtime, and operational owner:
- Rollback/forward recovery and data-loss risks:
- Monitoring and post-deployment smoke tests:

## Checklist

- [ ] Correct shared/company location; no unnecessary shared duplication.
- [ ] Tests and applicable checks pass, or limitations are documented above.
- [ ] No secrets, credentials, sensitive customer data, or notebook outputs committed.
- [ ] Company isolation and least-privilege access reviewed.
- [ ] No hardcoded environment targets; configuration and rebinding documented.
- [ ] Destructive/breaking changes and recovery are explicitly reviewed.
- [ ] Relevant READMEs, runbooks, company records, and ADRs updated.
- [ ] Appropriate owners have reviewed; no permanent environment branch introduced.