#!/usr/bin/env python3
"""guestcfg.py: a Salt master and two minions on the VM Service, proven and retired in one run.

The series of VM templates ends with a machine that configures itself once. This script stands up what keeps that
guest configured afterwards: an independent Salt master, a Linux minion and a Windows minion, all built from the
VM Service shape of stage 02, and walks the guest-configuration lifecycle end to end:

  1  read images, classes, storage and rights, and stop if anything is missing;
  2  build one Ubuntu 24.04 master: Salt 3008 LTS, its API over TLS, auto_accept False;
  3  build one Ubuntu 24.04 minion and one Windows Server 2022 minion;
  4  accept exactly the two expected minion ids, leave any other pending key unaccepted, and report it;
  5  ping, read grains, apply one state to each, then apply it again;
     then the probes, read-only: each minion's own public key against the one the master holds for its id,
     decoded and compared (Salt 3008.5 fingerprints one key two ways, so both fingerprints are recorded and
     neither decides), and the Windows sessions;
  6  change a managed file, name the drift with test=True, restore it with an apply;
  7  delete the minion keys, then the machines, then the master and its secrets;
  8  read the namespace back.

Two paths build steps 2 and 3. GUESTCFG_VIA=supervisor, the default, creates the objects directly at the namespace
endpoint. GUESTCFG_VIA=automation creates the three blueprints of templates/02x-vm-salt-minion/ in the project, from the
files as written, validates each, deploys the master, reads its address, and deploys the two minions with it; its
teardown deletes the deployments (minions first, then the master's) through VCF Automation, never their objects
underneath, and then the blueprints.

Run:
  export VCFA_HOST=<automation-fqdn> VCFA_ORG=<org>
  export VCFA_USER=<account> VCFA_PASSWORD_FILE=~/.vcf/vcfa-password   # or VCFA_REFRESH_TOKEN_FILE
  export GUESTCFG_NAMESPACE=<a-throwaway-namespace-you-may-build-in>
  export TLS_VERIFY=false                                              # only on a self-signed lab CA

  python3 guestcfg.py read                # read-only: images, classes, storage, what a run would need
  python3 guestcfg.py run --dry-run       # the default for run: every object it would create, nothing created
  python3 guestcfg.py run --execute       # build, prove, tear down, read back
  python3 guestcfg.py teardown            # list what a teardown would delete, deleting nothing
  python3 guestcfg.py teardown --execute  # idempotent; safe to run after any failure

Optional environment:
  GUESTCFG_PROJECT             the project holding the namespace; else every project is searched. Required with
                               GUESTCFG_VIA=automation: the project the blueprints and deployments are made in
  GUESTCFG_VIA                 supervisor (default) or automation (see above); a teardown takes the run's path
  GUESTCFG_LINUX_IMAGE         display name of the Ubuntu 24.04 image; else the single match in the namespace
  GUESTCFG_WINDOWS_IMAGE       display name of the Windows Server 2022 image; else the single match
  GUESTCFG_VM_CLASS            master and Linux minion class (default best-effort-small)
  GUESTCFG_WINDOWS_VM_CLASS    Windows minion class (default best-effort-medium)
  GUESTCFG_STORAGE_CLASS       storage class; else the single class the sign-in can see
  GUESTCFG_MIN_FREE_GIB        free storage quota required (default 160, an allowance for three boot disks, and 0
                               skips the check on a namespace that states no limit)
  GUESTCFG_WINDOWS_BOOTSTRAP   sysprep (default) or cloudinit, which needs Cloudbase-Init in the image; the
                               automation path has the Sysprep blueprint only
  GUESTCFG_KEYS                accept (default): the run accepts each pending minion key by exact expected id; or
                               preseed: once the API answers and before any minion exists, the master generates the
                               Linux minion's key pair (wheel key.gen_accept) and the minion's bootstrap Secret seeds
                               it, so its key is accepted from the start and never pending. Supervisor path only. The
                               Windows minion is not seeded, the companion's choice: one first-logon CommandLine holds
                               at most 1024 characters, a PEM private key is longer, and splitting it across commands
                               was not built or run, so the Windows minion keeps acceptance by exact id
  GUESTCFG_API_SOURCE_RANGES   comma-separated CIDRs set as the API load balancer's loadBalancerSourceRanges, on
                               both paths; unset leaves the field out on the supervisor path and passes 0.0.0.0/0 to
                               the master blueprint, which requires the input
  GUESTCFG_PROVE_SOURCE_RANGES 1 (supervisor path): once the API answers, patch the ranges to 192.0.2.0/24
                               (TEST-NET-1), then to 0.0.0.0/0, then to GUESTCFG_RUNNER_ADDRESS/32 when it is set,
                               read after each whether the API answers from here, and restore the original ranges.
                               What it finds never fails the run; a refused patch does
  GUESTCFG_RUNNER_ADDRESS      this runner's own address as the load balancer sees it, for the third read above
  GUESTCFG_OPERATOR_SSH_KEY    one SSH public key line (supervisor path): the master and the Linux minion get an
                               account named salt-operator that signs in with it (no password, sudo), for the by-hand
                               walkthroughs; never printed or recorded. Unset, the user-data is the proven shape
  GUESTCFG_RUN_ID              for teardown: the run to remove, when the namespace holds more than one
  OUT_DIR                      where guestcfg.json goes (default the current directory)

It builds only in the namespace GUESTCFG_NAMESPACE names; a missing or non-matching namespace is a refusal. Every
object it makes carries the label handbook-guestcfg-run=<run> and a run deletes only what carries its run's label.
Every secret is generated for the run, held in Kubernetes Secrets, and never printed or written to the record; a key
pair generated on the master is never printed or recorded by the run, which holds it in memory and writes it only to the
minion's bootstrap Secret, and the install deletes the copy beside its script before anything can exit. Any failure runs the
teardown before exiting. The Salt API is reached over TLS pinned to a certificate generated for the run, through a
load balancer that exposes port 8000 and exists only for the run.

Exit: 0 done; 2 a sign-in was refused, a precondition was not met, a step failed (the teardown ran) or the record was
refused; 3 something this run created could not be removed; 5 an unknown argument. Standard library only; openssl on the PATH for the
certificate.
"""
import base64
import hashlib
import http.client
import json
import os
import re
import secrets as secretlib
import shutil
import signal
import ssl
import subprocess
import sys
import tempfile
import textwrap
import time
import urllib.error
import urllib.parse
import urllib.request
from xml.sax.saxutils import escape as xml_escape

http.client._MAXHEADERS = 1000

CCI = "/cci/kubernetes"
A3 = "infrastructure.cci.vmware.com/v1alpha3"
INFRA1 = "infrastructure.cci.vmware.com/v1alpha1"
PROJ = "project.cci.vmware.com/v1alpha2"
VMOP = "vmoperator.vmware.com"
VMAPI = "v1alpha5"
K8S_RELEASE_LABEL = "services.supervisor.vmware.com/kubernetes.vmware.com"
NODE_IMAGE = re.compile(r"v\d+\.\d+\.\d+(\+[\w.]+)?---vmware\.")
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
PLACEHOLDER = re.compile(r"(\{\{[^}]*\}\})")
IPV4 = re.compile(r"(?<![0-9.])(?:\d{1,3}\.){3}\d{1,3}(?![0-9.])")
SUFFIX = {"Ki": 1024, "Mi": 1024 ** 2, "Gi": 1024 ** 3, "Ti": 1024 ** 4,
          "K": 1000, "k": 1000, "M": 1000 ** 2, "G": 1000 ** 3, "T": 1000 ** 4}

