// The same lookup without the Command object: name resolution moves into a Python action
// (resolve_host.py beside this file), which JavaScript calls by module path like any other action. No
// Java class, and concat in place of spread, which every measured engine accepts.
var addresses = System.getModule("com.example.network").resolve_host(hostname);
var hosts = knownHosts.concat([hostname]);
System.log("hosts: " + hosts.join(", ") + "; addresses: " + addresses);
