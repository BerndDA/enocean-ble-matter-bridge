/*
 * Matter identity of the gateway firmware, computed by the bootloader from the chip ID, for the
 * UF2 drive's MATTER.TXT and QR.HTM. See enmt_identity.c.
 */

#ifndef ENMT_IDENTITY_H
#define ENMT_IDENTITY_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define ENMT_CHIP_ID_LEN     16
#define ENMT_MANUAL_CODE_LEN 11
#define ENMT_QR_PAYLOAD_LEN  22 // "MT:" + 19 Base38 characters
#define ENMT_FILE_MAX        511 // GhostFAT text files fit in one 512-byte sector
#define ENMT_QR_HTM_MAX      160

typedef struct {
  char     chip_id[ENMT_CHIP_ID_LEN + 1];
  uint16_t discriminator;
  uint32_t passcode;
} enmt_identity_t;

typedef struct {
  uint16_t vendor_id;
  uint16_t product_id;
  char     product_name[33];
} enmt_product_t;

// The file contents served by GhostFAT, filled by enmt_identity_init().
extern char enmt_matter_txt[ENMT_FILE_MAX + 1];
extern char enmt_qr_htm[ENMT_QR_HTM_MAX + 1];

// Reads the chip ID and the factory data, then fills enmt_matter_txt and enmt_qr_htm.
void enmt_identity_init(void);

// The parts below don't touch the hardware (host tests: test/identity_test.c).

// chip_id: 16 upper-case hex digits, as the app and the bootloader's USB serial number print it.
void enmt_identity_derive(const char* chip_id, enmt_identity_t* id);

// 11 digits, no dashes, NUL-terminated.
void enmt_manual_code(uint16_t discriminator, uint32_t passcode, char out[ENMT_MANUAL_CODE_LEN + 1]);

// "MT:..." for BLE commissioning with the standard flow, NUL-terminated.
void enmt_qr_payload(const enmt_product_t* product, const enmt_identity_t* id, char out[ENMT_QR_PAYLOAD_LEN + 1]);

// Vendor ID, product ID and product name from the Matter factory data (a CBOR map).
// False if they aren't there, e.g. erased flash.
bool enmt_factory_data_parse(const uint8_t* data, size_t len, enmt_product_t* product);

// Fills the two files (buffers of ENMT_FILE_MAX + 1 and ENMT_QR_HTM_MAX + 1).
// product may be NULL (no factory data: no QR code). ext_addr is the Thread extended address
// (the status page's hostname), NULL if the gateway hasn't joined a Thread network.
void enmt_identity_format(const enmt_identity_t* id, const enmt_product_t* product, const uint8_t* ext_addr,
                          char* matter_txt, char* qr_htm);

#endif // ENMT_IDENTITY_H
