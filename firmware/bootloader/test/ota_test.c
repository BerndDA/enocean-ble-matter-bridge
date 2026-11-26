/*
 * Host test of enmt_ota.c against fake external and internal flash: no header, a good image,
 * bad headers, a bad image, a power cut in the middle of the copy, a failed verify, and an
 * external flash that doesn't answer. Run by ../test.sh.
 */

#include "../enmt_ota.h"

#include <setjmp.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "tinycrypt/sha256.h"

#define APP_START 0x1000u
#define APP_END   0xDF000u
#define PAGE      ENMT_OTA_PAGE

static int failures;

#define CHECK(cond, ...)                              \
  do {                                                \
    if (!(cond)) {                                    \
      printf("FAIL %s:%d: ", __FILE__, __LINE__);     \
      printf(__VA_ARGS__);                            \
      printf("\n");                                   \
      failures++;                                     \
    }                                                 \
  } while (0)

static uint8_t ext[0x100000];   // 1 MB of external flash
static uint8_t intf[APP_END];   // internal flash up to the end of the app area
static uint8_t buf[PAGE] __attribute__((aligned(4)));

static int writes;              // internal pages written
static int power_cut_after;     // > 0: "lose power" (longjmp) when that many pages were written
static jmp_buf power_cut;
static int corrupt_writes;      // write a wrong byte into each page
static int ext_dead;            // external reads fail
static int copying;             // progress(true) seen, not yet progress(false)

static bool ext_read(uint32_t addr, void *b, uint32_t len) {
  if (ext_dead || addr + len > sizeof(ext) || (len & 3)) {
    return false;
  }
  memcpy(b, ext + addr, len);
  return true;
}

static bool ext_erase_sector(uint32_t addr) {
  memset(ext + (addr & ~(PAGE - 1)), 0xff, PAGE);
  return true;
}

static void int_erase_page(uint32_t addr) {
  CHECK(addr >= APP_START && addr + PAGE <= APP_END && !(addr & (PAGE - 1)), "erase 0x%x", addr);
  memset(intf + addr, 0xff, PAGE);
}

static void int_write_page(uint32_t addr, void const *b) {
  CHECK(addr >= APP_START && addr + PAGE <= APP_END, "write 0x%x", addr);
  for (uint32_t i = 0; i < PAGE; i++) {
    CHECK(intf[addr + i] == 0xff, "write to unerased flash at 0x%x", addr + i);
  }
  memcpy(intf + addr, b, PAGE);
  if (corrupt_writes) {
    intf[addr + 100] ^= 0x01;
  }
  if (power_cut_after && ++writes == power_cut_after) {
    longjmp(power_cut, 1);
  } else if (!power_cut_after) {
    writes++;
  }
}

static uint8_t const *int_ptr(uint32_t addr) {
  return intf + addr;
}

static void progress(bool c) {
  copying = c;
}

static enmt_ota_io_t const io = {ext_read, ext_erase_sector, int_erase_page, int_write_page,
                                 int_ptr, progress};

static void reset(void) {
  memset(ext, 0xff, sizeof(ext));
  for (uint32_t i = 0; i < sizeof(intf); i++) {
    intf[i] = (uint8_t) (i * 7 + 3); // the old app
  }
  writes = power_cut_after = corrupt_writes = ext_dead = copying = 0;
}

// Stages an image of size bytes (contents from seed) with a matching header.
static void stage(uint32_t size, uint8_t seed, enmt_ota_header_t *out) {
  enmt_ota_header_t h = {ENMT_OTA_MAGIC, ENMT_OTA_HEADER_VERSION, APP_START, size, 7, {0}};
  for (uint32_t i = 0; i < size; i++) {
    ext[ENMT_OTA_SLOT_ADDR + i] = (uint8_t) (i * 13 + seed);
  }
  // Junk after the image in the slot: must not reach internal flash
  memset(ext + ENMT_OTA_SLOT_ADDR + size, 0x5a, PAGE);
  struct tc_sha256_state_struct s;
  tc_sha256_init(&s);
  tc_sha256_update(&s, ext + ENMT_OTA_SLOT_ADDR, size);
  tc_sha256_final(h.sha256, &s);
  memcpy(ext + ENMT_OTA_HEADER_ADDR, &h, sizeof(h));
  if (out) {
    *out = h;
  }
}

static bool header_erased(void) {
  for (uint32_t i = 0; i < PAGE; i++) {
    if (ext[ENMT_OTA_HEADER_ADDR + i] != 0xff) {
      return false;
    }
  }
  return true;
}

static bool image_in_place(uint32_t size) {
  if (memcmp(intf + APP_START, ext + ENMT_OTA_SLOT_ADDR, size) != 0) {
    return false;
  }
  // Rest of the last page erased, not the slot's junk
  uint32_t const end = APP_START + ((size + PAGE - 1) & ~(PAGE - 1));
  for (uint32_t a = APP_START + size; a < end; a++) {
    if (intf[a] != 0xff) {
      return false;
    }
  }
  return true;
}

