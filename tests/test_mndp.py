"""Tests for MNDP discovery module."""

from __future__ import annotations

import asyncio
import socket as real_socket
import struct
from unittest.mock import MagicMock, mock_open, patch

import pytest

from custom_components.mikrotik_extended.mndp import (
    _MNDP_PROBE,
    MNDP_PORT,
    MndpDevice,
    _get_default_gateway,
    _listen_mndp_broadcast,
    _mndp_unicast,
    _parse_mndp,
    _parse_snmp_sysname,
    _populate_arp_table,
    _read_arp_table,
    _snmp_sysname,
    async_scan_mndp,
)

# ---------------------------------------------------------------------------
# Helpers for building canned byte sequences
# ---------------------------------------------------------------------------


def _tlv(tlv_type: int, value: bytes) -> bytes:
    return struct.pack(">HH", tlv_type, len(value)) + value


def _make_mndp_packet(
    *,
    mac: bytes | None = b"\x00\x0c\x42\x11\x22\x33",
    ip: bytes | None = b"\xc0\xa8\x58\x01",
    identity: bytes | None = b"MyRouter",
    board: bytes | None = b"RB750",
    extra: bytes = b"",
    header: bytes = b"\x00\x00\x00\x01",
) -> bytes:
    """Build a synthetic MNDP packet."""
    pkt = header
    if mac is not None:
        pkt += _tlv(1, mac)
    if ip is not None:
        pkt += _tlv(5, ip)
    if identity is not None:
        pkt += _tlv(11, identity)
    if board is not None:
        pkt += _tlv(12, board)
    pkt += extra
    return pkt


# ---------------------------------------------------------------------------
# MndpDevice.label
# ---------------------------------------------------------------------------


def test_mndp_device_label_with_identity() -> None:
    dev = MndpDevice(ip="10.0.0.1", identity="Core")
    assert dev.label() == "10.0.0.1 (Core)"


def test_mndp_device_label_without_identity() -> None:
    dev = MndpDevice(ip="10.0.0.1")
    assert dev.label() == "10.0.0.1"


# ---------------------------------------------------------------------------
# _get_default_gateway
# ---------------------------------------------------------------------------


def test_get_default_gateway_found() -> None:
    # 0100A8C0 little-endian -> 192.168.0.1
    route_contents = "Iface\tDestination\tGateway\tFlags\tRefCnt\tUse\tMetric\tMask\tMTU\tWindow\tIRTT\neth0\t00000000\t0100A8C0\t0003\t0\t0\t0\t00000000\t0\t0\t0\n"
    with patch(
        "custom_components.mikrotik_extended.mndp.open",
        mock_open(read_data=route_contents),
        create=True,
    ):
        assert _get_default_gateway() == "192.168.0.1"


def test_get_default_gateway_no_default_route() -> None:
    route_contents = "Iface\tDestination\tGateway\tFlags\neth0\t0100A8C0\t00000000\t0001\n"
    with patch(
        "custom_components.mikrotik_extended.mndp.open",
        mock_open(read_data=route_contents),
        create=True,
    ):
        assert _get_default_gateway() is None


def test_get_default_gateway_short_line_skipped() -> None:
    route_contents = "header\nshort\neth0\t00000000\t0100A8C0\t0003\n"
    with patch(
        "custom_components.mikrotik_extended.mndp.open",
        mock_open(read_data=route_contents),
        create=True,
    ):
        assert _get_default_gateway() == "192.168.0.1"


def test_get_default_gateway_oserror() -> None:
    with patch(
        "custom_components.mikrotik_extended.mndp.open",
        side_effect=OSError("nope"),
        create=True,
    ):
        assert _get_default_gateway() is None


# ---------------------------------------------------------------------------
# _read_arp_table
# ---------------------------------------------------------------------------


