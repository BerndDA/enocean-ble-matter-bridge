# EnOcean–Matter bridge PCB

One board for [firmware/enocean-gateway](../../firmware/enocean-gateway/): a bare nRF52840, a TCM 515 and USB-C. It replaces the Pro Micro nRF52840 plus EnOcean Pi hat.

**Firmware compatibility is the main constraint.** The board keeps every pin the Pro Micro build uses, and its three status LEDs are wired like those of the [EnMT carrier](../enocean-carrier/DESIGN.md). So **`make flash APP=enocean-gateway BOARD=enmt`** runs on it unchanged, LEDs included, UF2 bootloader included. `BOARD=promicro-uf2` (and `BOARD=promicro`) run too, with the LEDs dark. No new board definition is needed for the first revision.

Status: schematic done (47 parts, ERC clean). PCB placed and fully routed ([enocean-bridge.kicad_pcb](enocean-bridge.kicad_pcb)): 57 × 26 mm, 0 unconnected, 0 DRC errors, schematic parity clean, only silkscreen warnings. Nothing is ordered yet.

Simplified from the first version (67.2 × 26 mm, 62 parts): no u.FL, no test pads, no polyfuse, no RF tuning pads, no DEC5 cap, no mounting holes; the 2.4 GHz antenna stands along the right edge; all parts on the top side; three status LEDs instead of one.

## Decisions

