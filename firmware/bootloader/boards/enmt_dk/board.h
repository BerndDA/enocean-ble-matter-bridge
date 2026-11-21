/*
 * nRF52840 DK standing in for the EnMT carrier: the carrier's three-LED bootloader pattern
 * (enmt_leds.h) on the DK's LED1..3, in the same roles as firmware/common/boards/nrf52840dk_status_leds.dtsi.
 * Based on boards/pca10056; same USB IDs.
 */

#ifndef _ENMT_DK_H
#define _ENMT_DK_H

/*------------------------------------------------------------------*/
/* LED: three-LED pattern, see enmt_leds.h. Active low; LED4 stays off.
 *------------------------------------------------------------------*/
#define BOARD_LEDS_ENMT   1
#define LEDS_NUMBER       3
#define LED_PRIMARY_PIN   13 // LED1 = green LINK
#define LED_SECONDARY_PIN 14 // LED2 = yellow RX
#define LED_TERTIARY_PIN  15 // LED3 = red PWR
#define LED_TERTIARY      2
#define LED_STATE_ON      0

/*------------------------------------------------------------------*/
/* BUTTON
 *------------------------------------------------------------------*/
#define BUTTON_DFU     11
#define BUTTON_DFU_OTA 12
#define BUTTON_PULL    NRF_GPIO_PIN_PULLUP

//--------------------------------------------------------------------+
// BLE OTA
//--------------------------------------------------------------------+
#define BLEDIS_MANUFACTURER "Nordic"
#define BLEDIS_MODEL        "PCA10056"

//--------------------------------------------------------------------+
// USB
//--------------------------------------------------------------------+
#define USB_DESC_VID          0x239A
#define USB_DESC_UF2_PID      0x00DA
#define USB_DESC_CDC_ONLY_PID 0x00DA

#define UF2_PRODUCT_NAME      "nRF52840 DK (EnMT LEDs)"
#define UF2_VOLUME_LABEL      "ENMTBOOT   "
#define UF2_BOARD_ID          "nRF52840-pca10056-enmt"
#define UF2_INDEX_URL         "https://github.com/BerndDA/enocean-ble-matter-bridge"

#endif // _ENMT_DK_H
