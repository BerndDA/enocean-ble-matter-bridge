/*
 * OTA image staged in external flash (Matter OTA, OTA_PLAN.md): the app writes the new image to
 * the external flash's slot and then the header; the bootloader copies the slot into internal
 * flash on the next boot and erases the header once the copy is verified.
 *
 * External flash layout (the same on every board):
 *   0x000000  header (one 4 KB erase sector)
 *   0x001000  slot: raw app binary for load_addr
 *
 * Hardware-independent part, compiled into the bootloader (board BOARD_QSPI_OTA, glue in
 * enmt_qspi_ota.c) and into the host test (test/ota_test.c) against fake flash.
 */

#ifndef ENMT_OTA_H
#define ENMT_OTA_H

#include <stdbool.h>
#include <stdint.h>

#define ENMT_OTA_MAGIC          0x544F4D45u // "EMOT" little endian
#define ENMT_OTA_HEADER_VERSION 1u
#define ENMT_OTA_HEADER_ADDR    0x000000u   // in external flash
#define ENMT_OTA_SLOT_ADDR      0x001000u   // in external flash
#define ENMT_OTA_PAGE           4096u       // internal flash page = external erase sector

typedef struct {
  uint32_t magic;          // ENMT_OTA_MAGIC
  uint32_t header_version; // ENMT_OTA_HEADER_VERSION
  uint32_t load_addr;      // internal flash address of the image (the app start, 0x1000)
  uint32_t size;           // image bytes in the slot
  uint32_t sw_version;     // Matter software version of the image (informational)
  uint8_t sha256[32];      // over the size bytes in the slot
} enmt_ota_header_t;

// Flash access for enmt_ota_apply(). Addresses: ext_* in external flash, int_* in internal flash.
// All buffers are 4-byte aligned, lengths multiples of 4.
typedef struct {
  bool (*ext_read)(uint32_t addr, void *buf, uint32_t len);
  bool (*ext_erase_sector)(uint32_t addr);      // 4 KB
  void (*int_erase_page)(uint32_t addr);        // 4 KB
  void (*int_write_page)(uint32_t addr, void const *buf); // 4 KB, page erased before
  uint8_t const *(*int_ptr)(uint32_t addr);     // internal flash is memory-mapped
  void (*progress)(bool copying);               // true once copying starts, false when done
} enmt_ota_io_t;

typedef enum {
  ENMT_OTA_NONE = 0,      // no header: nothing to do
  ENMT_OTA_BAD_HEADER,    // header present but not valid for this board: erased
  ENMT_OTA_BAD_IMAGE,     // slot hash differs from the header: erased, app untouched
  ENMT_OTA_APPLIED,       // copied and verified, header erased
  ENMT_OTA_VERIFY_FAILED, // copied but internal flash differs: header kept, retried next boot
  ENMT_OTA_IO_ERROR,      // external flash didn't answer: header kept
} enmt_ota_result_t;

// Header valid for an app area [load_addr, app_end)? load_addr must be app_start.
bool enmt_ota_header_ok(enmt_ota_header_t const *h, uint32_t app_start, uint32_t app_end);

// Applies a staged image, if any. buf: 4 KB, 4-byte aligned scratch buffer.
enmt_ota_result_t enmt_ota_apply(enmt_ota_io_t const *io, uint32_t app_start, uint32_t app_end,
                                 uint8_t *buf);

#endif
