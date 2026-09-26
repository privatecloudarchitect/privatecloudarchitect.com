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

## Running it

```bash
export TOKEN='<a bearer you already hold>'
python tokens.py

python tokens.py --file token.txt      # from a file
cat token.txt | python tokens.py -     # from stdin
python tokens.py --kubeconfig          # every kubeconfig credential, no token needed
```

Standard library only, except `--kubeconfig`, which needs PyYAML.

Exit code: `0` the token is usable, `1` it is expired or inside the clock-skew margin, `2` nothing
could be read.

## What it tells you

| Section | Answers |
|---|---|
| Who it says you are | subject, issuer, audience, tenant, client. The **audience** is the one people skip: a token minted for one appliance is refused by another with a 403 that reads like a permissions problem |
| The two clocks | `exp` minus `iat` is the **mint lifetime**, a property of the issuer's policy rather than of your token, and the number to plan a refresh cadence around. `exp` minus now is what decides whether the next call works |
| The verdict | usable, expired, or expiring inside the clock-skew margin |

Scopes are counted, never printed. The count tells you whether a token is broadly or narrowly
granted without putting the grant itself on your screen.

## The clock-skew margin

A token with forty seconds left passes every check you can write and fails the call that follows it.
`tokens.py` treats anything inside two minutes as already gone, which is the honest answer for a
credential you are about to use rather than merely inspect.

## `--kubeconfig`

Classifies every credential by whether it can renew itself:

- **exec plugin**: renews itself, possibly by prompting, which is fine at a terminal and a hang in a
  script.
- **client certificate**: no login at all. These commonly outlive every token around them.
- **static token**: has an expiry and **nothing renews it**. This is the one that fails an hour
  after it started working.

It reads the file directly rather than shelling out, because `kubectl config view` redacts token
values and would report nothing at all wrong.

## What it does not do

- It does not validate a signature. It reads claims; it does not tell you a token is authentic, and
  a decoded token is not a verified one.
- It does not read opaque tokens. Not every issuer mints a JWT, and an opaque token is not a worse
  token: it means the issuer is the only thing that knows its lifetime, which you learn from the
  issuer's documentation or by measuring when it stops working.
- It does not refresh anything. Reading and re-minting are deliberately separate, so this stays safe
  to run against a credential you did not create.
