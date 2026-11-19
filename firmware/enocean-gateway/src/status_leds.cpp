/*
 * PWR and RX LEDs of the EnMT carrier board, see status_leds.h.
 */

#include "status_leds.h"

#include "app/task_executor.h"
#include "board/board.h"
#include "tcm.h"

#include <zephyr/kernel.h>

namespace Gateway::StatusLeds
{
namespace
{

constexpr uint32_t kRxPulseMs = 80;
constexpr uint32_t kTcmCheckMs = 1000;
constexpr int64_t kTcmGraceMs = 3000;          /* the TCM answers within about a second after boot */
constexpr uint32_t kTcmMissingOnMs = 150;
constexpr uint32_t kTcmMissingOffMs = 850;

enum class TcmState { Unknown, Present, Missing };

TcmState sTcmState = TcmState::Unknown;
k_timer sTcmTimer;
k_timer sRxTimer;

Nrf::LEDWidget &PwrLed()
{
	return Nrf::GetBoard().GetLED(Nrf::DeviceLeds::LED3);
}

Nrf::LEDWidget &RxLed()
{
	return Nrf::GetBoard().GetLED(Nrf::DeviceLeds::LED2);
}

/* App task: set PWR only when the TCM state changes, so a factory reset's blinking isn't overridden. */
void UpdatePwr()
{
	TcmState state = TcmState::Unknown;

	if (tcm_base_id() != 0) {
		state = TcmState::Present;
	} else if (k_uptime_get() >= kTcmGraceMs) {
		state = TcmState::Missing;
	}
	if (state == sTcmState || state == TcmState::Unknown) {
		return;
	}
	sTcmState = state;
	if (state == TcmState::Present) {
		PwrLed().Set(true);
	} else {
		PwrLed().Blink(kTcmMissingOnMs, kTcmMissingOffMs);
	}
}

void TcmTimerHandler(k_timer *)
{
	Nrf::PostTask([] { UpdatePwr(); });
}

void RxTimerHandler(k_timer *)
{
	Nrf::PostTask([] { RxLed().Set(false); });
}

} /* namespace */

void Init()
{
	k_timer_init(&sTcmTimer, TcmTimerHandler, nullptr);
	k_timer_init(&sRxTimer, RxTimerHandler, nullptr);
	/* PWR lights right away; it starts blinking if the TCM stays silent. */
	PwrLed().Set(true);
	k_timer_start(&sTcmTimer, K_MSEC(kTcmCheckMs), K_MSEC(kTcmCheckMs));
}

void TelegramReceived()
{
	Nrf::PostTask([] {
		RxLed().Set(true);
		k_timer_start(&sRxTimer, K_MSEC(kRxPulseMs), K_NO_WAIT);
	});
}

} /* namespace Gateway::StatusLeds */
