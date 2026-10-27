"""Asyncio UDP emulator of a Cololight strip, faithful to the behaviour measured on
2026-10-25 (docs/findings.md). Used by the tests; no Home Assistant import.

Usage::

    lamp = FakeLamp()
    host, port = await lamp.start()
    ...
    lamp.drop_next = 2        # lose the next two requests
    lamp.delay = 0.3          # answer 300 ms late
    lamp.power_cycle()        # boot back into the EEPROM-saved state
    await lamp.stop()
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field

MAC = "4C11AEB1B614"
MAGIC = b"SZ00"
UNKNOWN_OP_ERROR = 0x43
CRASH_ABOVE_BRIGHTNESS = 101  # 255 made the real strip drop off WiFi


@dataclass
class Received:
    op: int
    seq: int
    element: int | None
    data: bytes
    raw: bytes


@dataclass
class FakeLamp(asyncio.DatagramProtocol):
    mac: str = MAC
    power: bytes = bytes([0xCF, 50])  # element 01 content
    mode: bytes = bytes([0xFF, 0x00, 0xFF, 0x22, 0x22])  # element 02 content
    saved_power: bytes = bytes([0xCF, 100])  # what the lamp boots with
    saved_mode: bytes = bytes([0xFF, 0x00, 0xFF, 0x22, 0x22])
    drop_next: int = 0  # number of upcoming requests to ignore
    drop_filter: Callable[[Received], bool] | None = None  # return True to ignore
    delay: float = 0.0  # reply delay in seconds
    duplicate_replies: bool = False  # send every reply twice
    crashed: bool = False  # WiFi lost: ignores everything until power_cycle()
    received: list[Received] = field(default_factory=list)
    _transport: asyncio.DatagramTransport | None = None

    # ------------------------------------------------------------- lifecycle

    async def start(self, host: str = "127.0.0.1", port: int = 0) -> tuple[str, int]:
        loop = asyncio.get_running_loop()
        self._transport, _ = await loop.create_datagram_endpoint(lambda: self, local_addr=(host, port))
        return self._transport.get_extra_info("sockname")[:2]

    async def stop(self) -> None:
        if self._transport is not None:
            self._transport.close()
            self._transport = None

    def power_cycle(self) -> None:
        """Simulate unplugging: volatile state is lost, the saved one comes back."""
        self.power = self.saved_power
        self.mode = self.saved_mode
        self.crashed = False

    # ------------------------------------------------------------- protocol

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self._transport = transport  # type: ignore[assignment]

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        if len(data) < 40 or data[:4] != MAGIC or data[4] & 0x80:
            return
        op, seq, seq2 = data[36], data[26], data[37]
        element = data[39] if len(data) > 39 else None
        tlv_data = data[40 : 39 + data[38]] if len(data) > 39 else b""
        req = Received(op=op, seq=seq, element=element, data=bytes(tlv_data), raw=bytes(data))
        self.received.append(req)
        if self.crashed:
            return
        if self.drop_next > 0:
            self.drop_next -= 1
            return
        if self.drop_filter is not None and self.drop_filter(req):
            return
        reply_tlv = self._handle(op, element, bytes(tlv_data))
        frame = self._reply(op, seq, seq2, reply_tlv)
        if self.delay:
            asyncio.get_running_loop().call_later(self.delay, self._send, frame, addr)
        else:
            self._send(frame, addr)

    def _handle(self, op: int, element: int | None, data: bytes) -> bytes:
        if op == 0x03:  # read
            if element == 0x01:
                return _tlv(0x01, self.power)
            if element == 0x02:
                return _tlv(0x02, self.mode)
            if element == 0x03:
                return _tlv(0x03, bytes.fromhex("fe00000000"))
            return _tlv(element or 0, b"\x1e")  # element that does not exist
        if op in (0x04, 0x07):  # write / write + EEPROM
            if element == 0x01 and len(data) == 2 and data[0] in (0xCE, 0xCF):
                if data[0] == 0xCF and data[1] > CRASH_ABOVE_BRIGHTNESS:
                    self.crashed = True  # still acknowledges this one, then goes silent
                self.power = data
                if op == 0x07:
                    self.saved_power = data
            elif element == 0x02 and len(data) == 5 and data[0] == 0xFF:
                self.mode = data
                if op == 0x07:
                    self.saved_mode = data
            return _tlv(element or 0, data)
        return bytes([0x01, UNKNOWN_OP_ERROR])  # error TLV: length 1, id = code

    def _reply(self, op: int, seq: int, seq2: int, tlvs: bytes) -> bytes:
        frame = bytearray(38)
        frame[0:4] = MAGIC
        frame[4] = 0x80
        frame[26] = seq
        frame[36] = op | 0x80
        frame[37] = seq2
        frame += tlvs + _tlv(0x01, self.mac.encode("ascii"))
        frame[8:10] = (len(frame) - 10).to_bytes(2, "big")
        frame[16:18] = (sum(frame[18:]) & 0xFFFF).to_bytes(2, "big")
        return bytes(frame)

    def _send(self, frame: bytes, addr: tuple[str, int]) -> None:
        if self._transport is None:
            return
        self._transport.sendto(frame, addr)
        if self.duplicate_replies:
            self._transport.sendto(frame, addr)

    # ------------------------------------------------------------- helpers

    @property
    def is_on(self) -> bool:
        return self.power[0] == 0xCF

    @property
    def brightness(self) -> int | None:
        return self.power[1] if self.is_on else None

    @property
    def mode_code(self) -> bytes:
        return self.mode[1:5]

    def writes(self) -> list[Received]:
        return [r for r in self.received if r.op in (0x04, 0x07)]


def _tlv(element: int, data: bytes) -> bytes:
    return bytes([len(data) + 1, element]) + data
