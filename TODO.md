# TODO

What's left to do and to decide. Tick items off here; the plan behind the steps is in [doc/BLE-to-Matter-over-Thread-Gateway.md](doc/BLE-to-Matter-over-Thread-Gateway.md).

## Decisions

- [ ] **Far sensors.** The sensor in the other room delivers about 1 % of its advertisements, with gaps of up to 6.5 minutes ([measurements](doc/measurements.md)). Options:
  - Place the gateway more centrally (no code change).
  - Have pvvx advertise more often, for example every 1 s (costs sensor battery).
  - Scan at a 50 % duty cycle instead of 25 % (costs Thread listening time; run the A/B test again).
- [ ] **Unreachable timeout.** 10 minutes now. Raise it if far sensors stay, or keep it once reception is better.

## Next

- [ ] EnOcean hardware: decide between the carrier board (Pro Micro + TCM 515, simple) and the full custom board (see the two sections below).

## EnOcean carrier board

Pro Micro nRF52840 soldered onto a 2-layer board with a TCM 515. Design in [hardware/enocean-carrier/DESIGN.md](hardware/enocean-carrier/DESIGN.md).

- [x] Pro Micro symbol and footprint (with antenna keepout) in `hardware/lib/`; the TCM 515 library moved there too.
- [x] Schematic: ERC clean, netlist checked.
- [x] Board: placed, 868 MHz path, autorouted, stitched. DRC 0 errors, 0 unconnected.
- [x] One small SMD button (Pro Micro reset), no function button, no test pads; TCM rotated, board 46.5 × 33.4 mm.
- [ ] Check the Pro Micro pinout against the module you'll use (B+/GND/RST/VCC = top four of the right column).
- [ ] Review the routing; tidy the 8 silkscreen warnings.
- [x] Function button (SW2, P1.06) and an EnOcean LED (P1.11) added back in the space the rotated TCM freed.
- [x] Fabrication files: `fab/` (Gerbers + drill zip, BOM and CPL for JLC assembly of the 10 small parts).
- [x] v0.2: three status LEDs (P1.11 red, P1.13 green, P1.15 yellow, active low, all JLC basic) instead of the single LED; whip hole for wire up to 1.5 mm. v0.1 kept as tag `enocean-carrier-v0.1`.
- [x] Firmware: `BOARD=enmt` drives the status LEDs in both apps (green LINK = Matter status, yellow RX = packet pulse, red PWR = on / TCM answers); `promicro-uf2` and `dk` unchanged. Test on the real board, EnOcean and BLE.
- [ ] Order at JLCPCB: upload the zip, 2 layers 1.6 mm; optionally PCB Assembly (Economic, top) with the BOM/CPL, check the placement preview.
- [ ] Order 5 × TCM 515 (Digi-Key 1084-TCM515), Pro Micros (with their pin headers; no sockets), 3 mm clear acrylic rod for the three light pipes (3 × 8.7 mm per case), one M2 × 6 mm screw and hex nut per case; passives and buttons only if not assembled by JLC.
- [ ] Assemble, flash `BOARD=promicro-uf2`, check `enocean info` and range with the whip.
- [x] 3D-printable case (`case/`, OpenSCAD).
- [ ] Case: measure the Pro Micro height on the real stack, adjust `pm_gap`/`usb_z`, test-print the base.
- [ ] Tools are copies of the custom board's (`tools/`); share them if both boards stay.

## EnOcean bridge PCB

nRF52840 + TCM 515 + USB-C, pin-compatible with the Pro Micro build. Design, scripts and status in [hardware/enocean-bridge-pcb/DESIGN.md](hardware/enocean-bridge-pcb/DESIGN.md).

