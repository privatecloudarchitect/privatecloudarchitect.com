"""resilient.py - the resilient API call, as a client you can read in one sitting.

Stdlib only. The three guarantees the chapter describes, each in one place:

  1. survive the token     a bearer is minted through a callable you supply, cached with its expiry, refreshed
                           on a UTC buffer before it runs out, and re-minted exactly once when a call answers 401;
                           the second answer, whatever it is, propagates
  2. trust the response    unwrap() finds the list under the wrapper key an API actually used and names the keys it
                           saw when none match; require() validates the fields you depend on and names the one that
                           drifted; paginate() reads a whole collection and refuses to stop short of the total the
                           envelope declares
  3. run twice safely      ensure() is find-by-key, update-if-changed, create-if-absent, and its dry run returns the
                           request it would have sent instead of sending it

The TLS seam is configuration: TLS_VERIFY=false turns verification off for a self-signed lab CA and the client
warns once, on stderr, every time it runs that way. Nothing here prints a token value.
"""

import http.client
import json
import os
import ssl
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

WRAPPER_KEYS = ("resourceList", "values", "content", "results", "elements", "servicesDetails", "vcfRoles", "items")
_WARNED = False
# the consumption surface answers a large collection page with more than a hundred response headers, and the
# standard library refuses such an answer outright ("got more than 100 headers") unless this limit is raised
http.client._MAXHEADERS = 1000


class ApiError(Exception):
    """A non-401 HTTP failure, or a 401 that survived one re-authentication."""
    def __init__(self, method, url, status, body):
        super().__init__(f"{method} {url} -> HTTP {status}: {str(body)[:200]}")
        self.method, self.url, self.status, self.body = method, url, status, body


class ShapeError(Exception):
    """The response did not have the shape the program depends on; the message names the field."""


def tls_context():
    global _WARNED
    verify = os.environ.get("TLS_VERIFY", "true").strip().lower() not in ("0", "false", "no", "off")
    if verify:
        return ssl.create_default_context()
    if not _WARNED:
        print("warning: TLS verification is OFF (TLS_VERIFY=false); acceptable for a self-signed lab CA, never for production", file=sys.stderr)
        _WARNED = True
    return ssl._create_unverified_context()


class Client:
    """One endpoint, one identity, one minter.

    mint:      a callable returning (bearer, lifetime_seconds); called on first use, on expiry, and once after a 401
    identity:  the cache key, an identity name rather than a host name: several endpoints can share one host
    cache:     an optional file path; the entry is written atomically at owner-only permissions
    """
    REFRESH_BUFFER_S = 600   # refresh proactively ten minutes before expiry; the 401 path is the safety net

    def __init__(self, host, mint, identity, api_base="", cache=None, timeout=60):
        self.host, self.mint, self.identity, self.api_base, self.cache, self.timeout = host, mint, identity, api_base, cache, timeout
        self._bearer, self._expires = None, 0.0
        self.mints = 0
        self.last_headers = []   # the names of the headers on the last answer, for the reads that carry many
        if cache and os.path.exists(cache):
            try:
                d = json.load(open(cache, encoding="utf-8")).get(identity) or {}
                self._bearer, self._expires = d.get("bearer"), float(d.get("expires", 0))
            except (OSError, ValueError):
                pass   # a cache that cannot be read is treated as absent, never rewritten blindly

    # ---- the token
    def bearer(self):
        if not self._bearer or time.time() + self.REFRESH_BUFFER_S >= self._expires:
            self._bearer, life = self.mint(); self._expires = time.time() + life; self.mints += 1
            self._persist()
        return self._bearer

    def invalidate(self):
        self._bearer, self._expires = None, 0.0

    def corrupt(self):
        """For the demo only: make the cached bearer wrong so the next call answers 401 the way an expired one would."""
        self._bearer = "expired." + (self._bearer or "x")[:12]

    def _persist(self):
        if not self.cache:
            return
        d = {}
        if os.path.exists(self.cache):
            try:
                d = json.load(open(self.cache, encoding="utf-8"))
            except (OSError, ValueError):
                d = {}
        d[self.identity] = {"bearer": self._bearer, "expires": self._expires, "written": datetime.now(timezone.utc).isoformat()}
        folder = os.path.dirname(os.path.abspath(self.cache)) or "."
        fd, tmp = tempfile.mkstemp(dir=folder, prefix=".cache-")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(d, f)
        os.chmod(tmp, 0o600); os.replace(tmp, self.cache)   # complete or absent, never half-written

    # ---- the call
    def _once(self, method, path, params, body, headers):
        url = f"https://{self.host}{self.api_base}{path}" + ("?" + urllib.parse.urlencode(params) if params else "")
        h = {"Authorization": f"Bearer {self.bearer()}", "Accept": "application/json"}
        if body is not None:
            h["Content-Type"] = "application/json"
        h.update(headers or {})
        req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None, method=method, headers=h)
        try:
            with urllib.request.urlopen(req, context=tls_context(), timeout=self.timeout) as r:
                raw = r.read(); self.last_headers = [k for k, _ in r.getheaders()]
                return r.status, (json.loads(raw) if raw else None), url
        except urllib.error.HTTPError as e:
            raw = e.read(); self.last_headers = list(e.headers.keys())
            try:
                return e.code, json.loads(raw), url
            except ValueError:
                return e.code, raw.decode(errors="replace")[:300], url

    def request(self, method, path, params=None, body=None, headers=None):
        """One call with the first guarantee: a 401 is answered by one re-mint and one retry, then it is the caller's."""
        status, data, url = self._once(method, path, params, body, headers)
        if status == 401:
            self.invalidate()
            status, data, url = self._once(method, path, params, body, headers)
        if status >= 400:
            raise ApiError(method, url, status, data)
        return data

    def get(self, path, **params):
        return self.request("GET", path, params=params or None)


