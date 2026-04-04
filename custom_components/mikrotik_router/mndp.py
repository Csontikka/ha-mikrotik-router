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


@dataclass
class MndpDevice:
    """A MikroTik device discovered via ARP or MNDP."""

    ip: str = ""
    identity: str = ""
    board: str = ""
    mac: str = ""

    def label(self) -> str:
        """Human-readable label for UI display."""
        parts: list[str] = []
        if self.identity:
            parts.append(self.identity)
        if self.ip:
            parts.append(f"({self.ip})")
        if self.board:
            parts.append(f"— {self.board}")
        return " ".join(parts) if parts else self.ip


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


async def async_scan_mndp(timeout: float = 2.0) -> list[MndpDevice]:
    """Discover MikroTik routers on the local network.

    Strategy:
    1. Read /proc/net/arp to find MikroTik devices by OUI (fast, no network I/O)
    2. For each found IP, send a unicast MNDP probe to get identity/board info
    3. Fallback: broadcast MNDP probe (works when ARP table is empty)
    """
    loop = asyncio.get_event_loop()
    found: dict[str, MndpDevice] = {}

    # --- Step 1: ARP table scan ---
    arp_devices = _read_arp_table()
    _LOGGER.debug("MNDP: ARP table found %d MikroTik device(s)", len(arp_devices))

    if arp_devices:
        # Send unicast MNDP probes in parallel to all found IPs
        probe_timeout = min(1.0, timeout * 0.6)
        tasks = [
            _mndp_unicast(loop, ip, probe_timeout)
            for ip, mac in arp_devices
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for (ip, mac), result in zip(arp_devices, results):
            if isinstance(result, MndpDevice):
                result.mac = result.mac or mac
                found[result.ip or ip] = result
            elif not isinstance(result, Exception):
                # No MNDP response but we know it's a MikroTik from ARP
                found[ip] = MndpDevice(ip=ip, mac=mac)
        _LOGGER.debug("MNDP: unicast probe results: %s", list(found.keys()))

    # --- Step 2: Broadcast fallback if ARP found nothing ---
    if not found:
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
            return []

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

    _LOGGER.debug("MNDP scan complete: found %d device(s)", len(found))
    return list(found.values())
