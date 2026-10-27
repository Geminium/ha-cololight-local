"""Tests of the UDP client (custom_components/cololight_local/client.py) against FakeLamp.

Nothing here talks to a real lamp: every socket targets 127.0.0.1 (or 127.0.0.2).
Small acknowledgement timeouts and retry delays keep the tests fast; tests that count
retries which should not happen use a generous timeout (``patient_client``), so that a
slow test host cannot turn a late reply into a retry.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator, Awaitable, Callable, Generator, Sequence
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest
import pytest_socket

from custom_components.cololight_local import client as client_module
from custom_components.cololight_local.client import (
    DEFAULT_ACK_TIMEOUT,
    DEFAULT_ATTEMPTS,
    DEFAULT_READ_ATTEMPTS,
    DEFAULT_RETRY_DELAYS,
    ClientStats,
    CololightClient,
    CololightConnectionError,
    CololightRejected,
    CololightTimeout,
    CololightWrongDevice,
    DiscoveredDevice,
    async_discover,
    async_probe,
)
from custom_components.cololight_local.effects import DEFAULT_EFFECTS, STRIP_DYNAMIC_EFFECTS
from custom_components.cololight_local.protocol import (
    PORT,
    CololightError,
    DeviceState,
    Element,
    ModeState,
    Op,
    PowerState,
    ProtocolError,
    checksum,
)
from tests.fake_lamp import MAC, FakeLamp, Received

HOST = "127.0.0.1"
ACK_TIMEOUT = 0.1
RETRY_DELAYS = (0.01,)

SUNRISE = DEFAULT_EFFECTS["Sunrise"].frames
TRON = STRIP_DYNAMIC_EFFECTS["Tron"].frames
INITIAL_RGB = (255, 34, 34)  # FakeLamp default mode ff 00 ff 22 22


# ---------------------------------------------------------------------- helpers


def _reframe(frame: bytes | bytearray) -> bytes:
    """Recompute the length field and the checksum of a datagram."""
    out = bytearray(frame)
    out[8:10] = (len(out) - 10).to_bytes(2, "big")
    out[16:18] = checksum(out).to_bytes(2, "big")
    return bytes(out)


def _reply_frame(op: int, tlvs: bytes, *, seq: int = 1, mac: str = MAC) -> bytes:
    """A reply datagram as the lamp sends it (``op`` without the reply flag)."""
    frame = bytearray(38)
    frame[0:4] = b"SZ00"
    frame[4] = 0x80
    frame[26] = seq
    frame[36] = op | 0x80
    frame[37] = seq
    frame += tlvs + bytes([len(mac) + 1, 0x01]) + mac.encode("ascii")
    return _reframe(frame)


@dataclass
class ScriptedLamp(FakeLamp):
    """FakeLamp with extra misbehaviours, for the cases the real lamp never showed."""

    noise: Callable[[bytes], list[bytes]] | None = None  # extra datagrams sent before each reply
    reject_code: int | None = None  # answer every request with this error code
    reply_op: int | None = None  # force the operation of every reply
    reply_element: int | None = None  # force the element of every reply
    apply: Callable[[int, bytes], bytes] | None = None  # (element, requested) -> applied data
    in_flight: int = 0
    max_in_flight: int = 0
    noise_sent: list[bytes] = field(default_factory=list)

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        super().datagram_received(data, addr)

    def _handle(self, op: int, element: int | None, data: bytes) -> bytes:
        if self.reject_code is not None:
            return bytes([0x01, self.reject_code])
        if self.apply is not None and op in (Op.WRITE, Op.WRITE_SAVE) and element is not None:
            data = self.apply(element, data)
        return super()._handle(op, element, data)

    def _reply(self, op: int, seq: int, seq2: int, tlvs: bytes) -> bytes:
        if self.reply_op is not None:
            op = self.reply_op
        if self.reply_element is not None:
            tlvs = bytes([tlvs[0], self.reply_element]) + tlvs[2:]
        return super()._reply(op, seq, seq2, tlvs)

    def _send(self, frame: bytes, addr: tuple[str, int]) -> None:
        self.in_flight -= 1
        if self.noise is not None and self._transport is not None:
            for datagram in self.noise(frame):
                self.noise_sent.append(datagram)
                self._transport.sendto(datagram, addr)
        super()._send(frame, addr)


StartLamp = Callable[..., Awaitable[int]]
MakeClient = Callable[..., CololightClient]


@pytest.fixture
async def start_lamp(socket_enabled: None) -> AsyncGenerator[StartLamp]:
    """Start extra (possibly scripted) lamps; they are stopped after the test."""
    lamps: list[FakeLamp] = []

    async def _start(lamp: FakeLamp, host: str = HOST, port: int = 0) -> int:
        _host, bound = await lamp.start(host, port)
        lamps.append(lamp)
        return int(bound)

    yield _start
    for lamp in lamps:
        if lamp.delay:
            await asyncio.sleep(lamp.delay + 0.05)
        await lamp.stop()


@pytest.fixture
async def make_client(socket_enabled: None) -> AsyncGenerator[MakeClient]:
    """Build fast clients (small timeouts); their sockets are closed after the test."""
    clients: list[CololightClient] = []

    def _make(port: int, host: str = HOST, **kwargs: Any) -> CololightClient:
        kwargs.setdefault("ack_timeout", ACK_TIMEOUT)
        kwargs.setdefault("retry_delays", RETRY_DELAYS)
        client = CololightClient(host, port=port, **kwargs)
        clients.append(client)
        return client

    yield _make
    for client in clients:
        await client.async_stop()


@pytest.fixture
def client(make_client: MakeClient, fake_lamp_port: int) -> CololightClient:
    return make_client(fake_lamp_port)


@pytest.fixture
def patient_client(make_client: MakeClient, fake_lamp_port: int) -> CololightClient:
    """A client with a generous timeout, for tests counting retries that should not happen.

    The emulator answers within a millisecond, so these tests stay fast; a slow or loaded
    test host cannot turn a late reply into a retry.
    """
    return make_client(fake_lamp_port, ack_timeout=1.0)


@pytest.fixture
def allow_second_loopback(second_loopback: None) -> Generator[None]:
    """Also allow connect() to 127.0.0.2, to run a second lamp on the same port."""
    pytest_socket.socket_allow_hosts(["127.0.0.1", "127.0.0.2"])
    yield
    pytest_socket.socket_allow_hosts(["127.0.0.1"])


async def _exchange(port: int, frame: bytes) -> bytes:
    """Send one raw datagram to the emulator and return its answer."""
    loop = asyncio.get_running_loop()
    answer: asyncio.Future[bytes] = loop.create_future()

    class _Proto(asyncio.DatagramProtocol):
        def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
            if not answer.done():
                answer.set_result(data)

    transport, _ = await loop.create_datagram_endpoint(_Proto, remote_addr=(HOST, port))
    try:
        transport.sendto(frame)
        return await asyncio.wait_for(answer, 1)
    finally:
        transport.close()


# ---------------------------------------------------------------------- emulator fidelity

# Real request/reply pairs from logs/cololight-20261025.jsonl: the emulator must answer
# exactly like the strip (byte 35, maybe the WiFi signal, aside).
REAL_EXCHANGES = [
    pytest.param(
        "cf13",
        "535a303000000000001e000000000000000000000000000000002600000000000000000003020101",
        "535a303080000000002e000000000000044e00000000000000002600000000000000000083020301cf13"
        "0d01344331314145423142363134",
        id="read-power",
    ),
    pytest.param(
        "cf32",
        "535a3030000000000020000000000000000000000000000000002700000000000000000004010301ce1e",
        "535a303080000000002e000000000000045900000000000000002700000000000000000084010301ce1e"
        "0d01344331314145423142363134",
        id="off",
    ),
    pytest.param(
        "cf32",
        "535a3030000000000023000000000000000000000000000000002a00000000000000000004010602ff00ff0000",
        "535a3030800000000031000000000000057200000000000000002a00000000000000000084010602ff00ff0000"
        "0d01344331314145423142363134",
        id="red",
    ),
    pytest.param(
        "cf32",
        "535a303000000000002300000000000000000000000000000000c500000000000000000005010602ff0000ff05",
        "535a303080000000002c000000000000048b0000000000000000c500000000000000003f85010143"
        "0d01344331314145423142363134",
        id="unknown-op-05",
    ),
]


@pytest.mark.parametrize(("power", "request_hex", "reply_hex"), REAL_EXCHANGES)
async def test_emulator_answers_like_the_real_lamp(
    fake_lamp: FakeLamp, fake_lamp_port: int, power: str, request_hex: str, reply_hex: str
) -> None:
    fake_lamp.power = bytes.fromhex(power)
    answer = await _exchange(fake_lamp_port, bytes.fromhex(request_hex))
    real = bytearray(bytes.fromhex(reply_hex))
    real[35] = 0  # the emulator does not fill byte 35
    assert answer == _reframe(real)


# ---------------------------------------------------------------------- construction


def test_client_defaults() -> None:
    client = CololightClient(HOST)
    assert client.host == HOST
    assert client.port == PORT == 8900
    assert client.mac is None
    assert client.stats == ClientStats()
    assert DEFAULT_ACK_TIMEOUT == 1.5
    assert DEFAULT_ATTEMPTS == 4
    assert DEFAULT_READ_ATTEMPTS == 2
    assert DEFAULT_RETRY_DELAYS == (0.2, 0.5, 1.0)


def test_client_stats_record_rtt() -> None:
    stats = ClientStats()
    for i in range(60):
        stats.record_rtt(i / 100)
    assert stats.rtts == [i / 100 for i in range(10, 60)]
    assert stats.last_rtt == 0.59


def test_exceptions() -> None:
    for exc in (CololightTimeout, CololightConnectionError, CololightRejected, CololightWrongDevice):
        assert issubclass(exc, CololightError)
    err = CololightRejected(0x49)
    assert err.code == 0x49
    assert "0x49" in str(err)


# ---------------------------------------------------------------------- reading


async def test_get_state(fake_lamp: FakeLamp, patient_client: CololightClient) -> None:
    client = patient_client
    fake_lamp.power = bytes.fromhex("cf13")
    fake_lamp.mode = bytes.fromhex("ff00ff2222")
    state = await client.async_get_state()
    assert state == DeviceState(PowerState(True, 19), ModeState(bytes.fromhex("00ff2222")))
    assert state.mode.rgb == INITIAL_RGB
    assert client.mac == MAC
    assert [(r.op, r.element) for r in fake_lamp.received] == [(Op.READ, 1), (Op.READ, 2)]
    stats = client.stats
    assert (stats.requests, stats.datagrams_sent, stats.retries, stats.timeouts) == (2, 2, 0, 0)
    assert len(stats.rtts) == 2
    assert stats.last_rtt == stats.rtts[-1]


async def test_get_state_off_with_multi_frame_effect(fake_lamp: FakeLamp, client: CololightClient) -> None:
    fake_lamp.power = bytes.fromhex("ce1e")
    fake_lamp.mode = b"\xff" + TRON[-1]
    state = await client.async_get_state()
    assert state.power == PowerState(False, None)
    assert state.mode.code == TRON[-1]
    assert state.mode.is_multi_frame


async def test_read_power_and_mode(fake_lamp: FakeLamp, client: CololightClient) -> None:
    assert await client.async_read_power() == PowerState(True, 50)
    assert await client.async_read_mode() == ModeState(bytes.fromhex("00ff2222"))
    assert [r.element for r in fake_lamp.received] == [1, 2]


async def test_undecodable_state_raises_protocol_error(fake_lamp: FakeLamp, client: CololightClient) -> None:
    fake_lamp.power = bytes.fromhex("ab01")
    with pytest.raises(ProtocolError, match="power"):
        await client.async_read_power()
    fake_lamp.mode = bytes.fromhex("fe00000000")
    with pytest.raises(ProtocolError, match="mode"):
        await client.async_read_mode()


# ---------------------------------------------------------------------- commands


async def test_turn_off_and_on(fake_lamp: FakeLamp, client: CololightClient) -> None:
    assert await client.async_turn_off() == PowerState(False, None)
    assert not fake_lamp.is_on
    assert await client.async_turn_on(42) == PowerState(True, 42)
    assert fake_lamp.brightness == 42
    writes = [(w.op, w.element, w.data) for w in fake_lamp.writes()]
    assert writes == [(Op.WRITE, 1, bytes.fromhex("ce1e")), (Op.WRITE, 1, bytes.fromhex("cf2a"))]
    assert fake_lamp.saved_power == bytes([0xCF, 100])  # volatile writes leave the EEPROM alone


@pytest.mark.parametrize(("requested", "sent"), [(255, 100), (101, 100), (10_000, 100), (0, 1), (-3, 1)])
async def test_brightness_is_clamped(
    fake_lamp: FakeLamp, client: CololightClient, requested: int, sent: int
) -> None:
    assert await client.async_turn_on(requested) == PowerState(True, sent)
    assert fake_lamp.writes()[-1].data == bytes([0xCF, sent])
    assert not fake_lamp.crashed


async def test_never_sends_brightness_above_100(fake_lamp: FakeLamp, client: CololightClient) -> None:
    """255 made the real strip drop off WiFi until a power cut."""
    values = (1, 50, 100, 101, 150, 254, 255, 256, 10_000)
    for value in values:
        await client.async_turn_on(value)
        await client.async_turn_on(value, save=True)
    await client.async_save_state(PowerState(True, 255), ModeState(bytes.fromhex("00ffffff")))
    on_writes = [w for w in fake_lamp.writes() if w.element == Element.POWER and w.data[0] == 0xCF]
    assert len(on_writes) == 2 * len(values) + 1
    assert max(w.data[1] for w in on_writes) == 100
    assert max(w.raw[41] for w in on_writes) == 100
    assert not fake_lamp.crashed


async def test_set_color(fake_lamp: FakeLamp, client: CololightClient) -> None:
    fake_lamp.power = bytes([0xCF, 30])
    mode = await client.async_set_color((1, 2, 3))
    assert mode == ModeState(bytes.fromhex("00010203"))
    assert mode.rgb == (1, 2, 3)
    assert fake_lamp.mode == bytes.fromhex("ff00010203")
    assert fake_lamp.power == bytes([0xCF, 30])  # brightness kept
    write = fake_lamp.writes()[0]
    assert (write.op, write.element, write.data) == (Op.WRITE, 2, bytes.fromhex("ff00010203"))


async def test_invalid_color_sends_nothing(fake_lamp: FakeLamp, client: CololightClient) -> None:
    with pytest.raises(ValueError, match="out of range"):
        await client.async_set_color((256, 0, 0))
    assert fake_lamp.received == []
    assert client.stats.requests == 0


async def test_single_frame_effect(fake_lamp: FakeLamp, client: CololightClient) -> None:
    mode = await client.async_set_effect(SUNRISE)
    assert mode == ModeState(SUNRISE[0])
    assert fake_lamp.mode_code == SUNRISE[0]
    assert [w.data for w in fake_lamp.writes()] == [b"\xff" + SUNRISE[0]]


async def test_multi_frame_effect_each_frame_acknowledged(
    fake_lamp: FakeLamp, patient_client: CololightClient
) -> None:
    client = patient_client
    mode = await client.async_set_effect(TRON)
    assert mode.code == TRON[-1]
    assert mode.is_multi_frame
    writes = fake_lamp.writes()
    assert [w.data for w in writes] == [b"\xff" + f for f in TRON]
    assert all(w.op == Op.WRITE for w in writes)
    assert len({w.seq for w in writes}) == len(TRON)
    stats = client.stats
    assert (stats.requests, stats.datagrams_sent, stats.retries) == (6, 6, 0)
    # the lamp only reports the last frame
    assert (await client.async_read_mode()).code == TRON[-1]


async def test_multi_frame_effect_frames_sent_one_at_a_time(
    start_lamp: StartLamp, make_client: MakeClient
) -> None:
    lamp = ScriptedLamp(delay=0.01)
    client = make_client(await start_lamp(lamp))
    await client.async_set_effect(TRON)
    assert lamp.max_in_flight == 1  # frame n+1 only leaves once frame n is acknowledged
    assert [w.data for w in lamp.writes()] == [b"\xff" + f for f in TRON]


def _drop_once(frames: Sequence[bytes]) -> Callable[[Received], bool]:
    """A drop filter losing the first request of each of ``frames``, once."""
    pending = [b"\xff" + frame for frame in frames]

    def drop(request: Received) -> bool:
        if request.data in pending:
            pending.remove(request.data)
            return True
        return False

    return drop


async def test_multi_frame_effect_restarted_after_a_resent_frame(
    fake_lamp: FakeLamp, fake_lamp_port: int, make_client: MakeClient
) -> None:
    """A palette upload is a counted sequence: a frame sent twice restarts it, once.

    The lamp may have received the frame twice (only its acknowledgement was lost), so the
    whole effect is sent again from its first frame, the start marker.
    """
    client = make_client(fake_lamp_port, ack_timeout=0.3)
    fake_lamp.drop_filter = _drop_once([TRON[2]])
    mode = await client.async_set_effect(TRON)
    assert mode.code == TRON[-1]
    expected = [TRON[0], TRON[1], TRON[2], TRON[2], *TRON]
    assert [w.data for w in fake_lamp.writes()] == [b"\xff" + f for f in expected]
    stats = client.stats
    assert (stats.requests, stats.retries, stats.upload_restarts) == (3 + len(TRON), 1, 1)


async def test_multi_frame_effect_restarted_only_once(
    fake_lamp: FakeLamp, fake_lamp_port: int, make_client: MakeClient
) -> None:
    client = make_client(fake_lamp_port, ack_timeout=0.3)
    fake_lamp.drop_filter = _drop_once([TRON[3], TRON[-1]])
    assert (await client.async_set_effect(TRON)).code == TRON[-1]
    # Frame 3 lost: restart; in the 2nd pass the last frame is lost once: no more restart.
    expected = [*TRON[:4], TRON[3], *TRON, TRON[-1]]
    assert [w.data for w in fake_lamp.writes()] == [b"\xff" + f for f in expected]
    assert (client.stats.retries, client.stats.upload_restarts) == (2, 1)


async def test_lost_first_frame_or_single_frame_is_not_restarted(
    fake_lamp: FakeLamp, fake_lamp_port: int, make_client: MakeClient
) -> None:
    """Sending the start marker (or a single frame, an absolute value) twice is harmless."""
    client = make_client(fake_lamp_port, ack_timeout=0.3)
    fake_lamp.drop_filter = _drop_once([TRON[0], SUNRISE[0]])
    await client.async_set_effect(TRON)
    await client.async_set_effect(SUNRISE)
    expected = [TRON[0], *TRON, SUNRISE[0], SUNRISE[0]]
    assert [w.data for w in fake_lamp.writes()] == [b"\xff" + f for f in expected]
    assert client.stats.upload_restarts == 0


async def test_late_acknowledgement_of_a_palette_frame_restarts_the_upload(
    fake_lamp: FakeLamp, fake_lamp_port: int, make_client: MakeClient
) -> None:
    """The case the restart is for: the frame arrived, only its acknowledgement was late."""
    client = make_client(fake_lamp_port, ack_timeout=0.2, retry_delays=(0.01,))
    original_send = fake_lamp._send
    late = [b"\xff" + TRON[1]]

    def send(frame: bytes, addr: tuple[str, int]) -> None:
        if late and frame[40:45] == late[0]:
            late.clear()
            asyncio.get_running_loop().call_later(0.31, original_send, frame, addr)
        else:
            original_send(frame, addr)

    fake_lamp._send = send  # type: ignore[method-assign]
    await client.async_set_effect(TRON)
    await asyncio.sleep(0.35)  # let the 2nd acknowledgement of the frame arrive
    received = [w.data for w in fake_lamp.writes()]
    assert received == [b"\xff" + f for f in (TRON[0], TRON[1], TRON[1], *TRON)]
    assert client.stats.upload_restarts == 1


@pytest.mark.parametrize(
    ("frames", "message"),
    [
        ([], "at least one frame"),
        ([bytes.fromhex("00ff0000")], "cannot start with 00"),  # a static colour is not an effect
        ([SUNRISE[0], bytes.fromhex("01c10a")], "4 bytes"),  # 2nd frame invalid: nothing is sent
    ],
)
async def test_invalid_effect_sends_nothing(
    fake_lamp: FakeLamp, client: CololightClient, frames: list[bytes], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        await client.async_set_effect(frames)
    assert fake_lamp.received == []


# ---------------------------------------------------------------------- retries and timeouts


async def test_retry_on_lost_request(fake_lamp: FakeLamp, client: CololightClient) -> None:
    fake_lamp.drop_next = 2
    assert await client.async_turn_on(60) == PowerState(True, 60)
    received = fake_lamp.received
    assert len(received) == 3
    assert len({r.seq for r in received}) == 3  # every attempt has its own sequence number
    assert all(r.data == bytes([0xCF, 60]) for r in received)  # same absolute command
    stats = client.stats
    assert (stats.requests, stats.datagrams_sent, stats.retries, stats.timeouts) == (1, 3, 2, 0)


async def test_read_retry(fake_lamp: FakeLamp, client: CololightClient) -> None:
    fake_lamp.drop_next = 1
    assert await client.async_read_power() == PowerState(True, 50)
    assert client.stats.retries == 1


async def test_read_gives_up_after_read_attempts(fake_lamp: FakeLamp, client: CololightClient) -> None:
    fake_lamp.drop_next = 2
    with pytest.raises(CololightTimeout, match="after 2 attempts"):
        await client.async_read_power()
    assert len(fake_lamp.received) == DEFAULT_READ_ATTEMPTS


async def test_timeout_after_all_attempts(fake_lamp: FakeLamp, client: CololightClient) -> None:
    fake_lamp.crashed = True
    loop = asyncio.get_running_loop()
    started = loop.time()
    with pytest.raises(CololightTimeout, match="did not answer after 4 attempts"):
        await client.async_turn_off()
    elapsed = loop.time() - started
    assert elapsed >= DEFAULT_ATTEMPTS * ACK_TIMEOUT + 3 * RETRY_DELAYS[0] - 0.01
    stats = client.stats
    assert (stats.requests, stats.datagrams_sent, stats.retries, stats.timeouts) == (1, 4, 3, 1)
    assert stats.rtts == []
    assert stats.last_rtt is None
    assert len(fake_lamp.received) == DEFAULT_ATTEMPTS
    # the lamp comes back after a power cut: the same client simply works again
    fake_lamp.power_cycle()
    assert await client.async_read_power() == PowerState(True, 100)
    assert client.stats.timeouts == 1


async def test_retry_delays(fake_lamp: FakeLamp, fake_lamp_port: int, make_client: MakeClient) -> None:
    """Delays are taken in order; the last one is reused for further retries."""
    client = make_client(fake_lamp_port, ack_timeout=0.05, retry_delays=(0.02, 0.1))
    fake_lamp.crashed = True
    sleeps: list[float] = []
    real_sleep = asyncio.sleep

    async def spy_sleep(delay: float) -> None:
        sleeps.append(delay)
        await real_sleep(delay)

    loop = asyncio.get_running_loop()
    started = loop.time()
    with patch.object(client_module.asyncio, "sleep", spy_sleep), pytest.raises(CololightTimeout):
        await client.async_turn_off()
    elapsed = loop.time() - started
    assert sleeps == [0.02, 0.1, 0.1]
    # Only a lower bound: a loaded test host can be slower, never faster.
    assert elapsed >= 4 * 0.05 + 0.02 + 0.1 + 0.1 - 0.01


async def test_attempts_are_at_least_one(
    fake_lamp: FakeLamp, fake_lamp_port: int, make_client: MakeClient
) -> None:
    client = make_client(fake_lamp_port, attempts=0, read_attempts=0, retry_delays=())
    fake_lamp.crashed = True
    with pytest.raises(CololightTimeout, match="after 1 attempts"):
        await client.async_turn_off()
    with pytest.raises(CololightTimeout, match="after 1 attempts"):
        await client.async_read_power()
    assert len(fake_lamp.received) == 2


async def test_late_acknowledgement_is_accepted(
    fake_lamp: FakeLamp, fake_lamp_port: int, make_client: MakeClient
) -> None:
    # The acknowledgement of attempt 1 arrives 0.1 s after attempt 2 left, and 0.1 s
    # before attempt 2 times out: wide margins for a slow test host.
    client = make_client(fake_lamp_port, ack_timeout=0.2, retry_delays=(0.01,))
    fake_lamp.delay = 0.31
    assert await client.async_turn_on(70) == PowerState(True, 70)
    # attempt 1 timed out, attempt 2 was sent, then the late ACK of attempt 1 was accepted
    assert client.stats.retries == 1
    assert len(fake_lamp.received) == 2
    await asyncio.sleep(fake_lamp.delay + 0.05)  # the ACK of attempt 2 arrives too
    assert client.stats.late_replies == 1
    assert client.stats.timeouts == 0


async def test_ack_arriving_during_retry_pause_avoids_resend(
    fake_lamp: FakeLamp, fake_lamp_port: int, make_client: MakeClient
) -> None:
    client = make_client(fake_lamp_port, ack_timeout=0.1, retry_delays=(0.5,))
    fake_lamp.delay = 0.3  # after the 100 ms timeout, during the 500 ms pause
    assert await client.async_turn_on(20) == PowerState(True, 20)
    assert len(fake_lamp.received) == 1
    assert client.stats.datagrams_sent == 1
    assert client.stats.retries == 1


async def test_duplicate_replies_are_ignored(fake_lamp: FakeLamp, patient_client: CololightClient) -> None:
    client = patient_client
    fake_lamp.duplicate_replies = True
    await client.async_turn_on(10)
    await client.async_set_color((0, 0, 255))
    state = await client.async_get_state()
    assert state == DeviceState(PowerState(True, 10), ModeState(bytes.fromhex("000000ff")))
    await asyncio.sleep(0.02)
    stats = client.stats
    assert (stats.requests, stats.datagrams_sent, stats.retries) == (4, 4, 0)
    assert stats.late_replies == 4


async def test_reply_for_another_sequence_is_not_taken(
    start_lamp: StartLamp, make_client: MakeClient
) -> None:
    """A stray "off" acknowledgement (other sequence) must not be taken for the answer."""

    def stray_off_ack(frame: bytes) -> list[bytes]:
        return [_reply_frame(Op.WRITE, bytes.fromhex("0301ce1e"), seq=frame[26] ^ 0x80)]

    lamp = ScriptedLamp(noise=stray_off_ack)
    client = make_client(await start_lamp(lamp), ack_timeout=1.0)
    assert await client.async_turn_on(33) == PowerState(True, 33)
    assert await client.async_read_power() == PowerState(True, 33)
    assert client.stats.late_replies == 2
    assert client.stats.invalid_datagrams == 0


async def test_invalid_datagrams_are_ignored(start_lamp: StartLamp, make_client: MakeClient) -> None:
    def junk(frame: bytes) -> list[bytes]:
        bad_checksum = bytearray(frame)
        bad_checksum[-1] ^= 0xFF
        not_a_reply = bytearray(frame)
        not_a_reply[4] = 0x00
        return [b"hello", bytes(bad_checksum), _reframe(not_a_reply), frame[:30], frame + b"\x00"]

    lamp = ScriptedLamp(noise=junk)
    # A generous timeout: a stalled event loop must not turn the reply into a retry.
    client = make_client(await start_lamp(lamp), ack_timeout=1.0)
    state = await client.async_get_state()
    assert state.power == PowerState(True, 50)
    assert client.stats.invalid_datagrams == 10
    assert client.stats.datagrams_sent == client.stats.requests == 2
    assert client.stats.late_replies == 0


async def test_unreachable_port_fails_cleanly(start_lamp: StartLamp, make_client: MakeClient) -> None:
    """Nothing listens any more: a clean error after every attempt, no crash.

    The ICMP "port unreachable" answer is reported to the socket on most systems (then the
    error says so); otherwise the request simply times out.
    """
    lamp = FakeLamp()
    port = await start_lamp(lamp)
    await lamp.stop()
    client = make_client(port, attempts=3)
    with pytest.raises((CololightConnectionError, CololightTimeout)):
        await client.async_turn_off()
    assert client.stats.requests == 1
    assert client.stats.timeouts == 1


# ---------------------------------------------------------------------- lamp answers


async def test_rejected_request(start_lamp: StartLamp, make_client: MakeClient) -> None:
    lamp = ScriptedLamp(reject_code=0x43)
    client = make_client(await start_lamp(lamp))
    with pytest.raises(CololightRejected) as exc_info:
        await client.async_set_color((1, 2, 3))
    assert exc_info.value.code == 0x43
    assert "0x43" in str(exc_info.value)
    assert client.stats.rejected == 1
    assert client.stats.datagrams_sent == 1  # an error answer is final: no retry
    assert client.mac == MAC  # the MAC trailer is read even from an error
    assert lamp.mode == FakeLamp().mode  # nothing applied
    with pytest.raises(CololightRejected):
        await client.async_read_power()
    assert client.stats.rejected == 2


async def test_reply_to_another_operation(start_lamp: StartLamp, make_client: MakeClient) -> None:
    client = make_client(await start_lamp(ScriptedLamp(reply_op=Op.READ)))
    with pytest.raises(ProtocolError, match="operation"):
        await client.async_turn_off()
    assert client.stats.datagrams_sent == 1


async def test_reply_for_another_element(start_lamp: StartLamp, make_client: MakeClient) -> None:
    client = make_client(await start_lamp(ScriptedLamp(reply_element=Element.MODE)))
    with pytest.raises(ProtocolError, match="element"):
        await client.async_read_power()


async def test_ack_mismatch_is_trusted_and_counted(
    start_lamp: StartLamp, make_client: MakeClient, caplog: pytest.LogCaptureFixture
) -> None:
    def cap_at_80(element: int, data: bytes) -> bytes:
        if element == Element.POWER and data[0] == 0xCF:
            return bytes([0xCF, min(data[1], 80)])
        return data

    lamp = ScriptedLamp(apply=cap_at_80)
    client = make_client(await start_lamp(lamp))
    with caplog.at_level(logging.WARNING, logger=client_module.__name__):
        state = await client.async_turn_on(90)
    assert state == PowerState(True, 80)  # the state comes from the acknowledgement
    assert client.stats.ack_mismatches == 1
    assert "applied cf50 instead of cf5a" in caplog.text
    assert await client.async_turn_on(50) == PowerState(True, 50)
    assert client.stats.ack_mismatches == 1


# ---------------------------------------------------------------------- EEPROM save (op 07)


async def test_save_survives_power_cycle(fake_lamp: FakeLamp, client: CololightClient) -> None:
    await client.async_turn_on(30, save=True)
    await client.async_set_color((255, 128, 0), save=True)
    assert [w.op for w in fake_lamp.writes()] == [Op.WRITE_SAVE, Op.WRITE_SAVE]
    await client.async_turn_on(80)  # volatile changes on top
    await client.async_set_color((0, 0, 255))
    fake_lamp.power_cycle()
    state = await client.async_get_state()
    assert state == DeviceState(PowerState(True, 30), ModeState(bytes.fromhex("00ff8000")))


async def test_volatile_writes_are_lost_on_power_cycle(fake_lamp: FakeLamp, client: CololightClient) -> None:
    await client.async_turn_off()
    await client.async_set_color((0, 255, 0))
    fake_lamp.power_cycle()
    state = await client.async_get_state()
    assert state == DeviceState(PowerState(True, 100), ModeState(bytes.fromhex("00ff2222")))


async def test_turn_off_saved(fake_lamp: FakeLamp, client: CololightClient) -> None:
    assert await client.async_turn_off(save=True) == PowerState(False, None)
    assert fake_lamp.writes()[0].op == Op.WRITE_SAVE
    assert fake_lamp.saved_power == bytes.fromhex("ce1e")


async def test_save_state(fake_lamp: FakeLamp, client: CololightClient) -> None:
    power, mode = PowerState(True, 40), ModeState(SUNRISE[0])
    await client.async_save_state(power, mode)
    writes = [(w.op, w.element, w.data) for w in fake_lamp.writes()]
    assert writes == [
        (Op.WRITE_SAVE, Element.MODE, b"\xff" + SUNRISE[0]),  # mode first
        (Op.WRITE_SAVE, Element.POWER, bytes([0xCF, 40])),
    ]
    await client.async_turn_off()
    fake_lamp.power_cycle()
    assert await client.async_get_state() == DeviceState(power, mode)


@pytest.mark.parametrize("power", [PowerState(False, None), PowerState(True, None)])
async def test_save_state_while_off_keeps_the_saved_power(
    fake_lamp: FakeLamp, client: CololightClient, power: PowerState
) -> None:
    """A lamp saved "off" would stay dark when switched on at the wall: power is not stored."""
    await client.async_save_state(power, ModeState(bytes.fromhex("000000ff")))
    assert [(w.op, w.element) for w in fake_lamp.writes()] == [(Op.WRITE_SAVE, Element.MODE)]
    assert fake_lamp.saved_power == bytes([0xCF, 100])
    fake_lamp.power_cycle()
    state = await client.async_get_state()
    assert state.power == PowerState(True, 100)
    assert state.mode.rgb == (0, 0, 255)


async def test_save_multi_frame_effect(fake_lamp: FakeLamp, client: CololightClient) -> None:
    await client.async_set_effect(TRON, save=True)
    writes = fake_lamp.writes()
    assert len(writes) == len(TRON)
    assert all(w.op == Op.WRITE_SAVE for w in writes)
    await client.async_set_color((1, 1, 1))
    fake_lamp.power_cycle()
    assert (await client.async_read_mode()).code == TRON[-1]


# ---------------------------------------------------------------------- concurrency


async def test_concurrent_calls_are_serialized(start_lamp: StartLamp, make_client: MakeClient) -> None:
    lamp = ScriptedLamp(delay=0.002)
    client = make_client(await start_lamp(lamp), ack_timeout=0.5)
    calls: list[Awaitable[Any]] = []
    for i in range(1, 21):
        calls += [client.async_turn_on(i), client.async_get_state(), client.async_set_color((i, 0, 0))]
    results = await asyncio.gather(*calls)

    assert lamp.max_in_flight == 1  # one request in flight at a time
    stats = client.stats
    assert (stats.requests, stats.retries, stats.timeouts, stats.late_replies) == (80, 0, 0, 0)
    # the lock is fair: the lamp saw the commands in the order they were issued...
    assert [w.data[1] for w in lamp.writes() if w.element == Element.POWER] == list(range(1, 21))
    # ...and nothing slipped between the two reads of a get_state
    for i in range(1, 21):
        turned_on, state, color = results[3 * (i - 1) : 3 * i]
        assert turned_on == PowerState(True, i)
        assert state.power == PowerState(True, i)
        assert state.mode.rgb == ((i - 1, 0, 0) if i > 1 else INITIAL_RGB)
        assert color.rgb == (i, 0, 0)
    assert lamp.power == bytes([0xCF, 20])
    assert lamp.mode == bytes([0xFF, 0x00, 20, 0, 0])


async def test_concurrent_calls_with_packet_loss(fake_lamp: FakeLamp, client: CololightClient) -> None:
    seen: set[int] = set()

    def lose_every_third_new_request(request: Received) -> bool:
        if request.seq in seen:
            return False
        seen.add(request.seq)
        return len(seen) % 3 == 0

    fake_lamp.drop_filter = lose_every_third_new_request
    results = await asyncio.gather(*(client.async_turn_on(b) for b in range(1, 16)))
    assert results == [PowerState(True, b) for b in range(1, 16)]
    assert fake_lamp.brightness == 15
    # 15 requests + r retries, one new datagram in three lost: r = (15 + r) // 3, so r = 7
    assert client.stats.retries == 7
    assert client.stats.timeouts == 0


# ---------------------------------------------------------------------- socket and host


async def test_socket_lifecycle(fake_lamp: FakeLamp, client: CololightClient) -> None:
    await client.async_start()
    await client.async_start()  # idempotent
    await client.async_read_power()
    await client.async_stop()
    await client.async_stop()  # idempotent
    assert client._transport is None
    # A stopped client never reopens a socket (an unloaded entry must stay silent).
    with pytest.raises(CololightConnectionError, match="stopped"):
        await client.async_read_power()
    with pytest.raises(CololightConnectionError, match="stopped"):
        await client.async_start()
    assert client._transport is None
    assert len(fake_lamp.received) == 1


async def test_stop_during_a_request(fake_lamp: FakeLamp, client: CololightClient) -> None:
    """Unloading closes the socket without waiting for the lock: the pending request
    then fails with a timeout (as documented), not with an unexpected exception."""
    fake_lamp.crashed = True
    task = asyncio.create_task(client.async_turn_off())
    await asyncio.sleep(ACK_TIMEOUT / 2)  # attempt 1 sent, waiting for its acknowledgement
    await client.async_stop()
    with pytest.raises(CololightTimeout):
        await task
    assert len(fake_lamp.received) == 1  # nothing left the closed socket
    fake_lamp.crashed = False
    with pytest.raises(CololightConnectionError):
        await client.async_read_power()  # no new socket either
    assert len(fake_lamp.received) == 1
    assert client._transport is None


async def test_sequence_numbers_wrap_and_skip_zero(
    fake_lamp: FakeLamp, fake_lamp_port: int, make_client: MakeClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(client_module, "random", SimpleNamespace(randint=lambda a, b: 254))
    client = make_client(fake_lamp_port)
    for _ in range(3):
        await client.async_read_power()
    assert [r.seq for r in fake_lamp.received] == [255, 1, 2]
    assert [r.raw[37] for r in fake_lamp.received] == [255, 1, 2]


async def test_rtt_history_is_capped(patient_client: CololightClient) -> None:
    client = patient_client
    for _ in range(55):
        await client.async_read_power()
    assert len(client.stats.rtts) == 50
    assert client.stats.last_rtt == client.stats.rtts[-1]
    assert all(0 <= rtt < client._ack_timeout for rtt in client.stats.rtts)


async def test_set_host(start_lamp: StartLamp, make_client: MakeClient, allow_second_loopback: None) -> None:
    """The lamp moved to another address (same port): the client follows."""
    lamp_a = FakeLamp(mac="AAAAAAAAAAAA")
    port = await start_lamp(lamp_a, "127.0.0.1")
    lamp_b = FakeLamp(mac="BBBBBBBBBBBB")
    await start_lamp(lamp_b, "127.0.0.2", port)
    client = make_client(port)
    await client.async_read_power()
    assert client.mac == "AAAAAAAAAAAA"
    await client.async_set_host("127.0.0.2")
    assert client.host == "127.0.0.2"
    assert client.port == port
    await client.async_read_power()
    assert client.mac == "BBBBBBBBBBBB"
    assert (len(lamp_a.received), len(lamp_b.received)) == (1, 1)


@pytest.mark.parametrize("expected_mac", [MAC, "4c:11:ae:b1:b6:14", "4C-11-AE-B1-B6-14"])
async def test_expected_mac_accepts_the_lamp(
    fake_lamp: FakeLamp, fake_lamp_port: int, make_client: MakeClient, expected_mac: str
) -> None:
    client = make_client(fake_lamp_port, expected_mac=expected_mac)
    assert await client.async_read_power() == PowerState(True, 50)
    assert client.mac == MAC


async def test_reply_from_another_device(start_lamp: StartLamp, make_client: MakeClient) -> None:
    """Two lamps swapped their addresses: the other lamp's replies are refused, at once."""
    other = FakeLamp(mac="4C11AE000001")
    client = make_client(await start_lamp(other), expected_mac=MAC)
    with pytest.raises(CololightWrongDevice, match="4C11AE000001"):
        await client.async_get_state()
    with pytest.raises(CololightWrongDevice):
        await client.async_turn_off()
    assert client.mac is None
    stats = client.stats
    assert (stats.datagrams_sent, stats.retries, stats.wrong_device) == (2, 0, 2)  # no retry
    # Without an expected MAC (probe, discovery), any lamp is accepted.
    probe = make_client(await start_lamp(FakeLamp(mac="4C11AE000002")))
    assert await probe.async_read_power() == PowerState(True, 50)
    assert probe.mac == "4C11AE000002"


