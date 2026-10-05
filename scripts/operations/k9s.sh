#!/usr/bin/env bash
set -euo pipefail
set +x
umask 077
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
# shellcheck source=../lib/env.sh
source "$ROOT/scripts/lib/env.sh"
# shellcheck source=../lib/discovery.sh
source "$ROOT/scripts/lib/discovery.sh"
if [[ "${1:-}" == --help ]]; then
  printf '%s\n' 'Usage: k9s [SLOT]' \
    'Opens k9s in all namespaces of every live plane cluster. SLOT selects the first context.'
  exit 0
fi
(( $# <= 1 )) || { demo_error 'Provide at most one starting slot'; exit 1; }
start=${1:-management}
demo_load_env "$ROOT/.env"
demo_slot "$start" || exit 1

install_hint() {
  case "$1" in
    k9s) printf '%s' 'brew install k9s (https://k9scli.io/topics/install/)' ;;
    az) printf '%s' 'brew install azure-cli' ;;
    kubelogin) printf '%s' 'brew install Azure/kubelogin/kubelogin' ;;
    *) printf '%s' "brew install $1" ;;
  esac
}

tools="k9s kubectl jq"
if [[ "$DEMO_ENV" == local ]]; then tools="$tools docker kind"; else tools="$tools az kubelogin"; fi
missing=0
for tool in $tools; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    demo_status error "$tool was not found. Install it: $(install_hint "$tool")"
    missing=1
  fi
done
(( missing == 0 )) || exit 1
[[ -t 0 && -t 1 ]] || { demo_error 'planes-k9s opens an interactive UI; run it in a terminal'; exit 1; }

demo_workspace
trap demo_remove_workspace EXIT

# Print running, stopped or absent for the selected local slot's owned kind node.
node_state() {
  local host ids running
  host=$(demo_docker_host) || return
  ids=$(env -u DOCKER_CONTEXT -u DOCKER_CONFIG docker --host "$host" ps -aq --no-trunc \
    --filter "label=io.x-k8s.kind.cluster=$DEMO_CONTEXT") || return
  if [[ -z "$ids" ]]; then printf 'absent\n'; return; fi
  running=$(env -u DOCKER_CONTEXT -u DOCKER_CONFIG docker --host "$host" inspect \
    --type container --format '{{.State.Running}}' "${ids%%$'\n'*}") || return
  if [[ "$running" == true ]]; then printf 'running\n'; else printf 'stopped\n'; fi
}

if [[ "$DEMO_ENV" == azure ]]; then
  "$ROOT/.venv/bin/python" "$ROOT/scripts/operations/azure/catalog.py" --slots \
    > "$DEMO_WORKSPACE/slots"
else
  printf '%s\n' management shared-control shared-data isolated-1-control isolated-1-data \
    > "$DEMO_WORKSPACE/slots"
fi
slots=()
while IFS= read -r slot; do slots+=("$slot"); done < "$DEMO_WORKSPACE/slots"
(( ${#slots[@]} > 0 )) || { demo_error 'No plane clusters were discovered'; exit 1; }

profiles=()
start_context=''
cluster_prefix=kind-
[[ "$DEMO_ENV" == local ]] || cluster_prefix=aks-
for slot in "${slots[@]}"; do
  demo_slot "$slot"
  if [[ "$DEMO_ENV" == local ]]; then
    state=$(node_state) || exit 1
    if [[ "$state" == absent ]]; then
      demo_status progress "Skip $slot: no cluster exists"
      continue
    elif [[ "$state" != running ]]; then
      demo_status warning "Skip $slot: its kind node is stopped"
      continue
    fi
  fi
  demo_open_cluster "$slot"
  # Short display names: the selected .env already fixes the deployment, and k9s
  # reads "all" as every namespace, so each context opens like the first after :ctx.
  kubectl --kubeconfig "$DEMO_KUBECONFIG" config view --raw --output json |
    jq --arg context "$slot-plane" --arg cluster "$cluster_prefix$slot-plane" '{
      clusters: [.clusters[0] | .name = $cluster],
      users: [.users[0] | .name = $cluster],
      contexts: [.contexts[0] | .name = $context | .context.cluster = $cluster
        | .context.user = $cluster | .context.namespace = "all"]
    }' > "$DEMO_WORKSPACE/$slot.json"
  profiles+=("$DEMO_WORKSPACE/$slot.json")
  [[ "$slot" != "$start" ]] || start_context="$slot-plane"
done
[[ -n "$start_context" ]] || { demo_error "The $start cluster is not running"; exit 1; }

kubeconfig="$DEMO_WORKSPACE/kubeconfig"
jq -s --arg current "$start_context" '
  def distinct: (map(.name) | length) == (map(.name) | unique | length);
  {
    apiVersion: "v1", kind: "Config", preferences: {},
    clusters: map(.clusters[]), users: map(.users[]), contexts: map(.contexts[]),
    "current-context": $current
  }
  | if (.clusters | distinct) and (.users | distinct) and (.contexts | distinct) then .
    else error("duplicate names") end
' "${profiles[@]}" > "$kubeconfig" || { demo_error 'Plane cluster profiles collide'; exit 1; }
chmod 600 "$kubeconfig"
# Commands that k9s starts, such as edit or shell, reach only these plane clusters.
export KUBECONFIG="$kubeconfig"
demo_status success "Opening k9s on ${#profiles[@]} plane clusters; type :ctx to switch"
status=0
k9s --kubeconfig "$kubeconfig" --context "$start_context" --all-namespaces || status=$?
exit "$status"
