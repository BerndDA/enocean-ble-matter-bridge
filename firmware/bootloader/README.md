# UF2 bootloader for the EnMT carrier

The Adafruit nRF52 UF2 bootloader 0.11.0 (the same one as tested in `spike/uf2-bootloader-dk`, same flash layout) with two additions:

- an LED pattern on the EnMT carrier's three status LEDs, in place of its own LED code; the built-in LED of the nice!nano stays off
- the gateway's Matter pairing codes on the UF2 drive (`MATTER.TXT`, `QR.HTM`)
- the gateway's settings as `SETTINGS.UF2`, to back up, restore or clone onto another board
- the installed bootloader as `BOOTLOAD.UF2`, to install it on another board

## LEDs

| Bootloader state | LEDs |
|---|---|
| no USB host (charger, before enumeration) | red breathes, 2 s |
| UF2 drive ready | a light sweeps green → yellow → red → yellow → …, 1.6 s per pass |
| writing a `.uf2` | all three pulse together, 0.4 s; then the app starts |

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

## Settings backup, restore and clone

`SETTINGS.UF2` holds the app's settings partition (0xEA000–0xF2000, 32 KB, `storage_partition` in the UF2 overlays), read from flash like `CURRENT.UF2`, which ends where it begins: Matter fabrics and keys, the Thread network, the bridged devices. Copy it off the drive as a backup.

Copying a saved `SETTINGS.UF2` onto the drive (any name, or over the one there) writes it back; then the bootloader starts the app, as after a firmware copy. The bootloader takes settings blocks only from a file shaped like its own `SETTINGS.UF2` (128 blocks, block number = position in the settings area), so a firmware `.uf2` can't overwrite the settings; blocks of any other shape are ignored.

Onto another board, this clones the gateway: same Matter node in the same fabrics (Apple Home sees the old accessory), same Thread network, same bridged devices. Keep in mind:

- Only one of the two may run: turn the old board off or give it empty settings.
- Serial number and setup code still come from the new board's chip ID. Existing pairings don't use them; a new controller pairs with the new board's code (`MATTER.TXT`).
- Settings belong to one app: clone a BLE gateway onto a BLE gateway, an EnOcean gateway onto an EnOcean gateway.
- EnOcean: the actuators are taught in to the TCM module's sender IDs, which the module stores itself. Move the TCM to the new board, or teach the actuators in again.

A file of 128 blocks with all bytes 0xFF (made from a downloaded `SETTINGS.UF2`) erases the settings: the app starts like after a factory reset.

The file contains the Thread network key and the Matter operational keys unencrypted (the app's secure storage derives its key from the item ID, not from the chip), so keep it like a password. Anyone who can double-press RESET on a board can copy it, as they could read the flash over SWD, and can write settings the same way.

Tested on the DK: download, upload of empty settings (the app started without bridged devices), a file with a wrong block count (ignored), and restoring the download (all bridged devices back). Don't read the chip over the J-Link (`nrfjprog --readcode`, `--readregs`) while the drive is mounted: that halts the CPU, macOS then drops the USB device and the next copy fails.

## Bootloader download and updates

`BOOTLOAD.UF2` is the installed bootloader as a bootloader update, the same as `update-<board>_bootloader-*_nosd.uf2` from the build: the bootloader's image (its end comes from its own linker symbols), its config block and the UICR block with the bootloader address. Copied onto another board's drive, it installs this bootloader there and keeps app, factory data and settings. A board takes it only if its own bootloader has the same USB IDs (an `enmt_dk` bootloader doesn't go onto a carrier).

How a bootloader update writes: a bootloader can't overwrite itself while it runs, so the new bootloader goes to a 40 KB staging area in the app space first. Once complete, the Nordic MBR copies it into place; the MBR records the job in its params page (0xFE000) and finishes it after a power loss. The stock bootloader stages at 0xE0000–0xEA000, which puts the config block at 0xE9800, inside the gateways' factory data page. This one stages at 0xDF000–0xE9000 (`BOARD_BL_STAGING_ADDR` in `board.mk`) and leaves the factory data page alone. Hence the gateways' UF2 layout (`boards/promicro_nrf52840_nrf52840_uf2.overlay` of both apps):

- the app partition ends at 0xDF000 (888 KB); a larger app fails to link instead of losing its end at the next bootloader update
- the factory data at 0xE9000 may use only its first 2 KB, for boards that still have the stock bootloader
- `scripts/make-uf2.py` refuses a `.uf2` with data in 0xDF000–0xE9000 or 0xE9800–0xEA000

The MBR copies the whole staging area, so after an update the unused end of the bootloader region holds whatever was at the end of the staging area (with the stock bootloader: a copy of the factory data page). That's harmless, and the reason why `BOOTLOAD.UF2` takes the image end from the linker instead of looking for the last non-empty flash.

Tested on the DK: an update to a bootloader with another version string and back, each verified against its build; the factory data page stayed byte for byte the same.

## Build

```sh
./build.sh            # both boards; or ./build.sh enmt_dk
```

It clones the bootloader into `_src/` (ignored), applies `boards.patch`, copies `boards/*`, `enmt_leds.h` and `enmt_identity.*` into it, and builds with the nRF Connect SDK's `arm-zephyr-eabi-gcc`. No separate ARM toolchain is needed; the Makefile part of the patch handles picolibc in place of newlib-nano. Output in `out/`:

- `<board>_bootloader-0.11.0-enmt_nosd.hex`: MBR + bootloader + settings + UICR, for nrfjprog
- `update-<board>_bootloader-0.11.0-enmt_nosd.uf2`: bootloader update to drop on a running UF2 drive

`boards.patch` changes, each for boards that switch it on in `board.mk` or `board.h`:

- `boards.c`: a third PWM channel, and `led_tick()`/`led_state()` from `enmt_leds.h` (`BOARD_LEDS_ENMT`)
- `ghostfat.c`: `MATTER.TXT` and `QR.HTM` instead of `INDEX.HTM` (`BOARD_IDENTITY_FILES`; `board.mk` also adds `enmt_identity.c` and tinycrypt's SHA-256), `SETTINGS.UF2` (`BOARD_SETTINGS_ADDR`, `BOARD_SETTINGS_SIZE`), and `BOOTLOAD.UF2` (`BOARD_BOOTLOADER_FILE`)
- `main.c`, `bootloader.c`, Makefile: no BLE OTA DFU (`NO_BLE_OTA = 1`). It needs a SoftDevice, which the gateways' layout doesn't have. Serial DFU over the bootloader's USB serial port (`adafruit-nrfutil`) stays as a fallback to the UF2 drive.
- Makefile: the toolchain

The bootloader uses about 31 of its 38 KB.

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
