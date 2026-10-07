#!/usr/bin/env python3
"""test_gate.py: the four rules of gate.py, checked off the engine with a stubbed registry and a fake clock.

Each case is one way a pre-delete gate can be wrong: acting on a create, letting a delete through when the
registry cannot be reached or is not configured, blocking for ever on a record that is already gone, and running
past its own ceiling. The fake clock makes the deadline cases instant. deploy_gate.py also checks that the
workflow it builds carries gate.py byte for byte, so what passes here is what the Orchestrator runs.

Run:  python3 test_gate.py      exit 0 when every case holds
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gate import GateRefused, handler, plan, unregister  # noqa: E402

REG = "https://registry.example.net/machines"
DELETE = {"eventType": "DELETE_RESOURCE", "id": "res-1", "resourceName": "Web01VM"}
CREATE = {"eventType": "CREATE_RESOURCE", "id": "res-1", "resourceName": "Web01VM"}


class Clock:
    """A clock that advances only when the code under test sleeps or a request takes time."""
    def __init__(self):
        self.t = 0.0
    def now(self):
        return self.t
    def sleep(self, s):
        self.t += s


def registry(*answers, clock=None, cost=0.5):
    """A send() stub that answers in order (an int status, or an exception to raise) and records each call."""
    calls, queue = [], list(answers)
    def send(method, url, timeout, verify_tls=True):
        calls.append((method, url, round(timeout, 3)))
        if clock:
            clock.t += min(cost, timeout)
        a = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(a, BaseException):
            raise a
        return a
    return send, calls


def case(name, fn, holds):
    try:
        got = fn()
    except Exception as e:  # noqa: BLE001  the refusals are the result under test
        got = e
    ok = holds(got)
    print(("PASS" if ok else "FAIL"), name)
    return ok


def run(send, clock, deadline=30):
    return unregister(REG, "res-1", deadline, send=send, now=clock.now, sleep=clock.sleep)


def main():
    results = []
    send, calls = registry(204)
    results.append(case("a create on the same topic is a no-op, and the registry is not called",
                        lambda: (plan(CREATE), handler(None, {"inputProperties": CREATE, "registryUrl": "", "deadlineSeconds": 0})),
                        lambda r: r[0][0] is False and r[1] == {} and not calls))
    results.append(case("an event with no eventType is refused rather than guessed at",
                        lambda: plan({"id": "res-1"}), lambda e: isinstance(e, GateRefused) and "eventType" in str(e)))
    results.append(case("a delete with no resource id is refused",
                        lambda: plan({"eventType": "DELETE_RESOURCE"}), lambda e: isinstance(e, GateRefused)))
    results.append(case("a delete with no registry configured is refused (fail closed)",
                        lambda: handler(None, {"inputProperties": DELETE, "registryUrl": "", "deadlineSeconds": 30}),
                        lambda e: isinstance(e, GateRefused) and "no registryUrl" in str(e)))
    c = Clock(); send, calls = registry(204, clock=c)
    results.append(case("a delete the registry accepts is done in one call, keyed by the resource id",
                        lambda: run(send, c), lambda r: r == ("unregistered (HTTP 204)", 1) and calls[0][1] == REG + "/res-1"))
    c = Clock(); send, calls = registry(404, clock=c)
    results.append(case("a record already gone (404) counts as done, so a redelivered event succeeds",
                        lambda: run(send, c), lambda r: r[0].startswith("already absent") and r[1] == 1))
    c = Clock(); send, calls = registry(503, 503, 200, clock=c)
    results.append(case("a transient 503 is retried inside the deadline and then succeeds",
                        lambda: run(send, c), lambda r: r == ("unregistered (HTTP 200)", 3)))
    c = Clock(); send, calls = registry(403, clock=c)
    results.append(case("a 403 is a refusal retrying will not change: refused at once, one call",
                        lambda: run(send, c), lambda e: isinstance(e, GateRefused) and "403" in str(e) and len(calls) == 1))
    c = Clock(); send, calls = registry(TimeoutError("timed out"), clock=c, cost=10)
    results.append(case("an unreachable registry is refused at the deadline, never later",
                        lambda: run(send, c, deadline=30),
                        lambda e: isinstance(e, GateRefused) and "did not finish inside 30 s" in str(e) and c.t <= 30
                        and all(t <= 10 for _m, _u, t in calls)))
    c = Clock(); send, calls = registry(500, clock=c)
    results.append(case("a registry that keeps failing is refused at the deadline, with the last answer named",
                        lambda: run(send, c, deadline=20), lambda e: isinstance(e, GateRefused) and "HTTP 500" in str(e) and c.t <= 20))
    results.append(case("a deadline of zero is refused: the gate will not run unbounded",
                        lambda: unregister(REG, "res-1", 0), lambda e: isinstance(e, GateRefused) and "positive" in str(e)))
    print(f"\n{sum(results)} of {len(results)} cases hold")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
