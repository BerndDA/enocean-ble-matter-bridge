# UF2 bootloader for the EnMT carrier

The Adafruit nRF52 UF2 bootloader 0.11.0 with an LED pattern on the carrier's three status LEDs, the gateway's Matter pairing codes on the UF2 drive, settings backup and cloning (`SETTINGS.UF2`), a bootloader download (`BOOTLOAD.UF2`), a restart into the app (`RESTART.UF2`) and copies that end without an error on the host. Boards `enmt` (carrier) and `enmt_dk` (nRF52840 DK as a stand-in).

```sh
./build.sh            # both boards into out/; or ./build.sh enmt_dk
./test.sh             # host tests: pairing codes, status page hostname from the settings
```

Everything else (what's on the drive, settings and cloning, bootloader updates, the patch, testing on the DK) is on the wiki page [Bootloader](https://github.com/BerndDA/enocean-ble-matter-bridge/wiki/Bootloader).
