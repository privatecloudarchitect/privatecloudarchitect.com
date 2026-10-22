# Expected output

What `vip.py` printed on the reference estate at 2026-10-22T01:03:37Z: the workload Avi controller, a session login, GETs only. It exited 0: every pool holds a member. Every object name is a placeholder in `vip.json` and none is printed.

```
$ python3 vip.py
vip.py: the load-balancer graph behind a control-plane endpoint

  graph: 7 virtual service(s), 7 address object(s), 7 policy set(s), 9 pool(s)
     virtual services carrying a DIRECT pool reference: 0
     every one reaches its pools through a policy set instead; 9 selection rule(s) in total
     ports [443, 6443]    -> 2 pool(s), members [3, 3]
     ports [443]          -> 1 pool(s), members [3]
     ports [10093]        -> 1 pool(s), members [1]
     ports [53]           -> 2 pool(s), members [3, 3]
     ports [5000]         -> 1 pool(s), members [3]
     ports [443]          -> 1 pool(s), members [1]
     ports [443]          -> 1 pool(s), members [1]

  arithmetic: 9 pools; 9 of them are selected by a policy set rule; reconciles
  membership now: {1: 3, 3: 6} (pool size -> how many pools). Empty pools: 0
     a control-plane pool is created empty, before any node exists; a populated one is the end of that story, and only the controller's event log shows the beginning
  addresses: 7 address object(s) holding 7 address(es), 7 allocated
```
