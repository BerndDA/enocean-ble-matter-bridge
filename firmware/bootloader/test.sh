#!/bin/sh
# Host test of enmt_identity.c (see test/identity_test.c). Needs the bootloader clone in _src
# (./build.sh once) for tinycrypt's SHA-256.
#   ./test.sh [factory_data.bin]    also prints MATTER.TXT and QR.HTM for that factory data
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
TC=$HERE/_src/lib/tinycrypt/lib
OUT=$HERE/out/identity_test
mkdir -p "$HERE/out"
cc -std=c11 -Wall -Wextra -Werror -DENMT_IDENTITY_HOST_TEST -I"$TC/include" -o "$OUT" \
	"$HERE/test/identity_test.c" "$HERE/enmt_identity.c" "$TC/source/sha256.c" "$TC/source/utils.c"
"$OUT" "$@"