def test_read_arp_table_finds_mikrotik() -> None:
    arp = (
        "IP address       HW type     Flags       HW address            Mask     Device\n"
        "192.168.88.1     0x1         0x2         00:0C:42:AA:BB:CC     *        eth0\n"
        "192.168.88.2     0x1         0x2         AA:BB:CC:DD:EE:FF     *        eth0\n"
        "192.168.88.3     0x1         0x0         00:0C:42:11:22:33     *        eth0\n"
        "short line\n"
    )
    with patch(
        "custom_components.mikrotik_extended.mndp.open",
        mock_open(read_data=arp),
        create=True,
    ):
        result = _read_arp_table()
    assert result == [("192.168.88.1", "00:0c:42:aa:bb:cc")]


def test_read_arp_table_oserror() -> None:
    with patch(
        "custom_components.mikrotik_extended.mndp.open",
        side_effect=OSError,
        create=True,
    ):
        assert _read_arp_table() == []


# ---------------------------------------------------------------------------
# _parse_mndp
# ---------------------------------------------------------------------------


def test_parse_mndp_full_packet() -> None:
    pkt = _make_mndp_packet()
    dev = _parse_mndp(pkt)
    assert dev is not None
    assert dev.ip == "192.168.88.1"
    assert dev.mac == "00:0C:42:11:22:33"
    assert dev.identity == "MyRouter"
    assert dev.board == "RB750"


def test_parse_mndp_too_short_header() -> None:
    assert _parse_mndp(b"\x00\x01") is None


def test_parse_mndp_no_ip_returns_none() -> None:
    pkt = b"\x00\x00\x00\x01" + _tlv(11, b"JustIdentity")
    assert _parse_mndp(pkt) is None


def test_parse_mndp_truncated_tlv_value() -> None:
    # TLV claims length 10 but only 2 bytes follow — loop breaks
    pkt = b"\x00\x00\x00\x01" + struct.pack(">HH", 11, 10) + b"AB"
    assert _parse_mndp(pkt) is None


def test_parse_mndp_wrong_mac_length_ignored() -> None:
    pkt = (
        b"\x00\x00\x00\x01"
        + _tlv(1, b"\x00\x0c\x42")  # bad MAC length
        + _tlv(5, b"\x0a\x00\x00\x01")
    )
    dev = _parse_mndp(pkt)
    assert dev is not None
    assert dev.ip == "10.0.0.1"
    assert dev.mac == ""


def test_parse_mndp_invalid_ip_suppressed() -> None:
    # Force ValueError path: 3-byte "IP"
    pkt = (
        b"\x00\x00\x00\x01"
        + _tlv(5, b"\xc0\xa8\x01")  # wrong length -> skipped by length check
        + _tlv(5, b"\x0a\x00\x00\x02")
    )
    dev = _parse_mndp(pkt)
    assert dev is not None
    assert dev.ip == "10.0.0.2"


def test_parse_mndp_unknown_tlv_ignored() -> None:
    pkt = b"\x00\x00\x00\x01" + _tlv(5, b"\x0a\x00\x00\x05") + _tlv(99, b"whatever")
    dev = _parse_mndp(pkt)
    assert dev is not None
    assert dev.ip == "10.0.0.5"


# ---------------------------------------------------------------------------
# _parse_snmp_sysname
# ---------------------------------------------------------------------------


_OID = b"\x06\x08\x2b\x06\x01\x02\x01\x01\x05\x00"


def test_parse_snmp_sysname_success() -> None:
    name = b"MyRouter"
    data = b"\x30\x20" + _OID + b"\x04" + bytes([len(name)]) + name
    assert _parse_snmp_sysname(data) == "MyRouter"


def test_parse_snmp_sysname_no_oid() -> None:
    assert _parse_snmp_sysname(b"no oid here at all") is None


def test_parse_snmp_sysname_truncated_no_value_header() -> None:
    # OID present but no room for type+len bytes
    data = _OID  # nothing after
    assert _parse_snmp_sysname(data) is None


def test_parse_snmp_sysname_truncated_value() -> None:
    # val_len = 10 but only 2 bytes follow
    data = _OID + b"\x04\x0a" + b"AB"
    assert _parse_snmp_sysname(data) is None


