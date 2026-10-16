"""The same check on any Python 3: socket replaces telnetlib, shlex.quote replaces pipes.quote, and
getToken is read as the key it is."""
import json
import shlex
import socket


def handler(context, inputs):
    host, port = inputs["host"], int(inputs.get("port", 443))
    try:
        socket.create_connection((host, port), timeout=5).close()
        reachable = True
    except OSError:
        reachable = False
    token = context["getToken"]()
    return json.dumps({"host": shlex.quote(host), "reachable": reachable, "authenticated": bool(token)})
