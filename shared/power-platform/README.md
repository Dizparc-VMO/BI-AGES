# Power Platform

Reusable group-wide Power Apps and Power Automate components live here. Company
data mappings, app rules, connection bindings, and access policies belong in
`companies/<company>/power-platform/`. Reuse does not imply permission to move
data between subsidiaries.

| Directory | Responsibility |
| --- | --- |
| [power-apps](power-apps/README.md) | Canvas/model-driven app sources, components, and solution guidance |
| [power-automate](power-automate/README.md) | Cloud flow sources, triggers, connector and reliability contracts |

Prefer solution-aware source and supported unpack/pack workflows. Document
solution dependencies, owners, connector/DLP requirements, environment variables,
connection references, licensing, validation, and promotion/recovery. Keep
credentials and customer data out of exports and source control. See the
[Power Platform authoring rules](../../.github/instructions/power-platform.instructions.md).