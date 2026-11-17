#!/bin/sh
# Fetch the attestation roots (PAA) and CD signing certs from connectedhomeip
# into ./certs: the production set for certified devices plus the CSA test set
# for development devices (test DACs, vendor 0xFFF1, e.g. DIY ESP32 builds).
set -eu
cd "$(dirname "$0")"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
git clone -q --depth 1 --filter=blob:none --sparse \
    https://github.com/project-chip/connectedhomeip "$tmp/chip"
git -C "$tmp/chip" sparse-checkout set credentials/production credentials/test
rm -rf certs
mkdir -p certs/paa certs/cd
cp "$tmp"/chip/credentials/production/paa-root-certs/*.der certs/paa/
cp "$tmp"/chip/credentials/production/cd-certs/*.der certs/cd/
t="$tmp/chip/credentials/test"
cp "$t/attestation/Chip-Test-PAA-FFF1-Cert.der" "$t/attestation/Chip-Test-PAA-NoVID-Cert.der" certs/paa/
openssl x509 -in "$t/certification-declaration/Chip-Test-CD-Signing-Cert.pem" \
    -outform der -out certs/cd/Chip-Test-CD-Signing-Cert.der
echo "certs: $(ls certs/paa | wc -l | tr -d ' ') PAA, $(ls certs/cd | wc -l | tr -d ' ') CD"
