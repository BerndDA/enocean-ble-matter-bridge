# Matter-over-Thread Gateways (BLE and EnOcean)

Firmware and hardware for nRF52840 gateways that bring existing devices into a Matter smart home over Thread. There are two separate apps, built from a shared bridge core:

- **BLE gateway** ([firmware/ble-gateway/](firmware/ble-gateway/)): BLE temperature/humidity sensors (BTHome) and eQ-3 radiator thermostats.
- **EnOcean gateway** ([firmware/enocean-gateway/](firmware/enocean-gateway/)): Eltako and D2-01 actuators through a TCM 310/515 module.

Both are based on the nRF Connect SDK Matter Bridge application (pinned to v3.4.2) and are meant for home use, not certification.

**Documentation is in the [wiki](https://github.com/BerndDA/enocean-ble-matter-bridge/wiki)**:

- [Ready-made firmware](https://github.com/BerndDA/enocean-ble-matter-bridge/wiki/Ready-Made-Firmware) and [commissioning](https://github.com/BerndDA/enocean-ble-matter-bridge/wiki/Commissioning)
- [BLE gateway](https://github.com/BerndDA/enocean-ble-matter-bridge/wiki/BLE-Gateway), [EnOcean gateway](https://github.com/BerndDA/enocean-ble-matter-bridge/wiki/EnOcean-Gateway) and its [commands](https://github.com/BerndDA/enocean-ble-matter-bridge/wiki/EnOcean-Gateway-Commands)
- Hardware: [boards](https://github.com/BerndDA/enocean-ble-matter-bridge/wiki/Boards), [EnMT carrier board](https://github.com/BerndDA/enocean-ble-matter-bridge/wiki/EnMT-Carrier-Board), [EnOcean bridge PCB](https://github.com/BerndDA/enocean-ble-matter-bridge/wiki/EnOcean-Bridge-PCB), [bootloader](https://github.com/BerndDA/enocean-ble-matter-bridge/wiki/Bootloader)
- Development: [toolchain setup](https://github.com/BerndDA/enocean-ble-matter-bridge/wiki/Toolchain-Setup), [building and flashing](https://github.com/BerndDA/enocean-ble-matter-bridge/wiki/Building-and-Flashing), [repository layout](https://github.com/BerndDA/enocean-ble-matter-bridge/wiki/Repository-Layout), [measurements](https://github.com/BerndDA/enocean-ble-matter-bridge/wiki/Measurements)

Quick start on an nRF52840 DK with the SDK installed:

```sh
make flash                         # BLE gateway; APP=enocean-gateway for the EnOcean gateway
make identity                      # the board's Matter setup code
```

`make` lists all targets. Open tasks are in [TODO.md](TODO.md).

The wiki is also a git submodule in [wiki/](wiki/): `git submodule update --init wiki` checks it out for editing next to the code. Commit and push page changes inside `wiki/` (that publishes them), then commit the new `wiki` pointer here; `git submodule update --remote wiki` fetches edits made in the browser.
