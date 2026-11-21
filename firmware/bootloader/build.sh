#!/bin/sh
# Builds the Adafruit nRF52 UF2 bootloader 0.11.0 with the EnMT three-LED pattern, for the
# boards enmt (carrier) and enmt_dk (nRF52840 DK), with the nRF Connect SDK's Zephyr GCC.
# Output: out/<board>_bootloader-<ver>_nosd.hex (MBR + bootloader, for nrfjprog)
#         out/update-<board>_bootloader-<ver>_nosd.uf2 (drop on a running UF2 drive)
#
#   ./build.sh [board ...]     default: enmt enmt_dk
set -e

TAG=0.11.0
VERSION=$TAG-enmt
HERE=$(cd "$(dirname "$0")" && pwd)
SRC=$HERE/_src

. "$HERE/../../scripts/ncs-env.sh" >/dev/null  # not under set -u
PATH=$ZEPHYR_SDK_INSTALL_DIR/gnu/arm-zephyr-eabi/bin:$PATH
set -u

if [ ! -d "$SRC" ]; then
	/usr/bin/git clone -q --depth 1 --branch "$TAG" --recurse-submodules --shallow-submodules \
		https://github.com/adafruit/Adafruit_nRF52_Bootloader.git "$SRC"
fi

# Fresh patch and board files on every build
/usr/bin/git -C "$SRC" checkout -q -- Makefile src/boards/boards.c
/usr/bin/git -C "$SRC" apply "$HERE/boards.patch"
cp "$HERE/enmt_leds.h" "$SRC/src/boards/"
for b in "$HERE"/boards/*/; do
	rm -rf "$SRC/src/boards/$(basename "$b")"
	cp -R "${b%/}" "$SRC/src/boards/"
done

mkdir -p "$HERE/out"
for board in ${@:-enmt enmt_dk}; do
	name=${board}_bootloader-$VERSION
	# _VER3: the Makefile's own version parsing needs GNU sed
	make -C "$SRC" -j8 BOARD="$board" CROSS_COMPILE=arm-zephyr-eabi- PYTHON=python3 \
		GIT_VERSION="$VERSION" _VER3="$(echo $TAG | tr . ' ')" \
		"_build/build-$board/${name}_nosd.hex" "_build/build-$board/update-${name}_nosd.uf2" |
		grep -E 'FLASH:|RAM:|Create|error' || true
	cp "$SRC/_build/build-$board/${name}_nosd.hex" "$SRC/_build/build-$board/update-${name}_nosd.uf2" "$HERE/out/"
done
ls -l "$HERE/out"
