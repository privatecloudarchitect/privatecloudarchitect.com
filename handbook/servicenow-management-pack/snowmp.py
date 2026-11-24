#!/usr/bin/env python3
"""snowmp.py: check, before and after a first sync, what the ServiceNow Management Pack and VCF Operations' ServiceNow
plug-in need on each side. It reads only: it creates, changes and deletes nothing, on either side.

Three subcommands, each a list of checks, each check HOLDS, FAILS or is a NOTE:

  file  offline: the pack's configuration file (and its custom trees, when they are enabled). The name filter's keys
        name the classes the trees sync (the CMDB class for the built-in tree, the classIdentifier for a custom tree);
        every alertingConfig has its own callerId and a filter that names alert definitions; no reference column is
        asked for in serviceNowElementsToRetrieve; every custom class maps the name column.
  ops   VCF Operations: the pack's version, each of its adapter instances (its state and status message, every integer
        setting set, the SSL setting), each ServiceNow plug-in instance and the notification rules that use it (each
        held to an object scope, definitions only narrowing it), the pack's credential kinds, what the plug-in accepts and what its rule
        sets, and whether a rule and the pack's adapter are both present; this script reads no file on the appliance,
        so whether the pack's alertingConfigs name the caller a rule sets is yours to read.
  snow  ServiceNow, as the account the pack or the plug-in signs in with: the discovery source VMwareTVS on
        cmdb_ci.discovery_source, a reconciliation rule for it on each class the trees sync, each class's
        identification rule (independent, or depending on something), the account's read of each table the pack's
        page lists and of sys_choice by field, whether Event Management's tables exist, and, with --elements, each
        column's type on the incident table, and for each class, that no two CIs from VMwareTVS share an identifier.

Settings (environment):
  OPS_HOST, OPS_BROKER_HOST, OPS_REALM, OPS_TLS_VERIFY, OPS_API_TOKEN_FILE   for ops (snowmp_ops.py)
  SNOW_INSTANCE              for snow: https://<instance>.service-now.com
  SNOW_USER, SNOW_PASSWORD_FILE   for snow: the account to check (a file, mode 0600, holding the password)
  SNOW_TLS_VERIFY            for snow: TLS verification, on by default; set false for an instance behind a private CA
  OUT                        the directory a --record is written to (default: the current directory)

Arguments:
  file PATH [--trees DIR]    the primary file and its custom_trees directory (default: DIR beside PATH)
  ops                        no arguments
  snow [--classes A,B] [--elements a,b]   the CMDB classes to check (default: the built-in tree's six)
  --record                   also write the result as JSON into OUT. With it, every name read from your estate (the
                             instance and account, the Operations host, adapter, plug-in and rule names, the pack's
                             file) is replaced by a placeholder such as {{adapter-1}}, in the record and in what is
                             printed, so either can be shared; the record is refused when a registered name survives

Run:
  python3 snowmp.py file work/my-config.json
  export OPS_HOST=<operations-fqdn> OPS_BROKER_HOST=<identity-broker-fqdn> OPS_API_TOKEN_FILE=<token file>
  python3 snowmp.py ops
  export SNOW_INSTANCE=https://<instance>.service-now.com SNOW_USER=<pack account> SNOW_PASSWORD_FILE=<file>
  python3 snowmp.py snow --elements state,priority
Exit: 0 every check held · 1 a check failed · 2 an argument or setting is missing, or a secret file is open to group or
      other · 3 a sign-in or a read failed, or the record was refused because a registered name survived its scrub
"""

import base64
import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import snowmp_ops as opslib  # the shared sign-in, under this companion's own module name

