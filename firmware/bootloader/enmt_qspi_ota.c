/*
 * nRF52840 glue for enmt_ota.c: the QSPI flash (read, 4 KB sector erase) and NVMC, register level
 * to keep the bootloader small. Called from main() before anything else, see boards.patch.
 *
 * The board defines BOARD_QSPI_OTA and the pins QSPI_OTA_PIN_SCK/CSN/IO0..IO3. Reads use READ2O
 * (opcode 0x3B, two data lines) at 8 MHz: no quad-enable bit needed, and within what both chips
 * (MX25R6435F on the DK, W25Q32JV on the carrier) do in their default modes. About 0.3 s per pass
 * over a full 888 KB image.
 *
 * The QSPI is left disabled, its pins disconnected, as after reset: Zephyr's driver sets it up
 * from scratch, and an activated QSPI keeps drawing current (nRF52840 erratum 122).
 */

#ifdef BOARD_QSPI_OTA

#include "boards.h"
#include "enmt_ota.h"
#include "nrfx_nvmc.h"
#include "nrfx_glue.h"

#ifdef BOARD_BL_STAGING_ADDR
#define OTA_APP_END BOARD_BL_STAGING_ADDR // the app ends where bootloader updates are staged
#else
#error "BOARD_QSPI_OTA needs BOARD_BL_STAGING_ADDR (end of the app area)"
#endif
#define OTA_APP_START 0x1000u

#define SPI_RES      0xAB // release from deep power-down
#define SPI_RDSR     0x05 // read status register
#define SR_WIP       0x01
#define WAIT_LOOPS   2000000u // > 1 s at 64 MHz; erasing a sector takes at most 0.4 s

static bool qspi_wait_ready(void) {
  for (uint32_t i = 0; i < WAIT_LOOPS; i++) {
    if (NRF_QSPI->EVENTS_READY) {
      NRF_QSPI->EVENTS_READY = 0;
      return true;
    }
  }
  return false;
}

// Custom instruction: opcode plus len-1 data bytes (len 1..2); returns CINSTRDAT0.
static bool qspi_cinstr(uint8_t opcode, uint32_t len, uint32_t *dat) {
  NRF_QSPI->CINSTRDAT0 = 0;
  NRF_QSPI->CINSTRCONF = ((uint32_t) opcode << QSPI_CINSTRCONF_OPCODE_Pos) |
                         (len << QSPI_CINSTRCONF_LENGTH_Pos) |
                         QSPI_CINSTRCONF_LIO2_Msk | QSPI_CINSTRCONF_LIO3_Msk; // WP#, HOLD# high
  if (!qspi_wait_ready()) {
    return false;
  }
  if (dat) {
    *dat = NRF_QSPI->CINSTRDAT0;
  }
  return true;
}

static bool qspi_init(void) {
  NRF_QSPI->PSEL.SCK = QSPI_OTA_PIN_SCK;
  NRF_QSPI->PSEL.CSN = QSPI_OTA_PIN_CSN;
  NRF_QSPI->PSEL.IO0 = QSPI_OTA_PIN_IO0;
  NRF_QSPI->PSEL.IO1 = QSPI_OTA_PIN_IO1;
  NRF_QSPI->PSEL.IO2 = QSPI_OTA_PIN_IO2;
  NRF_QSPI->PSEL.IO3 = QSPI_OTA_PIN_IO3;
  NRF_QSPI->XIPOFFSET = 0;
  NRF_QSPI->IFCONFIG0 = (QSPI_IFCONFIG0_READOC_READ2O << QSPI_IFCONFIG0_READOC_Pos) |
                        (QSPI_IFCONFIG0_WRITEOC_PP << QSPI_IFCONFIG0_WRITEOC_Pos) |
                        (QSPI_IFCONFIG0_ADDRMODE_24BIT << QSPI_IFCONFIG0_ADDRMODE_Pos);
  NRF_QSPI->IFCONFIG1 = (3u << QSPI_IFCONFIG1_SCKFREQ_Pos) | // 32 MHz / (3 + 1) = 8 MHz
                        (QSPI_IFCONFIG1_SPIMODE_MODE0 << QSPI_IFCONFIG1_SPIMODE_Pos) |
                        (1u << QSPI_IFCONFIG1_SCKDELAY_Pos);
  NRF_QSPI->EVENTS_READY = 0;
  NRF_QSPI->ENABLE = QSPI_ENABLE_ENABLE_Enabled;
  NRF_QSPI->TASKS_ACTIVATE = 1;
  if (!qspi_wait_ready()) {
    return false;
  }
  // The app may have left the chip in deep power-down; then it ignores everything else
  if (!qspi_cinstr(SPI_RES, 1, NULL)) {
    return false;
  }
  NRFX_DELAY_US(50); // tRES1: 30 us (W25Q32JV), 35 us (MX25R6435F)
  return true;
}

