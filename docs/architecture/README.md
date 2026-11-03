# Architecture

One repository represents `<CUSTOMER_NAME>` and its subsidiaries. Shared reusable
contracts live in `shared/`; company rules and source mappings live in
`companies/<company>/`. Data sharing requires explicit authorization independently
of code reuse. Technologies are folders, environments are targets, branches are
changes, and `main` is approved source.

Before implementation, document:

- System context, business outcomes, owners, and supported platform versions.
- Source-to-consumer flows across SQL Server, Power Platform, Fabric, Power BI, and AI.
- Data grain, keys, lineage, quality, retention, and compatibility contracts.
- Company/tenant trust boundaries, permissions, RLS, and allowed data movement.
- DEV/TEST/PROD resources, identities, bindings, network and gateway dependencies.
- Power Apps/Automate owners, connectors, DLP, licensing, and solution dependencies.
- Capacity, refresh/scheduling, observability, failure recovery, and service goals.

Use medallion layers where justified, separate semantic models from presentation,
and enforce AI tool authorization outside prompts. Record significant choices
and alternatives in [decision records](../decisions/README.md). Diagrams and
examples must omit credentials and sensitive customer data.