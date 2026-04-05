"""MikroTik device discovery via ARP table and MNDP."""
from __future__ import annotations

import asyncio
import ipaddress
import logging
import socket
import struct
from dataclasses import dataclass

_LOGGER = logging.getLogger(__name__)

MNDP_PORT = 5678
_MNDP_PROBE = b"\x00\x00\x00\x00"

# MikroTik IEEE OUI prefixes (first 3 octets of MAC, lower-cased, colon-separated)
_MIKROTIK_OUIS: set[str] = {
    "00:0c:42",
    "04:f4:1c",
    "08:55:31",
    "18:fd:74",
    "4c:5e:0c",
    "2c:c8:1b",
    "48:8f:5a",
    "64:d1:54",
    "6c:3b:6b",
    "74:4d:28",
    "78:9a:18",
    "b4:fb:e4",
    "b8:69:f4",
    "c4:ad:34",
    "cc:2d:e0",
    "d4:01:c3",
    "d4:ca:6d",
    "dc:2c:6e",
    "e4:8d:8c",
}

# TLV type IDs used in MNDP responses
_TYPE_MAC = 1
_TYPE_IP = 5
_TYPE_IDENTITY = 11
_TYPE_BOARD = 12

# SNMP
_SNMP_PORT = 161
_SNMP_TIMEOUT = 0.5

# Minimal SNMP v2c GET request for OID 1.3.6.1.2.1.1.5.0 (sysName), community "public".
# Pre-encoded BER/DER — no external dependency needed.
#
# Structure:
#   SEQUENCE {
#     INTEGER 1               -- version v2c
#     OCTET STRING "public"   -- community
#     GetRequest-PDU {
#       INTEGER 1             -- request-id
#       INTEGER 0             -- error-status
#       INTEGER 0             -- error-index
#       SEQUENCE {            -- VarBindList
#         SEQUENCE {          -- VarBind
#           OID 1.3.6.1.2.1.1.5.0
#           NULL
#         }
#       }
#     }
#   }
_SNMP_SYSNAME_GET = bytes.fromhex(
    "3029"                  # SEQUENCE (41 bytes)
    "020101"                # INTEGER: version=1 (v2c)
    "04067075626c6963"      # OCTET STRING: "public"
    "a01c"                  # GetRequest-PDU (28 bytes)
    "020400000001"          # INTEGER: request-id=1
    "020100"                # INTEGER: error-status=0
    "020100"                # INTEGER: error-index=0
    "300e"                  # SEQUENCE: VarBindList (14 bytes)
    "300c"                  # SEQUENCE: VarBind (12 bytes)
    "06082b0601020101" "0500"  # OID 1.3.6.1.2.1.1.5.0
    "0500"                    # NULL value
)


@dataclass
class MndpDevice:
    """A MikroTik device discovered via ARP or MNDP."""

    ip: str = ""
    identity: str = ""
    board: str = ""
    mac: str = ""

    def label(self) -> str:
        """Human-readable label for UI display."""
        if self.identity:
            return f"{self.ip} ({self.identity})"
        return self.ip


def _get_default_gateway() -> str | None:
    """Return the default gateway IP from /proc/net/route, or None."""
    try:
        with open("/proc/net/route") as f:
            for line in f.readlines()[1:]:
                parts = line.split()
                if len(parts) < 3:
                    continue
                if parts[1] == "00000000" and parts[2] != "00000000":
                    gw_bytes = bytes.fromhex(parts[2])
                    return ".".join(str(b) for b in reversed(gw_bytes))
    except OSError:
        pass
    return None


def _read_arp_table() -> list[tuple[str, str]]:
    """Return (ip, mac) pairs from /proc/net/arp for MikroTik devices."""
    results: list[tuple[str, str]] = []
    try:
        with open("/proc/net/arp") as f:
            lines = f.readlines()
        # Format: IP address  HW type  Flags  HW address  Mask  Device
        for line in lines[1:]:
            parts = line.split()
            if len(parts) < 4:
                continue
            ip = parts[0]
            mac = parts[3].lower()
            flags = parts[2]
            if flags == "0x0":
                continue
            oui = mac[:8]
            if oui in _MIKROTIK_OUIS:
                results.append((ip, mac))
                _LOGGER.debug("ARP: found MikroTik at %s (%s)", ip, mac)
    except OSError:
        pass
    return results


