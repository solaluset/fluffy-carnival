set -e

table=$(printf '%d' $(wg show "$2" fwmark))

cmd() {
  echo "[# wl] $* $EXTRA" >&2
  eval '"$@"' "$EXTRA"
}

whitelist() {
  local ip_ver="$1"
  local addresses="$2"

  local vpn_route=$(ip $ip_ver route show table $table | sed -n 's/default //p')
  local main_route=$(ip $ip_ver route show table main | grep '^default ')

  cmd ip $ip_ver route del default $vpn_route table $table
  if [ -n "$main_route" ]; then
    cmd ip $ip_ver route add $main_route table $table
  fi
  local addr
  for addr in $addresses; do
    cmd ip $ip_ver route add $addr $vpn_route table $table
  done
}


if [ "$1" = "up" ]; then
  whitelist -4 "$3"
  whitelist -6 "$4"

elif [ "$1" = "down" ]; then
  for ip_ver in -4 -6; do
    EXTRA="2>/dev/null || true" cmd ip $ip_ver route del default table $table
  done
fi
