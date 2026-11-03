# Microsoft Fabric

Store reusable group-wide definitions here. Company sources, rules, connections,
and isolation policies belong under `companies/<company>/fabric/`.

| Directory | Contents |
| --- | --- |
| `pipelines/` | Supported orchestration definitions, parameters, dependencies, retries |
| `notebooks/` | Source notebooks, transformations, validation, dependency contracts |
| `lakehouse/` | Supported definitions, schemas, table contracts, retention policies |
| `warehouse/` | Supported definitions, SQL objects, analytical contracts |

Use supported Fabric exports/Git serialization; retain required metadata,
including `.platform`. These directories contain sources, not customer datasets.
Use Bronze/Silver/Gold layers where useful, documenting grain, keys, lineage,
quality rules, and schema evolution. Simpler designs need a stated rationale.

Parameterize ingestion, watermarks, company scope, workspace/item references,
connections, Lakehouse attachments, and paths. Resolve target values from reviewed
non-secret configuration or supported platform variables. Use managed connections
or platform secret management; never embed credentials or production identifiers.

Document runtime versions, capacity, scheduling, monitoring, and recovery. Clear
notebook outputs before commit. Test initial/incremental loads, reruns, schema
drift, and company isolation. Validate supported SQL against the actual engine.
Promotion must rebind connections and validate permissions in each environment.
See [Fabric instructions](../../.github/instructions/fabric.instructions.md).