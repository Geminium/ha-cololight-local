"""Asynchronous UDP client for one Cololight lamp, plus LAN discovery.

Pure asyncio, no Home Assistant import. Strategy (docs/findings.md, section 6):

* one connected UDP socket per lamp, never blocking the event loop;
* one request in flight at a time (lock), replies matched by sequence number;
* every command is acknowledged by the lamp with the value it applied: a missing
  acknowledgement means the datagram, or its acknowledgement, was lost, so the request
  is retried. A single frame is an absolute value, hence idempotent. The frames of a
  palette upload are not: they form a counted sequence (docs/protocol.md, 3.5), so when
  one of them had to be sent twice, the whole upload is restarted once from its first
  frame, the start marker. That this marker resets the lamp's upload state is an
  assumption, not verified on the device;
* an acknowledgement for an earlier attempt of the same request is accepted;
* a client that knows the lamp's MAC address refuses replies from another device (two
  lamps that swapped their IP addresses).
"""

from __future__ import annotations

import asyncio
import logging
import random
import socket
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field

from .protocol import (
    PORT,
    CololightError,
    DeviceState,
    Element,
    ModeState,
    Op,
    PowerState,
    ProtocolError,
    Reply,
    build_read,
    build_write,
    color_data,
    decode_mode,
    decode_power,
    effect_data,
    parse_reply,
    power_off_data,
    power_on_data,
)

_LOGGER = logging.getLogger(__name__)

DEFAULT_ACK_TIMEOUT = 1.5  # seconds; observed p99 0.9 s, max 1.3 s
DEFAULT_ATTEMPTS = 4
DEFAULT_READ_ATTEMPTS = 2
DEFAULT_RETRY_DELAYS = (0.2, 0.5, 1.0)


class CololightTimeout(CololightError):
    """The lamp did not acknowledge after every attempt."""


class CololightConnectionError(CololightError):
    """The socket could not be opened or used."""


class CololightWrongDevice(CololightError):
    """Another device (another MAC address) answered at the lamp's address."""


class CololightRejected(CololightError):
    """The lamp answered with an error code."""

    def __init__(self, code: int) -> None:
        super().__init__(f"lamp rejected the request (error code 0x{code:02x})")
        self.code = code


@dataclass(slots=True)
class ClientStats:
    """Counters exposed in diagnostics."""

    requests: int = 0
    datagrams_sent: int = 0  # handed to the socket without an immediate error
    retries: int = 0
    timeouts: int = 0  # requests that failed after every attempt
    late_replies: int = 0
    invalid_datagrams: int = 0
    rejected: int = 0
    ack_mismatches: int = 0
    socket_errors: int = 0
    wrong_device: int = 0  # replies from another MAC address
    upload_restarts: int = 0  # palette uploads sent again from their first frame
    last_rtt: float | None = None
    rtts: list[float] = field(default_factory=list)  # last 50 round trips, seconds

    def record_rtt(self, rtt: float) -> None:
        self.last_rtt = rtt
        self.rtts.append(rtt)
        del self.rtts[:-50]


class _Protocol(asyncio.DatagramProtocol):
    def __init__(self, client: CololightClient) -> None:
        self._client = client

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        self._client._datagram_received(data)

    def error_received(self, exc: Exception) -> None:
        # Send failures (network unreachable...) and ICMP errors. asyncio transports report
        # them here, never by raising from sendto().
        self._client._socket_error_received(exc)


