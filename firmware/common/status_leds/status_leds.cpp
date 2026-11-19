/*
 * PWR and RX LEDs of the EnMT carrier board, see status_leds.h.
 */

#include "status_leds.h"

#include "app/task_executor.h"
#include "board/board.h"

#include <zephyr/kernel.h>

namespace Gateway::StatusLeds
{
namespace
{

constexpr uint32_t kRxPulseMs = 80;
constexpr uint32_t kCheckMs = 1000;
constexpr int64_t kGraceMs = 3000;             /* e.g. the TCM answers within about a second after boot */
constexpr uint32_t kFaultOnMs = 150;
constexpr uint32_t kFaultOffMs = 850;

enum class Health { Unknown, Ok, Fault };

HealthCheck sHealthy;
Health sHealth = Health::Unknown;
k_timer sCheckTimer;
k_timer sRxTimer;

Nrf::LEDWidget &PwrLed()
{
	return Nrf::GetBoard().GetLED(Nrf::DeviceLeds::LED3);
}

Nrf::LEDWidget &RxLed()
{
	return Nrf::GetBoard().GetLED(Nrf::DeviceLeds::LED2);
}

/* App task: set PWR only when the health changes, so a factory reset's blinking isn't overridden. */
void UpdatePwr()
{
	Health health = Health::Unknown;

	if (sHealthy()) {
		health = Health::Ok;
	} else if (k_uptime_get() >= kGraceMs) {
		health = Health::Fault;
	}
	if (health == sHealth || health == Health::Unknown) {
		return;
	}
	sHealth = health;
	if (health == Health::Ok) {
		PwrLed().Set(true);
	} else {
		PwrLed().Blink(kFaultOnMs, kFaultOffMs);
	}
}

void CheckTimerHandler(k_timer *)
{
	Nrf::PostTask([] { UpdatePwr(); });
}

void RxTimerHandler(k_timer *)
{
	Nrf::PostTask([] { RxLed().Set(false); });
}

} /* namespace */

void Init(HealthCheck healthy)
{
	k_timer_init(&sRxTimer, RxTimerHandler, nullptr);
	/* PWR lights right away; with a health check it starts blinking while the check fails. */
	PwrLed().Set(true);
	sHealthy = healthy;
	if (sHealthy) {
		k_timer_init(&sCheckTimer, CheckTimerHandler, nullptr);
		k_timer_start(&sCheckTimer, K_MSEC(kCheckMs), K_MSEC(kCheckMs));
	}
}

void PacketReceived()
{
	Nrf::PostTask([] {
		RxLed().Set(true);
		k_timer_start(&sRxTimer, K_MSEC(kRxPulseMs), K_NO_WAIT);
	});
}

} /* namespace Gateway::StatusLeds */
