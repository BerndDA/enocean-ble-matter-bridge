/*
 * Bootloader LED pattern for the EnMT carrier's three status LEDs (green LINK, yellow RX, red PWR).
 *
 * Copied to src/boards/ of the Adafruit nRF52 bootloader and included by boards.c in place of its
 * own led_tick()/led_state() when the board defines BOARD_LEDS_ENMT (see boards.patch).
 * The board maps LED_PRIMARY/SECONDARY/TERTIARY to green/yellow/red; all on PWM0, 1 kHz SysTick.
 *
 * The patterns fade, so they can't be mistaken for the app, which only switches its LEDs:
 *   no USB host           red breathes (2 s), e.g. on a charger or before the host enumerates
 *   UF2 drive ready       a light sweeps green → yellow → red → yellow → … (1.6 s per pass)
 *   writing a .uf2        all three pulse together (0.4 s); then the bootloader starts the app
 *   BLE DFU connected     green breathes (only boards without NO_BLE_OTA, with a SoftDevice)
 */

#ifndef ENMT_LEDS_H
#define ENMT_LEDS_H

#ifndef ENMT_LED_MAX
#define ENMT_LED_MAX 0xff // peak PWM duty (COUNTERTOP is 0xff)
#endif

enum {
  ENMT_MODE_NO_HOST = 0,
  ENMT_MODE_READY,
  ENMT_MODE_WRITING,
  ENMT_MODE_BLE,
};

static volatile uint8_t _enmt_mode = ENMT_MODE_NO_HOST;
static uint8_t _enmt_base_mode = ENMT_MODE_NO_HOST; // mode to return to after writing

// Triangle wave 0..256..0 over period ms.
static uint32_t enmt_triangle(uint32_t millis, uint32_t period) {
  uint32_t const half = period / 2;
  uint32_t phase = millis % period;
  if (phase > half) {
    phase = period - phase;
  }
  return 256 * phase / half;
}

// Brightness 0..256 to PWM duty, squared so the fade looks even to the eye.
static uint16_t enmt_duty(uint32_t level) {
  uint32_t const duty = level * level * ENMT_LED_MAX / (256 * 256);
#if LED_STATE_ON == 1
  return 0xff - duty;
#else
  return duty;
#endif
}

// Light position 0..512 (green 0, yellow 256, red 512): each LED fades with its distance to it.
static void enmt_sweep(uint32_t millis, uint32_t period) {
  uint32_t const pos = 2 * enmt_triangle(millis, period);
  uint32_t const center[3] = {0, 256, 512};
  uint32_t const led[3] = {LED_PRIMARY, LED_SECONDARY, LED_TERTIARY};

  for (int i = 0; i < 3; i++) {
    uint32_t const dist = pos > center[i] ? pos - center[i] : center[i] - pos;
    led_pwm_duty_cycle(led[i], enmt_duty(dist < 256 ? 256 - dist : 0));
  }
}

static void enmt_breathe(uint32_t millis, uint32_t period, uint32_t lit) {
  uint32_t const level = enmt_triangle(millis, period);
  led_pwm_duty_cycle(LED_PRIMARY, enmt_duty(lit == LED_PRIMARY ? level : 0));
  led_pwm_duty_cycle(LED_SECONDARY, enmt_duty(lit == LED_SECONDARY ? level : 0));
  led_pwm_duty_cycle(LED_TERTIARY, enmt_duty(lit == LED_TERTIARY ? level : 0));
}

void led_tick(void) {
  uint32_t const millis = _systick_count;

  switch (_enmt_mode) {
    case ENMT_MODE_READY:
      enmt_sweep(millis, 1600);
      break;

    case ENMT_MODE_WRITING: {
      uint16_t const duty = enmt_duty(enmt_triangle(millis, 400));
      led_pwm_duty_cycle(LED_PRIMARY, duty);
      led_pwm_duty_cycle(LED_SECONDARY, duty);
      led_pwm_duty_cycle(LED_TERTIARY, duty);
      break;
    }

    case ENMT_MODE_BLE:
      enmt_breathe(millis, 2000, LED_PRIMARY);
      break;

    case ENMT_MODE_NO_HOST:
    default:
      enmt_breathe(millis, 2000, LED_TERTIARY);
      break;
  }
}

void led_state(uint32_t state) {
  switch (state) {
    case STATE_BOOTLOADER_STARTED:
    case STATE_USB_UNMOUNTED:
    case STATE_BLE_DISCONNECTED:
      _enmt_base_mode = ENMT_MODE_NO_HOST;
      _enmt_mode = ENMT_MODE_NO_HOST;
      break;

    case STATE_USB_MOUNTED:
      _enmt_base_mode = ENMT_MODE_READY;
      _enmt_mode = ENMT_MODE_READY;
      break;

    case STATE_BLE_CONNECTED:
      _enmt_base_mode = ENMT_MODE_BLE;
      _enmt_mode = ENMT_MODE_BLE;
      break;

    case STATE_WRITING_STARTED:
      _enmt_mode = ENMT_MODE_WRITING;
      break;

    case STATE_WRITING_FINISHED:
      _enmt_mode = _enmt_base_mode;
      break;

    default:
      break;
  }
}

#endif // ENMT_LEDS_H
