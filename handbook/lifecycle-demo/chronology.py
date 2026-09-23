#!/usr/bin/env python3
"""chronology.py: turn a real run of the hybrid self-service demo into a publishable record.

The demo prints a structured transcript as it runs: every step announces its purpose, the file that
implements it, the exact command or API call, and then the results that came back. That transcript is
already the chapter; what it is not is publishable, because it is full of this estate's coordinates.

This script parses a captured transcript and emits `chronology.json` with every estate value replaced by
a readable placeholder. It is read-only with respect to the estate: it reads files you already have and
calls `pca lab context` for the coordinate list, nothing else.

**Placeholders are chosen to teach.** `{{project}}` rather than `project-1`, because the reader is meant
to substitute their own and the shape of the name is the lesson. The application's own name reads like a
fictional example and is not one: it is the workload's name on this estate, so it is scrubbed to
`{{app}}` and the generated shape publishes as `{{app}}-<env>-{{project}}`, which is the better teaching
anyway. The blueprint bundle's name is repository content, not an estate value, and stays.

The script refuses to write a record in which an estate value survived, and refuses to write one in which
the platform's own vocabulary was eaten by the scrub. Both have happened on this handbook before.

Usage:
    python3 chronology.py --transcript <create.log> [--transcript <story.log>] [--out chronology.json]

Scope it does not cover: the transcript is one run on one estate. Timings are that run's, not a promise.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys

UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I)
ANSI = re.compile(r"\x1b\[[0-9;]*m")
IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
VMI = re.compile(r"\bvmi-[0-9a-f]+\b")
TOKENLEN = re.compile(r"\(length \d+\)")

# The platform's own words. If the scrub eats one of these the record stops teaching, so it is asserted
# to survive rather than hoped for. Learned on the identifier-planes chapter, where registering a user
# named `admin` rewrote every `administrators` in the record.
RESERVED = {
    "SupervisorNamespace", "VirtualMachine", "VirtualMachineService", "VirtualMachineImage",
    "Cluster", "Deployment", "CREATE_SUCCESSFUL", "DELETE_SUCCESSFUL", "CREATE_FAILED",
    "Provisioned", "Created", "Deleting", "PoweredOn", "Ready", "large", "medium", "small",
    "kubectl", "curl", "generateName", "classConfigOverrides", "vm_service_spec",
    "content_libraries", "cpuLimit", "cpuReservation", "memoryLimit", "storageClass",
    "Add.Disk", "Remove.Disk", "Create.Snapshot", "Delete.Snapshot", "LoadBalancer",
    "ClusterIP", "Antrea", "CAPI", "phase", "status", "conditions", "namespace",
}

# The same idea for hostnames. A Kubernetes API group reads exactly like a hostname
# (`vmoperator.vmware.com`, `cluster.x-k8s.io`), so a blanket host scrub eats the platform's
# vocabulary. Anything NOT under one of these in a run transcript is an estate host.
RESERVED_DOMAINS = (
    "vmware.com", "broadcom.com", "kubernetes.io", "k8s.io", "x-k8s.io", "cluster.local",
    "sigs.k8s.io", "privatecloudarchitect.com", "github.com",
)
# Three labels or more, so a file name (`01-create.sh`, `lifecycle-story.py`) is not read as a host.
FQDN = re.compile(r"\b(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.){2,}[a-z]{2,}\b")


def reserved_domain(host: str) -> bool:
    return any(host == d or host.endswith("." + d) for d in RESERVED_DOMAINS)


class Labels:
    """Estate coordinates become readable placeholders; the demo's own example names do not."""

    def __init__(self) -> None:
        self.pairs: list[tuple[str, str]] = []
        self.seen: dict[str, str] = {}

    def add(self, real: str | None, label: str) -> None:
        if not real or str(real) in RESERVED or len(str(real)) < 3:
            return
        real = str(real)
        if real in self.seen:
            return
        self.seen[real] = label
        self.pairs.append((real, label))

    def scrub(self, text: str) -> str:
        if not isinstance(text, str):
            return text
        # Longest first: a namespace name contains the project name, and replacing the short one first
        # corrupts the long one.
        # The boundary permits an adjacent HYPHEN on purpose. An estate coordinate is most often a
        # COMPONENT of a generated name rather than a standalone token: the project name sits inside
        # `<app>-<env>-<project>`, which is the whole point of the naming convention being taught. A
        # hyphen-excluding boundary leaves it there, and the stem check below catches that as a leak.
        # Rendering it as `{{app}}-dev-{{project}}` keeps the convention legible and the estate out
        # of it.
        for real, label in sorted(self.pairs, key=lambda kv: -len(kv[0])):
            text = re.sub(r"(?<![A-Za-z0-9])" + re.escape(real) + r"(?![A-Za-z0-9])",
                          "{{%s}}" % label, text)
        text = UUID.sub("{{id}}", text)
        text = VMI.sub("{{image-id}}", text)
        text = IPV4.sub("{{ip}}", text)
        text = TOKENLEN.sub("(length {{n}})", text)
        return text


