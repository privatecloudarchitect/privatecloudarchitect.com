#!/usr/bin/env python3
"""exporters.py: which hosts send the Operations for Networks collector IPFIX, read on the collector itself.

The export proof (the flow-collection chapter, Plate 04, rung 1): a host absent from the collector's exporter list
sends it nothing, whatever the switches report and whatever the flows name. A flow in the store names where its
endpoints run, never the host that exported it, so this list is read where the records arrive.

Read-only on the estate. The collector appliance refuses root over SSH, so the read goes through vSphere Guest
Operations, which signs in to the guest through VMware Tools: one fixed command in the guest (`nfdump -E` over the
newest minute files the collector's IPFIX receiver wrote), its output copied back, and the one temporary file it
wrote under the guest's /tmp removed. From each vCenter named it reads every host's VMkernel addresses, to name the
exporters and the hosts that sent nothing.

Prints each host with the observation domains it exported under in the window (0 is a distributed switch's; any
other number is an NSX profile's), its records, packets and sequence failures, then the hosts that sent nothing and
any exporter address no vCenter named; `--redact` prints placeholders instead of your names. Writes
`exporters.record.json` with every estate value replaced by a placeholder, and refuses to write it if one survived.

Environment:
  VC_HOSTS, VC_USER                 comma-separated vCenter FQDNs: the one that runs the collector VM, and every
                                    vCenter whose hosts export (needs pyVmomi)
  VC_PASSWORD_FILE                  a file, mode 0600, holding VC_USER's password (VC_PASSWORD is read when no file
                                    is named)
  COLLECTOR_VM                      the collector VM's name in vCenter
  GUEST_USER                        the collector's guest account that can read /var/flows (root)
  GUEST_PASSWORD_FILE               a file, mode 0600, holding that account's password (GUEST_PASSWORD when none)
  OPS_TLS_VERIFY                    TLS verification, on by default; false for a self-signed CA
Usage: python3 exporters.py [--minutes N] [--redact] [--out DIR]
"""

from __future__ import annotations

import argparse
import base64
import os
import re
import sys
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
# The TLS context and the secret reader are the metrics harness's (one source of each), as flow_paths.py imports them.
LIB = next(
    (
        p
        for p in (
            HERE.parent / "metrics-collection" / "harness",
            HERE.parents[3]
            / "deploy/privatecloudarchitect/companion/staging/handbook/metrics-collection/harness",
        )
        if (p / "opslib.py").is_file()
    ),
    None,
)
if LIB is None:
    raise SystemExit(
        "FATAL: the metrics-collection harness (opslib.py) is not beside this folder; "
        "run from the companion repository's handbook/ tree"
    )
sys.path.insert(0, str(LIB))
sys.path.insert(0, str(HERE))

from opslib import _ctx, secret  # noqa: E402
from scrub import Scrubber  # noqa: E402

NFDUMP_ENV = "/home/ubuntu/build-target/nfdump/nfcapd_env.sh"
NFDUMP = "/home/ubuntu/build-target/nfdump/nfdump"
FLOW_FILES = "/var/flows/vds/nfcapd/nfcapd.2*"
EXPORTER = re.compile(
    r"IP:\s*(?P<address>[0-9A-Fa-f:.]+),\s*version:\s*\d+,\s*ID:\s*(?P<domain>\d+)"
    r"(?:,\s*Sequence failures:\s*(?P<seq>\d+),\s*packets:\s*(?P<packets>\d+),\s*flows:\s*(?P<flows>\d+))?"
)


def guest_script(minutes: int) -> str:
    """The one command run in the guest: the exporter list of each of the newest `minutes` files, one per minute."""
    return (
        f". {NFDUMP_ENV}; "
        f'for f in $(ls {FLOW_FILES} | tail -{minutes}); do echo "FILE $(basename $f)"; {NFDUMP} -E "$f"; done'
    )


def parse(text: str) -> dict:
    """Exporter lines summed per address and observation domain over every file in the output.

    A line without counts is an exporter the receiver has registered (its templates) with nothing in that file."""
    files = [ln.split(" ", 1)[1].strip() for ln in text.splitlines() if ln.startswith("FILE ")]
    rows: dict[tuple[str, int], dict] = {}
    for m in EXPORTER.finditer(text):
        key = (m.group("address"), int(m.group("domain")))
        row = rows.setdefault(
            key,
            {
                "address": key[0],
                "domain": key[1],
                "records": 0,
                "packets": 0,
                "sequence_failures": 0,
                "files_with_packets": 0,
            },
        )
        if m.group("packets") is not None:
            row["records"] += int(m.group("flows"))
            row["packets"] += int(m.group("packets"))
            row["sequence_failures"] += int(m.group("seq"))
            row["files_with_packets"] += 1
    return {
        "files": files,
        "exporters": sorted(rows.values(), key=lambda r: (r["address"], r["domain"])),
    }


def connect(host: str):
    from pyVim.connect import SmartConnect

    password = secret("VC_PASSWORD")
    if not password:
        raise SystemExit("FATAL: VC_PASSWORD_FILE (or VC_PASSWORD) is not set")
    return SmartConnect(host=host, user=os.environ["VC_USER"], pwd=password, sslContext=_ctx())


def host_addresses(si) -> dict[str, str]:
    """Every VMkernel IPv4 address of every host this vCenter holds, to the host's name."""
    from pyVmomi import vim

    content = si.RetrieveContent()
    view = content.viewManager.CreateContainerView(content.rootFolder, [vim.HostSystem], True)
    try:
        out = {}
        for h in view.view:
            for vnic in (h.config.network.vnic if h.config else []) or []:
                ip = getattr(vnic.spec.ip, "ipAddress", None)
                if ip:
                    out[ip] = h.name
        return out
    finally:
        view.Destroy()


