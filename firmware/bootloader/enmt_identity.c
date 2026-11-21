/*
 * Matter identity of the gateway firmware, computed by the bootloader from the chip ID.
 *
 * The gateways derive serial number, discriminator and setup code from the chip ID at boot
 * (firmware/common/identity/chip_id_identity.h, CONFIG_GATEWAY_IDENTITY_FROM_CHIP_ID); nothing of
 * it is stored in flash. This file repeats that derivation (as scripts/make-uf2.py does), so the
 * UF2 drive can show the pairing codes even before the app has run (MATTER.TXT, QR.HTM):
 *   h(label)       = SHA-256("blegw-identity-v1:<label>:<chip ID>")
 *   discriminator  = first 2 bytes of h("discriminator"), big endian, & 0xFFF
 *   setup code     = 1 + (first 4 bytes of h("passcode<n>"), big endian) % 99999998,
 *                    n = 0, 1, ... until it isn't one of the codes Matter forbids
 * Vendor ID, product ID and product name come from the app's factory data (0xE9000).
 * The QR payload and manual code follow the Matter core spec 5.1.3 and 5.1.4; BLE discovery,
 * standard commissioning flow, like the codes the factory data generator prints.
 * Changing the derivation in the app means changing it here too: test/identity_test.c checks it.
 */

#include "enmt_identity.h"

#include <string.h>
#include <tinycrypt/sha256.h>

#define FACTORY_DATA_ADDR 0xE9000 // factory_data_partition of the UF2 layout
#define FACTORY_DATA_SIZE 0x1000
#define SERIAL_PREFIX     "BLEGW-"
#define QR_VIEWER_URL     "https://project-chip.github.io/connectedhomeip/qrcode.html?data=MT%3A"

char enmt_matter_txt[ENMT_FILE_MAX + 1];
char enmt_qr_htm[ENMT_QR_HTM_MAX + 1];

//--------------------------------------------------------------------+
// Derivation
//--------------------------------------------------------------------+

static void hash(const char* label, const char* chip_id, uint8_t out[TC_SHA256_DIGEST_SIZE]) {
  static const char prefix[] = "blegw-identity-v1:";
  struct tc_sha256_state_struct s;
  tc_sha256_init(&s);
  tc_sha256_update(&s, (const uint8_t*) prefix, sizeof(prefix) - 1);
  tc_sha256_update(&s, (const uint8_t*) label, strlen(label));
  tc_sha256_update(&s, (const uint8_t*) ":", 1);
  tc_sha256_update(&s, (const uint8_t*) chip_id, strlen(chip_id));
  tc_sha256_final(out, &s);
}

static uint32_t big_endian(const uint8_t* p, size_t n) {
  uint32_t v = 0;
  for (size_t i = 0; i < n; i++) {
    v = (v << 8) | p[i];
  }
  return v;
}

static bool is_forbidden_passcode(uint32_t code) {
  // Matter core spec 5.1.7.1
  static const uint32_t forbidden[] = {0, 11111111, 22222222, 33333333, 44444444, 55555555,
                                       66666666, 77777777, 88888888, 99999999, 12345678, 87654321};
  for (size_t i = 0; i < sizeof(forbidden) / sizeof(forbidden[0]); i++) {
    if (code == forbidden[i]) {
      return true;
    }
  }
  return false;
}

void enmt_identity_derive(const char* chip_id, enmt_identity_t* id) {
  uint8_t h[TC_SHA256_DIGEST_SIZE];

  memset(id, 0, sizeof(*id));
  strncpy(id->chip_id, chip_id, ENMT_CHIP_ID_LEN);

  hash("discriminator", id->chip_id, h);
  id->discriminator = (uint16_t) (big_endian(h, 2) & 0xFFF);

  for (unsigned n = 0; id->passcode == 0 || is_forbidden_passcode(id->passcode); n++) {
    char label[] = "passcode\0\0\0";
    // n stays a single digit in practice; two digits cover any realistic run of forbidden codes
    if (n < 10) {
      label[8] = (char) ('0' + n);
    } else {
      label[8] = (char) ('0' + n / 10);
      label[9] = (char) ('0' + n % 10);
    }
    hash(label, id->chip_id, h);
    id->passcode = 1 + big_endian(h, 4) % 99999998;
  }
}

//--------------------------------------------------------------------+
// Onboarding codes
//--------------------------------------------------------------------+