RUN_LABEL = "handbook-guestcfg-run"
PART_OF = "guest-configuration"
RUN_ID = re.compile(r"^[0-9a-f]{6}$")
NAMESPACE = re.compile(r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$")

# Salt: 3008 LTS, pinned to one point release on both operating systems, from Broadcom's package location.
SALT_VERSION = "3008.5"
SALT_KEY_URL = "https://packages.broadcom.com/artifactory/api/security/keypair/SaltProjectKey/public"
SALT_DEB_URIS = "https://packages.broadcom.com/artifactory/saltproject-deb"
SALT_WIN_EXE = ("https://packages.broadcom.com/artifactory/saltproject-generic/windows/"
                f"{SALT_VERSION}/Salt-Minion-{SALT_VERSION}-Py3-AMD64-Setup.exe")
API_PORT = 8000
API_USER = "guestcfg-api"
# Salt's onedir Python on the master, where salt-api finds CherryPy. salt-common 3008.5 carries CherryPy 18.10.0 in it
# (read offline from the package, 2026-11-11), so the master installs nothing from the Python Package Index; its
# bootstrap logs whether the module imports.
SALT_PYTHON = "/opt/saltstack/salt/bin/python3"

# The polling limits, in seconds: the longest a run waits for each thing before it stops and tears down.
LIMITS = {
    "vm_ready": 15 * 60,        # a machine PoweredOn with an address
    "lb_address": 15 * 60,      # the load balancer's external address
    "api_login": 30 * 60,       # the master's first boot: packages, configuration, the API answering
    "linux_key": 30 * 60,       # a Linux minion's key arriving at the master
    "windows_key": 60 * 60,     # a Windows minion's key: Cloudbase-Init or Sysprep, a first boot, the installer
    "job": 20 * 60,             # one Salt job's return
    "vm_gone": 20 * 60,         # a machine's delete
    "deployment": 45 * 60,      # a VCF Automation deployment reaching CREATE_SUCCESSFUL or CREATE_FAILED
    "deployment_gone": 30 * 60, # a deployment's Deployment.Delete request completing
    "range_read": 3 * 60,       # how long each source-range setting is read before its outcome is taken
}
POLL = 15                       # seconds between reads
REPORT = 60                     # seconds between progress lines
ANSWER_TIMEOUT = 10             # seconds one read of whether the API answers may take

BOOTSTRAP_PATHS = {"cloudinit": "cloud-init through Cloudbase-Init", "sysprep": "Sysprep (rawSysprep)"}
VIA_PATHS = {"supervisor": "directly at the namespace endpoint", "automation": "VCF Automation blueprints"}
KEY_MODES = {"accept": "accepted by exact expected id", "preseed": "generated on the master and seeded at bootstrap"}

# The automation path: the three blueprints beside this script, created in the project from the files as written.
TEMPLATES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates", "02x-vm-salt-minion")
BLUEPRINT_FILES = {"master": "salt-master.blueprint.yaml", "linux": "salt-minion-linux.blueprint.yaml",
                   "windows": "salt-minion-windows-sysprep.blueprint.yaml"}
# Every object a blueprint makes says so, and a teardown on the supervisor path never deletes one: a deployment's
# objects go through the deployment's own Delete (the record, never the machines underneath it).
MANAGED_BY = "app.kubernetes.io/managed-by"
AUTOMATION = "vcf-automation"
ACTIVE_DEPLOYMENT = ("CREATE_SUCCESSFUL", "CREATE_FAILED")

# loadBalancerSourceRanges: two documentation values that are never an estate's, and the shape of a range.
TEST_NET_1 = "192.0.2.0/24"     # TEST-NET-1: no runner is in it
ANY_SOURCE = "0.0.0.0/0"
CIDR = re.compile(r"^(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)/(?:3[0-2]|[12]?\d)$")
ADDRESS = re.compile(r"^(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)$")


def _now():
    return time.monotonic()


def _sleep(seconds):
    time.sleep(seconds)


def ctx():
    verify = os.environ.get("TLS_VERIFY", "true").strip().lower() not in ("0", "false", "no", "off")
    return ssl.create_default_context() if verify else ssl._create_unverified_context()


def pinned_context(cert_pem):
    """TLS context for the Salt API: only the certificate this run generated is trusted, so no hostname check is
    needed and no verification is turned off. The address is the load balancer's, unknown when the certificate is made."""
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.load_verify_locations(cadata=cert_pem)
    return context


def qty(v):
    """A Kubernetes quantity; a bare number is bytes. None when it is not a quantity."""
    m = re.match(r"^(\d+(?:\.\d+)?)([A-Za-z]*)$", str(v).strip())
    if not m or (m.group(2) and m.group(2) not in SUFFIX):
        return None
    return int(float(m.group(1)) * SUFFIX.get(m.group(2), 1))


def secret(name):
    """A secret from NAME_FILE (a file, mode 0600, its value stripped) or else NAME itself; None when neither is set.
    A file open to group or other is refused before it is read; the refusal names the variable, never the content."""
    path = os.environ.get(f"{name}_FILE")
    if path:
        with open(path, encoding="utf-8") as f:
            mode = os.fstat(f.fileno()).st_mode & 0o777
            if mode & 0o077 and os.name != "nt":
                raise PermissionError(f"{name}_FILE names a file of mode {mode:04o}, open to group or other: "
                                      f'run chmod 600 "${name}_FILE" and try again (the file was not read)')
            return f.read().strip()
    return os.environ.get(name) or None


class Refusal(Exception):
    """A precondition is not met; nothing was created."""


class StepFailed(Exception):
    """A step failed; the teardown runs before the script exits."""


class Labels:
    """Estate names become placeholders. Secrets become a fixed marker. The product's own vocabulary is left alone."""

    RESERVED = {"admin", "view", "edit", "user", "owner", "default", "system", "none", "all", "VirtualMachine", "Namespace",
                "VM", "Delete", "PowerOn", "PowerOff", "true", "false", "Debian", "Windows", "Linux", "PoweredOn",
                "best-effort-small", "best-effort-medium", "best-effort-xsmall", "best-effort-large",
                # the companion's own setting values: an estate can name an object one of them (a storage class called
                # supervisor), and scrubbing it would rewrite this script's prose ("the supervisor path")
                "supervisor", "automation", "accept", "preseed", "sysprep", "cloudinit"}

    def __init__(self):
        self.maps = {}
        self.secrets = []

    def get(self, family, name):
        if not name or str(name) in self.RESERVED:
            return name
        m = self.maps.setdefault(family, {})
        if name not in m:
            m[name] = f"{family}-{len(m) + 1}"
        return "{{%s}}" % m[name]

    def hold(self, value):
        """Register a secret: its exact text never reaches stdout or the record."""
        if value and value not in self.secrets:
            self.secrets.append(value)

    def scrub(self, text, addresses=False):
        """Replace every registered name in one pass, never inside a placeholder already written (G-646), withhold every
        registered secret first, and with addresses=True replace any dotted-quad address, for text the platform wrote."""
        if not isinstance(text, str):
            return text
        for value in sorted(self.secrets, key=len, reverse=True):
            text = text.replace(value, "{{withheld}}")
        label = {real: lab for m in self.maps.values() for real, lab in m.items()}
        names = sorted(label, key=len, reverse=True)
        rx = re.compile(r"(?<![A-Za-z0-9-])(" + "|".join(map(re.escape, names)) + r")(?![A-Za-z0-9-])") if names else None
        parts = PLACEHOLDER.split(text)
        for i in range(0, len(parts), 2):
            if rx:
                parts[i] = rx.sub(lambda mt: "{{%s}}" % label[mt.group(1)], parts[i])
            parts[i] = UUID.sub("{{id}}", parts[i])
            if addresses:
                parts[i] = IPV4.sub("{{address}}", parts[i])
        return "".join(parts)


class Estate:
    """One bearer, renewed when it ends, and two base URLs: the organization gateway and the namespace's own endpoint."""

    def __init__(self, host, org, refresh_token=None, user=None, password=None):
        self.host, self.org = host, org
        self._refresh, self._user, self._password = refresh_token, user, password
        self.kind = "refresh token" if refresh_token else "session login"
        self.bearer = None
        self._mint()

    def _mint(self):
        """Sign in and take a bearer. A run can outlast one, and a teardown that met an ended bearer would leave machines."""
        if self._refresh:
            body = urllib.parse.urlencode({"grant_type": "refresh_token", "refresh_token": self._refresh}).encode()
            req = urllib.request.Request(f"https://{self.host}/oauth/tenant/{self.org}/token", data=body, method="POST",
                                         headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"})
        else:
            basic = base64.b64encode(f"{self._user.split('@')[0]}@{self.org}:{self._password}".encode()).decode()
            req = urllib.request.Request(f"https://{self.host}/cloudapi/1.0.0/sessions", method="POST",
                                         headers={"Authorization": f"Basic {basic}", "Accept": "application/json;version=40.0"})
        try:
            # 120 s: on 2026-11-11 a VCF Automation 9.1.1 under load took 55 s to answer a session sign-in that normally
            # answers in a few, and a 30 s limit refused every run while the platform still worked
            with urllib.request.urlopen(req, context=ctx(), timeout=120) as r:
                self.bearer = json.loads(r.read())["access_token"] if self._refresh else r.headers.get("X-VMWARE-VCLOUD-ACCESS-TOKEN")
        except urllib.error.HTTPError as ex:
            raise Refusal(f"the {self.kind} answered HTTP {ex.code}") from None
        except (urllib.error.URLError, OSError) as ex:
            raise Refusal(f"the {self.kind} did not answer: {ex}") from None
        if not self.bearer:
            raise Refusal(f"the {self.kind} answered without a bearer")
        L.hold(self.bearer)

    def call(self, url, method="GET", payload=None, renewed=False, content_type="application/json"):
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(url, data=data, method=method, headers={
            "Authorization": f"Bearer {self.bearer}", "Accept": "application/json",
            **({"Content-Type": content_type} if data else {})})
        try:
            with urllib.request.urlopen(req, context=ctx(), timeout=180) as r:
                return r.status, json.loads(r.read() or b"null")
        except urllib.error.HTTPError as ex:
            if ex.code == 401 and not renewed:      # the bearer ended: sign in once more and send the same request again
                try:
                    self._mint()
                except Refusal:
                    return 401, {}
                return self.call(url, method, payload, renewed=True, content_type=content_type)
            raw = ex.read()
            try:
                return ex.code, json.loads(raw)
            except ValueError:
                return ex.code, {}
        except (urllib.error.URLError, OSError, ValueError):
            return None, {}

    def gw(self, path, method="GET", payload=None):
        return self.call(f"https://{self.host}{CCI}{path}", method, payload)

    def ns(self, endpoint, path, method="GET", payload=None, content_type="application/json"):
        return self.call(endpoint.rstrip("/") + path, method, payload, content_type=content_type)

    def api(self, path, method="GET", payload=None):
        """VCF Automation's own APIs on the same host: projects, blueprints, deployments."""
        return self.call(f"https://{self.host}{path}", method, payload)

    def pages(self, path):
        """Every item of a VCF Automation paged list (content, totalPages); a list that fails is a refusal."""
        out, page = [], 0
        while True:
            sep = "&" if "?" in path else "?"
            st, body = self.api(f"{path}{sep}size=200&page={page}")
            if st != 200 or not isinstance(body, dict):
                raise Refusal(f"GET {path.split('?')[0]} answered {st if st else 'nothing'}")
            out += body.get("content") or []
            page += 1
            if page >= (body.get("totalPages") or 1):
                return out

    def items(self, base, path):
        """Every item of a Kubernetes-style list, following its continue token; a list that fails is a refusal."""
        out, token = [], None
        while True:
            sep = "&" if "?" in path else "?"
            st, body = self.call(base.rstrip("/") + path + (f"{sep}continue={urllib.parse.quote(token)}" if token else ""))
            if st != 200 or not isinstance(body, dict):
                raise Refusal(f"GET {path} answered {st if st else 'nothing'}")
            out += body.get("items") or []
            token = (body.get("metadata") or {}).get("continue")
            if not token:
                return out


def msg(r):
    if isinstance(r, dict):
        return " ".join(str(r.get("message") or r.get("detail") or r.get("error") or "").split())
    return ""


def gateway(e):
    return f"https://{e.host}{CCI}"


def _endpoints(e, project):
    return [(project, n["metadata"]["name"], (n.get("status") or {}).get("namespaceEndpointURL"))
            for n in e.items(gateway(e), f"/apis/{A3}/namespaces/{project}/supervisornamespaces")
            if (n.get("status") or {}).get("namespaceEndpointURL")]


def quota(e, url, name):
    """A namespace's storage limit and use in bytes, and whether the limit is stated at all."""
    lim, used, stated = 0, 0, False
    for item in e.items(url, f"/apis/cns.vmware.com/v1alpha1/namespaces/{name}/storagepolicyquotas"):
        conv = json.loads((item.get("metadata") or {}).get("annotations", {}).get("cns.vmware.com/conversion", "{}") or "{}")
        stt = conv.get("status") or {}
        limit = qty(stt.get("appliedLimit") or (item.get("spec") or {}).get("limit") or "")
        if limit is not None:
            lim, stated = lim + limit, True
        used += sum(qty(t["scQuotaUsage"]["used"]) or 0 for t in (stt.get("total") or []))
    return lim, used, stated


# --------------------------------------------------------------------------- what the run builds

# The names of a run. A minion id is its machine's name, so one string identifies the machine and its key.
def names(run_id):
    """The run's object names. The Windows machine's name is also its host name, and VM Operator refuses a Windows name
    over 15 characters on the Sysprep path, so it takes a short form of its own."""
    prefix = f"guestcfg-{run_id}"
    return {"prefix": prefix, "master": f"{prefix}-master", "linux": f"{prefix}-linux", "windows": f"gc-{run_id}-win",
            "lb": f"{prefix}-api", "api_secret": f"{prefix}-api-access", "master_secret": f"{prefix}-master-bootstrap",
            "linux_secret": f"{prefix}-linux-bootstrap", "windows_secret": f"{prefix}-windows-bootstrap",
            # the automation path: the Windows blueprint's name input, the blueprints, and its Windows Secret's name
            "windows_app": f"gc-{run_id}", "windows_bp_secret": f"gc-{run_id}-win-bootstrap",
            "bp_master": f"{prefix}-salt-master", "bp_linux": f"{prefix}-salt-minion-linux",
            "bp_windows": f"{prefix}-salt-minion-windows-sysprep"}


def blueprint_name(n, role):
    return n[{"master": "bp_master", "linux": "bp_linux", "windows": "bp_windows"}[role]]


EXPECTED_ID = re.compile(r"^(guestcfg-[0-9a-f]{6}-linux|gc-[0-9a-f]{6}-win)$")
GRAINS = ("os_family", "osfinger", "saltversion")


def labels_for(name, component, run_id=None, managed_by=None):
    labels = {"app": name, "app.kubernetes.io/name": name, "app.kubernetes.io/component": component,
              "app.kubernetes.io/part-of": PART_OF}
    if run_id:
        labels[RUN_LABEL] = run_id
    if managed_by:
        labels[MANAGED_BY] = managed_by
    return labels


def secret_manifest(name, string_data, component, run_id=None, managed_by=None):
    return {"apiVersion": "v1", "kind": "Secret",
            "metadata": {"name": name, "labels": labels_for(name, component, run_id, managed_by)},
            "type": "Opaque", "stringData": string_data}


def vm_manifest(name, component, image, vm_class, storage, bootstrap, run_id=None, managed_by=None):
    return {"apiVersion": f"{VMOP}/{VMAPI}", "kind": "VirtualMachine",
            "metadata": {"name": name, "labels": labels_for(name, component, run_id, managed_by)},
            "spec": {"className": vm_class, "imageName": image, "storageClass": storage, "powerState": "PoweredOn",
                     "bootstrap": bootstrap}}


def lb_manifest(name, master_app, run_id=None, source_ranges=None, managed_by=None):
    """The API's load balancer: port 8000 only. With source_ranges, loadBalancerSourceRanges restricts who may reach it,
    where the provider supports it; VM Operator's v1alpha5 reference: "This field will be ignored if the provider does
    not support the feature." """
    spec = {"type": "LoadBalancer", "selector": {"app": master_app},
            "ports": [{"name": "salt-api", "protocol": "TCP", "port": API_PORT, "targetPort": API_PORT}]}
    if source_ranges is not None:
        spec["loadBalancerSourceRanges"] = list(source_ranges)
    return {"apiVersion": f"{VMOP}/{VMAPI}", "kind": "VirtualMachineService",
            "metadata": {"name": name, "labels": labels_for(name, "salt-api", run_id, managed_by)}, "spec": spec}


def cloud_init_bootstrap(secret_name):
    return {"cloudInit": {"rawCloudConfig": {"name": secret_name, "key": "user-data"}}}


def sysprep_bootstrap(secret_name):
    return {"sysprep": {"rawSysprep": {"name": secret_name, "key": "unattend"}}}


def _block(text, width):
    pad = " " * width
    return "\n".join(pad + line if line else "" for line in text.splitlines())


def b64(text):
    """One line of base64: how a blueprint input carries a multi-line value into a cloud-config without meeting its
    indentation, and how cloud-init's write_files takes it back (encoding: b64)."""
    return base64.b64encode(text.encode()).decode()


def _b64_file(path, permissions, encoded):
    """One write_files entry whose content is one line of base64. Single quotes are safe: base64 has none."""
    return (f"  - path: {path}\n"
            f"    permissions: '{permissions}'\n"
            "    encoding: b64\n"
            f"    content: '{encoded}'\n")


def salt_sources():
    """The apt source Salt's install guide publishes, minus the description lines, so a guest reaches only Broadcom's
    package location for it."""
    return textwrap.dedent(f"""\
        X-Repolib-Name: Salt Project
        Enabled: yes
        Types: deb
        URIs: {SALT_DEB_URIS}
        Signed-By: /etc/apt/keyrings/salt-archive-keyring.pgp
        Suites: stable
        Components: main
        """)


def salt_pin():
    return "Package: salt-*\nPin: version 3008.*\nPin-Priority: 1001\n"


def _install_head():
    """The Linux bootstrap's opening: the shell settings and the helpers, before anything that can exit."""
    return textwrap.dedent(f"""\
        #!/bin/bash
        set -uo pipefail
        export DEBIAN_FRONTEND=noninteractive
        log() {{ echo "[guestcfg $(date -u +%H:%M:%SZ)] $*"; }}
        retry() {{ local left=$1; shift; until "$@"; do left=$((left-1)); [ "$left" -gt 0 ] || return 1; log "retrying: $*"; sleep 20; done; }}
        fetch_key() {{ curl -fsSL --retry 3 --retry-delay 5 "{SALT_KEY_URL}" | gpg --dearmor --yes -o /etc/apt/keyrings/salt-archive-keyring.pgp; }}
        apt_up() {{ apt-get -o DPkg::Lock::Timeout=300 update; }}
        """)


def _install_network():
    """The Linux bootstrap's network half: the repository key and source, the 3008 pin, retries on the network. Either
    read exits the script when it fails."""
    return textwrap.dedent("""\
        install -d -m 755 /etc/apt/keyrings
        retry 6 fetch_key || { log "the Salt signing key could not be fetched"; exit 1; }
        install -m 0644 /opt/guestcfg/salt.sources /etc/apt/sources.list.d/salt.sources
        install -m 0644 /opt/guestcfg/salt-pin /etc/apt/preferences.d/salt-pin-1001
        retry 6 apt_up || { log "the Salt repository could not be read"; exit 1; }
        """)


def _install_common():
    """The shared first half of the Linux bootstrap: the helpers, then the repository key and source, the 3008 pin, retries
    on the network."""
    return _install_head() + _install_network()


def linux_master_install(version=SALT_VERSION):
    """The master's install script: packages at one version, then the run's configuration, owned so the salt user reads it."""
    return _install_common() + textwrap.dedent(f"""\
        apt_in() {{ apt-get -o DPkg::Lock::Timeout=300 install -y salt-common={version} salt-master={version} salt-api={version}; }}
        retry 3 apt_in || {{ log "the Salt master packages did not install"; exit 1; }}
        apt-mark hold salt-common salt-master salt-api
        if {SALT_PYTHON} -c 'import cherrypy'; then log "CherryPy imports in Salt's own Python: salt-api has its web server"; else log "CherryPy does not import in Salt's own Python: salt-api cannot serve"; fi
        install -d -o root -g salt -m 0750 /etc/salt/guestcfg
        install -o root -g salt -m 0640 /opt/guestcfg/api.digest /etc/salt/guestcfg/api.digest
        install -o root -g salt -m 0640 /opt/guestcfg/api.crt /etc/salt/guestcfg/api.crt
        install -o root -g salt -m 0640 /opt/guestcfg/api.key /etc/salt/guestcfg/api.key
        install -m 0644 /opt/guestcfg/master.conf /etc/salt/master.d/guestcfg.conf
        systemctl enable salt-master salt-api
        systemctl restart salt-master
        sleep 10
        systemctl restart salt-api
        log "salt-master and salt-api restarted with the run's configuration"
        """)


def linux_minion_install(version=SALT_VERSION, seeded=False):
    """A Linux minion's install. With seeded, a key pair written beside the script, when it is not empty, goes into the
    minion's key directory before the package is installed, so the minion's first start presents it. Salt's page on
    preseeding names the two files, /etc/salt/pki/minion/minion.pem and minion.pub, placed "before starting the
    salt-minion daemon". The seeding comes before anything that can exit, so the copy of the private key beside the
    script is deleted whatever happens to the network reads after it."""
    seed = textwrap.dedent("""\
        if [ -s /opt/guestcfg/minion.pem ] && [ -s /opt/guestcfg/minion.pub ]; then
          install -d -m 0700 /etc/salt/pki/minion
          install -m 0400 /opt/guestcfg/minion.pem /etc/salt/pki/minion/minion.pem
          install -m 0644 /opt/guestcfg/minion.pub /etc/salt/pki/minion/minion.pub
          rm -f /opt/guestcfg/minion.pem
          log "the key pair generated on the master is in place before the minion first starts"
        else
          rm -f /opt/guestcfg/minion.pem
          log "no key pair was seeded: the minion makes its own at first start"
        fi
        """) if seeded else ""
    return _install_head() + seed + _install_network() + textwrap.dedent(f"""\
        apt_in() {{ apt-get -o DPkg::Lock::Timeout=300 install -y salt-common={version} salt-minion={version}; }}
        retry 3 apt_in || {{ log "the Salt minion packages did not install"; exit 1; }}
        apt-mark hold salt-common salt-minion
        install -m 0644 /opt/guestcfg/minion.conf /etc/salt/minion.d/guestcfg.conf
        systemctl enable salt-minion
        systemctl restart salt-minion
        log "salt-minion restarted with the run's configuration"
        """)


def master_config(linux_id, windows_id, digest_path="/etc/salt/guestcfg/api.digest", gen_accept=False):
    """The master's configuration. auto_accept and open_mode stated at their defaults, the API on TLS, the API account
    allowed exactly the functions this run calls, on exactly the two minions it expects: key.finger and key.print, both
    read-only, for the probe's comparison, and key.gen_accept only when the run generates a minion's key pair on the
    master."""
    text = textwrap.dedent(f"""\
        auto_accept: False
        open_mode: False
        file_roots:
          base:
            - /srv/salt
        netapi_enable_clients:
          - local_async
          - runner
          - wheel
        rest_cherrypy:
          port: {API_PORT}
          ssl_crt: /etc/salt/guestcfg/api.crt
          ssl_key: /etc/salt/guestcfg/api.key
        external_auth:
          file:
            ^filename: {digest_path}
            ^hashtype: sha256
            {API_USER}:
              - 'L@{linux_id},{windows_id}':
                  - test.ping
                  - grains.item
                  - state.apply
              - '@wheel':
                  - key.list_all
                  - key.accept
                  - key.delete
                  - key.finger
                  - key.print
              - '@runner':
                  - jobs.lookup_jid
        """)
    printed = "          - key.print\n"
    return text.replace(printed, printed + "          - key.gen_accept\n") if gen_accept else text


def _load_states():
    base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "states", "guestcfg")
    out = {}
    for name in ("init.sls", "drift.sls", "probe.sls"):
        with open(os.path.join(base, name), encoding="utf-8") as f:
            out[name] = f.read()
    return out


# Not "operator": Ubuntu's base system already has a group of that name (gid 37), so useradd refuses a user named
# operator, cloud-init logs it and carries on, and SSH says only "Permission denied" (walkthrough proof, 2026-11-12).
OPERATOR_USER = "salt-operator"


def operator_users(operator_key):
    """The optional operator login for the by-hand walkthroughs: cloud-init's default user kept, and one named account
    that signs in with the reader's SSH public key only (no password), with sudo for the lessons that change a managed
    file. Absent, it renders nothing, so a run without a key builds exactly the user-data the proofs ran."""
    if not operator_key:
        return ""
    return ("users:\n"
            "  - default\n"
            f"  - name: {OPERATOR_USER}\n"
            "    groups: [sudo]\n"
            "    shell: /bin/bash\n"
            "    sudo: ALL=(ALL) NOPASSWD:ALL\n"
            "    lock_passwd: true\n"
            "    ssh_authorized_keys:\n"
            f"      - {operator_key}\n")


def operator_key_from_env():
    """GUESTCFG_OPERATOR_SSH_KEY, one public key line, or None. A private key, or anything that is not one line of a
    public key, is refused before anything opens."""
    raw = (os.environ.get("GUESTCFG_OPERATOR_SSH_KEY") or "").strip()
    if not raw:
        return None
    if "\n" in raw or "PRIVATE KEY" in raw or not re.match(r"^(ssh-(ed25519|rsa)|ecdsa-sha2-nistp(256|384|521)) [A-Za-z0-9+/=]+( \S.*)?$", raw):
        raise ValueError("GUESTCFG_OPERATOR_SSH_KEY must be one public key line (ssh-ed25519, ssh-rsa or ecdsa-sha2-*)")
    return raw


# ---- VM Apps: the same install, run so that a reboot in the middle of the first boot cannot strand it (G-988)

VM_APPS_BOOT = "/var/lib/cloud/scripts/per-boot/10-guestcfg.sh"
VM_APPS_DONE = "/var/lib/guestcfg/installed"


def apt_timeouts():
    """apt's waits, bounded: on a stalled mirror apt-get otherwise waits on one connection for good (G-988)."""
    return 'Acquire::http::Timeout "30";\nAcquire::https::Timeout "30";\nAcquire::Retries "3";\n'


def vm_apps_boot_script():
    """On VM Apps, vSphere's guest customization can reboot the machine while cloud-init's first boot is still running,
    and cloud-init never runs again a once-per-instance module it started (G-988). So the install is not a runcmd: this script, in
    cloud-init's per-boot directory, runs at every boot until it has finished once. It finishes an interrupted dpkg,
    bounds apt's waits, installs what the install script needs, runs the same install.sh the supervisor path runs, and
    sets its marker only when that succeeds; on a later boot the marker makes it exit at once."""
    return textwrap.dedent(f"""\
        #!/bin/bash
        set -uo pipefail
        [ -f {VM_APPS_DONE} ] && exit 0
        export DEBIAN_FRONTEND=noninteractive
        log() {{ echo "[guestcfg $(date -u +%H:%M:%SZ)] $*"; }}
        systemctl stop unattended-upgrades apt-daily.timer apt-daily-upgrade.timer 2>/dev/null || true
        dpkg --configure -a || true
        install -m 0644 /opt/guestcfg/apt-timeouts /etc/apt/apt.conf.d/99guestcfg-timeouts
        prereq() {{ apt-get -o DPkg::Lock::Timeout=300 update && apt-get -o DPkg::Lock::Timeout=300 install -y ca-certificates curl gnupg; }}
        left=6; until prereq; do left=$((left-1)); [ "$left" -gt 0 ] || {{ log "the install's prerequisites did not install"; exit 1; }}; sleep 30; done
        bash /opt/guestcfg/install.sh || {{ log "install.sh failed; the next boot runs it again"; exit 1; }}
        install -d -m 0755 {os.path.dirname(VM_APPS_DONE)}
        touch {VM_APPS_DONE}
        log "installed; later boots skip this script"
        """)


def _vm_apps_files():
    return ("  - path: /opt/guestcfg/apt-timeouts\n"
            "    permissions: '0644'\n"
            "    content: |\n" + _block(apt_timeouts(), 6) + "\n"
            f"  - path: {VM_APPS_BOOT}\n"
            "    permissions: '0755'\n"
            "    content: |\n" + _block(vm_apps_boot_script(), 6) + "\n")


def _first_boot_tail(vm_apps):
    """How the install runs: a runcmd on the VM Service, the per-boot script on VM Apps (written by write_files, which
    finishes before the customization's reboot)."""
    return _vm_apps_files() if vm_apps else "runcmd:\n  - [bash, /opt/guestcfg/install.sh]\n"


_PACKAGES = ("packages:\n"
             "  - ca-certificates\n"
             "  - curl\n"
             "  - gnupg\n")


def render_master_user_data(name, linux_id, windows_id, api_digest_line, tls_cert, tls_key, states, encoded=False,
                            gen_accept=False, operator_key=None, vm_apps=False):
    """The master's first boot: Salt 3008 LTS, its configuration, the API's certificate and the states the run applies.
    With encoded, the digest line, the certificate and the key are each one line of base64 that write_files decodes:
    the shape of salt-master.blueprint.yaml, whose inputs carry them."""
    states_files = "".join(f"  - path: /srv/salt/guestcfg/{fname}\n    permissions: '0644'\n    content: |\n" + _block(body, 6) + "\n"
                           for fname, body in states.items())
    if encoded:
        api_files = (_b64_file("/opt/guestcfg/api.digest", "0600", b64(api_digest_line + "\n"))
                     + _b64_file("/opt/guestcfg/api.crt", "0644", b64(tls_cert))
                     + _b64_file("/opt/guestcfg/api.key", "0600", b64(tls_key)))
    else:
        api_files = ("  - path: /opt/guestcfg/api.digest\n"
                     "    permissions: '0600'\n"
                     "    content: |\n" + _block(api_digest_line, 6) + "\n"
                     "  - path: /opt/guestcfg/api.crt\n"
                     "    permissions: '0644'\n"
                     "    content: |\n" + _block(tls_cert, 6) + "\n"
                     "  - path: /opt/guestcfg/api.key\n"
                     "    permissions: '0600'\n"
                     "    content: |\n" + _block(tls_key, 6) + "\n")
    return ("#cloud-config\n"
            f"hostname: {name}\n"
            + operator_users(operator_key) +
            "bootcmd:\n"
            "  - systemctl stop unattended-upgrades 2>/dev/null || true\n"
            "  - systemctl stop apt-daily.timer apt-daily-upgrade.timer 2>/dev/null || true\n"
            + ("" if vm_apps else _PACKAGES) +
            "write_files:\n"
            "  - path: /opt/guestcfg/salt.sources\n"
            "    permissions: '0644'\n"
            "    content: |\n" + _block(salt_sources(), 6) + "\n"
            "  - path: /opt/guestcfg/salt-pin\n"
            "    permissions: '0644'\n"
            "    content: |\n" + _block(salt_pin(), 6) + "\n"
            "  - path: /opt/guestcfg/master.conf\n"
            "    permissions: '0600'\n"
            "    content: |\n" + _block(master_config(linux_id, windows_id, gen_accept=gen_accept), 6) + "\n"
            + api_files
            + states_files +
            "  - path: /opt/guestcfg/install.sh\n"
            "    permissions: '0700'\n"
            "    content: |\n" + _block(linux_master_install(), 6) + "\n"
            + _first_boot_tail(vm_apps))


def render_linux_user_data(name, master_ip, pem_b64=None, pub_b64=None, operator_key=None, vm_apps=False):
    """A Linux minion's first boot: the same repository, the master's address, the minion's own id. Given a key pair
    (each one line of base64, both empty for none: the shape of salt-minion-linux.blueprint.yaml), write_files holds
    it beside the script and the install puts a non-empty pair in place before the minion first starts."""
    minion_conf = f"master: {master_ip}\nid: {name}\n"
    seeded = pem_b64 is not None or pub_b64 is not None
    key_files = (_b64_file("/opt/guestcfg/minion.pem", "0600", pem_b64 or "")
                 + _b64_file("/opt/guestcfg/minion.pub", "0644", pub_b64 or "")) if seeded else ""
    return ("#cloud-config\n"
            f"hostname: {name}\n"
            + operator_users(operator_key) +
            "bootcmd:\n"
            "  - systemctl stop unattended-upgrades 2>/dev/null || true\n"
            "  - systemctl stop apt-daily.timer apt-daily-upgrade.timer 2>/dev/null || true\n"
            + ("" if vm_apps else _PACKAGES) +
            "write_files:\n"
            "  - path: /opt/guestcfg/salt.sources\n"
            "    permissions: '0644'\n"
            "    content: |\n" + _block(salt_sources(), 6) + "\n"
            "  - path: /opt/guestcfg/salt-pin\n"
            "    permissions: '0644'\n"
            "    content: |\n" + _block(salt_pin(), 6) + "\n"
            "  - path: /opt/guestcfg/minion.conf\n"
            "    permissions: '0644'\n"
            "    content: |\n" + _block(minion_conf, 6) + "\n"
            + key_files +
            "  - path: /opt/guestcfg/install.sh\n"
            "    permissions: '0700'\n"
            "    content: |\n" + _block(linux_minion_install(seeded=seeded), 6) + "\n"
            + _first_boot_tail(vm_apps))


def windows_install_snippet(master_ip, minion_id, exe_url=SALT_WIN_EXE):
    """The minion install in PowerShell, one line, in the Nullsoft silent form of Salt's install guide. Written without
    double quotes so the Sysprep path can quote it in FirstLogonCommands and without doubled braces, which the VM
    Service's template engine would read. Both paths run this same text."""
    return ("$ProgressPreference='SilentlyContinue'; $ErrorActionPreference='Stop'; "
            f"$url='{exe_url}'; "
            "$exe=Join-Path $env:TEMP 'Salt-Minion-Setup.exe'; "
            "for($i=1;$i -le 10;$i++){ try { [Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; "
            "Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $exe; break } "
            "catch { if($i -eq 10){ throw }; Start-Sleep -Seconds 30 } }; "
            f"Start-Process -FilePath $exe -ArgumentList '/S','/master={master_ip}','/minion-name={minion_id}' -Wait")


def sign_out_command():
    """The second first-logon command: sign the automatic Administrator session out once the install has finished.
    Microsoft's page for a SynchronousCommand's Order says these commands "are now started at the same time, and no
    longer wait for the previous command to finish", so this one does not trust its Order: it waits until the
    salt-minion service runs and the installer has exited (60 minutes at most, then it signs out regardless), and then
    signs out with shutdown.exe /l. Written without doubled braces, which the VM Service's template engine would read."""
    return ('powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "'
            "$deadline=(Get-Date).AddMinutes(60); "
            "while((Get-Date) -lt $deadline){ "
            "$svc=Get-Service salt-minion -ErrorAction SilentlyContinue; "
            "$setup=Get-Process Salt-Minion-Setup -ErrorAction SilentlyContinue; "
            "if($svc -and $svc.Status -eq 'Running' -and -not $setup){ break }; "
            "Start-Sleep -Seconds 10 }; "
            'shutdown.exe /l"')


def render_windows_user_data(minion_id, master_ip):
    """A Windows minion's first boot through Cloudbase-Init: user-data its first line marks as PowerShell."""
    return "#ps1_sysnative\n" + windows_install_snippet(master_ip, minion_id) + "\n"


def windows_admin_password_line(admin_password):
    """VM Apps: the first boot sets the built-in Administrator's password and enables the account, the login a reader
    signs in with to compare the minion's key. On the reference estate's image remoteAccess set no password any
    account accepted (G-989), so the first boot does it. The password is a single-quoted PowerShell string, so the
    blueprint's input refuses a single quote."""
    return ("$ErrorActionPreference='Stop'; "
            f"Set-LocalUser -Name Administrator -Password (ConvertTo-SecureString -String '{admin_password}' -AsPlainText -Force); "
            "Enable-LocalUser -Name Administrator")


def render_windows_vm_apps_cloud_config(minion_id, master_ip, admin_password):
    """A Windows minion's cloudConfig on VM Apps: the Administrator's password, then the same PowerShell install, as
    one part of a MIME multipart document, the form the VM Apps organization's own Windows blueprints hand to
    Cloudbase-Init."""
    return ('Content-Type: multipart/mixed; boundary="==guestcfg=="\n'
            "MIME-Version: 1.0\n"
            "\n"
            "--==guestcfg==\n"
            'Content-Type: text/x-shellscript; charset="us-ascii"\n'
            "MIME-Version: 1.0\n"
            "Content-Transfer-Encoding: 7bit\n"
            'Content-Disposition: attachment; filename="salt-minion.ps1"\n'
            "\n"
            "#ps1_sysnative\n"
            + windows_admin_password_line(admin_password) + "\n"
            + windows_install_snippet(master_ip, minion_id) + "\n"
            "--==guestcfg==--\n")


def render_windows_unattend(minion_id, master_ip, admin_password):
    """A Windows minion's first boot through Sysprep: the VM Operator project's raw Sysprep minimal configuration for
    the network and the customization status, the OOBE settings from the same page, and an automatic first logon that
    runs the same install and then signs the session out (sign_out_command). Two fields follow Microsoft's unattend
    reference rather than that page's example: a DNS server's address is the IpAddress element's value with its key an
    index, and the default route's Prefix is 0.0.0.0/0, a prefix rather than a subnet mask."""
    command = ('powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "'
               + windows_install_snippet(master_ip, minion_id) + '"')
    password = xml_escape(admin_password)
    return textwrap.dedent(f"""\
        <?xml version="1.0" encoding="UTF-8"?>
        <unattend xmlns="urn:schemas-microsoft-com:unattend">
          <settings pass="specialize">
            <component name="Microsoft-Windows-TCPIP" processorArchitecture="amd64" publicKeyToken="31bf3856ad364e35" language="neutral" versionScope="nonSxS" xmlns:wcm="http://schemas.microsoft.com/WMIConfig/2002/State" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
              <Interfaces>
                <Interface wcm:action="add">
                  <Ipv4Settings>
                    <DhcpEnabled>false</DhcpEnabled>
                  </Ipv4Settings>
                  <Ipv6Settings>
                    <DhcpEnabled>false</DhcpEnabled>
                  </Ipv6Settings>
                  <Identifier>{{{{ V1alpha5_FirstNicMacAddr }}}}</Identifier>
                  <UnicastIpAddresses>
                    <IpAddress wcm:action="add" wcm:keyValue="1">{{{{ V1alpha5_FirstIP }}}}</IpAddress>
                  </UnicastIpAddresses>
                  <Routes>
                    <Route wcm:action="add">
                      <Identifier>0</Identifier>
                      <Metric>10</Metric>
                      <NextHopAddress>{{{{ (index .V1alpha5.Net.Devices 0).Gateway4 }}}}</NextHopAddress>
                      <Prefix>0.0.0.0/0</Prefix>
                    </Route>
                  </Routes>
                </Interface>
              </Interfaces>
            </component>
            <component name="Microsoft-Windows-DNS-Client" processorArchitecture="amd64" publicKeyToken="31bf3856ad364e35" language="neutral" versionScope="nonSxS" xmlns:wcm="http://schemas.microsoft.com/WMIConfig/2002/State" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
              <Interfaces>
                <Interface wcm:action="add">
                  <Identifier>{{{{ V1alpha5_FirstNicMacAddr }}}}</Identifier>
                  <DNSServerSearchOrder>
                    <IpAddress wcm:action="add" wcm:keyValue="1">{{{{ index .V1alpha5.Net.Nameservers 0 }}}}</IpAddress>
                    {{{{ if gt (len .V1alpha5.Net.Nameservers) 1 }}}}<IpAddress wcm:action="add" wcm:keyValue="2">{{{{ index .V1alpha5.Net.Nameservers 1 }}}}</IpAddress>{{{{ end }}}}
                  </DNSServerSearchOrder>
                </Interface>
              </Interfaces>
            </component>
            <component name="Microsoft-Windows-Deployment" processorArchitecture="amd64" publicKeyToken="31bf3856ad364e35" language="neutral" versionScope="nonSxS" xmlns:wcm="http://schemas.microsoft.com/WMIConfig/2002/State" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
              <RunSynchronous>
                <RunSynchronousCommand wcm:action="add">
                  <Path>C:\\sysprep\\guestcustutil.exe restoreMountedDevices</Path>
                  <Order>1</Order>
                </RunSynchronousCommand>
                <RunSynchronousCommand wcm:action="add">
                  <Path>C:\\sysprep\\guestcustutil.exe flagComplete</Path>
                  <Order>2</Order>
                </RunSynchronousCommand>
                <RunSynchronousCommand wcm:action="add">
                  <Path>C:\\sysprep\\guestcustutil.exe deleteContainingFolder</Path>
                  <Order>3</Order>
                </RunSynchronousCommand>
              </RunSynchronous>
            </component>
          </settings>
          <settings pass="oobeSystem">
            <component name="Microsoft-Windows-International-Core" processorArchitecture="amd64" publicKeyToken="31bf3856ad364e35" language="neutral" versionScope="nonSxS" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
              <InputLocale>0409:00000409</InputLocale>
              <SystemLocale>en-US</SystemLocale>
              <UserLocale>en-US</UserLocale>
              <UILanguage>en-US</UILanguage>
            </component>
            <component name="Microsoft-Windows-Shell-Setup" processorArchitecture="amd64" publicKeyToken="31bf3856ad364e35" language="neutral" versionScope="nonSxS" xmlns:wcm="http://schemas.microsoft.com/WMIConfig/2002/State" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
              <OOBE>
                <HideEULAPage>true</HideEULAPage>
                <HideLocalAccountScreen>true</HideLocalAccountScreen>
                <HideOEMRegistrationScreen>true</HideOEMRegistrationScreen>
                <HideOnlineAccountScreens>true</HideOnlineAccountScreens>
                <HideWirelessSetupInOOBE>true</HideWirelessSetupInOOBE>
                <ProtectYourPC>3</ProtectYourPC>
                <SkipMachineOOBE>true</SkipMachineOOBE>
                <SkipUserOOBE>true</SkipUserOOBE>
              </OOBE>
              <TimeZone>UTC</TimeZone>
              <UserAccounts>
                <AdministratorPassword>
                  <Value>{password}</Value>
                  <PlainText>true</PlainText>
                </AdministratorPassword>
              </UserAccounts>
              <AutoLogon>
                <Enabled>true</Enabled>
                <Username>Administrator</Username>
                <LogonCount>1</LogonCount>
                <Password>
                  <Value>{password}</Value>
                  <PlainText>true</PlainText>
                </Password>
              </AutoLogon>
              <FirstLogonCommands>
                <SynchronousCommand wcm:action="add" xmlns:wcm="http://schemas.microsoft.com/WMIConfig/2002/State">
                  <Order>1</Order>
                  <Description>Install the Salt minion</Description>
                  <CommandLine>{xml_escape(command)}</CommandLine>
                </SynchronousCommand>
                <SynchronousCommand wcm:action="add" xmlns:wcm="http://schemas.microsoft.com/WMIConfig/2002/State">
                  <Order>2</Order>
                  <Description>Sign the first logon out once the install has finished</Description>
                  <CommandLine>{xml_escape(sign_out_command())}</CommandLine>
                </SynchronousCommand>
              </FirstLogonCommands>
            </component>
          </settings>
        </unattend>
        """)


def generate_certificate(common_name):
    """A self-signed certificate and key for the Salt API, generated for this run with openssl. Returned in memory only:
    the working files stay in a private temporary directory and are gone before this returns."""
    with tempfile.TemporaryDirectory(prefix="guestcfg-") as tmp:
        key, crt = os.path.join(tmp, "api.key"), os.path.join(tmp, "api.crt")
        done = subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-sha256", "-days", "2",
                               "-subj", f"/CN={common_name}", "-keyout", key, "-out", crt],
                              capture_output=True, text=True, check=False)
        if done.returncode != 0:
            raise StepFailed(f"openssl could not generate the API certificate (exit {done.returncode})")
        with open(key, encoding="utf-8") as f:
            tls_key = f.read()
        with open(crt, encoding="utf-8") as f:
            tls_cert = f.read()
    return tls_cert, tls_key