def read_in_guest(si, vc_host: str, vm_name: str, minutes: int) -> str:
    from pyVmomi import vim

    content = si.RetrieveContent()
    view = content.viewManager.CreateContainerView(content.rootFolder, [vim.VirtualMachine], True)
    try:
        vm = next((v for v in view.view if v.name == vm_name), None)
    finally:
        view.Destroy()
    if vm is None:
        return ""
    password = secret("GUEST_PASSWORD")
    if not password:
        raise SystemExit("FATAL: GUEST_PASSWORD_FILE (or GUEST_PASSWORD) is not set")
    creds = vim.vm.guest.NamePasswordAuthentication(
        username=os.environ["GUEST_USER"], password=password
    )
    gom = content.guestOperationsManager
    out = f"/tmp/exporters-{int(time.time())}.txt"
    command = base64.b64encode(guest_script(minutes).encode()).decode()
    spec = vim.vm.guest.ProcessManager.ProgramSpec(
        programPath="/bin/bash", arguments=f"-c 'echo {command} | base64 -d | bash > {out} 2>&1'"
    )
    pid = gom.processManager.StartProgramInGuest(vm, creds, spec)
    try:
        deadline = time.time() + 300
        while time.time() < deadline:
            if gom.processManager.ListProcessesInGuest(vm, creds, [pid])[0].endTime:
                break
            time.sleep(1)
        else:
            raise SystemExit("FATAL: the read in the guest did not finish in 300 s")
        info = gom.fileManager.InitiateFileTransferFromGuest(vm, creds, out)
        with urllib.request.urlopen(
            info.url.replace("*", vc_host), context=_ctx(), timeout=120
        ) as r:
            return r.read().decode("utf-8", errors="replace")
    finally:
        rm = vim.vm.guest.ProcessManager.ProgramSpec(programPath="/bin/rm", arguments=f"-f {out}")
        gom.processManager.StartProgramInGuest(vm, creds, rm)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--minutes", type=int, default=60, help="the newest N minute files (1 to 1440; default 60)"
    )
    parser.add_argument(
        "--redact", action="store_true", help="print with placeholders instead of your names"
    )
    parser.add_argument("--out", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    if not 1 <= args.minutes <= 1440:
        parser.error("--minutes takes 1 to 1440")
    vcenters = [h.strip() for h in os.environ.get("VC_HOSTS", "").split(",") if h.strip()]
    if not vcenters or not os.environ.get("COLLECTOR_VM") or not os.environ.get("GUEST_USER"):
        raise SystemExit(
            "FATAL: set VC_HOSTS, VC_USER, COLLECTOR_VM and GUEST_USER (see the docstring)"
        )
    try:
        from pyVim.connect import Disconnect
    except ImportError:
        raise SystemExit("FATAL: pyVmomi is not installed") from None

    scrub = Scrubber()
    read_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    names: dict[str, str] = {}
    output = ""
    for vc in vcenters:
        scrub.add_host(vc, "vcenter")
        si = connect(vc)
        try:
            names.update(host_addresses(si))
            if not output:
                output = read_in_guest(si, vc, os.environ["COLLECTOR_VM"], args.minutes)
        finally:
            Disconnect(si)
    if not output:
        raise SystemExit("FATAL: no vCenter named in VC_HOSTS runs a VM called COLLECTOR_VM")
    scrub.add(os.environ["COLLECTOR_VM"], "collector")

    parsed = parse(output)
    for address, host in names.items():
        scrub.add_host(host, "esx")
        scrub.add(address, "address")
    exporting = {r["address"] for r in parsed["exporters"] if r["files_with_packets"]}
    for r in parsed["exporters"]:
        scrub.add(r["address"], "address")
        r["host"] = names.get(r["address"])
    silent = sorted({h for a, h in names.items()} - {names[a] for a in exporting if a in names})
    unknown = sorted(a for a in exporting if a not in names)
    record = {
        "harness": "exporters.py",
        "read_at": read_at,
        "window": {
            "minute_files": len(parsed["files"]),
            "first": parsed["files"][0] if parsed["files"] else None,
            "last": parsed["files"][-1] if parsed["files"] else None,
        },
        "exporters": parsed["exporters"],
        "hosts_sending_nothing": silent,
        "exporting_addresses_no_vcenter_named": unknown,
    }
    args.out.mkdir(parents=True, exist_ok=True)
    scrub.write(args.out / "exporters.record.json", record)

    def say(line: str) -> None:
        print(scrub.scrub(line) if args.redact else line)

    w = record["window"]
    say(
        f"read at {read_at}: {w['minute_files']} minute files on the collector, {w['first']} to {w['last']}"
    )
    by_host: dict[str, list[dict]] = {}
    for r in parsed["exporters"]:
        by_host.setdefault(r["host"] or r["address"], []).append(r)
    for host in sorted(by_host):
        parts = []
        for r in by_host[host]:
            kind = "switch" if r["domain"] == 0 else "NSX profile"
            if r["files_with_packets"]:
                parts.append(
                    f"domain {r['domain']} ({kind}) {r['records']:,} records, {r['packets']:,} packets, "
                    f"{r['sequence_failures']:,} sequence failures"
                )
            else:
                parts.append(f"domain {r['domain']} ({kind}) registered, nothing in the window")
        say(f"  {host}: " + "; ".join(parts))
    say(f"  hosts that sent nothing: {', '.join(silent) if silent else 'none'}")
    if unknown:
        say(f"  exporting addresses no vCenter named: {', '.join(unknown)}")
    say(f"  record: {args.out / 'exporters.record.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