def _parse_mndp(data: bytes) -> MndpDevice | None:
    """Parse an MNDP TLV response packet into a MndpDevice."""
    if len(data) < 4:
        return None
    # Header: 2-byte type (0x0000) + 2-byte sequence number — skip both
    offset = 4
    dev = MndpDevice()
    while offset + 4 <= len(data):
        tlv_type, tlv_len = struct.unpack_from(">HH", data, offset)
        offset += 4
        if offset + tlv_len > len(data):
            break
        value = data[offset : offset + tlv_len]
        offset += tlv_len
        if tlv_type == _TYPE_MAC and tlv_len == 6:
            dev.mac = ":".join(f"{b:02X}" for b in value)
        elif tlv_type == _TYPE_IP and tlv_len == 4:
            try:
                dev.ip = str(ipaddress.IPv4Address(value))
            except ValueError:
                pass
        elif tlv_type == _TYPE_IDENTITY:
            dev.identity = value.decode("utf-8", errors="replace")
        elif tlv_type == _TYPE_BOARD:
            dev.board = value.decode("utf-8", errors="replace")
    return dev if dev.ip else None


def _parse_snmp_sysname(data: bytes) -> str | None:
    """Extract sysName string from an SNMP GetResponse packet."""
    # Find the OID value bytes in the response, then read the next TLV as the value.
    oid_tlv = b"\x06\x08\x2b\x06\x01\x02\x01\x01\x05\x00"
    idx = data.find(oid_tlv)
    if idx == -1:
        return None
    after = idx + len(oid_tlv)
    if after + 2 > len(data):
        return None
    val_type = data[after]
    val_len = data[after + 1]
    if after + 2 + val_len > len(data):
        return None
    if val_type == 0x04:  # OCTET STRING
        return data[after + 2 : after + 2 + val_len].decode("utf-8", errors="replace").strip()
    return None


async def _snmp_sysname(loop: asyncio.AbstractEventLoop, ip: str) -> str | None:
    """Query SNMP sysName (1.3.6.1.2.1.1.5.0) with community 'public'."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setblocking(False)
        sock.sendto(_SNMP_SYSNAME_GET, (ip, _SNMP_PORT))
        data = await asyncio.wait_for(
            loop.sock_recv(sock, 1024), timeout=_SNMP_TIMEOUT
        )
        return _parse_snmp_sysname(data)
    except (asyncio.TimeoutError, OSError):
        return None
    finally:
        sock.close()


async def _mndp_unicast(loop: asyncio.AbstractEventLoop, ip: str, timeout: float) -> MndpDevice | None:
    """Send a unicast MNDP probe to *ip* and wait for a response."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setblocking(False)
        sock.sendto(_MNDP_PROBE, (ip, MNDP_PORT))
    except OSError as err:
        _LOGGER.debug("MNDP unicast to %s failed: %s", ip, err)
        return None

    try:
        data = await asyncio.wait_for(loop.sock_recv(sock, 4096), timeout=timeout)
        return _parse_mndp(data)
    except (asyncio.TimeoutError, OSError):
        return None
    finally:
        sock.close()


async def _listen_mndp_broadcast(
    loop: asyncio.AbstractEventLoop,
    found: dict[str, MndpDevice],
    timeout: float,
) -> None:
    """Listen for periodic MNDP broadcast announcements from routers."""
    broadcast_addrs: list[str] = ["255.255.255.255"]
    try:
        _tmp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        _tmp.connect(("8.8.8.8", 80))
        local_ip = _tmp.getsockname()[0]
        _tmp.close()
        parts = local_ip.split(".")
        if len(parts) == 4 and local_ip != "127.0.0.1":
            directed = f"{parts[0]}.{parts[1]}.{parts[2]}.255"
            if directed not in broadcast_addrs:
                broadcast_addrs.append(directed)
    except OSError:
        pass

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setblocking(False)
        sock.bind(("", MNDP_PORT))
        for bcast in broadcast_addrs:
            sock.sendto(_MNDP_PROBE, (bcast, MNDP_PORT))
    except OSError as err:
        _LOGGER.debug("MNDP broadcast failed: %s", err)
        return

    deadline = loop.time() + timeout
    try:
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                break
            try:
                data = await asyncio.wait_for(
                    loop.sock_recv(sock, 4096), timeout=remaining
                )
                if data == _MNDP_PROBE:
                    continue  # ignore loopback of our own probe
                dev = _parse_mndp(data)
                if dev and dev.ip not in found:
                    found[dev.ip] = dev
            except asyncio.TimeoutError:
                break
            except OSError:
                break
    finally:
        sock.close()


