// A lookup written for an older Orchestrator. The Command object was removed in 8.17, so the first two
// lines fail on any 9.x instance; java.io.File reaches a Java class the class shutter decides on; and
// the spread in the last line parses on 9.1.1 and fails on 9.1.0 (both measured), so it breaks any
// instance still on 9.1.0 that imports the package during the upgrade window.
var cmd = new Command("/usr/bin/nslookup " + hostname);
cmd.execute(true);
var out = new java.io.File("/tmp/lookup.txt");
var hosts = [...knownHosts, hostname];
System.log("hosts: " + hosts.join(", "));