# ---- the boundary
def unwrap(body, *keys):
    """The list under whichever wrapper key this API used; a shape that drifted is named, not guessed at."""
    if isinstance(body, list):
        return body
    if not isinstance(body, dict):
        raise ShapeError(f"expected an object or a list, got {type(body).__name__}")
    for k in keys or WRAPPER_KEYS:
        if isinstance(body.get(k), list):
            return body[k]
    raise ShapeError(f"no list under any of {list(keys or WRAPPER_KEYS)}; the answer's keys are {sorted(body)}")


def require(obj, spec, where="record"):
    """Validate the fields the program depends on, in one place, with a message that names the field."""
    if not isinstance(obj, dict):
        raise ShapeError(f"{where}: expected an object, got {type(obj).__name__}")
    for field, typ in spec.items():
        if field not in obj:
            raise ShapeError(f"{where}: missing field {field!r}; present: {sorted(obj)[:12]}")
        if typ is not None and not isinstance(obj[field], typ):
            raise ShapeError(f"{where}: field {field!r} is {type(obj[field]).__name__}, expected {getattr(typ, '__name__', typ)}")
    return obj


def paginate(client, path, key, *, size=100, first_page=0, page_param="page", size_param="pageSize", total_of=None, extra=None, headers=None):
    """Read a whole collection. total_of(body) returns the total the envelope declares; the walk refuses to stop short of it."""
    items, page = [], first_page
    while True:
        body = client.request("GET", path, params={page_param: page, size_param: size, **(extra or {})}, headers=headers)
        chunk = unwrap(body, key)
        items.extend(chunk)
        total = total_of(body) if total_of else None
        if not chunk or (total is not None and len(items) >= total) or (total is None and len(chunk) < size):
            break
        page += 1
        if page - first_page > 10000:
            raise ShapeError("pagination did not converge")
    if total is not None and len(items) != total:
        raise ShapeError(f"collected {len(items)} of a declared total of {total}")
    return items


# ---- the mutation
def ensure(find, create, update=None, matches=None, *, dry_run=True):
    """Find by a stable key, update if changed, create if absent; a re-run is a no-op, and a dry run sends nothing.

    find():             the existing object or None
    create():           the request that would create it: (method, path, body); sent only when dry_run is False
    update(existing):   the request that would bring it in line, or None when nothing differs
    matches(existing):  True when the existing object already matches the desired state
    """
    existing = find()
    if existing is None:
        req = create()
        return ("create", req) if dry_run else ("created", req[3](*req[:3]) if len(req) > 3 else req)
    if matches is not None and matches(existing):
        return ("unchanged", existing)
    if update is None:
        return ("exists", existing)
    req = update(existing)
    if req is None:
        return ("unchanged", existing)
    return ("update", req) if dry_run else ("updated", req[3](*req[:3]) if len(req) > 3 else req)
