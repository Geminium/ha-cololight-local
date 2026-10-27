#!/usr/bin/env python3
"""Acceptance check of the integration's client against a REAL lamp.

Runs the same code Home Assistant uses (custom_components/cololight_local/client.py,
effects.py, protocol.py: no Home Assistant needed) through a short sequence of visible
changes, checks every acknowledgement against a read-back, then puts the lamp back
into the state it was in. Nothing is stored in the lamp's EEPROM.

    python tools/live_check.py 192.168.0.51 --delay-start 20
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Load the integration modules as a plain package, without running its __init__ (HA).
_pkg = types.ModuleType("cololight_lib")
_pkg.__path__ = [str(ROOT / "custom_components" / "cololight_local")]
sys.modules["cololight_lib"] = _pkg

from cololight_lib.client import CololightClient
from cololight_lib.effects import effect_speed, effects_for_model, identify_effect, with_speed
from cololight_lib.protocol import DeviceState

FAILURES: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'OK ' if ok else 'KO '} {label}{f'  ({detail})' if detail else ''}", flush=True)
    if not ok:
        FAILURES.append(label)


async def step(title: str, pause: float) -> None:
    await asyncio.sleep(pause)
    print(f"\n{time.strftime('%H:%M:%S')} {title}", flush=True)


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("host")
    ap.add_argument("--model", default="strip", choices=["strip", "hexagon"])
    ap.add_argument("--delay-start", type=int, default=0, help="seconds to wait before the first change")
    ap.add_argument("--pause", type=float, default=5.0, help="seconds between visible steps")
    args = ap.parse_args()

    effects = effects_for_model(args.model)
    client = CololightClient(args.host)
    try:
        start: DeviceState = await client.async_get_state()
        print(f"Lamp {args.host} (MAC {client.mac}): {start}")
        for left in range(args.delay_start, 0, -1):
            if left % 5 == 0 or left <= 3:
                print(f"... first change in {left} s", flush=True)
            await asyncio.sleep(1)

        await step("1. green, 60 %", 0)
        mode = await client.async_set_color((0, 255, 0))
        power = await client.async_turn_on(60)
        state = await client.async_get_state()
        check("colour acknowledged", mode.rgb == (0, 255, 0), mode.code.hex())
        check("brightness acknowledged", power.on and power.brightness == 60)
        check("read-back matches", state.mode.rgb == (0, 255, 0) and state.power.brightness == 60, str(state))

        await step("2. effect Sunrise", args.pause)
        mode = await client.async_set_effect(effects["Sunrise"].frames)
        state = await client.async_get_state()
        check("Sunrise read back", identify_effect(state.mode.code, effects) == "Sunrise", state.mode.code.hex())

        await step("3. Sunrise at full speed (32)", args.pause)
        mode = await client.async_set_effect([with_speed(state.mode.code, 32)])
        state = await client.async_get_state()
        check("speed 32 read back", effect_speed(state.mode.code) == 32, state.mode.code.hex())
        check("still named Sunrise", identify_effect(state.mode.code, effects) == "Sunrise")

        if args.model == "strip":
            await step("4. palette effect Tron (6 frames, each acknowledged)", args.pause)
            sent_before = client.stats.datagrams_sent
            mode = await client.async_set_effect(effects["Tron"].frames)
            state = await client.async_get_state()
            check("last frame read back", state.mode.code == effects["Tron"].frames[-1], state.mode.code.hex())
            check("identified with the hint", identify_effect(state.mode.code, effects, "Tron") == "Tron")
            check("datagrams for 6 frames + 2 reads", client.stats.datagrams_sent - sent_before >= 8)

        await step("5. off", args.pause)
        power = await client.async_turn_off()
        state = await client.async_get_state()
        check("off acknowledged and read back", not power.on and not state.power.on)

        await step("6. on again at 30 %", args.pause)
        power = await client.async_turn_on(30)
        state = await client.async_get_state()
        check("on at 30 % read back", state.power.on and state.power.brightness == 30)

        await step("7. back to the initial state", args.pause)
        if start.mode.is_multi_frame:
            print("  (initial mode was a palette effect: only its last frame is known, leaving Tron)")
        elif start.mode.is_color:
            await client.async_set_color(start.mode.rgb)
        else:
            await client.async_set_effect([start.mode.code])
        if start.power.on:
            await client.async_turn_on(start.power.brightness or 100)
        else:
            await client.async_turn_off()
        state = await client.async_get_state()
        check("initial state restored", state.mode == start.mode or start.mode.is_multi_frame, str(state))
        check("initial power restored", state.power == start.power, str(state.power))
    finally:
        await client.async_stop()

    s = client.stats
    rtts = sorted(s.rtts)
    print(
        f"\nRequests {s.requests}, datagrams {s.datagrams_sent}, retries {s.retries}, timeouts {s.timeouts}, "
        f"late replies {s.late_replies}, ACK mismatches {s.ack_mismatches}"
    )
    if rtts:
        print(f"Round trip: min {rtts[0] * 1000:.0f} ms, median {rtts[len(rtts) // 2] * 1000:.0f} ms, "
              f"max {rtts[-1] * 1000:.0f} ms")
    print("\nRESULT:", "all checks passed" if not FAILURES else f"{len(FAILURES)} check(s) failed: {FAILURES}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
