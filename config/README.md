# Environment Configuration

`dev/`, `test/`, and `prod/` represent deployment targets, not Git branches.
They initially contain documentation only. Do not infer real customer settings.

After target design, add reviewed non-secret settings such as server/database
names, workspace/item references, source bindings, company scope, and feature
flags. Define a schema, required values, defaults, consumers, and validation rules
alongside configuration. Environment inputs must be explicit; never silently use
DEV settings for PROD. Keep company mappings explicit and access independent.

Never store passwords, tokens, client secrets, API keys, private keys, or
credential-bearing connection strings here, even in encrypted example files.
Use GitHub repository/environment secrets or platform secret managers at runtime;
prefer managed/federated identity. A non-secret reference to a secret manager is
acceptable, but never its resolved value. Sanitize validation/deployment logs.

Promote the same reviewed commit/artifact with different reviewed target inputs.
See [deployment guidance](../docs/deployment/README.md) for approvals and checks.