def test_parse_snmp_sysname_wrong_type() -> None:
    data = _OID + b"\x02\x04" + b"\x00\x00\x00\x05"
    assert _parse_snmp_sysname(data) is None


def test_parse_snmp_sysname_strips_whitespace() -> None:
    name = b"  Trim  "
    data = _OID + b"\x04" + bytes([len(name)]) + name
    assert _parse_snmp_sysname(data) == "Trim"


# ---------------------------------------------------------------------------
# _snmp_sysname (async)
# ---------------------------------------------------------------------------


class _FakeSock:
    """Minimal fake socket to exercise _snmp_sysname / _mndp_unicast paths."""

    def __init__(self, *, send_raises: bool = False) -> None:
        self.closed = False
        self.sent: list[tuple[bytes, tuple[str, int]]] = []
        self.setblocking_called = False
        self._send_raises = send_raises
        self.setsockopt_calls: list[tuple] = []
        self.bind_args: tuple | None = None
        self.connect_args: tuple | None = None
        self.getsockname_return = ("192.168.1.50", 12345)

    def setblocking(self, flag: bool) -> None:
        self.setblocking_called = True

    def setsockopt(self, *args) -> None:
        self.setsockopt_calls.append(args)

    def sendto(self, data: bytes, addr: tuple[str, int]) -> None:
        if self._send_raises:
            raise OSError("sendto failed")
        self.sent.append((data, addr))

    def bind(self, addr: tuple) -> None:
        self.bind_args = addr

    def connect(self, addr: tuple) -> None:
        self.connect_args = addr

    def getsockname(self) -> tuple:
        return self.getsockname_return

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def patch_socket():
    """Patch socket.socket at module level and return the fake factory."""
    with patch("custom_components.mikrotik_extended.mndp.socket") as mod:
        # Preserve real constants
        mod.AF_INET = real_socket.AF_INET
        mod.SOCK_DGRAM = real_socket.SOCK_DGRAM
        mod.SOL_SOCKET = real_socket.SOL_SOCKET
        mod.SO_REUSEADDR = real_socket.SO_REUSEADDR
        mod.SO_BROADCAST = real_socket.SO_BROADCAST
        yield mod


async def test_snmp_sysname_success(patch_socket) -> None:
    sock = _FakeSock()
    patch_socket.socket.return_value = sock

    loop = asyncio.get_event_loop()
    name = b"R1"
    response = _OID + b"\x04" + bytes([len(name)]) + name

    async def fake_sock_recv(_sock, _n):
        return response

    with patch.object(loop, "sock_recv", side_effect=fake_sock_recv):
        result = await _snmp_sysname(loop, "10.0.0.1")

    assert result == "R1"
    assert sock.closed
    assert sock.sent and sock.sent[0][1] == ("10.0.0.1", 161)


async def test_snmp_sysname_timeout(patch_socket) -> None:
    sock = _FakeSock()
    patch_socket.socket.return_value = sock
    loop = asyncio.get_event_loop()

    async def hang(_sock, _n):
        await asyncio.sleep(5)
        return b""

    with (
        patch.object(loop, "sock_recv", side_effect=hang),
        patch("custom_components.mikrotik_extended.mndp._SNMP_TIMEOUT", 0.01),
    ):
        result = await _snmp_sysname(loop, "10.0.0.2")

    assert result is None
    assert sock.closed


async def test_snmp_sysname_oserror(patch_socket) -> None:
    sock = _FakeSock()
    patch_socket.socket.return_value = sock
    loop = asyncio.get_event_loop()

    async def boom(_sock, _n):
        raise OSError("nope")

    with patch.object(loop, "sock_recv", side_effect=boom):
        result = await _snmp_sysname(loop, "10.0.0.3")

    assert result is None
    assert sock.closed


# ---------------------------------------------------------------------------
# _mndp_unicast (async)
# ---------------------------------------------------------------------------