BUILT_IN = [
    "cmdb_ci_vcenter_datastore",
    "cmdb_ci_vcenter_datacenter",
    "cmdb_ci_esx_server",
    "cmdb_ci_vcenter_cluster",
    "cmdb_ci_vcenter",
    "cmdb_ci_vmware_instance",
]
SOURCE = "VMwareTVS"
PLUGIN_TYPE = "GenericRestPlugin-servicenow"
INTEGERS = [
    "alert_sync_period",
    "maximum_concurrent_servicenow_requests",
    "maximum_concurrent_vrops_requests",
    "sn_max_retries",
    "sn_request_timeout",
    "vr_max_retries",
    "vr_request_timeout",
]
SSL_VALUES = ["No SSL", "No Verify", "Verify"]
# The tables the pack's page "Creating a Least Privileged User" lists, by the purpose it gives them.
TABLES = {
    "all configurations": ["sys_user_has_role", "security_acl_detail", "sys_security_operation"],
    "resource grouping": [
        "cmdb_metadata_hosting",
        "cmdb_metadata_reference",
        "cmdb_metadata_containment",
        "sys_dictionary",
        "sys_glide_object",
    ],
    "alerting": ["sys_choice", "incident"],
    "cmdb sync": ["sys_db_object", "cmdb_reconciliation_definition", "cmdb_rel_type"],
}
# Columns of the incident table that hold a reference; serviceNowElementsToRetrieve takes primitive columns only.
KNOWN_REFERENCES = {
    "assignment_group",
    "assigned_to",
    "caller_id",
    "cmdb_ci",
    "opened_by",
    "resolved_by",
    "closed_by",
    "business_service",
    "service_offering",
    "company",
    "location",
    "problem_id",
    "parent_incident",
    "rfc",
    "caused_by",
    "sys_domain",
}
TIMEOUT = 30
DUP_LIMIT = 10000
# Words of the products' own vocabulary: never registered as an estate name, so a scrub cannot blank them.
RESERVED = {"servicenow", "vcf", "operations", "vmware", "admin", "itil", "incident", "default", "none", "null", ""}


class Checks:
    """The run's checks. Without --record each line prints as it is made; with it, the lines print at the end with
    every registered estate name replaced, the same scrub the record gets."""

    def __init__(self, scrubbed=False):
        self.rows = []
        self.names = {}
        self.scrubbed = scrubbed

    def register(self, value, kind):
        v = (value or "").strip()
        if v.lower() in RESERVED or v in self.names:
            return
        n = sum(1 for p in self.names.values() if p.startswith("{{" + kind + "-")) + 1
        self.names[v] = "{{" + f"{kind}-{n}" + "}}"

    def _rx(self):
        alts = "|".join(re.escape(v) for v in sorted(self.names, key=len, reverse=True))
        return re.compile(rf"(?<![\w.-])({alts})(?![\w-])") if alts else None

    def scrub(self, value):
        """One longest-first pass over string values, never keys, on the same boundary the leak check uses."""
        rx = self._rx()
        if rx is None:
            return value
        if isinstance(value, str):
            return rx.sub(lambda m: self.names[m.group(1)], value)
        if isinstance(value, list):
            return [self.scrub(x) for x in value]
        if isinstance(value, dict):
            return {k: self.scrub(x) for k, x in value.items()}
        return value

    def leaks(self, text):
        rx = self._rx()
        return sorted({m.group(1) for m in rx.finditer(text)}) if rx else []

    @staticmethod
    def line(r):
        return f"{r['verdict']:6} {r['check']}" + (f": {r['detail']}" if r["detail"] else "")

    def add(self, verdict, what, detail=""):
        self.rows.append({"verdict": verdict, "check": what, "detail": detail})
        if not self.scrubbed:
            print(self.line(self.rows[-1]))

    def held(self, ok, what, detail=""):
        self.add("HOLDS" if ok else "FAILS", what, detail)

    def failed(self):
        return any(r["verdict"] == "FAILS" for r in self.rows)


