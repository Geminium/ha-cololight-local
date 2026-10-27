"""Tests of the frame codec (custom_components/cololight_local/protocol.py).

Every ``REAL_*`` frame below was captured on the real strip on 2026-10-25 and copied
verbatim from ``logs/cololight-20261025.jsonl`` (field ``hex``, kind ``tx``/``rx``).
The requests were sent by the probe tool with the pycololight layout: checksum 0 and
byte 37 = 01 (write) / 02 (read). Our builder fills the checksum and puts the sequence
in byte 37 (both ignored by the lamp, see docs/findings.md 3.1), so requests are
compared field by field.
"""

from __future__ import annotations

import pytest

from custom_components.cololight_local.protocol import (
    BRIGHTNESS_MAX,
    BRIGHTNESS_MIN,
    FLAG_REPLY,
    HEADER_LEN,
    MAGIC,
    PORT,
    DeviceState,
    Element,
    ModeState,
    Op,
    PowerState,
    ProtocolError,
    build_frame,
    build_read,
    build_write,
    checksum,
    clamp_brightness,
    color_data,
    decode_mode,
    decode_power,
    effect_data,
    format_mac,
    parse_reply,
    power_off_data,
    power_on_data,
    tlv,
)

MAC = "4C11AEB1B614"
MAC_TRAILER = bytes.fromhex("0d01") + MAC.encode("ascii")

# ------------------------------------------------------------------ real requests (tx)

# read element 01, seq 0x26, byte 37 = 02 (16:34:04.677, label etape0)
REAL_TX_READ_POWER = "535a303000000000001e000000000000000000000000000000002600000000000000000003020101"
# read element 02, seq 0xfa (16:57:24.082, label read-probe)
REAL_TX_READ_MODE = "535a303000000000001e00000000000000000000000000000000fa00000000000000000003020102"
# off, seq 0x27 (16:37:25.524, label etape1-off)
REAL_TX_OFF = "535a3030000000000020000000000000000000000000000000002700000000000000000004010301ce1e"
# on at 50 %, seq 0x28 (16:38:49.704, label etape1-bright50)
REAL_TX_ON_50 = "535a3030000000000020000000000000000000000000000000002800000000000000000004010301cf32"
# static red, seq 0x2a (16:39:44.205, label etape1-rouge)
REAL_TX_RED = "535a3030000000000023000000000000000000000000000000002a00000000000000000004010602ff00ff0000"
# on at 30 % saved in EEPROM (op 07), seq 0xf2 (17:52:46.275, label persist-op07)
REAL_TX_SAVE_ON_30 = "535a303000000000002000000000000000000000000000000000f200000000000000000007010301cf1e"
# same layout but with a correct checksum 0x01b2 (17:37:33.310, label cksum-ok)
REAL_TX_CHECKSUM_OK = "535a303000000000002000000000000001b20000000000000000bc00000000000000000004010301cf1e"

# ------------------------------------------------------------------ real replies (rx)

