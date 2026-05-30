"""Unit tests for VNC RFB server-side authentication helpers.

Tests cover:
  - _vnc_des_key bit-reversal and padding
  - _rfb_auth: chooses type-1 (None) when offered
  - _rfb_auth: performs DES challenge/response for type-2 (VNC Auth)
  - _rfb_auth: returns False when server reports authentication failure
  - _rfb_auth: returns False when no password is stored but server requires type-2
"""
import asyncio
import struct

import pytest

from fleet_platform.api.routes.vnc import _rfb_auth, _vnc_des_key


# ---------------------------------------------------------------------------
# _vnc_des_key tests
# ---------------------------------------------------------------------------


def test_vnc_des_key_produces_eight_bytes():
    key = _vnc_des_key("pwd")
    assert len(key) == 8


def test_vnc_des_key_reverses_bits_on_first_byte():
    # 'p' == 0x70 == 0b01110000
    # reversed bits: 0b00001110 == 0x0E
    key = _vnc_des_key("p")
    assert key[0] == 0x0E


def test_vnc_des_key_pads_short_password_with_null_bytes():
    key = _vnc_des_key("abc")
    assert len(key) == 8
    # Last 5 bytes must be 0 (bit-reversed 0x00 is still 0x00)
    assert key[3:] == bytes(5)


def test_vnc_des_key_truncates_long_password():
    # Passwords longer than 8 characters are truncated to 8
    key_long = _vnc_des_key("abcdefghijklmnop")
    key_short = _vnc_des_key("abcdefgh")
    assert key_long == key_short


def test_vnc_des_key_empty_password():
    key = _vnc_des_key("")
    assert key == bytes(8)


# ---------------------------------------------------------------------------
# Helpers — minimal asyncio mock reader / writer
# ---------------------------------------------------------------------------


class _MockReader:
    """Feeds a pre-built byte sequence one read() call at a time."""

    def __init__(self, data: bytes) -> None:
        self._buf = bytearray(data)

    async def read(self, n: int) -> bytes:
        chunk = bytes(self._buf[:n])
        del self._buf[:n]
        return chunk


class _MockWriter:
    """Captures all written bytes for assertion."""

    def __init__(self) -> None:
        self.written = bytearray()
        self.closed = False

    def write(self, data: bytes) -> None:
        self.written.extend(data)

    async def drain(self) -> None:
        pass

    def close(self) -> None:
        self.closed = True


# ---------------------------------------------------------------------------
# _rfb_auth: type-1 (None auth)
# ---------------------------------------------------------------------------


def _build_type1_server(security_result: int = 0) -> bytes:
    """Build a minimal RFB 3.8 server greeting offering type-1 (None)."""
    version = b"RFB 003.008\n"
    sec_list = bytes([1, 1])  # n_types=1, types=[1]
    result = struct.pack(">I", security_result)
    return version + sec_list + result


@pytest.mark.asyncio
async def test_rfb_auth_picks_none_auth_when_available():
    data = _build_type1_server(security_result=0)
    reader = _MockReader(data)
    writer = _MockWriter()

    ok = await _rfb_auth(reader, writer, password=None)

    assert ok is True
    # Client must have replied with b"\x01" (type 1)
    assert b"\x01" in writer.written


@pytest.mark.asyncio
async def test_rfb_auth_returns_false_when_type1_result_is_failure():
    data = _build_type1_server(security_result=1)
    reader = _MockReader(data)
    writer = _MockWriter()

    ok = await _rfb_auth(reader, writer, password=None)

    assert ok is False


# ---------------------------------------------------------------------------
# _rfb_auth: type-2 (VNC Auth)
# ---------------------------------------------------------------------------


def _build_type2_server_with_challenge(challenge: bytes, auth_status: int = 0) -> bytes:
    """Build a minimal RFB 3.8 server greeting offering type-2 (VNC Auth)."""
    version = b"RFB 003.008\n"
    sec_list = bytes([1, 2])  # n_types=1, types=[2]
    result = struct.pack(">I", auth_status)
    return version + sec_list + challenge + result


def _compute_expected_response(password: str, challenge: bytes) -> bytes:
    """Mirror the DES response that _rfb_auth should send."""
    from cryptography.hazmat.decrepit.ciphers.algorithms import TripleDES as _TripleDES
    from cryptography.hazmat.primitives.ciphers import Cipher, modes

    key = _vnc_des_key(password)
    cipher = Cipher(_TripleDES(key * 3), modes.ECB())
    enc = cipher.encryptor()
    return enc.update(challenge[:8]) + enc.update(challenge[8:]) + enc.finalize()


@pytest.mark.asyncio
async def test_rfb_auth_succeeds_with_correct_password():
    challenge = b"\xde\xad\xbe\xef" * 4  # 16 bytes
    data = _build_type2_server_with_challenge(challenge, auth_status=0)
    reader = _MockReader(data)
    writer = _MockWriter()

    ok = await _rfb_auth(reader, writer, password="abcd")

    assert ok is True
    expected = _compute_expected_response("abcd", challenge)
    # The 16-byte DES response must appear in writer output
    assert expected in bytes(writer.written)


@pytest.mark.asyncio
async def test_rfb_auth_fails_when_server_returns_status_1():
    challenge = b"\x01\x02\x03\x04" * 4
    data = _build_type2_server_with_challenge(challenge, auth_status=1)
    reader = _MockReader(data)
    writer = _MockWriter()

    ok = await _rfb_auth(reader, writer, password="wrong")

    assert ok is False


@pytest.mark.asyncio
async def test_rfb_auth_fails_gracefully_when_no_password_for_type2():
    """If the server only offers type-2 and we have no password, return False."""
    challenge = b"\xAA\xBB\xCC\xDD" * 4
    # Build data: version + sec_list (type 2 only) + challenge + status=1
    # (status doesn't matter — we return False before reading it in the no-password path)
    version = b"RFB 003.008\n"
    sec_list = bytes([1, 2])  # n_types=1, types=[2]
    data = version + sec_list + challenge + struct.pack(">I", 0)
    reader = _MockReader(data)
    writer = _MockWriter()

    ok = await _rfb_auth(reader, writer, password=None)

    assert ok is False


# ---------------------------------------------------------------------------
# _rfb_auth: error paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rfb_auth_returns_false_on_truncated_version():
    reader = _MockReader(b"RFB")  # incomplete
    writer = _MockWriter()

    ok = await _rfb_auth(reader, writer, password=None)

    assert ok is False


@pytest.mark.asyncio
async def test_rfb_auth_returns_false_when_n_types_is_zero():
    """RFB 3.8 sends n_types=0 to signal a connection error."""
    version = b"RFB 003.008\n"
    data = version + bytes([0])  # n_types = 0
    reader = _MockReader(data)
    writer = _MockWriter()

    ok = await _rfb_auth(reader, writer, password=None)

    assert ok is False