async def test_set_host_waits_for_the_request_in_flight(fake_lamp: FakeLamp, client: CololightClient) -> None:
    fake_lamp.delay = 0.05
    task = asyncio.create_task(client.async_turn_on(15))
    await asyncio.sleep(0)  # the command takes the lock
    await client.async_set_host(HOST)
    assert task.done()
    assert task.result() == PowerState(True, 15)
    assert await client.async_read_power() == PowerState(True, 15)


async def test_cannot_open_socket(make_client: MakeClient) -> None:
    loop = asyncio.get_running_loop()
    client = make_client(PORT)
    failure = OSError(99, "Cannot assign requested address")
    with (
        patch.object(loop, "create_datagram_endpoint", side_effect=failure),
        pytest.raises(CololightConnectionError, match="cannot open UDP socket"),
    ):
        await client.async_get_state()
    assert client.stats.requests == 0


def _failing_sendto(
    transport: asyncio.DatagramTransport, error: OSError, *, later: bool = False
) -> list[bytes]:
    """Make a real transport fail its sends the way asyncio reports it.

    asyncio datagram transports never raise OSError from sendto(): they pass it to the
    protocol's error_received(), at once (selector event loops) or later (proactor ones).
    """
    attempted: list[bytes] = []
    protocol = transport.get_protocol()
    loop = asyncio.get_running_loop()

    def sendto(data: bytes, addr: Any = None) -> None:
        attempted.append(data)
        if later:
            loop.call_soon(protocol.error_received, error)
        else:
            protocol.error_received(error)

    transport.sendto = sendto  # type: ignore[method-assign]
    return attempted


