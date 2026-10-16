"""Name resolution for lookup_host.js: the Python action that replaces the removed Command object."""
import json
import socket


def handler(context, inputs):
    infos = socket.getaddrinfo(inputs["hostname"], None)
    return json.dumps(sorted({info[4][0] for info in infos}))