# --------------------------------------------------------------------------- the Salt API

class SaltApi:
    """The Salt API over TLS pinned to the run's certificate: log in, apply, read the job."""

    def __init__(self, base, cert_pem, user, password):
        self.base, self.user, self.password = base.rstrip("/"), user, password
        self.context = pinned_context(cert_pem)
        self.token = None

    def _post(self, path, payload, token=None):
        data = json.dumps(payload).encode()
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if token:
            headers["X-Auth-Token"] = token
        req = urllib.request.Request(self.base + path, data=data, method="POST", headers=headers)
        try:
            with urllib.request.urlopen(req, context=self.context, timeout=120) as r:
                return r.status, json.loads(r.read() or b"null"), r.headers.get("X-Auth-Token")
        except urllib.error.HTTPError as ex:
            return ex.code, {}, None
        except (urllib.error.URLError, OSError, ValueError):
            return None, {}, None

    def login(self):
        st, body, header_token = self._post("/login", {"username": self.user, "password": self.password, "eauth": "file"})
        if st == 200 and isinstance(body, dict):
            ret = body.get("return")
            row = ret[0] if isinstance(ret, list) and ret else ret if isinstance(ret, dict) else {}
            self.token = (row or {}).get("token") or header_token
        return bool(self.token)

    def low(self, payload):
        """One command at the API's root. A 401 is answered by one fresh login; any other failure is the caller's."""
        st, body, _ = self._post("/", [payload], self.token)
        if st == 401 and self.login():
            st, body, _ = self._post("/", [payload], self.token)
        if st != 200 or not isinstance(body, dict):
            raise StepFailed(f"the Salt API answered {st if st else 'nothing'} to {payload.get('client')} {payload.get('fun')}")
        ret = body.get("return")
        return ret[0] if isinstance(ret, list) and ret else ret

    def wheel(self, fun, **kwargs):
        row = self.low({"client": "wheel", "fun": fun, **kwargs}) or {}
        data = (row.get("data") or {}) if isinstance(row, dict) else {}
        if data.get("success") is False:
            raise StepFailed(f"wheel {fun} reported failure: {str(data.get('return'))[:300]}")
        return data.get("return") if "return" in data else row

    def keys(self):
        return self.wheel("key.list_all") or {}

    def finger(self, minion, hash_type=None):
        """The fingerprint of the key the master accepted for one id: wheel key.finger, whose page shows
        {'minions': {'minion1': '5d:f6:...'}}; hash_type names the algorithm, else the master's own default. None when
        the master holds no accepted key for it."""
        ret = self.wheel("key.finger", match=minion, **({"hash_type": hash_type} if hash_type else {})) or {}
        return ((ret.get("minions") or {}) if isinstance(ret, dict) else {}).get(minion)

    def key_pem(self, minion):
        """The public key the master holds for one id, as wheel key.print returns it; None when it holds none."""
        ret = self.wheel("key.print", match=minion) or {}
        pem = ((ret.get("minions") or {}) if isinstance(ret, dict) else {}).get(minion)
        return str(pem) if pem else None

    def key_head(self, minion):
        """The first line of the public key the master holds for one id (wheel key.print), which names its PEM form."""
        pem = self.key_pem(minion)
        return pem.splitlines()[0].strip() if pem else None

    def gen_accept(self, minion):
        """Generate a key pair on the master and accept its public key (wheel key.gen_accept): "only the public key is
        preserved on the master". An empty answer means a key is already accepted for the id, and nothing was made."""
        ret = self.wheel("key.gen_accept", id_=minion) or {}
        return ret if isinstance(ret, dict) else {}

    def answers(self, timeout=ANSWER_TIMEOUT):
        """Whether the API answers from here at all: a read of its root over the pinned TLS, where any HTTP status, a
        401 included, is an answer, and a refused or timed-out connection is not."""
        req = urllib.request.Request(self.base + "/", method="GET", headers={"Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, context=self.context, timeout=timeout):
                return True
        except urllib.error.HTTPError:
            return True
        except (urllib.error.URLError, OSError, ValueError):
            return False

    def local_async(self, tgt, fun, arg=None, kwarg=None, tgt_type="compound"):
        payload = {"client": "local_async", "tgt": tgt, "tgt_type": tgt_type, "fun": fun}
        if arg:
            payload["arg"] = arg
        if kwarg:
            payload["kwarg"] = kwarg
        row = self.low(payload) or {}
        jid = row.get("jid") if isinstance(row, dict) else None
        if not jid:
            raise StepFailed(f"{fun} was not accepted for its target: {str(row)[:200]}")
        return jid

    def lookup(self, jid):
        row = self.low({"client": "runner", "fun": "jobs.lookup_jid", "jid": jid})
        if isinstance(row, dict) and "outputter" in row and "data" in row:   # the jobs runner wraps state returns
            row = row["data"]
        return row if isinstance(row, dict) else {}


def patiently(read, default):
    """One read through the Salt API during a wait: a failed read is one bad moment in a long wait, not the end of it."""
    try:
        return read()
    except StepFailed:
        return default


def state_outcome(run):
    """A state.apply return, as counts: states, changed, failed, the ones test=True would change, and an error string
    when the return is not a state dictionary at all."""
    if not isinstance(run, dict):
        return {"states": 0, "changed": 0, "failed": 1, "wouldChange": 0, "error": str(run)[:300]}
    rows = [v for v in run.values() if isinstance(v, dict)]
    return {"states": len(rows), "changed": sum(1 for s in rows if s.get("changes")),
            "failed": sum(1 for s in rows if s.get("result") is False),
            "wouldChange": sum(1 for s in rows if s.get("result") is None and s.get("changes"))}


def poll(what, read, done, limit, every=POLL, report=REPORT, note=None):
    """Read until done(value), with one progress line per `report` seconds. Past `limit` the run stops and names what
    it was waiting for."""
    start = last = _now()
    while True:
        value = read()
        if done(value):
            return round(_now() - start), value
        elapsed = _now() - start
        if elapsed >= limit:
            raise StepFailed(f"{what}: not done within {limit // 60} minutes" + (f"; {note}" if note else ""))
        if _now() - last >= report:
            last = _now()
            say(f"    still waiting for {what}: {round(elapsed)}s of {limit}s")
        _sleep(every)


# --------------------------------------------------------------------------- output

L = Labels()


def say(text=""):
    print(L.scrub(text))


# --------------------------------------------------------------------------- reading the namespace

def read_images(e, url, ns):
    """Every image the namespace can name: bound to it, or cluster-scoped and not a Kubernetes node image."""
    out = []
    for i in e.items(url, f"/apis/{VMOP}/{VMAPI}/namespaces/{ns}/virtualmachineimages"):
        st_ = i.get("status") or {}
        out.append({"name": str(st_.get("name") or i["metadata"]["name"]), "os": str((st_.get("osInfo") or {}).get("type") or ""), "scope": "bound"})
    path = f"/apis/{VMOP}/{VMAPI}/clustervirtualmachineimages"
    st, _ = e.ns(url, path)
    if st == 200:
        for i in e.items(url, path):
            st_ = i.get("status") or {}
            name = str(st_.get("name") or i["metadata"]["name"])
            if NODE_IMAGE.search(name) or K8S_RELEASE_LABEL in ((i.get("metadata") or {}).get("labels") or {}):
                continue
            out.append({"name": name, "os": str((st_.get("osInfo") or {}).get("type") or ""), "scope": "cluster"})
    return out


def ubuntu_2404(images):
    return [i for i in images if ("ubuntu" in i["os"].lower() or "ubuntu" in i["name"].lower()) and re.search(r"24[._-]?04", i["name"])]


def windows_2022(images):
    return [i for i in images if i["os"] == "windows2019srvNext_64Guest" or
            ("windows" in (i["os"] + i["name"]).lower() and "2022" in i["name"])]


def pick_image(images, env_name, candidates, what):
    wanted = os.environ.get(env_name)
    if wanted:
        if not any(i["name"] == wanted for i in images):
            raise Refusal(f"{env_name} names an image this namespace cannot name")
        return wanted
    if len(candidates) == 1:
        return candidates[0]["name"]
    raise Refusal(f"{what}: {len(candidates)} matching image(s) in this namespace; set {env_name} to one display name")


ACCESS = (("create", "", "secrets"), ("delete", "", "secrets"), ("get", "", "secrets"),
          ("create", VMOP, "virtualmachines"), ("delete", VMOP, "virtualmachines"), ("get", VMOP, "virtualmachines"),
          ("create", VMOP, "virtualmachineservices"), ("delete", VMOP, "virtualmachineservices"))
# The automation path creates nothing at the namespace endpoint: its deployments do. The run reads what they made.
ACCESS_READ = (("get", "", "secrets"), ("get", VMOP, "virtualmachines"), ("get", VMOP, "virtualmachineservices"))
ACCESS_PATCH = (("patch", VMOP, "virtualmachineservices"),)


def access_reviews(e, url, ns, access=ACCESS):
    """What the sign-in may do in the namespace, by the namespace's own answer. A missing right stops the run here."""
    out = []
    for verb, group, resource in access:
        review = {"apiVersion": "authorization.k8s.io/v1", "kind": "SelfSubjectAccessReview",
                  "spec": {"resourceAttributes": {"namespace": ns, "verb": verb, "group": group, "resource": resource}}}
        st, body = e.ns(url, "/apis/authorization.k8s.io/v1/selfsubjectaccessreviews", "POST", review)
        allowed = (body.get("status") or {}).get("allowed") if st in (200, 201) else None
        out.append({"verb": verb, "apiGroup": group or "core", "resource": resource, "allowed": allowed})
    return out


def resolve_namespace(e):
    """The one namespace this script may touch, named by GUESTCFG_NAMESPACE and found among the sign-in's namespaces. A
    missing or non-matching name is a refusal, before anything is read further or written."""
    want = os.environ.get("GUESTCFG_NAMESPACE")
    if not want:
        raise Refusal("GUESTCFG_NAMESPACE is not set; it names the one namespace this script may build in")
    if not NAMESPACE.match(want):
        raise Refusal("GUESTCFG_NAMESPACE is not a Kubernetes namespace name")
    projects = [p["metadata"]["name"] for p in e.items(gateway(e), f"/apis/{PROJ}/projects")]
    if not projects:
        raise Refusal("no project is visible to this identity")
    wanted_project = os.environ.get("GUESTCFG_PROJECT")
    if wanted_project and wanted_project not in projects:
        raise Refusal("GUESTCFG_PROJECT is not a project this sign-in can see")
    match = None
    for project in ([wanted_project] if wanted_project else projects):
        for _p, name, url in _endpoints(e, project):
            if name == want:
                match = (project, url)
    if not match:
        raise Refusal("GUESTCFG_NAMESPACE does not match a namespace with an endpoint that this sign-in can see")
    project, url = match
    L.get("project", project)
    L.get("namespace", want)
    return project, want, url


def via_path():
    via = (os.environ.get("GUESTCFG_VIA") or "supervisor").strip().lower()
    if via not in VIA_PATHS:
        raise Refusal("GUESTCFG_VIA must be supervisor or automation")
    return via


def run_settings(bootstrap):
    """The settings that shape a run beyond its namespace, each checked before anything is read further. The ranges and
    the runner's address are estate values, so each is registered for the scrub; the two documentation values are not."""
    via = via_path()
    keys = (os.environ.get("GUESTCFG_KEYS") or "accept").strip().lower()
    if keys not in KEY_MODES:
        raise Refusal("GUESTCFG_KEYS must be accept or preseed")
    raw = os.environ.get("GUESTCFG_API_SOURCE_RANGES")
    ranges = [r.strip() for r in raw.split(",") if r.strip()] if raw and raw.strip() else None
    if ranges is not None and not all(CIDR.match(r) for r in ranges):
        raise Refusal("GUESTCFG_API_SOURCE_RANGES must be comma-separated IPv4 CIDRs, such as 203.0.113.0/24")
    prove = (os.environ.get("GUESTCFG_PROVE_SOURCE_RANGES") or "").strip().lower() in ("1", "true", "yes")
    runner = (os.environ.get("GUESTCFG_RUNNER_ADDRESS") or "").strip() or None
    if runner and not ADDRESS.match(runner):
        raise Refusal("GUESTCFG_RUNNER_ADDRESS must be one IPv4 address, this runner's as the load balancer sees it")
    # The runner's address and any range the operator names are the operator's own network: placeholders from here
    # on, in stdout and in the record, which otherwise refuses to be written with them in it.
    for value in [runner] + [r for r in (ranges or []) if r not in (ANY_SOURCE, TEST_NET_1)]:
        if value:
            L.get("address", value)
    try:
        operator = operator_key_from_env()
    except ValueError as e:
        raise Refusal(str(e)) from None
    if operator:
        L.hold(operator)  # not a secret, but it names the reader: never in stdout or the record
    if via == "automation":
        if operator:
            raise Refusal("GUESTCFG_OPERATOR_SSH_KEY runs on the supervisor path: the blueprints take no operator login")
        if not os.environ.get("GUESTCFG_PROJECT"):
            raise Refusal("GUESTCFG_VIA=automation needs GUESTCFG_PROJECT: the project the blueprints and deployments are made in")
        if bootstrap != "sysprep":
            raise Refusal("the automation path has a Windows blueprint for Sysprep only; unset GUESTCFG_WINDOWS_BOOTSTRAP")
        if keys == "preseed":
            raise Refusal("GUESTCFG_KEYS=preseed runs on the supervisor path: the master blueprint grants its API account "
                          "no key.gen_accept")
        if prove:
            raise Refusal("GUESTCFG_PROVE_SOURCE_RANGES runs on the supervisor path: on the automation path the load "
                          "balancer belongs to a deployment, and the run does not patch a deployment's objects")
    for r in ranges or []:
        if r not in (ANY_SOURCE, TEST_NET_1):
            L.get("cidr", r)
    if runner:
        L.get("cidr", f"{runner}/32")
        L.get("address", runner)
    for name in BLUEPRINT_FILES.values():
        if via == "automation" and not os.path.isfile(os.path.join(TEMPLATES, name)):
            raise Refusal(f"the blueprint file {name} is not beside this script in templates/02x-vm-salt-minion/")
    return {"via": via, "keys": keys, "sourceRanges": ranges, "proveSourceRanges": prove, "runnerAddress": runner,
            "operatorKey": operator}


def classic_project(e, name):
    """A project's id on VCF Automation's classic project list, where blueprints and deployments name it. The list
    refuses a sort, so it is read as one page, as building-blueprints/shapes.py does."""
    st, body = e.api("/project-service/api/projects?size=200&page=0")
    if st != 200 or not isinstance(body, dict):
        raise Refusal(f"the classic project list answered {st if st else 'nothing'}")
    if (body.get("totalPages") or 1) > 1:
        raise Refusal("the classic project list spans pages and refuses a sort, so a paged read could overlap")
    pid = next((p.get("id") for p in body.get("content") or [] if p.get("name") == name), None)
    if not pid:
        raise Refusal("GUESTCFG_PROJECT is not on the classic project list this sign-in reads")
    return pid


def preflight(e):
    """Step 1: the named namespace, its images, classes, storage and rights. A refusal here means nothing was created."""
    # Sysprep is the default: Windows carries it as shipped, and on the reference estate's stock Windows Server 2022 image
    # the cloud-init path left the guest with no address (proof run, 2026-11-10). cloudinit is for images built with
    # Cloudbase-Init.
    bootstrap = (os.environ.get("GUESTCFG_WINDOWS_BOOTSTRAP") or "sysprep").strip().lower()
    if bootstrap not in BOOTSTRAP_PATHS:
        raise Refusal("GUESTCFG_WINDOWS_BOOTSTRAP must be cloudinit or sysprep")
    settings = run_settings(bootstrap)
    project, want, url = resolve_namespace(e)
    project_id = classic_project(e, project) if settings["via"] == "automation" else None
    images = read_images(e, url, want)
    for i in images:
        L.get("image", i["name"])
    classes = sorted(c["metadata"]["name"] for c in e.items(url, f"/apis/{VMOP}/{VMAPI}/namespaces/{want}/virtualmachineclasses"))
    try:
        quotas = e.items(gateway(e), f"/apis/{INFRA1}/regionstorageclassquotas")
    except Refusal:
        quotas = []
    storages = sorted({(s.get("spec") or {}).get("storageClassName") for s in quotas} - {None})
    for s in storages:
        L.get("storageclass", s)
    linux_image = pick_image(images, "GUESTCFG_LINUX_IMAGE", ubuntu_2404(images), "Ubuntu 24.04")
    windows_image = pick_image(images, "GUESTCFG_WINDOWS_IMAGE", windows_2022(images), "Windows Server 2022")
    vm_class = os.environ.get("GUESTCFG_VM_CLASS", "best-effort-small")
    windows_class = os.environ.get("GUESTCFG_WINDOWS_VM_CLASS", "best-effort-medium")
    for c in (vm_class, windows_class):
        if c not in classes:
            raise Refusal(f"the namespace does not publish the VM class {c}; set GUESTCFG_VM_CLASS or GUESTCFG_WINDOWS_VM_CLASS")
    storage = os.environ.get("GUESTCFG_STORAGE_CLASS") or (storages[0] if len(storages) == 1 else None)
    if not storage:
        raise Refusal(f"{len(storages)} storage class(es) visible; set GUESTCFG_STORAGE_CLASS (kubectl get regionstorageclassquotas)")
    L.get("storageclass", storage)
    limit, used, stated = quota(e, url, want)
    try:
        min_free = int(os.environ.get("GUESTCFG_MIN_FREE_GIB", "160"))
    except ValueError:
        raise Refusal("GUESTCFG_MIN_FREE_GIB is not a whole number") from None
    free = round((limit - used) / SUFFIX["Gi"], 1) if stated else None
    if min_free and (not stated or free < min_free):
        raise Refusal(f"the namespace states no storage limit or under {min_free} GiB free; "
                      "the run needs three boot disks (GUESTCFG_MIN_FREE_GIB=0 skips this check where no limit is stated)")
    access = (ACCESS if settings["via"] == "supervisor" else ACCESS_READ) + (ACCESS_PATCH if settings["proveSourceRanges"] else ())
    reviews = access_reviews(e, url, want, access)
    denied = [f"{r['verb']} {r['resource']}" for r in reviews if r["allowed"] is not True]
    if denied:
        raise Refusal(f"this sign-in may not {', '.join(denied)} in the namespace; "
                      + ("the run creates, removes and patches these objects directly at the namespace endpoint"
                         if settings["via"] == "supervisor" else "the run reads what its deployments make there"))
    if not shutil.which("openssl"):
        raise Refusal("openssl is not on the PATH; it generates the API's certificate")
    return {"project": project, "namespace": want, "url": url, "images": images, "classes": classes, "storages": storages,
            "linuxImage": linux_image, "windowsImage": windows_image, "vmClass": vm_class, "windowsClass": windows_class,
            "storage": storage, "quotaStated": stated, "freeGiB": free, "minFreeGiB": min_free, "reviews": reviews,
            "windowsBootstrap": bootstrap, "projectId": project_id, **settings}


def print_read(plan, reveal=False):
    """What the namespace offers and what a run would use. Only the read subcommand shows display names (reveal), so
    the operator can set GUESTCFG_LINUX_IMAGE from them; a run's output and record carry placeholders."""
    show = print if reveal else say
    say(f"namespace {plan['namespace']} in project {plan['project']}")
    say(f"  images the namespace can name: {len(plan['images'])}")
    for i in plan["images"]:
        show(f"    {i['name']}  ({i['scope']}, {i['os'] or 'no guest id stated'})")
    say(f"  classes: {', '.join(plan['classes'])}")
    show(f"  storage classes visible: {', '.join(plan['storages'])}")
    say(f"  storage quota free: {plan['freeGiB'] if plan['quotaStated'] else 'no limit stated'}"
        + (f" GiB; a run needs {plan['minFreeGiB']} GiB" if plan["quotaStated"] else ""))
    say("  rights in the namespace:")
    for r in plan["reviews"]:
        say(f"    {r['verb']:7s} {r['apiGroup']:24s} {r['resource']:24s} {r['allowed']}")
    say("  what a run would use:")
    show(f"    Ubuntu 24.04 image    {plan['linuxImage']}")
    show(f"    Windows 2022 image    {plan['windowsImage']}")
    say(f"    classes               {plan['vmClass']} (master, Linux minion), {plan['windowsClass']} (Windows minion)")
    show(f"    storage class         {plan['storage']}")
    say(f"    built                 {VIA_PATHS[plan['via']]} (GUESTCFG_VIA={plan['via']})")
    say(f"    minion keys           {KEY_MODES[plan['keys']]} (GUESTCFG_KEYS={plan['keys']})")
    say(f"    API source ranges     {', '.join(plan['sourceRanges']) if plan['sourceRanges'] is not None else 'not set'}"
        + ("; the run proves whether the load balancer enforces them" if plan["proveSourceRanges"] else ""))
    say(f"    Windows bootstrap     {BOOTSTRAP_PATHS[plan['windowsBootstrap']]}")


# --------------------------------------------------------------------------- the run

class Run:
    """One run: its id, the objects it makes in one namespace, and the record of what happened."""

    KINDS = {"secrets": "/api/v1/namespaces/{ns}/secrets",
             "virtualmachines": "/apis/" + VMOP + "/" + VMAPI + "/namespaces/{ns}/virtualmachines",
             "virtualmachineservices": "/apis/" + VMOP + "/" + VMAPI + "/namespaces/{ns}/virtualmachineservices"}

    def __init__(self, e, plan, run_id=None):
        self.e, self.plan = e, plan
        self.ns, self.url = plan["namespace"], plan["url"]
        self.run_id = run_id or secretlib.token_hex(3)
        self.n = names(self.run_id)
        self.created = []
        self.salt = None
        self.api_password = None
        self.cert = None
        self.master_ip = None
        self.lb_address = None
        self.windows_password = None
        self.steps = {}
        self.record_failure = None
        self.blueprints = {}        # the automation path: role -> {"id", "name"}
        self.deployments = {}       # the automation path: role -> {"id", "name", "requestId"}
        self.seeds = {}             # preseed: minion id -> its key pair as base64, in memory only
        self.generated = {}         # preseed: minion id -> the fingerprint the master read right after generating it

    def path(self, kind, name=None):
        base = self.KINDS[kind].format(ns=self.ns)
        return base if name is None else f"{base}/{urllib.parse.quote(name, safe='')}"

    def create(self, kind, body):
        """Create one object in the named namespace, under this run's label. A refused create is a step failure."""
        labels = (body.get("metadata") or {}).get("labels") or {}
        if labels.get(RUN_LABEL) != self.run_id:
            raise StepFailed(f"{body['kind']} {body['metadata']['name']} is missing this run's label; refusing to create it")
        st, r = self.e.ns(self.url, self.path(kind), "POST", body)
        if st not in (200, 201):
            raise StepFailed(f"create {body['kind']} {body['metadata']['name']} answered {st if st else 'nothing'}: {msg(r)[:240]}")
        self.created.append({"kind": body["kind"], "name": body["metadata"]["name"]})

    def read_vm(self, name):
        st, v = self.e.ns(self.url, self.path("virtualmachines", name))
        return v if st == 200 and isinstance(v, dict) else None

    def wait_ready(self, name, limit, note=None):
        """A machine PoweredOn with an IPv4 address; returns (seconds, address)."""
        def done(v):
            st_ = (v or {}).get("status") or {}
            return st_.get("powerState") == "PoweredOn" and (st_.get("network") or {}).get("primaryIP4")
        secs, v = poll(f"machine {name} PoweredOn with an address", lambda: self.read_vm(name), done, limit, report=120, note=note)
        return secs, ((v.get("status") or {}).get("network") or {}).get("primaryIP4")

    def vm_conditions(self, name):
        v = self.read_vm(name) or {}
        return {c.get("type"): c.get("status") for c in ((v.get("status") or {}).get("conditions") or [])}

    # ---- step 2: the master, then its API reachable from outside

    def run_secrets(self):
        """The API account's password, its digest line and the API's certificate and key, generated for this run and held
        so that none reaches stdout or the record."""
        self.api_password = secretlib.token_urlsafe(32)
        L.hold(self.api_password)
        tls_cert, tls_key = generate_certificate(self.n["master"])
        L.hold(tls_key)
        L.hold(tls_key.replace("\n", ""))
        L.hold(b64(tls_key))
        self.cert = tls_cert
        digest = hashlib.sha256(self.api_password.encode()).hexdigest()
        L.hold(digest)
        api_digest_line = f"{API_USER}:{digest}"
        L.hold(b64(api_digest_line + "\n"))
        return api_digest_line, tls_cert, tls_key

    def step_master(self):
        if self.plan["via"] == "automation":
            return self.step_master_automation()
        say("step 2: the master")
        n = self.n
        plan = self.plan
        api_digest_line, tls_cert, tls_key = self.run_secrets()
        user_data = render_master_user_data(n["master"], n["linux"], n["windows"], api_digest_line, tls_cert, tls_key, _load_states(),
                                            gen_accept=plan["keys"] == "preseed", operator_key=plan.get("operatorKey"))
        L.hold(user_data)
        self.create("secrets", secret_manifest(n["api_secret"], {"username": API_USER, "password": self.api_password, "tls.crt": tls_cert},
                                               "salt-api", self.run_id))
        self.create("secrets", secret_manifest(n["master_secret"], {"user-data": user_data}, "salt-master", self.run_id))
        self.create("virtualmachines", vm_manifest(n["master"], "salt-master", plan["linuxImage"], plan["vmClass"], plan["storage"],
                                                   cloud_init_bootstrap(n["master_secret"]), self.run_id))
        secs, ip = self.wait_ready(n["master"], LIMITS["vm_ready"])
        self.master_ip = ip
        L.get("address", ip)
        say(f"  master PoweredOn with an address after {secs}s")
        self.create("virtualmachineservices", lb_manifest(n["lb"], n["master"], self.run_id, plan["sourceRanges"]))
        self.steps["2"] = {"name": "master", "via": "supervisor", "secondsToPoweredOn": secs, **self.reach_api()}

    def reach_api(self):
        """The API's load balancer address, a login over TLS pinned to the run's certificate, and the source ranges the
        load balancer carries, read back."""
        n = self.n

        def lb_addr(s):
            ing = (((s or {}).get("status") or {}).get("loadBalancer") or {}).get("ingress") or []
            return ing[0].get("ip") or ing[0].get("hostname") if ing else None
        secs_lb, svc = poll("the Salt API load balancer's address",
                            lambda: self.e.ns(self.url, self.path("virtualmachineservices", n["lb"]))[1], lb_addr, LIMITS["lb_address"])
        self.lb_address = lb_addr(svc)
        L.get("address", self.lb_address)
        say(f"  load balancer for port {API_PORT} has an address after {secs_lb}s")
        self.salt = SaltApi(f"https://{self.lb_address}:{API_PORT}", self.cert, API_USER, self.api_password)
        secs_api, _ = poll("the Salt API to answer a TLS login", self.salt.login, lambda ok: ok, LIMITS["api_login"], report=120,
                           note="the master's first boot installs Salt from packages.broadcom.com; a guest that cannot reach it never answers")
        L.hold(self.salt.token)
        say(f"  Salt API answered over TLS pinned to the run's certificate after {secs_api}s")
        requested = self.requested_ranges()
        carried = self.read_ranges()
        if requested is not None:
            say(f"  the load balancer carries loadBalancerSourceRanges {', '.join(carried or []) or 'none'}"
                + ("" if carried == requested else f", not the {', '.join(requested)} requested"))
        return {"secondsToLoadBalancerAddress": secs_lb, "secondsToApiLogin": secs_api, "apiTlsPinnedToRunCertificate": True,
                "sourceRanges": {"requested": requested, "readBack": carried,
                                 "carried": None if requested is None else carried == requested}}

    def requested_ranges(self):
        """The ranges the run asks for: the setting, or on the automation path, where the blueprint requires the input,
        0.0.0.0/0 when it is unset."""
        ranges = self.plan["sourceRanges"]
        return [ANY_SOURCE] if ranges is None and self.plan["via"] == "automation" else ranges

    def read_ranges(self):
        st, svc = self.e.ns(self.url, self.path("virtualmachineservices", self.n["lb"]))
        return list(((svc or {}).get("spec") or {}).get("loadBalancerSourceRanges") or []) if st == 200 else None

    # ---- step 2, on the automation path: the three blueprints, then the master's deployment

    def step_master_automation(self):
        say("step 2: the master, through VCF Automation")
        n = self.n
        plan = self.plan
        api_digest_line, tls_cert, tls_key = self.run_secrets()
        made = self.make_blueprints()
        inputs = {"app_name": n["prefix"], "target_namespace_name": self.ns, "vm_image": plan["linuxImage"],
                  "storage_class": plan["storage"], "vm_class": plan["vmClass"], "run_label": self.run_id,
                  "linux_minion_id": n["linux"], "windows_minion_id": n["windows"],
                  "api_digest_b64": b64(api_digest_line + "\n"), "api_tls_cert_b64": b64(tls_cert),
                  "api_tls_key_b64": b64(tls_key), "api_source_ranges": self.requested_ranges()}
        self.request_deployment("master", inputs)
        secs_dep = self.wait_deployment("master")
        say(f"  deployment {n['master']} CREATE_SUCCESSFUL after {secs_dep}s")
        secs, ip = self.wait_ready(n["master"], LIMITS["vm_ready"])
        self.master_ip = ip
        L.get("address", ip)
        say(f"  master PoweredOn with an address after {secs}s more, read from the namespace")
        self.steps["2"] = {"name": "master", "via": "automation", "blueprints": made, "secondsToMasterDeployment": secs_dep,
                           "secondsToPoweredOn": secs, **self.reach_api()}

    def make_blueprints(self):
        """Create the three blueprints in the project from the files beside this script, exactly as written and named for
        the run, then validate each. Any validation error stops the run before anything is deployed."""
        pid = self.plan["projectId"]
        contents = {}
        for role, fname in BLUEPRINT_FILES.items():
            with open(os.path.join(TEMPLATES, fname), encoding="utf-8") as f:
                contents[role] = f.read()
            name = blueprint_name(self.n, role)
            st, b = self.e.api("/blueprint/api/blueprints", "POST",
                               {"name": name, "projectId": pid, "content": contents[role],
                                "description": f"guest-configuration run {self.run_id}: {fname}, deleted by the run's teardown"})
            if st not in (200, 201) or not isinstance(b, dict) or not b.get("id"):
                raise StepFailed(f"create blueprint {name} answered {st if st else 'nothing'}: {msg(b)[:240]}")
            self.blueprints[role] = {"id": b["id"], "name": name}
            self.created.append({"kind": "Blueprint", "name": name})
        say(f"  {len(contents)} blueprints created in the project from the files as written")
        made = {}
        for role, content in contents.items():
            name = self.blueprints[role]["name"]
            st, v = self.e.api("/blueprint/api/blueprint-validation", "POST", {"content": content, "projectId": pid})
            if st != 200 or not isinstance(v, dict):
                raise StepFailed(f"the validation of blueprint {name} answered {st if st else 'nothing'}")
            notes = v.get("validationMessages") or []
            errors = [m for m in notes if (m or {}).get("type") == "ERROR"]
            if errors or v.get("valid") is not True:
                first = " ".join(str((errors or notes or [{}])[0].get("message") or "no message").split())[:240]
                raise StepFailed(f"blueprint {name} did not validate ({len(errors)} error(s)): {first}")
            made[role] = {"valid": True, "warnings": sum(1 for m in notes if (m or {}).get("type") == "WARNING")}
        say(f"  each validated with no error: {', '.join(BLUEPRINT_FILES.values())}")
        return made

    def request_deployment(self, role, inputs):
        """Request one deployment of a blueprint, named for its machine. The request body carries the run's secrets as
        inputs and is never printed."""
        name = self.n[role]
        bp = self.blueprints[role]
        st, r = self.e.api("/blueprint/api/blueprint-requests", "POST",
                           {"blueprintId": bp["id"], "projectId": self.plan["projectId"], "deploymentName": name,
                            "inputs": inputs, "reason": f"guest-configuration run {self.run_id}"})
        if st not in (200, 201, 202) or not isinstance(r, dict) or not r.get("deploymentId"):
            raise StepFailed(f"the deployment request for {name} answered {st if st else 'nothing'}: {msg(r)[:240]}")
        self.deployments[role] = {"id": r["deploymentId"], "name": name, "requestId": r.get("id")}
        self.created.append({"kind": "Deployment", "name": name})

    def wait_deployment(self, role):
        """Wait for CREATE_SUCCESSFUL; CREATE_FAILED stops the run with the deployment's own message."""
        dep = self.deployments[role]

        def read():
            st, d = self.e.api(f"/deployment/api/deployments/{dep['id']}")
            return d if st == 200 and isinstance(d, dict) else {}
        secs, d = poll(f"deployment {dep['name']} to finish creating", read, lambda d: d.get("status") in ACTIVE_DEPLOYMENT,
                       LIMITS["deployment"], report=120)
        if d.get("status") == "CREATE_FAILED":
            raise StepFailed(f"deployment {dep['name']} is CREATE_FAILED: {self.deployment_failure(dep, d)}")
        return secs

    def deployment_failure(self, dep, d):
        """The failure as VCF Automation states it: the deployment's last request's details, else the blueprint
        request's failureMessage."""
        text = ((d.get("lastRequest") or {}).get("details") or "") if isinstance(d.get("lastRequest"), dict) else ""
        if not text and dep.get("requestId"):
            st, r = self.e.api(f"/blueprint/api/blueprint-requests/{dep['requestId']}")
            text = (r or {}).get("failureMessage") or "" if st == 200 and isinstance(r, dict) else ""
        return " ".join(str(text or "no message stated").split())[:400]

    # ---- after the API answers, on the supervisor path: is loadBalancerSourceRanges enforced?

    def step_source_ranges(self):
        """Patch the load balancer's ranges to TEST-NET-1, to any source, and to the runner's own /32 when it is known,
        read after each whether the API answers from here, then restore the original ranges. What it finds is recorded,
        never a failure; a refused patch is."""
        say("source ranges: whether this estate's load balancer enforces loadBalancerSourceRanges")
        runner = self.plan["runnerAddress"]
        settings = [("TEST-NET-1", [TEST_NET_1]), ("any source", [ANY_SOURCE])]
        if runner:
            settings.append(("the runner's own address", [f"{runner}/32"]))
        original = self.plan["sourceRanges"]
        reads = []
        for label, ranges in settings:
            self.patch_ranges(ranges)
            seen = self.read_answers(LIMITS["range_read"])
            outcome = "answered" if seen[-1] else "did not answer"
            reads.append({"setting": label, "ranges": ranges, "outcome": outcome, "waitSeconds": LIMITS["range_read"],
                          "readsAnswered": sum(seen), "reads": len(seen)})
            say(f"  {label} ({', '.join(ranges)}): {outcome} at the end of a {LIMITS['range_read']}s read "
                f"({sum(seen)} of {len(seen)} reads answered)")
        self.patch_ranges(original)
        secs, _ = poll("the Salt API to answer again with the original ranges", self.salt.login, lambda ok: ok,
                       LIMITS["api_login"], report=120)
        say(f"  original ranges restored; the API answered again after {secs}s")
        self.steps["sourceRanges"] = {"name": "source ranges", "reads": reads, "restored": original,
                                      "secondsToAnswerAfterRestore": secs, "runnerAddressKnown": bool(runner)}

    def patch_ranges(self, ranges):
        """A JSON merge patch of the load balancer's spec.loadBalancerSourceRanges; None removes the field."""
        st, r = self.e.ns(self.url, self.path("virtualmachineservices", self.n["lb"]), "PATCH",
                          {"spec": {"loadBalancerSourceRanges": ranges}}, content_type="application/merge-patch+json")
        if st not in (200, 201):
            raise StepFailed(f"the patch of the load balancer's source ranges to {ranges} answered "
                             f"{st if st else 'nothing'}: {msg(r)[:240]}")

    def read_answers(self, window):
        """Read whether the API answers, once per POLL seconds for `window` seconds; the last read is the outcome."""
        start = _now()
        seen = []
        while True:
            seen.append(self.salt.answers())
            if _now() - start >= window:
                return seen
            _sleep(POLL)

    # ---- after the API answers and before any minion exists: a key pair generated on the master (preseed)

    def step_preseed(self):
        """Generate the Linux minion's key pair on the master with key.gen_accept, which accepts its public key at once,
        and read the fingerprint the master holds for it. The pair goes to the minion's bootstrap Secret; the private key
        is never printed or recorded. The Windows minion is not seeded, the companion's choice: one first-logon
        CommandLine holds at most 1024 characters, a PEM private key is longer, and splitting it across commands was
        not built or run, so it keeps acceptance by exact id."""
        say("keys generated on the master, before any minion exists (key.gen_accept)")
        minion = self.n["linux"]
        pair = self.salt.gen_accept(minion)
        priv, pub = pair.get("priv"), pair.get("pub")
        if not priv or not pub:
            raise StepFailed(f"key.gen_accept returned no key pair for {minion}: the master already holds an accepted key for it")
        L.hold(priv)
        L.hold(priv.strip())
        for line in priv.splitlines()[1:-1]:
            L.hold(line)
        self.seeds[minion] = {"pem_b64": b64(priv), "pub_b64": b64(pub)}
        L.hold(self.seeds[minion]["pem_b64"])
        finger = self.salt.finger(minion)
        if not finger:
            raise StepFailed(f"the master holds no accepted key for {minion} right after key.gen_accept")
        self.generated[minion] = finger
        say("  the Linux minion's pair generated and its public key accepted; the Windows minion keeps acceptance by exact id")
        self.steps["keysGenerated"] = {"name": "keys generated on the master", "seeded": ["Linux"], "notSeeded": ["Windows"],
                                       "windowsNotSeededBecause": "the companion's choice: one first-logon CommandLine holds "
                                                                  "at most 1024 characters, a PEM private key is longer, and "
                                                                  "splitting it across commands was not built or run",
                                       "fingerprintReadAtGeneration": True}

    # ---- step 3: the minions, built after the master so their configuration can name it

    def step_minions(self):
        if self.plan["via"] == "automation":
            return self.step_minions_automation()
        say("step 3: the minions")
        n = self.n
        plan = self.plan
        seed = self.seeds.get(n["linux"])
        operator = self.plan.get("operatorKey")
        linux_data = render_linux_user_data(n["linux"], self.master_ip, seed["pem_b64"], seed["pub_b64"], operator_key=operator) \
            if seed else render_linux_user_data(n["linux"], self.master_ip, operator_key=operator)
        if seed:
            L.hold(linux_data)
        self.create("secrets", secret_manifest(n["linux_secret"], {"user-data": linux_data}, "salt-minion", self.run_id))
        self.create("virtualmachines", vm_manifest(n["linux"], "salt-minion", plan["linuxImage"], plan["vmClass"], plan["storage"],
                                                   cloud_init_bootstrap(n["linux_secret"]), self.run_id))
        path = plan["windowsBootstrap"]
        say(f"  Windows path: {BOOTSTRAP_PATHS[path]}")
        if path == "cloudinit":
            data, bootstrap = {"user-data": render_windows_user_data(n["windows"], self.master_ip)}, cloud_init_bootstrap(n["windows_secret"])
        else:
            self.windows_password = secretlib.token_urlsafe(24) + "Aa1!"
            L.hold(self.windows_password)
            data, bootstrap = ({"unattend": render_windows_unattend(n["windows"], self.master_ip, self.windows_password)},
                               sysprep_bootstrap(n["windows_secret"]))
        self.create("secrets", secret_manifest(n["windows_secret"], data, "salt-minion", self.run_id))
        self.create("virtualmachines", vm_manifest(n["windows"], "salt-minion", plan["windowsImage"], plan["windowsClass"], plan["storage"],
                                                   bootstrap, self.run_id))
        self.wait_minions(path, via="supervisor")

    def wait_minions(self, path, via, **extra):
        n = self.n
        secs_l, _ = self.wait_ready(n["linux"], LIMITS["vm_ready"])
        say(f"  Linux minion PoweredOn with an address after {secs_l}s")
        secs_w, _ = self.wait_ready(n["windows"], LIMITS["vm_ready"] * 2, note=f"Windows path tried: {BOOTSTRAP_PATHS[path]}")
        say(f"  Windows minion PoweredOn with an address after {secs_w}s")
        self.steps["3"] = {"name": "minions", "via": via, "windowsBootstrap": path, "linuxSecondsToPoweredOn": secs_l,
                           "windowsSecondsToPoweredOn": secs_w, **extra}

    def step_minions_automation(self):
        """The two minion deployments, each given the master's address as an input, requested together."""
        say("step 3: the minions, through VCF Automation")
        n = self.n
        plan = self.plan
        say(f"  Windows path: {BOOTSTRAP_PATHS['sysprep']}")
        self.windows_password = secretlib.token_urlsafe(24) + "Aa1!"
        L.hold(self.windows_password)
        common = {"target_namespace_name": self.ns, "storage_class": plan["storage"], "run_label": self.run_id,
                  "salt_master_address": self.master_ip}
        self.request_deployment("linux", {**common, "app_name": n["prefix"], "vm_image": plan["linuxImage"],
                                          "vm_class": plan["vmClass"], "minion_pem_b64": "", "minion_pub_b64": ""})
        self.request_deployment("windows", {**common, "app_name": n["windows_app"], "vm_image": plan["windowsImage"],
                                            "vm_class": plan["windowsClass"], "admin_password": self.windows_password})
        secs = {role: self.wait_deployment(role) for role in ("linux", "windows")}
        say(f"  deployments {n['linux']} and {n['windows']} CREATE_SUCCESSFUL after {secs['linux']}s and {secs['windows']}s more")
        self.wait_minions("sysprep", via="automation", secondsToMinionDeployments=secs)

    def missing_key(self, minion, elapsed):
        conditions = self.vm_conditions(minion)
        if minion == self.n["windows"]:
            path = BOOTSTRAP_PATHS[self.plan["windowsBootstrap"]]
            other = "sysprep" if self.plan["windowsBootstrap"] == "cloudinit" else "cloudinit"
            detail = (f"Windows path tried: {path}. Either the image does not carry what this path needs or the guest "
                      f"could not reach the master or the package location. VM conditions {conditions}. "
                      f"GUESTCFG_WINDOWS_BOOTSTRAP={other} selects the other path")
        else:
            detail = f"Linux minion, cloud-init. VM conditions {conditions}"
        return f"no key from minion {minion} reached the master within {elapsed // 60} minutes. {detail}"

    # ---- step 4: trust, by exact expected id

    def seeded_never_pending(self, keys=None):
        """A seeded minion's key is accepted from its generation. Seen pending, or denied or rejected (the master's answer
        to a different key under an accepted id), it is not the key the master generated, and the run stops."""
        seeded = set(self.seeds)
        if not seeded:
            return
        keys = keys if keys is not None else patiently(self.salt.keys, {})
        for bucket in ("minions_pre", "minions_denied", "minions_rejected"):
            hit = seeded & set(keys.get(bucket) or [])
            if hit:
                raise StepFailed(f"the seeded minion {sorted(hit)} appeared in {bucket}: it presented a key other than "
                                 "the one generated for it on the master")

    def expected_not_denied(self, keys=None, where="the key step"):
        """An id accepted by name trusts whichever machine presented the first key under it. A second key under that id
        lands in minions_denied (salt-key's page: "This occurs when a minion has a duplicate ID"), and an administrator's
        rejection in minions_rejected; either means another machine claims an expected id, so the run stops. A seeded id
        is held by seeded_never_pending instead."""
        expected = [i for i in (self.n["linux"], self.n["windows"]) if i not in self.seeds]
        keys = keys if keys is not None else patiently(self.salt.keys, {})
        for bucket in ("minions_denied", "minions_rejected"):
            hit = sorted(set(expected) & set(keys.get(bucket) or []))
            if hit:
                raise StepFailed(f"at {where}, the expected id {hit} is also in {bucket}: a second key claims an id "
                                 "accepted by name, so the accepted key may not be its machine's")

    def step_keys(self):
        seeded = [i for i in (self.n["linux"], self.n["windows"]) if i in self.seeds]
        say("step 4: key acceptance, by exact expected id" + (f"; {len(seeded)} key generated on the master" if seeded else ""))
        expected = [self.n["linux"], self.n["windows"]]
        assert all(EXPECTED_ID.match(i) for i in expected), "the expected ids are the run's own names"
        deadlines = {self.n["linux"]: LIMITS["linux_key"], self.n["windows"]: LIMITS["windows_key"]}
        start = last = _now()
        while True:
            keys = patiently(self.salt.keys, {})
            self.seeded_never_pending(keys)
            self.expected_not_denied(keys)
            pending, accepted = set(keys.get("minions_pre") or []), set(keys.get("minions") or [])
            seen = pending | accepted
            missing = [i for i in expected if i not in seen]
            if not missing:
                break
            elapsed = round(_now() - start)
            for i in missing:
                if elapsed >= deadlines[i]:
                    raise StepFailed(self.missing_key(i, deadlines[i]))
            if _now() - last >= REPORT * 2:
                last = _now()
                say(f"    waiting for minion keys: {len(expected) - len(missing)} of {len(expected)} arrived after {elapsed}s "
                    f"(limits {deadlines[self.n['linux']]}s Linux, {deadlines[self.n['windows']]}s Windows, path {BOOTSTRAP_PATHS[self.plan['windowsBootstrap']]})")
            _sleep(POLL)
        arrived_after = round(_now() - start)
        others = sorted(pending - set(expected))
        for minion in expected:
            if minion in pending:
                self.salt.wheel("key.accept", match=minion)
        keys = self.salt.keys()
        self.expected_not_denied(keys)
        accepted, pending_after = set(keys.get("minions") or []), set(keys.get("minions_pre") or [])
        if accepted != set(expected):
            raise StepFailed(f"the accepted set is {len(accepted)} key(s), not exactly the two expected ids")
        unaccepted = sorted(pending_after - set(expected))
        if others or unaccepted:
            say(f"  {len(others)} other pending key(s) left unaccepted")
        say(f"  accepted exactly the {len(expected)} expected ids after {arrived_after}s")
        self.steps["4"] = {"name": "keys", "secondsToBothKeys": arrived_after, "accepted": len(accepted),
                           "otherPendingKeysLeftUnaccepted": len(unaccepted), "acceptanceByExactId": True}
        if seeded:
            self.steps["4"]["generatedOnTheMaster"] = self.check_seeded(seeded)

    def check_seeded(self, seeded):
        """Each seeded minion: answers a ping, was never pending, and its accepted key's fingerprint is still the one the
        master read when it generated the pair."""
        secs, _ = self.ping_until(seeded, LIMITS["linux_key"], watch=self.seeded_never_pending)
        self.seeded_never_pending()
        for minion in seeded:
            if self.salt.finger(minion) != self.generated[minion]:
                raise StepFailed(f"the key the master holds for {minion} is not the one it generated")
        say(f"  the seeded minion answered a ping after {secs}s, was never pending, and its key is the one generated for it")
        return {"seeded": len(seeded), "answeredPing": True, "secondsToPing": secs, "neverPending": True,
                "fingerprintIsTheGeneratedOne": True}

    # ---- steps 5 and 6: remote execution and state

    def job(self, tgt, fun, expected, what, arg=None, kwarg=None, tgt_type="compound"):
        """Run one function through the API and wait for each expected minion's return."""
        jid = self.salt.local_async(tgt, fun, arg, kwarg, tgt_type)

        def done(ret):
            return all(m in ret for m in expected)
        _secs, ret = poll(what, lambda: patiently(lambda: self.salt.lookup(jid), {}), done, LIMITS["job"], report=120)
        return {m: ret[m] for m in expected}

    def ping_both(self, target, expected):
        return self.ping_until(expected, LIMITS["job"], target=target)

    def ping_until(self, expected, limit, target=None, watch=None):
        """Ping until every expected minion has answered. After a key is accepted the minion needs a moment to
        authenticate, and a publish it was not connected for never reaches it, so the ping is published again each short
        round. The target is the two expected ids, as the API account's rights name them; watch runs each round."""
        target = target or f"L@{self.n['linux']},{self.n['windows']}"
        start = _now()
        answered = set()
        while True:
            if watch:
                watch()
            jid = self.salt.local_async(target, "test.ping")
            until = _now() + 45
            while _now() < until:
                ret = patiently(lambda: self.salt.lookup(jid), {})
                answered |= {m for m, v in ret.items() if v is True and m in expected}
                if answered >= set(expected):
                    return round(_now() - start), {m: True for m in expected}
                _sleep(5)
            if _now() - start >= limit:
                raise StepFailed(f"test.ping: {len(answered)} of {len(expected)} minions answered within {limit // 60} minutes")

    def apply_state(self, tgt, sls, expected, what, test=False):
        kwarg = {"test": True} if test else None
        ret = self.job(tgt, "state.apply", expected, what, arg=[sls], kwarg=kwarg, tgt_type="grain")
        out = {m: state_outcome(r) for m, r in ret.items()}
        failed = {m: o for m, o in out.items() if o["failed"]}
        if failed:
            raise StepFailed(f"state.apply {sls} failed on {sorted(failed)}: {[o.get('error') for o in failed.values() if o.get('error')]}")
        return out

    def step_apply(self):
        say("step 5: ping, grains, one state, applied twice")
        n = self.n
        expected = [n["linux"], n["windows"]]
        target = f"L@{n['linux']},{n['windows']}"
        secs_ping, ping = self.ping_both(target, expected)
        say(f"  test.ping: {len(ping)} minions answered after {secs_ping}s")
        grains = self.job(target, "grains.item", expected, "grains.item", arg=list(GRAINS))
        for minion, g in grains.items():
            if not isinstance(g, dict) or g.get("saltversion") != SALT_VERSION:
                raise StepFailed(f"minion {minion} reports Salt {g.get('saltversion') if isinstance(g, dict) else g}, not {SALT_VERSION}")
        families = {m: g.get("os_family") for m, g in grains.items()}
        if families != {n["linux"]: "Debian", n["windows"]: "Windows"}:
            raise StepFailed(f"unexpected os_family grains: {sorted(set(families.values()))}")
        say(f"  grains: {families[n['linux']]} and {families[n['windows']]}, Salt {SALT_VERSION}")
        first = {}
        second = {}
        for grain, minion, label in (("os_family:Debian", n["linux"], "Linux"), ("os_family:Windows", n["windows"], "Windows")):
            first[label] = self.apply_state(grain, "guestcfg", [minion], f"the first apply on {label}")[minion]
            second[label] = self.apply_state(grain, "guestcfg", [minion], f"the second apply on {label}")[minion]
        for label in ("Linux", "Windows"):
            if not first[label]["changed"]:
                raise StepFailed(f"the first apply on {label} changed nothing; the state did no work")
            if second[label]["changed"]:
                raise StepFailed(f"the second apply on {label} changed something; the state is not idempotent")
        say("  the first apply changed the managed file; the second apply changed nothing, on both")
        self.steps["5"] = {"name": "first state", "firstApply": first, "secondApply": second, "secondApplyChangedNothing": True,
                           "osFamily": sorted(set(families.values())), "saltVersion": SALT_VERSION,
                           "targetedBy": "grain os_family"}

    def step_probes(self):
        """The read-only probe state on each minion, set against what the master holds for its id. Both sides are read
        and recorded before anything is judged, so a mismatch shows which of three it is: a different key, the same key
        hashed with a different default, or the same key stored in another PEM form. Fingerprints and the first line of
        a public key are public. A mismatch stops the run after the record is written; on Windows the signed-in sessions
        are recorded too.

        This is a consistency read, not a trust check: the probe reaches the minion over the channel its accepted key
        authenticates, so a second machine that claimed the id first would answer with its own key and still agree. What
        can show a second claimant is a second key under the id, which expected_not_denied reads again here."""
        say("probes, read-only: each minion's own key fingerprint against the master's, and the Windows sessions")
        n = self.n
        result, mismatch = {}, []
        for grain, minion, label in (("os_family:Debian", n["linux"], "Linux"), ("os_family:Windows", n["windows"], "Windows")):
            ret = self.job(grain, "state.apply", [minion], f"the probes on {label}", arg=["guestcfg.probe"], tgt_type="grain")[minion]
            own = {"default": probe_note(ret, "own-fingerprint"), "sha256": probe_note(ret, "own-sha256"),
                   "hashType": probe_note(ret, "hash-type"), "pubHead": probe_note(ret, "pub-head")}
            pem = self.salt.key_pem(minion)
            held = {"default": self.salt.finger(minion), "sha256": self.salt.finger(minion, "sha256"),
                    "pubHead": pem.splitlines()[0].strip() if pem else None,
                    "pubLines": ",".join(str(len(ln)) for ln in pem.splitlines()) if pem else None}
            own["pubLines"] = probe_note(ret, "pub-lines")
            own["pubFileSha256"] = probe_note(ret, "pub-file-sha256")
            own_body, held_body = probe_note(ret, "pub-body"), ("".join(pem.splitlines()[1:-1]) if pem else None)
            fingers_agree = bool(own["default"]) and own["default"] == held["default"]
            same_key = key_der_equal(own_body, held_body)
            master_hex = (held["sha256"] or "").replace(":", "").lower()
            row = {"sameKey": same_key, "fingerprintsAgree": fingers_agree, "pkiDir": probe_pki_dir(ret),
                   "minion": own, "master": held,
                   "fileSha256MatchesMaster": bool(own["pubFileSha256"]) and own["pubFileSha256"].lower() == master_hex,
                   "sha256Matches": bool(own["sha256"]) and own["sha256"] == held["sha256"],
                   "samePemForm": bool(own["pubHead"]) and own["pubHead"] == held["pubHead"],
                   "sameLayout": bool(own["pubLines"]) and own["pubLines"] == held["pubLines"]}
            say(f"  {label}: the same key {row['sameKey']}; key.finger minion {own['default']}, master {held['default']} "
                f"({'agree' if fingers_agree else 'differ'}); SHA-256 of the whole minion.pub "
                f"{'equals' if row['fileSha256MatchesMaster'] else 'differs from'} the master's; line lengths minion "
                f"{own['pubLines']}, master {held['pubLines']}")
            if label == "Windows":
                row["sessions"] = probe_sessions(ret)
            result[label] = row
            if not same_key:
                mismatch.append(label)
        self.steps["probes"] = {"name": "probes", **result}
        self.expected_not_denied(where="the probes")
        unread = [lb for lb in mismatch if result[lb]["sameKey"] is None]
        if unread:
            raise StepFailed(f"on {' and '.join(unread)}, the minion's own public key could not be read against the "
                             "master's for its id")
        if mismatch:
            raise StepFailed(f"on {' and '.join(mismatch)}, the minion's own public key is not the one the master holds "
                             "for its id; both sides are in the record")
        sessions = result["Windows"]["sessions"]
        say("  on both minions the minion's own public key is the one the master holds for its id; Windows: "
            + (f"{sessions['signedInSessions']} session(s) signed in" if sessions["read"] else "the session read failed")
            + f" (quser exit {sessions['quserExit']})")

    def step_drift(self):
        say("step 6: drift named, then corrected")
        n = self.n
        result = {}
        for grain, minion, label in (("os_family:Debian", n["linux"], "Linux"), ("os_family:Windows", n["windows"], "Windows")):
            drifted = self.apply_state(grain, "guestcfg.drift", [minion], f"the drifting change on {label}")[minion]
            named = self.apply_state(grain, "guestcfg", [minion], f"test=True on {label}", test=True)[minion]
            restored = self.apply_state(grain, "guestcfg", [minion], f"the restoring apply on {label}")[minion]
            again = self.apply_state(grain, "guestcfg", [minion], f"test=True after the restore on {label}", test=True)[minion]
            if not (drifted["changed"] and named["wouldChange"] and restored["changed"] and not again["wouldChange"]):
                raise StepFailed(f"drift on {label}: changed {drifted['changed']}, named {named['wouldChange']}, "
                                 f"restored {restored['changed']}, after restore {again['wouldChange']}")
            result[label] = {"driftChanged": drifted["changed"], "testNamedIt": named["wouldChange"],
                             "applyRestoredIt": restored["changed"], "testAfterRestoreWouldChange": again["wouldChange"]}
        say("  on both minions: test=True named the drift, an apply restored it, and test=True afterwards reported nothing to change")
        self.steps["6"] = {"name": "drift", **result}

    def execute(self):
        started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        outcome, code = "complete", 0
        teardown_record = None
        try:
            self.step_master()
            if self.plan["proveSourceRanges"]:
                self.step_source_ranges()
            if self.plan["keys"] == "preseed":
                self.step_preseed()
            self.step_minions()
            self.step_keys()
            self.step_apply()
            self.step_probes()
            self.step_drift()
            say("step 7: retirement, in order: keys, " + ("the minion deployments, the master's, the blueprints"
                                                          if self.plan["via"] == "automation" else "machines, master and secrets"))
            teardown_record = self.retire()
            self.steps["7"] = {"name": "retirement", **teardown_record}
            say("step 8: read back")
            residue = self.residue()
            self.steps["8"] = {"name": "read back", "residue": residue, "clean": not any(residue.values())}
            if any(residue.values()):
                outcome, code = "residue", 3
                say(f"  SOMETHING REMAINS: {residue}")
            else:
                say("  nothing this run created is still here")
        except BaseException as ex:
            outcome, code = "failed", 2
            reason = _reason(ex)
            self.record_failure = reason
            say(f"FAILED: {reason}")
            say("running the teardown")
            try:
                teardown_record = self.retire()
            except BaseException as ex2:
                teardown_record = {"clean": False, "error": _reason(ex2)}
                say(f"the teardown itself failed: {_reason(ex2)}")
            residue = teardown_record.get("residue") if isinstance(teardown_record, dict) else None
            if not teardown_record.get("clean", False) or (residue and any(residue.values())):
                outcome, code = "failed, residue", 3
                say("SOMETHING REMAINS; run guestcfg.py teardown --execute")
        if not write_record(self.record(started, outcome, teardown_record), self) and code == 0:
            code = 2
        return code

    def retire(self):
        if self.plan["via"] == "automation":
            return teardown_automation(self.e, self.url, self.ns, self.run_id, self.plan["projectId"], self)
        return teardown(self.e, self.url, self.ns, self.run_id, self)

    def residue(self):
        if self.plan["via"] == "automation":
            return automation_residue(self.e, self.url, self.ns, self.run_id, self.plan["projectId"])
        return list_residue(self.e, self.url, self.ns, self.run_id)

    def record(self, started, outcome, teardown_record):
        plan = self.plan
        return {"captured_utc": started, "signIn": self.e.kind, "saltVersion": SALT_VERSION,
                "project": L.get("project", plan["project"]), "namespace": L.get("namespace", plan["namespace"]),
                "runId": self.run_id, "windowsBootstrap": plan["windowsBootstrap"], "windowsBootstrapPath": BOOTSTRAP_PATHS[plan["windowsBootstrap"]],
                "via": plan["via"], "viaPath": VIA_PATHS[plan["via"]], "keys": plan["keys"],
                "sourceRanges": self.requested_ranges(), "proveSourceRanges": plan["proveSourceRanges"],
                "linuxImage": L.get("image", plan["linuxImage"]), "windowsImage": L.get("image", plan["windowsImage"]),
                "classes": {"master": plan["vmClass"], "windows": plan["windowsClass"]}, "storageClass": L.get("storageclass", plan["storage"]),
                "created": [{"kind": c["kind"], "role": _role(c["name"], self.run_id)} for c in self.created],
                "steps": self.steps, "failure": self.record_failure, "outcome": outcome, "teardown": teardown_record}


def probe_fingerprint(ret):
    """The minion's own fingerprint from the probe state's return, at the minion's default hash type."""
    return probe_note(ret, "own-fingerprint")

def key_der_equal(body_a, body_b):
    """Whether two PEM bodies, each joined into one line of base64, decode to the same bytes: the same key, whatever its
    line layout. None when either side is missing or is not base64."""
    if not body_a or not body_b or "unread" in (body_a, body_b):
        return None
    try:
        return base64.b64decode(body_a, validate=True) == base64.b64decode(body_b, validate=True)
    except ValueError:
        return None


def probe_note(ret, prefix):
    """One read of the probe state: the text after PREFIX in the comment of the notification guestcfg-probe-<prefix>."""
    for key, row in (ret.items() if isinstance(ret, dict) else []):
        if f"_|-guestcfg-probe-{prefix}_|-" in key and isinstance(row, dict):
            text = str(row.get("comment") or "")
            return text.split(f"{prefix} ", 1)[1].strip() if f"{prefix} " in text else None
    return None


def probe_pki_dir(ret):
    """Where the minion keeps its key pair, as its own configuration resolves pki_dir: the comment of
    guestcfg-probe-pki-dir. A system path, never an estate value."""
    for key, row in (ret.items() if isinstance(ret, dict) else []):
        if "_|-guestcfg-probe-pki-dir_|-" in key and isinstance(row, dict):
            text = str(row.get("comment") or "")
            return text.split("pki-dir ", 1)[1].strip() if "pki-dir " in text else None
    return None


def probe_sessions(ret):
    """The Windows sessions from the probe's quser read, as quser printed them: its exit code, how many lines it wrote to
    stdout, how many sessions those lines list (every line after the header), and the first words of stderr. Microsoft's
    quser page states no exit codes, so nothing is inferred from the code alone: noUserSignedIn is True only when stdout
    lists no session and stderr says no user exists. No user name is recorded."""
    for key, row in (ret.items() if isinstance(ret, dict) else []):
        if "_|-guestcfg-probe-signed-in-sessions_|-" in key and isinstance(row, dict):
            changes = row.get("changes") or {}
            lines = [ln for ln in str(changes.get("stdout") or "").splitlines() if ln.strip()]
            stderr = " ".join(str(changes.get("stderr") or "").split())[:80]
            sessions = max(len(lines) - 1, 0)
            return {"read": row.get("result") is True, "quserExit": changes.get("retcode"), "stdoutLines": len(lines),
                    "signedInSessions": sessions, "stderr": stderr,
                    "noUserSignedIn": row.get("result") is True and not lines and "no user exists" in stderr.lower()}
    return {"read": False, "quserExit": None, "stdoutLines": None, "signedInSessions": None, "stderr": None,
            "noUserSignedIn": None}

def _role(name, run_id):
    roles = {v: k for k, v in names(run_id).items() if k != "prefix"}
    return roles.get(name, name.replace(f"guestcfg-{run_id}-", ""))


def _reason(ex):
    return L.scrub(f"{type(ex).__name__}: {ex}", addresses=True)


def list_residue(e, url, ns, run_id):
    """Everything still carrying this run's label, by kind, read back from the namespace."""
    out = {}
    for kind, base in Run.KINDS.items():
        out[kind] = [o["metadata"]["name"] for o in _owned(e, url, base.format(ns=ns), run_id)]
    return out


def _owned(e, url, path, run_id):
    """Objects carrying exactly this run's label. The selector asks the server; the filter below is the authority, so an
    object the server returned without the label is never in this list."""
    selector = urllib.parse.quote(f"{RUN_LABEL}={run_id}", safe="=")
    items = e.items(url, f"{path}?labelSelector={selector}")
    return [o for o in items if ((o.get("metadata") or {}).get("labels") or {}).get(RUN_LABEL) == run_id]


def _delete(e, url, path, name, refused):
    st, _ = e.ns(url, f"{path}/{urllib.parse.quote(name, safe='')}", "DELETE")
    if st not in (200, 202, 204, 404):
        refused.append({"object": name, "status": st})
    return st


def teardown(e, url, ns, run_id, run=None):
    """Remove one run, in the retirement order: minion keys, minion machines, the API's load balancer, the master, the
    secrets. Every object removed is first read back carrying this run's label. A second run finds nothing and succeeds."""
    n = names(run_id)
    vm_path = Run.KINDS["virtualmachines"].format(ns=ns)
    svc_path = Run.KINDS["virtualmachineservices"].format(ns=ns)
    secret_path = Run.KINDS["secrets"].format(ns=ns)
    result = {"keysDeleted": None, "minionMachines": 0, "loadBalancers": 0, "masterMachines": 0, "secrets": 0, "refused": [], "stillDeleting": []}

    # 0. objects a VCF Automation deployment made are that deployment's: they go through its Delete, never from here
    managed = [o["metadata"]["name"] for base in Run.KINDS.values() for o in _owned(e, url, base.format(ns=ns), run_id)
               if ((o.get("metadata") or {}).get("labels") or {}).get(MANAGED_BY) == AUTOMATION]
    if managed:
        residue = list_residue(e, url, ns, run_id)
        say(f"  {len(managed)} object(s) of this run belong to VCF Automation deployments and were not deleted here: "
            "set GUESTCFG_VIA=automation and GUESTCFG_PROJECT, and run the teardown again")
        return {**result, "keysDeleted": "skipped: the run's objects belong to VCF Automation deployments",
                "managedByAutomation": len(managed), "residue": residue, "clean": False}

    # 1. the minion keys, while the master still answers
    result["keysDeleted"] = _delete_keys(e, url, ns, run_id, n, run)

    # 2. the minion machines
    vms = _owned(e, url, vm_path, run_id)
    minions = [v["metadata"]["name"] for v in vms if v["metadata"]["name"] in (n["linux"], n["windows"])]
    master = [v["metadata"]["name"] for v in vms if v["metadata"]["name"] == n["master"]]
    strays = [v["metadata"]["name"] for v in vms if v["metadata"]["name"] not in (n["linux"], n["windows"], n["master"])]
    for name in minions:
        _delete(e, url, vm_path, name, result["refused"])
        result["minionMachines"] += 1
    result["stillDeleting"] += _wait_gone(e, url, vm_path, minions, run_id)

    # 3. the load balancer, so the API is no longer exposed before the master goes
    for s in _owned(e, url, svc_path, run_id):
        _delete(e, url, svc_path, s["metadata"]["name"], result["refused"])
        result["loadBalancers"] += 1

    # 4. the master
    for name in master + strays:
        _delete(e, url, vm_path, name, result["refused"])
        result["masterMachines"] += 1
    result["stillDeleting"] += _wait_gone(e, url, vm_path, master + strays, run_id)

    # 5. the secrets last, so the keys step above can still read the API credentials
    for s in _owned(e, url, secret_path, run_id):
        _delete(e, url, secret_path, s["metadata"]["name"], result["refused"])
        result["secrets"] += 1

    residue = list_residue(e, url, ns, run_id)
    result["residue"] = residue
    result["clean"] = not any(residue.values())
    say(f"  teardown: {result['minionMachines']} minion machine(s), {result['loadBalancers']} load balancer(s), "
        f"{result['masterMachines']} master machine(s), {result['secrets']} secret(s); keys: {result['keysDeleted']}; "
        f"residue: {'none' if result['clean'] else residue}")
    for item in result["refused"]:
        say(f"  the delete of {item['object']} answered {item['status']}")
    return result


def _delete_keys(e, url, ns, run_id, n, run):
    """Delete the two minion keys through the master's API. The API credentials come from the run in memory, or for a
    fresh process from the run's labelled Secret. An API that cannot be reached is reported; the machines still go.
    Returns "deleted" when every expected key the master held is gone, "none present" when it held none of them (a run
    that failed before a key arrived), "some keys remained", or "skipped: <why>"."""
    secret_path = Run.KINDS["secrets"].format(ns=ns)
    svc_path = Run.KINDS["virtualmachineservices"].format(ns=ns)
    salt = run.salt if run is not None else None
    if salt is None:
        st, s = e.ns(url, f"{secret_path}/{n['api_secret']}")
        data = (s.get("data") or {}) if st == 200 and isinstance(s, dict) else {}
        labelled = ((s.get("metadata") or {}).get("labels") or {}).get(RUN_LABEL) == run_id if isinstance(s, dict) else False
        if not (labelled and data):
            return "skipped: the API credentials were not found"
        try:
            password = base64.b64decode(data["password"]).decode()
            cert = base64.b64decode(data["tls.crt"]).decode()
        except (KeyError, ValueError):
            return "skipped: the API credentials could not be read"
        L.hold(password)
        address = None
        for svc in _owned(e, url, svc_path, run_id):
            ing = (((svc or {}).get("status") or {}).get("loadBalancer") or {}).get("ingress") or []
            address = (ing[0].get("ip") or ing[0].get("hostname")) if ing else None
        if not address:
            return "skipped: the API's load balancer has no address"
        L.get("address", address)
        salt = SaltApi(f"https://{address}:{API_PORT}", cert, API_USER, password)
    try:
        if not (salt.token or salt.login()):
            return "skipped: the Salt API did not accept the login"
        L.hold(salt.token)
        before = salt.keys()
        ids = [i for i in (n["linux"], n["windows"]) if EXPECTED_ID.match(i)]
        present = set(before.get("minions") or []) | set(before.get("minions_pre") or [])
        found = [m for m in ids if m in present]
        if not found:
            return "none present"   # a run that failed before any key reached the master deleted nothing
        for minion in found:
            salt.wheel("key.delete", match=minion)
        after = salt.keys()
        gone = not (set(ids) & (set(after.get("minions") or []) | set(after.get("minions_pre") or [])))
        return "deleted" if gone else "some keys remained"
    except StepFailed as ex:
        return f"skipped: {ex}"


def _wait_gone(e, url, path, names_, run_id):
    """Wait for each machine to go. One that is still present at its limit is reported and the teardown continues, so
    the rest of the run's objects still go; the read-back then names what remains. Returns the names still present."""
    still = []
    for name in names_:
        def read():
            st, v = e.ns(url, f"{path}/{urllib.parse.quote(name, safe='')}")
            if st == 404:
                return None
            if st == 200 and ((v.get("metadata") or {}).get("labels") or {}).get(RUN_LABEL) != run_id:
                return None
            return v if st == 200 else {}
        try:
            poll(f"machine {name} to be deleted", read, lambda v: v is None, LIMITS["vm_gone"], report=120)
        except StepFailed:
            still.append(name)
            say(f"  machine {name} is still deleting at the limit of {LIMITS['vm_gone'] // 60} minutes")
    return still


# --------------------------------------------------------------------------- the automation path's records

def find_deployments(e, project_id, name):
    """The project's deployments of exactly this name: the list filters by name, and the filter below is the authority."""
    q = urllib.parse.urlencode({"projects": project_id, "name": name})
    return [d for d in e.pages(f"/deployment/api/deployments?{q}")
            if d.get("name") == name and d.get("projectId") in (None, project_id) and d.get("id")]


def find_blueprints(e, project_id, name):
    q = urllib.parse.urlencode({"projects": project_id, "name": name})
    return [b for b in e.pages(f"/blueprint/api/blueprints?{q}")
            if b.get("name") == name and b.get("projectId") in (None, project_id) and b.get("id")]


def _delete_deployment(e, dep_id, name, refused):
    """A Deployment.Delete request on the deployment: VCF Automation removes what the deployment made. A request still
    in progress on it answers 409, so the delete waits its turn up to the deployment limit. True when one was accepted."""
    start = last = _now()
    while True:
        st, r = e.api(f"/deployment/api/deployments/{dep_id}/requests", "POST",
                      {"actionId": "Deployment.Delete", "reason": "guest-configuration teardown", "inputs": {}})
        if st in (200, 201, 202):
            return True
        if st == 404:
            return False
        if st == 409 and _now() - start < LIMITS["deployment"]:
            if _now() - last >= REPORT * 2:
                last = _now()
                say(f"    deployment {name} is busy with another request; its delete waits")
            _sleep(POLL)
            continue
        refused.append({"object": name, "status": st, "message": msg(r)[:200]})
        return False


def _wait_deployment_gone(e, dep_id, name):
    try:
        poll(f"deployment {name} to be deleted", lambda: e.api(f"/deployment/api/deployments/{dep_id}")[0],
             lambda st: st == 404, LIMITS["deployment_gone"], report=120)
    except StepFailed:
        say(f"  deployment {name} is still deleting at the limit of {LIMITS['deployment_gone'] // 60} minutes")
        return False
    return True


def teardown_automation(e, url, ns, run_id, project_id, run=None):
    """Remove one automation-path run in the retirement order: the minion keys through the master's API, the two minion
    deployments, then the master's, each by a Deployment.Delete request on the deployment (the record, never the
    machines underneath it) and each waited for until it is gone, then the three blueprints. Deployments and blueprints
    are found by the run's names in the project as well as from the run's memory, so a fresh process finds them too and
    a second teardown deletes nothing."""
    n = names(run_id)
    result = {"keysDeleted": None, "deployments": 0, "blueprints": 0, "refused": [], "stillDeleting": []}
    result["keysDeleted"] = _delete_keys(e, url, ns, run_id, n, run)
    known = run.deployments if run is not None else {}
    for group in (("linux", "windows"), ("master",)):
        asked = []
        for role in group:
            ids = {d["id"] for d in find_deployments(e, project_id, n[role])}
            if role in known:
                ids.add(known[role]["id"])
            for dep_id in sorted(ids):
                if _delete_deployment(e, dep_id, n[role], result["refused"]):
                    result["deployments"] += 1
                    asked.append((dep_id, n[role]))
        for dep_id, name in asked:
            if not _wait_deployment_gone(e, dep_id, name):
                result["stillDeleting"].append(name)
    known_bp = run.blueprints if run is not None else {}
    for role in BLUEPRINT_FILES:
        name = blueprint_name(n, role)
        ids = {b["id"] for b in find_blueprints(e, project_id, name)}
        if role in known_bp:
            ids.add(known_bp[role]["id"])
        for bp_id in sorted(ids):
            st, r = e.api(f"/blueprint/api/blueprints/{bp_id}", "DELETE")
            if st in (200, 204):
                result["blueprints"] += 1
            elif st != 404:
                result["refused"].append({"object": name, "status": st, "message": msg(r)[:200]})
    residue = automation_residue(e, url, ns, run_id, project_id)
    result["residue"] = residue
    result["clean"] = not any(residue.values())
    say(f"  teardown: {result['deployments']} deployment(s) deleted through VCF Automation, minions first; "
        f"{result['blueprints']} blueprint(s); keys: {result['keysDeleted']}; residue: {'none' if result['clean'] else residue}")
    for item in result["refused"]:
        say(f"  the delete of {item['object']} answered {item['status']}")
    return result


def automation_residue(e, url, ns, run_id, project_id):
    """The namespace read back by the run's label, and the project's deployments and blueprints by the run's names."""
    n = names(run_id)
    out = list_residue(e, url, ns, run_id)
    out["deployments"] = [n[r] for r in ("linux", "windows", "master") if find_deployments(e, project_id, n[r])]
    out["blueprints"] = [blueprint_name(n, r) for r in BLUEPRINT_FILES if find_blueprints(e, project_id, blueprint_name(n, r))]
    return out


AUTOMATION_NAMES = re.compile(r"^(?:guestcfg-([0-9a-f]{6})-(?:master|linux|salt-master|salt-minion-linux|salt-minion-windows-sysprep)"
                              r"|gc-([0-9a-f]{6})-win)$")


def automation_runs(e, project_id):
    """The run ids the project's deployments and blueprints carry in their names, for a teardown that finds no label in
    the namespace (a run that failed before its first deployment made anything there)."""
    found = set()
    for path in (f"/deployment/api/deployments?projects={project_id}", f"/blueprint/api/blueprints?projects={project_id}"):
        for item in e.pages(path):
            m = AUTOMATION_NAMES.match(str(item.get("name") or ""))
            if m:
                found.add(m.group(1) or m.group(2))
    return found


def write_record(payload, run):
    """Write guestcfg.json, scrubbed. A record in which a secret or an estate name survived is not written."""
    out_dir = os.environ.get("OUT_DIR", ".")
    text = L.scrub(json.dumps(payload, indent=1, ensure_ascii=False))
    bare = PLACEHOLDER.sub("", text)
    secrets_ = list(L.secrets) + [run.api_password, run.windows_password, run.e.bearer, run.salt.token if run.salt else None]
    secrets_ += [s["pem_b64"] for s in run.seeds.values()]
    names_ = [run.e.host, run.master_ip, run.lb_address, run.plan["namespace"], run.plan["project"], run.plan.get("runnerAddress")]
    names_ += [r for r in run.plan.get("sourceRanges") or [] if r not in (ANY_SOURCE, TEST_NET_1)]
    leaked = [v for v in secrets_ if v and v in bare] + [
        v for v in names_ if v and re.search(r"(?<![A-Za-z0-9-])" + re.escape(v) + r"(?![A-Za-z0-9-])", bare)]
    if leaked:
        say(f"{len(leaked)} secret or estate value(s) reached the record; nothing was written")
        return False
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "guestcfg.json"), "w", encoding="utf-8") as f:
        f.write(text + "\n")
    say(f"wrote guestcfg.json: outcome {payload['outcome']}")
    return True


