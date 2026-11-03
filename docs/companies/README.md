# Company Registry

Replace starter slugs and `<COMPANY_NAME>` independently for each subsidiary of
`<CUSTOMER_NAME>`. Remove unused entries; do not add unrelated customers.

| Slug | Display name | Ownership status |
| --- | --- | --- |
| `company-a` | `<COMPANY_NAME>` | Assign before implementation |
| `company-b` | `<COMPANY_NAME>` | Assign before implementation |
| `company-c` | `<COMPANY_NAME>` | Assign before implementation |

For each company, record the technical/business owner, approved source systems,
Power Apps/Automate owners and connector/DLP boundaries, shared component dependencies,
local business exceptions, permitted data flows,
retention/residency requirements, and DEV/TEST/PROD target mapping. Record identity
and permission design without credentials or sensitive data extracts.

Test permitted and denied access separately. Shared ingestion or semantic models
must not silently combine company data. Update this registry, company README,
configuration contracts, and ownership paths when a company is renamed or added.