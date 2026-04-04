"""Root conftest — must run before any asyncio fixtures are set up."""
import asyncio
import asyncio.events
import sys


def pytest_configure(config):
    """Fix Windows asyncio + pytest-socket incompatibility.

    pytest-homeassistant-custom-component:
      1. Sets HassEventLoopPolicy (uses ProactorEventLoop on Windows)
      2. Monkey-patches asyncio.set_event_loop_policy → no-op lambda
      3. Calls pytest_socket.disable_socket(allow_unix_socket=True)
         → blocks ALL socket.socket() calls except AF_UNIX

    On Windows both ProactorEventLoop and SelectorEventLoop create their
    internal self-pipe via socket.socketpair() (AF_INET), which is blocked.

    Fixes applied:
      A) Switch to WindowsSelectorEventLoopPolicy via asyncio.events (bypasses
         HA's no-op monkey-patch on asyncio.set_event_loop_policy).
      B) Patch socket.socketpair to use pytest_socket._true_socket directly,
         so asyncio can always create its internal self-pipe regardless of
         whether the guard is active (affects both fixture setup and teardown).
    """
    if sys.platform != "win32":
        return

    # Fix A: bypass HA's monkey-patch, switch to SelectorEventLoop
    asyncio.events.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    # Fix B: patch socket.socketpair to bypass GuardedSocket.
    # socket.socket.accept() looks up "socket" in its module globals, so it
    # would instantiate GuardedSocket for the accepted fd.  Temporarily
    # restoring socket.socket to _true_socket for the duration of the call
    # is the cleanest workaround.
    import socket as _socket_mod

    def _unguarded_socketpair(
        family=_socket_mod.AF_INET,
        type=_socket_mod.SOCK_STREAM,  # noqa: A002
        proto=0,
    ):
        """socketpair that bypasses pytest-socket's GuardedSocket for asyncio."""
        import pytest_socket as _ps

        _guarded = _socket_mod.socket
        _socket_mod.socket = _ps._true_socket  # restore for accept() lookup
        try:
            lsock = _ps._true_socket(family, type, proto)
            try:
                lsock.bind(("127.0.0.1", 0))
                lsock.listen(1)
                addr = lsock.getsockname()
                csock = _ps._true_socket(family, type, proto)
                try:
                    csock.connect(addr)
                    ssock, _ = lsock.accept()
                    csock.setblocking(False)
                    ssock.setblocking(False)
                    return ssock, csock
                except Exception:
                    csock.close()
                    raise
            finally:
                lsock.close()
        finally:
            _socket_mod.socket = _guarded  # re-apply guard

    _socket_mod.socketpair = _unguarded_socketpair