# --------------------------------------------------------------------------- the commands

def dry_run(plan):
    if plan["via"] == "automation":
        return dry_run_automation(plan)
    run_id = "<run>"
    n = names(run_id)
    say("DRY RUN: every object a run would create, in order. Nothing is created.")
    say(f"  in namespace {plan['namespace']}, each carrying the label {RUN_LABEL}=<run>:")
    objects = [
        ("Secret", n["api_secret"], f"API account {API_USER}: a generated password and the run's TLS certificate (values withheld)"),
        ("Secret", n["master_secret"], f"cloud-config: Salt {SALT_VERSION} from Broadcom's package location, auto_accept False, open_mode False, API over TLS, generated certificate and key"),
        ("VirtualMachine", n["master"], f"image {plan['linuxImage']}, class {plan['vmClass']}, storage class {plan['storage']}, cloud-init"),
        ("VirtualMachineService", n["lb"], f"type LoadBalancer, port {API_PORT} only, selector app={n['master']}"),
        ("Secret", n["linux_secret"], "cloud-config: the master's address, minion id " + n["linux"]),
        ("VirtualMachine", n["linux"], f"image {plan['linuxImage']}, class {plan['vmClass']}, storage class {plan['storage']}, cloud-init"),
        ("Secret", n["windows_secret"], f"Windows bootstrap path: {BOOTSTRAP_PATHS[plan['windowsBootstrap']]}; minion id {n['windows']}"),
        ("VirtualMachine", n["windows"], f"image {plan['windowsImage']}, class {plan['windowsClass']}, storage class {plan['storage']}, {BOOTSTRAP_PATHS[plan['windowsBootstrap']]}"),
    ]
    for kind, name, what in objects:
        say(f"    {kind:22s} {name:36s} {what}")
    say("  then, through the API on the load balancer: accept the two expected keys, ping, read grains, apply the state twice,")
    say("  read the probes, introduce and name drift, restore it; delete the two keys, the minions, the load balancer, the master")
    say("  and the secrets; read back.")
    dry_run_options(plan)
    say("  Windows limit: " + f"{LIMITS['windows_key']}s for its key to arrive, path {BOOTSTRAP_PATHS[plan['windowsBootstrap']]}.")
    say("Nothing was created.")