# ---------------------------------------------------------------- file
def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def check_file(path, trees_dir, c):
    cfg = load(path)
    sync = cfg.get("cmdbSync") or {}
    built_in = sync.get("builtInTreeEnabled", True)
    custom = sync.get("customTreesEnabled", False)
    classes, identifiers = [], []
    if built_in:
        classes += BUILT_IN
    trees = []
    if custom:
        trees_dir = trees_dir or os.path.join(os.path.dirname(path), "custom_trees")
        names = (
            sorted(n for n in os.listdir(trees_dir) if n.endswith(".json"))
            if os.path.isdir(trees_dir)
            else []
        )
        c.held(
            bool(names),
            "custom trees are enabled and the custom_trees directory holds a tree",
            trees_dir,
        )
        for n in names:
            t = load(os.path.join(trees_dir, n))
            trees.append(t)
            for sc in t.get("syncClasses", []):
                identifiers.append(sc.get("classIdentifier"))
                classes.append(((sc.get("serviceNow") or {}).get("type") or {}).get("cmdbCiClass"))
                c.held(
                    bool(sc.get("identifierMapping")),
                    f"custom class {sc.get('classIdentifier')!r} maps identifiers",
                )
                cols = {d.get("cmdbColumn") for d in sc.get("dataColumns", [])} | {
                    (m.get("serviceNowId") or {}).get("column")
                    for m in sc.get("identifierMapping", [])
                }
                c.held(
                    "name" in cols,
                    f"custom class {sc.get('classIdentifier')!r} maps the name column",
                    ""
                    if "name" in cols
                    else "a custom tree syncs only the columns it maps, so without it the CI has no name",
                )
    if sync:
        c.held(
            sync.get("syncMode", "POPULATE_AND_DELETE_WHEN_NOT_EXISTING")
            in (
                "POPULATE_ONLY",
                "POPULATE_AND_DELETE_WHEN_NOT_EXISTING",
                "POPULATE_AND_DELETE_WHEN_REMOVED",
            ),
            "syncMode is one of the page's three",
            sync.get("syncMode", "(default)"),
        )
        c.add(
            "NOTE",
            "objectIdentifierSource",
            f"{sync.get('objectIdentifierSource', 'MOID (default)')}: it applies to VMs only. "
            "MOID, the page's choice for a first population, is reassigned when a VM moves to another vCenter; "
            "UUID is optional on a VM. On a populated CMDB keep the format its object_id column already holds",
        )
        keys = set((sync.get("nameFilter") or {}).keys())
        allowed = set(identifiers) | (set(BUILT_IN) if built_in else set())
        stray = sorted(keys - allowed)
        c.held(
            not stray,
            "every name filter key names a class the trees sync",
            (
                "not synced: "
                + ", ".join(stray)
                + ("; with a custom tree the key is its classIdentifier" if custom else "")
            )
            if stray
            else f"{len(keys)} key(s)",
        )
        for k, rx in (sync.get("nameFilter") or {}).items():
            try:
                re.compile(rx)
                c.add("NOTE", f"name filter {k!r} EXCLUDES the names it matches", rx)
            except re.error as e:
                c.held(False, f"name filter {k!r} is a valid regular expression", str(e))
    callers = [a.get("callerId") for a in cfg.get("alertingConfigs", [])]
    c.held(
        len(callers) == len(set(callers)) and all(callers),
        "every alertingConfig has its own callerId",
        ", ".join(map(str, callers)) or "(none)",
    )
    for a in cfg.get("alertingConfigs", []):
        scope = (a.get("filters") or {}).get("scope") or {}
        c.held(
            bool(scope.get("objectTypes")),
            f"alertingConfig {a.get('callerId')!r} narrows its scope to object types",
            "its scope takes object types only, so its own creates are not bounded by a rule's object scope"
            if scope.get("objectTypes")
            else "with no object types it acts on alerts from every kind of object",
        )
        trig = (a.get("filters") or {}).get("trigger") or {}
        c.held(
            bool(trig.get("alertDefinitions")),
            f"alertingConfig {a.get('callerId')!r} names its alert definitions",
            ""
            if trig.get("alertDefinitions")
            else "an alertingConfig with no definitions processes every alert its scope matches",
        )
        refs = sorted(set(a.get("serviceNowElementsToRetrieve", [])) & KNOWN_REFERENCES)
        c.held(
            not refs,
            f"alertingConfig {a.get('callerId')!r} retrieves primitive columns only",
            ("reference column(s): " + ", ".join(refs) + "; one puts the whole adapter down")
            if refs
            else "by a list of common reference columns; snow --elements reads each column's type",
        )
    if cfg.get("alertingConfigs"):
        c.add(
            "NOTE",
            "this file turns on the pack's alert sync (alertingConfigs)",
            "it adds to incidents a notification rule on the ServiceNow plug-in opens with the caller callerId names; "
            "on 9.1.1.0 it also opened records of its own: count the records one alert makes after three cycles",
        )
    return {
        "file": os.path.basename(path),
        "builtInTree": built_in,
        "customTrees": custom,
        "classes": classes,
    }


