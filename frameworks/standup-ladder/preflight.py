#!/usr/bin/env python3
"""Standup Dependency Ladder preflight - the adoptable, dependency-free gate.

Run this against your target namespace BEFORE you submit a deployment, so the
prerequisites that get taken for granted fail fast with a remediation instead of
stalling silently while the orchestrator reports success. The one discipline: the
control plane reporting created is not the data plane being ready; verify each
prerequisite at the layer that owns it.

Standard library only. Parameterized entirely by environment and flags, so it runs
on your estate with no repository dependency and touches nothing (it only reads).

  export PREFLIGHT_VC_HOST=your-supervisor-vcenter.example.com
  export PREFLIGHT_NAMESPACE=your-target-namespace
  export PREFLIGHT_SESSION_ID=<a vCenter API session id>   # POST /api/session
  # R1 reads the images the namespace can see through the namespace's own endpoint:
  export PREFLIGHT_NS_ENDPOINT=<the namespace's endpoint URL>   # status.namespaceEndpointURL of the namespace
  export PREFLIGHT_BEARER_FILE=~/.vcf/vcfa-bearer               # a VCF Automation bearer, file of mode 0600
  python3 preflight.py --image <the vmi-... id or display name the bundle pins> --vm-count 2

R1 asks whether the pinned image is among the images the namespace can name: its own VirtualMachineImages, or the
Supervisor's ClusterVirtualMachineImages, where a library attached to the whole Supervisor lands. It does not
judge from the namespace's vCenter library setting, which stays empty for a Supervisor-wide library and keeps
the id of a library that was deleted. Without the endpoint and bearer, R1 reports that it did not look.

The check functions are pure so you can unit test them; the live wrapper is the
only part that reads your estate.
"""

from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
import urllib.request

PASS, WARN, FAIL, SKIP, UNKNOWN = "PASS", "WARN", "FAIL", "SKIP", "UNKNOWN"
DEFAULT_BOOT_DISK_GIB = 80  # conservative un-right-sized OS image default


# --- pure checks (no I/O; unit-testable) ------------------------------------


def check_auth_probe(probe_ok):
    if probe_ok is None:
        return (
            "R0",
            "L8",
            "auth probe",
            WARN,
            "No live session provided, so the auth probe did not run.",
            "Set PREFLIGHT_VC_HOST / PREFLIGHT_NAMESPACE / PREFLIGHT_SESSION_ID so the gate can "
            "read the namespace live; validate one call before any bulk operations.",
        )
    if probe_ok:
        return ("R0", "L8", "auth probe", PASS, "A live authenticated read succeeded.", "")
    return (
        "R0",
        "L8",
        "auth probe",
        FAIL,
        "The initial authenticated read failed.",
        "Validate one call before bulk operations; a burst of failures locks the account and a "
        "restored credential may be stale. Refresh or unlock the identity first.",
    )


def check_image_resolves(image_ref, visible):
    """R1: is the pinned image (an id, or a display name one image carries) among the images the namespace can
    name? `visible` is a list of (image id, display name, scope), or None when it was not read."""
    t = "image resolves in namespace"
    if not image_ref:
        return ("R1", "L1", t, SKIP, "Bundle declares no VM image.", "")
    if visible is None:
        return ("R1", "L1", t, UNKNOWN, "The namespace's images were not read, so whether the image resolves "
                "was not observed.", "Set PREFLIGHT_NS_ENDPOINT and PREFLIGHT_BEARER_FILE so the gate can list them.")
    hit = [v for v in visible if v[0] == image_ref]
    if hit:
        return ("R1", "L1", t, PASS, f"{image_ref} ({hit[0][1] or 'no display name'}) is visible at {hit[0][2]} "
                "scope.", "")
    named = [v for v in visible if v[1] == image_ref]
    if len(named) == 1:
        return ("R1", "L1", t, PASS, f"Display name {image_ref} resolves to {named[0][0]} at {named[0][2]} scope "
                "(a name pin follows whatever image carries it).", "")
    if len(named) > 1:
        return ("R1", "L1", t, WARN, f"Display name {image_ref} is carried by {len(named)} images; which one "
                "admission picks was not tested.", "Pin the image by id, or remove the duplicate display name.")
    n_cluster = sum(1 for v in visible if v[2] == "cluster")
    return ("R1", "L1", t, FAIL,
            f"The pinned image {image_ref} is not among the {len(visible)} images this namespace can see "
            f"({n_cluster} cluster-wide, {len(visible) - n_cluster} in the namespace); the VM will be refused at admission.",
            "If the image's library was rebuilt, every image id changed: find the image by its display name and "
            "re-pin. If the image is missing entirely, check that its library is ready and attached, to the "
            "Supervisor for every namespace or to this namespace.")


def check_quota_footprint(storage_limit_mib, vm_count, per_vm_boot_disk_gib=DEFAULT_BOOT_DISK_GIB):
    if vm_count <= 0:
        return ("R3", "L3", "quota covers footprint", SKIP, "Bundle declares no VMs.", "")
    if not storage_limit_mib:
        return (
            "R3",
            "L3",
            "quota covers footprint",
            WARN,
            f"Bundle has {vm_count} VM(s) but the namespace storage limit is unreadable.",
            "Set the quota to at least the sum of each VM's real boot disk plus PVCs.",
        )
    est = vm_count * per_vm_boot_disk_gib
    limit = storage_limit_mib / 1024
    if limit >= est:
        return (
            "R3",
            "L3",
            "quota covers footprint",
            PASS,
            f"Storage limit {limit:.0f} GiB covers the estimated {est} GiB.",
            "",
        )
    return (
        "R3",
        "L3",
        "quota covers footprint",
        WARN,
        f"Storage limit {limit:.0f} GiB may not cover the estimated {est} GiB for "
        f"{vm_count} un-right-sized VM(s); admission may deny on quota.",
        "Raise the quota to the real footprint, or right-size the image boot disk.",
    )


