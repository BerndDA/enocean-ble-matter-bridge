/*
 * PWR and RX LEDs of the EnMT carrier board (common/boards/enmt_carrier.overlay, `make BOARD=enmt`)
 * and of the nRF52840 DK (LED3, LED2; common/boards/nrf52840dk_status_leds.dtsi).
 * LINK is Nrf::Board's status LED (LED1) and needs nothing here.
 *
 *   PWR (red, LED3)    on; blinks while the app's health check fails (EnOcean: the TCM hasn't
 *                      answered yet; the BLE gateway has no check, PWR just stays on). An app
 *                      with more to say picks one of four patterns instead (Pwr, Nuki gateway).
 *   RX  (yellow, LED2) a short pulse per radio packet from a bridged or known device, or on
 *                      for as long as the app holds it (Nuki: a connection to the lock)
 *
 * Built only with CONFIG_GATEWAY_STATUS_LEDS, which the led_pwr label turns on.
 */

#pragma once

#include <stdint.h>

namespace Gateway::StatusLeds
{

/* Returns false while something the gateway needs is missing (polled every second). */
using HealthCheck = bool (*)();

/* PWR patterns, from fine to needs attention */
enum class Pwr : uint8_t {
	On,
	Activity, /* fast blink (100/100 ms): e.g. looking for a device to pair */
	Warning, /* slow even blink (500/500 ms): e.g. a paired device isn't reached */
	Fault, /* short flash per second (150/850 ms): something is missing (the health check's fault) */
};

/* Returns the pattern to show (polled every second). */
using PwrCheck = Pwr (*)();

/* After Nrf::GetBoard().Init(), in the app task. @p healthy may be nullptr: PWR stays on. */
void Init(HealthCheck healthy = nullptr);

/* The same with a pattern per state instead of on / fault. */
void InitPattern(PwrCheck pattern);

/* From any thread. */
void PacketReceived();

/* From any thread: RX stays on while active (a pulse in between doesn't turn it off). */
void SetRxActive(bool active);

} /* namespace Gateway::StatusLeds */