async def _populate_arp_table() -> None:
    """Send pings across the local subnet to populate the ARP table."""
    try:
        _tmp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        _tmp.connect(("8.8.8.8", 80))
        local_ip = _tmp.getsockname()[0]
        _tmp.close()
    except OSError:
        return

    parts = local_ip.split(".")
    if len(parts) != 4 or local_ip == "127.0.0.1":
        return

    # Build subnet scan — send UDP to common IPs to trigger ARP resolution
    base = f"{parts[0]}.{parts[1]}.{parts[2]}"
    targets = [f"{base}.{i}" for i in range(1, 255) if str(i) != parts[3]]
    _LOGGER.debug("MNDP: scanning %s.0/24 to populate ARP table", base)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setblocking(False)
    for target in targets:
        try:
            sock.sendto(b"\x00", (target, 9))
        except OSError:
            pass
    sock.close()

    # Give ARP time to resolve
    await asyncio.sleep(1.0)


async def async_scan_mndp(timeout: float = 5.0) -> list[MndpDevice]:
    """Discover MikroTik routers on the local network.

    Strategy (all run in parallel):
    1. Broadcast ping to populate ARP table with local devices
    2. Read /proc/net/arp to find MikroTik devices by OUI + unicast MNDP/SNMP probes
    3. Listen for periodic MNDP broadcast announcements from all routers on the network
    """
    loop = asyncio.get_event_loop()
    found: dict[str, MndpDevice] = {}

    # --- Populate ARP table first ---
    await _populate_arp_table()

    # --- Start broadcast listener (runs for full timeout) ---
    broadcast_task = asyncio.ensure_future(
        _listen_mndp_broadcast(loop, found, timeout)
    )

    # --- ARP table scan + unicast probes (runs in parallel with broadcast) ---
    arp_devices = _read_arp_table()
    _LOGGER.debug("MNDP: ARP table found %d MikroTik device(s)", len(arp_devices))

    arp_ips = {ip for ip, _ in arp_devices}

    gateway_ip = _get_default_gateway()
    if gateway_ip and gateway_ip not in arp_ips:
        _LOGGER.debug("MNDP: probing default gateway %s", gateway_ip)

    probe_list: list[tuple[str, str, bool]] = [
        (ip, mac, True) for ip, mac in arp_devices
    ]
    if gateway_ip and gateway_ip not in arp_ips:
        probe_list.append((gateway_ip, "", False))

    if probe_list:
        probe_timeout = min(1.0, timeout * 0.4)
        mndp_results, snmp_results = await asyncio.gather(
            asyncio.gather(
                *[_mndp_unicast(loop, ip, probe_timeout) for ip, _, _ in probe_list],
                return_exceptions=True,
            ),
            asyncio.gather(
                *[_snmp_sysname(loop, ip) for ip, _, _ in probe_list],
                return_exceptions=True,
            ),
        )
        for (ip, mac, is_known), mndp_result, snmp_result in zip(
            probe_list, mndp_results, snmp_results
        ):
            snmp_name = snmp_result if isinstance(snmp_result, str) else None
            if isinstance(mndp_result, MndpDevice):
                if not mndp_result.identity and snmp_name:
                    mndp_result.identity = snmp_name
                mndp_result.mac = mndp_result.mac or mac
                found[mndp_result.ip or ip] = mndp_result
            elif not isinstance(mndp_result, Exception) and is_known:
                found[ip] = MndpDevice(ip=ip, mac=mac, identity=snmp_name or "")
        _LOGGER.debug("MNDP: unicast probe results: %s", list(found.keys()))

    # --- Wait for broadcast listener to finish ---
    await broadcast_task

    _LOGGER.debug("MNDP scan complete: found %d device(s)", len(found))
    return list(found.values())
