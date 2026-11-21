/*
 * Host test of enmt_identity.c: derivation, manual code and QR payload against codes printed by
 * the Matter factory data generator (make identity) for three boards, the factory data parser,
 * and the file sizes. Run by ../test.sh; an optional argument is a factory_data.bin to parse.
 */

#include "../enmt_identity.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int failures;

#define CHECK(cond, ...)               \
  do {                                 \
    if (!(cond)) {                     \
      printf("FAIL %s:%d: ", __FILE__, __LINE__); \
      printf(__VA_ARGS__);             \
      printf("\n");                    \
      failures++;                      \
    }                                  \
  } while (0)

static const struct {
  const char* chip_id;
  uint16_t product_id;
  uint16_t discriminator;
  uint32_t passcode;
  const char* manual;
  const char* qr;
} boards[] = {
    {"9E749BD508DCE477", 0x8002, 834, 51096418, "06025831180", "MT:06PS0KQS02IZNR21310"},
    {"032E94EDF02406E9", 0x8003, 1435, 1405427, "12917100851", "MT:29801S0.03LB7674100"},
    {"54932B32846202D7", 0x8002, 516, 51758911, "03462331593", "MT:06PS0-C714827I4L310"},
};

int main(int argc, char** argv) {
  for (size_t i = 0; i < sizeof(boards) / sizeof(boards[0]); i++) {
    enmt_identity_t id;
    enmt_product_t product = {.vendor_id = 0xFFF1, .product_id = boards[i].product_id};
    char manual[ENMT_MANUAL_CODE_LEN + 1], qr[ENMT_QR_PAYLOAD_LEN + 1];

    enmt_identity_derive(boards[i].chip_id, &id);
    CHECK(id.discriminator == boards[i].discriminator, "%s discriminator %u", boards[i].chip_id, id.discriminator);
    CHECK(id.passcode == boards[i].passcode, "%s passcode %u", boards[i].chip_id, id.passcode);
    enmt_manual_code(id.discriminator, id.passcode, manual);
    CHECK(strcmp(manual, boards[i].manual) == 0, "%s manual code %s", boards[i].chip_id, manual);
    enmt_qr_payload(&product, &id, qr);
    CHECK(strcmp(qr, boards[i].qr) == 0, "%s QR %s", boards[i].chip_id, qr);
  }

  // A CBOR map like the generator's: other keys of every type before and between ours
  static const uint8_t cbor[] = {
      0xA6,                                                          // map(6)
      0x67, 'v', 'e', 'r', 's', 'i', 'o', 'n', 0x01,                 // "version": 1
      0x62, 's', 'n', 0x43, 'a', 'b', 'c',                           // "sn": h'616263'
      0x69, 'v', 'e', 'n', 'd', 'o', 'r', '_', 'i', 'd', 0x19, 0xFF, 0xF1,
      0x63, 'u', 's', 'r', 0xA1, 0x61, 'k', 0x82, 0x01, 0x20,         // "usr": {"k": [1, -1]}
      0x6A, 'p', 'r', 'o', 'd', 'u', 'c', 't', '_', 'i', 'd', 0x19, 0x80, 0x03,
      0x6C, 'p', 'r', 'o', 'd', 'u', 'c', 't', '_', 'n', 'a', 'm', 'e', 0x43, 'G', '<', 'W'};
  enmt_product_t p;
  CHECK(enmt_factory_data_parse(cbor, sizeof(cbor), &p), "parse");
  CHECK(p.vendor_id == 0xFFF1 && p.product_id == 0x8003, "ids %04X %04X", p.vendor_id, p.product_id);
  CHECK(strcmp(p.product_name, "G<W") == 0, "name %s", p.product_name);
  CHECK(!enmt_factory_data_parse(cbor, sizeof(cbor) - 20, &p), "truncated data accepted");

  uint8_t erased[64];
  memset(erased, 0xFF, sizeof(erased));
  CHECK(!enmt_factory_data_parse(erased, sizeof(erased), &p), "erased flash accepted");

  // Files: the longest product name must fit without truncation
  enmt_identity_t id;
  char txt[ENMT_FILE_MAX + 1], htm[ENMT_QR_HTM_MAX + 1];
  enmt_product_t longest = {.vendor_id = 0xFFF1, .product_id = 0x8003};
  memset(longest.product_name, '&', sizeof(longest.product_name) - 1);
  enmt_identity_derive(boards[1].chip_id, &id);
  static const uint8_t ext_addr[8] = {0x1A, 0x2B, 0x3C, 0x4D, 0x5E, 0x6F, 0x70, 0x81};
  enmt_identity_format(&id, &longest, ext_addr, txt, htm);
  CHECK(strlen(txt) < ENMT_FILE_MAX && strstr(txt, "Status page: http://1A2B3C4D5E6F7081.local/\r\n"),
        "MATTER.TXT truncated or wrong (%zu)", strlen(txt));
  CHECK(strlen(htm) < ENMT_QR_HTM_MAX && strstr(htm, "MT%3A29801S0.03LB7674100\">"), "QR.HTM truncated (%zu)", strlen(htm));
  enmt_identity_format(&id, NULL, NULL, txt, htm);
  CHECK(strstr(txt, "No factory data") && !strstr(htm, "http") && strstr(txt, "not on a Thread network"),
        "without factory data and Thread");

  // A real factory_data.bin: print both files as the drive would show them
  if (argc > 1) {
    FILE* f = fopen(argv[1], "rb");
    static uint8_t data[4096];
    size_t const n = f ? fread(data, 1, sizeof(data), f) : 0;
    if (f) fclose(f);
    CHECK(enmt_factory_data_parse(data, n, &p), "parse %s", argv[1]);
    enmt_identity_format(&id, &p, NULL, txt, htm);
    printf("--- MATTER.TXT (%zu bytes)\n%s--- QR.HTM (%zu bytes)\n%s", strlen(txt), txt, strlen(htm), htm);
  }

  printf(failures ? "%d failures\n" : "identity_test: all passed\n", failures);
  return failures ? 1 : 0;
}
