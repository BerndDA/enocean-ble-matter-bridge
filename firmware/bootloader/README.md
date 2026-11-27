# UF2 bootloader for the EnMT carrier

The Adafruit nRF52 UF2 bootloader 0.11.0 with an LED pattern on the carrier's three status LEDs, the gateway's Matter pairing codes on the UF2 drive, settings backup and cloning (`SETTINGS.UF2`), a bootloader download (`BOOTLOAD.UF2`), a restart into the app (`RESTART.UF2`) and copies that end without an error on the host. Boards `enmt` (carrier), `enmt_dk` (nRF52840 DK as a stand-in) and `promicro` (a bare Pro Micro nRF52840: the pattern on its single LED, no Matter OTA since it has no QSPI flash; only `update-promicro_bootloader-*.uf2` is needed, dropped onto its stock bootloader's drive).

```sh
./build.sh            # all boards into out/; or ./build.sh promicro
./test.sh             # host tests: pairing codes, status page hostname from the settings
```

Everything else (what's on the drive, settings and cloning, bootloader updates, the patch, testing on the DK) is on the wiki page [Bootloader](https://github.com/BerndDA/enocean-ble-matter-bridge/wiki/Bootloader).
