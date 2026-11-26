/*
 * EnMT carrier board (hardware/enocean-carrier): a nice!nano v2 with three status LEDs under the
 * lid's light pipes and the FUNC button (firmware/common/boards/enmt_carrier.overlay).
 * Based on boards/nice_nano; same USB IDs, so a nice!nano's stock bootloader accepts this one
 * as update-enmt_bootloader-*_nosd.uf2.
 */

#ifndef _ENMT_H
#define _ENMT_H

#define UICR_REGOUT0_VALUE UICR_REGOUT0_VOUT_3V3

/*------------------------------------------------------------------*/
/* LED: three-LED pattern, see enmt_leds.h. All hang from 3.3 V: low = on.
 * The nice!nano's own LED (P0.15, under the module) stays off.
 *------------------------------------------------------------------*/
#define BOARD_LEDS_ENMT   1
#define LEDS_NUMBER       3
#define LED_PRIMARY_PIN   PINNUM(1, 13) // green LINK
#define LED_SECONDARY_PIN PINNUM(1, 15) // yellow RX
#define LED_TERTIARY_PIN  PINNUM(1, 11) // red PWR
#define LED_TERTIARY      2
#define LED_STATE_ON      0

/*------------------------------------------------------------------*/
/* BUTTON: FUNC (P1.06 to GND) held while resetting enters the UF2 drive
 *------------------------------------------------------------------*/
#define BUTTON_DFU  PINNUM(1, 6)
#define BUTTON_PULL NRF_GPIO_PIN_PULLUP

/*------------------------------------------------------------------*/
/* QSPI flash (U3, W25Q32JV, 4 MB) for staged OTA images, see enmt_qspi_ota.c
 *------------------------------------------------------------------*/
#define QSPI_OTA_PIN_SCK PINNUM(0, 17)
#define QSPI_OTA_PIN_CSN PINNUM(0, 24)
#define QSPI_OTA_PIN_IO0 PINNUM(0, 22)
#define QSPI_OTA_PIN_IO1 PINNUM(0, 20)
#define QSPI_OTA_PIN_IO2 PINNUM(1, 0)
#define QSPI_OTA_PIN_IO3 PINNUM(0, 11)

//--------------------------------------------------------------------+
// BLE OTA
//--------------------------------------------------------------------+
#define BLEDIS_MANUFACTURER "EnMT"
#define BLEDIS_MODEL        "EnMT carrier"

//--------------------------------------------------------------------+
// USB
//--------------------------------------------------------------------+
#define USB_DESC_VID          0x239A
#define USB_DESC_UF2_PID      0x00B3
#define USB_DESC_CDC_ONLY_PID 0x00B3

#define UF2_PRODUCT_NAME      "EnMT carrier"
#define UF2_VOLUME_LABEL      "ENMTBOOT   "
#define UF2_BOARD_ID          "nRF52840-EnMT-carrier"
#define UF2_INDEX_URL         "https://github.com/BerndDA/enocean-ble-matter-bridge"

#endif // _ENMT_H
