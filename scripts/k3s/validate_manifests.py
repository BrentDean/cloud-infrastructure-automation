"""Offline shape and safety checks; no kubeconfig, cluster, or cloud access required."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
DOCS = {}
for path in sorted((ROOT / "kubernetes" / "k3s").glob("*.yaml")):
    for document in yaml.safe_load_all(path.read_text()):
        if document is None:
            continue
        key = (document["kind"], document["metadata"]["name"])
        assert key not in DOCS, f"Duplicate object: {key}"
        DOCS[key] = document

assert set(DOCS) == {
    ("Namespace", "infra-lab"),
    ("Service", "postgres"),
    ("StatefulSet", "postgres"),
    ("Service", "three-tier-api"),
    ("Deployment", "three-tier-api"),
}, f"Unexpected Kubernetes resources: {set(DOCS)}"

for (kind, name), obj in DOCS.items():
    if kind != "Namespace":
        assert obj["metadata"]["namespace"] == "infra-lab", (kind, name)
    if kind == "Service":
        assert obj["spec"]["type"] == "ClusterIP"
        assert "nodePort" not in str(obj), name

db = DOCS[("StatefulSet", "postgres")]["spec"]
claim = db["volumeClaimTemplates"][0]
assert claim["metadata"]["name"] == "postgres-data"
assert claim["spec"]["storageClassName"] == "local-path"
assert claim["spec"]["resources"]["requests"]["storage"] == "4Gi"
assert db["replicas"] == 1
db_container = db["template"]["spec"]["containers"][0]
db_password = next(x for x in db_container["env"] if x["name"] == "POSTGRES_PASSWORD")
assert db_password["valueFrom"]["secretKeyRef"] == {"name": "db-auth", "key": "password"}

app = DOCS[("Deployment", "three-tier-api")]["spec"]
assert app["replicas"] == 2
assert app["strategy"]["rollingUpdate"]["maxUnavailable"] == 0
template = app["template"]["spec"]
assert template["securityContext"]["runAsNonRoot"]
container = template["containers"][0]
assert container["imagePullPolicy"] == "Never"
assert container["image"].startswith("localhost/three-tier-api:")
assert container["securityContext"]["readOnlyRootFilesystem"]
assert not container["securityContext"]["allowPrivilegeEscalation"]
assert container["livenessProbe"]["httpGet"]["path"] == "/healthz"
assert container["startupProbe"]["httpGet"]["path"] == "/healthz"
assert container["readinessProbe"]["httpGet"]["path"] == "/readyz"
app_password = next(x for x in container["env"] if x["name"] == "PGPASSWORD")
assert app_password["valueFrom"]["secretKeyRef"] == {"name": "db-auth", "key": "password"}
assert not any(kind == "Secret" for kind, _ in DOCS), "Never commit database credentials"

print("PASS: isolated ClusterIP Services, PostgreSQL PVC, probes, non-root API, runtime Secret references")
