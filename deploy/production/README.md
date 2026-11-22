# Production deployment contract

This directory is the production baseline. It intentionally contains no credentials.

- RabbitMQ is a three-node quorum cluster, uses TLS-only listeners, encrypted persistent volumes, anti-affinity, and a two-node disruption budget.
- `study-production` is isolated from the default vhost. API, publisher, and worker identities have separate least-privilege permissions.
- `ExternalSecret` supplies database URLs, signed API token secret, per-service AMQPS URLs, provider keys, and management credentials from the platform secret store.
- Worker autoscaling is driven by RabbitMQ ready-message depth; the five-minute downscale window avoids retry storms.
- Install both RabbitMQ Cluster and Messaging Topology operators and External Secrets before applying these manifests. Replace the image release and platform storage/secret-store names in the delivery overlay.
- Run all SQL migrations through `004_runtime_contract_completion.sql` before rolling application pods. Roll consumers first (they accept schemas 1 and 2), then producers.

Apply in this order: `rabbitmq-cluster.yaml`, wait for all three nodes, then
`rabbitmq-topology.yaml`, `app-runtime.yaml`, and `app-services.yaml`. The external secret must expose
`rabbitmq_api_url`, `rabbitmq_publisher_url`, and `rabbitmq_worker_url` as AMQPS URLs plus the normal
database, Redis, provider and `AUTH_TOKEN_SECRET` values.