class CololightClient:
    """Talk to one lamp. Methods are coroutine-safe; calls are serialized."""

    def __init__(
        self,
        host: str,
        *,
        port: int = PORT,
        ack_timeout: float = DEFAULT_ACK_TIMEOUT,
        attempts: int = DEFAULT_ATTEMPTS,
        read_attempts: int = DEFAULT_READ_ATTEMPTS,
        retry_delays: Sequence[float] = DEFAULT_RETRY_DELAYS,
        expected_mac: str | None = None,
    ) -> None:
        """``expected_mac`` (any usual notation): refuse replies from another device."""
        self._host = host
        self._port = port
        self._ack_timeout = ack_timeout
        self._attempts = max(1, attempts)
        self._read_attempts = max(1, read_attempts)
        self._retry_delays = tuple(retry_delays) or (0.0,)
        self._expected_mac = (
            expected_mac.replace(":", "").replace("-", "").upper() if expected_mac else None
        )
        self._transport: asyncio.DatagramTransport | None = None
        self._closed = False
        self._socket_error: Exception | None = None  # reported during the current request
        self._lock = asyncio.Lock()
        self._seq = random.randint(1, 255)
        self._pending: dict[int, asyncio.Future[Reply]] = {}
        self.mac: str | None = None
        self.stats = ClientStats()

    @property
    def host(self) -> str:
        return self._host

    @property
    def port(self) -> int:
        return self._port

    # ------------------------------------------------------------------ socket

    async def async_start(self) -> None:
        """Open the socket (done automatically by the first request)."""
        if self._closed:
            raise CololightConnectionError(f"the client of {self._host} is stopped")
        if self._transport is not None:
            return
        loop = asyncio.get_running_loop()
        try:
            transport, _ = await loop.create_datagram_endpoint(
                lambda: _Protocol(self), remote_addr=(self._host, self._port)
            )
        except OSError as err:
            raise CololightConnectionError(f"cannot open UDP socket to {self._host}: {err}") from err
        self._transport = transport

    async def async_stop(self) -> None:
        """Close the socket for good.

        A pending request fails with a timeout, and any later one with
        CololightConnectionError: a stopped client never reopens a socket (the entry was
        unloaded; setting it up again creates a new client).
        """
        self._closed = True
        self._close_transport()

    def _close_transport(self) -> None:
        if self._transport is not None:
            self._transport.close()
            self._transport = None

    async def async_set_host(self, host: str) -> None:
        """Point the client at a new address (the lamp changed IP)."""
        async with self._lock:
            self._close_transport()
            self._host = host

    # ------------------------------------------------------------------ core

    def _next_seq(self) -> int:
        self._seq = self._seq % 255 + 1
        return self._seq

    def _socket_error_received(self, exc: Exception) -> None:
        self.stats.socket_errors += 1
        self._socket_error = exc
        _LOGGER.debug("%s: socket error %s", self._host, exc)

    def _datagram_received(self, data: bytes) -> None:
        try:
            reply = parse_reply(data)
        except ProtocolError as err:
            self.stats.invalid_datagrams += 1
            _LOGGER.debug("%s: ignoring invalid datagram (%s): %s", self._host, err, data.hex())
            return
        _LOGGER.debug("%s: rx %s", self._host, data.hex())
        future = self._pending.get(reply.seq)
        if future is None or future.done():
            self.stats.late_replies += 1
            return
        future.set_result(reply)

    async def _request(
        self, op: Op, element: Element, frame_for_seq: Callable[[int], bytes], attempts: int
    ) -> Reply:
        """Send a request until it is acknowledged; caller must hold the lock."""
        await self.async_start()
        # Local reference: if async_stop() (lock-free) closes the socket meanwhile, the closed
        # transport silently drops the retries and the request times out, as documented.
        transport = self._transport
        assert transport is not None
        loop = asyncio.get_running_loop()
        future: asyncio.Future[Reply] = loop.create_future()
        seqs: list[int] = []
        self.stats.requests += 1
        self._socket_error = None
        try:
            for attempt in range(attempts):
                if attempt:
                    self.stats.retries += 1
                    delay = self._retry_delays[min(attempt - 1, len(self._retry_delays) - 1)]
                    _LOGGER.debug("%s: no acknowledgement, retry %d in %.1f s", self._host, attempt, delay)
                    if not future.done():
                        await asyncio.sleep(delay)
                if not future.done():
                    seq = self._next_seq()
                    self._pending[seq] = future
                    seqs.append(seq)
                    frame = frame_for_seq(seq)
                    errors = self.stats.socket_errors
                    transport.sendto(frame)
                    # A send failure is reported through error_received(), at once by
                    # selector event loops, later by proactor ones.
                    if self.stats.socket_errors == errors:
                        self.stats.datagrams_sent += 1
                    _LOGGER.debug("%s: tx %s", self._host, frame.hex())
                sent_at = loop.time()
                try:
                    reply = await asyncio.wait_for(asyncio.shield(future), self._ack_timeout)
                except TimeoutError:
                    continue
                self.stats.record_rtt(loop.time() - sent_at)
                return self._check_reply(reply, op, element)
            self.stats.timeouts += 1
            if (error := self._socket_error) is not None:
                raise CololightConnectionError(f"{self._host}: {error}") from error
            raise CololightTimeout(f"{self._host} did not answer after {attempts} attempts")
        finally:
            for seq in seqs:
                self._pending.pop(seq, None)
            if not future.done():
                future.cancel()

    def _check_reply(self, reply: Reply, op: Op, element: Element) -> Reply:
        if reply.mac:
            if self._expected_mac is not None and reply.mac != self._expected_mac:
                # Final: retrying would only reach the same device again.
                self.stats.wrong_device += 1
                raise CololightWrongDevice(
                    f"{self._host} answered with MAC {reply.mac}, expected {self._expected_mac}"
                )
            self.mac = reply.mac
        if reply.op != op:
            raise ProtocolError(f"reply to operation {reply.op:#04x}, expected {op:#04x}")
        if reply.error:
            self.stats.rejected += 1
            raise CololightRejected(reply.element)
        if reply.element != element:
            raise ProtocolError(f"reply for element {reply.element:#04x}, expected {element:#04x}")
        return reply

    async def _read(self, element: Element) -> Reply:
        return await self._request(
            Op.READ, element, lambda seq: build_read(element, seq), self._read_attempts
        )

    async def _write(self, element: Element, data: bytes, save: bool) -> Reply:
        reply = await self._request(
            Op.WRITE_SAVE if save else Op.WRITE,
            element,
            lambda seq: build_write(element, data, seq, save=save),
            self._attempts,
        )
        if reply.data != data:
            # The acknowledgement carries what the lamp applied: trust it, but say so.
            self.stats.ack_mismatches += 1
            _LOGGER.warning(
                "%s: lamp applied %s instead of %s", self._host, reply.data.hex(), data.hex()
            )
        return reply

    # ------------------------------------------------------------------ API

    async def async_read_power(self) -> PowerState:
        async with self._lock:
            return decode_power((await self._read(Element.POWER)).data)

    async def async_read_mode(self) -> ModeState:
        async with self._lock:
            return decode_mode((await self._read(Element.MODE)).data)

    async def async_get_state(self) -> DeviceState:
        """Read power and mode (two requests, no command can slip in between)."""
        async with self._lock:
            power = decode_power((await self._read(Element.POWER)).data)
            mode = decode_mode((await self._read(Element.MODE)).data)
        return DeviceState(power=power, mode=mode)

    async def async_turn_on(self, brightness: int, *, save: bool = False) -> PowerState:
        """Turn on at ``brightness`` % (clamped to 1-100). Returns the acknowledged state."""
        async with self._lock:
            reply = await self._write(Element.POWER, power_on_data(brightness), save)
        return decode_power(reply.data)

    async def async_turn_off(self, *, save: bool = False) -> PowerState:
        async with self._lock:
            reply = await self._write(Element.POWER, power_off_data(), save)
        return decode_power(reply.data)

    async def async_set_color(self, rgb: tuple[int, int, int], *, save: bool = False) -> ModeState:
        async with self._lock:
            reply = await self._write(Element.MODE, color_data(rgb), save)
        return decode_mode(reply.data)

    async def async_set_effect(self, frames: Sequence[bytes], *, save: bool = False) -> ModeState:
        """Send an effect; multi-frame effects are sent frame by frame, each acknowledged.

        If a frame of a multi-frame effect other than the first had to be sent more than
        once, the lamp may have received it twice (only its acknowledgement was lost):
        the whole effect is then sent again, once, from its first frame.
        """
        if not frames:
            raise ValueError("an effect needs at least one frame")
        datas = [effect_data(f) for f in frames]
        async with self._lock:
            restarted = False
            index = 0
            reply = None
            while index < len(datas):
                sent = self.stats.datagrams_sent
                reply = await self._write(Element.MODE, datas[index], save)
                index += 1
                if index > 1 and not restarted and self.stats.datagrams_sent - sent > 1:
                    _LOGGER.debug(
                        "%s: frame %d of %d was sent more than once, sending the effect again",
                        self._host,
                        index,
                        len(datas),
                    )
                    self.stats.upload_restarts += 1
                    restarted = True
                    index = 0
        assert reply is not None
        return decode_mode(reply.data)

    async def async_save_state(self, power: PowerState, mode: ModeState) -> None:
        """Store a state in EEPROM (op 07) so the lamp boots with it after a power cut.

        The power element is only stored when on: a lamp saved "off" would stay dark
        when switched on at the wall. For a multi-frame effect the lamp only reports
        the last frame: re-send the whole effect with ``async_set_effect(..., save=True)``
        instead of calling this.
        """
        async with self._lock:
            await self._write(Element.MODE, bytes([0xFF]) + mode.code, True)
            if power.on and power.brightness is not None:
                await self._write(Element.POWER, power_on_data(power.brightness), True)


