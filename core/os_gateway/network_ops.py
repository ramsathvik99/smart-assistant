"""
Universal OS Operations — Network Operations and System Diagnostics
Provides system-level diagnostic operations:
- Network adapters and IP configuration
- Port and listening socket inspection
- DNS lookup and connectivity tests
- Comprehensive diagnostics for "Why isn't my backend accessible?"
"""

from __future__ import annotations

import logging
import os
import socket
import subprocess
import sys
import time
import urllib.request
from typing import Any, Dict, List, Optional

import psutil

logger = logging.getLogger(__name__)


def get_network_adapters() -> Dict[str, Any]:
    """List network adapters with addresses and status."""
    adapters = []
    addrs = psutil.net_if_addrs()
    stats = psutil.net_if_stats()

    for iface_name, addr_list in addrs.items():
        st = stats.get(iface_name)
        ipv4 = []
        ipv6 = []
        mac = None

        for a in addr_list:
            if a.family == socket.AF_INET:
                ipv4.append(a.address)
            elif hasattr(socket, 'AF_INET6') and a.family == socket.AF_INET6:
                ipv6.append(a.address)
            elif hasattr(psutil, 'AF_LINK') and a.family == psutil.AF_LINK:
                mac = a.address

        adapters.append({
            "name": iface_name,
            "is_up": st.isup if st else False,
            "speed_mbps": st.speed if st else 0,
            "ipv4": ipv4,
            "ipv6": ipv6,
            "mac": mac,
        })

    return {
        "success": True,
        "status": "inspected",
        "count": len(adapters),
        "adapters": adapters,
        "message": f"Found {len(adapters)} network interfaces.",
    }


def test_connectivity(target_host: str = "8.8.8.8", timeout: float = 3.0) -> Dict[str, Any]:
    """Test network and internet connectivity."""
    start = time.time()
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        # Port 53 (DNS) on 8.8.8.8 or 80/443 on host
        port = 80 if target_host.startswith("http") or not target_host.replace(".", "").isdigit() else 53
        clean_host = target_host.replace("https://", "").replace("http://", "").split("/")[0].split(":")[0]
        sock.connect((clean_host, port))
        sock.close()
        latency = round((time.time() - start) * 1000, 2)
        return {
            "success": True,
            "status": "connected",
            "host": clean_host,
            "latency_ms": latency,
            "message": f"Connected to {clean_host} in {latency} ms.",
        }
    except Exception as exc:
        return {
            "success": False,
            "status": "disconnected",
            "host": target_host,
            "error": str(exc),
            "message": f"Could not connect to {target_host}: {exc}",
        }


def dns_lookup(hostname: str) -> Dict[str, Any]:
    """Perform a DNS lookup for a hostname."""
    try:
        clean_host = hostname.strip().replace("https://", "").replace("http://", "").split("/")[0].split(":")[0]
        ip = socket.gethostbyname(clean_host)
        return {
            "success": True,
            "status": "resolved",
            "hostname": clean_host,
            "ip_address": ip,
            "addresses": [ip],
            "message": f"Hostname '{clean_host}' resolves to {ip}.",
        }
    except Exception as exc:
        return {
            "success": False,
            "status": "error",
            "hostname": hostname,
            "error": str(exc),
            "message": f"DNS resolution failed for '{hostname}': {exc}",
        }


def diagnose_backend_issue(port: int = 8000, host: str = "127.0.0.1") -> Dict[str, Any]:
    """
    Composite diagnostic for "Why isn't my backend accessible?":
    - Checks whether any process is listening on the port
    - Checks PID and process state
    - Tests local loopback TCP connection
    - Returns structured diagnostic explanation
    """
    from core.os_gateway.process_ops import inspect_port
    port_info = inspect_port(port)

    diag_findings = []
    is_listening = port_info.get("in_use", False)

    if not is_listening:
        diag_findings.append(f"No process is listening on port {port}. The backend server is not running.")
        remedy = f"Start your backend application and verify it binds to port {port}."
    else:
        top = port_info.get("primary_listener", {})
        diag_findings.append(f"Process '{top.get('name')}' (PID: {top.get('pid')}) is actively listening on port {port}.")

        # Test connecting to localhost:port
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2.0)
            sock.connect((host, port))
            sock.close()
            diag_findings.append(f"TCP connection to {host}:{port} succeeded. The port is accepting connections.")
            remedy = f"The backend is accessible on {host}:{port}. Check if your browser/client is hitting the correct URL or path."
        except Exception as exc:
            diag_findings.append(f"Connection to {host}:{port} failed: {exc}. The process may be hung or bound exclusively to a different interface (e.g., 0.0.0.0 vs 127.0.0.1).")
            remedy = "Verify that the backend is responding and configured to accept local connections."

    summary = " ".join(diag_findings)
    return {
        "success": True,
        "status": "diagnosed",
        "port": port,
        "host": host,
        "is_listening": is_listening,
        "findings": diag_findings,
        "remedy": remedy,
        "port_info": port_info,
        "message": summary + " " + remedy,
    }
