"""Offline checks for AWS three-tier k3s workload contracts; no cloud access."""

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
    ("Service", "three-tier-api"),
    ("Deployment", "three-tier-api"),
    ("PersistentVolumeClaim", "lab-evidence"),
    ("Pod", "pvc-evidence"),
}, f"Unexpected or missing Kubernetes resources: {set(DOCS)}"

for (kind, name), obj in DOCS.items():
    if kind != "Namespace":
        assert obj["metadata"]["namespace"] == "infra-lab", (kind, name)

service = DOCS[("Service", "three-tier-api")]["spec"]
assert service["type"] == "NodePort"
assert service["ports"][0]["nodePort"] == 30080
assert service["ports"][0]["targetPort"] == 8000
assert service["selector"] == {"app": "three-tier-api"}

app = DOCS[("Deployment", "three-tier-api")]["spec"]
assert app["replicas"] == 2
assert app["strategy"]["rollingUpdate"]["maxUnavailable"] == 0
template = app["template"]["spec"]
assert template["securityContext"]["runAsNonRoot"]
container = template["containers"][0]
assert container["imagePullPolicy"] == "Never"
assert container["image"] == "localhost/three-tier-api:pr2"
assert container["securityContext"]["readOnlyRootFilesystem"]
assert not container["securityContext"]["allowPrivilegeEscalation"]
assert container["livenessProbe"]["httpGet"]["path"] == "/healthz"
assert container["startupProbe"]["httpGet"]["path"] == "/healthz"
assert container["readinessProbe"]["httpGet"]["path"] == "/readyz"
environment = {entry["name"]: entry for entry in container["env"]}
assert environment["PGHOST"]["valueFrom"]["configMapKeyRef"] == {
    "name": "db-endpoint", "key": "host"
}
assert environment["PGPASSWORD"]["valueFrom"]["secretKeyRef"] == {
    "name": "db-auth", "key": "password"
}
assert environment["PGDATABASE"]["value"] == "labdb"
assert environment["PGUSER"]["value"] == "labuser"

claim = DOCS[("PersistentVolumeClaim", "lab-evidence")]["spec"]
assert claim["storageClassName"] == "local-path"
assert claim["resources"]["requests"]["storage"] == "1Gi"
assert claim["accessModes"] == ["ReadWriteOnce"]
pod = DOCS[("Pod", "pvc-evidence")]["spec"]
assert pod["volumes"][0]["persistentVolumeClaim"]["claimName"] == "lab-evidence"
assert pod["containers"][0]["volumeMounts"][0]["mountPath"] == "/data"

assert not any(kind in {"StatefulSet", "Secret", "ConfigMap"} for kind, _ in DOCS), (
    "PostgreSQL stays on EC2 #3; secrets and private DB IP are runtime-only"
)

print("PASS: private-tier NodePort, independent DB ConfigMap, non-root API, probes, runtime Secret, local-path PVC")