static void put_digits(char* out, uint32_t value, int digits) {
  for (int i = digits - 1; i >= 0; i--) {
    out[i] = (char) ('0' + value % 10);
    value /= 10;
  }
}

static char verhoeff_check(const char* digits, size_t n) {
  static const uint8_t d[10][10] = {
      {0, 1, 2, 3, 4, 5, 6, 7, 8, 9}, {1, 2, 3, 4, 0, 6, 7, 8, 9, 5}, {2, 3, 4, 0, 1, 7, 8, 9, 5, 6},
      {3, 4, 0, 1, 2, 8, 9, 5, 6, 7}, {4, 0, 1, 2, 3, 9, 5, 6, 7, 8}, {5, 9, 8, 7, 6, 0, 4, 3, 2, 1},
      {6, 5, 9, 8, 7, 1, 0, 4, 3, 2}, {7, 6, 5, 9, 8, 2, 1, 0, 4, 3}, {8, 7, 6, 5, 9, 3, 2, 1, 0, 4},
      {9, 8, 7, 6, 5, 4, 3, 2, 1, 0}};
  static const uint8_t p[8][10] = {
      {0, 1, 2, 3, 4, 5, 6, 7, 8, 9}, {1, 5, 7, 6, 2, 8, 3, 0, 9, 4}, {5, 8, 0, 3, 7, 9, 6, 1, 4, 2},
      {8, 9, 1, 6, 0, 4, 3, 5, 2, 7}, {9, 4, 5, 3, 1, 2, 7, 6, 0, 8}, {4, 2, 8, 6, 5, 7, 3, 9, 0, 1},
      {2, 7, 9, 3, 8, 0, 6, 4, 1, 5}, {7, 0, 4, 6, 9, 1, 3, 2, 5, 8}};
  static const uint8_t inv[10] = {0, 4, 3, 2, 1, 5, 6, 7, 8, 9};

  uint8_t c = 0;
  for (size_t i = 0; i < n; i++) {
    c = d[c][p[(i + 1) % 8][digits[n - 1 - i] - '0']];
  }
  return (char) ('0' + inv[c]);
}

void enmt_manual_code(uint16_t discriminator, uint32_t passcode, char out[ENMT_MANUAL_CODE_LEN + 1]) {
  uint32_t const short_disc = discriminator >> 8; // upper 4 of 12 bits
  uint32_t const chunk1 = short_disc >> 2;        // VID/PID not included
  uint32_t const chunk2 = ((short_disc & 0x3) << 14) | (passcode & 0x3FFF);
  uint32_t const chunk3 = passcode >> 14;

  put_digits(out, chunk1, 1);
  put_digits(out + 1, chunk2, 5);
  put_digits(out + 6, chunk3, 4);
  out[10] = verhoeff_check(out, 10);
  out[11] = '\0';
}

static void put_bits(uint8_t* buf, unsigned* offset, uint32_t value, unsigned bits) {
  for (unsigned i = 0; i < bits; i++, (*offset)++) {
    if (value & (1UL << i)) {
      buf[*offset / 8] |= (uint8_t) (1U << (*offset % 8));
    }
  }
}

void enmt_qr_payload(const enmt_product_t* product, const enmt_identity_t* id, char out[ENMT_QR_PAYLOAD_LEN + 1]) {
  static const char base38[] = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ-.";
  uint8_t bits[11] = {0};
  unsigned offset = 0;

  put_bits(bits, &offset, 0, 3);                   // version
  put_bits(bits, &offset, product->vendor_id, 16);
  put_bits(bits, &offset, product->product_id, 16);
  put_bits(bits, &offset, 0, 2);                   // standard commissioning flow
  put_bits(bits, &offset, 0x02, 8);                // discovery: BLE
  put_bits(bits, &offset, id->discriminator, 12);
  put_bits(bits, &offset, id->passcode, 27);
  put_bits(bits, &offset, 0, 4);                   // padding

  char* o = out;
  memcpy(o, "MT:", 3);
  o += 3;
  // 3 bytes -> 5 characters, the last 2 bytes -> 4 characters, least significant first
  for (size_t i = 0; i < sizeof(bits); i += 3) {
    size_t const n = sizeof(bits) - i < 3 ? sizeof(bits) - i : 3;
    uint32_t value = 0;
    for (size_t j = 0; j < n; j++) {
      value |= (uint32_t) bits[i + j] << (8 * j);
    }
    int const chars = n == 3 ? 5 : n == 2 ? 4 : 2;
    for (int c = 0; c < chars; c++) {
      *o++ = base38[value % 38];
      value /= 38;
    }
  }
  *o = '\0';
}

