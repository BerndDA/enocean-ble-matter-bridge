#!/usr/bin/env python3
"""Stage an app image in a DK's QSPI flash the way the app's OTA processor will (enmt_ota.h):
header at 0x000000, image at 0x001000. For testing the bootloader's QSPI OTA copy without Matter.

  ./ota-stage.py zephyr.bin -o staged.hex [--version N] [--corrupt]
  nrfjprog --program staged.hex --qspisectorerase --verify    # then reset: the bootloader copies

The hex is at the QSPI's XIP address (0x12000000), as nrfjprog expects for external flash.
--corrupt flips one byte of the image after hashing (the bootloader must refuse it).
"""

import argparse
import hashlib
import struct
import sys

XIP = 0x12000000
HEADER = 0x000000
SLOT = 0x001000
MAGIC = 0x544F4D45  # "EMOT"
APP_START = 0x1000
APP_END = 0xDF000


def ihex(chunks):
    """Intel HEX from [(address, bytes)]."""
    out = []
    upper = None
    for addr, data in chunks:
        for off in range(0, len(data), 16):
            a = addr + off
            if a >> 16 != upper:
                upper = a >> 16
                rec = bytes([2, 0, 0, 4]) + struct.pack(">H", upper)
                out.append(":" + (rec + bytes([-sum(rec) & 0xFF])).hex().upper())
            row = data[off:off + 16]
            rec = bytes([len(row)]) + struct.pack(">H", a & 0xFFFF) + b"\x00" + row
            out.append(":" + (rec + bytes([-sum(rec) & 0xFF])).hex().upper())
    out.append(":00000001FF")
    return "\n".join(out) + "\n"


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("bin", help="app binary for 0x1000 (zephyr.bin of a UF2-layout build)")
    p.add_argument("-o", "--output", required=True)
    p.add_argument("--version", type=int, default=0, help="software version in the header (informational)")
    p.add_argument("--corrupt", action="store_true", help="flip a byte after hashing")
    a = p.parse_args()

    image = bytearray(open(a.bin, "rb").read())
    if not 0 < len(image) <= APP_END - APP_START:
        sys.exit(f"{a.bin}: {len(image)} bytes, the app area holds {APP_END - APP_START}")
    digest = hashlib.sha256(image).digest()
    header = struct.pack("<5I32s", MAGIC, 1, APP_START, len(image), a.version, digest)
    if a.corrupt:
        image[len(image) // 2] ^= 0x01

    open(a.output, "w").write(ihex([(XIP + HEADER, header), (XIP + SLOT, bytes(image))]))
    print(f"{a.output}: {len(image)} bytes, version {a.version}, sha256 {digest.hex()[:16]}…"
          + (" (corrupted)" if a.corrupt else ""))


if __name__ == "__main__":
    main()
