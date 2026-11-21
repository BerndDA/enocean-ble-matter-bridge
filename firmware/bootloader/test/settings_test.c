/*
 * Host test of enmt_settings.c on settings images written like Zephyr NVS does (data from a
 * sector's start, ATEs from its end, close ATE when full, GC-done ATE in a new sector).
 * Run by ../test.sh; an optional argument is a SETTINGS.UF2 from a gateway's drive, whose
 * status page hostname is printed (compare with `make hosts`).
 */

#include "../enmt_settings.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define SECTOR  4096
#define SECTORS 8
#define ATE     8

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

static uint8_t area[SECTOR * SECTORS];

typedef struct {
  int sector;
  size_t data_wra; // offset in sector
  size_t ate_wra;  // offset in sector of the next ATE
} nvs_t;

static uint8_t crc8(const uint8_t* p, size_t n) {
  uint8_t crc = 0xFF;
  while (n--) {
    crc ^= *p++;
    for (int i = 0; i < 8; i++) crc = (crc & 0x80) ? (uint8_t) ((crc << 1) ^ 0x07) : (uint8_t) (crc << 1);
  }
  return crc;
}

static void put_ate(uint8_t* p, uint16_t id, uint16_t offset, uint16_t len) {
  p[0] = id & 0xFF, p[1] = id >> 8, p[2] = offset & 0xFF, p[3] = offset >> 8, p[4] = len & 0xFF, p[5] = len >> 8;
  p[6] = 0xFF;
  p[7] = crc8(p, 7);
}

static void nvs_open(nvs_t* fs, int sector) {
  fs->sector = sector;
  fs->data_wra = 0;
  put_ate(area + sector * SECTOR + SECTOR - 2 * ATE, 0xFFFF, 0, 0); // GC done
  fs->ate_wra = SECTOR - 3 * ATE;
}

static void nvs_init(int first_sector, nvs_t* fs) {
  memset(area, 0xFF, sizeof(area));
  nvs_open(fs, first_sector);
}

static uint8_t* nvs_write(nvs_t* fs, uint16_t id, const void* data, size_t len) {
  size_t const aligned = (len + 3) & ~3u;
  if (fs->data_wra + aligned + ATE > fs->ate_wra) { // full: close, go to the next sector
    put_ate(area + fs->sector * SECTOR + SECTOR - ATE, 0xFFFF, (uint16_t) (fs->ate_wra + ATE), 0);
    nvs_open(fs, (fs->sector + 1) % SECTORS);
  }
  uint8_t* sec = area + fs->sector * SECTOR;
  memcpy(sec + fs->data_wra, data, len);
  uint8_t* ate = sec + fs->ate_wra;
  put_ate(ate, id, (uint16_t) fs->data_wra, (uint16_t) len);
  fs->data_wra += aligned;
  fs->ate_wra -= ATE;
  return ate;
}

static void settings_save(nvs_t* fs, uint16_t name_id, const char* name, const void* value, size_t len) {
  nvs_write(fs, name_id, name, strlen(name));
  nvs_write(fs, name_id + 0x4000, value, len);
}

static void network_info(uint8_t info[38], uint8_t first) {
  memset(info, 0, 38);
  for (int i = 0; i < 8; i++) info[20 + i] = (uint8_t) (first + i);
}

static int find_ext(uint8_t ext[8]) {
  return enmt_thread_ext_addr(area, sizeof(area), SECTOR, ext);
}

int main(int argc, char** argv) {
  nvs_t fs;
  uint8_t info[38], ext[8];
  char filler[200];
  memset(filler, 'x', sizeof(filler));

  // Empty area
  nvs_init(0, &fs);
  CHECK(!find_ext(ext), "found in an empty area");

  // One network info among other keys
  nvs_init(0, &fs);
  settings_save(&fs, 0x8001, "mt/g/fidx", "\x01", 1);
  network_info(info, 0x10);
  settings_save(&fs, 0x8002, "ot/3", info, sizeof(info));
  settings_save(&fs, 0x8003, "ot/1", filler, 100);
  CHECK(find_ext(ext) && ext[0] == 0x10 && ext[7] == 0x17, "single record");

  // Updated many times, across several sectors and round from sector 7 to 0: the newest wins
  nvs_init(6, &fs);
  for (int i = 0; i < 60; i++) {
    network_info(info, (uint8_t) i);
    nvs_write(&fs, 0x4000 + 0x8005, info, sizeof(info));
    nvs_write(&fs, 0x9000, filler, sizeof(filler)); // other traffic
  }
  nvs_write(&fs, 0x8005, "ot/3", 4); // the name, written after its values (ids are what matters)
  CHECK(fs.sector != 6, "test setup: no sector change (%d)", fs.sector);
  CHECK(find_ext(ext) && ext[0] == 59, "newest across sectors: got %d", ext[0]);

  // A corrupt newest ATE: the previous value counts
  nvs_init(0, &fs);
  network_info(info, 0x20);
  settings_save(&fs, 0x8002, "ot/3", info, sizeof(info));
  network_info(info, 0x30);
  uint8_t* ate = nvs_write(&fs, 0x8002 + 0x4000, info, sizeof(info));
  ate[7] ^= 0x55;
  CHECK(find_ext(ext) && ext[0] == 0x20, "corrupt ATE skipped: got 0x%02X", ext[0]);

  // Deleted (length 0), as after a factory reset
  nvs_write(&fs, 0x8002 + 0x4000, "", 0);
  CHECK(!find_ext(ext), "deleted value still found");

  // Name id reused for another key
  nvs_init(0, &fs);
  network_info(info, 0x40);
  settings_save(&fs, 0x8002, "ot/3", info, sizeof(info));
  nvs_write(&fs, 0x8002, "mt/other", 8);
  CHECK(!find_ext(ext), "name id reused, old name still matched");

  // Network info too short (other OpenThread version)
  nvs_init(0, &fs);
  settings_save(&fs, 0x8002, "ot/3", info, 20);
  CHECK(!find_ext(ext), "short record accepted");

  // Not NVS at all
  memset(area, 0, sizeof(area));
  CHECK(!find_ext(ext), "zeroed area accepted");

  // A real SETTINGS.UF2: print the hostname
  if (argc > 1) {
    FILE* f = fopen(argv[1], "rb");
    static uint8_t uf2[512 * 128];
    size_t const n = f ? fread(uf2, 1, sizeof(uf2), f) : 0;
    if (f) fclose(f);
    CHECK(n == sizeof(uf2), "%s: not a 128-block SETTINGS.UF2", argv[1]);
    for (int b = 0; b < 128; b++) memcpy(area + b * 256, uf2 + b * 512 + 32, 256);
    if (find_ext(ext)) {
      printf("%s: status page http://", argv[1]);
      for (int i = 0; i < 8; i++) printf("%02X", ext[i]);
      printf(".local/\n");
    } else {
      printf("%s: no Thread network info\n", argv[1]);
    }
  }

  printf(failures ? "%d failures\n" : "settings_test: all passed\n", failures);
  return failures ? 1 : 0;
}