# ---------------------------------------------------------------- ops
def check_ops(c):
    tok = opslib.bearer()

    def get(path, params=None):
        st, body = opslib.ops("GET", path, tok, params={"_no_links": "true", **(params or {})})
        if st != 200:
            raise RuntimeError(f"GET {path} answered {st}")
        return body or {}

    sol = [
        s
        for s in get("/api/solutions").get("solution", [])
        if "servicenow" in (s.get("name") or "").lower()
    ]
    c.held(
        bool(sol),
        "the ServiceNow Management Pack is installed",
        ", ".join(f"{s.get('name')} {s.get('version')}" for s in sol),
    )
    kinds = get("/api/credentialkinds", {"adapterKind": "SERVICENOW_ADAPTER"}).get(
        "credentialTypes", []
    )
    c.add(
        "NOTE",
        "the pack's credential kinds",
        "; ".join(
            f"{k.get('name')} ({', '.join(f.get('key') for f in k.get('fields', []))})" for k in kinds
        )
        or "(none)",
    )
    st, ptype = opslib.ops(
        "GET", f"/api/alertplugins/types/{PLUGIN_TYPE}", tok, params={"_no_links": "true"}
    )
    accepts = next(
        (
            x.get("acceptableServiceCredentialTypes")
            for x in (ptype or {}).get("properties", [])
            if x.get("key") == "serviceCredentialType"
        ),
        None,
    )
    sets = [x.get("key") for x in (ptype or {}).get("rule-properties", [])]
    if st == 200:
        c.add("NOTE", "the ServiceNow plug-in's credential types", ", ".join(accepts or []) or "(none)")
        c.add(
            "NOTE",
            "a notification rule on the plug-in sets",
            ", ".join(sets) + ("" if "cmdb_ci" in sets else "; cmdb_ci is not among them"),
        )
    else:
        c.add("NOTE", f"the plug-in type {PLUGIN_TYPE}", f"answered {st}")
    adapters = get("/api/adapters", {"adapterKindKey": "SERVICENOW_ADAPTER"}).get(
        "adapterInstancesInfoDto", []
    )
    for a in adapters:
        name = a["resourceKey"]["name"]
        ids = {
            x["identifierType"]["name"]: x.get("value")
            for x in a["resourceKey"].get("resourceIdentifiers", [])
        }
        c.register(name, "adapter")
        for k in ("sn_host", "sn_proxy_host", "vrops_ui_hostname"):
            c.register(ids.get(k), "host")
        c.register(os.path.basename(ids.get("configuration_file") or ""), "file")
        missing = [k for k in INTEGERS if ids.get(k) in (None, "")]
        c.held(
            not missing,
            f"adapter {name!r}: every integer setting is set",
            (
                "unset: "
                + ", ".join(missing)
                + "; an instance created by API gets none of the pack's defaults"
            )
            if missing
            else "",
        )
        c.held(
            ids.get("sn_ssl_config") in SSL_VALUES,
            f"adapter {name!r}: sn_ssl_config is one of {', '.join(SSL_VALUES)}",
            str(ids.get("sn_ssl_config")),
        )
        if ids.get("sn_ssl_config") != "Verify":
            c.add(
                "NOTE",
                f"adapter {name!r} does not verify the instance's certificate",
                str(ids.get("sn_ssl_config")),
            )
        res = get(f"/api/resources/{a['id']}")
        states = [
            (s.get("resourceState"), s.get("resourceStatus"), s.get("statusMessage") or "")
            for s in res.get("resourceStatusStates", [])
        ]
        said = "; ".join(f"{s[0]} {s[1]} {s[2][:200]}".strip() for s in states)
        if any(s[0] == "STOPPED" for s in states):
            c.add("NOTE", f"adapter {name!r} is stopped: it syncs nothing and opens nothing", said)
        elif any(s[1] == "DATA_RECEIVING" for s in states):
            c.held(True, f"adapter {name!r}: collecting", said)
        elif any(s[0] == "FAILED" or s[1] in ("DOWN", "NO_DATA_RECEIVING") for s in states):
            c.held(False, f"adapter {name!r}: collecting", said or "FAILED with no message: read the adapter's log")
        else:
            c.add("NOTE", f"adapter {name!r} has not collected yet: read it again after one cycle", said)
    plugins = [
        p
        for p in get("/api/alertplugins").get("notificationPluginInstances", [])
        if p.get("pluginTypeId") == PLUGIN_TYPE
    ]
    rules = get("/api/notifications/rules").get("rules", [])
    ids = {p["pluginId"] for p in plugins}
    on_snow = [r for r in rules if r.get("pluginId") in ids]
    for p in plugins:
        c.register(p.get("name"), "plugin")
    for r in on_snow:
        c.register(r.get("name"), "rule")
    c.add(
        "NOTE",
        "ServiceNow plug-in instances",
        ", ".join(f"{p.get('name')} ({'on' if p.get('enabled') else 'off'})" for p in plugins)
        or "(none)",
    )
    for r in on_snow:
        objects = bool(r.get("resourceFilters"))
        definitions = bool((r.get("alertDefinitionIdFilters") or {}).get("values"))
        c.held(
            objects,
            f"rule {r.get('name')!r} on a ServiceNow plug-in carries an object scope",
            ""
            if objects
            else (
                "definitions alone send their alerts from every object, non-production included"
                if definitions
                else "a rule with neither sends every alert to ServiceNow"
            ),
        )
    live_rules = [r for r in on_snow if r.get("enabled")]
    collecting = [a for a in adapters]
    if live_rules and collecting:
        c.add(
            "NOTE",
            "a rule on the plug-in and the pack's adapter are both present",
            f"{len(live_rules)} enabled rule(s) on a ServiceNow plug-in and {len(collecting)} pack adapter "
            "instance(s): the rule opens, and an alertingConfig with the rule's caller adds to its incident; "
            "on 9.1.1.0 the pack also opened records of its own, so count the records one alert makes after three cycles",
        )
    return {
        "pack": [f"{s.get('name')} {s.get('version')}" for s in sol],
        "credential_kinds": {
            k.get("name"): [f.get("key") for f in k.get("fields", [])] for k in kinds
        },
        "plugin_credential_types": accepts,
        "rule_properties": sets,
        "adapters": len(adapters),
        "plugins": len(plugins),
        "rules_on_plugins": len(on_snow),
    }