async def test_send_failure_raises_connection_error(
    fake_lamp: FakeLamp, client: CololightClient
) -> None:
    """Every send fails (e.g. network unreachable): every attempt, then a clear error."""
    await client.async_start()
    assert client._transport is not None
    attempted = _failing_sendto(client._transport, OSError(101, "Network is unreachable"))
    with pytest.raises(CololightConnectionError, match="Network is unreachable"):
        await client.async_turn_off()
    assert len(attempted) == DEFAULT_ATTEMPTS
    assert fake_lamp.received == []
    stats = client.stats
    assert (stats.datagrams_sent, stats.retries, stats.timeouts, stats.socket_errors) == (0, 3, 1, 4)


async def test_socket_error_reported_later_raises_connection_error(
    fake_lamp: FakeLamp, client: CololightClient
) -> None:
    await client.async_start()
    assert client._transport is not None
    _failing_sendto(client._transport, OSError(101, "Network is unreachable"), later=True)
    with pytest.raises(CololightConnectionError, match="Network is unreachable"):
        await client.async_turn_off()
    # Handed to the socket without an immediate error: counted as sent.
    assert client.stats.datagrams_sent == DEFAULT_ATTEMPTS


async def test_socket_error_of_an_earlier_request_is_forgotten(
    fake_lamp: FakeLamp, client: CololightClient
) -> None:
    await client.async_start()
    assert client._transport is not None
    client._transport.get_protocol().error_received(ConnectionRefusedError())
    fake_lamp.crashed = True
    with pytest.raises(CololightTimeout):
        await client.async_turn_off()


