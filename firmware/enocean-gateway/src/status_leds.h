/*
 * PWR and RX LEDs of the EnMT carrier board (boards/enmt_carrier.overlay, `make BOARD=enmt`).
 * LINK is Nrf::Board's status LED (LED1) and needs nothing here.
 *
 *   PWR (red, LED3)    on once the TCM has told its base ID; blinks while it hasn't (wiring, no TCM)
 *   RX  (yellow, LED2) a short pulse for every telegram received from another sender
 *
 * Built only with CONFIG_GATEWAY_STATUS_LEDS, which the overlay turns on.
 */

#pragma once

namespace Gateway::StatusLeds
{

/* After Nrf::GetBoard().Init(), in the app task. */
void Init();

/* From any thread. */
void TelegramReceived();

} /* namespace Gateway::StatusLeds */
