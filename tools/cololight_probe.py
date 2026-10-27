#!/usr/bin/env python3
"""Cololight UDP probe: send raw or named frames and dump everything that comes back.

Standalone (stdlib only). Every event is logged to logs/cololight-YYYYMMDD.log (human
readable) and logs/cololight-YYYYMMDD.jsonl (structured).

Effect tables come from pycololight (MIT, (c) 2021 BazaJayGee66).

Examples:
    python tools/cololight_probe.py state
    python tools/cololight_probe.py bright 40
    python tools/cololight_probe.py --seq 5 --b37 5 off
    python tools/cololight_probe.py color ff0000
    python tools/cololight_probe.py effect "Sunrise"
    python tools/cololight_probe.py raw 535a3030...
    python tools/cololight_probe.py listen 60
    python tools/cololight_probe.py loss 20 --delay 1000
    python tools/cololight_probe.py note "bandeau rouge fixe"
"""
from __future__ import annotations

import argparse
import json
import random
import socket
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = ROOT / "logs"
SEQ_FILE = LOG_DIR / ".seq"

DEFAULT_HOST = "192.168.0.51"
PORT = 8900
MAGIC = bytes.fromhex("535a3030")

# Command headers (bytes 36..39) as seen in pycololight. Byte 37 may be overridden.
HDR_POWER = bytes.fromhex("04010301")   # payload: ce 1e (off) / cf NN (on + brightness)
HDR_EFFECT = bytes.fromhex("04010602")  # payload: ff 00 RR GG BB (colour) / ff A B C D (effect)
HDR_STATE = bytes.fromhex("03020101")   # read element 01 (power/brightness)
HDR_STATE2 = bytes.fromhex("03020102")  # read element 02 (colour/effect)

DEFAULT_EFFECTS = {
    "80s Club": ["049a0000"],
    "Cherry Blossom": ["04940800"],
    "Cocktail Parade": ["05bd0690"],
    "Instagrammer": ["03bc0190"],
    "Pensieve": ["04c40600"],
    "Savasana": ["04970400"],
    "Sunrise": ["01c10a00"],
    "The Circus": ["04810130"],
    "Unicorns": ["049a0e00"],
    "Christmas": ["068b0900"],
    "Rainbow Flow": ["03810690"],
    "Music Mode": ["07bd0990"],
}