# ---------------------------------------------------------------------- probe


async def test_probe(fake_lamp: FakeLamp, fake_lamp_port: int) -> None:
    device = await async_probe(HOST, port=fake_lamp_port, timeout=0.2)
    assert device == DiscoveredDevice(host=HOST, mac=MAC)
    assert [(r.op, r.element) for r in fake_lamp.received] == [(Op.READ, Element.POWER)]


async def test_probe_lower_case_mac(start_lamp: StartLamp) -> None:
    port = await start_lamp(FakeLamp(mac="4c11aeb1b614"))
    assert (await async_probe(HOST, port=port, timeout=0.2)).mac == MAC


async def test_probe_silent_host(fake_lamp: FakeLamp, fake_lamp_port: int) -> None:
    fake_lamp.crashed = True
    with pytest.raises(CololightTimeout):
        await async_probe(HOST, port=fake_lamp_port, timeout=0.05, attempts=2)
    assert len(fake_lamp.received) == 2


async def test_probe_reply_without_mac(start_lamp: StartLamp) -> None:
    port = await start_lamp(FakeLamp(mac=""))
    with pytest.raises(ProtocolError, match="without a MAC"):
        await async_probe(HOST, port=port, timeout=0.2)


# ---------------------------------------------------------------------- discovery


async def test_discover(fake_lamp: FakeLamp, fake_lamp_port: int) -> None:
    devices = await async_discover([HOST, HOST], port=fake_lamp_port, timeout=0.2)
    assert devices == [DiscoveredDevice(host=HOST, mac=MAC)]  # one entry despite two answers
    # two repeats, duplicate targets merged, a state request each time
    assert [(r.op, r.element) for r in fake_lamp.received] == [(Op.READ, Element.POWER)] * 2