| Topic | Choice | Why |
| --- | --- | --- |
| EnOcean module | TCM 515, soldered (castellated) | Current part; small; 868.3 MHz, ESP3, same protocol as the TCM 310 |
| MCU | Bare nRF52840-QIAA (aQFN73), Nordic **circuit configuration 3** | Single 3.3 V supply on VDD, USB, LDO mode: the same regulator setup the Zephyr `promicro` board uses (no DC/DC enabled) |
| RF match | Nordic's 4-component match (config 7 values) | Nordic recommends it for new designs (better harmonic suppression) |
| 2.4 GHz antenna | PCB antenna (TI SWRA117D meander, in KiCad's `RF_Antenna` library) | No part to source; the Johanson 2450AT18 chip antenna isn't stocked at JLCPCB |
| 868 MHz antenna | 86 mm wire whip in a plated hole, no u.FL | Whip is what TCM 515 is certified with (RED); one antenna option keeps the layout simple |
| Supply | USB-C 5 V → 3.3 V LDO → nRF VDD and (through a ferrite) TCM VDD | ≈ 60 mA total; a linear regulator keeps switching noise away from the 868 MHz ASK receiver (TCM manual 11.6/11.7) |
| 32.768 kHz | None | Firmware runs the LF clock from the RC oscillator (`CONFIG_CLOCK_CONTROL_NRF_K32SRC_RC`), like the Pro Micro; XL2 (F2) also can't escape the aQFN at JLC's 0.1 mm minimum |
| Layers | 4 (Signal / GND / +3V3 / Signal), 1.6 mm, JLC04161H-7628; signals only on top and bottom | The aQFN73 inner pads AC5 (DECUSB) and AC13 (nRESET) need vias in pad, which JLC doesn't confirm for 2 layers; continuous GND under both radios; unbroken +3V3 plane |
| Assembly | JLCPCB PCBA, top side only, everything except the TCM 515 | One-sided assembly is cheaper; TCM 515 is not stocked at JLCPCB/LCSC: hand-solder or consign it |
| Mounting | No holes | Not needed yet; they took two corners of the board |

## Pin map (Pro Micro contract)

| Function | nRF52840 pin (ball) | Connects to | Firmware source |
| --- | --- | --- | --- |
| UART0 TX → TCM | P0.09 (L24, NFC1) | TCM 515 pin 20 UART_RX | `promicro_nrf52840_common.dtsi`, 57600 8N1 |
| UART0 RX ← TCM | P0.10 (J24, NFC2) | TCM 515 pin 21 UART_TX | same; board sets `nfct-pins-as-gpios` |
| Status LEDs | P1.11 (B19), P1.13 (A16), P1.15 (A14) | red PWR, green LINK, yellow RX; 3.3 V → LED → resistor → pin, **active low** | `BOARD=enmt` ([enmt_carrier.overlay](../../firmware/common/boards/enmt_carrier.overlay)); P0.15 (the Pro Micro's `led0`) stays unconnected |
| Function button | P1.06 (R24) | Push button to GND (internal pull-up) | `sw0`, hold 6 s = factory reset |
| Reset | P0.18/nRESET (AC13) | Push button to GND; double-tap = UF2 bootloader | `gpio-as-nreset` |
| USB | D+ (AD6), D− (AD4), VBUS (AD2) | USB-C via ESD array | USB CDC console |
| SWD | SWDIO (AC24), SWDCLK (AA24) | Tag-Connect TC2030 pads | Bootloader flashing, `BOARD=promicro` |
| TCM reset (new) | P0.20 (AD16) | TCM 515 pin 24 nRESET | Unused by today's firmware: the pin floats as an input and the TCM's internal pull-up wins. Lets later firmware reset a stuck TCM |

Everything else stays unconnected. The firmware doesn't use P0.13 either, the nice!nano's VCC switch pin.

## Circuit

### nRF52840 (configuration 3, Product Specification v1.11, Figure 220 / Table 75)

| Ref (PS) | Value | Pin(s) | Note |
| --- | --- | --- | --- |
| C5 | 100 nF | DEC1 (C1) | |
| C13 | not mounted | DEC2 (A18) | |
| C11 | 100 pF NP0 | DEC3 (D23) | |
| C15 | 1.0 µF | DEC4 (B5) + DEC6 (E24), tied together | C10 (to GND) not mounted |
| — | — | DEC5 (N24) | unconnected: the 820 pF (PS C9) isn't needed on Fxx silicon (JLC stocks NRF52840-QIAA-**F**-R7) |
| C20 | 4.7 µF | DECUSB (AC5) | |
| C21 | 4.7 µF X7S | VBUS (AD2) | 2.2 Ω series resistor from USB VBUS (Nordic's recommended transient protection) |
| C14 | 1.0 µF | VDD (B1) | |
| C12, C7, C8 | 100 nF | VDD (A22), VDD (AD14), VDD (AD23) | one per VDD pin, at the pin |
| C6 | 4.7 µF | VDD (W1) | VDDH (Y2) tied to VDD: normal-voltage mode |
| — | — | DCC (B3), DCCH (AB2) | unconnected (no DC/DC) |
| — | — | VSS (B7), VSS_PA (F23), exposed pad (EP) | GND |
| X1, C1, C2 | 32 MHz 2016, CL 8 pF; 12 pF NP0 ×2 | XC1 (B24), XC2 (A23) | ABM11W-32.0000MHZ-8-D1X-T3 (C5189005) |
| — | — | XL1 P0.00 (D2), XL2 P0.01 (F2) | unconnected: no 32.768 kHz crystal (see Decisions) |

### 2.4 GHz RF path (configuration 7, Table 83)

```
ANT (H23) ─┬─ L1 4.7 nH ─┬─ L5 2.2 nH ──── 50 Ω CPWG ──── PCB antenna
           │             │
          C3 1.0 pF     C4 1.2 pF
           │             │
          VSS_PA        GND
```

C3's ground goes to VSS_PA (F23) as in the reference. The match sits right at the pin, before any trace. No tuning pads: the meander antenna is used as TI specifies it, without a VNA to tune it.

### TCM 515 (User Manual v1.22)

- VDD (22): 3V3 → ferrite bead (Würth 742863160 or LCSC equivalent, manual 11.6) → 22 µF X5R/X7R ≥ 6.3 V + 100 nF at the pin.
- nRESET (24): 100 nF to GND at the pin (manual Figure 20), plus a link to P0.20.
- nTURBO (31): 10 kΩ pull-up to TCM VDD, plus an open solder jumper to GND. The firmware expects 57600 baud; closing the jumper would make the module start at 460800 baud.
- UART_RX (20) ← P0.09, UART_TX (21) → P0.10. No test pads (the manual recommends them): probe the UART at the module's castellated pins.
- TP1–TP3 (25–27): unconnected, no test pads.
- RF_50 (2): 50 Ω CPWG → 0 Ω series resistor → whip hole. No tuning pads.
- GND (1, 3, 6, 15, 23). Every NC pad stays unconnected (manual: "must not be connected").

### USB and power

- USB-C receptacle HRO TYPE-C-31-M-12 (C165948): CC1/CC2 each 5.1 kΩ to GND (USB 2.0 sink), shield to GND through 1 MΩ ∥ 10 nF.
- ESD: USBLC6-2SC6 on D+/D− and VBUS, placed at the connector.
- 5 V → 3.3 V LDO, ≥ 300 mA, SOT-23-5 (AP2112K-3.3 or ME6211C33, whichever JLC has in stock at order time). 4.7 µF in, 4.7 µF out. Budget: nRF52840 ≈ 15 mA (radio + USB) + TCM 515 25 mA RX/TX + LED ⇒ < 60 mA.
- No polyfuse: USB hosts and chargers limit their own port current, and the LDO has current limiting and thermal shutdown (the Pro Micro has none either).

### UI and debug

- Buttons RESET (P0.18) and FUNC (P1.06): small SMD tactile switches to GND.
- Three 0805 LEDs as on the EnMT carrier, all JLC basic: red D1 (NCD0805R1, C84256) with R9 1 kΩ on P1.11, green D2 (KT-0805G, C2297) with R10 330 Ω on P1.13, yellow D3 (KT-0805Y, C2296) with R11 1 kΩ on P1.15. Anodes on 3.3 V; a pin pulled low lights its LED. In a row 4 mm apart, one light pipe each.
- SWD: Tag-Connect TC2030-IDC-NL footprint (VDD, SWDIO, nRESET, SWDCLK, GND). The DK's Debug Out (P20) can drive it through a TC2030 cable, or through pogo pins on the TC2030 pads.
- No test pads.

## Board outline and layout

```
 ←———————————————————————— 57 mm ———————————————————————→
 ┌─────┬───────────────────────┬─────────────────────┬────┐  ↑
 │whip │                       │ FB1  decoupling  X1 │2.4 │  │
 │ o   │       TCM 515         │     nRF52840 ─ match┤GHz │  │
 │     │   (no copper under    │ LDO                 │ant.│ 26 mm
 │     │    module, top+bottom)│ CC  ESD caps    ┌───┴────┤  │
 │     │  FUNC  RESET          │                 │TC2030  │  │
 │     │                       │      ESD     LED LED LED │  │
 └─────┴───────────────────────┴──[USB-C]─────────────────┘  ↓
```

- The 2.4 GHz antenna and the 868 MHz antenna sit at opposite ends. The 2.4 GHz meander (SWRA117D, KiCad's `_Left` variant turned 270°) stands along the right edge, radiating towards it, open end in the top-right corner. The ground plane runs beside it over its full length and continues past its short end, as in TI's layout turned by 90°. No copper on any layer between the antenna and the board edge.
- In1 is solid GND everywhere except under the 2.4 GHz antenna. Stitch GND vias densely along both RF lines and the board edge.
- The TCM 515 needs a GND plane of at least 38 × 18 mm and 10 mm from the whip to the GND plane (manual 12.1.1). No tracks under the module on the top (footprint keepout) or the bottom (rule area from the board's left and top edges to the module's outline, which also keeps signals away from the RF pin and the whip). GND stitching vias under it must be tented.
- 50 Ω CPWG on the top layer, referenced to In1: about 0.3–0.35 mm trace with 0.15–0.2 mm gap on JLC04161H-7628. This is an estimate; confirm it with JLC's impedance calculator and order with impedance control.
- aQFN73: follow Nordic's reference layout for the decoupling placement (each cap at its pin, DEC caps first). Vias in the inner-row pads need via-in-pad (epoxy-filled and capped) or 0.2/0.4 mm vias between pads. Check JLC's current rules at order time.
- USB D+/D−: 90 Ω differential, short. The ESD array goes at the connector.
- All UART/TCM I/O lines < 5 cm (TCM manual 11.5); trivially met.

## Sourcing (JLCPCB/LCSC, checked 2026-11-18)

| Part | LCSC | Note |
| --- | --- | --- |
| nRF52840-QIAA-F-R7 | C3606858 | extended, 241 in stock |
| 32 MHz ABM11W-32.0000MHZ-8-D1X-T3 | C5189005 | |
| USB-C TYPE-C-31-M-12 | C165948 | |
| USBLC6-2SC6 | C3029034 (USBLC6-2SC6-MS) | |
| 4.7 nH 0402 | C97989 (LQG15HN4N7S02D) | |
| 2.2 nH 0402 | C162540 (LQG15HS2N2B02D) | low stock; any 2.2 nH ±0.1 nH, 0402 HF inductor |
| 1.2 pF C0G 0402 (C20) | C85877 (Murata GJM1555C1H1R2CB01D) | ±0.25 pF, high-Q RF series; ±0.1/±0.05 pF versions not stocked (checked 2026-11-20) |
| TCM 515 | — | buy from EnOcean distributors (Mouser, Digi-Key); MSL 4: 72 h floor life, solder once |

Passives come from JLC's basic library at BOM time. The remaining LCSC numbers are filled in with the schematic.

## Bring-up

1. JLC delivers a blank nRF52840. Flash the nice!nano UF2 bootloader (Adafruit `nice_nano_bootloader-<ver>_s140_6.1.1.hex`, ≥ 0.6.1) over SWD from the DK's Debug Out, as in the README's SWD section.
2. The board now enumerates as a UF2 drive. Then `make flash APP=enocean-gateway BOARD=enmt`: red PWR must stay on (blinking = no answer from the TCM).
3. `enocean info` in the shell must show the TCM version and base ID. If it doesn't, check that the nTURBO jumper is open and probe the UART at the TCM's castellated pins 20/21 (57600 baud).

## Schematic

The schematic is generated: [tools/design.py](tools/design.py) holds every part with its value, footprint, LCSC number and pin → net map, and [tools/gen_schematic.py](tools/gen_schematic.py) writes `enocean-bridge.kicad_sch` from it with KiCad's own library symbols (TCM 515 from [../lib/](../lib/)). The sheet ([enocean-bridge.png](enocean-bridge.png)) has four framed blocks: nRF52840 with decoupling, crystal and 2.4 GHz match; TCM 515; USB-C/ESD/LDO; buttons, LED and SWD. Inside a block, parts are wired (`WIRES` in `design.py`); net labels carry only the signals between blocks. The generator splits wires at every T, adds the junction dots, and refuses wires that join two different nets. **Change the circuit in `design.py`** and regenerate. Edits made in Eeschema are overwritten.

```sh
cd hardware/enocean-bridge-pcb
python3 tools/gen_schematic.py        # writes enocean-bridge.kicad_sch, sym-lib-table, fp-lib-table
kicad-cli sch erc enocean-bridge.kicad_sch
python3 tools/check_netlist.py        # KiCad's netlist vs design.py, pin by pin
```

`kicad-cli` is `/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli` on macOS. Current state: 47 parts, ERC 0 errors / 0 warnings, netlist matches `design.py`.

Without LCSC number: U4 (TCM 515, hand-soldered), AE1, JP1 and J3 (copper only).

## PCB

[tools/gen_pcb.py](tools/gen_pcb.py) builds `enocean-bridge.kicad_pcb` with KiCad's Python API. It takes nets and fields from KiCad's netlist of the schematic and placement from [tools/placement.py](tools/placement.py):

- **Board:** 57 × 26 mm, 4 copper layers, 1.6 mm (order as JLC04161H-7628 with impedance control).
- **Layer use:** In1 solid GND (the reference under both radios), In2 the +3V3 plane, GND pours on top and bottom. Signals run on top and bottom only.
- **Keepouts:** no copper on any layer over the 2.4 GHz antenna; no top copper under the TCM 515 (keepout in its footprint); no bottom tracks under the TCM 515 or between it and the left and top board edges (rule area in `gen_pcb.py`).
- **Net classes:** Default 0.15/0.15 mm, Power 0.3 mm, RF 0.37 mm with 0.2 mm clearance (50 Ω CPWG on 0.2104 mm prepreg, εr 4.4; quasi-static calculation: 49.7 Ω at 0.38 mm, 51.2 Ω at 0.36 mm).
- **Design rules:** JLC multilayer limits in the project: 0.1 mm track/clearance, 0.4/0.2 mm via. One custom rule in `enocean-bridge.kicad_dru` lets RF items inside the nRF52840's courtyard keep 0.1 mm. The ANT pad is an inner-row aQFN pad and escapes between E24 and J24 as a 0.15 mm neck.
- **Routed by the script:** both RF paths, i.e. the 2.4 GHz match from ANT along y = 8.75 mm, then right after L2 45° down, straight down beside the antenna's ground edge and 45° into the feed (turning early keeps the board short), and TCM RF_50 → whip. Also VSS_PA to the exposed pad, ground vias at every RF shunt, and a via fence along the 2.4 GHz line.
- **Not routed:** everything else.
- **Block check:** each part must sit inside the board area of its schematic block (`BLOCKS` in `placement.py`); `gen_pcb.py` stops otherwise.

[tools/render_placement.py](tools/render_placement.py) draws the placement before routing: block areas, keepout, courtyards, pads and the ratsnest still to route ([enocean-bridge-placement.png](enocean-bridge-placement.png); after routing, pass `autoroute/unrouted.kicad_pcb`).

```sh
KPY=/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3
$KPY tools/gen_pcb.py            # refuses to overwrite a board with tracks once routing started; --force overrides
kicad-cli pcb drc --schematic-parity enocean-bridge.kicad_pcb
tools/render_png.sh              # schematic PNG + 3D render of the board
```

KiCad 10 needs units in `.kicad_dru` values (`0.1mm`). Without them, kicad-cli silently ignores the whole rule file.

**Once routing starts, the board belongs to KiCad.** Change parts in `design.py`, regenerate the schematic, then "Update PCB from Schematic" in the PCB editor (footprints are linked to their symbols). Don't rerun `gen_pcb.py --force`.

## Routing

The board is routed by a pipeline, not by hand:

1. `gen_pcb.py` places the parts and draws everything that must not be left to the router:
   - both RF paths;
   - power fanout: one via per nRF52840 VDD pin into the In2 +3V3 plane, one via per capacitor GND / +3V3 pad and per CC/shield resistor GND pad, and one via for every other +3V3 pad (LDO output, FB1, TC2030);
   - the 9 vias in the exposed pad;
   - vias in the pads of AC5 (DECUSB), AC13 (nRESET) and B19 (P1.11, red LED): inner-row pads whose outer neighbours leave no reliable escape.
   All of these tracks and vias are locked.
2. `route.py` runs `autoroute.py` (Freerouting 2.5.0, headless) with several strategies and keeps the best, then `stitch.py` adds GND stitching vias and DRC scores the result. In1 and In2 are offered to Freerouting as plane layers, so it routes signals on top and bottom only (`PLANE_LAYERS=In1` in the environment would let it use In2 again). Only the 0.45/0.25 mm via is offered to it.

```sh
KPY=/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3
$KPY tools/gen_pcb.py --force && python3 tools/route.py
```

Current result: routed by the first strategy, 0 unconnected, 0 DRC errors, schematic parity clean, 7 silkscreen warnings. Signal tracks: 370 mm on top, 203 mm on the bottom, 30 signal vias; no tracks on In1 or In2, none under the TCM 515. Pictures: [top](enocean-bridge-layer-top.png), [In1](enocean-bridge-layer-in1.png), [In2](enocean-bridge-layer-in2.png), [bottom](enocean-bridge-layer-bottom.png) copper, 3D [top](enocean-bridge-top.png) and [bottom](enocean-bridge-bottom.png).

**Ordering note:** the three vias in the pads of AC5/AC13/B19 are 0.25/0.15 mm. Order with epoxy-filled and capped vias (JLC "via in pad"), which applies to every via on the board.

## Ordering at JLCPCB

`python3 tools/export_fab.py` writes [fab/](fab/):

| File | Use |
| --- | --- |
| [enocean-bridge-gerbers.zip](fab/enocean-bridge-gerbers.zip) | Gerbers (4 copper layers, mask, paste, silkscreen, outline) + Excellon drill; upload this as the PCB |
| [enocean-bridge-bom.csv](fab/enocean-bridge-bom.csv) | BOM for assembly, 28 lines / 42 parts (JLC columns: Comment, Designator, Footprint, LCSC Part #) |
| [enocean-bridge-cpl.csv](fab/enocean-bridge-cpl.csv) | Placement for assembly (Designator, Mid X, Mid Y, Layer, Rotation), top side only |

**PCB:** 4 layers, 1.6 mm, stackup **JLC04161H-7628** (the 50 Ω lines are calculated for it), impedance control on, **epoxy-filled and capped vias** (via in pad at AC5, AC13 and B19 of the nRF52840), ENIG surface finish (flat pads for the 0.5 mm aQFN73 and the filled vias).

**Assembly:** top side; JLC places everything except U4. Not in the BOM: U4 (TCM 515, hand-soldered after assembly), AE1 (antenna), JP1 (solder jumper), J3 (TC2030 pads), TP1 (whip hole): copper only.

**Check in JLC's placement preview before confirming:**
- the rotations of U1 (nRF52840, pin 1 marker), U2/U3 (SOT-23-5/6), Y1 and J1;
- LED polarity: the cathode (pad 1) of D1–D3 is on the left; the anodes (right) go to +3V3.

## Cost estimate (2026-11-18)

5 assembled boards at JLCPCB, rough, before the real quote:

| Item | Cost |
| --- | --- |
| Bare board, 4 layers, 57 × 26 mm | ~$10–20 |
| Via in pad on 4 layers (free only from 6 layers) | maybe +$15–40 |
| Parts from JLC stock (LCSC prices; the five nRF52840s are $31.50 of it, $6.30 each) | ~$45 |
| Assembly, Economic, top side only: $8.18 setup + $1.53 stencil + extended-part fees ($3.07 each) | ~$40 |
| Assembly, if Standard is needed: $25.56 setup + $8.21 stencil + ≥ $14.93 handling + $1.53 per distinct part | ~$90 |
| Shipping (DHL), import VAT 19 % + customs handling | ~€45–75 |
| 5 × TCM 515 (Digi-Key, before VAT) | ~€63 |

Total about €200–290, i.e. €40–55 per board. Setup, stencil and part fees are paid once per order, so 10–20 boards cost much less each.

## Next steps

The open items are tracked in the repo's [TODO.md](../../TODO.md), section "EnOcean bridge PCB".
