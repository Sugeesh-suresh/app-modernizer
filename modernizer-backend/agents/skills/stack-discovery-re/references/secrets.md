# Secret stores (Google Cloud Secret Manager, AWS Secrets Manager, Vault) — what to document

Where to look:
- Client code and configuration: Secret Manager / Secrets Manager clients, Spring Cloud GCP/AWS property sources (`sm://…`, `${sm://…}`), Vault configuration, bootstrap files
- Encrypted properties (Jasypt `ENC(...)`) and where their decryption key is supplied from
- Deployment files that inject secrets as environment variables or mounted files

What to record (never a secret value — names and locations only):
- Every secret the application reads: its name/path (e.g. `projects/<project>/secrets/<name>`), which property or code reads it, and what it is used for (database password, API key, service account)
- How the application authenticates to the secret store (service account, workload identity, IAM role) and where that is configured
- Per-environment differences (project ids, secret names by profile)
- Caching/refresh of secrets, and what happens when a secret is missing
- Tests that cover secret loading and what they need to run
