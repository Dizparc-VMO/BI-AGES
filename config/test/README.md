# TEST Configuration

Reserved for reviewed non-secret integration/acceptance target settings. No
customer configuration is supplied. Promote the same reviewed artifact from DEV
and explicitly bind TEST resources, identities, and company permissions.

Validate integrations, reconciliation, access denial, and recovery before PROD
approval. Keep authentication outside Git; never fall back to DEV or PROD inputs.
See [configuration rules](../README.md).