# state: on, brightness 19 (0x13), seq 0x26 (16:34:04.927)
REAL_RX_STATE_ON_19 = (
    "535a303080000000002e000000000000044e00000000000000002600000000000000000083020301cf13"
    "0d01344331314145423142363134"
)
# acknowledgement of "off", seq 0x27 (16:37:25.831)
REAL_RX_ACK_OFF = (
    "535a303080000000002e000000000000045900000000000000002700000000000000000084010301ce1e"
    "0d01344331314145423142363134"
)
# acknowledgement of "static red", seq 0x2a (16:39:44.373)
REAL_RX_ACK_RED = (
    "535a3030800000000031000000000000057200000000000000002a00000000000000000084010602ff00ff0000"
    "0d01344331314145423142363134"
)
# mode read: static #ff2222, byte 35 = 0x40 (signal?), seq 0xfa (16:57:24.491)
REAL_RX_MODE_FF2222 = (
    "535a303080000000003100000000000006c60000000000000000fa00000000000000004083020602ff00ff2222"
    "0d01344331314145423142363134"
)
# mode read: effect "Sunrise" 01c10a00, seq 0xfd (16:59:52.575)
REAL_RX_MODE_SUNRISE = (
    "535a303080000000003100000000000006510000000000000000fd00000000000000003f83020602ff01c10a00"
    "0d01344331314145423142363134"
)
# mode read after "Tron" (6 frames): only the last frame 9300ff64 is reported, seq 0xfe (17:19:09.026)
REAL_RX_MODE_TRON_LAST = (
    "535a3030800000000031000000000000077d0000000000000000fe00000000000000004083020602ff9300ff64"
    "0d01344331314145423142363134"
)
# acknowledgement of op 07 (write + EEPROM) on element 02, seq 0xcb (17:50:40.229)
REAL_RX_ACK_SAVE_MODE = (
    "535a3030800000000031000000000000065d0000000000000000cb00000000000000004087010602ff0000ff07"
    "0d01344331314145423142363134"
)
# acknowledgement of op 07 on element 01 (on, 30 %), seq 0xf2 (17:52:46.493)
REAL_RX_ACK_SAVE_ON_30 = (
    "535a303080000000002e00000000000005670000000000000000f200000000000000003f87010301cf1e"
    "0d01344331314145423142363134"
)
# element 03 (unknown) read, seq 0x3c (17:24:43.987)
REAL_RX_ELEMENT_03 = (
    "535a303080000000003100000000000004c400000000000000003c00000000000000003f83020603fe00000000"
    "0d01344331314145423142363134"
)
# element 04 does not exist: data 1e, seq 0x3d (17:24:45.519)
REAL_RX_ELEMENT_04 = (
    "535a303080000000002d00000000000003e200000000000000003d00000000000000003f830202041e"
    "0d01344331314145423142363134"
)
# unknown op 05 -> error TLV "01 43", seq 0xc5 (17:50:30.086)
REAL_RX_ERROR_43 = (
    "535a303080000000002c000000000000048b0000000000000000c500000000000000003f85010143"
    "0d01344331314145423142363134"
)
# unknown op 0b -> error TLV "01 49", seq 0xd7 (17:51:00.191)
REAL_RX_ERROR_49 = (
    "535a303080000000002c00000000000004aa0000000000000000d70000000000000000408b010149"
    "0d01344331314145423142363134"
)
# op 09 (device info): 24-byte block holding the binary MAC, seq 0xd1 (17:50:50.361)
REAL_RX_INFO = (
    "535a30308000000000430000000000000ab40000000000000000d10000000000000000408901180100ff0501004c11"
    "aeb1b614000000000000464c11aeb1b60d01344331314145423142363134"
)

ALL_REAL_REPLIES = [
    REAL_RX_STATE_ON_19,
    REAL_RX_ACK_OFF,
    REAL_RX_ACK_RED,
    REAL_RX_MODE_FF2222,
    REAL_RX_MODE_SUNRISE,
    REAL_RX_MODE_TRON_LAST,
    REAL_RX_ACK_SAVE_MODE,
    REAL_RX_ACK_SAVE_ON_30,
    REAL_RX_ELEMENT_03,
    REAL_RX_ELEMENT_04,
    REAL_RX_ERROR_43,
    REAL_RX_ERROR_49,
    REAL_RX_INFO,
]


def _reply(op: int, tlvs: bytes, *, seq: int = 0x10, seq2: int = 0x01, flag: int = FLAG_REPLY) -> bytes:
    """Build a reply datagram with a correct length field and checksum."""
    frame = bytearray(HEADER_LEN)
    frame[0:4] = MAGIC
    frame[4] = flag
    frame[26] = seq
    frame[36] = op
    frame[37] = seq2
    frame += tlvs
    frame[8:10] = (len(frame) - 10).to_bytes(2, "big")
    frame[16:18] = checksum(frame).to_bytes(2, "big")
    return bytes(frame)


def _refresh(frame: bytes | bytearray) -> bytes:
    """Recompute the length field and the checksum of a modified datagram."""
    out = bytearray(frame)
    out[8:10] = (len(out) - 10).to_bytes(2, "big")
    out[16:18] = checksum(out).to_bytes(2, "big")
    return bytes(out)


def _assert_same_request(ours: bytes, real_hex: str, seq: int) -> None:
    """Our request equals the captured one except checksum (16-17) and byte 37."""
    real = bytes.fromhex(real_hex)
    assert len(ours) == len(real)
    assert ours[0:4] == real[0:4] == MAGIC
    assert ours[4:16] == real[4:16]  # flags, length field, zeros
    assert ours[18:37] == real[18:37]  # zeros, sequence at 26, op at 36
    assert ours[38:] == real[38:]  # TLV blocks
    assert ours[26] == real[26] == seq
    assert ours[37] == seq  # our secondary sequence, echoed by the lamp, no effect
    assert int.from_bytes(ours[16:18], "big") == checksum(ours)
    differing = {i for i, (a, b) in enumerate(zip(ours, real, strict=True)) if a != b}
    assert differing <= {16, 17, 37}


