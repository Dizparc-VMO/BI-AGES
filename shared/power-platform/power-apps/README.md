# Power Apps

Store reusable Power Apps source and solution guidance here. Keep company-specific
screens, data mappings, roles, and business logic under
`companies/<company>/power-platform/power-apps/`.

Document whether the app is canvas or model-driven, its owner, users, data sources,
connectors, required roles, accessibility expectations, licensing, and supported
environments. Parameterize target values; use solution-aware components and
environment variables where supported. Keep connection credentials and customer
data out of source. Validate permissions at the data source, not only in the UI,
and test loading, error, empty, and denied-access states before promotion.