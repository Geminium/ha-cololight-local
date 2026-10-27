# Cololight (local) for Home Assistant

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/docs/faq/custom_repositories/)
[![Tests](https://github.com/Geminium/ha-cololight-local/actions/workflows/tests.yml/badge.svg)](https://github.com/Geminium/ha-cololight-local/actions/workflows/tests.yml)
[![Validate](https://github.com/Geminium/ha-cololight-local/actions/workflows/validate.yml/badge.svg)](https://github.com/Geminium/ha-cololight-local/actions/workflows/validate.yml)

A Home Assistant integration that controls **LifeSmart Cololight** lamps directly on your LAN
(UDP port 8900), with no cloud account. Commands are confirmed by the lamp, the state shown in
Home Assistant is read back from the lamp, and lamps are found automatically.

> A French step-by-step user guide is available in [`docs/mode-emploi.md`](docs/mode-emploi.md).

---

## Why another Cololight integration?

The existing options are not reliable enough:

- The **official app** goes through the LifeSmart cloud (`ict.ilifesmart.com`). It sends no local
  packets, and it never shows changes made locally.
- The **community integration** (`cololight`, based on pycololight) sends each command once and
  never reads the lamp's answer. It then shows the state it *hoped* for (optimistic state), only reads
  on/off and brightness back, and identifies the lamp by its IP address. About 1–2 % of UDP packets
  are lost on a typical 2.4 GHz network, so you sometimes had to press twice. When that happened,
  Home Assistant showed a state the lamp was not actually in.

This integration is built on measurements made on a real Cololight Strip (see
[`docs/findings.md`](docs/findings.md)):

| | Community `cololight` | **Cololight (local)** |
|---|---|---|
| Command delivery | one datagram, fire-and-forget | **waits for the lamp's acknowledgement**, 1.5 s timeout, up to 4 attempts |
| State after a command | assumed (optimistic) | **taken from the acknowledgement**, which carries the value the lamp applied |
| Colour / effect state | not readable, restored from memory | **read back from the lamp** on every poll |
| Failed command | silent | **error shown in the UI** and a warning in the log |
| One lost poll | entity unavailable | ignored; unavailable only after **3 failed polls in a row** |
| Device identity | IP address | **MAC address**, checked in every reply, so the lamp is found again after an IP change |
| Setup | type the IP | **automatic discovery** (DHCP and broadcast scan) or manual IP |
| Brightness | capped at 100 | capped at 100 (see [Known limitations](#known-limitations)) |

## Supported devices

| Device | Status |
|---|---|
| **Cololight Strip** (tested: model `ls167s6`, 120 LEDs) | Tested on real hardware |
| **Cololight Hexagon** | Same protocol according to pycololight. **Not tested** on real hardware. Feedback welcome |

The lamp must already be connected to your WiFi, which you do with the official app. This
integration does not handle WiFi provisioning.

## Requirements

- Home Assistant **2025.2.0 or newer** (developed and tested on 2026.10).
- Home Assistant and the lamp on the **same local network**. Unicast UDP to port 8900 is enough for
  control. Automatic discovery uses DHCP and broadcast, which do not cross routers or VLANs.
- If Home Assistant runs in Docker, use `network_mode: host`: DHCP discovery and the broadcast scan
  need it. With bridged networking, add the lamp by IP instead.

## Installation

### HACS (custom repository)

1. In Home Assistant open **HACS**, then the **⋮** menu (top right), then **Custom repositories**.
2. Repository: `https://github.com/Geminium/ha-cololight-local`, type: **Integration**, then **Add**.
3. Search for **Cololight (local)** in HACS, open it and click **Download**.
4. **Restart Home Assistant**.

### Manual

1. Copy the folder `custom_components/cololight_local` from this repository into
   `/config/custom_components/` on your Home Assistant host. Use Samba, the File editor or Studio Code
   Server add-on, or SSH. You should end up with `/config/custom_components/cololight_local/manifest.json`.
2. **Restart Home Assistant**.

### Migrating from the community `cololight` integration

The two integrations use different domains (`cololight` and `cololight_local`), so they can
technically run side by side. Controlling the same lamp from both is confusing, though, and the old
one keeps showing optimistic state. The recommended path is:

1. Remove the old integration (**Settings → Devices & services → Cololight → ⋮ → Delete**), and
   uninstall it from HACS. If you configured it in YAML, remove the `light: - platform: cololight`
   lines too.
2. Install and configure this one.
3. The entity IDs change, because the new entities are identified by MAC address and live in a new
   domain. Either update your automations, scripts and dashboards, or rename the new light's entity
   ID to the old one (**Settings → Entities → the light → ⚙ → Entity ID**).
4. The built-in effect names are the same as in pycololight, so `effect:` values in automations keep
   working. Custom effects you defined in the old integration must be recreated in the options (see
   below).

## Configuration

Everything is done in the UI.

- **Discovery.** The first lamp is found in one of two ways: by Home Assistant's DHCP discovery,
  which reacts to devices with the Espressif MAC prefix `4C:11:AE` (it needs host networking when Home
  Assistant runs in Docker), or by the scan of the **Add integration** dialog (below). Once at least
  one lamp is configured, the integration also scans the network (broadcast on UDP 8900) when Home
  Assistant starts and then every 15 minutes, to find other lamps and to follow address changes. A
  discovered lamp shows up as **Discovered** in **Settings → Devices & services**. Click **Add** and
  choose the model.
- **Add integration.** Go to **Settings → Devices & services → Add integration → Cololight (local)**.
  The lamps that answer within 2 seconds and are not configured yet are listed as `IP (MAC)`. Pick
  one, or choose **Enter an IP address manually**. When no new lamp answers, the **Enter the IP
  address** form opens directly. The integration checks that a Cololight answers at that address;
  otherwise it shows *No Cololight answered at this address. Check the address, and that the lamp is
  powered and connected to your Wi-Fi.*
- **Model.** Choose **Strip** or **Hexagon**. The model cannot be detected over the LAN, and it
  decides which effects are offered.
- **Reconfigure.** To change the IP address or the model later, use **⋮ → Reconfigure** on the
  integration entry. If another lamp answers at the new address, the change is refused (*Another lamp
  answered at this address…*).

The device is named `Cololight XXXX`, where `XXXX` is the end of the MAC address (for example
`Cololight B614`). Rename it in the UI if you like.

The MAC address is the unique ID, and the integration checks it in every reply. If another device
answers at the configured address (for example two lamps that swapped addresses), its replies are
refused: the poll counts as failed, commands fail, and the lamp is searched for by its MAC. A lamp
that got a new IP address is found again through DHCP discovery, the 15-minute scan, or the broadcast
search started by failed polls, and the entry is updated by itself. Reserving the IP address in your
router (static DHCP lease) is still a good idea.

## Options

Open **Settings → Devices & services → Cololight (local) → Configure**. The menu has three entries:
**Settings**, **Add a custom effect** and **Remove custom effects**. The first four rows below are the
fields of **Settings**.

| Option | Default | Range | Description |
|---|---|---|---|
| Polling interval | 10 s | 5–300 s | How often the state is read (two ~40-byte requests per poll). Changes made in the official app or after a power cut show up within this delay |
| Save the state as power-on state automatically | off | on/off | Once the state set from Home Assistant has stopped changing, write it to the lamp's EEPROM (operation `07`) so the lamp boots with it after a power cut. See [Automatic save](#automatic-save) and [EEPROM wear](#eeprom-wear) |
| Delay before saving | 30 s | 10–600 s | How long the state must stay unchanged before the automatic save |
| Hidden effects | none | built-in names | Removed from the effect lists of the UI. A hidden effect can still be started by its name in YAML, and is still recognised when started from the app |
| Add a custom effect | – | Name, Colour scheme (scheme and colour picked together, e.g. `Breath \| Rainbow`), Speed 0–32, Mode | Creates a named effect, like the custom effects of the official app. It appears in the effect list and can be used by name in automations. The name cannot be `off` or `Unknown palette effect`, or start with `Effect ` |
| Remove custom effects | – | – | Deletes custom effects |

Changing options reloads the integration. The last brightness, colour and effect are kept.

### Automatic save

With **Save the state as power-on state automatically** on:

- Every command sent from Home Assistant and acknowledged by the lamp (turn on, brightness, colour,
  effect, speed, `set_custom_effect`, `set_effect_code`) restarts a timer of **Delay before saving**
  (30 s by default). Nothing is written while you keep changing things. Changes made in the official
  app do not start the timer.
- When the timer ends, the state is written once with operation `07`: colour or effect, then
  brightness. A palette (multi-frame) effect is written by sending all its frames again. If the
  palette effect is unidentified (`Unknown palette effect`), only the brightness is saved and a warning
  is logged.
- **Nothing is written while the lamp is off**, and turning off does not start the timer. A state set
  just before turning off is saved after the next turn-on from Home Assistant, once the delay has
  passed.
- **Nothing is written if the state has not changed since the last save** (automatic or explicit), so
  an on/off routine that always comes back to the same state writes once. This comparison is kept in
  memory: after a restart or a reload, the first automatic save writes again.
- The power state "off" is never saved.

The button and the `save_state` action always write when asked, even a state saved before (the app
may have stored another power-on state through the cloud since).

### Custom effects

Custom effects use a **scheme**, a **colour** (from that scheme), a **speed** (0 = slowest, 32 =
fastest) and an animation **mode** (1–13 for the Strip, 1–27 for the Hexagon). Pictures of the modes
are in pycololight's
[MODES.md](https://github.com/BazaJayGee66/pycololight/blob/main/MODES.md).

| Scheme | Colours |
|---|---|
| Breath | `Red, Green, Blue` · `Rainbow` · `Green` · `Azure` · `Blue` · `Purple` · `Red` · `Orange` · `Yellow` · `White` · `Green, Blue` |
| Shadow | `Red, Yellow` · `Red, Green` · `Red, Purple` · `Red, Blue` · `Green, Yellow` · `Green, Azure` · `Green, Blue` · `Blue, Azure` · `Blue, Purple` · `Yellow, White` · `Red, White` · `Green, White` · `Azure, White` · `Blue, White` · `Purple, White` |
| Flash | `Red, Green, Blue` · `Rainbow` · `Green` · `Azure` · `Blue` · `Purple` · `Red` · `Orange` · `Yellow` · `White` |
| Flicker | same as Flash |
| Scene | `Birthday` · `Girlfriends` · `Friends` · `Workmates` · `Family` · `Lover` |
| Mood | `Red` · `Orange` · `Yellow` · `Green` · `Grass` · `Azure` · `Blue` · `Pink` · `Gold` · `Color` · `True Color` |
| Selected | `Savasana` · `Sunrise` · `Unicorns` |

A colour such as `Red, Green, Blue` is **one** value. Quote it in YAML.

## Entities

Example IDs for a device named `Cololight B614`. Yours depend on your device name.

| Entity | Example ID | What it does |
|---|---|---|
| Light | `light.cololight_b614` | On/off, brightness, RGB colour, effects |
| Effect speed | `number.cololight_b614_effect_speed` | Slider 0 (slowest) to 32 (fastest). **Available only while the current effect has an adjustable speed**: not for a static colour or a multi-frame (palette) effect |
| Save as power-on state | `button.cololight_b614_save_as_power_on_state` | Stores the current state as power-on state (EEPROM), at each press. Configuration category |

The number and button IDs are built from the entity names in Home Assistant's language when the lamp
is added (French: `number.cololight_b614_vitesse_de_l_effet`,
`button.cololight_b614_memoriser_comme_etat_au_demarrage`): copy the exact ID from the entity's
settings.

Light details:

- Colour mode RGB. Colours given as `hs_color`, `xy_color`, `color_name` or `color_temp_kelvin` are
  converted to RGB by Home Assistant.
- Brightness 1–255 in Home Assistant maps to 1–100 % on the lamp.
- While an effect runs, `rgb_color` is empty and `effect` holds its name. An effect the integration
  cannot name is shown as `Effect xxxxxxxx` (its 8-hex-digit code; `light.turn_on` accepts that name
  back), or `Unknown palette effect` for an unidentified multi-frame effect.
- Extra attributes while an effect runs: `effect_code` (hex code reported by the lamp) and
  `effect_speed` (when adjustable).
- Effect `off` goes back to the last static colour (white if none is known yet). Effect `off` together
  with `rgb_color` sets that colour: this is what scenes send.
- Turning on with only a colour or an effect also switches the lamp on, at the last brightness.
- Changing the brightness during an effect only sends the brightness: the integration does not resend
  the effect.
- The last brightness, colour and effect are kept across reloads and Home Assistant restarts (restored
  state), because the lamp does not report its brightness while off, its colour while an effect runs,
  or more than the last frame of a palette effect. Turning on an off lamp after a restart therefore
  uses the previous brightness.
- `transition` and `flash` are not supported.

## Services (actions)

All three target light entities of this integration.

### `cololight_local.set_custom_effect`

Starts a custom effect without saving it in the options. Like `set_effect_code`, it changes the effect
but does not turn the lamp on.

| Field | Required | Values |
|---|---|---|
| `scheme` | yes | `Breath`, `Shadow`, `Flash`, `Flicker`, `Scene`, `Mood`, `Selected` |
| `color` | yes | free text: a colour of that scheme, written exactly as in the table above (English, case-sensitive). A wrong colour is refused with a message that lists the valid colours of the scheme |
| `speed` | no | 0–32, default 16 |
| `mode` | no | 1–13 (Strip) / 1–27 (Hexagon), default 1 |

```yaml
action: cololight_local.set_custom_effect
target:
  entity_id: light.cololight_b614
data:
  scheme: Breath
  color: "Red, Green, Blue"
  speed: 20
  mode: 3
```

### `cololight_local.set_effect_code`

Sends raw effect frames: one or more 8-hex-digit frames separated by spaces or commas. The first byte
must not be `00`, because that would be a static colour. This is useful to replay a single-frame
effect started from the app: read its `effect_code` attribute in **Developer tools → States**.

If `effect_code` starts with `93`, it is only the **last frame** of a palette effect and cannot be
replayed this way. Use the effect's name when Home Assistant shows one. An `Unknown palette effect` is
either one of the pairs listed in [Known limitations](#known-limitations) (start it by its name) or an
app effect that is not in the tables, which can only be started from the app.

```yaml
action: cololight_local.set_effect_code
target:
  entity_id: light.cololight_b614
data:
  code: "05bd0690"
```

```yaml
# Multi-frame (palette) effect, frames sent in order, each one acknowledged
# (the four frames of Blue meteor, from the effect table)
action: cololight_local.set_effect_code
target:
  entity_id: light.cololight_b614
data:
  code: "93fefefe 9302027d 93f04800 930046ff"
```

### `cololight_local.save_state`

Stores the current state in the lamp's EEPROM, so it boots with it after a power cut. It does the
same as the button, and writes every time it is called.

- A palette effect is stored by sending all its frames again.
- If the running palette effect is unidentified (`Unknown palette effect`), nothing is stored and the
  action fails with *The running palette effect is not identified, so it cannot be stored as power-on
  state. Start it again by its name from Home Assistant, then save.* Storing its last frame alone would
  not reproduce the effect.
- When the lamp is off, only the colour or effect is stored, never "off" (see
  [Known limitations](#known-limitations)).

```yaml
action: cololight_local.save_state
target:
  entity_id: light.cololight_b614
```

### Standard actions

```yaml
# Effect by name, at 40 %
action: light.turn_on
target:
  entity_id: light.cololight_b614
data:
  effect: Sunrise
  brightness_pct: 40
```

```yaml
# Static colour (leaves the effect)
action: light.turn_on
target:
  entity_id: light.cololight_b614
data:
  rgb_color: [255, 120, 0]
```

```yaml
# Effect speed: start the effect first, then set the speed
action: number.set_value
target:
  entity_id: number.cololight_b614_effect_speed
data:
  value: 8
```

### Scenes and snapshots

Scenes and `scene.create` snapshots restore the light through `light.turn_on` (or `light.turn_off`):

- A static colour comes back as effect `off` plus its colour: the scene's own colour is set.
- An effect comes back by its name, `Effect xxxxxxxx` names included, at its default speed: the
  speed is the state of the speed number, not of the light. To restore it with a snapshot, add the
  speed number after the light in `snapshot_entities`.
- `Unknown palette effect` cannot be sent, because its frames are unknown. If an unidentified palette
  effect is still running, the mode is left as it is; otherwise the current colour or effect is kept
  and a warning is logged. Brightness and on/off are restored in both cases, and the scene does not
  fail.
- Home Assistant applies the light and the effect speed number of a scene at the same time; the
  integration runs their commands one after the other, in the order they appear in the scene. A scene
  restores an effect's speed reliably only when the light is listed **before** the speed number, and
  only if the speed number is available when the scene starts (an effect with an adjustable speed is
  already running). Otherwise the speed is skipped or reaches the previous effect, and the scene's
  effect starts at its default speed. To be sure, use a script: `light.turn_on` with the effect, then
  `number.set_value`.

## Effects

- **Strip: 52 built-in effects.** There are 12 default effects (80s Club, Cherry Blossom, Cocktail
  Parade, Instagrammer, Pensieve, Savasana, Sunrise, The Circus, Unicorns, Christmas, Rainbow Flow,
  Music Mode) and 40 dynamic effects. 22 of the dynamic effects are **multi-frame palette effects**
  (Graffiti, Tron, Urban beauty, Cyberpunk, Tropic affair, Go by, Break dance, Children park,
  Thunder, Red/Green/Blue meteor, Forest, Cherry lake, World cup, Sunset, Tide, Lilac, Witch hut,
  Cranberry, Tricolor, Innocence), whose speed cannot be changed.
- **Hexagon: the 12 default effects.**
- The names and codes come from pycololight. Your custom effects (options) are added to the list. A
  custom effect with the same name as a built-in one replaces it.
- An effect started from the official app is recognised when it matches a known code (a single-frame
  effect at any speed, a palette effect by its last frame, see
  [Known limitations](#known-limitations)). Otherwise it is shown as `Effect xxxxxxxx` or
  `Unknown palette effect`.

## How it works (short)

- There is one UDP socket per lamp, with one request in flight at a time. Replies are matched to
  requests by sequence number, and the MAC address carried by each reply is checked: a reply from
  another device is refused at once, without retry.
- Commands from the light and the speed number, and the saves, run one at a time, each starting from
  the state left by the previous one.
- Every command is acknowledged by the lamp with the value it applied. The integration waits up to
  1.5 s for that acknowledgement, retries after 0.2 s, 0.5 s and 1 s (4 attempts in total, i.e. 3
  resends, about 8 s at most), and updates the entity from the acknowledgement. A command that still
  fails raises an error in the UI.
- A single frame is an absolute value (never a toggle), so a retry cannot produce a wrong state.
  Palette effects are uploaded frame by frame, each frame with its own retries. Their frames form a
  sequence: if one of them had to be sent twice, the whole upload is restarted once from its first
  frame (that this start marker resets the lamp's upload is an assumption, not verified on the device).
- Each poll reads power/brightness and colour/effect (two requests). One or two failed polls are
  ignored. At the 2nd and 3rd failed polls in a row, then every 4th one, a broadcast search looks for
  the lamp's MAC, follows it to a new IP, or reads it again if it answers at the same address (it may
  have just finished booting). After three failed polls the entities become unavailable, and they come
  back as soon as the lamp answers.
- DHCP discovery matches the Espressif prefix `4C:11:AE`, which other ESP-based devices share: each of
  them gets one short UDP probe on port 8900, and is ignored when it does not answer as a Cololight.

## Troubleshooting

**Debug logging.** Use **Enable debug logging** on the integration page; when you disable it, Home
Assistant offers the log file for download. Or set it in `configuration.yaml`:

```yaml
logger:
  default: warning
  logs:
    custom_components.cololight_local: debug
```

Debug logs contain every frame sent and received, in hex.

**Diagnostics.** Go to **Settings → Devices & services → Cololight (local) → ⋮ → Download
diagnostics**. The file contains the options, the last state, the remembered effect, the failure
counter and the client statistics: requests, retries, timeouts, late replies, rejected requests,
replies from another device, palette upload restarts and round-trip times. The IP and MAC addresses
are redacted. Many retries usually means weak WiFi at the lamp.

**Common problems**

| Symptom | What to check |
|---|---|
| Lamp not discovered | Same subnet/VLAN as Home Assistant? Docker without host networking? The 15-minute scan only runs once a lamp is configured: add the first one from **Add integration**, or by IP |
| *No Cololight answered at this address…* when adding by IP | Correct IP (see your router)? Lamp powered and on WiFi (does the app work)? UDP 8900 not blocked |
| Entities unavailable | Lamp unplugged or switched off at the wall, WiFi down, or new IP not found yet. They come back by themselves when the lamp answers |
| *The Cololight at … did not answer. Check that it is powered and connected to your Wi-Fi, then try again.* | The lamp did not acknowledge 4 attempts, or another device answered at its address. Check the WiFi signal, and look at the diagnostics counters |
| *Unknown effect: … Effect names are case-sensitive…* | Write the name exactly as in the effect list. Dynamic effects exist only for the Strip model |
| *Invalid custom effect: "…" is not a colour of the … scheme…* | The message lists the valid colours: copy one exactly (English, case-sensitive) |
| *The running palette effect is not identified…* when saving | Start the effect by its name from Home Assistant, then save |
| Lamp does not answer at all, LEDs frozen | The lamp's WiFi module hung. Unplug it for 10 s and wait 20–30 s after plugging it back in |
| The official app does not show what Home Assistant did | Normal. The app reads the cloud, not the lamp. Home Assistant does see changes made in the app, at the next poll |

## Known limitations

- **Multi-frame (palette) effects are reported by their last frame only.** The integration remembers
  the effect it sent, also across restarts and reloads. Four pairs end with the same frame and cannot
  be told apart from what the lamp reports: **Tron/Tricolor, Tropic affair/Red meteor, Break
  dance/Sunset, Witch hut/Cranberry**. One of these 8 effects started from the official app or with
  `set_effect_code` shows as `Unknown palette effect`, and so does a palette effect that is not in the
  tables. The other 14 palette effects are always named. A direct switch in the app between the two
  effects of a pair cannot be detected (the old name stays). An unidentified palette effect cannot be
  saved, nor restored by a scene or snapshot.
- **80s Club and Unicorns differ only by their speed**, so changing the speed can change the reported
  name.
- **No local push.** The lamp never reports changes on its own (checked for 2 × 150 s while using the
  app), so the integration polls. Changes made elsewhere appear within the polling interval.
- **Brightness is capped at 100 %.** The lamp accepts 0–101, but a value of 255 made it drop off
  WiFi until it was unplugged. The integration never sends more than 100 and never sends 0 (it turns
  the lamp off instead).
- **The official app uses the LifeSmart cloud** and does not display local changes. Both can be used;
  the last command wins.
- <a id="eeprom-wear"></a>**EEPROM wear.** Normal commands are volatile (operation `04`): after a power
  cut, the lamp comes back with the last *saved* state, from the app or from this integration. Saving
  (operation `07`) writes to flash memory, which supports a limited number of writes. This is why the
  automatic save option is **off by default**. When it is on, the state is written once after it has
  been stable for the delay, never on each slider move, never while the lamp is off and never when it
  has not changed (see [Automatic save](#automatic-save)). Leave it off if your automations change the
  lamp every few minutes, and use the button or the `save_state` action at chosen moments instead.
  Saving overwrites the power-on state set in the official app.
- **The power state "off" is never saved**: when the lamp is off, saving stores the colour/effect
  only. A lamp saved as "off" would probably stay dark when switched on at the wall (not tested).
  Whether a colour/effect written while the lamp is off (button or action) switches it on has not been
  tested either. In our tests the lamp always came back on with its saved state after a power cut.
- Saving colour and brightness was verified on a real lamp. Saving an **effect** was not.
- Scenes restore the effect speed only in the conditions given in
  [Scenes and snapshots](#scenes-and-snapshots).
- The Hexagon is untested. The model must be chosen by hand.

## Development

- **Tests.** From the repository root: `pip install -r requirements_test.txt`, then `pytest`. They run
  with pytest-homeassistant-custom-component against an emulator of the lamp
  ([`tests/fake_lamp.py`](tests/fake_lamp.py)) on the loopback interface: no test ever sends a packet
  to a real lamp. The pinned test plugin installs Home Assistant 2026.10.4, which needs Python 3.14 and
  does not run natively on Windows: use Linux, WSL, or the Docker image
  (`docker build -f docker/test.Dockerfile -t cololight-test .`, then
  `docker run --rm -v "$PWD":/work -w /work cololight-test pytest`). On macOS, the few tests that need a
  second loopback address (127.0.0.2) are skipped.
- **Continuous integration** (GitHub Actions). `.github/workflows/tests.yml` runs the tests on Python
  3.14 (with coverage) on every push and pull request. `.github/workflows/validate.yml` runs hassfest
  and the HACS validation (also weekly). The HACS check expects the GitHub repository to have a
  description and topics.
- **Documentation of the protocol**: [`docs/protocol.md`](docs/protocol.md),
  [`docs/findings.md`](docs/findings.md) (what was measured on the real lamp) and
  [`docs/integration-design.md`](docs/integration-design.md).

## Credits

- [pycololight](https://github.com/BazaJayGee66/pycololight) and
  [homeassistant_cololight](https://github.com/BazaJayGee66/homeassistant_cololight) by BazaJayGee66
  (MIT): effect tables, custom effect encoding and the first Home Assistant integration.
- [Projekt: ColoLight in FHEM](https://haus-automatisierung.com/projekt/2019/04/05/projekt-cololight-fhem.html)
  (haus-automatisierung.com): the original reverse engineering of the UDP protocol.
- The protocol details used here (acknowledgements, element 02 read-back, EEPROM write, discovery)
  were measured on a real strip. See [`docs/findings.md`](docs/findings.md).

Not affiliated with LifeSmart.

## License

MIT, see [`LICENSE`](LICENSE). The effect tables are derived from pycololight (MIT, © 2021
BazaJayGee66).