# ------------------------------------------------------------------ constants


def test_constants() -> None:
    assert PORT == 8900
    assert MAGIC == b"SZ00"
    assert HEADER_LEN == 38
    assert (BRIGHTNESS_MIN, BRIGHTNESS_MAX) == (1, 100)
    assert (Op.READ, Op.WRITE, Op.WRITE_SAVE) == (0x03, 0x04, 0x07)
    assert (Element.POWER, Element.MODE) == (0x01, 0x02)


# ------------------------------------------------------------------ checksum


@pytest.mark.parametrize("frame_hex", ALL_REAL_REPLIES)
def test_checksum_matches_every_real_reply(frame_hex: str) -> None:
    frame = bytes.fromhex(frame_hex)
    assert checksum(frame) == int.from_bytes(frame[16:18], "big")


def test_checksum_of_real_request() -> None:
    frame = bytes.fromhex(REAL_TX_CHECKSUM_OK)
    assert checksum(frame) == 0x01B2


def test_checksum_ignores_header_bytes_before_18() -> None:
    frame = bytearray(bytes.fromhex(REAL_RX_ACK_OFF))
    before = checksum(frame)
    frame[0:18] = b"\xff" * 18
    assert checksum(frame) == before


def test_checksum_wraps_at_16_bits() -> None:
    frame = bytes(18) + b"\xff" * 300
    assert checksum(frame) == (300 * 0xFF) & 0xFFFF
    assert checksum(bytearray(frame)) == checksum(frame)


# ------------------------------------------------------------------ requests


def test_build_read_power_matches_real_frame() -> None:
    _assert_same_request(build_read(Element.POWER, 0x26), REAL_TX_READ_POWER, 0x26)


def test_build_read_mode_matches_real_frame() -> None:
    _assert_same_request(build_read(Element.MODE, 0xFA), REAL_TX_READ_MODE, 0xFA)


def test_build_off_matches_real_frame() -> None:
    _assert_same_request(build_write(Element.POWER, power_off_data(), 0x27), REAL_TX_OFF, 0x27)


def test_build_on_matches_real_frame() -> None:
    _assert_same_request(build_write(Element.POWER, power_on_data(50), 0x28), REAL_TX_ON_50, 0x28)


def test_build_colour_matches_real_frame() -> None:
    frame = build_write(Element.MODE, color_data((255, 0, 0)), 0x2A)
    _assert_same_request(frame, REAL_TX_RED, 0x2A)


def test_build_save_matches_real_frame() -> None:
    frame = build_write(Element.POWER, power_on_data(30), 0xF2, save=True)
    _assert_same_request(frame, REAL_TX_SAVE_ON_30, 0xF2)
    assert frame[36] == Op.WRITE_SAVE


def test_build_off_field_by_field() -> None:
    """The layout of docs/findings.md 3.1, offset by offset."""
    frame = build_write(Element.POWER, power_off_data(), 0x27)
    assert len(frame) == 42
    assert frame[0:4] == b"SZ00"
    assert frame[4] == 0x00  # request
    assert int.from_bytes(frame[8:10], "big") == len(frame) - 10 == 0x20
    assert int.from_bytes(frame[16:18], "big") == sum(frame[18:]) & 0xFFFF
    assert frame[26] == 0x27
    assert frame[36] == Op.WRITE
    assert frame[37] == 0x27
    assert frame[38:] == bytes.fromhex("0301ce1e")
    # every other header byte is zero
    assert not any(frame[i] for i in [*range(5, 8), *range(10, 16), *range(18, 26), *range(27, 36)])


def test_build_frame_checksum_and_length() -> None:
    frame = build_frame(Op.WRITE, tlv(Element.MODE, bytes.fromhex("ff01c10a00")), 0xBC)
    assert int.from_bytes(frame[8:10], "big") == len(frame) - 10
    assert int.from_bytes(frame[16:18], "big") == checksum(frame)
    assert frame[38:] == bytes.fromhex("0602ff01c10a00")


@pytest.mark.parametrize("seq", [0, 1, 0x7F, 0xFF])
def test_build_frame_sequence_bounds_ok(seq: int) -> None:
    frame = build_read(Element.POWER, seq)
    assert frame[26] == frame[37] == seq