//--------------------------------------------------------------------+
// Factory data: a CBOR map with text keys
//--------------------------------------------------------------------+

typedef struct {
  const uint8_t* p;
  const uint8_t* end;
} cbor_t;

// Reads an item header: major type and argument (value or length). False on error.
static bool cbor_head(cbor_t* c, uint8_t* major, uint32_t* arg) {
  if (c->p >= c->end) return false;
  uint8_t const b = *c->p++;
  uint8_t const info = b & 0x1F;
  *major = b >> 5;
  if (info < 24) {
    *arg = info;
    return true;
  }
  size_t const n = info == 24 ? 1 : info == 25 ? 2 : info == 26 ? 4 : info == 27 ? 8 : 0;
  if (n == 0 || (size_t) (c->end - c->p) < n) return false; // indefinite lengths not used
  uint64_t v = 0;
  for (size_t i = 0; i < n; i++) {
    v = (v << 8) | *c->p++;
  }
  if (v > 0xFFFFFFFFu && *major != 7 && *major != 0) return false;
  *arg = (uint32_t) v;
  return true;
}

static bool cbor_skip(cbor_t* c, int depth) {
  uint8_t major;
  uint32_t arg;
  if (depth > 4 || !cbor_head(c, &major, &arg)) return false;
  switch (major) {
    case 2:
    case 3:
      if ((uint32_t) (c->end - c->p) < arg) return false;
      c->p += arg;
      return true;
    case 4:
    case 5:
      for (uint32_t i = 0; i < (major == 5 ? 2 * arg : arg); i++) {
        if (!cbor_skip(c, depth + 1)) return false;
      }
      return true;
    case 6:
      return cbor_skip(c, depth + 1);
    default: // 0, 1, 7: the head is all
      return true;
  }
}

bool enmt_factory_data_parse(const uint8_t* data, size_t len, enmt_product_t* product) {
  cbor_t c = {data, data + len};
  uint8_t major;
  uint32_t count;
  bool have_vid = false, have_pid = false;

  memset(product, 0, sizeof(*product));
  if (!cbor_head(&c, &major, &count) || major != 5) return false;

  for (uint32_t i = 0; i < count; i++) {
    uint32_t key_len, arg;
    if (!cbor_head(&c, &major, &key_len) || major != 3 || (uint32_t) (c.end - c.p) < key_len) return false;
    const char* key = (const char*) c.p;
    c.p += key_len;

#define KEY_IS(s) (key_len == sizeof(s) - 1 && memcmp(key, s, key_len) == 0)
    if (KEY_IS("vendor_id") || KEY_IS("product_id")) {
      if (!cbor_head(&c, &major, &arg) || major != 0 || arg > 0xFFFF) return false;
      if (KEY_IS("vendor_id")) {
        product->vendor_id = (uint16_t) arg;
        have_vid = true;
      } else {
        product->product_id = (uint16_t) arg;
        have_pid = true;
      }
    } else if (KEY_IS("product_name")) {
      // the generator writes text values as byte strings
      if (!cbor_head(&c, &major, &arg) || (major != 2 && major != 3) || (uint32_t) (c.end - c.p) < arg) return false;
      size_t const n = arg < sizeof(product->product_name) - 1 ? arg : sizeof(product->product_name) - 1;
      memcpy(product->product_name, c.p, n);
      product->product_name[n] = '\0';
      c.p += arg;
    } else if (!cbor_skip(&c, 0)) {
      return false;
    }
#undef KEY_IS
  }
  return have_vid && have_pid;
}

//--------------------------------------------------------------------+
// Files
//--------------------------------------------------------------------+

typedef struct {
  char* buf;
  size_t len;
  size_t max;
} text_t;

static void add(text_t* t, const char* s) {
  while (*s && t->len < t->max) {
    t->buf[t->len++] = *s++;
  }
  t->buf[t->len] = '\0';
}

static void add_dec(text_t* t, uint32_t v, int min_digits) {
  char s[11];
  int n = 0;
  do {
    s[n++] = (char) ('0' + v % 10);
    v /= 10;
  } while (v || n < min_digits);
  char out[11];
  for (int i = 0; i < n; i++) {
    out[i] = s[n - 1 - i];
  }
  out[n] = '\0';
  add(t, out);
}