def dry_run_options(plan):
    if plan["sourceRanges"] is not None:
        say(f"  the API's load balancer carries loadBalancerSourceRanges {', '.join(plan['sourceRanges'])}, read back once it answers.")
    if plan["proveSourceRanges"]:
        steps = [TEST_NET_1, ANY_SOURCE] + ([f"{plan['runnerAddress']}/32"] if plan["runnerAddress"] else [])
        say(f"  once the API answers, its ranges are patched to {', '.join(steps)} in turn, each read for "
            f"{LIMITS['range_read']}s from here, then restored.")
    if plan["keys"] == "preseed":
        say("  once the API answers, key.gen_accept makes the Linux minion's key pair on the master; its bootstrap Secret seeds it")
        say("  (values withheld), and the Windows minion keeps acceptance by exact id.")


def dry_run_automation(plan):
    n = names("<run>")
    say("DRY RUN (GUESTCFG_VIA=automation): every object a run would create, in order. Nothing is created.")
    say(f"  in project {plan['project']}, three blueprints from the files beside this script, as written, each validated:")
    for role, fname in BLUEPRINT_FILES.items():
        say(f"    {'Blueprint':22s} {blueprint_name(n, role):48s} {fname}")
    say("  then three deployments, the master's first; the minions' are requested with the master's address:")
    ranges = ", ".join(plan["sourceRanges"] or [ANY_SOURCE])
    deployments = [
        (n["master"], f"app_name {n['prefix']}, image {plan['linuxImage']}, class {plan['vmClass']}, storage class "
                      f"{plan['storage']}, source ranges {ranges}; the API digest, certificate and key (values withheld)"),
        (n["linux"], f"app_name {n['prefix']}, image {plan['linuxImage']}, class {plan['vmClass']}, the master's address, no seeded key"),
        (n["windows"], f"app_name {n['windows_app']}, image {plan['windowsImage']}, class {plan['windowsClass']}, the master's "
                       "address, a generated administrator password (withheld)"),
    ]
    for name, what in deployments:
        say(f"    {'Deployment':22s} {name:48s} {what}")
    say(f"  each deployment makes its objects in namespace {plan['namespace']}, labelled {RUN_LABEL}=<run> and "
        f"{MANAGED_BY}={AUTOMATION}:")
    objects = [("Secret", n["master_secret"]), ("VirtualMachine", n["master"]), ("VirtualMachineService", n["lb"]),
               ("Secret", n["linux_secret"]), ("VirtualMachine", n["linux"]),
               ("Secret", n["windows_bp_secret"]), ("VirtualMachine", n["windows"])]
    for kind, name in objects:
        say(f"    {kind:22s} {name}")
    say("  then steps 4 to 8 as on the supervisor path; the teardown deletes the minion deployments, then the master's,")
    say("  through VCF Automation, then the blueprints, and reads the namespace, the deployments and the blueprints back.")
    dry_run_options(plan)
    say("Nothing was created.")


