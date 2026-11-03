# Nigrani Helm chart

```bash
helm install nigrani ./deploy/helm/nigrani -n monitoring --create-namespace \
  --set config.datasources.prometheus=http://prometheus-server.monitoring.svc.cluster.local:9090
```

See [values.yaml](values.yaml) for every setting and the "Kubernetes (Helm)" section of the
[main README](../../../README.md#d-kubernetes-helm) for the common ones.

| | |
|---|---|
| Replicas | Always 1 (one SQLite file), strategy `Recreate` |
| Admin password | `auth.password`, `auth.existingSecret`, or generated once and kept across upgrades |
| Configuration | `config:` is `nigrani.yaml`; secrets go in `extraEnv` / `extraEnvFrom` and are written `${NAME}` |
| Data | A PersistentVolumeClaim, kept by `helm uninstall` |
| Kubernetes integration | `rbac.create: true` and `config.kubernetes: {}` |
| Security | Non-root, read-only root filesystem, no capabilities; no service account token unless `rbac.create` |
