/*
 * Read-only lookup in the app's settings partition, as stored by nRF Connect SDK v3.4.2
 * (Zephyr settings on NVS, zephyr/subsys/kvss/nvs and zephyr/subsys/settings/src/settings_nvs.c).
 *
 * NVS: the area is split into sectors. Data grows from a sector's start, 8-byte entries (ATEs:
 * id, offset, len, part, crc8) from its end: the last slot is the close ATE (written when the
 * sector is full), the one before it the GC-done ATE, then the data ATEs downwards. The sector
 * being written is the open one that follows a closed one; reading from the sector after it,
 * round to it, sees every entry from oldest to newest, so the last valid entry for an id wins.
 * A length of 0 means deleted. No data CRC (CONFIG_NVS_DATA_CRC is off).
 *
 * Settings: a name is stored under an id from 0x8001 up (NVS_NAMECNT_ID + 1), its value under
 * that id + 0x4000 (NVS_NAME_ID_OFFSET).
 *
 * The status page hostname: Matter registers the Thread extended address (otLinkGetExtendedAddress)
 * as SRP hostname, in uppercase hex. OpenThread keeps it in its network info, settings key
 * "ot/3" (OT_SETTINGS_KEY_NETWORK_INFO), at bytes 20..27 (after role, device mode, RLOC16, key
 * sequence and three frame counters / partition id; settings.hpp, class NetworkInfo).
 *
 * Every entry is CRC-checked, and nothing is shown unless a full, valid record is found. A
 * format change in a future SDK makes the line disappear, not show a wrong address;
 * test/settings_test.c catches it when run on a dump from the new SDK.
 */

#include "enmt_settings.h"

#include <string.h>

#define ATE_SIZE        8
#define NAMECNT_ID      0x8000
#define NAME_ID_OFFSET  0x4000
#define MAX_SECTORS     16
#define OT_NETWORK_INFO "ot/3"
#define EXT_ADDR_OFFSET 20

typedef struct {
  uint16_t id, offset, len;
  uint8_t part, crc8;
} ate_t;

static uint8_t crc8_ccitt(const uint8_t* p, size_t n) {
  uint8_t crc = 0xFF;
  while (n--) {
    crc ^= *p++;
    for (int i = 0; i < 8; i++) {
      crc = (crc & 0x80) ? (uint8_t) ((crc << 1) ^ 0x07) : (uint8_t) (crc << 1);
    }
  }
  return crc;
}

static bool is_erased(const uint8_t* p, size_t n) {
  while (n--) {
    if (*p++ != 0xFF) return false;
  }
  return true;
}

static ate_t read_ate(const uint8_t* p) {
  ate_t a = {(uint16_t) (p[0] | p[1] << 8), (uint16_t) (p[2] | p[3] << 8), (uint16_t) (p[4] | p[5] << 8), p[6], p[7]};
  return a;
}

// Calls fn for every valid data ATE in write order (oldest first).
typedef void (*ate_fn)(const uint8_t* data, const ate_t* ate, void* ctx);

static bool for_each_ate(const uint8_t* area, size_t size, size_t sector_size, ate_fn fn, void* ctx) {
  size_t const sectors = sector_size ? size / sector_size : 0;
  if (sectors < 2 || sectors > MAX_SECTORS || sector_size % ATE_SIZE || sector_size > 0x10000) return false;

  // The write sector: the open sector after a closed one (else the first, as NVS does)
  size_t write = 0;
  for (size_t i = 0; i < sectors; i++) {
    const uint8_t* close = area + i * sector_size + sector_size - ATE_SIZE;
    const uint8_t* next_close = area + ((i + 1) % sectors) * sector_size + sector_size - ATE_SIZE;
    if (!is_erased(close, ATE_SIZE) && is_erased(next_close, ATE_SIZE)) {
      write = (i + 1) % sectors;
      break;
    }
  }

  for (size_t n = 1; n <= sectors; n++) {
    const uint8_t* sec = area + ((write + n) % sectors) * sector_size;
    // From the GC-done slot downwards; stop at the first erased slot
    for (size_t pos = sector_size - 2 * ATE_SIZE; pos >= ATE_SIZE; pos -= ATE_SIZE) {
      const uint8_t* raw = sec + pos;
      if (is_erased(raw, ATE_SIZE)) break;
      ate_t const ate = read_ate(raw);
      if (crc8_ccitt(raw, ATE_SIZE - 1) != ate.crc8 || ate.id == 0xFFFF) continue;
      if ((size_t) ate.offset + ate.len > pos) continue; // data must lie below the ATEs
      fn(sec + ate.offset, &ate, ctx);
    }
  }
  return true;
}

typedef struct {
  const char* name;
  size_t name_len;
  uint16_t name_id; // 0: not found
} find_name_t;

static void match_name(const uint8_t* data, const ate_t* ate, void* ctx) {
  find_name_t* f = ctx;
  if (ate->id <= NAMECNT_ID || ate->id >= NAMECNT_ID + NAME_ID_OFFSET) return;
  if (ate->len == f->name_len && memcmp(data, f->name, f->name_len) == 0) {
    f->name_id = ate->id;
  } else if (ate->id == f->name_id) {
    f->name_id = 0; // that id now holds another name, or was deleted
  }
}

typedef struct {
  uint16_t id;
  const uint8_t* value;
  size_t len;
} find_value_t;

static void match_value(const uint8_t* data, const ate_t* ate, void* ctx) {
  find_value_t* f = ctx;
  if (ate->id == f->id) {
    f->value = ate->len ? data : NULL;
    f->len = ate->len;
  }
}

bool enmt_settings_find(const uint8_t* area, size_t size, size_t sector_size, const char* name,
                        const uint8_t** value, size_t* len) {
  find_name_t fn = {name, strlen(name), 0};
  if (!for_each_ate(area, size, sector_size, match_name, &fn) || !fn.name_id) return false;

  find_value_t fv = {(uint16_t) (fn.name_id + NAME_ID_OFFSET), NULL, 0};
  for_each_ate(area, size, sector_size, match_value, &fv);
  if (!fv.value) return false;
  *value = fv.value;
  *len = fv.len;
  return true;
}

bool enmt_thread_ext_addr(const uint8_t* area, size_t size, size_t sector_size, uint8_t ext_addr[8]) {
  const uint8_t* info;
  size_t len;
  if (!enmt_settings_find(area, size, sector_size, OT_NETWORK_INFO, &info, &len) || len < EXT_ADDR_OFFSET + 8) {
    return false;
  }
  memcpy(ext_addr, info + EXT_ADDR_OFFSET, 8);
  return !is_erased(ext_addr, 8);
}