# ---------------------------------------------------------------------- discovery


@dataclass(frozen=True, slots=True)
class DiscoveredDevice:
    host: str
    mac: str  # "4C11AEB1B614"


class _DiscoveryProtocol(asyncio.DatagramProtocol):
    def __init__(self) -> None:
        self.found: dict[str, DiscoveredDevice] = {}

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        try:
            reply = parse_reply(data)
        except ProtocolError:
            return
        if reply.mac and reply.mac not in self.found:
            self.found[reply.mac] = DiscoveredDevice(host=addr[0], mac=reply.mac)

    def error_received(self, exc: Exception) -> None:
        _LOGGER.debug("discovery socket error: %s", exc)


async def async_discover(
    broadcast_addresses: Iterable[str],
    *,
    timeout: float = 2.0,
    port: int = PORT,
    repeats: int = 2,
) -> list[DiscoveredDevice]:
    """Broadcast a state request and collect the lamps that answer (with their MAC)."""
    targets = sorted({str(a) for a in broadcast_addresses})
    loop = asyncio.get_running_loop()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.setblocking(False)
    sock.bind(("", 0))
    transport, protocol = await loop.create_datagram_endpoint(_DiscoveryProtocol, sock=sock)
    try:
        for repeat in range(max(1, repeats)):
            frame = build_read(Element.POWER, random.randint(1, 255))
            for target in targets:
                # An unreachable target is reported to error_received(), not raised.
                transport.sendto(frame, (target, port))
            await asyncio.sleep(timeout / max(1, repeats))
    finally:
        transport.close()
    return list(protocol.found.values())


async def async_probe(host: str, *, port: int = PORT, timeout: float = 1.5, attempts: int = 2) -> DiscoveredDevice:
    """Check that ``host`` is a Cololight and return its MAC. Raises CololightError."""
    client = CololightClient(host, port=port, ack_timeout=timeout, read_attempts=attempts)
    try:
        await client.async_read_power()
    finally:
        await client.async_stop()
    if client.mac is None:
        raise ProtocolError(f"{host} answered without a MAC address")
    return DiscoveredDevice(host=host, mac=client.mac)
