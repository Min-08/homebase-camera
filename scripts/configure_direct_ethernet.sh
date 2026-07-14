#!/usr/bin/env bash
set -Eeuo pipefail

DEVICE="eth0"
DIRECT_CIDR="192.168.250.2/24"
DIRECT_IP="${DIRECT_CIDR%/*}"
DISPATCHER_PATH="/etc/NetworkManager/dispatcher.d/90-homebase-direct-address"
BACKUP_DIR="/var/lib/homebase-camera/network-backups"
ACTION="${1:-install}"

if [[ "$ACTION" != "install" && "$ACTION" != "--remove" ]]; then
  echo "Usage: sudo ./scripts/configure_direct_ethernet.sh [--remove]" >&2
  exit 2
fi

if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
  exec sudo "$0" "$@"
fi

command -v nmcli >/dev/null 2>&1 || {
  echo "NetworkManager(nmcli)가 필요합니다." >&2
  exit 1
}
command -v ip >/dev/null 2>&1 || {
  echo "iproute2의 ip 명령이 필요합니다." >&2
  exit 1
}

CONNECTION="$(nmcli -g GENERAL.CONNECTION device show "$DEVICE" 2>/dev/null || true)"
if [[ -z "$CONNECTION" || "$CONNECTION" == "--" ]]; then
  CONNECTION="$(nmcli -t -f NAME,TYPE connection show | awk -F: '$2 == "802-3-ethernet" {print $1; exit}')"
fi
[[ -n "$CONNECTION" ]] || {
  echo "$DEVICE 유선 연결 프로필을 찾지 못했습니다." >&2
  exit 1
}

if [[ "$ACTION" == "--remove" ]]; then
  rm -f "$DISPATCHER_PATH"
  ip address delete "$DIRECT_CIDR" dev "$DEVICE" >/dev/null 2>&1 || true
  nmcli connection modify "$CONNECTION" ipv4.link-local default
  nmcli connection modify "$CONNECTION" -ipv4.addresses "$DIRECT_CIDR" >/dev/null 2>&1 || true
  nmcli device reapply "$DEVICE" >/dev/null 2>&1 || true
  echo "Homebase Ethernet 직결 주소를 제거했습니다."
  exit 0
fi

install -d -m 0755 "$BACKUP_DIR" "$(dirname "$DISPATCHER_PATH")"
nmcli connection show "$CONNECTION" > "$BACKUP_DIR/${CONNECTION// /_}-$(date +%Y%m%d-%H%M%S).txt"

# DHCP 주소는 그대로 사용하고, DHCP가 없는 직결 링크도 활성화되도록 IPv4LL을 허용합니다.
nmcli connection modify "$CONNECTION" ipv4.link-local enabled
nmcli connection modify "$CONNECTION" -ipv4.addresses "$DIRECT_CIDR" >/dev/null 2>&1 || true

cat > "$DISPATCHER_PATH" <<EOF
#!/bin/sh

if [ "\${1:-}" != "$DEVICE" ]; then
  exit 0
fi

case "\${2:-}" in
  pre-up|up|dhcp4-change|reapply)
    /usr/sbin/ip address replace "$DIRECT_CIDR" dev "$DEVICE"
    ;;
esac
EOF
chmod 0755 "$DISPATCHER_PATH"

nmcli device reapply "$DEVICE" >/dev/null 2>&1 || true
"$DISPATCHER_PATH" "$DEVICE" up

if ! ip -4 address show dev "$DEVICE" | grep -Fq "$DIRECT_CIDR"; then
  echo "직결 주소 $DIRECT_CIDR 적용에 실패했습니다." >&2
  exit 1
fi

cat <<EOF
Homebase Ethernet 직결 설정 완료

Raspberry Pi: $DIRECT_IP
Windows PC:   192.168.250.1
서브넷 마스크: 255.255.255.0
게이트웨이/DNS: 비워 둠

RealVNC Viewer: $DIRECT_IP
대시보드: http://$DIRECT_IP:8501/
EOF