async def test_mndp_unicast_success(patch_socket) -> None:
    sock = _FakeSock()
    patch_socket.socket.return_value = sock
    loop = asyncio.get_event_loop()

    response = _make_mndp_packet()

    async def fake_sock_recv(_sock, _n):
        return response

    with patch.object(loop, "sock_recv", side_effect=fake_sock_recv):
        dev = await _mndp_unicast(loop, "192.168.88.1", timeout=0.5)

    assert dev is not None
    assert dev.ip == "192.168.88.1"
    assert sock.closed
    assert sock.sent[0] == (_MNDP_PROBE, ("192.168.88.1", MNDP_PORT))


async def test_mndp_unicast_sendto_oserror(patch_socket) -> None:
    sock = _FakeSock(send_raises=True)
    patch_socket.socket.return_value = sock
    loop = asyncio.get_event_loop()

    dev = await _mndp_unicast(loop, "10.0.0.1", timeout=0.5)
    assert dev is None


async def test_mndp_unicast_timeout(patch_socket) -> None:
    sock = _FakeSock()
    patch_socket.socket.return_value = sock
    loop = asyncio.get_event_loop()

    async def hang(_sock, _n):
        await asyncio.sleep(5)
        return b""

    with patch.object(loop, "sock_recv", side_effect=hang):
        dev = await _mndp_unicast(loop, "10.0.0.4", timeout=0.01)

    assert dev is None
    assert sock.closed


async def test_mndp_unicast_recv_oserror(patch_socket) -> None:
    sock = _FakeSock()
    patch_socket.socket.return_value = sock
    loop = asyncio.get_event_loop()

    async def boom(_sock, _n):
        raise OSError

    with patch.object(loop, "sock_recv", side_effect=boom):
        dev = await _mndp_unicast(loop, "10.0.0.5", timeout=0.5)

    assert dev is None
    assert sock.closed


# ---------------------------------------------------------------------------
# _listen_mndp_broadcast (async)
# ---------------------------------------------------------------------------


async def test_listen_mndp_broadcast_collects_devices(patch_socket) -> None:
    tmp_sock = _FakeSock()  # for local-IP probe
    tmp_sock.getsockname_return = ("192.168.50.10", 0)
    listen_sock = _FakeSock()

    # First call returns tmp_sock, second returns listen_sock
    patch_socket.socket.side_effect = [tmp_sock, listen_sock]
    loop = asyncio.get_event_loop()

    pkt = _make_mndp_packet(ip=b"\xc0\xa8\x32\x02", identity=b"R2")

    calls = {"n": 0}

    async def fake_sock_recv(_sock, _n):
        calls["n"] += 1
        if calls["n"] == 1:
            return _MNDP_PROBE  # loopback — should be skipped
        if calls["n"] == 2:
            return pkt
        raise TimeoutError

    found: dict[str, MndpDevice] = {}
    with patch.object(loop, "sock_recv", side_effect=fake_sock_recv):
        await _listen_mndp_broadcast(loop, found, timeout=0.5)

    assert "192.168.50.2" in found
    assert listen_sock.closed
    # Broadcast addresses include directed subnet broadcast
    dests = [addr for _, addr in listen_sock.sent]
    assert ("255.255.255.255", MNDP_PORT) in dests
    assert ("192.168.50.255", MNDP_PORT) in dests


async def test_listen_mndp_broadcast_local_ip_failure(patch_socket) -> None:
    # tmp socket connect raises OSError -> only "255.255.255.255" used
    tmp_sock = MagicMock()
    tmp_sock.connect.side_effect = OSError
    listen_sock = _FakeSock()
    patch_socket.socket.side_effect = [tmp_sock, listen_sock]
    loop = asyncio.get_event_loop()

    async def fake_sock_recv(_sock, _n):
        raise TimeoutError

    found: dict[str, MndpDevice] = {}
    with patch.object(loop, "sock_recv", side_effect=fake_sock_recv):
        await _listen_mndp_broadcast(loop, found, timeout=0.05)

    assert found == {}
    dests = [addr for _, addr in listen_sock.sent]
    assert dests == [("255.255.255.255", MNDP_PORT)]