- [x] Design and decisions (TCM 515 soldered, bare nRF52840 in Nordic configuration 3, 4 layers, JLCPCB assembly).
- [x] TCM 515 footprint and symbol from the EnOcean manual.
- [x] Schematic, generated from `tools/design.py`: ERC clean, netlist checked pin by pin.
- [x] PCB: placement, both RF paths, power fanout, autorouting (Freerouting), GND stitching: 0 DRC errors.
- [x] Simplified: no u.FL, test pads, polyfuse, RF tuning pads, DEC5 cap or mounting holes; antenna along the right edge; 57 × 26 mm, all parts on top; three status LEDs wired as on the EnMT carrier (`BOARD=enmt`); no tracks under the TCM 515 on either side; signals on top/bottom only, In2 an unbroken +3V3 plane; fully routed, 0 unconnected.
- [ ] Review the autorouted board, especially USB D+/D− (90 Ω pair, short, ESD at the connector), the decoupling paths at the nRF52840, and that nothing crosses the RF areas.
- [ ] From here on edit the board in KiCad only: don't rerun `gen_pcb.py --force` / `route.py`, they start from scratch.
- [x] LCSC part for C20: C85877, Murata GJM1555C1H1R2CB01D (±0.25 pF; tighter ones aren't stocked).
- [x] Fewer extended parts: buttons (TS-1187A), LDO (XC6206) and R4 (0 Ω) from JLC's basic library; 8 extended parts left, none of them replaceable.
- [ ] Cosmetics: 9 silkscreen warnings on the board (J1 outline and JP1/AE1 references at the edge, references over pads, SW1/SW2 labels on the TCM outline).
- [x] Fabrication outputs: Gerbers, drill, BOM and CPL in JLC format (`tools/export_fab.py`, TCM 515 not assembled).
- [x] JLC quote (2026-11-20): PCB $8, Economic PCBA $107.50 (takes the aQFN73, with X-ray); about $98 after the basic-part swaps (DESIGN.md, "Cost").
- [ ] Before ordering: select epoxy-filled and capped vias (the quote showed "Via Covering $0.00"); JLC04161H-7628 stackup with impedance control; ENIG.
- [ ] Check JLC stock of the nRF52840 (C3606858, 241 on 2026-11-18) right before ordering.
- [ ] Order 5 × TCM 515 (Digi-Key 1084-TCM515, about €12.50 each).
- [ ] Bring-up: solder the TCM 515, solder the SWD header J3, flash the nice!nano UF2 bootloader over SWD (DK Debug out P19, 10-pin flat cable), then `make flash APP=enocean-gateway BOARD=enmt`, `enocean info`.
- [x] 3D-printed case (`hardware/enocean-bridge-pcb/case/`): like the carrier's, light pipes for 3 mm rods, SWD opening, no screws.
- [ ] Later: own board definition in `firmware/boards/` once pins change (e.g. TCM reset on P0.20).

## Step 4: one thermostat

- [x] eQ-3 CC-RT-BLE with [eq3-custom-fw](https://github.com/dbuezas/eq3-custom-fw): values come from BTHome broadcasts, control over GATT ([spike/eq3-flash](spike/eq3-flash/README.md), protocol in the firmware's PROTOCOL.md).
- [x] Thermostat endpoint (cluster 0x0201), read-only: room temperature, target, valve as heating demand, Off below 4.75 °C, battery from voltage and low flag.
- [x] Checked in Apple Home.
- [x] Setpoint and Off/Heat from Apple Home: one short GATT connection per command, 7–13 s until the thermostat has it. Needs the thermostat's PIN off ("Ask for a PIN" in the web app, or `PIn CodE` in its Bluetooth menu).
- [x] Decided: thermostats run without PIN. The gateway does not pair; anyone in Bluetooth range could control or reflash a thermostat.
- [x] Decided: thermostats run in manual mode. Every target from Apple Home is sent as manual + target (`40 <0x40 | temp×2>`), so the weekly schedule does not override it (`CONFIG_GATEWAY_EQ3_TARGET_SETS_MANUAL`).
- [x] Command queue with a timeout per attempt. No routine polls are needed: the values come from the broadcasts.
- [x] Measured again with thermostat commands ([measurements](doc/measurements.md)): 9 of 9 answered, Thread stable; bt_tx_processor stack and system heap raised.

## Later

- [ ] eQ-3: connect right after the scanner hears the thermostat, if commands start failing. Now about half of the first attempts miss the advertisement or drop at once (HCI 0x3E); the retry has always worked, 7–14 s per command.
- [ ] Own Matter credentials and DAC instead of the test ones; own MCUboot signing key instead of the SDK's debug key.
- [ ] OTA updates over Matter.
- [ ] Encrypted BTHome (bindkey per sensor).
- [ ] Decide on the nRF5340 only if a later measurement runs out of headroom.

## Done

- [x] Step 1: toolchain and the bridge on the nRF52840 DK
- [x] Step 2: commissioned into Apple Home (HomePod as border router)
- [x] Step 3: BTHome sensors with auto-add, remove/ignore, temperature and humidity
- [x] Sensors restore after a reboot with the same endpoints and names in Apple Home
- [x] Battery level of BTHome sensors in Apple Home (Power Source cluster)
- [x] System work queue stack raised to 1536 B
- [x] Step 5, first round: RAM, flash and radio measured with two sensors
- [x] Sensors decided: pvvx firmware with BTHome v2, unencrypted
- [x] Thermostat decided: eQ-3 CC-RT-BLE with eq3-custom-fw