static void qspi_uninit(void) {
  NRF_QSPI->TASKS_DEACTIVATE = 1;
  *(volatile uint32_t *) 0x40029054ul = 1; // erratum 122: QSPI current after deactivation
  NRF_QSPI->ENABLE = QSPI_ENABLE_ENABLE_Disabled;
  NRF_QSPI->EVENTS_READY = 0;
  NRF_QSPI->PSEL.SCK = 0xFFFFFFFFu;
  NRF_QSPI->PSEL.CSN = 0xFFFFFFFFu;
  NRF_QSPI->PSEL.IO0 = 0xFFFFFFFFu;
  NRF_QSPI->PSEL.IO1 = 0xFFFFFFFFu;
  NRF_QSPI->PSEL.IO2 = 0xFFFFFFFFu;
  NRF_QSPI->PSEL.IO3 = 0xFFFFFFFFu;
}

static bool ext_read(uint32_t addr, void *buf, uint32_t len) {
  NRF_QSPI->READ.SRC = addr;
  NRF_QSPI->READ.DST = (uint32_t) buf;
  NRF_QSPI->READ.CNT = len;
  NRF_QSPI->TASKS_READSTART = 1;
  return qspi_wait_ready();
}

static bool ext_erase_sector(uint32_t addr) {
  NRF_QSPI->ERASE.PTR = addr;
  NRF_QSPI->ERASE.LEN = QSPI_ERASE_LEN_LEN_4KB;
  NRF_QSPI->TASKS_ERASESTART = 1; // the QSPI sends WREN itself
  if (!qspi_wait_ready()) {
    return false;
  }
  // READY can come before the chip has finished: wait for its write-in-progress bit
  for (uint32_t i = 0; i < WAIT_LOOPS / 64; i++) {
    uint32_t sr;
    if (!qspi_cinstr(SPI_RDSR, 2, &sr)) {
      return false;
    }
    if (!(sr & SR_WIP)) {
      return true;
    }
  }
  return false;
}

static void int_erase_page(uint32_t addr) {
  nrfx_nvmc_page_erase(addr);
}

static void int_write_page(uint32_t addr, void const *buf) {
  nrfx_nvmc_words_write(addr, buf, ENMT_OTA_PAGE / 4);
}

static uint8_t const *int_ptr(uint32_t addr) {
  return (uint8_t const *) addr;
}

static void progress(bool copying) {
  led_state(copying ? STATE_WRITING_STARTED : STATE_WRITING_FINISHED);
}

void enmt_qspi_ota_apply(void) {
  static uint8_t buf[ENMT_OTA_PAGE] __attribute__((aligned(4)));
  static enmt_ota_io_t const io = {
      .ext_read = ext_read,
      .ext_erase_sector = ext_erase_sector,
      .int_erase_page = int_erase_page,
      .int_write_page = int_write_page,
      .int_ptr = int_ptr,
      .progress = progress,
  };

  if (qspi_init()) {
    enmt_ota_result_t const r = enmt_ota_apply(&io, OTA_APP_START, OTA_APP_END, buf);
    (void) r;
    PRINTF("QSPI OTA: %d\r\n", (int) r);
  }
  qspi_uninit();
}

#endif // BOARD_QSPI_OTA
