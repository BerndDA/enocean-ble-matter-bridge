#!/bin/sh
# Host tests of the drive's MATTER.TXT/QR.HTM: test/identity_test.c (pairing codes, factory data)
# test/settings_test.c (status page hostname from the settings) and test/ota_test.c (staged OTA
# image copy, enmt_ota.c). Needs the bootloader clone in
# _src (./build.sh once) for tinycrypt's SHA-256.
#   ./test.sh [factory_data.bin] [SETTINGS.UF2]
#     factory_data.bin: also print MATTER.TXT and QR.HTM for that factory data
#     SETTINGS.UF2:     also print the status page hostname from a gateway's settings download
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
TC=$HERE/_src/lib/tinycrypt/lib
OUT=$HERE/out
mkdir -p "$OUT"

FACTORY=
SETTINGS=
for f in "$@"; do
	case "$f" in
	*.uf2 | *.UF2) SETTINGS=$f ;;
	*) FACTORY=$f ;;
	esac
done

CFLAGS="-std=c11 -Wall -Wextra -Werror -DENMT_IDENTITY_HOST_TEST"
cc $CFLAGS -I"$TC/include" -o "$OUT/identity_test" \
	"$HERE/test/identity_test.c" "$HERE/enmt_identity.c" "$TC/source/sha256.c" "$TC/source/utils.c"
cc $CFLAGS -o "$OUT/settings_test" "$HERE/test/settings_test.c" "$HERE/enmt_settings.c"
cc $CFLAGS -I"$TC/include" -o "$OUT/ota_test" \
	"$HERE/test/ota_test.c" "$HERE/enmt_ota.c" "$TC/source/sha256.c" "$TC/source/utils.c"

"$OUT/identity_test" $FACTORY
"$OUT/settings_test" $SETTINGS
"$OUT/ota_test"