@pytest.mark.parametrize("seq", [-1, 256, 1000])
def test_build_frame_sequence_out_of_range(seq: int) -> None:
    with pytest.raises(ValueError, match="sequence"):
        build_read(Element.POWER, seq)


def test_build_write_volatile_by_default() -> None:
    assert build_write(Element.POWER, power_on_data(10), 1)[36] == Op.WRITE
    assert build_write(Element.POWER, power_on_data(10), 1, save=True)[36] == Op.WRITE_SAVE


def test_tlv() -> None:
    assert tlv(Element.POWER) == b"\x01\x01"
    assert tlv(Element.POWER, b"\xce\x1e") == bytes.fromhex("0301ce1e")
    assert tlv(0x02, b"\x00" * 254)[0] == 0xFF
    with pytest.raises(ValueError, match="too long"):
        tlv(0x02, b"\x00" * 255)


# ------------------------------------------------------------------ payloads


def test_power_payloads() -> None:
    assert power_on_data(50) == bytes.fromhex("cf32")
    assert power_off_data() == bytes.fromhex("ce1e")


@pytest.mark.parametrize(
    ("requested", "sent"),
    [(-5, 1), (0, 1), (1, 1), (19, 19), (100, 100), (101, 100), (102, 100), (255, 100), (10**6, 100)],
)
def test_power_on_payload_is_clamped(requested: int, sent: int) -> None:
    assert power_on_data(requested) == bytes([0xCF, sent])


def test_clamp_brightness_never_above_100() -> None:
    """255 made the real strip drop off WiFi until a power cut: never send more than 100."""
    for value in range(-300, 1000):
        assert 1 <= clamp_brightness(value) <= 100
    assert clamp_brightness(50.9) == 50  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("rgb", "expected"),
    [
        ((255, 0, 0), "ff00ff0000"),
        ((0, 0, 0), "ff00000000"),
        ((1, 0, 0), "ff00010000"),
        ((128, 128, 128), "ff00808080"),
        ((255, 255, 255), "ff00ffffff"),
        ((255, 34, 34), "ff00ff2222"),
    ],
)
def test_color_data(rgb: tuple[int, int, int], expected: str) -> None:
    assert color_data(rgb) == bytes.fromhex(expected)


def test_color_data_accepts_sequences_and_floats() -> None:
    assert color_data([1, 2, 3]) == bytes.fromhex("ff00010203")  # type: ignore[arg-type]
    assert color_data((1.9, 2.0, 3.2)) == bytes.fromhex("ff00010203")  # type: ignore[arg-type]


@pytest.mark.parametrize("rgb", [(256, 0, 0), (0, -1, 0), (0, 0, 1000)])
def test_color_data_out_of_range(rgb: tuple[int, int, int]) -> None:
    with pytest.raises(ValueError, match="out of range"):
        color_data(rgb)


def test_effect_data() -> None:
    assert effect_data(bytes.fromhex("01c10a00")) == bytes.fromhex("ff01c10a00")
    assert effect_data(bytes.fromhex("9300ff64")) == bytes.fromhex("ff9300ff64")
    assert effect_data(bytearray.fromhex("049a0000")) == bytes.fromhex("ff049a0000")


@pytest.mark.parametrize("code", ["", "01", "01c10a", "01c10a0000"])
def test_effect_data_wrong_length(code: str) -> None:
    with pytest.raises(ValueError, match="4 bytes"):
        effect_data(bytes.fromhex(code))


def test_effect_data_rejects_static_colour_prefix() -> None:
    with pytest.raises(ValueError, match="cannot start with 00"):
        effect_data(bytes.fromhex("00ff0000"))


# ------------------------------------------------------------------ parse_reply on real replies


def test_parse_real_state_reply() -> None:
    reply = parse_reply(bytes.fromhex(REAL_RX_STATE_ON_19))
    assert reply.op == Op.READ
    assert reply.seq == 0x26
    assert reply.seq2 == 0x02
    assert reply.element == Element.POWER
    assert reply.data == bytes.fromhex("cf13")
    assert not reply.error
    assert reply.mac == MAC
    assert format_mac(reply.mac) == "4c:11:ae:b1:b6:14"
    assert reply.raw == bytes.fromhex(REAL_RX_STATE_ON_19)
    assert decode_power(reply.data) == PowerState(on=True, brightness=19)


