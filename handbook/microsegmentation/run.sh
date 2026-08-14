#!/usr/bin/env bash
# run.sh - the firewall-policy round-trip, exactly as the sheet teaches it:
#   land the rule DISABLED -> verify Realized -> review the one-field diff ->
#   flip the enable -> verify Realized -> tear down.
#
# Prereqs (same as the isolation-design harness):
#   - kubectl context "vcfa-cci" pointing at https://<vcfa-fqdn>/cci/kubernetes
#     with an org-admin SESSION token (see README for the 3-line recipe).
#   - VCFA_REGION set to your region name (kubectl get regions shows it).
#
# Environment:
#   VCFA_REGION    (required)  region name substituted into the manifests
#   VCFA_CONTEXT   (optional)  kubectl context name, default vcfa-cci
#   KEEP=1         (optional)  skip teardown, leave the objects for inspection
#
# Two gateway behaviors this script is built around (details in the README):
#   - Server-side DRY-RUN is NOT dry for vpc.nsx kinds here: it persists the
#     object. There is deliberately no dry-run step; the review gate is the
#     disabled flag plus read-back, not a preview flag.
#   - The gateway does not persist Kubernetes field managers, so every apply
#     over an EXISTING vpc.nsx object reports a conflict with
#     "before-first-apply". --force-conflicts is therefore the standard update
#     idiom on this plane, not an override of another owner.
#
# Safety: the rule ships disabled, the group has no members, and the section's
# appliedTo is scoped to that empty group, so no traffic on your estate changes
# at any step. Teardown removes both objects; the estate ends as it began.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CTX="${VCFA_CONTEXT:-vcfa-cci}"
REGION="${VCFA_REGION:?set VCFA_REGION to your region name (kubectl get regions)}"

k() { kubectl --context "$CTX" "$@"; }

step()  { printf "\n== %s\n" "$*"; }
ok()    { printf "   OK: %s\n" "$*"; }
fail()  { printf "   FAIL: %s\n" "$*"; exit 1; }

# Substitute the region placeholder into a working copy (no-op if you already
# edited the manifests directly).
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
for f in 10-group.yaml 20-policy-disabled.yaml 21-policy-enabled.yaml; do
  sed "s/<your-region>/$REGION/" "$HERE/manifests/$f" > "$WORK/$f"
done

wait_realized() { # kind name timeout_s
  local kind="$1" name="$2" timeout="${3:-60}" elapsed=0 s
  while [ "$elapsed" -lt "$timeout" ]; do
    s="$(k get "$kind" "$name" -o jsonpath='{.status.conditions[?(@.type=="Realized")].status}' 2>/dev/null || true)"
    if [ "$s" = "True" ]; then ok "$kind/$name Realized"; return 0; fi
    sleep 3; elapsed=$((elapsed + 3))
  done
  fail "$kind/$name did not reach Realized within ${timeout}s (last status: '${s:-none}')"
}

step "1. Create the group the rule will speak"
k apply --server-side --force-conflicts -f "$WORK/10-group.yaml"
wait_realized networksecuritygroup seg-proof-app

step "2. Land the section DISABLED (the reviewable document)"
k apply --server-side --force-conflicts -f "$WORK/20-policy-disabled.yaml"
wait_realized firewallpolicy seg-proof-section
DISABLED="$(k get firewallpolicy seg-proof-section -o jsonpath='{.spec.rules[0].disabled}')"
[ "$DISABLED" = "true" ] && ok "rule is disabled, section is Realized: reviewed in place, altering nothing" \
                         || fail "expected rules[0].disabled=true, got '$DISABLED'"

step "3. The change under review is ONE field (diff of the two documents)"
diff "$WORK/20-policy-disabled.yaml" "$WORK/21-policy-enabled.yaml" || true

step "4. Flip the enable (the change that alters traffic is one auditable field)"
k apply --server-side --force-conflicts -f "$WORK/21-policy-enabled.yaml"
wait_realized firewallpolicy seg-proof-section
DISABLED="$(k get firewallpolicy seg-proof-section -o jsonpath='{.spec.rules[0].disabled}')"
[ "$DISABLED" = "false" ] && ok "rule is enabled and the section re-Realized" \
                          || fail "expected rules[0].disabled=false, got '$DISABLED'"

step "5. Read the section back the way an auditor would"
k get firewallpolicy seg-proof-section
printf "   note: the LIST view trims rules[]; 'kubectl get firewallpolicy seg-proof-section -o yaml' shows the full rule grammar\n"

if [ "${KEEP:-0}" = "1" ]; then
  step "KEEP=1: leaving seg-proof-section + seg-proof-app in place"
  exit 0
fi

step "6. Teardown (policy first, then the group it references)"
k delete firewallpolicy seg-proof-section
k delete networksecuritygroup seg-proof-app
ok "estate as it began"

printf "\nRound-trip complete: land disabled -> Realized -> one-field enable -> Realized -> teardown.\n"