STRIP_DYNAMIC_EFFECTS = {
    "Graffiti": ["93fefefe", "9305088c", "93f0a003", "93fa00ff", "93ffaf00", "9300c3ff", "93ff0091"],
    "Color train": ["069a0d00"],
    "Snow": ["058908c0"],
    "White link": ["06a20e00"],
    "Tron": ["93fefefe", "9304058b", "93f0b003", "93ff0000", "930087ff", "9300ff64"],
    "Urban beauty": ["93fefefe", "930304b4", "93f04000", "93ff00c3", "9300ffc3"],
    "Cyberpunk": ["93fefefe", "9303052c", "93f0a801", "93ff00d2", "9300c3ff"],
    "Tropic affair": ["93fefefe", "93050713", "93f08003", "9319ff00", "93fff000", "93ff9b00", "93ff0000"],
    "Go by": ["93fefefe", "93030448", "93f06000", "93ff0000", "9300faff"],
    "Break dance": ["93fefefe", "9303048c", "93f0b003", "936400ff", "93ff8700"],
    "Children park": ["93fefefe", "93050896", "93f0a602", "93ff00b4", "93b900ff", "9300aaff", "93ffeb00"],
    "Thunder": ["93fefefe", "9303064a", "93f0a582", "930037ff", "93ffffff"],
    "Red meteor": ["93fefefe", "93020237", "93f04800", "93ff0000"],
    "Green meteor": ["93fefefe", "93020246", "93f04800", "9300ff0f"],
    "Blue meteor": ["93fefefe", "9302027d", "93f04800", "930046ff"],
    "Forest": ["93fefefe", "9303045a", "93f01580", "9332ff00", "93ffa500"],
    "Cherry lake": ["93fefefe", "9303050d", "93f01680", "93ff738e", "9304ff84"],
    "World cup": ["93fefefe", "9304057f", "93f02200", "930037ff", "93ffe100", "930089ce"],
    "Sunset": ["93fefefe", "930404dd", "93f00500", "936400ff", "93ff0000", "93ff8700"],
    "Tide": ["93fefefe", "93040775", "93f09a82", "930050ff", "933d98ff", "9395b2ff"],
    "Lilac": ["93fefefe", "930407f8", "93f00800", "93fdb7ff", "93cb34ff", "93d977ff"],
    "Witch hut": ["93fefefe", "93030381", "93f02500", "936900ff", "9300ff05"],
    "Cranberry": ["93fefefe", "93030388", "93f01580", "93ff0000", "9300ff05"],
    "Tricolor": ["93fefefe", "93040563", "93f08803", "93ff0000", "930087ff", "9300ff64"],
    "Color star": ["05810cc0"],
    "Lover": ["05ba0150"],
    "Treasure": ["06bb0330"],
    "Heavy traffic": ["06a01d00"],
    "Weird story": ["06900e00"],
    "Green field": ["06950160"],
    "Seaman": ["06960100"],
    "Purple link": ["069e0e00"],
    "Blue link": ["069d0e00"],
    "Orange star": ["05870f70"],
    "Green star": ["05820f70"],
    "Red star": ["05860f70"],
    "Dusk": ["06920f00"],
    "Innocence": ["93fefefe", "93060c28", "93f01300", "935ab4ff", "93ff7878", "93a9ffac", "93d696ff", "93fff477"],
    "Red alert": ["06a90100"],
    "Blue alert": ["06a70100"],
}

ALL_EFFECTS = {**DEFAULT_EFFECTS, **STRIP_DYNAMIC_EFFECTS}

CUSTOM_COLOURS = {
    "Breath": (128, ["Red, Green, Blue", "Rainbow", "Green", "Azure", "Blue", "Purple", "Red",
                     "Orange", "Yellow", "White", "Green, Blue"]),
    "Shadow": (138, ["Red, Yellow", "Red, Green", "Red, Purple", "Red, Blue", "Green, Yellow",
                     "Green, Azure", "Green, Blue", "Blue, Azure", "Blue, Purple", "Yellow, White",
                     "Red, White", "Green, White", "Azure, White", "Blue, White", "Purple, White"]),
    "Flash": (153, ["Red, Green, Blue", "Rainbow", "Green", "Azure", "Blue", "Purple", "Red",
                    "Orange", "Yellow", "White"]),
    "Flicker": (163, ["Red, Green, Blue", "Rainbow", "Green", "Azure", "Blue", "Purple", "Red",
                      "Orange", "Yellow", "White"]),
    "Scene": (173, ["Birthday", "Girlfriends", "Friends", "Workmates", "Family", "Lover"]),
    "Mood": (179, ["Red", "Orange", "Yellow", "Green", "Grass", "Azure", "Blue", "Pink", "Gold",
                   "Color", "True Color"]),
    "Selected": (191, ["Savasana", "", "Sunrise", "", "Unicorns"]),
}

STRIP_MODES = [("01", "00"), ("02", "00"), ("05", "10"), ("05", "30"), ("05", "40"), ("05", "50"),
               ("05", "70"), ("05", "c0"), ("05", "f0"), ("05", "10"), ("06", "00"), ("06", "30"),
               ("06", "60")]
STRIP_LOWER_MODES = [10]


# --------------------------------------------------------------------------- logging

