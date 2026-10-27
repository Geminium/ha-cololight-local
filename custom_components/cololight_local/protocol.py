"""Cololight local UDP protocol (frame codec).

Pure Python, no Home Assistant import: it is shared by the integration, the tests and
the command line tools. Every rule below was verified against a real strip on
2026-10-25 (see docs/findings.md).

Frame layout (offsets in bytes)::

    0-3   b"SZ00"                  magic
    4     0x00 request / 0x80 reply
    8-9   uint16 BE                length of what follows offset 9 (= len - 10)
    16-17 uint16 BE                sum of every byte from offset 18 (not checked by the lamp)
    26    sequence                 echoed by the lamp
    36    operation                reply = operation | 0x80
    37    secondary sequence       echoed by the lamp, no effect
    38..  TLV blocks               [length][id][data (length - 1 bytes)]

A reply carries the TLV of the element it refers to, followed by a trailer TLV
holding the MAC address in ASCII (``0d 01 "4C11AEB1B614"``). A TLV of length 1
(no data) means an error: its id is the error code.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

PORT = 8900
MAGIC = b"SZ00"
FLAG_REPLY = 0x80
HEADER_LEN = 38  # bytes before the first TLV

POWER_ON = 0xCF
POWER_OFF = 0xCE
POWER_OFF_FILLER = 0x1E  # second byte of the "off" payload, as sent by every known client
MODE_PREFIX = 0xFF
MULTI_FRAME_PREFIX = 0x93  # first byte of every frame of a multi-frame (palette) effect

BRIGHTNESS_MIN = 1
# 0-101 were accepted during tests; 255 made the strip drop off WiFi until a power cycle.
BRIGHTNESS_MAX = 100


class Op(IntEnum):
    """Operation byte (offset 36)."""

    READ = 0x03
    WRITE = 0x04
    WRITE_SAVE = 0x07  # write and store in EEPROM: survives a power cut


class Element(IntEnum):
    """TLV ids of the device state."""

    POWER = 0x01  # cf NN (on, brightness NN %) / ce 1e (off)
    MODE = 0x02  # ff 00 RR GG BB (static colour) / ff A B C D (effect)


class CololightError(Exception):
    """Base error for everything raised by this package."""


class ProtocolError(CololightError):
    """A datagram could not be decoded."""


@dataclass(frozen=True, slots=True)
class Reply:
    """A decoded reply datagram."""

    op: int  # without FLAG_REPLY
    seq: int
    seq2: int
    element: int  # id of the first TLV (the error code when error is True)
    data: bytes  # data of the first TLV
    error: bool
    mac: str | None  # "4C11AEB1B614" when the trailer is present
    raw: bytes


@dataclass(frozen=True, slots=True)
class PowerState:
    """Content of element 01."""

    on: bool
    brightness: int | None  # 0-100, None when off (the lamp does not report it)


@dataclass(frozen=True, slots=True)
class ModeState:
    """Content of element 02."""

    code: bytes  # the 4 bytes after 0xFF

    @property
    def is_color(self) -> bool:
        return self.code[0] == 0x00

    @property
    def rgb(self) -> tuple[int, int, int] | None:
        if not self.is_color:
            return None
        return (self.code[1], self.code[2], self.code[3])

    @property
    def is_multi_frame(self) -> bool:
        """True when this is the last frame of a multi-frame effect (ambiguous)."""
        return self.code[0] == MULTI_FRAME_PREFIX


@dataclass(frozen=True, slots=True)
class DeviceState:
    """Full state, as read with two requests."""

    power: PowerState
    mode: ModeState


def checksum(frame: bytes | bytearray) -> int:
    """16-bit sum of every byte from offset 18."""
    return sum(frame[18:]) & 0xFFFF


def build_frame(op: int, tlvs: bytes, seq: int) -> bytes:
    """Build a request frame around already encoded TLV blocks."""
    if not 0 <= seq <= 0xFF:
        raise ValueError(f"sequence out of range: {seq}")
    frame = bytearray(HEADER_LEN)
    frame[0:4] = MAGIC
    frame[26] = seq
    frame[36] = op
    frame[37] = seq
    frame += tlvs
    frame[8:10] = (len(frame) - 10).to_bytes(2, "big")
    frame[16:18] = checksum(frame).to_bytes(2, "big")
    return bytes(frame)


def tlv(element: int, data: bytes = b"") -> bytes:
    """Encode one TLV block."""
    if len(data) + 1 > 0xFF:
        raise ValueError("TLV data too long")
    return bytes([len(data) + 1, element]) + data


def build_read(element: Element, seq: int) -> bytes:
    """Request reading one element (the lamp ignores any further TLV)."""
    return build_frame(Op.READ, tlv(element), seq)


def build_write(element: Element, data: bytes, seq: int, *, save: bool = False) -> bytes:
    """Request writing one element; ``save`` stores it in EEPROM (op 07)."""
    return build_frame(Op.WRITE_SAVE if save else Op.WRITE, tlv(element, data), seq)


def power_on_data(brightness: int) -> bytes:
    """Payload of element 01 turning the lamp on at ``brightness`` % (clamped 1-100)."""
    return bytes([POWER_ON, clamp_brightness(brightness)])


def power_off_data() -> bytes:
    """Payload of element 01 turning the lamp off."""
    return bytes([POWER_OFF, POWER_OFF_FILLER])


def color_data(rgb: tuple[int, int, int]) -> bytes:
    """Payload of element 02 selecting a static colour."""
    r, g, b = (int(c) for c in rgb)
    for c in (r, g, b):
        if not 0 <= c <= 0xFF:
            raise ValueError(f"colour component out of range: {rgb}")
    return bytes([MODE_PREFIX, 0x00, r, g, b])


def effect_data(code: bytes) -> bytes:
    """Payload of element 02 selecting an effect frame (4 bytes)."""
    if len(code) != 4:
        raise ValueError(f"effect frame must be 4 bytes, got {code.hex()}")
    if code[0] == 0x00:
        raise ValueError("an effect frame cannot start with 00 (that is a static colour)")
    return bytes([MODE_PREFIX]) + bytes(code)


def clamp_brightness(brightness: int) -> int:
    """Clamp to the only range known to be safe."""
    return max(BRIGHTNESS_MIN, min(BRIGHTNESS_MAX, int(brightness)))


def parse_reply(datagram: bytes) -> Reply:
    """Decode a reply; raise ProtocolError on anything malformed."""
    if len(datagram) < HEADER_LEN + 2:
        raise ProtocolError(f"datagram too short ({len(datagram)} bytes)")
    if datagram[0:4] != MAGIC:
        raise ProtocolError("bad magic")
    if not datagram[4] & FLAG_REPLY:
        raise ProtocolError("not a reply (flag 0x80 missing)")
    if int.from_bytes(datagram[8:10], "big") != len(datagram) - 10:
        raise ProtocolError("length field mismatch")
    if int.from_bytes(datagram[16:18], "big") != checksum(datagram):
        raise ProtocolError("checksum mismatch")
    if not datagram[36] & FLAG_REPLY:
        raise ProtocolError("operation byte lacks the reply flag")

    blocks: list[tuple[int, bytes]] = []
    i = HEADER_LEN
    while i < len(datagram):
        length = datagram[i]
        if length == 0 or i + 1 + length > len(datagram):
            raise ProtocolError(f"truncated TLV at offset {i}")
        blocks.append((datagram[i + 1], datagram[i + 2 : i + 1 + length]))
        i += 1 + length

    element, data = blocks[0]
    mac = None
    for tid, tdata in blocks[1:]:
        if tid == 0x01 and len(tdata) == 12:
            try:
                mac = tdata.decode("ascii").upper()
            except UnicodeDecodeError:
                mac = None
    return Reply(
        op=datagram[36] & ~FLAG_REPLY & 0xFF,
        seq=datagram[26],
        seq2=datagram[37],
        element=element,
        data=data,
        error=len(data) == 0,
        mac=mac,
        raw=bytes(datagram),
    )


def decode_power(data: bytes) -> PowerState:
    """Decode element 01."""
    if len(data) != 2 or data[0] not in (POWER_ON, POWER_OFF):
        raise ProtocolError(f"unexpected power data {data.hex()}")
    if data[0] == POWER_ON:
        return PowerState(on=True, brightness=data[1])
    return PowerState(on=False, brightness=None)


def decode_mode(data: bytes) -> ModeState:
    """Decode element 02."""
    if len(data) != 5 or data[0] != MODE_PREFIX:
        raise ProtocolError(f"unexpected mode data {data.hex()}")
    return ModeState(code=bytes(data[1:5]))


def format_mac(mac: str) -> str:
    """'4C11AEB1B614' -> '4c:11:ae:b1:b6:14'."""
    mac = mac.replace(":", "").replace("-", "").lower()
    return ":".join(mac[i : i + 2] for i in range(0, 12, 2))
