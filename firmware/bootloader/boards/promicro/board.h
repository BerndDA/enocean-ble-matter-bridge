/*
 * Plain Pro Micro nRF52840 (nice!nano v2 and its clones), without the EnMT carrier: the gateway
 * apps built with BOARD=promicro-uf2, and BOARD=enmt on a bare module.
 * Based on boards/nice_nano; same USB IDs, so the module's stock bootloader accepts this one
 * as update-promicro_bootloader-*_nosd.uf2. Same features as boards/enmt, except the Matter OTA
 * from the QSPI flash (there is none) and the FUNC button (a double reset enters the drive).
 */

#ifndef _PROMICRO_H
#define _PROMICRO_H

#define UICR_REGOUT0_VALUE UICR_REGOUT0_VOUT_3V3

/*------------------------------------------------------------------*/
/* LED: the module's own LED, single-LED variant of the pattern in enmt_leds.h
 *------------------------------------------------------------------*/
#define BOARD_LEDS_ENMT 1
#define LEDS_NUMBER     1
#define LED_PRIMARY_PIN PINNUM(0, 15) // blue (red on some clones), under the module
#define LED_STATE_ON    1

/*------------------------------------------------------------------*/
/* BUTTON: none, double-tap reset enters the UF2 drive
 *------------------------------------------------------------------*/

//--------------------------------------------------------------------+
// BLE OTA
//--------------------------------------------------------------------+
#define BLEDIS_MANUFACTURER "EnMT"
#define BLEDIS_MODEL        "EnMT Pro Micro"

//--------------------------------------------------------------------+
// USB
//--------------------------------------------------------------------+
#define USB_DESC_VID          0x239A
#define USB_DESC_UF2_PID      0x00B3
#define USB_DESC_CDC_ONLY_PID 0x00B3

#define UF2_PRODUCT_NAME      "EnMT Pro Micro"
#define UF2_VOLUME_LABEL      "ENMTBOOT   "
#define UF2_BOARD_ID          "nRF52840-EnMT-promicro"
#define UF2_INDEX_URL         "https://github.com/BerndDA/enocean-ble-matter-bridge"

#endif // _PROMICRO_H