class Log:
    def __init__(self, label: str | None) -> None:
        LOG_DIR.mkdir(exist_ok=True)
        day = datetime.now().strftime("%Y%m%d")
        self.txt = open(LOG_DIR / f"cololight-{day}.log", "a", encoding="utf-8")
        self.jsonl = open(LOG_DIR / f"cololight-{day}.jsonl", "a", encoding="utf-8")
        self.label = label

    def event(self, kind: str, text: str, **data) -> None:
        ts = datetime.now().isoformat(timespec="milliseconds")
        line = f"{ts} [{kind:6}] {text}"
        print(line)
        self.txt.write(line + "\n")
        self.jsonl.write(json.dumps({"ts": ts, "kind": kind, "label": self.label, "text": text,
                                     **data}) + "\n")
        self.txt.flush()
        self.jsonl.flush()


def hexdump(data: bytes) -> str:
    rows = []
    for off in range(0, len(data), 16):
        chunk = data[off:off + 16]
        rows.append(f"      {off:04d}  " + " ".join(f"{b:02x}" for b in chunk))
    return "\n".join(rows)


# --------------------------------------------------------------------------- frames

def next_seq(forced: int | None) -> int:
    if forced is not None:
        return forced
    try:
        seq = int(SEQ_FILE.read_text()) % 255 + 1
    except (OSError, ValueError):
        seq = random.randint(1, 255)
    LOG_DIR.mkdir(exist_ok=True)
    SEQ_FILE.write_text(str(seq))
    return seq


def build_frame(header: bytes, payload: bytes, seq: int, b37: int | None,
                cksum: str = "zero") -> bytes:
    body = bytearray(16) + bytes([seq]) + bytearray(9) + bytearray(header) + payload
    if b37 is not None:
        body[27] = b37  # offset 37 in the full frame = 27 in the body
    if cksum != "zero":
        # Offsets 16-17: 16-bit sum of every byte from offset 18 on (observed in replies).
        total = sum(body[8:]) + (0x1234 if cksum == "bad" else 0)
        body[6:8] = (total & 0xFFFF).to_bytes(2, "big")
    return MAGIC + bytes(4) + len(body).to_bytes(2, "big") + bytes(body)


def decode(data: bytes) -> str:
    """Best-effort interpretation of a frame (request or response)."""
    if len(data) < 10 or data[:4] != MAGIC:
        return "not an SZ00 frame"
    parts = [f"len={len(data)}", f"lenfield={int.from_bytes(data[8:10], 'big')}"]
    if len(data) > 26:
        parts.append(f"seq[26]={data[26]}")
    if len(data) >= 40:
        parts.append(f"hdr[36:40]={data[36:40].hex(' ')}")
    if len(data) > 41:
        if data[40] == 0xCF:
            parts.append(f"ON brightness={data[41]}")
        elif data[40] == 0xCE:
            parts.append("OFF")
    if len(data) > 40:
        parts.append(f"payload[40:]={data[40:].hex(' ')}")
    nonzero = [i for i in list(range(4, 8)) + list(range(10, 26)) + list(range(27, 36))
               if i < len(data) and data[i]]
    if nonzero:
        parts.append("unexpected non-zero at " + ",".join(f"[{i}]={data[i]:02x}" for i in nonzero))
    return "  ".join(parts)


def custom_effect(scheme: str, colour: str, speed: int, mode: int) -> str:
    base, colours = CUSTOM_COLOURS[scheme]
    if colour not in colours:
        raise SystemExit(f"colour must be one of {[c for c in colours if c]}")
    if not 1 <= mode <= len(STRIP_MODES):
        raise SystemExit("strip mode must be 1..13")
    if not 1 <= speed <= 32:
        raise SystemExit("speed must be 1..32")
    col = base + colours.index(colour) - (128 if mode in STRIP_LOWER_MODES else 0)
    a, d = STRIP_MODES[mode - 1]
    if mode == 2:
        spd = [3, 11, 19][min(3, speed) - 1]
        return f"{a}{spd:02x}{col:02x}{d}"
    return f"{a}{col:02x}{33 - speed:02x}{d}"


# --------------------------------------------------------------------------- transport

@dataclass
class Rx:
    data: bytes
    addr: tuple
    delay_ms: float


