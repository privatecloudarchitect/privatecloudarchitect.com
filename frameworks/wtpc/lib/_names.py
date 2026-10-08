"""lib/_names: the one place the WTPC framework builds, recognizes and adopts its object names.

The names follow the private-cloud-architect naming standard (owner prefix, one grammar per content class,
scope values only on scope objects; the companion's handbook/ops-estate/naming.py checks a name against it).
The framework's names changed on 2026-10-07 from the earlier form ('PCA - WTPC - Policy - <posture>',
'PCA - WTPC - Group - <posture> (VMs)', '... (<posture>)' on a per-posture super metric) to the current one
('PCA - WTPC - <posture>', 'PCA - WTPC - <posture> (VMs)', '... [<posture>]'). Every adopt-by-name lookup here
answers to both forms, so an estate built under the earlier names is adopted, never duplicated, and a
generator run converges it.

  * BUILD a name from here (posture_group, tier_policy, qualified, kinded, ...);
  * ADOPT through with_aliases / find / same;
  * RECOGNIZE with is_posture_policy, is_tier_group, ... (both forms).
"""
from __future__ import annotations

import functools
import re


OWNER = "PCA"
WTPC = f"{OWNER} - WTPC"
MEMBER_KINDS = ("VMs", "Hosts", "Clusters")


# ---------------------------------------------------------------- builders (the new grammar)
def posture_group(posture: str, members: str) -> str:
    """`PCA - WTPC - <posture> (<VMs|Hosts|Clusters>)`; estate-governance is built the same way."""
    return f"{WTPC} - {posture} ({members})"


def posture_policy(posture: str) -> str:
    return f"{WTPC} - {posture}"


def tier_scope(tier: str) -> str:
    """A tier scope reads '<tier> tier' wherever it is named: a group, a policy, or a qualifier."""
    return f"{tier} tier"


def tier_group(tier: str, members: str) -> str:
    return f"{WTPC} - {tier_scope(tier)} ({members})"


def tier_policy(tier: str) -> str:
    return f"{WTPC} - {tier_scope(tier)}"


def qualified(base: str, scope: str) -> str:
    """A per-scope copy: the base name with one final ' [<scope>]' qualifier."""
    return f"{base} [{scope}]"


# The kind field's short names (the registry's kind vocabulary), by resource kind key.
KIND_SHORT = {"VirtualMachine": "VM", "HostSystem": "Host", "ClusterComputeResource": "Cluster",
              "Datastore": "Datastore", "Environment": "Group", "ping_adapter_instance": "Ping Instance",
              "fqdn_type": "FQDN Check", "ip_type": "IP Check"}


def kinded(bundle_prefix: str, kind_key: str, rest: str) -> str:
    """`<Owner> - <Bundle> - <Kind> - <rest>` for a definition on `kind_key`."""
    return f"{bundle_prefix} - {KIND_SHORT[kind_key]} - {rest}"


UNION_GROUP = posture_group("estate-governance", "Clusters")


# ---------------------------------------------------------------- recognizers (old and new forms)
_P = r"[\w.-]+"   # a posture or tier token: no spaces
_RE = {
    "tier_policy": [rf"{WTPC} - ({_P}) tier", rf"{WTPC} - Tier - ({_P})"],
    "posture_policy": [rf"{WTPC} - Policy - ({_P})", rf"{WTPC} - ({_P})"],
    "tier_group": [rf"{WTPC} - ({_P}) tier \((Hosts|Clusters|VMs)\)", rf"{WTPC} - Tier - ({_P}) \((Hosts|Clusters|VMs)\)"],
    "posture_group": [rf"{WTPC} - Group - ({_P}) \((VMs|Hosts|Clusters)\)", rf"{WTPC} - ({_P}) \((VMs|Hosts|Clusters)\)"],
}


def _match(kind: str, name: str):
    for pat in _RE[kind]:
        m = re.fullmatch(pat, name or "")
        if m:
            return m
    return None


def is_tier_policy(name: str) -> bool:
    return _match("tier_policy", name) is not None


def is_posture_policy(name: str) -> bool:
    """A WTPC posture policy, old or new form. A tier policy is not one, though both are 'PCA - WTPC - <x>'."""
    return not is_tier_policy(name) and _match("posture_policy", name) is not None


