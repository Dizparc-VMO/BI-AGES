# Solution Documentation

Maintain documentation for `<CUSTOMER_NAME>` / `<PROJECT_NAME>` alongside changes.

| Directory | Responsibility |
| --- | --- |
| [architecture](architecture/README.md) | System design, contracts, flows, trust boundaries |
| [companies](companies/README.md) | Subsidiary registry, ownership, isolation, dependencies |
| [deployment](deployment/README.md) | CI/CD, environment promotion, operations and recovery |
| [decisions](decisions/README.md) | Architecture decision records and alternatives |

Every implementation should document business rules, ownership, dependencies,
configuration contracts, meaningful tests, monitoring, and deployment/rollback
impact. Update the nearest README and relevant records in the same pull request.
Use synthetic examples only: no secrets, customer extracts, or sensitive logs.