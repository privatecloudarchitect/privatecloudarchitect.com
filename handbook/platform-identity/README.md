# platform-identity

Decode a bearer you are holding and read its two clocks. Companion to
[Platform identity](https://privatecloudarchitect.com/handbook/platform-identity).

**Offline.** No network call, no identity provider contacted, nothing written. It never prints,
logs or returns a token value: it reads the claims a JWT carries about itself.

## Why

The commonest identity failure is not a wrong token, it is a token whose clock ran out, and the
error you get back almost never names one. A platform bearer and the credential that minted it run on
two different clocks. Knowing which one expired is what decides whether you re-mint in a command or
in a console, and that is the difference between thirty seconds and an afternoon.

## Try it without an estate

`tokens.py` reads a token you already hold and sends nothing, so it needs no estate, only a token. Make an unsigned
demo token in the shell, with placeholder claims and fixed dates, and read it. This one was minted for an hour and ran
out on 2025-10-09, so the run reads both clocks and exits 1:

```bash
python3 -c 'import base64, json; p = lambda o: base64.urlsafe_b64encode(json.dumps(o).encode()).rstrip(b"=").decode(); print(p({"alg": "none", "typ": "JWT"}) + "." + p({"sub": "demo-reader", "iss": "https://broker.example.test/acs/t/CUSTOMER/", "iat": 1760000000, "exp": 1760003600}) + ".demo")' | python3 tokens.py -
```

Nothing is sent and nothing is written. The demo token carries no signature and was issued by nothing; `tokens.py`
reads claims and does not validate a signature, so it reads this one as it would a bearer you hold. It takes no
`--replay`: it sends no request, so there is nothing to replay.

## Running it

```bash
python3 tokens.py -                    # paste the bearer, then Ctrl-D: it never reaches your shell history
python3 tokens.py --file token.txt     # a bearer a pipeline already keeps in a file, mode 0600
python3 tokens.py --kubeconfig         # every kubeconfig credential, no token needed
python3 tokens.py                      # reads $TOKEN, if a tool already set it in the environment
```

Lead with `-` or `--file`. Typing `export TOKEN=<bearer>` at a prompt writes a live bearer into your shell
history, where it outlives the session it opens.

Standard library only, except `--kubeconfig`, which needs PyYAML.

| Exit | Means |
|---|---|
| 0 | the token is usable; with `--kubeconfig`, every credential of every user entry was judged and none has run out: an exec plugin with a command renews itself, and each token's, token file's and client certificate's end date was read |
| 1 | it is expired or inside the clock-skew margin; with `--kubeconfig`, a user entry whose soonest end, among every credential it holds, has passed or falls inside the margin, and this comes first |
| 3 | undetermined: it is not a JWT, or it carries no `exp` claim, so nothing here can say when it expires; with `--kubeconfig`, and none run out, a credential it could not judge, which it names (an opaque token, a certificate or token file it could not read, an exec entry that is not a plugin with a command, an auth-provider entry, a user name and password, an entry with none of these), even beside one it judged, or a kubeconfig that declares no users; or an error the script did not expect |
| 5 | a usage error: no token given, a file it cannot read, a kubeconfig it cannot read or that is not one (any file `KUBECONFIG` lists), a `KUBECONFIG` none of whose files exists, a `--file`, a kubeconfig or a token file a kubeconfig names that is open to group or other (refused unread, with the fix: `chmod 600`), PyYAML missing for `--kubeconfig`, an argument it does not take, a Python older than 3.10 |

0, 3 and 5 mean what they mean on every identity companion; 1 is this script's own finding. A token with no `exp`
exits 3 rather than 0, because a token that does not say when it dies is not known to work.

## What it tells you

| Section | Answers |
|---|---|
| Who it says you are | subject, issuer, audience, tenant, client. The **audience**, where a token carries one, is the field people skip: on the reference estate a bearer minted through the embedded Orchestrator's own sign-in was refused by the standalone Orchestrator with a 403 that reads like a permissions problem (2026-10-15). A fleet plane service JWT carries no audience: it is minted per service, so compare the service it was minted for with the one you call |
| The two clocks | `exp` minus `iat` is the **mint lifetime**, a property of the issuer's policy rather than of your token, and the number to plan a refresh cadence around. `exp` minus now is what decides whether the next call works |
| The verdict | usable, expired, or expiring inside the clock-skew margin |

Scopes are counted, never printed. The count tells you whether a token is broadly or narrowly
granted without putting the grant itself on your screen.

## The clock-skew margin

A token with forty seconds left passes every check you can write and fails the call that follows it.
`tokens.py` treats anything inside two minutes as already gone, which is the honest answer for a
credential you are about to use rather than merely inspect.

## `--kubeconfig`

Classifies every credential by whether it can renew itself, and reads the end of each one that cannot. A user entry
can hold more than one (a client certificate beside a token, a token beside an exec plugin), and which one a client
presents is not read here, so every credential of the entry is judged and the soonest end stands for it: a valid
certificate beside an expired token is an entry that has run out (exit 1).

- **exec plugin**: renews itself, possibly by prompting, which is fine at a terminal and a hang in a
  script. An `exec` entry that is not a mapping with a `command` (an `exec: null`, a string) is not a plugin anything
  can run, and is not judged.
- **client certificate**: no login at all, and an end date of its own: the run reads the certificate's
  `notAfter` (from `client-certificate-data`, or the file `client-certificate` names) and says how long it has.
  It reads the date only; it does not say the certificate is trusted.
- **static token**, inline or in a `tokenFile`: has an expiry and **nothing renews it**. This is the one that fails
  an hour after it started working.

A credential whose end cannot be read is listed as UNDETERMINED and named again under `NOT JUDGED`: an opaque token,
a token with no `exp` claim, a certificate or token file it cannot read, an `exec` entry that is not a plugin with a
command, an `auth-provider` entry, a user name and password, or an entry with none of these. A credential judged
beside it does not judge it. A token or certificate that ends inside the two-minute clock-skew margin counts as run
out here too. The run then exits 3 unless another credential has already run out, and a
kubeconfig that declares no users exits 3 as well: a run that judged nothing has nothing to pass.

It reads the file directly rather than shelling out, because `kubectl config view` redacts token
values and would report nothing at all wrong.

`KUBECONFIG` is read as kubectl reads it: a list of files, colon-delimited (semicolon-delimited on Windows), empty
names ignored, merged by user name, the first file to name a user winning; a later file's entry of the same name is
not read, and the run says how many it set aside. A file an entry names is read relative to the kubeconfig that holds
the entry. A file the list names that does not exist is named in the output and read as holding nothing; when none of
them exists, or one does not parse as a kubeconfig, the run exits 5. Without `KUBECONFIG`, it reads `~/.kube/config`.

A kubeconfig holds live credentials, so one open to group or other is refused before it is read, every file
`KUBECONFIG` lists among them, and so is a token file one of its entries names, before any of them is read: the run
prints the fix (`chmod 600` on that file), judges nothing and exits 5. A run that read it and exited 0 would say nothing is left to do while every other account on the
machine can read the credential.

## What it does not do

- It does not validate a signature. It reads claims; it does not tell you a token is authentic, and
  a decoded token is not a verified one.
- It does not read opaque tokens. Not every issuer mints a JWT, and an opaque token is not a worse
  token: it means the issuer is the only thing that knows its lifetime, which you learn from the
  issuer's documentation or by measuring when it stops working.
- It does not refresh anything. Reading and re-minting are deliberately separate, so this stays safe
  to run against a credential you did not create.
