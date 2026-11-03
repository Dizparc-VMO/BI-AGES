# PROD Configuration

Reserved for reviewed non-secret production target settings. No customer
configuration is supplied. Require approved identities, least privilege,
environment gates, validated inputs, and a recorded recovery plan before use.

Deploy only the reviewed immutable artifact tested in TEST. Do not assume DEV or
TEST permissions apply. Record promotion and smoke-test evidence without exposing
secrets or customer data. See [configuration rules](../README.md).