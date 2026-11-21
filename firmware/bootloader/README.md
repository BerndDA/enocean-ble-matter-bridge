# UF2 bootloader with the EnMT LED pattern

The Adafruit nRF52 UF2 bootloader 0.11.0 (the same one as tested in `spike/uf2-bootloader-dk`, same flash layout) with its LED code replaced by a pattern for the EnMT carrier's three status LEDs. The built-in LED of the nice!nano stays off.

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

## Build

```sh
./build.sh            # both boards; or ./build.sh enmt_dk
```

It clones the bootloader into `_src/` (ignored), applies `boards.patch`, copies `boards/*` and `enmt_leds.h` into it, and builds with the nRF Connect SDK's `arm-zephyr-eabi-gcc`. No separate ARM toolchain is needed; the Makefile part of the patch handles picolibc in place of newlib-nano. Output in `out/`:

- `<board>_bootloader-0.11.0-enmt_nosd.hex`: MBR + bootloader + settings + UICR, for nrfjprog
- `update-<board>_bootloader-0.11.0-enmt_nosd.uf2`: bootloader update to drop on a running UF2 drive

The LED code is in `enmt_leds.h`. `boards.patch` only adds a third PWM channel and swaps out `led_tick()`/`led_state()` in `boards.c` for boards that define `BOARD_LEDS_ENMT`.

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
