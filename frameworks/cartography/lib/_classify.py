"""frameworks/cartography/lib/_classify - the pure classification core (no I/O).

Two classifiers over one input: a VM's declared Kubernetes labels.

* :func:`classify_from_labels` reads the recommended labels as DECLARATIONS: a present
  ``app.kubernetes.io/part-of`` names the application at high confidence, the component label
  names the tier, and the namespace name yields the observed environment by token match.
  Declared intent beats inference, which is why this lens runs before any flow analysis.

* :func:`classify_function` proposes the ``function`` axis (db / web / app / vdi / k8s / infra),
  the one discovery-authority axis the tuning framework governs on. Proposals only, never writes:
  a Kubernetes cluster-node label wins outright (k8s, high confidence, auto-ratifiable), the
  component label maps through a CLOSED conservative table (db and web high, app-ish medium), and
  anything ambiguous or silent is flagged for the operator instead of guessed. ``vdi`` and
  ``infra`` have no reliable label signal and are never proposed; the operator declares them.

The semantics mirror the reference implementation exactly; the estate's offline gate proves the
outputs equal on a shared fixture.
"""
from __future__ import annotations

from dataclasses import dataclass

# The Kubernetes "recommended labels" (+ topology) the VM Service already carries.
APP_LABELS = ("app.kubernetes.io/part-of", "app.kubernetes.io/name")
TIER_LABEL = "app.kubernetes.io/component"
ZONE_LABEL = "topology.kubernetes.io/zone"

# A VM that IS a Kubernetes cluster node carries the standard Cluster-API cluster label; the
# provider role labels carry the control-plane/worker sub-role (VKS sets these, not the upstream
# cluster.x-k8s.io/control-plane).
K8S_CLUSTER_LABEL = "cluster.x-k8s.io/cluster-name"
CAPI_ROLE_LABELS = ("capw.vmware.com/cluster.role", "capv.vmware.com/cluster.role")

# namespace-token -> env. Consumption namespaces commonly encode the environment in the name.
ENV_TOKENS: dict[str, tuple[str, ...]] = {
    "prod": ("prod", "prd", "production"),
    "stage": ("stage", "stg", "staging"),
    "dev": ("dev", "develop", "development"),
    "test": ("test", "qa", "uat", "sit"),
    "dr": ("dr", "disaster"),
    "lab": ("lab", "sandbox", "poc"),
}

# component -> function. CLOSED and conservative: only unambiguous components map; the value is
# lowercased before lookup. Ambiguous components (loadbalancer, cache, ...) are deliberately
# absent so they surface as corrections, never silent guesses.
COMPONENT_FUNCTION: dict[str, str] = {
    "database": "db", "db": "db", "postgres": "db", "postgresql": "db",
    "mysql": "db", "mariadb": "db", "mongodb": "db", "mongo": "db",
    "web": "web", "frontend": "web", "www": "web", "nginx": "web", "httpd": "web", "apache": "web",
    "api": "app", "backend": "app", "app": "app", "application": "app",
    "server": "app", "worker": "app", "logic": "app", "service": "app",
}

# function -> the closed app-layer vocabulary (presentation / logic / data). The tier
# recommendation derives from the SAME conservative map as function, so an ambiguous component
# yields neither.
FUNCTION_LAYER = {"web": "presentation", "app": "logic", "db": "data"}


@dataclass(frozen=True)
class SupervisorClassification:
    """One VM classified from its DECLARED Kubernetes labels (authoritative where present)."""

    vm: str
    namespace: str
    app: str | None
    tier: str | None
    env: str                       # prod|stage|dev|test|dr|lab|unknown
    availability_zone: str | None  # placement AZ, never the security zone
    confidence: str                # high|medium|none
    evidence: tuple[str, ...]
    source: str = "declared-label"


@dataclass(frozen=True)
class FunctionProposal:
    """One proposed function for one VM: a CANDIDATE for operator ratification, not a write."""

    vm: str
    function: str | None           # None = no confident signal; the operator declares
    confidence: str                # high|medium|low|none
    source: str                    # capi-label | component-label | none
    evidence: tuple[str, ...]
    auto_ratifiable: bool          # high + concrete; a per-scope opt-in MAY auto-accept
    note: str = ""


