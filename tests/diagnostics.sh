#!/usr/bin/env bash
set -euo pipefail

# $1 = prometheus unit name, e.g. prom/0

if [[ $# -ne 1 ]]; then
  echo "Invalid number of arguments."
  echo "Usage:   diagnostics prom/0"
  return 1
fi

UNIT="$1"

# The following commented out two checks won't work with ingress because of the path

#echo "Checking reachability via localhost"
#juju ssh "$UNIT" curl localhost:9090/-/ready
#
#echo
#
#echo "Checking reachability via pod ip"
#POD_IP="$(juju status --format json | jq -r ".applications[].units.\"$UNIT\".address" | grep -v 'null')"
#echo "Pod IP: $POD_IP"
#curl "$POD_IP:9090/-/ready"
#
#echo

echo "Checking reachability via external URL"
API_ENDPOINT=$(juju exec --unit "$UNIT" -- PEBBLE_SOCKET=/charm/containers/prometheus/pebble.socket pebble plan | grep -oP -- '--web.external-url=\K[^ ]+')
echo "External URL: $API_ENDPOINT"
# Need to use juju ssh because if the external url is the fqdn, it won't be reachable from the host
juju ssh "$UNIT" curl "$API_ENDPOINT/-/ready"

echo

echo "Alert rules present from the following juju_applications:"
juju ssh "$UNIT" curl -s "$API_ENDPOINT/api/v1/rules" | jq | grep -oP -- '"juju_application": "\K[^"]+' | sort | uniq

echo

echo "Metrics present from the following 'metrics groups':"
juju ssh "$UNIT" curl -s --data-urlencode 'match[]={__name__=~\".+\"}' "$API_ENDPOINT/api/v1/series" | jq -r '.data[].__name__' | cut -d'_' -f1 | sort | uniq | tr '\n' ','
echo