def test_parse_real_off_acknowledgement() -> None:
    reply = parse_reply(bytes.fromhex(REAL_RX_ACK_OFF))
    assert (reply.op, reply.seq, reply.seq2, reply.element) == (Op.WRITE, 0x27, 0x01, Element.POWER)
    assert decode_power(reply.data) == PowerState(on=False, brightness=None)
    assert reply.mac == MAC


def test_parse_real_colour_acknowledgement() -> None:
    reply = parse_reply(bytes.fromhex(REAL_RX_ACK_RED))
    assert (reply.op, reply.seq, reply.element) == (Op.WRITE, 0x2A, Element.MODE)
    mode = decode_mode(reply.data)
    assert mode.is_color
    assert mode.rgb == (255, 0, 0)


def test_parse_real_mode_read_with_signal_byte() -> None:
    raw = bytes.fromhex(REAL_RX_MODE_FF2222)
    assert raw[35] == 0x40  # the lamp fills byte 35 in state replies; it must not matter
    reply = parse_reply(raw)
    assert (reply.op, reply.seq, reply.element) == (Op.READ, 0xFA, Element.MODE)
    mode = decode_mode(reply.data)
    assert mode == ModeState(code=bytes.fromhex("00ff2222"))
    assert mode.rgb == (255, 34, 34)
    assert not mode.is_multi_frame


def test_parse_real_effect_read() -> None:
    mode = decode_mode(parse_reply(bytes.fromhex(REAL_RX_MODE_SUNRISE)).data)
    assert mode.code == bytes.fromhex("01c10a00")
    assert not mode.is_color
    assert mode.rgb is None
    assert not mode.is_multi_frame


def test_parse_real_multi_frame_effect_read() -> None:
    mode = decode_mode(parse_reply(bytes.fromhex(REAL_RX_MODE_TRON_LAST)).data)
    assert mode.code == bytes.fromhex("9300ff64")
    assert mode.is_multi_frame
    assert not mode.is_color
    assert mode.rgb is None


def test_parse_real_save_acknowledgements() -> None:
    reply = parse_reply(bytes.fromhex(REAL_RX_ACK_SAVE_MODE))
    assert (reply.op, reply.seq, reply.element) == (Op.WRITE_SAVE, 0xCB, Element.MODE)
    assert decode_mode(reply.data).code == bytes.fromhex("0000ff07")
    reply = parse_reply(bytes.fromhex(REAL_RX_ACK_SAVE_ON_30))
    assert (reply.op, reply.seq, reply.element) == (Op.WRITE_SAVE, 0xF2, Element.POWER)
    assert decode_power(reply.data) == PowerState(on=True, brightness=30)


def test_parse_real_unknown_elements() -> None:
    reply = parse_reply(bytes.fromhex(REAL_RX_ELEMENT_03))
    assert (reply.element, reply.data, reply.error) == (0x03, bytes.fromhex("fe00000000"), False)
    reply = parse_reply(bytes.fromhex(REAL_RX_ELEMENT_04))
    assert (reply.element, reply.data, reply.error) == (0x04, b"\x1e", False)


@pytest.mark.parametrize(
    ("frame_hex", "op", "code", "seq"),
    [(REAL_RX_ERROR_43, 0x05, 0x43, 0xC5), (REAL_RX_ERROR_49, 0x0B, 0x49, 0xD7)],
)
def test_parse_real_error_replies(frame_hex: str, op: int, code: int, seq: int) -> None:
    reply = parse_reply(bytes.fromhex(frame_hex))
    assert reply.error
    assert reply.op == op
    assert reply.element == code  # error code in the id of a length-1 TLV
    assert reply.data == b""
    assert reply.seq == seq
    assert reply.mac == MAC


def test_parse_real_device_info_reply() -> None:
    reply = parse_reply(bytes.fromhex(REAL_RX_INFO))
    assert reply.op == 0x09
    assert reply.element == 0x01
    assert len(reply.data) == 23
    assert bytes.fromhex(MAC) in reply.data  # binary MAC inside the 24-byte block
    assert reply.mac == MAC


@pytest.mark.parametrize("frame_hex", ALL_REAL_REPLIES)
def test_every_real_reply_parses(frame_hex: str) -> None:
    reply = parse_reply(bytes.fromhex(frame_hex))
    assert reply.mac == MAC
    assert reply.raw[36] == reply.op | FLAG_REPLY