static bool old_app_in_place(void) {
  for (uint32_t i = APP_START; i < sizeof(intf); i++) {
    if (intf[i] != (uint8_t) (i * 7 + 3)) {
      return false;
    }
  }
  return true;
}

static enmt_ota_result_t apply(void) {
  return enmt_ota_apply(&io, APP_START, APP_END, buf);
}

static void test_no_header(void) {
  reset();
  CHECK(apply() == ENMT_OTA_NONE, "no header");
  CHECK(old_app_in_place(), "old app touched");
  CHECK(writes == 0, "%d writes", writes);
}

static void test_good_image(uint32_t size) {
  reset();
  stage(size, 1, NULL);
  enmt_ota_result_t const r = apply();
  CHECK(r == ENMT_OTA_APPLIED, "size %u: result %d", size, r);
  CHECK(image_in_place(size), "size %u: image not in place", size);
  CHECK(header_erased(), "size %u: header kept", size);
  CHECK(!copying, "progress not finished");
  // Pages after the image keep the old app
  uint32_t const end = APP_START + ((size + PAGE - 1) & ~(PAGE - 1));
  CHECK(end == APP_END || intf[end] == (uint8_t) (end * 7 + 3), "size %u: page after touched", size);
  // A second boot: nothing left to do
  CHECK(apply() == ENMT_OTA_NONE, "size %u: second boot", size);
}

static void bad_header(char const *what, uint32_t offset, uint32_t value) {
  reset();
  stage(3 * PAGE, 2, NULL);
  memcpy(ext + ENMT_OTA_HEADER_ADDR + offset, &value, 4);
  enmt_ota_result_t const r = apply();
  CHECK(r == ENMT_OTA_BAD_HEADER, "%s: result %d", what, r);
  CHECK(header_erased(), "%s: header kept", what);
  CHECK(old_app_in_place(), "%s: old app touched", what);
}

static void test_bad_image(void) {
  reset();
  stage(5 * PAGE + 100, 3, NULL);
  ext[ENMT_OTA_SLOT_ADDR + 2 * PAGE + 17] ^= 0x80; // one bit flipped after the hash
  enmt_ota_result_t const r = apply();
  CHECK(r == ENMT_OTA_BAD_IMAGE, "result %d", r);
  CHECK(header_erased(), "header kept");
  CHECK(old_app_in_place(), "old app touched");
  CHECK(writes == 0, "%d writes", writes);
}

static void test_power_cut(void) {
  uint32_t const size = 20 * PAGE + 123;
  reset();
  stage(size, 4, NULL);
  power_cut_after = 8;
  if (setjmp(power_cut) == 0) {
    apply();
    CHECK(0, "no power cut");
  }
  CHECK(!header_erased(), "header erased after a power cut");
  // Next boot: finishes the copy, rewriting only what's still missing
  power_cut_after = 0;
  writes = 0;
  enmt_ota_result_t const r = apply();
  CHECK(r == ENMT_OTA_APPLIED, "result %d", r);
  CHECK(image_in_place(size), "image not in place");
  CHECK(header_erased(), "header kept");
  CHECK(writes == 21 - 8, "%d pages rewritten, expected 13", writes); // 8 were complete
}

static void test_verify_failed(void) {
  reset();
  stage(4 * PAGE, 5, NULL);
  corrupt_writes = 1;
  enmt_ota_result_t const r = apply();
  CHECK(r == ENMT_OTA_VERIFY_FAILED, "result %d", r);
  CHECK(!header_erased(), "header erased although the copy is wrong");
  // Next boot with working flash: the copy is repeated and succeeds
  corrupt_writes = 0;
  CHECK(apply() == ENMT_OTA_APPLIED, "retry");
  CHECK(image_in_place(4 * PAGE), "image not in place after retry");
}

static void test_ext_dead(void) {
  reset();
  stage(4 * PAGE, 6, NULL);
  ext_dead = 1;
  CHECK(apply() == ENMT_OTA_IO_ERROR, "dead external flash");
  CHECK(old_app_in_place(), "old app touched");
  ext_dead = 0;
  CHECK(!header_erased(), "header erased");
}

int main(void) {
  test_no_header();
  test_good_image(1);
  test_good_image(PAGE);
  test_good_image(PAGE + 1);
  test_good_image(123457);
  test_good_image(APP_END - APP_START); // the largest image: 888 KB
  bad_header("magic ok, version", offsetof(enmt_ota_header_t, header_version), 2);
  bad_header("load address", offsetof(enmt_ota_header_t, load_addr), 0x2000);
  bad_header("size 0", offsetof(enmt_ota_header_t, size), 0);
  bad_header("size too big", offsetof(enmt_ota_header_t, size), APP_END - APP_START + 1);
  test_bad_image();
  test_power_cut();
  test_verify_failed();
  test_ext_dead();

  if (failures) {
    printf("ota_test: %d failures\n", failures);
    return 1;
  }
  printf("ota_test: ok\n");
  return 0;
}
