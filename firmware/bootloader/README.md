# UF2 bootloader for the EnMT carrier

The Adafruit nRF52 UF2 bootloader 0.11.0 (the same one as tested in `spike/uf2-bootloader-dk`, same flash layout) with two additions:

- an LED pattern on the EnMT carrier's three status LEDs, in place of its own LED code; the built-in LED of the nice!nano stays off
- the gateway's Matter pairing codes on the UF2 drive (`MATTER.TXT`, `QR.HTM`)
- the gateway's settings as a download (`SETTINGS.UF2`)

## LEDs

| Bootloader state | LEDs |
|---|---|
| no USB host (charger, before enumeration) | red breathes, 2 s |
| UF2 drive ready | a light sweeps green → yellow → red → yellow → …, 1.6 s per pass |
| writing a `.uf2` | all three pulse together, 0.4 s; then the app starts |
| BLE DFU connected (only with a SoftDevice) | green breathes |

All of them fade, so they can't be mistaken for the app, which only switches its LEDs on and off.

Two boards:

- `enmt`: the carrier (green P1.13, yellow P1.15, red P1.11, all active low). Holding FUNC (P1.06) while resetting also opens the UF2 drive. USB IDs of the nice!nano, so a stock nice!nano bootloader accepts `update-enmt_bootloader-*_nosd.uf2`.
- `enmt_dk`: the nRF52840 DK as a stand-in, on LED1 (green), LED2 (yellow) and LED3 (red), like `firmware/common/boards/nrf52840dk_status_leds.dtsi`. Button 1 held at reset opens the UF2 drive.

## Pairing codes on the drive

The gateways derive their serial number, discriminator and setup code from the chip ID at boot (`firmware/common/identity/`); nothing of it is stored in flash. The bootloader repeats that derivation (`enmt_identity.c`) and reads vendor ID, product ID and product name from the app's factory data at 0xE9000, so the drive shows:

- `MATTER.TXT`: product, vendor and product ID, chip ID, serial number, discriminator, setup code, manual pairing code, QR payload and a link that shows the QR code
- `QR.HTM`: opens the QR code straight away (in place of `INDEX.HTM`, which led to the board's web page)

The codes match `make identity` and are valid for every gateway build (they all use `CONFIG_GATEWAY_IDENTITY_FROM_CHIP_ID`). Without factory data, e.g. on an erased chip, there is no QR code. Both open the Matter project's QR viewer on github.io and sends it the payload.

If the derivation in the app changes, `enmt_identity.c` has to change with it. `./test.sh` checks it on the Mac against the codes the factory data generator printed for three boards, and with a `factory_data.bin` as argument it also prints both files:

```sh
./test.sh ../enocean-gateway/build-enmt/matter_factory_data/zephyr/factory_data.bin
```

## Settings download

`SETTINGS.UF2` holds the app's settings partition (0xEA000–0xF2000, 32 KB, `storage_partition` in the UF2 overlays), read from flash like `CURRENT.UF2`, which ends where it begins: Matter fabrics and keys, the Thread network, the bridged devices. Copy it off the drive as a backup.

It contains the Thread network key and the Matter operational keys unencrypted (the app's secure storage derives its key from the item ID, not from the chip), so keep it like a password. Anyone who can double-press RESET on a board can copy it, as they could read the flash over SWD.

Copying it back onto a drive does nothing yet: the bootloader still writes only 0x1000–0xEA000 and ignores its blocks.

## Build

```sh
./build.sh            # both boards; or ./build.sh enmt_dk
```

It clones the bootloader into `_src/` (ignored), applies `boards.patch`, copies `boards/*`, `enmt_leds.h` and `enmt_identity.*` into it, and builds with the nRF Connect SDK's `arm-zephyr-eabi-gcc`. No separate ARM toolchain is needed; the Makefile part of the patch handles picolibc in place of newlib-nano. Output in `out/`:

- `<board>_bootloader-0.11.0-enmt_nosd.hex`: MBR + bootloader + settings + UICR, for nrfjprog
- `update-<board>_bootloader-0.11.0-enmt_nosd.uf2`: bootloader update to drop on a running UF2 drive

`boards.patch` changes three files: `boards.c` gets a third PWM channel and takes `led_tick()`/`led_state()` from `enmt_leds.h` for boards that define `BOARD_LEDS_ENMT`; `ghostfat.c` serves `MATTER.TXT` and `QR.HTM` instead of `INDEX.HTM` for boards that set `BOARD_IDENTITY_FILES` (in their `board.mk`, which also adds `enmt_identity.c` and tinycrypt's SHA-256), and `SETTINGS.UF2` for boards that set `BOARD_SETTINGS_ADDR` and `BOARD_SETTINGS_SIZE`; the Makefile handles the toolchain. The bootloader uses about 35 of its 38 KB.

## Test on the DK

Connect J2 (debug) and J3 (nRF USB, long edge), and turn the power switch on.

```sh
source ../../scripts/ncs-env.sh
nrfjprog --eraseall          # also wipes the app, factory data and Matter settings
nrfjprog --program out/enmt_dk_bootloader-0.11.0-enmt_nosd.hex --verify --reset
```

With no app on the chip, the bootloader stays in UF2 mode: the `ENMTBOOT` drive mounts and the sweep runs. Unplugging J3 should switch to the breathing red LED, and plugging it back in should bring the sweep back. Then flash an app from the repo root:

```sh
make flash BOARD=promicro-uf2      # or BOARD=enmt for the gateway with the carrier's LEDs
```

During the copy all three LEDs pulse together, then the app starts. Back into the bootloader: double-press RESET, hold Button 1 while pressing RESET, or `nrfjprog --memwr 0x4000051C --val 0x57 && nrfjprog --reset`.

On a DK that already runs a UF2 bootloader with the DK's IDs (stock `pca10056` or `enmt_dk`), `update-enmt_dk_bootloader-0.11.0-enmt_nosd.uf2` can also be copied to the drive instead of using nrfjprog; it keeps the app.

Note: an app built for `BOARD=enmt` drives P1.13/P1.15/P1.11, which aren't the DK's LEDs, so on the DK only the bootloader shows the pattern.
