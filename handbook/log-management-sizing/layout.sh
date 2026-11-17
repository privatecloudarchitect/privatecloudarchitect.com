#!/bin/sh
# layout.sh: read how Log Management is laid out on a VCF services runtime. Read-only: kubectl get, nothing else.
# Run it on a control plane node of the runtime, as root, with KUBECONFIG=/etc/kubernetes/admin.conf.
# It prints counts, sizes and one version only: no node name, pod suffix or address.
# A read that fails prints "could not read" on its line and the script goes on; it never prints a failure as a count.
export KUBECONFIG="${KUBECONFIG:-/etc/kubernetes/admin.conf}"
NS=ops-logs
q() { out=$("$@" 2>/dev/null) || { echo "could not read"; return 1; }; echo "$out"; }
echo "read at $(date -u +%Y-%m-%dT%H:%M:%SZ)"
IMG=$(q kubectl -n $NS get statefulset log-store -o jsonpath='{.spec.template.spec.containers[0].image}') && echo "log store image tag: ${IMG##*:}" || echo "log store image tag: could not read"
# role by taint, the one test used everywhere below: a control plane node carries the control-plane taint
NODES=$(q kubectl get nodes -o jsonpath='{range .items[*]}{.status.capacity.cpu}|{.status.capacity.memory}|{.spec.taints[*].key}{"\n"}{end}')
if [ "$NODES" = "could not read" ]; then echo "nodes: could not read"; else
  echo "$NODES" | awk -F'|' 'NF{if($3 ~ /control-plane/)c++; else w++} END{printf "nodes: %d control plane, %d workers\n", c, w}'
  echo "$NODES" | awk -F'|' 'NF{role=($3 ~ /control-plane/)?"control plane":"worker"; m=$2; gsub(/Ki/,"",m); printf "%s, %s vCPU %d GiB\n", role, $1, m/1048576+0.5}' | sort | uniq -c | awk '{n=$1; $1=""; printf "node size: %s x%s\n", n, $0}'
  echo "workers carrying a taint: $(echo "$NODES" | awk -F'|' 'NF && $3 !~ /control-plane/ && $3 != ""{n++} END{print n+0}')"
fi
# every container of the pod template is summed, so a sidecar is counted
for s in log-store log-processor; do
  R=$(q kubectl -n $NS get statefulset $s -o jsonpath='{.status.readyReplicas}|{.spec.template.spec.containers[*].name}|{.spec.template.spec.containers[*].resources.requests.cpu}|{.spec.template.spec.containers[*].resources.requests.memory}')
  if [ "$R" = "could not read" ]; then echo "$s: could not read"; else
    echo "$R" | awk -F'|' -v s="$s" '{n=split($2,c," "); printf "%s: %s ready, %d container(s), requests cpu %s memory %s\n", s, ($1==""?0:$1), n, $3, $4}'
  fi
done
PODS=$(q kubectl -n $NS get pods --no-headers -o custom-columns=P:.metadata.name,N:.spec.nodeName)
if [ "$PODS" = "could not read" ]; then echo "replica pods on distinct workers: could not read"; else
  echo "replica pods on distinct workers: $(echo "$PODS" | awk '$1 ~ /^log-(store|processor)-/{print $2}' | sort -u | awk 'END{print NR}') of $(echo "$PODS" | awk '$1 ~ /^log-(store|processor)-/{n++} END{print n+0}') pods"
fi
# any pod autoscaler, in any namespace, whose target is the log store or the log processor
HPA=$(q kubectl get hpa -A --no-headers -o custom-columns=T:.spec.scaleTargetRef.name)
if [ "$HPA" = "could not read" ]; then echo "pod autoscalers targeting the log store or log processor: could not read"; else
  echo "pod autoscalers targeting the log store or log processor: $(echo "$HPA" | awk '$1=="log-store"||$1=="log-processor"{n++} END{print n+0}') (of $(echo "$HPA" | awk 'NF{n++} END{print n+0}') in the cluster)"
fi
GW=$(q kubectl get pods -A --no-headers -o custom-columns=P:.metadata.name,C:.spec.containers[*].resources.requests.cpu,M:.spec.containers[*].resources.requests.memory)
if [ "$GW" = "could not read" ]; then echo "gateway pods: could not read"; else
  echo "$GW" | awk '$1 ~ /^ops-logs-gateway/{n++; c=$2; m=$3} END{if(n) printf "gateway pods: %d, requests cpu %s memory %s\n", n, c, m; else print "gateway pods: 0"}'
fi
POOL=$(q kubectl get inclusterippools -A -o jsonpath='{range .items[*]}{.status.ipAddresses.total}|{.status.ipAddresses.used}|{.status.ipAddresses.free}{"\n"}{end}')
if [ "$POOL" = "could not read" ]; then echo "node address pools: could not read"; else
  echo "$POOL" | awk -F'|' 'NF{n++; t+=$1; u+=$2; f+=$3} END{printf "node address pools: %d, %d addresses, %d in use, %d free\n", n, t, u, f}'
fi
CA=$(q kubectl get deploy -A --no-headers -o custom-columns=N:.metadata.name)
if [ "$CA" = "could not read" ]; then echo "cluster autoscaler deployments: could not read"; else
  echo "cluster autoscaler deployments: $(echo "$CA" | awk '$1 ~ /cluster-autoscaler/{n++} END{print n+0}')"
fi