def choose_run_id(e, url, ns, project_id=None):
    """Which run a teardown removes: GUESTCFG_RUN_ID, or the only run in the namespace, and on the automation path the
    only run whose names the project's deployments and blueprints carry. Two or more runs without the variable is a
    refusal, because each may belong to someone else."""
    wanted = os.environ.get("GUESTCFG_RUN_ID")
    if wanted:
        if not RUN_ID.match(wanted):
            raise Refusal("GUESTCFG_RUN_ID is not a run id (six lowercase hexadecimal characters)")
        return wanted
    found = set()
    for base in Run.KINDS.values():
        for o in e.items(url, f"{base.format(ns=ns)}?labelSelector={urllib.parse.quote(RUN_LABEL, safe='')}"):
            value = ((o.get("metadata") or {}).get("labels") or {}).get(RUN_LABEL)
            if value and RUN_ID.match(value):
                found.add(value)
    if project_id:
        found |= automation_runs(e, project_id)
    if len(found) > 1:
        raise Refusal(f"{len(found)} runs carry the label in this namespace ({', '.join(sorted(found))}); set GUESTCFG_RUN_ID to one of them")
    return found.pop() if found else None


def cmd_teardown(e, target, execute):
    project, ns, url = target
    via = via_path()
    if via == "automation" and not os.environ.get("GUESTCFG_PROJECT"):
        raise Refusal("GUESTCFG_VIA=automation needs GUESTCFG_PROJECT: the project the run's deployments and blueprints are in")
    project_id = classic_project(e, project) if via == "automation" else None
    run_id = choose_run_id(e, url, ns, project_id)
    if not run_id:
        say("nothing carries this tool's run label in the namespace" + (", or its names in the project" if project_id else "")
            + "; nothing to do")
        return 0
    say(f"run {run_id}")
    if not execute:
        say("DRY RUN: a teardown would delete, in order, these objects carrying the run's label (nothing is deleted):")
        if via == "automation":
            residue = automation_residue(e, url, ns, run_id, project_id)
            say("  through VCF Automation: the minion deployments, then the master's, then the blueprints; the namespace's "
                "objects go with their deployments")
            for kind in ("deployments", "blueprints", *Run.KINDS):
                say(f"    {kind:24s} {residue[kind] if residue[kind] else 'none'}")
            return 0
        for kind, base in Run.KINDS.items():
            names_ = [o["metadata"]["name"] for o in _owned(e, url, base.format(ns=ns), run_id)]
            say(f"    {kind:24s} {names_ if names_ else 'none'}")
        return 0
    res = teardown_automation(e, url, ns, run_id, project_id) if via == "automation" else teardown(e, url, ns, run_id)
    return 0 if res["clean"] else 3