def test_parse_accepts_bytearray() -> None:
    raw = bytes.fromhex(REAL_RX_STATE_ON_19)
    reply = parse_reply(bytearray(raw))
    assert reply.raw == raw
    assert isinstance(reply.raw, bytes)
    assert reply.mac == MAC


# ------------------------------------------------------------------ parse_reply: MAC trailer


def test_parse_reply_without_trailer() -> None:
    reply = parse_reply(_reply(0x84, tlv(Element.POWER, b"\xce\x1e")))
    assert reply.mac is None
    assert reply.data == b"\xce\x1e"


def test_parse_reply_lower_case_mac_is_upper_cased() -> None:
    reply = parse_reply(_reply(0x83, tlv(Element.POWER, b"\xcf\x01") + tlv(0x01, b"4c11aeb1b614")))
    assert reply.mac == MAC


def test_parse_reply_non_ascii_mac_is_ignored() -> None:
    reply = parse_reply(_reply(0x83, tlv(Element.POWER, b"\xcf\x01") + tlv(0x01, b"\xff" * 12)))
    assert reply.mac is None


@pytest.mark.parametrize("trailer", [tlv(0x01, b"4C11AEB1B6"), tlv(0x02, MAC.encode()), tlv(0x01)])
def test_parse_reply_ignores_other_trailers(trailer: bytes) -> None:
    reply = parse_reply(_reply(0x83, tlv(Element.POWER, b"\xcf\x01") + trailer))
    assert reply.mac is None


def test_parse_reply_mac_found_after_extra_tlv() -> None:
    reply = parse_reply(_reply(0x83, tlv(Element.POWER, b"\xcf\x01") + tlv(0x05, b"\x00") + MAC_TRAILER))
    assert reply.mac == MAC
    assert reply.data == b"\xcf\x01"


def test_parse_reply_error_flag_only_for_empty_data() -> None:
    assert parse_reply(_reply(0x85, tlv(0x43) + MAC_TRAILER)).error
    assert not parse_reply(_reply(0x83, tlv(0x04, b"\x1e") + MAC_TRAILER)).error


# ------------------------------------------------------------------ parse_reply: malformed input


@pytest.mark.parametrize("size", [0, 1, 4, HEADER_LEN, HEADER_LEN + 1])
def test_parse_reply_too_short(size: int) -> None:
    raw = bytes.fromhex(REAL_RX_ACK_OFF)[:size]
    with pytest.raises(ProtocolError, match="too short"):
        parse_reply(raw)


def test_parse_reply_bad_magic() -> None:
    raw = bytearray(bytes.fromhex(REAL_RX_ACK_OFF))
    raw[0:4] = b"SZ01"
    with pytest.raises(ProtocolError, match="magic"):
        parse_reply(bytes(raw))


def test_parse_reply_rejects_requests() -> None:
    """Our own request (no 0x80 flag at offset 4), e.g. echoed by a broadcast."""
    with pytest.raises(ProtocolError, match="not a reply"):
        parse_reply(bytes.fromhex(REAL_TX_OFF))
    raw = bytearray(bytes.fromhex(REAL_RX_ACK_OFF))
    raw[4] = 0x00
    with pytest.raises(ProtocolError, match="not a reply"):
        parse_reply(bytes(raw))


def test_parse_reply_length_field_mismatch() -> None:
    raw = bytes.fromhex(REAL_RX_ACK_OFF)
    with pytest.raises(ProtocolError, match="length"):
        parse_reply(raw + b"\x00")  # one trailing byte too many
    bad = bytearray(raw)
    bad[9] += 1
    with pytest.raises(ProtocolError, match="length"):
        parse_reply(bytes(bad))
    with pytest.raises(ProtocolError, match="length"):
        parse_reply(raw[:-1])  # truncated datagram


def test_parse_reply_bad_checksum() -> None:
    raw = bytearray(bytes.fromhex(REAL_RX_STATE_ON_19))
    raw[41] = 0x14  # brightness 19 -> 20 without updating the checksum
    with pytest.raises(ProtocolError, match="checksum"):
        parse_reply(bytes(raw))
    raw = bytearray(bytes.fromhex(REAL_RX_STATE_ON_19))
    raw[17] ^= 0x01
    with pytest.raises(ProtocolError, match="checksum"):
        parse_reply(bytes(raw))


