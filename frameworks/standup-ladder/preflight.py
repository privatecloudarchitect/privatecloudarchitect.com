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
  python3 preflight.py --requires-vm-image --vm-count 2

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

PASS, WARN, FAIL, SKIP = "PASS", "WARN", "FAIL", "SKIP"
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


def check_image_resolves(requires_vm_image, namespace_content_libraries):
    if not requires_vm_image:
        return ("R1", "L1", "image resolves in namespace", SKIP, "Bundle declares no VM image.", "")
    if namespace_content_libraries:
        n = len(namespace_content_libraries)
        return (
            "R1",
            "L1",
            "image resolves in namespace",
            PASS,
            f"Namespace VM Service has {n} content library(ies) attached.",
            "",
        )
    return (
        "R1",
        "L1",
        "image resolves in namespace",
        FAIL,
        "The bundle needs a VM image but the namespace VM Service has no content library "
        "attached, so the image will not resolve at admission.",
        "Attach a content library holding the image to the namespace VM Service (and share it to "
        "the org); prefer a Supervisor- or region-wide association so new namespaces inherit it.",
    )


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


def main():
    ap = argparse.ArgumentParser(description="Standup Dependency Ladder preflight gate.")
    ap.add_argument(
        "--requires-vm-image", action="store_true", help="the bundle deploys a VM Service VM"
    )
    ap.add_argument(
        "--requires-vks", action="store_true", help="the bundle deploys a VKS guest cluster"
    )
    ap.add_argument("--vm-count", type=int, default=0, help="number of VMs the bundle deploys")
    args = ap.parse_args()

    host = os.environ.get("PREFLIGHT_VC_HOST")
    namespace = os.environ.get("PREFLIGHT_NAMESPACE")
    session_id = os.environ.get("PREFLIGHT_SESSION_ID")
    probe_ok, content_libs, storage_mib = None, None, None
    if host and namespace and session_id:
        try:
            data = _read_namespace_instance(host, namespace, session_id)
            content_libs = (data.get("vm_service_spec") or {}).get("content_libraries")
            specs = data.get("storage_specs") or []
            storage_mib = sum(int(s.get("limit") or 0) for s in specs) or None
        except Exception as exc:
            print(f"live read failed: {exc}", file=sys.stderr)
            probe_ok = False
    else:
        print(
            "PREFLIGHT_VC_HOST / PREFLIGHT_NAMESPACE / PREFLIGHT_SESSION_ID unset; "
            "R0/R1/R3 will report on what they can.",
            file=sys.stderr,
        )

    rungs = [
        check_auth_probe(probe_ok),
        check_image_resolves(args.requires_vm_image, content_libs),
        check_quota_footprint(storage_mib, args.vm_count),
        check_loadbalancer(args.requires_vks, True if args.requires_vks else None),
    ]
    rungs.sort(key=lambda r: ORDER.index(r[0]) if r[0] in ORDER else len(ORDER))

    blocked = False
    print(f"Standup preflight -> namespace {namespace or '(unset)'}")
    for rung, lesson, title, status, detail, fix in rungs:
        print(f"  [{status:4}] {rung} {title} ({lesson}) - {detail}")
        if fix and status in (FAIL, WARN):
            print(f"         fix: {fix}")
        blocked = blocked or status == FAIL
    if blocked:
        print("BLOCKED: a prerequisite rung failed; resolve it before deploying.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
