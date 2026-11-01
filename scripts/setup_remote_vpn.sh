#!/bin/bash
# ==============================================================================
# Smart Assistant — Production Multi-Endpoint VPN Gateway Deployment Script
# ==============================================================================
# Target: Ubuntu 22.04 / 24.04 LTS VPS
# Purpose: Zero-install cross-network Android connection (Redmi Note 12 5G / HyperOS)
#          and native Windows 10/11 Laptop connection.
#
# Protocols:
#   1. Phone:   IKEv2/IPSec PSK with MOBIKE (RFC 4555) for seamless 5G/Wi-Fi mobility
#   2. Laptop:  L2TP/IPSec with PSK (Native Windows VPN client, split tunneling)
# Security: Strict internal isolation (10.8.0.0/24). Port 5555 strictly blocked from WAN.
# ==============================================================================

set -e

# Detect public IP if not provided as argument 1
SERVER_ENDPOINT="${1}"
if [ -z "$SERVER_ENDPOINT" ]; then
    SERVER_ENDPOINT=$(curl -s -4 ifconfig.me || curl -s -4 icanhazip.com || ip route get 1.1.1.1 | awk '{print $7}')
fi

# Generate strong cryptographic PSK if not provided as argument 2
IPSEC_PSK="${2}"
if [ -z "$IPSEC_PSK" ]; then
    IPSEC_PSK=$(openssl rand -base64 32 | tr -d '\n\r/=+' | cut -c1-32)
fi

IPSEC_ID="${3:-smart-assistant-redmi}"
LAPTOP_ID="${4:-smart-assistant-laptop}"

VPN_SUBNET="10.8.0.0/24"
VPN_PHONE_IP="10.8.0.2"
VPN_LAPTOP_IP="10.8.0.1"

echo "========================================================================"
echo "Smart Assistant Remote VPN Gateway Deployment"
echo "========================================================================"
echo "Server Endpoint : ${SERVER_ENDPOINT}"
echo "IPSec ID        : ${IPSEC_ID}"
echo "Laptop ID       : ${LAPTOP_ID}"
echo "Phone Tunnel IP : ${VPN_PHONE_IP}"
echo "Laptop Tunnel IP: ${VPN_LAPTOP_IP}"
echo "========================================================================"

# Update package lists and install strongSwan and xl2tpd
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y strongswan strongswan-pki libcharon-extra-plugins xl2tpd iptables-persistent curl

# Enable kernel IP forwarding
sysctl -w net.ipv4.ip_forward=1
sed -i 's/#net.ipv4.ip_forward=1/net.ipv4.ip_forward=1/' /etc/sysctl.conf
if ! grep -q "net.ipv4.ip_forward=1" /etc/sysctl.conf; then
    echo "net.ipv4.ip_forward=1" >> /etc/sysctl.conf
fi

# Detect public network interface
PUB_IFACE=$(ip route | grep default | awk '{print $5}' | head -n1)

# Configure strongSwan ipsec.conf
cat << EOF > /etc/ipsec.conf
config setup
    charondebug="ike 1, knl 1, cfg 0"
    uniqueids=never

conn %default
    keyexchange=ikev2
    ike=aes256-sha256-modp2048,aes256gcm16-sha256-modp2048,aes128-sha256-modp2048,aes128gcm16-sha256-modp2048,aes256-sha1-modp1024,3des-sha1-modp1024!
    esp=aes256gcm16,aes128gcm16,aes256-sha256,aes128-sha256,aes256-sha1,3des-sha1!
    dpdaction=clear
    dpddelay=30s
    dpdtimeout=120s
    mobike=yes
    fragmentation=yes

# Connection 1: Universal Android Phones (Native Android 11-15+ IKEv2/IPSec PSK Pool)
conn android-phone
    left=%any
    leftid=${SERVER_ENDPOINT}
    leftsubnet=0.0.0.0/0
    leftdns=8.8.8.8,1.1.1.1
    leftauth=psk
    right=%any
    rightid=%any
    rightsourceip=10.8.0.2-10.8.0.250
    rightauth=psk
    auto=add

# Connection 2: Windows Laptop (Native L2TP/IPSec Transport Mode with PSK)
conn windows-l2tp
    keyexchange=ikev1
    type=transport
    authby=secret
    pfs=no
    rekey=no
    keyingtries=3
    left=%any
    leftid=${SERVER_ENDPOINT}
    leftprotoport=17/1701
    right=%any
    rightprotoport=17/%any
    auto=add