def test_parse_reply_zero_checksum_is_rejected() -> None:
    """Unlike the lamp, we do check the checksum: every real reply carries a correct one."""
    raw = bytearray(bytes.fromhex(REAL_RX_ACK_OFF))
    raw[16:18] = b"\x00\x00"
    with pytest.raises(ProtocolError, match="checksum"):
        parse_reply(bytes(raw))


def test_parse_reply_operation_without_reply_flag() -> None:
    raw = bytearray(bytes.fromhex(REAL_RX_ACK_OFF))
    raw[36] = 0x04
    with pytest.raises(ProtocolError, match="operation byte"):
        parse_reply(_refresh(raw))


@pytest.mark.parametrize(
    "tlvs",
    [
        bytes.fromhex("0301ce"),  # announced 3, only 2 present
        bytes.fromhex("0301ce1e") + bytes.fromhex("0d01") + MAC.encode()[:-1],  # truncated trailer
        bytes.fromhex("0000"),  # zero-length TLV
        bytes.fromhex("0301ce1e00"),  # zero-length TLV after a valid one
        bytes.fromhex("ff01"),  # length far beyond the datagram
    ],
)
def test_parse_reply_truncated_tlv(tlvs: bytes) -> None:
    with pytest.raises(ProtocolError, match="truncated TLV"):
        parse_reply(_reply(0x84, tlvs))


def test_protocol_error_is_a_cololight_error() -> None:
    from custom_components.cololight_local.protocol import CololightError

    assert issubclass(ProtocolError, CololightError)


# ------------------------------------------------------------------ decoders


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        ("cf13", PowerState(on=True, brightness=19)),
        ("cf01", PowerState(on=True, brightness=1)),
        ("cf64", PowerState(on=True, brightness=100)),
        ("cf00", PowerState(on=True, brightness=0)),
        ("ce1e", PowerState(on=False, brightness=None)),
        ("ce00", PowerState(on=False, brightness=None)),
    ],
)
def test_decode_power(data: str, expected: PowerState) -> None:
    assert decode_power(bytes.fromhex(data)) == expected


@pytest.mark.parametrize("data", ["", "cf", "cf1300", "1e", "0013", "ff00ff0000"])
def test_decode_power_invalid(data: str) -> None:
    with pytest.raises(ProtocolError, match="power"):
        decode_power(bytes.fromhex(data))


@pytest.mark.parametrize(
    ("data", "code", "rgb", "multi"),
    [
        ("ff00ff0000", "00ff0000", (255, 0, 0), False),
        ("ff00000000", "00000000", (0, 0, 0), False),
        ("ff01c10a00", "01c10a00", None, False),
        ("ff020b8d00", "020b8d00", None, False),
        ("ff9300ff64", "9300ff64", None, True),
    ],
)
def test_decode_mode(data: str, code: str, rgb: tuple[int, int, int] | None, multi: bool) -> None:
    mode = decode_mode(bytes.fromhex(data))
    assert mode.code == bytes.fromhex(code)
    assert mode.is_color is (rgb is not None)
    assert mode.rgb == rgb
    assert mode.is_multi_frame is multi


@pytest.mark.parametrize("data", ["", "ff", "ff00ff00", "ff00ff000000", "fe00ff0000", "0000ff0000", "1e"])
def test_decode_mode_invalid(data: str) -> None:
    with pytest.raises(ProtocolError, match="mode"):
        decode_mode(bytes.fromhex(data))


def test_state_dataclasses_are_frozen_and_comparable() -> None:
    state = DeviceState(PowerState(True, 50), ModeState(bytes.fromhex("00ff2222")))
    assert state == DeviceState(PowerState(True, 50), ModeState(bytes.fromhex("00ff2222")))
    assert hash(state) == hash(DeviceState(PowerState(True, 50), ModeState(bytes.fromhex("00ff2222"))))
    with pytest.raises(AttributeError):
        state.power = PowerState(False, None)  # type: ignore[misc]


# ------------------------------------------------------------------ format_mac


@pytest.mark.parametrize(
    "mac", ["4C11AEB1B614", "4c11aeb1b614", "4C:11:AE:B1:B6:14", "4c-11-ae-b1-b6-14", "4c:11:ae:b1:b6:14"]
)
def test_format_mac(mac: str) -> None:
    assert format_mac(mac) == "4c:11:ae:b1:b6:14"


def test_format_mac_is_idempotent() -> None:
    assert format_mac(format_mac(MAC)) == format_mac(MAC)