class Probe:
    def __init__(self, args: argparse.Namespace, log: Log) -> None:
        self.args = args
        self.log = log
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self.sock.bind(("0.0.0.0", args.lport))
        self.log.event("info", f"socket bound to local port {self.sock.getsockname()[1]}, "
                               f"target {args.host}:{PORT}")

    def frame(self, header: bytes, payload: bytes = b"", seq: int | None = None) -> bytes:
        return build_frame(header, payload, next_seq(seq if seq is not None else self.args.seq),
                           self.args.b37, self.args.cksum)

    def send(self, frame: bytes, host: str | None = None) -> float:
        host = host or self.args.host
        t0 = time.perf_counter()
        self.sock.sendto(frame, (host, PORT))
        self.log.event("tx", f"-> {host}:{PORT}  {decode(frame)}\n{hexdump(frame)}",
                       hex=frame.hex(), dst=host)
        return t0

    def receive(self, t0: float, wait: float, quiet: bool = False) -> list[Rx]:
        """Collect every datagram arriving within `wait` seconds after t0."""
        out: list[Rx] = []
        deadline = t0 + wait
        while (remaining := deadline - time.perf_counter()) > 0:
            self.sock.settimeout(remaining)
            try:
                data, addr = self.sock.recvfrom(4096)
            except socket.timeout:
                break
            except ConnectionResetError:  # Windows: ICMP port unreachable
                self.log.event("rx", "ICMP port unreachable (ConnectionResetError)")
                continue
            rx = Rx(data, addr, (time.perf_counter() - t0) * 1000)
            out.append(rx)
            if not quiet:
                self.log.event("rx", f"<- {addr[0]}:{addr[1]}  +{rx.delay_ms:.1f} ms  {decode(data)}"
                                     f"\n{hexdump(data)}",
                               hex=data.hex(), src=f"{addr[0]}:{addr[1]}", delay_ms=rx.delay_ms)
        if not out and not quiet:
            self.log.event("rx", f"(nothing received within {wait * 1000:.0f} ms)")
        return out

    def send_frames(self, frames: list[bytes]) -> None:
        t0 = None
        for i, f in enumerate(frames):
            if i and self.args.gap:
                time.sleep(self.args.gap / 1000)
            t = self.send(f)
            t0 = t0 or t
        self.receive(t0, self.args.wait)

    def read_state(self, tries: int = 3, timeout: float = 1.0) -> tuple[bool, int | None] | None:
        """Query state, retrying; returns (on, brightness) or None."""
        for _ in range(tries):
            req = self.frame(HDR_STATE)
            t0 = self.send(req)
            for rx in self.receive(t0, timeout):
                d = rx.data
                # Only the state reply (0x83) carrying our sequence; late command ACKs also hold cf/ce.
                if (rx.addr[0] == self.args.host and len(d) > 41 and d[26] == req[26]
                        and d[36] == 0x83 and d[40] in (0xCE, 0xCF)):
                    return (d[40] == 0xCF, d[41] if d[40] == 0xCF else None)
        return None

    def read_mode(self, tries: int = 3, timeout: float = 1.0) -> str | None:
        """Read element 02 and describe it (static colour or effect code)."""
        for _ in range(tries):
            req = self.frame(HDR_STATE2)
            t0 = self.send(req)
            for rx in self.receive(t0, timeout):
                d = rx.data
                if len(d) > 44 and d[26] == req[26] and d[36] == 0x83 and d[38:40] == b"\x06\x02":
                    abcd = d[41:45]
                    if abcd[0] == 0:
                        return f"colour #{abcd[1:].hex()}"
                    name = next((n for n, f in ALL_EFFECTS.items() if f == [abcd.hex()]), "?")
                    return f"effect {abcd.hex()} ({name})"
        return None


# --------------------------------------------------------------------------- tests