async def test_listen_mndp_broadcast_loopback_ip(patch_socket) -> None:
    # tmp socket returns 127.0.0.1 -> directed broadcast NOT added
    tmp_sock = _FakeSock()
    tmp_sock.getsockname_return = ("127.0.0.1", 0)
    listen_sock = _FakeSock()
    patch_socket.socket.side_effect = [tmp_sock, listen_sock]
    loop = asyncio.get_event_loop()

    async def fake_sock_recv(_sock, _n):
        raise TimeoutError

    found: dict[str, MndpDevice] = {}
    with patch.object(loop, "sock_recv", side_effect=fake_sock_recv):
        await _listen_mndp_broadcast(loop, found, timeout=0.05)

    dests = [addr for _, addr in listen_sock.sent]
    assert dests == [("255.255.255.255", MNDP_PORT)]


async def test_listen_mndp_broadcast_bind_oserror(patch_socket) -> None:
    tmp_sock = _FakeSock()
    tmp_sock.getsockname_return = ("192.168.1.1", 0)

    bad_sock = MagicMock()
    bad_sock.setsockopt = MagicMock()
    bad_sock.setblocking = MagicMock()
    bad_sock.bind.side_effect = OSError("bind fail")
    bad_sock.close = MagicMock()

    patch_socket.socket.side_effect = [tmp_sock, bad_sock]
    loop = asyncio.get_event_loop()

    found: dict[str, MndpDevice] = {}
    await _listen_mndp_broadcast(loop, found, timeout=0.05)
    # early return -> close never called (function returns before finally)
    assert found == {}


async def test_listen_mndp_broadcast_recv_oserror(patch_socket) -> None:
    tmp_sock = _FakeSock()
    tmp_sock.getsockname_return = ("192.168.1.1", 0)
    listen_sock = _FakeSock()
    patch_socket.socket.side_effect = [tmp_sock, listen_sock]
    loop = asyncio.get_event_loop()

    async def boom(_sock, _n):
        raise OSError

    found: dict[str, MndpDevice] = {}
    with patch.object(loop, "sock_recv", side_effect=boom):
        await _listen_mndp_broadcast(loop, found, timeout=0.5)

    assert found == {}
    assert listen_sock.closed


async def test_listen_mndp_broadcast_zero_remaining(patch_socket) -> None:
    # Simulate deadline already passed -> loop exits immediately
    tmp_sock = _FakeSock()
    tmp_sock.getsockname_return = ("192.168.1.1", 0)
    listen_sock = _FakeSock()
    patch_socket.socket.side_effect = [tmp_sock, listen_sock]
    loop = asyncio.get_event_loop()

    found: dict[str, MndpDevice] = {}
    # Zero timeout -> remaining<=0 -> immediate break
    await _listen_mndp_broadcast(loop, found, timeout=0.0)
    assert found == {}
    assert listen_sock.closed


# ---------------------------------------------------------------------------
# _populate_arp_table
# ---------------------------------------------------------------------------


async def test_populate_arp_table_scans(patch_socket) -> None:
    tmp_sock = _FakeSock()
    tmp_sock.getsockname_return = ("10.11.12.13", 0)
    scan_sock = _FakeSock()
    patch_socket.socket.side_effect = [tmp_sock, scan_sock]

    with patch("custom_components.mikrotik_extended.mndp.asyncio.sleep", return_value=None):
        await _populate_arp_table()

    # Should send to .1 through .254 except .13
    assert len(scan_sock.sent) == 253
    assert scan_sock.closed


async def test_populate_arp_table_local_ip_oserror(patch_socket) -> None:
    tmp_sock = MagicMock()
    tmp_sock.connect.side_effect = OSError
    patch_socket.socket.return_value = tmp_sock

    with patch("custom_components.mikrotik_extended.mndp.asyncio.sleep", return_value=None):
        await _populate_arp_table()
    # Should not crash; only one socket created
    assert patch_socket.socket.call_count == 1