async def test_discover_nothing(fake_lamp: FakeLamp, fake_lamp_port: int) -> None:
    fake_lamp.crashed = True
    assert await async_discover([HOST], port=fake_lamp_port, timeout=0.1, repeats=0) == []
    assert len(fake_lamp.received) == 1  # at least one round


async def test_discover_no_target(socket_enabled: None) -> None:
    assert await async_discover([], timeout=0.01) == []


async def test_discover_several_lamps(start_lamp: StartLamp, second_loopback: None) -> None:
    port = await start_lamp(FakeLamp(mac="AAAAAAAAAAAA"), "127.0.0.1")
    await start_lamp(FakeLamp(mac="BBBBBBBBBBBB"), "127.0.0.2", port)
    devices = await async_discover(["127.0.0.2", "127.0.0.1"], port=port, timeout=0.2)
    assert sorted(devices, key=lambda d: d.host) == [
        DiscoveredDevice(host="127.0.0.1", mac="AAAAAAAAAAAA"),
        DiscoveredDevice(host="127.0.0.2", mac="BBBBBBBBBBBB"),
    ]


async def test_discover_ignores_invalid_replies(start_lamp: StartLamp) -> None:
    lamp = ScriptedLamp(noise=lambda frame: [b"junk", frame[:-1]])
    port = await start_lamp(lamp)
    assert await async_discover([HOST], port=port, timeout=0.1) == [DiscoveredDevice(host=HOST, mac=MAC)]
    assert len(lamp.noise_sent) == 4


