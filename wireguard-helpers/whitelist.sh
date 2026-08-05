#!/bin/sh
set -euo pipefail

cmd() {
  echo "[# wl] $* ${EXTRA-}" >&2
  eval '"$@"' "${EXTRA-}"
}

whitelist() {
  local ip_ver="$1"
  local addresses="$2"

  local vpn_route=$(ip $ip_ver route show table $table | sed -n 's/default //p')

  cmd ip $ip_ver route del default $vpn_route table $table

  if [ "$addresses" != "" ]; then
    local addr
    for addr in $addresses; do
      cmd ip $ip_ver route add $addr $vpn_route table $table
    done
  fi
}


table=$(wg show "$2" fwmark)

if [ "$1" = "up" ]; then
  whitelist -4 "${3-}"
  whitelist -6 "${4-}"

elif [ "$1" = "down" ]; then
  # no need to do anything
  # leaving this for past and maybe future scripts
  true
else
  EXTRA="# unknown command $1" cmd exit 1
fi

cmd exit "$?"