async def test_populate_arp_table_loopback(patch_socket) -> None:
    tmp_sock = _FakeSock()
    tmp_sock.getsockname_return = ("127.0.0.1", 0)
    patch_socket.socket.return_value = tmp_sock

    with patch("custom_components.mikrotik_extended.mndp.asyncio.sleep", return_value=None):
        await _populate_arp_table()
    # Bails out after loopback check — only one socket created
    assert patch_socket.socket.call_count == 1


async def test_populate_arp_table_sendto_oserror_suppressed(patch_socket) -> None:
    tmp_sock = _FakeSock()
    tmp_sock.getsockname_return = ("10.11.12.13", 0)
    scan_sock = _FakeSock(send_raises=True)
    patch_socket.socket.side_effect = [tmp_sock, scan_sock]

    with patch("custom_components.mikrotik_extended.mndp.asyncio.sleep", return_value=None):
        await _populate_arp_table()  # should not raise
    assert scan_sock.closed


# ---------------------------------------------------------------------------
# async_scan_mndp integration
# ---------------------------------------------------------------------------


async def test_async_scan_mndp_combines_arp_and_broadcast() -> None:
    """End-to-end: ARP table yields one device, unicast returns MndpDevice."""
    mndp_dev = MndpDevice(ip="192.168.88.1", mac="00:0c:42:aa:bb:cc", identity="R1")

    async def fake_populate():
        return None

    async def fake_listen(loop, found, timeout):
        found["192.168.88.99"] = MndpDevice(ip="192.168.88.99", identity="R99")

    async def fake_unicast(loop, ip, timeout):
        return mndp_dev if ip == "192.168.88.1" else None

    async def fake_snmp(loop, ip):
        return "sys-snmp"

    with (
        patch(
            "custom_components.mikrotik_extended.mndp._populate_arp_table",
            side_effect=fake_populate,
        ),
        patch(
            "custom_components.mikrotik_extended.mndp._listen_mndp_broadcast",
            side_effect=fake_listen,
        ),
        patch(
            "custom_components.mikrotik_extended.mndp._read_arp_table",
            return_value=[("192.168.88.1", "00:0c:42:aa:bb:cc")],
        ),
        patch(
            "custom_components.mikrotik_extended.mndp._get_default_gateway",
            return_value="192.168.88.254",
        ),
        patch(
            "custom_components.mikrotik_extended.mndp._mndp_unicast",
            side_effect=fake_unicast,
        ),
        patch(
            "custom_components.mikrotik_extended.mndp._snmp_sysname",
            side_effect=fake_snmp,
        ),
    ):
        result = await async_scan_mndp(timeout=0.5)

    ips = {d.ip for d in result}
    assert "192.168.88.1" in ips
    assert "192.168.88.99" in ips


async def test_async_scan_mndp_snmp_fallback_for_known_device() -> None:
    """If unicast MNDP returns None but the device is in ARP, keep it with SNMP name."""

    async def fake_populate():
        return None

    async def fake_listen(loop, found, timeout):
        return None

    async def fake_unicast(loop, ip, timeout):
        return None  # no MNDP response

    async def fake_snmp(loop, ip):
        return "snmp-name"

    with (
        patch(
            "custom_components.mikrotik_extended.mndp._populate_arp_table",
            side_effect=fake_populate,
        ),
        patch(
            "custom_components.mikrotik_extended.mndp._listen_mndp_broadcast",
            side_effect=fake_listen,
        ),
        patch(
            "custom_components.mikrotik_extended.mndp._read_arp_table",
            return_value=[("10.0.0.1", "00:0c:42:11:22:33")],
        ),
        patch(
            "custom_components.mikrotik_extended.mndp._get_default_gateway",
            return_value=None,
        ),
        patch(
            "custom_components.mikrotik_extended.mndp._mndp_unicast",
            side_effect=fake_unicast,
        ),
        patch(
            "custom_components.mikrotik_extended.mndp._snmp_sysname",
            side_effect=fake_snmp,
        ),
    ):
        result = await async_scan_mndp(timeout=0.2)

    assert len(result) == 1
    assert result[0].ip == "10.0.0.1"
    assert result[0].identity == "snmp-name"
    assert result[0].mac == "00:0c:42:11:22:33"