def test_loss(p: Probe, n: int, delay_ms: int) -> None:
    """Send n brightness commands (alternating values), verify each by reading state."""
    ok = lost = unknown = 0
    values = [20, 80]
    for i in range(n):
        target = values[i % 2]
        p.send_frames([p.frame(HDR_POWER, bytes([0xCF, target]))])
        time.sleep(delay_ms / 1000)
        st = p.read_state()
        if st is None:
            unknown += 1
            verdict = "state unreadable"
        elif st == (True, target):
            ok += 1
            verdict = "applied"
        else:
            lost += 1
            verdict = f"NOT applied (state={st})"
        p.log.event("result", f"loss {i + 1}/{n}: target={target} -> {verdict}")
    p.log.event("result", f"LOSS SUMMARY n={n} delay={delay_ms}ms applied={ok} lost={lost} "
                          f"unknown={unknown}", n=n, applied=ok, lost=lost, unknown=unknown)


def watch(p: Probe, seconds: float, period: float) -> None:
    """Poll state every `period` s; print only changes; flag any datagram we did not ask for."""
    end = time.perf_counter() + seconds
    last = None
    while time.perf_counter() < end:
        req = p.frame(HDR_STATE)
        t0 = time.perf_counter()
        p.sock.sendto(req, (p.args.host, PORT))
        st = None
        for rx in p.receive(t0, period, quiet=True):
            d = rx.data
            if len(d) > 41 and d[36] == 0x83 and d[26] == req[26]:
                st = (d[40] == 0xCF, d[41] if d[40] == 0xCF else None, f"+{rx.delay_ms:.0f}ms")
            elif len(d) > 36 and d[36] == 0x83:
                p.log.event("rx", f"late state reply seq={d[26]} (current {req[26]})", hex=d.hex())
            else:
                p.log.event("rx", f"UNSOLICITED <- {rx.addr[0]}:{rx.addr[1]}  {decode(d)}\n{hexdump(d)}",
                            hex=d.hex(), src=f"{rx.addr[0]}:{rx.addr[1]}", unsolicited=True)
        key = st[:2] if st else None
        if key != last:
            p.log.event("result", f"state change -> {st if st else 'NO REPLY'}")
            last = key


def opscan(p: Probe, ops: list[int], b37s: list[int]) -> None:
    """Try other op bytes [36] / byte [37] for a colour write; colour #00ffNN tags each attempt."""
    attempts = [(op, 0x01) for op in ops] + [(0x04, b) for b in b37s]
    for op, b37 in attempts:
        p.send_frames([p.frame(HDR_EFFECT, b"\xff\x00\xff\x00\x00")])  # red baseline, op 04
        time.sleep(0.5)
        tag = op if b37 == 0x01 else 0x30 + b37
        hdr = bytes([op, b37, 0x06, 0x02])
        req = p.frame(hdr, b"\xff\x00\x00\xff" + bytes([tag]))
        t0 = p.send(req)
        replies = [rx for rx in p.receive(t0, 1.5) if len(rx.data) > 36 and rx.data[26] == req[26]]
        reply = replies[0].data[36:40].hex(" ") if replies else "none"
        time.sleep(0.5)
        mode = p.read_mode()
        if mode is None:
            p.log.event("result", f"OPSCAN op={op:02x} b37={b37:02x}: LAMP NOT ANSWERING - stop")
            return
        applied = mode == f"colour #00ff{tag:02x}"
        p.log.event("result", f"OPSCAN op={op:02x} b37={b37:02x}: reply_hdr={reply} "
                              f"mode={mode} -> {'APPLIED' if applied else 'not applied'}",
                    op=op, b37=b37, reply=reply, applied=applied)


def test_burst(p: Probe, delays: list[int], reps: int) -> None:
    """For each delay: baseline 10%, then B=40 and C=70 separated by `delay`; is C applied?"""
    for d in delays:
        res = {"C": 0, "B": 0, "baseline": 0, "other": 0}
        for _ in range(reps):
            p.send_frames([p.frame(HDR_POWER, bytes([0xCF, 10]))])
            time.sleep(0.8)
            t0 = p.send(p.frame(HDR_POWER, bytes([0xCF, 40])))
            while (time.perf_counter() - t0) * 1000 < d:
                pass
            p.send(p.frame(HDR_POWER, bytes([0xCF, 70])))
            p.receive(t0, 0.3)
            time.sleep(0.5)
            st = p.read_state()
            key = {(True, 70): "C", (True, 40): "B", (True, 10): "baseline"}.get(st, "other")
            res[key] += 1
        p.log.event("result", f"BURST delay={d}ms reps={reps} -> {res}", delay_ms=d, **res)