def env_from_namespace(namespace: str) -> str:
    """Derive the environment from a namespace name by token match."""
    tokens = set(namespace.lower().replace("_", "-").split("-"))
    for env, markers in ENV_TOKENS.items():
        if tokens & set(markers):
            return env
    return "unknown"


def classify_from_labels(vm: str, labels: dict[str, str], namespace: str) -> SupervisorClassification:
    """Turn one VM's labels plus its namespace into a classification. Pure."""
    app = next((labels[k] for k in APP_LABELS if labels.get(k)), None)
    tier = labels.get(TIER_LABEL) or None
    az = labels.get(ZONE_LABEL) or None
    env = env_from_namespace(namespace)
    evidence = tuple(k for k in (*APP_LABELS, TIER_LABEL, ZONE_LABEL) if labels.get(k)) + (
        ("namespace",) if env != "unknown" else ()
    )
    if app:
        confidence = "high"
    elif tier or az or env != "unknown":
        confidence = "medium"
    else:
        confidence = "none"
    return SupervisorClassification(
        vm=vm, namespace=namespace, app=app, tier=tier, env=env,
        availability_zone=az, confidence=confidence, evidence=evidence,
    )


def classify_function(vm: str, labels: dict[str, str]) -> FunctionProposal:
    """Propose the function axis for one VM from its declared labels. Pure.

    Precedence: a Kubernetes cluster-node label wins (k8s, high); else the component label through
    the closed map (db and web high, app medium). An unmapped component or no signal yields a
    proposal flagged for correction or declaration; never a guess."""
    if labels.get(K8S_CLUSTER_LABEL):
        role = next((labels[k] for k in CAPI_ROLE_LABELS if labels.get(k)), None)
        evidence = (K8S_CLUSTER_LABEL, *(k for k in CAPI_ROLE_LABELS if labels.get(k)))
        return FunctionProposal(
            vm=vm, function="k8s", confidence="high", source="capi-label",
            evidence=evidence, auto_ratifiable=True,
            note=f"Kubernetes cluster node ({role})" if role else "Kubernetes cluster node",
        )
    comp_raw = labels.get(TIER_LABEL)
    if comp_raw:
        mapped = COMPONENT_FUNCTION.get(comp_raw.strip().lower())
        if mapped in ("db", "web"):
            return FunctionProposal(
                vm=vm, function=mapped, confidence="high", source="component-label",
                evidence=(TIER_LABEL,), auto_ratifiable=True,
            )
        if mapped == "app":
            return FunctionProposal(
                vm=vm, function="app", confidence="medium", source="component-label",
                evidence=(TIER_LABEL,), auto_ratifiable=False,
            )
        return FunctionProposal(
            vm=vm, function=None, confidence="low", source="component-label",
            evidence=(TIER_LABEL,), auto_ratifiable=False,
            note=f"component={comp_raw!r} has no confident function mapping; operator to classify",
        )
    return FunctionProposal(
        vm=vm, function=None, confidence="none", source="none", evidence=(),
        auto_ratifiable=False,
        note="no declared function signal; operator to declare (or a flow lens proposes later)",
    )


def classify_namespace(namespace: str, vms_raw: list[dict]) -> list[SupervisorClassification]:
    """Classify every VirtualMachine object (raw CRD dicts) in one namespace. Pure."""
    out: list[SupervisorClassification] = []
    for vm in vms_raw:
        md = vm.get("metadata", {})
        name = md.get("name")
        if not isinstance(name, str) or not name:
            continue
        out.append(classify_from_labels(name, md.get("labels", {}) or {}, namespace))
    return out


def function_proposals(vms_raw: list[dict]) -> list[FunctionProposal]:
    """Propose function for every VirtualMachine CRD dict in one namespace payload. Pure."""
    out: list[FunctionProposal] = []
    for vm in vms_raw:
        md = vm.get("metadata", {})
        name = md.get("name")
        if not isinstance(name, str) or not name:
            continue
        out.append(classify_function(name, md.get("labels", {}) or {}))
    return out