def deploy_context(repo_root: str) -> dict:
    """The estate's coordinates, from the one place that declares them."""
    pca = os.path.join(repo_root, ".venv", "bin", "pca")
    if not os.path.exists(pca):
        return {}
    try:
        out = subprocess.run([pca, "lab", "context", "--format", "env"],
                             capture_output=True, text=True, timeout=60).stdout
    except Exception:
        return {}
    d = {}
    for line in out.splitlines():
        if "=" in line and line.startswith("PCA_DEPLOY_"):
            k, v = line.split("=", 1)
            d[k.strip()] = v.strip()
    return d


STEP = re.compile(r"^┌─ Step (?P<n>[0-9a-z/]+) — (?P<title>.+?)\s*$")
FIELD = re.compile(r"^│\s+(?P<k>Purpose|File|Action):\s*(?P<v>.*)$")
RESULT = re.compile(r"^(?P<mark>[✓⚠✗ℹ])\s*(?P<text>.+?)\s*$")
STAGE = re.compile(r"^║ STAGE (?P<n>\d+) · (?P<title>.+?)\s*║$")
STAGEROW = re.compile(r"^║ (?P<k>lifecycle|the user|owned by)\s+(?P<v>.+?)\s*║$")


def parse(path: str) -> dict:
    """Pull the step skeleton and the stage banners out of one captured run."""
    lines = [ANSI.sub("", ln.rstrip("\n")) for ln in open(path, encoding="utf-8", errors="replace")]
    steps, stages, cur, curstage = [], [], None, None
    for ln in lines:
        m = STAGE.match(ln)
        if m:
            curstage = {"n": int(m.group("n")), "title": m.group("title").strip(), "rows": {}}
            stages.append(curstage)
            continue
        m = STAGEROW.match(ln)
        if m and curstage is not None:
            curstage["rows"][m.group("k")] = m.group("v").strip()
            continue
        m = STEP.match(ln)
        if m:
            cur = {"step": m.group("n"), "title": m.group("title").strip(),
                   "purpose": "", "file": "", "action": "", "results": []}
            steps.append(cur)
            continue
        if cur is not None:
            m = FIELD.match(ln)
            if m:
                cur[m.group("k").lower()] = m.group("v").strip()
                continue
            if ln.startswith("└─"):
                continue
            m = RESULT.match(ln)
            if m and m.group("text").strip():
                cur["results"].append({"mark": m.group("mark"), "text": m.group("text").strip()})
    return {"steps": steps, "stages": stages}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--transcript", action="append", required=True,
                    help="a captured run log; repeat for the create run and the story run")
    ap.add_argument("--out", default="chronology.json")
    # Coordinates the run's own output cannot be asked for. Everything this script CAN learn from the
    # transcript or from `pca lab context` it learns, so that it carries no estate value of its own;
    # what is left (an appliance FQDN that appears only inside a URL, a machine named outside the
    # generated shape) is passed in. A forgotten one does not leak silently: the survivor checks at the
    # end fail the run and name what to pass.
    ap.add_argument("--also-scrub", action="append", default=[], metavar="VALUE=LABEL",
                    help="an extra coordinate to replace, as value=label (repeatable)")
    # companion/staging/handbook/<sheet>/ sits SIX levels under the repo root. Getting this wrong is
    # silent: `pca lab context` simply returns nothing, no coordinate is registered, and the scrub
    # becomes a no-op that still writes a record. The assertion below is what makes it loud.
    ap.add_argument("--repo-root", default=os.path.abspath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), *([".."] * 6))))
    args = ap.parse_args()

    L = Labels()
    ctx = deploy_context(args.repo_root)
    for key, label in (("PCA_DEPLOY_PROJECT", "project"), ("PCA_DEPLOY_TENANT", "tenant"),
                       ("PCA_DEPLOY_ORG", "org"), ("PCA_DEPLOY_CCI_CONTEXT", "kube-context"),
                       ("PCA_DEPLOY_REGION", "region"), ("PCA_DEPLOY_VPC", "vpc"),
                       ("PCA_DEPLOY_VDC", "vdc"), ("PCA_DEPLOY_SEG", "service-engine-group"),
                       ("PCA_DEPLOY_ZONE", "zone"), ("PCA_DEPLOY_SUPERVISOR_ENDPOINT", "workload-vcenter")):
        L.add(ctx.get(key), label)
    for pair in args.also_scrub:
        if "=" not in pair:
            raise SystemExit(f"--also-scrub takes value=label, got {pair!r}")
        real, label = pair.split("=", 1)
        L.add(real.strip(), label.strip())

    # Zones sit beside the configured one and appear in the capacity readout.
    region = ctx.get("PCA_DEPLOY_REGION")
    if region:
        for i in (1, 2, 3):
            L.add(f"{region}-az{i}", f"zone-{i}")

    if not ctx.get("PCA_DEPLOY_PROJECT"):
        raise SystemExit(
            "FATAL: no deploy context resolved, so no estate coordinate would be registered and the "
            "scrub would be a no-op that still writes a record. Check --repo-root points at the "
            "repository root and .venv/bin/pca exists.")

    payload = {"runs": [], "estateCoordinatesReplaced": []}
    raw_all = []
    for t in args.transcript:
        if not os.path.exists(t):
            print(f"no such transcript: {t}", file=sys.stderr)
            return 2
        raw = open(t, encoding="utf-8", errors="replace").read()
        raw_all.append(raw)
        # Namespace names carry a generated suffix and appear everywhere; learn them from the run.
        for m in re.finditer(r"\b([a-z0-9][a-z0-9-]*-(?:dev|prod|test)-[a-z0-9-]+-[a-z0-9]{5})\b", raw):
            L.add(m.group(1), "namespace")
        # A deployment name is the namespace shape with a numeric suffix instead of a generated one.
        for m in re.finditer(r"\b([a-z0-9][a-z0-9-]*-(?:dev|prod|test)-[a-z0-9-]+-\d{6})\b", raw):
            L.add(m.group(1), "deployment-name")
        for m in re.finditer(r"--tenant\s+([a-z]{2,4})\b|01-create\.sh\s+([a-z]{2,4})\b", raw):
            L.add(m.group(1) or m.group(2), "operator")
        # The application's own name is an estate identifier, not a neutral example: it is this estate's
        # workload, and every generated name is built from it. Learn the STEM from those generated names
        # rather than writing it down here, so the shape `{{app}}-<env>-{{project}}` still teaches and
        # this script names nothing. Registered after the full names so the longer ones win.
        for m in re.finditer(r"(?<![A-Za-z0-9-])([a-z0-9][a-z0-9-]*)-(?:dev|prod|test)-[a-z0-9]", raw):
            L.add(m.group(1), "app")
        # Every kubeconfig context the run NAMED, not only the one configured now. A tool that falls
        # back to a stale context prints the name it tried, and that name is an estate coordinate the
        # deploy context can no longer supply: an org retired months ago still sits in the kubeconfig.
        for m in re.finditer(r"context '([a-z0-9][a-z0-9-]*)'", raw):
            L.add(m.group(1), "kube-context")
        for m in FQDN.finditer(raw):
            if not reserved_domain(m.group(0)):
                L.add(m.group(0), "automation-host")
        parsed = parse(t)
        # Step "1/4" belongs to the cleanup sequence and "1/8" to the create sequence; keying on the
        # number alone would collide them and the later one would silently replace the earlier.
        for st in parsed["steps"]:
            st["phase"] = "retire" if st["step"].endswith("/4") else "create"
        payload["runs"].append({"source": os.path.basename(t), **parsed})

    # MERGED VIEW, LAST TRANSCRIPT WINS. The same step can appear in several captures, and when the code
    # behind it changed between them, publishing the older one would show behaviour that no longer exists.
    # Pass transcripts oldest-first and the freshest capture of each step is the one that ships; `runs`
    # keeps every capture so the provenance is not lost.
    merged: dict[str, dict] = {}
    order: list[str] = []
    for run in payload["runs"]:
        for st in run["steps"]:
            key = f"{st.get('phase', 'create')}:{st['step']}"
            if key not in merged:
                order.append(key)
            merged[key] = {**st, "source": run["source"]}
    payload["chronology"] = [merged[k] for k in order]
    payload["stages"] = [s for r in payload["runs"] for s in r["stages"]]

    payload["estateCoordinatesReplaced"] = sorted({lab for _r, lab in L.pairs})

    # DASH NORMALISATION. The scripts being quoted print em dashes; the published pages forbid them and
    # assert on it at build time. This is a presentational change to a quoted string, not a factual one,
    # so it happens once here rather than in the renderer, and the README says the record carries it.
    def undash(t):
        return t.replace(" \u2014 ", ", ").replace(" \u2013 ", ", ").replace("\u2014", "-").replace("\u2013", "-")

    text = undash(L.scrub(json.dumps(payload, indent=1, ensure_ascii=False)))

    # Refuse to publish a record in which an estate value survived.
    bare = re.sub(r"\{\{[^}]*\}\}", "", text)
    for real, label in L.pairs:
        if re.search(r"(?<![A-Za-z0-9])" + re.escape(real) + r"(?![A-Za-z0-9])", bare):
            shape = re.sub(r"[A-Za-z]", "a", re.sub(r"[0-9]", "9", real))
            raise SystemExit(f"FATAL: a {label} value ({len(real)} chars, shape {shape}) reached the record")
        for sep in ("-", ".", "_"):
            if sep in real:
                stem = real.rsplit(sep, 1)[0]
                if len(stem) >= 8 and re.search(
                        r"(?<![A-Za-z0-9])" + re.escape(stem) + r"(?![A-Za-z0-9])", bare):
                    raise SystemExit(
                        f"FATAL: the stem of a {label} value ({len(stem)} chars) reached the record")
    if UUID.search(bare) or VMI.search(bare) or IPV4.search(bare):
        raise SystemExit("FATAL: an identifier, image id or address reached the record")
    # The loop above can only check values the scrub was TOLD about, so it cannot see a coordinate
    # nobody registered. A hostname is the case where that matters and where the shape gives it away:
    # anything left that is not the platform's own vocabulary is an estate host that was never passed.
    for host in sorted({m.group(0) for m in FQDN.finditer(bare)}):
        if not reserved_domain(host):
            shape = ".".join("a" * len(part) for part in host.split("."))
            raise SystemExit(
                f"FATAL: a host reached the record (shape {shape}). Pass it as "
                f"--also-scrub <host>=automation-host, or add its domain to RESERVED_DOMAINS if it is "
                f"the platform's vocabulary rather than yours.")

    # And refuse to publish one the scrub made useless.
    joined = json.dumps(payload)
    for word in ("SupervisorNamespace", "kubectl", "CREATE_SUCCESSFUL", "Provisioned"):
        if word in joined and word not in text:
            raise SystemExit(f"FATAL: the scrubber ate the platform's own word {word!r}")

    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(text + "\n")
    steps = sum(len(r["steps"]) for r in payload["runs"])
    stages = sum(len(r["stages"]) for r in payload["runs"])
    print(f"wrote {args.out}: {steps} step(s), {stages} stage(s) across {len(payload['runs'])} run(s); "
          f"{len(payload['estateCoordinatesReplaced'])} coordinate families replaced")
    return 0


if __name__ == "__main__":
    sys.exit(main())