static void add_hex(text_t* t, uint32_t v, int digits) {
  char s[9];
  for (int i = digits - 1; i >= 0; i--, v >>= 4) {
    s[i] = "0123456789ABCDEF"[v & 0xF];
  }
  s[digits] = '\0';
  add(t, "0x");
  add(t, s);
}

// 1234-567-8901
static void add_manual_code(text_t* t, const char* code) {
  char s[ENMT_MANUAL_CODE_LEN + 3];
  memcpy(s, code, 4);
  s[4] = '-';
  memcpy(s + 5, code + 4, 3);
  s[8] = '-';
  memcpy(s + 9, code + 7, 4);
  s[13] = '\0';
  add(t, s);
}

void enmt_identity_format(const enmt_identity_t* id, const enmt_product_t* product, char* matter_txt, char* qr_htm) {
  char manual[ENMT_MANUAL_CODE_LEN + 1];
  char qr[ENMT_QR_PAYLOAD_LEN + 1];
  bool const has_name = product && product->product_name[0];

  enmt_manual_code(id->discriminator, id->passcode, manual);
  if (product) {
    enmt_qr_payload(product, id, qr);
  }

  text_t t = {matter_txt, 0, ENMT_FILE_MAX};
  matter_txt[0] = '\0';
  add(&t, "Matter identity, computed from the chip ID\r\n");
  if (has_name) {
    add(&t, "Product: ");
    add(&t, product->product_name);
    add(&t, "\r\n");
  }
  if (product) {
    add(&t, "Vendor ID: ");
    add_hex(&t, product->vendor_id, 4);
    add(&t, ", product ID: ");
    add_hex(&t, product->product_id, 4);
    add(&t, "\r\n");
  }
  add(&t, "Chip ID: ");
  add(&t, id->chip_id);
  add(&t, "\r\nSerial number: " SERIAL_PREFIX);
  add(&t, id->chip_id);
  add(&t, "\r\nDiscriminator: ");
  add_dec(&t, id->discriminator, 1);
  add(&t, " (");
  add_hex(&t, id->discriminator, 3);
  add(&t, ")\r\nSetup code: ");
  add_dec(&t, id->passcode, 8);
  add(&t, "\r\nManual pairing code: ");
  add_manual_code(&t, manual);
  add(&t, "\r\n");
  if (product) {
    add(&t, "QR code: ");
    add(&t, qr);
    add(&t, "\r\nQR code image: " QR_VIEWER_URL);
    add(&t, qr + 3);
    add(&t, "\r\n");
  } else {
    add(&t, "No factory data: flash a gateway for the QR code\r\n");
  }

  // QR.HTM: straight to the QR viewer
  t = (text_t) {qr_htm, 0, ENMT_QR_HTM_MAX};
  qr_htm[0] = '\0';
  if (product) {
    add(&t, "<!doctype html><meta http-equiv=\"refresh\" content=\"0;url=" QR_VIEWER_URL);
    add(&t, qr + 3);
    add(&t, "\">\n");
  } else {
    add(&t, "No factory data: flash a gateway for the QR code\n");
  }
}

//--------------------------------------------------------------------+
// Bootloader
//--------------------------------------------------------------------+

#ifndef ENMT_IDENTITY_HOST_TEST
#include "nrf.h"

void enmt_identity_init(void) {
  char chip_id[ENMT_CHIP_ID_LEN + 1];
  uint32_t const words[2] = {NRF_FICR->DEVICEID[1], NRF_FICR->DEVICEID[0]};
  for (int w = 0; w < 2; w++) {
    for (int i = 0; i < 8; i++) {
      chip_id[w * 8 + i] = "0123456789ABCDEF"[(words[w] >> (28 - 4 * i)) & 0xF];
    }
  }
  chip_id[ENMT_CHIP_ID_LEN] = '\0';

  enmt_identity_t id;
  enmt_product_t product;
  enmt_identity_derive(chip_id, &id);
  bool const has_product = enmt_factory_data_parse((const uint8_t*) FACTORY_DATA_ADDR, FACTORY_DATA_SIZE, &product);
  enmt_identity_format(&id, has_product ? &product : NULL, enmt_matter_txt, enmt_qr_htm);
}
#endif