EOF

# Configure ipsec.secrets with 600 permissions
cat << EOF > /etc/ipsec.secrets
: PSK "${IPSEC_PSK}"
${IPSEC_ID} : PSK "${IPSEC_PSK}"
${LAPTOP_ID} : PSK "${IPSEC_PSK}"
EOF

chmod 600 /etc/ipsec.secrets

# Configure xl2tpd for Windows Laptop connection
cat << EOF > /etc/xl2tpd/xl2tpd.conf
[global]
port = 1701

[lns default]
ip range = 10.8.0.1-10.8.0.1
local ip = 10.8.0.254
require chap = yes
refuse pap = yes
require authentication = yes
name = smart-assistant-vpn
pppoptfile = /etc/ppp/options.xl2tpd
length bit = yes
EOF

cat << EOF > /etc/ppp/options.xl2tpd
require-mschap-v2
ms-dns 8.8.8.8
ms-dns 1.1.1.1
auth
mtu 1400
mru 1400
nodefaultroute
proxyarp
silent
EOF

cat << EOF > /etc/ppp/chap-secrets
smart-assistant-laptop * "${IPSEC_PSK}" 10.8.0.1
EOF

chmod 600 /etc/ppp/chap-secrets

# Configure Firewall (iptables)
# 1. Strictly block incoming ADB port 5555 from public internet (WAN)
iptables -D INPUT -p tcp --dport 5555 -i $PUB_IFACE -j DROP 2>/dev/null || true
iptables -I INPUT 1 -p tcp --dport 5555 -i $PUB_IFACE -j DROP

# 2. Allow IKE (UDP 500), NAT-Traversal (UDP 4500), and L2TP (UDP 1701) on WAN
iptables -A INPUT -p udp --dport 500 -j ACCEPT 2>/dev/null || true
iptables -A INPUT -p udp --dport 4500 -j ACCEPT 2>/dev/null || true
iptables -A INPUT -p udp --dport 1701 -j ACCEPT 2>/dev/null || true

# 3. Allow bi-directional private communication between Phone (10.8.0.2) and Laptop (10.8.0.1)
iptables -A FORWARD -s 10.8.0.0/24 -d 10.8.0.0/24 -j ACCEPT 2>/dev/null || true
iptables -A FORWARD -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT 2>/dev/null || true

# 4. NAT Masquerade for outbound internet
iptables -t nat -A POSTROUTING -s 10.8.0.0/24 -o $PUB_IFACE -j MASQUERADE 2>/dev/null || true

# Save persistent firewall rules
netfilter-persistent save 2>/dev/null || iptables-save > /etc/iptables/rules.v4 2>/dev/null || true

# Restart strongSwan and xl2tpd services
systemctl restart strongswan-starter 2>/dev/null || systemctl restart strongswan || ipsec restart 2>/dev/null || true
systemctl restart xl2tpd 2>/dev/null || true

echo "========================================================================"
echo "strongSwan + xl2tpd Gateway Deployed Successfully!"
echo "========================================================================"
echo "Server Endpoint : ${SERVER_ENDPOINT}"
echo "IPSec ID        : ${IPSEC_ID}"
echo "Pre-Shared Key  : ${IPSEC_PSK}"
echo "Phone Virtual IP: ${VPN_PHONE_IP} (IKEv2/IPSec PSK)"
echo "Laptop Virtual IP: ${VPN_LAPTOP_IP} (L2TP/IPSec PSK)"
echo ""
echo "Paste this JSON into your assistant at instance/remote_vpn_config.json:"
echo "{"
echo "  \"vpn_server\": \"${SERVER_ENDPOINT}\","
echo "  \"vpn_type\": \"IKEv2/IPSec PSK\","
echo "  \"ipsec_identifier\": \"${IPSEC_ID}\","
echo "  \"ipsec_psk\": \"${IPSEC_PSK}\","
echo "  \"phone_virtual_ip\": \"10.8.0.2\","
echo "  \"laptop_virtual_ip\": \"10.8.0.1\","
echo "  \"virtual_subnet\": \"10.8.0.0/24\","
echo "  \"adb_remote_port\": 5555,"
echo "  \"is_configured\": true"
echo "}"
echo "========================================================================"