def check_loadbalancer(requires_vks, lb_present):
    if not requires_vks:
        return (
            "R4",
            "L2",
            "load balancer serves VIPs",
            SKIP,
            "Bundle declares no VKS cluster.",
            "",
        )
    if lb_present is False:
        return (
            "R4",
            "L2",
            "load balancer serves VIPs",
            FAIL,
            "A VKS cluster is required but no load-balancer capability is present; the "
            "control-plane VIP cannot be placed and the cluster will not build.",
            "Ensure the region's registered load-balancer provider is serving VIPs; the cluster cannot start without it.",
        )
    return (
        "R4",
        "L2",
        "load balancer serves VIPs",
        WARN,
        "Verify the load balancer is actually placing VIPs; the definitive check is post-submit, "
        "that node machines appear within minutes.",
        "If nodes do not appear shortly after submit, the LB is not placing the VIP; restore it.",
    )


ORDER = ["R0", "R1", "R2", "R3", "R4", "R5", "R6"]


# --- live wrapper (stdlib; reads only) --------------------------------------


def _read_namespace_instance(host, namespace, session_id):
    """Read a Supervisor namespace instance from the vCenter automation API."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    url = f"https://{host}/api/vcenter/namespaces/instances/{namespace}"
    req = urllib.request.Request(url, headers={"vmware-api-session-id": session_id})
    with urllib.request.urlopen(req, context=ctx, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def _secret_file(name):
    """The value in the file NAME_FILE names, refused unread when the file is open to group or other."""
    path = os.environ.get(f"{name}_FILE")
    if not path:
        return None
    with open(os.path.expanduser(path)) as f:
        mode = os.fstat(f.fileno()).st_mode & 0o777
        if mode & 0o077 and os.name != "nt":
            raise PermissionError(f"{name}_FILE names a file of mode {mode:04o}, open to group or other: "
                                  f'run chmod 600 "${name}_FILE" and try again (the file was not read)')
        return f.read().strip()


def _read_visible_images(endpoint, namespace, bearer):
    """Every image the namespace can name: (id, display name, scope) for cluster and namespace scope."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    out = []
    for scope, path in (("cluster", "/apis/vmoperator.vmware.com/v1alpha5/clustervirtualmachineimages"),
                        ("namespace", f"/apis/vmoperator.vmware.com/v1alpha5/namespaces/{namespace}/virtualmachineimages")):
        req = urllib.request.Request(endpoint.rstrip("/") + path,
                                     headers={"Authorization": f"Bearer {bearer}", "Accept": "application/json"})
        with urllib.request.urlopen(req, context=ctx, timeout=30) as r:
            for item in json.loads(r.read().decode("utf-8")).get("items", []):
                out.append((item["metadata"]["name"], (item.get("status") or {}).get("name"), scope))
    return out


def main():
    ap = argparse.ArgumentParser(description="Standup Dependency Ladder preflight gate.")
    ap.add_argument(
        "--image", default=None,
        help="the image the bundle pins (a vmi-... id or a display name); omit when it deploys no VM",
    )
    ap.add_argument(
        "--requires-vks", action="store_true", help="the bundle deploys a VKS guest cluster"
    )
    ap.add_argument("--vm-count", type=int, default=0, help="number of VMs the bundle deploys")
    args = ap.parse_args()

    host = os.environ.get("PREFLIGHT_VC_HOST")
    namespace = os.environ.get("PREFLIGHT_NAMESPACE")
    session_id = os.environ.get("PREFLIGHT_SESSION_ID")
    probe_ok, visible, storage_mib = None, None, None
    if host and namespace and session_id:
        try:
            data = _read_namespace_instance(host, namespace, session_id)
            specs = data.get("storage_specs") or []
            storage_mib = sum(int(s.get("limit") or 0) for s in specs) or None
            probe_ok = True
        except Exception as exc:
            print(f"live read failed: {exc}", file=sys.stderr)
            probe_ok = False
    endpoint = os.environ.get("PREFLIGHT_NS_ENDPOINT")
    if args.image and endpoint and namespace:
        try:
            bearer = _secret_file("PREFLIGHT_BEARER")
            if bearer:
                visible = _read_visible_images(endpoint, namespace, bearer)
            del bearer
        except PermissionError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        except Exception as exc:
            print(f"image read failed: {exc}", file=sys.stderr)
    else:
        print(
            "PREFLIGHT_VC_HOST / PREFLIGHT_NAMESPACE / PREFLIGHT_SESSION_ID unset; "
            "R0/R1/R3 will report on what they can.",
            file=sys.stderr,
        )

    rungs = [
        check_auth_probe(probe_ok),
        check_image_resolves(args.image, visible),
        check_quota_footprint(storage_mib, args.vm_count),
        check_loadbalancer(args.requires_vks, True if args.requires_vks else None),
    ]
    rungs.sort(key=lambda r: ORDER.index(r[0]) if r[0] in ORDER else len(ORDER))

    blocked = False
    print(f"Standup preflight -> namespace {namespace or '(unset)'}")
    for rung, lesson, title, status, detail, fix in rungs:
        print(f"  [{status:4}] {rung} {title} ({lesson}) - {detail}")
        if fix and status in (FAIL, WARN, UNKNOWN):
            print(f"         fix: {fix}")
        blocked = blocked or status == FAIL
    if blocked:
        print("BLOCKED: a prerequisite rung failed; resolve it before deploying.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