def is_tier_group(name: str) -> bool:
    return _match("tier_group", name) is not None


def is_posture_group(name: str) -> bool:
    """A WTPC posture (or estate-governance) group, old or new form; never a tier group."""
    return not is_tier_group(name) and _match("posture_group", name) is not None


def scope_of(name: str) -> str | None:
    """The posture or tier token a WTPC group or policy name carries, either form."""
    for kind in ("tier_policy", "tier_group", "posture_policy", "posture_group"):
        m = _match(kind, name)
        if m:
            return m.group(1)
    return None


# ---------------------------------------------------------------- adoption (old and new as one key)
# The framework's renames that follow no rule (a symptom's kind cannot be read from its earlier name).
_IRREGULAR = (
    ('PCA - WTPC - Admission control not enabled',
     'PCA - WTPC - Cluster - Admission control not enabled'),
    ('PCA - WTPC - Consumed % of HA DRAM over 100',
     'PCA - WTPC - Cluster - Consumed % of HA DRAM over 100'),
    ('PCA - WTPC - DRS not fully automated',
     'PCA - WTPC - Cluster - DRS not fully automated'),
    ('PCA - WTPC - Failover level below N+1',
     'PCA - WTPC - Cluster - Failover level below N+1'),
    ('PCA - WTPC - HA config issues present',
     'PCA - WTPC - Cluster - HA config issues present'),
    ('PCA - WTPC - Member VMs over Contention breach',
     'PCA - WTPC - Cluster - Member VMs over Contention breach'),
    ('PCA - WTPC - Member VMs over Ready breach',
     'PCA - WTPC - Cluster - Member VMs over Ready breach'),
    ('PCA - WTPC - Member VMs swapping',
     'PCA - WTPC - Cluster - Member VMs swapping'),
    ('PCA - WTPC - Member hosts over CPU envelope',
     'PCA - WTPC - Cluster - Member hosts over CPU envelope'),
    ('PCA - WTPC - Member hosts over Memory envelope',
     'PCA - WTPC - Cluster - Member hosts over Memory envelope'),
    ('PCA - WTPC - Reclaimable position past breach',
     'PCA - WTPC - Cluster - Reclaimable position past breach'),
    ('PCA - WTPC - VM over CPU Ready envelope',
     'PCA - WTPC - VM - CPU Ready over envelope'),
    ('PCA - WTPC - VM over Memory Contention envelope',
     'PCA - WTPC - VM - Memory Contention over envelope'),
    # 2026-10-08: a unit at the end of a measure moved into parentheses
    ('PCA - Rightsizing - VM - Memory Workload %',
     'PCA - Rightsizing - VM - Memory Workload (%)'),
)


def pairs() -> tuple[tuple[str, str], ...]:
    """(earlier, current) for the renames no rule covers."""
    return _IRREGULAR