def refuse_unknown_args(argv, known):
    """Refuse any argument this script does not recognise, before a client opens (G-310): a stray flag must never reach
    a write. --help prints the usage above."""
    if "-h" in argv or "--help" in argv:
        print(__doc__)
        sys.exit(0)
    unknown = [a for a in argv if a not in known]
    if unknown:
        print(f"unknown argument(s) {unknown}: this script takes {', '.join(sorted(known))} (see --help)", file=sys.stderr)
        sys.exit(5)


def usage_error(text):
    print(f"{text} (see --help)", file=sys.stderr)
    sys.exit(5)


def parse(argv):
    refuse_unknown_args(argv, {"read", "run", "teardown", "--dry-run", "--execute"})
    commands = [a for a in argv if a in ("read", "run", "teardown")]
    if len(commands) != 1:
        usage_error("give exactly one of read, run or teardown")
    command, flags = commands[0], [a for a in argv if a.startswith("--")]
    if len(flags) != len(set(flags)) or len(flags) > 1:
        usage_error("give at most one flag")
    flag = flags[0] if flags else None
    if command == "read" and flag:
        usage_error("read takes no flag")
    return command, flag


def sign_in():
    host, org = os.environ.get("VCFA_HOST"), os.environ.get("VCFA_ORG")
    if not host or not org:
        raise Refusal("set VCFA_HOST and VCFA_ORG (see --help)")
    try:
        refresh, password = secret("VCFA_REFRESH_TOKEN"), secret("VCFA_PASSWORD")
    except OSError as ex:
        raise Refusal(str(ex)) from None
    user = os.environ.get("VCFA_USER")
    if not refresh and not (user and password):
        raise Refusal("set VCFA_REFRESH_TOKEN_FILE, or VCFA_USER with VCFA_PASSWORD_FILE (see --help)")
    L.hold(password)
    L.hold(refresh)
    e = Estate(host, org, refresh, None if refresh else user, None if refresh else password)
    L.hold(e.bearer)
    L.get("host", host)
    L.get("org", org)
    return e


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    command, flag = parse(argv)
    execute = flag == "--execute"
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
    try:
        e = sign_in()
        if command == "teardown":
            return cmd_teardown(e, resolve_namespace(e), execute)
        plan = preflight(e)
        if command == "read":
            print_read(plan, reveal=True)
            return 0
        print_read(plan)
        if not execute:
            dry_run(plan)
            return 0
        run = Run(e, plan)
        say(f"\nrun {run.run_id}: Salt {SALT_VERSION}, Windows path {BOOTSTRAP_PATHS[plan['windowsBootstrap']]}")
        if plan["via"] != "supervisor" or plan["keys"] != "accept":
            say(f"  built {VIA_PATHS[plan['via']]}; minion keys {KEY_MODES[plan['keys']]}")
        return run.execute()
    except Refusal as ex:
        print(f"REFUSED: {L.scrub(str(ex), addresses=True)}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
