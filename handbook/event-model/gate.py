"""gate.py: a pre-delete gate, as the one Python scriptable task of an Orchestrator workflow.

A blocking subscription on deployment.resource.request.pre runs this once per resource, before the resource is
removed. It unregisters the resource from an external registry and lets the delete continue only when that is
done. deploy_gate.py embeds this file, unchanged, as the workflow's script; test_gate.py drives the same functions
off the engine.

The four rules a blocking workflow owes the delete it holds, each in one place below:

  act only on deletes        plan(): the same topic carries every create, so anything but DELETE_RESOURCE is a no-op
  fail closed                every path that cannot finish the de-registration raises GateRefused, and a raise
                             refuses the delete with every resource left in place
  stay idempotent            a registry that no longer holds the record answers 404 or 410, which counts as done,
                             so a redelivered event or a second attempt succeeds rather than blocking for ever
  bound your own runtime     unregister() stops at deadlineSeconds and raises; the subscription's timeout of 0
                             makes the platform wait as long as the workflow runs, so the ceiling has to be here

Workflow contract: one input, inputProperties (Properties), which arrives here as a dict. Three workflow
attributes, bound into the task: registryUrl, deadlineSeconds, verifyTls.

The registry is keyed by the resource id the payload carries (the create event carries the same id, so a gate
that registers on create and unregisters on delete agrees with itself). Replace unregister() with your own
system's call and keep its contract: return when the record is gone, raise GateRefused otherwise.
"""
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

DELETE = "DELETE_RESOURCE"
GONE = (404, 410)            # the registry holds no record: already unregistered, which is success
PER_CALL_SECONDS = 10        # one request never takes the whole budget
BACKOFF_SECONDS = 2          # between attempts on a transient failure, growing with each attempt


class GateRefused(Exception):
    """Raised on every path that cannot finish the de-registration. Raising is what refuses the delete."""


def plan(props):
    """Decide whether this event is ours. Returns (act, reason); raises when the event cannot be read."""
    if not isinstance(props, dict):
        raise GateRefused("inputProperties did not arrive as properties, so this gate cannot read the event; refusing")
    event_type = props.get("eventType")
    if not event_type:
        raise GateRefused("the payload carries no eventType, so this gate cannot tell a delete from a create; refusing")
    if event_type != DELETE:
        return False, f"{event_type} on {props.get('resourceName')}: not a delete, nothing to do"
    if not props.get("id"):
        raise GateRefused("the delete carries no resource id, so there is nothing to unregister by; refusing")
    return True, f"{event_type} on {props.get('resourceName')}: unregister {props['id']} before it is removed"


def _send(method, url, timeout, verify_tls=True):
    """One HTTP request; returns the status. Network failures propagate as OSError for the caller to classify."""
    ctx = ssl.create_default_context()
    if not verify_tls:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(url, method=method, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def unregister(registry_url, key, deadline_seconds, send=_send, now=time.monotonic, sleep=time.sleep,
               verify_tls=True):
    """Remove `key` from the registry, within `deadline_seconds`. Returns (outcome, attempts); raises GateRefused.

    2xx is done, 404 or 410 is already done, 408, 429 and 5xx and network failures are retried until the
    deadline, and any other 4xx is a refusal that retrying will not change."""
    if not registry_url:
        raise GateRefused("no registryUrl is configured, so the de-registration cannot be actuated; refusing the delete")
    if not deadline_seconds or deadline_seconds <= 0:
        raise GateRefused("deadlineSeconds must be positive; an unbounded gate is a hung delete waiting to happen")
    url = registry_url.rstrip("/") + "/" + urllib.parse.quote(str(key), safe="")
    end = now() + deadline_seconds
    attempts, last = 0, "no attempt made"
    while True:
        remaining = end - now()
        if remaining <= 0:
            raise GateRefused(f"the de-registration did not finish inside {deadline_seconds:g} s "
                              f"({attempts} attempt(s), last: {last}); refusing the delete")
        attempts += 1
        try:
            status = send("DELETE", url, min(remaining, PER_CALL_SECONDS), verify_tls)
        except OSError as e:                      # covers URLError, timeouts and refused connections
            last = f"{type(e).__name__}: {getattr(e, 'reason', e)}"
        else:
            if 200 <= status < 300:
                return f"unregistered (HTTP {status})", attempts
            if status in GONE:
                return f"already absent (HTTP {status}), counted as done", attempts
            if 400 <= status < 500 and status not in (408, 429):
                raise GateRefused(f"the registry refused the de-registration with HTTP {status}; refusing the delete")
            last = f"HTTP {status}"
        sleep(max(0.0, min(BACKOFF_SECONDS * attempts, end - now())))


def _flag(value, default=True):
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() not in ("false", "0", "no")


def handler(context, inputs):
    """The scriptable task's entry point: Orchestrator calls handler(context, inputs) for a python:3.11 task."""
    props = inputs.get("inputProperties")
    act, reason = plan(props)
    print(reason)
    if not act:
        return {}
    started = time.monotonic()
    outcome, attempts = unregister(inputs.get("registryUrl"), props["id"], float(inputs.get("deadlineSeconds") or 0),
                                   verify_tls=_flag(inputs.get("verifyTls")))
    print(f"{outcome} after {attempts} attempt(s) in {time.monotonic() - started:.1f} s; the delete may continue")
    return {}
