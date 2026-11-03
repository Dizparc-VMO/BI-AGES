# Automation

Cross-cutting tooling belongs here; technology-specific business logic remains
in `shared/` or the owning company directory.

- `powershell/`: Reusable PowerShell helpers with declared version requirements.
- `scripts/`: Other validation/build helpers with pinned runtime dependencies.
- `deployment/`: Promotion orchestration and target-specific adapters.

Each tool must declare inputs, owner, dependencies, exit codes, tests, and safe
logging behavior. Make environment and company scope explicit, validate inputs,
fail on errors, and support repeatable execution. Retrieve secrets securely at
runtime, never from tracked files or command-line literals.

No runnable deployment tooling ships in this starter. Add reviewed tooling only
after platform selection, environment provisioning, and permission design. Follow
the [deployment blueprint](../docs/deployment/README.md); keep build/validation
separate from approved deployments and document recovery for impactful changes.