# ---------------------------------------------------------------- snow
def snow_get(path, params=None):
    inst = os.environ["SNOW_INSTANCE"].rstrip("/")
    user = os.environ["SNOW_USER"]
    pw = opslib.secret("SNOW_PASSWORD")
    if not pw:
        raise KeyError("SNOW_PASSWORD_FILE is not set")
    url = inst + path + ("?" + urllib.parse.urlencode(params) if params else "")
    auth = base64.b64encode(f"{user}:{pw}".encode()).decode()
    del pw
    req = urllib.request.Request(
        url, headers={"Authorization": "Basic " + auth, "Accept": "application/json"}
    )
    verify = os.environ.get("SNOW_TLS_VERIFY", "true").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )
    ctx = ssl.create_default_context() if verify else ssl._create_unverified_context()
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=TIMEOUT) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except ValueError:
            return e.code, {}


def table(name, query, fields="sys_id", limit=20):
    return snow_get(
        f"/api/now/table/{name}",
        {"sysparm_query": query, "sysparm_fields": fields, "sysparm_limit": limit},
    )


def check_snow(classes, elements, c):
    st, me = table(
        "sys_user",
        f"user_name={os.environ['SNOW_USER']}",
        "sys_id,web_service_access_only,active",
        1,
    )
    if st == 401:
        raise RuntimeError(
            "the sign-in was refused (401): the instance may admit Basic API sign-in only to accounts "
            "holding snc_basic_auth_api_access or flagged web-service-access-only"
        )
    st, ch = table("sys_choice", f"name=cmdb_ci^element=discovery_source^value={SOURCE}", "value")
    if st == 403:
        c.held(
            False,
            f"the account can query sys_choice by field (the pack's own {SOURCE} check)",
            "answered 403: the pack's configure runs this query and stops when it is refused",
        )
    else:
        c.held(
            bool((ch or {}).get("result")),
            f"the discovery source {SOURCE} exists on cmdb_ci.discovery_source",
        )
    for cls in classes:
        st, rr = table(
            "cmdb_reconciliation_definition",
            f"applies_to={cls}^discovery_source={SOURCE}^active=true",
            "applies_to",
        )
        c.held(
            st == 200 and bool((rr or {}).get("result")),
            f"a reconciliation rule for {SOURCE} on {cls}",
            "" if st == 200 else f"read answered {st}",
        )
        st, meta = snow_get(f"/api/now/cmdb/meta/{cls}")
        rule = ((meta or {}).get("result") or {}).get("identification_rules") or {}
        ok = bool(rule.get("is_independent")) or bool(rule.get("depends_on"))
        c.held(
            st == 200 and ok,
            f"{cls}'s identification rule is independent or depends on something",
            f"rule from {rule.get('applies_to')}, independent {rule.get('is_independent')}, depends_on {len(rule.get('depends_on') or [])}"
            if st == 200
            else f"meta read answered {st}",
        )
    for cls in classes:
        # one CI per object: no two CIs the pack wrote share an identifier
        st, made = table(
            cls,
            f"discovery_source={SOURCE}",
            "correlation_id,object_id,vcenter_uuid",
            DUP_LIMIT,
        )
        rows = (made or {}).get("result") or []
        if st != 200:
            c.add("NOTE", f"{cls}: the CIs from {SOURCE} could not be read", f"answered {st}")
        elif not rows:
            c.add("NOTE", f"{cls}: no CI from {SOURCE} yet", "run snow again after the first sync")
        else:
            corr = [r.get("correlation_id") for r in rows if r.get("correlation_id")]
            pair = [
                (r.get("object_id"), r.get("vcenter_uuid"))
                for r in rows
                if r.get("object_id") and r.get("vcenter_uuid")
            ]
            dup = (len(corr) - len(set(corr))) + (len(pair) - len(set(pair)))
            c.held(
                dup == 0,
                f"{cls}: no two CIs from {SOURCE} share an identifier",
                f"{len(rows)} CI(s)" + (f", {dup} sharing one" if dup else "")
                + (f"; read the first {DUP_LIMIT} only" if len(rows) == DUP_LIMIT else ""),
            )
    for purpose, names in TABLES.items():
        for t in names:
            st, _ = table(t, "", "sys_id", 1)
            c.held(st == 200, f"the account reads {t} ({purpose})", f"answered {st}")
    for t in ("em_alert", "em_event"):
        st, _ = table(t, "", "sys_id", 1)
        c.add(
            "NOTE",
            f"{t} on this instance",
            "present"
            if st == 200
            else f"answered {st}: the {t.split('_')[1].upper()} destination writes to this table, so use INCIDENT",
        )
    for e in elements:
        # incident inherits most of its columns from task, so the column's dictionary row may be on either table
        st, d = table("sys_dictionary", f"nameINincident,task^element={e}", "internal_type", 2)
        kind = ((d or {}).get("result") or [{}])[0].get("internal_type") or {}
        kind = kind.get("value") if isinstance(kind, dict) else kind
        if not kind:
            c.add(
                "NOTE",
                f"incident.{e}: its type could not be read",
                f"answered {st}; check it before listing it",
            )
        else:
            c.held(
                kind not in ("reference", "glide_list"),
                f"incident.{e} is a primitive column",
                f"type {kind}",
            )
    return {"classes": classes, "elements": elements}