async def test_async_scan_mndp_no_arp_no_gateway() -> None:
    """When no ARP and no gateway, probe_list is empty; only broadcast runs."""

    async def fake_populate():
        return None

    async def fake_listen(loop, found, timeout):
        return None

    with (
        patch(
            "custom_components.mikrotik_extended.mndp._populate_arp_table",
            side_effect=fake_populate,
        ),
        patch(
            "custom_components.mikrotik_extended.mndp._listen_mndp_broadcast",
            side_effect=fake_listen,
        ),
        patch(
            "custom_components.mikrotik_extended.mndp._read_arp_table",
            return_value=[],
        ),
        patch(
            "custom_components.mikrotik_extended.mndp._get_default_gateway",
            return_value=None,
        ),
    ):
        result = await async_scan_mndp(timeout=0.1)

    assert result == []


async def test_async_scan_mndp_gateway_only() -> None:
    """Gateway alone triggers a probe; unknown device without MNDP response is dropped."""

    async def fake_populate():
        return None

    async def fake_listen(loop, found, timeout):
        return None

    async def fake_unicast(loop, ip, timeout):
        return None  # no answer

    async def fake_snmp(loop, ip):
        return None

    with (
        patch(
            "custom_components.mikrotik_extended.mndp._populate_arp_table",
            side_effect=fake_populate,
        ),
        patch(
            "custom_components.mikrotik_extended.mndp._listen_mndp_broadcast",
            side_effect=fake_listen,
        ),
        patch(
            "custom_components.mikrotik_extended.mndp._read_arp_table",
            return_value=[],
        ),
        patch(
            "custom_components.mikrotik_extended.mndp._get_default_gateway",
            return_value="10.0.0.254",
        ),
        patch(
            "custom_components.mikrotik_extended.mndp._mndp_unicast",
            side_effect=fake_unicast,
        ),
        patch(
            "custom_components.mikrotik_extended.mndp._snmp_sysname",
            side_effect=fake_snmp,
        ),
    ):
        result = await async_scan_mndp(timeout=0.1)

    # Unknown gateway with no MNDP response -> not included
    assert result == []


async def test_async_scan_mndp_unicast_exception_handled() -> None:
    """Exceptions from unicast/snmp gather are swallowed gracefully."""

    async def fake_populate():
        return None

    async def fake_listen(loop, found, timeout):
        return None

    async def fake_unicast(loop, ip, timeout):
        raise RuntimeError("boom")

    async def fake_snmp(loop, ip):
        raise RuntimeError("boom-snmp")

    with (
        patch(
            "custom_components.mikrotik_extended.mndp._populate_arp_table",
            side_effect=fake_populate,
        ),
        patch(
            "custom_components.mikrotik_extended.mndp._listen_mndp_broadcast",
            side_effect=fake_listen,
        ),
        patch(
            "custom_components.mikrotik_extended.mndp._read_arp_table",
            return_value=[("10.0.0.1", "00:0c:42:11:22:33")],
        ),
        patch(
            "custom_components.mikrotik_extended.mndp._get_default_gateway",
            return_value=None,
        ),
        patch(
            "custom_components.mikrotik_extended.mndp._mndp_unicast",
            side_effect=fake_unicast,
        ),
        patch(
            "custom_components.mikrotik_extended.mndp._snmp_sysname",
            side_effect=fake_snmp,
        ),
    ):
        result = await async_scan_mndp(timeout=0.1)

    # mndp_result is Exception -> the `elif not Exception and is_known` branch skipped
    assert result == []
