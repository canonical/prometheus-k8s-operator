#!/usr/bin/env bash
set -euo pipefail

# $1 = prometheus unit name, e.g. prom/0

if [[ $# -ne 1 ]]; then
  echo "Invalid number of arguments."
  echo "Usage:   diagnostics prom/0"
  return 1
fi

UNIT=$1
API_ENDPOINT=$(juju exec --unit $UNIT -- PEBBLE_SOCKET=/charm/containers/prometheus/pebble.socket pebble plan | grep -oP -- '--web.external-url=\K[^ ]+')

echo "Alert rules present from the following juju_applications:"
curl -s "$API_ENDPOINT/api/v1/rules" | jq | grep -oP -- '"juju_application": "\K[^"]+' | sort | uniq

echo

echo "Metrics present from the following 'metrics groups':"
curl -s --data-urlencode 'match[]={__name__=~".+"}' "$API_ENDPOINT/api/v1/series" | jq -r '.data[].__name__' | cut -d'_' -f1 | sort | uniq | tr '\n' ','
echo
