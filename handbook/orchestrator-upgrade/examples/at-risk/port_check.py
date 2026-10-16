"""A reachability check written for Python 3.11. Two lines fail on the Python 3.14 that VCF 9.1.1 runs:
telnetlib and pipes left the standard library in Python 3.13, and the Python context is a dict, so
context.getToken() raises AttributeError."""
import json
import pipes
import telnetlib


def handler(context, inputs):
    host, port = inputs["host"], int(inputs.get("port", 443))
    try:
        telnetlib.Telnet(host, port, timeout=5).close()
        reachable = True
    except OSError:
        reachable = False
    token = context.getToken()
    return json.dumps({"host": pipes.quote(host), "reachable": reachable, "authenticated": bool(token)})
