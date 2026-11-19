/*
 * PWR and RX LEDs of the EnMT carrier board (common/boards/enmt_carrier.overlay, `make BOARD=enmt`).
 * LINK is Nrf::Board's status LED (LED1) and needs nothing here.
 *
 *   PWR (red, LED3)    on; blinks while the app's health check fails (EnOcean: the TCM hasn't
 *                      answered yet; the BLE gateway has no check, PWR just stays on)
 *   RX  (yellow, LED2) a short pulse per radio packet from a bridged or known device
 *
 * Built only with CONFIG_GATEWAY_STATUS_LEDS, which the overlay turns on.
 */

#pragma once

namespace Gateway::StatusLeds
{

/* Returns false while something the gateway needs is missing (polled every second). */
using HealthCheck = bool (*)();

/* After Nrf::GetBoard().Init(), in the app task. @p healthy may be nullptr: PWR stays on. */
void Init(HealthCheck healthy = nullptr);

/* From any thread. */
void PacketReceived();

} /* namespace Gateway::StatusLeds */