async def test_discover_ignores_replies_without_mac(start_lamp: StartLamp) -> None:
    port = await start_lamp(FakeLamp(mac=""))
    assert await async_discover([HOST], port=port, timeout=0.1) == []


async def test_discover_send_errors_are_ignored(fake_lamp: FakeLamp, fake_lamp_port: int) -> None:
    """A target that cannot be reached does not stop the others.

    A real transport reports the failed send to the protocol's error_received() (as for
    the broadcast address of a network that is down); it is simulated for the TEST-NET
    address, which is never really sent to.
    """
    loop = asyncio.get_running_loop()
    real_endpoint = loop.create_datagram_endpoint
    attempted: list[str] = []

    async def endpoint(factory: Callable[[], asyncio.DatagramProtocol], **kwargs: Any) -> tuple[Any, Any]:
        transport, protocol = await real_endpoint(factory, **kwargs)
        real_sendto = transport.sendto

        def sendto(data: bytes, addr: tuple[str, int]) -> None:
            attempted.append(addr[0])
            if addr[0] == "192.0.2.255":
                protocol.error_received(OSError(101, "Network is unreachable"))
            else:
                real_sendto(data, addr)

        transport.sendto = sendto
        return transport, protocol

    with patch.object(loop, "create_datagram_endpoint", endpoint):
        devices = await async_discover(["192.0.2.255", HOST], port=fake_lamp_port, timeout=0.2)
    assert devices == [DiscoveredDevice(host=HOST, mac=MAC)]
    assert sorted(attempted) == [HOST, HOST, "192.0.2.255", "192.0.2.255"]  # 2 targets x 2 repeats
