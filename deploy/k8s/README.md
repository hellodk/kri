# kri Kubernetes Deployment

Kustomize base for deploying kri to any Kubernetes cluster. Designed to apply
in one command on a fresh cluster (with secrets prepared out of band).

## Quick Start

```bash
# 1. Create the image-pull secret for your private registry
#    (e.g. gitea.local — adjust if you publish to ghcr.io / docker.io)
kubectl create namespace kri
kubectl -n kri create secret docker-registry regcred \
    --docker-server=gitea.local \
    --docker-username="$USER" \
    --docker-password="$REGISTRY_TOKEN"

# 2. Generate kri-secrets — either as a plain Secret (single-cluster) or via
#    SealedSecrets (GitOps). Plain secret example:
kubectl -n kri create secret generic kri-secrets \
    --from-literal=POSTGRES_PASSWORD="$(openssl rand -hex 16)" \
    --from-literal=REDIS_PASSWORD="$(openssl rand -hex 16)" \
    --from-literal=JWT_SECRET="$(python3 -c 'import secrets; print(secrets.token_hex(32))')" \
    --from-literal=FERNET_SECRET_KEY="$(python3 -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')" \
    --from-literal=SALT_API_URL="http://salt-master.example:8080" \
    --from-literal=SALT_API_USER="kri" \
    --from-literal=SALT_API_PASSWORD="$(openssl rand -hex 16)"

# 3. Generate the worker SSH keypair Secret. Without this every Ansible
#    bootstrap / playbook run fails with "Permission denied (publickey)".
ssh-keygen -t ed25519 -f /tmp/kri-worker -N "" -C "kri-worker"
ssh-keyscan -t ed25519 salt-master.example >> /tmp/kri-worker_known_hosts
kubectl -n kri create secret generic kri-worker-ssh \
    --from-file=id_ed25519=/tmp/kri-worker \
    --from-file=id_ed25519.pub=/tmp/kri-worker.pub \
    --from-file=known_hosts=/tmp/kri-worker_known_hosts
#    Distribute /tmp/kri-worker.pub to every fleet node's ~/.ssh/authorized_keys.

# 4. Apply the Kustomize base
kubectl apply -k deploy/k8s/
```

For SealedSecrets workflows, see `secret.yaml.template` for the kubeseal recipe
and commit the resulting `sealed-secret.yaml` alongside the base, then add a
small overlay that includes both `../../` (the base) and `sealed-secret.yaml`.

## Bumping the Image Tag

Edit a single line in `kustomization.yaml`:

```yaml
images:
  - name: gitea.local/kri/kri-api
    newTag: 0.1.500       # was 0.1.415
  - name: gitea.local/kri/kri-frontend
    newTag: 0.1.500
```

Then `kubectl apply -k deploy/k8s/`. No need to edit each Deployment manifest.

## What's in the Base

| Resource | File |
|---|---|
| Namespace `kri` | `namespace.yaml` |
| ConfigMap `kri-config` | `configmap.yaml` |
| Service `kri-api` (with ClientIP affinity) | `api-service.yaml` |
| Service `kri-frontend` | `frontend-service.yaml` |
| Deployment `kri-api` | `api-deployment.yaml` |
| Deployment `kri-frontend` | `frontend-deployment.yaml` |
| Deployment `kri-worker` | `worker-deployment.yaml` |
| Deployment `kri-worker-ansible` | `worker-ansible-deployment.yaml` |
| Deployment `kri-beat` | `beat-deployment.yaml` |
| Ingress `kri` (Traefik) | `ingress.yaml` |

The base injects `imagePullSecrets: [regcred]` into every Deployment via a
Kustomize patch. The Secret `kri-secrets` is referenced but NOT included —
provision it before the first apply (see Quick Start).

## What's NOT in the Base

- `secret.yaml` / `sealed-secret.yaml` — environment-specific.
- `observability/` — depends on Prometheus Operator being installed. Apply
  separately: `kubectl apply -f deploy/k8s/observability/`.

## Building Overlays

Recommended layout for multi-environment deployments:

```
deploy/k8s/
├── kustomization.yaml         # base (this file)
├── api-deployment.yaml        # ...
└── overlays/
    ├── dev/
    │   ├── kustomization.yaml # imports ../.., patches ingress host
    │   └── sealed-secret.yaml
    └── prod/
        ├── kustomization.yaml # imports ../.., patches replicas, image tags
        └── sealed-secret.yaml
```

The base is intentionally hostname-agnostic (Ingress host `kri.local`); patch
it in your overlay.
