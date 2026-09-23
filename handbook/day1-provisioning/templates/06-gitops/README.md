# 06 - GitOps: the cluster converges on a repository

**The one new concept:** nothing about the application changes. What changes is who
applies it. Until now you ran `kubectl apply` and the cluster matched your laptop at
the moment you pressed enter. Here a controller inside the cluster watches a git
repository and makes the cluster match *that*, continuously, whether or not you are
at your desk.

That is the whole idea. Everything else in this stage is plumbing.

## Why this is the last stage and not the first

The earlier templates deploy by hand on purpose. Applying a manifest and watching
the object appear is how you learn what the manifest means, and a controller in the
way makes that loop slower and the errors less legible. Learn the imperative path
first, then hand it over.

The handover is also where the shape of the earlier stages starts to pay: the
manifests you applied in [04](../04-hybrid-3tier/) and [05](../05-microservices/)
are already plain declarative YAML with no laptop-specific state in them. That is
what makes them safe to put under a controller without rewriting.

## Before you start

You need three things beyond stage 05:

1. **A GitOps controller.** These notes use Argo CD, which is the common choice on
   VCF estates. Flux works the same way with different object names. Installing it
   is your platform team's decision and is out of scope here; it usually runs in a
   management cluster rather than in the workload cluster it manages.
2. **A git repository** the controller can read, holding the manifests from the
   earlier stages.
3. **The guest cluster registered with the controller**, which is the step worth
   reading carefully below.

## Registering the VKS cluster, and why the kubeconfig kind matters

A controller needs credentials that work at three in the morning with nobody logged
in. This is exactly the distinction
[00-reaching-the-supervisor](../../00-reaching-the-supervisor.md#for-templates-4-and-5-a-vks-guest-cluster-kubeconfig)
draws between the two VKS kubeconfigs, and it is the reason that section exists:

- The kubeconfig `vcf cluster kubeconfig get` writes authenticates through an **exec
  plugin** that shells out to an interactive login. Hand that to a controller and it
  blocks forever on a prompt no one will ever answer.
- The kubeconfig in the namespace's `<cluster>-kubeconfig` **secret** carries
  `client-certificate-data`. No prompt, no refresh. **This is the one to register.**

```bash
# the cert-based kubeconfig, read through the NAMESPACE context
vcf context use <context-name>:<namespace>:<project>
kubectl get secret <cluster>-kubeconfig -n <namespace> \
    -o go-template='{{.data.value|base64decode}}' > ~/.kube/<cluster>.kubeconfig

# register it with the controller (Argo CD's CLI reads your kubeconfig contexts)
KUBECONFIG=~/.kube/<cluster>.kubeconfig argocd cluster add <context-in-that-file>
```

## Pointing the controller at the manifests

An Argo CD `Application` is a small object that says three things: where the YAML
lives, which cluster to put it in, and how aggressively to correct drift.
[`application.yaml`](./application.yaml) is a worked example against the stage 05
manifests. Fill the repository URL, the path, and the destination, then apply it to
the cluster the **controller** runs in:

```bash
kubectl apply -f application.yaml -n argocd
```

From that moment the application is no longer something you deploy. It is something
the controller maintains.

## What "working" looks like

```bash
# the controller's view
kubectl get application -n argocd
# SYNC STATUS should read Synced, HEALTH STATUS should read Healthy

# the cluster's view, unchanged from stage 05
kubectl get pods -n onlineboutique
```

The test that makes the idea land: delete something the controller owns, and watch
it come back without you.

```bash
kubectl delete deployment frontend -n onlineboutique
kubectl get pods -n onlineboutique -w      # it is recreated
```

In stage 05 that deletion would have been permanent until you re-applied. Here the
repository is the statement of intent and the cluster is only its current rendering.

## Watch points

- **Self-healing is a setting, not a default.** `selfHeal: true` is what makes the
  deletion above come back. With it off, the controller reports the cluster as
  OutOfSync and waits for a human. Both are legitimate; production estates often run
  self-heal off in prod and on in dev.
- **The controller's permissions are now your blast radius.** It holds credentials
  that can write to the cluster continuously. Scope its project and destinations to
  what it should reach, rather than granting cluster-admin and moving on.
- **Secrets do not belong in the repository.** The manifests you moved here are
  config. Anything sensitive should arrive through a secrets operator that pulls from
  a vault at apply time, so the repository holds a reference and never a value.
- **A manual `kubectl apply` is now a lie.** Once a path is under a controller, a
  hand edit is reverted at the next sync, or worse, silently persists until someone
  else's sync reverts it. Change the repository instead.

## Where this goes next

Two directions, both beyond this series:

- **Environment promotion.** One base, one overlay per environment, and a promotion
  that is a pull request rather than a command. The same manifests you have, arranged
  so dev, staging and prod differ only by their overlay.
- **Generated Applications.** Rather than writing one `Application` per app per
  environment, a generator emits them from a list, so a new deployment becomes a new
  row rather than a new file.

---

> **Scope.** Like the rest of this series these files are meant to be read and
> adapted, not run as a proof harness. The two kubeconfig kinds and the namespace
> secret path were verified on VCF 9.1; the Argo CD object shapes follow that
> project's documented schema and will need the version your estate runs.
