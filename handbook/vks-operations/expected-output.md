# Expected output

Example output: what `vks.py` printed on the reference estate at 2026-10-21T23:15:17Z, on VCF 9.1.1, for one organization, signed in with a session login, read-only, for you to compare the shape of your own run against. It names no project, namespace or cluster; the record behind it is `vks.json`.

```
$ python3 vks.py
vks.py: the Kubernetes estate, read from both places it answers from

  fleet surface: 12 kind(s); 12 declare a write verb and 8 actually permit one
     kinds whose declaration promises more than the plane allows: 4
       clusterresources                   declares create,delete,deletecollection,get   allows get
       clusters                           declares create,delete,deletecollection,get   allows get
       clusterpolicyinsights              declares create,delete,deletecollection,get   allows get
       clusterpolicyschemas               declares create,delete,deletecollection,get   allows get

  fleet content: 2 cluster(s) projected, 50 managed component(s) listed
     phase=Ready state=Healthy cpu 3278m/5790m (56%) memory 3679Mi/8500Mi (43%) components=['controllerManagerHealth', 'etcdHealth', 'schedulerHealth']
     phase=Ready state=Healthy cpu 3928m/5790m (67%) memory 4527Mi/8500Mi (53%) components=['controllerManagerHealth', 'etcdHealth', 'schedulerHealth']

  declared clusters at the namespace endpoints: 2
     class=builtin-generic-v3.6.0 version=v1.35.2+vmware.1 controlPlane=1 workers=[2] variables=['bootstrapAddons', 'kubernetes', 'storageClass', 'vmClass'] phase=Provisioned
     class=builtin-generic-v3.6.0 version=v1.35.2+vmware.1 controlPlane=1 workers=[2] variables=['bootstrapAddons', 'kubernetes', 'storageClass', 'vmClass'] phase=Provisioned

  ownership: 6 machine(s) owned by {'KubeadmControlPlane': 2, 'MachineSet': 4}; 6 of 7 virtual machines carry a controller owner
  the scope check: the same list answers HTTP 403 at cluster scope and HTTP 200 under a namespace
  self-rules: org gateway 153 rules (incomplete=False); namespace endpoint 198 rules (incomplete=True)
```

The projection can read a cluster at `phase=ReadyToAttach state=Unknown`, with no capacity figures and no etcd health entry, while the declared cluster reads `Provisioned`: earlier the same evening on the reference estate, one read of three did, and the reads either side found both clusters Ready and Healthy. Read the projection twice before acting on Unknown.