# --------------------------------------------------------------------------- CLI

def parse_colour(vals: list[str]) -> bytes:
    if len(vals) == 1:
        return bytes.fromhex(vals[0].lstrip("#"))
    return bytes(int(v) for v in vals)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default=DEFAULT_HOST)
    ap.add_argument("--lport", type=int, default=0, help="local UDP port to bind (0 = ephemeral)")
    ap.add_argument("--wait", type=float, default=1.5, help="seconds to listen after sending")
    ap.add_argument("--seq", type=int, help="force sequence byte [26] (default: auto-increment)")
    ap.add_argument("--b37", type=int, help="override byte [37]")
    ap.add_argument("--cksum", choices=["zero", "ok", "bad"], default="zero",
                    help="checksum at offsets 16-17: zero (like pycololight), ok, or deliberately wrong")
    ap.add_argument("--gap", type=int, default=0, help="ms between frames of a multi-frame command")
    ap.add_argument("--label", help="free text tag stored in the log")
    ap.add_argument("--delay-start", type=int, default=0,
                    help="countdown in seconds before sending (time to go and look at the strip)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("state")
    sub.add_parser("fullstate", help="read elements 01 and 02")
    sub.add_parser("off")
    for name in ("on", "bright"):
        s = sub.add_parser(name)
        s.add_argument("level", type=int, help="byte value sent after 0xcf")
        s.add_argument("--unsafe", action="store_true", help="allow values > 101")
    s = sub.add_parser("color", help="color RRGGBB | color R G B")
    s.add_argument("rgb", nargs="+")
    s = sub.add_parser("effect")
    s.add_argument("name")
    s = sub.add_parser("fx", help="raw 4-byte effect, e.g. fx 01c10a00")
    s.add_argument("abcd")
    s = sub.add_parser("custom", help='custom Breath "Red" 16 1')
    s.add_argument("scheme", choices=list(CUSTOM_COLOURS))
    s.add_argument("colour")
    s.add_argument("speed", type=int)
    s.add_argument("mode", type=int)
    s = sub.add_parser("payload", help="payload HDR_HEX PAYLOAD_HEX: auto header/length/seq")
    s.add_argument("hdr")
    s.add_argument("data", nargs="?", default="")
    s = sub.add_parser("raw", help="send a complete frame verbatim")
    s.add_argument("hex")
    s = sub.add_parser("repeat", help="repeat N INTERVAL_MS CMD...: same frame N times")
    s.add_argument("n", type=int)
    s.add_argument("interval", type=int)
    s.add_argument("what", choices=["off", "bright", "state", "color"])
    s.add_argument("arg", nargs="*")
    s.add_argument("--same-seq", action="store_true", help="reuse the same sequence for all")
    s = sub.add_parser("listen", help="listen SECONDS [--register]")
    s.add_argument("seconds", type=float)
    s.add_argument("--register", action="store_true", help="send a state request first")
    s = sub.add_parser("watch", help="poll state, print changes and unsolicited packets")
    s.add_argument("seconds", type=float)
    s.add_argument("--period", type=float, default=2.0)
    s = sub.add_parser("discover", help="broadcast a state request")
    s.add_argument("--bcast", default="255.255.255.255")
    s = sub.add_parser("loss")
    s.add_argument("n", type=int)
    s.add_argument("--delay", type=int, default=1000, help="ms between command and readback")
    s = sub.add_parser("burst")
    s.add_argument("--delays", default="0,10,25,50,100,200,400")
    s.add_argument("--reps", type=int, default=3)
    s = sub.add_parser("opscan", help="try other op bytes for a colour write")
    s.add_argument("--ops", default="05,06,07,08,09,0a,0b,0c,0d,0e,0f")
    s.add_argument("--b37s", default="02,03,04,05")
    s = sub.add_parser("note", help="record a physical observation")
    s.add_argument("text", nargs="+")
    sub.add_parser("effects", help="list effect names")

    args = ap.parse_args()
    log = Log(args.label)

    if args.cmd == "note":
        log.event("note", " ".join(args.text))
        return
    if args.cmd == "effects":
        for n, f in ALL_EFFECTS.items():
            print(f"{n:18} {len(f)} frame(s)  {' '.join(f)}")
        return

    p = Probe(args, log)
    log.event("cmd", " ".join(sys.argv[1:]))
    for left in range(args.delay_start, 0, -1):
        if left % 5 == 0 or left <= 3:
            print(f"... envoi dans {left} s", flush=True)
        time.sleep(1)
    c = args.cmd
    if c == "state":
        st = p.read_state(tries=1, timeout=args.wait)
        log.event("result", f"state = {st}")
    elif c == "fullstate":
        log.event("result", f"fullstate = {p.read_state()} / {p.read_mode()}")
    elif c == "off":
        p.send_frames([p.frame(HDR_POWER, bytes([0xCE, 0x1E]))])
    elif c in ("on", "bright"):
        if args.level > 101 and not args.unsafe:
            raise SystemExit("brightness > 101 crashed the strip's WiFi (2026-10-25); use --unsafe")
        p.send_frames([p.frame(HDR_POWER, bytes([0xCF, args.level]))])
    elif c == "color":
        p.send_frames([p.frame(HDR_EFFECT, b"\xff\x00" + parse_colour(args.rgb))])
    elif c == "effect":
        frames = ALL_EFFECTS[args.name]
        p.send_frames([p.frame(HDR_EFFECT, b"\xff" + bytes.fromhex(x)) for x in frames])
    elif c == "fx":
        p.send_frames([p.frame(HDR_EFFECT, b"\xff" + bytes.fromhex(args.abcd))])
    elif c == "custom":
        abcd = custom_effect(args.scheme, args.colour, args.speed, args.mode)
        log.event("info", f"custom effect bytes = {abcd}")
        p.send_frames([p.frame(HDR_EFFECT, b"\xff" + bytes.fromhex(abcd))])
    elif c == "payload":
        p.send_frames([p.frame(bytes.fromhex(args.hdr), bytes.fromhex(args.data))])
    elif c == "raw":
        p.send_frames([bytes.fromhex(args.hex)])
    elif c == "repeat":
        hdr, pl = {
            "off": (HDR_POWER, b"\xce\x1e"),
            "bright": (HDR_POWER, bytes([0xCF, int(args.arg[0])]) if args.arg else b""),
            "state": (HDR_STATE, b""),
            "color": (HDR_EFFECT, b"\xff\x00" + parse_colour(args.arg) if args.arg else b""),
        }[args.what]
        seq = next_seq(args.seq) if args.same_seq else None
        for i in range(args.n):
            t0 = p.send(p.frame(hdr, pl, seq))
            p.receive(t0, args.interval / 1000)
    elif c == "listen":
        t0 = time.perf_counter()
        if args.register:
            t0 = p.send(p.frame(HDR_STATE))
        p.receive(t0, args.seconds)
    elif c == "watch":
        watch(p, args.seconds, args.period)
    elif c == "discover":
        t0 = p.send(p.frame(HDR_STATE), host=args.bcast)
        p.receive(t0, args.wait)
    elif c == "loss":
        test_loss(p, args.n, args.delay)
    elif c == "opscan":
        opscan(p, [int(x, 16) for x in args.ops.split(",") if x],
               [int(x, 16) for x in args.b37s.split(",") if x])
    elif c == "burst":
        test_burst(p, [int(x) for x in args.delays.split(",")], args.reps)


if __name__ == "__main__":
    main()
