/*
 * Applies an OTA image staged in external flash, see enmt_ota.h.
 *
 * Power loss at any point is safe: the header is erased only after internal flash has been
 * verified against it, so an interrupted copy starts again on the next boot. Pages that already
 * hold the right data aren't erased again, so the repeat only rewrites what's missing.
 */

#include "enmt_ota.h"

#include <string.h>

#include "tinycrypt/sha256.h"

// SHA-256 over len bytes of the slot (external) or of internal flash from addr.
static bool hash_ext(enmt_ota_io_t const *io, uint32_t len, uint8_t *buf, uint8_t digest[32]) {
  struct tc_sha256_state_struct s;
  tc_sha256_init(&s);
  for (uint32_t off = 0; off < len; off += ENMT_OTA_PAGE) {
    if (!io->ext_read(ENMT_OTA_SLOT_ADDR + off, buf, ENMT_OTA_PAGE)) {
      return false;
    }
    uint32_t const n = len - off < ENMT_OTA_PAGE ? len - off : ENMT_OTA_PAGE;
    tc_sha256_update(&s, buf, n);
  }
  tc_sha256_final(digest, &s);
  return true;
}

static void hash_int(enmt_ota_io_t const *io, uint32_t addr, uint32_t len, uint8_t digest[32]) {
  struct tc_sha256_state_struct s;
  tc_sha256_init(&s);
  tc_sha256_update(&s, io->int_ptr(addr), len);
  tc_sha256_final(digest, &s);
}

enmt_ota_result_t enmt_ota_apply(enmt_ota_io_t const *io, uint32_t app_start, uint32_t app_end,
                                 uint8_t *buf) {
  enmt_ota_header_t h;
  uint8_t digest[32];

  if (!io->ext_read(ENMT_OTA_HEADER_ADDR, &h, sizeof(h))) {
    return ENMT_OTA_IO_ERROR;
  }
  if (h.magic != ENMT_OTA_MAGIC) {
    return ENMT_OTA_NONE; // erased (or no flash chip answering)
  }
  if (!enmt_ota_header_ok(&h, app_start, app_end)) {
    io->ext_erase_sector(ENMT_OTA_HEADER_ADDR);
    return ENMT_OTA_BAD_HEADER;
  }

  // The slot must match before internal flash is touched: a bad image leaves the old app running
  if (!hash_ext(io, h.size, buf, digest)) {
    return ENMT_OTA_IO_ERROR;
  }
  if (memcmp(digest, h.sha256, sizeof(digest)) != 0) {
    io->ext_erase_sector(ENMT_OTA_HEADER_ADDR);
    return ENMT_OTA_BAD_IMAGE;
  }

  io->progress(true);
  for (uint32_t off = 0; off < h.size; off += ENMT_OTA_PAGE) {
    if (!io->ext_read(ENMT_OTA_SLOT_ADDR + off, buf, ENMT_OTA_PAGE)) {
      io->progress(false);
      return ENMT_OTA_IO_ERROR;
    }
    if (h.size - off < ENMT_OTA_PAGE) {
      // Last, partial page: erased flash after the image, not whatever the slot holds there
      memset(buf + (h.size - off), 0xff, ENMT_OTA_PAGE - (h.size - off));
    }
    uint32_t const dst = app_start + off;
    if (memcmp(io->int_ptr(dst), buf, ENMT_OTA_PAGE) != 0) {
      io->int_erase_page(dst);
      io->int_write_page(dst, buf);
    }
  }
  io->progress(false);

  hash_int(io, app_start, h.size, digest);
  if (memcmp(digest, h.sha256, sizeof(digest)) != 0) {
    return ENMT_OTA_VERIFY_FAILED;
  }
  return io->ext_erase_sector(ENMT_OTA_HEADER_ADDR) ? ENMT_OTA_APPLIED : ENMT_OTA_IO_ERROR;
}