def flush(c):
    """The checks made before a run stopped, printed with the record's scrub when --record was given."""
    if c.scrubbed:
        for r in c.scrub(c.rows):
            print(Checks.line(r))


def main(argv):
    if not argv or argv[0] not in ("file", "ops", "snow"):
        print(__doc__)
        return 2
    sub, rest = argv[0], argv[1:]
    record = "--record" in rest
    c = Checks(scrubbed=record)
    for env, kind in (("OPS_HOST", "host"), ("OPS_BROKER_HOST", "host"), ("SNOW_USER", "account")):
        c.register(os.environ.get(env), kind)
    c.register(urllib.parse.urlparse(os.environ.get("SNOW_INSTANCE", "")).hostname, "host")
    try:
        if sub == "file":
            if not rest or rest[0].startswith("--"):
                print("file needs the configuration file's path")
                return 2
            trees = rest[rest.index("--trees") + 1] if "--trees" in rest else None
            facts = check_file(rest[0], trees, c)
        elif sub == "ops":
            facts = check_ops(c)
        else:
            for k in ("SNOW_INSTANCE", "SNOW_USER"):
                if not os.environ.get(k):
                    print(f"{k} is not set")
                    return 2
            classes = (
                rest[rest.index("--classes") + 1].split(",") if "--classes" in rest else BUILT_IN
            )
            elements = rest[rest.index("--elements") + 1].split(",") if "--elements" in rest else []
            facts = check_snow(classes, elements, c)
    except PermissionError as e:
        flush(c)
        print(str(e))
        return 2
    except KeyError as e:
        flush(c)
        print(f"a setting is missing: {e}")
        return 2
    except (RuntimeError, urllib.error.URLError, OSError) as e:
        flush(c)
        print(c.scrub(f"a sign-in or read failed: {e}"))
        return 3
    if record:
        stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H%M%SZ")
        rows = c.scrub(c.rows)
        body = json.dumps(
            {"subcommand": sub, "at": stamp, "facts": c.scrub(facts), "checks": rows}, indent=1
        )
        left = c.leaks(body)
        if left:
            print(f"refused to write the record: {len(left)} registered name(s) survived the scrub")
            return 3
        for r in rows:
            print(Checks.line(r))
        path = os.path.join(os.environ.get("OUT", "."), f"{stamp}-snowmp-{sub}.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write(body + "\n")
        print(f"record: {path}")
    held = sum(r["verdict"] == "HOLDS" for r in c.rows)
    failed = sum(r["verdict"] == "FAILS" for r in c.rows)
    print(f"\n{held} held, {failed} failed, {sum(r['verdict'] == 'NOTE' for r in c.rows)} notes")
    return 1 if c.failed() else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
