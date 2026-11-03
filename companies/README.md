# Company-Owned Components

Each directory represents one subsidiary of `<CUSTOMER_NAME>`, not an unrelated
customer. Rename `company-a`, `company-b`, and `company-c` to stable lowercase
kebab-case slugs, or remove unused examples. Replace `<COMPANY_NAME>` separately
in each company README and update paths and CODEOWNERS accordingly.

Company folders own local source mappings, business exceptions, security policies,
Power Apps, Power Automate flows, and presentation. Reuse shared contracts
without copying their implementations.
Adopt the corresponding shared technology subdirectories as assets are added.

Record company owners, permitted sources, connector/DLP boundaries, data boundaries,
shared dependencies, and environment targets in the [company registry](../docs/companies/README.md).
Validate company access independently; shared code is not permission to combine
subsidiary data. Document tests and rollout impact alongside every local asset.