# The renames that follow a rule, each as (old pattern, old template, new pattern, new template) with named
# groups, so a name in either form answers to the other. They cover a scope this estate never instantiated (an
# adopter's posture) as well as ours; the migration map covers the renames that follow no rule.
_S = r"(?P<s>[a-z0-9]+(?:-[a-z0-9]+)+)"       # a posture or governance scope: lowercase, hyphenated
_T = r"(?P<t>[a-z0-9]+)"                        # a tier name
_M = r"(?P<m>VMs|Hosts|Clusters)"
_W = re.escape(WTPC)
_RULES = [
    (rf"{_W} - Policy - {_S}", "%s - Policy - {s}" % WTPC, rf"{_W} - {_S}", "%s - {s}" % WTPC),
    (rf"{_W} - Tier - {_T}", "%s - Tier - {t}" % WTPC, rf"{_W} - {_T} tier", "%s - {t} tier" % WTPC),
    (rf"{_W} - Group - {_S} \({_M}\)", "%s - Group - {s} ({m})" % WTPC, rf"{_W} - {_S} \({_M}\)", "%s - {s} ({m})" % WTPC),
    (rf"{_W} - Tier - {_T} \({_M}\)", "%s - Tier - {t} ({m})" % WTPC, rf"{_W} - {_T} tier \({_M}\)", "%s - {t} tier ({m})" % WTPC),
    (rf"{_W} - Tier - {_T} - Host (?P<r>.+)", "%s - Tier - {t} - Host {r}" % WTPC,
     rf"{_W} - Host - (?P<r>.+) \[{_T} tier\]", "%s - Host - {r} [{t} tier]" % WTPC),
    (rf"{_W} - Host over its tier (?P<a>CPU|Memory) Overcommit ceiling \({_T}\)",
     "%s - Host over its tier {a} Overcommit ceiling ({t})" % WTPC,
     rf"{_W} - Host - (?P<a>CPU|Memory) Overcommit over tier ceiling \[{_T} tier\]",
     "%s - Host - {a} Overcommit over tier ceiling [{t} tier]" % WTPC),
    (rf"{_W} - Cluster - Member VMs {_S} \(count\)", "%s - Cluster - Member VMs {s} (count)" % WTPC,
     rf"{_W} - Cluster - Member VMs \(count\) \[{_S}\]", "%s - Cluster - Member VMs (count) [{s}]" % WTPC),
    (rf"(?P<b>{_W} - (?:VM|Host|Cluster) - .+) \({_S}\)", "{b} ({s})",
     rf"(?P<b>{_W} - (?:VM|Host|Cluster) - .+) \[{_S}\]", "{b} [{s}]"),
    (rf"{_W} - Floor Breach - (?P<x>.+) - {_S}", "%s - Floor Breach - {x} - {s}" % WTPC,
     rf"{_W} - Cluster - (?P<x>.+) Floor Breach \[{_S}\]", "%s - Cluster - {x} Floor Breach [{s}]" % WTPC),
] + [
    (rf"{_W} - {re.escape(a)} - {_S}", "%s - %s - {s}" % (WTPC, a),
     rf"{_W} - {k} - {re.escape(a)} \[{_S}\]", "%s - %s - %s [{s}]" % (WTPC, k, a))
    for a, k in (("Performance Envelope Breach", "VM"), ("Capacity Envelope Breach", "Cluster"),
                 ("Cost Envelope Breach", "Cluster"))
]


def _rule_aliases(name: str) -> set[str]:
    out = set()
    for old_re, old_t, new_re, new_t in _RULES:
        m = re.fullmatch(old_re, name)
        if m:
            out.add(new_t.format(**m.groupdict()))
        m = re.fullmatch(new_re, name)
        if m:
            out.add(old_t.format(**m.groupdict()))
    out.discard(name)
    return out


@functools.lru_cache(maxsize=None)
def aliases(name: str) -> frozenset[str]:
    """The name itself plus its other spelling across the migration: by rule, or from the migration map."""
    out = {name} | _rule_aliases(name)
    for old, new in pairs():
        if name == new:
            out.add(old)
        elif name == old:
            out.add(new)
    return frozenset(out)


def same(a: str, b: str) -> bool:
    return a == b or a in aliases(b)


class AliasIndex(dict):
    """A {name: value} index whose LOOKUPS answer to a migrated object's old or new name, while iteration,
    len() and items() see only the names that are actually live. A loop over the index therefore visits each
    object once (teardown never plans the same id twice), and `index[new_name]` finds the old-named object."""

    def _key(self, k):
        if dict.__contains__(self, k):
            return k
        for a in aliases(k):
            if dict.__contains__(self, a):
                return a
        return k

    def __getitem__(self, k):
        return dict.__getitem__(self, self._key(k))

    def __contains__(self, k):
        return dict.__contains__(self, self._key(k))

    def get(self, k, default=None):
        return dict.get(self, self._key(k), default)


class AliasSet(set):
    """A set of live names whose membership test answers to either spelling of a migrated name."""

    def __contains__(self, k):
        return any(set.__contains__(self, a) for a in aliases(k))


def with_aliases(index: dict) -> AliasIndex:
    """The index, answering lookups under each migrated object's old and new names (see AliasIndex)."""
    return AliasIndex(index)


def find(items, name: str, key: str = "name"):
    """The first item whose `key` is `name` or its other spelling; None when absent."""
    names = aliases(name)
    for it in items:
        value = it.get(key) if isinstance(it, dict) else getattr(it, key, None)
        if isinstance(it, dict) and value is None and "resourceKey" in it:
            value = (it.get("resourceKey") or {}).get("name")
        if value in names:
            return it
    return None
