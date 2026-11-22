/*
 * PWR and RX LEDs of the EnMT carrier board, see status_leds.h.
 */

#include "status_leds.h"

#include "app/task_executor.h"
#include "board/board.h"

#include <zephyr/kernel.h>
#include <zephyr/sys/atomic.h>

namespace Gateway::StatusLeds
{
namespace
{

constexpr uint32_t kRxPulseMs = 80;
constexpr uint32_t kCheckMs = 1000;
constexpr int64_t kGraceMs = 3000; /* e.g. the TCM answers within about a second after boot */

enum class State : uint8_t { Unknown, On, Activity, Warning, Fault };

HealthCheck sHealthy;
PwrCheck sPattern;
State sState = State::Unknown;
k_timer sCheckTimer;
k_timer sRxTimer;
atomic_t sRxHeld;

Nrf::LEDWidget &PwrLed()
{
	return Nrf::GetBoard().GetLED(Nrf::DeviceLeds::LED3);
}

Nrf::LEDWidget &RxLed()
{
	return Nrf::GetBoard().GetLED(Nrf::DeviceLeds::LED2);
}

State Wanted()
{
	if (sPattern) {
		switch (sPattern()) {
		case Pwr::On: return State::On;
		case Pwr::Activity: return State::Activity;
		case Pwr::Warning: return State::Warning;
		case Pwr::Fault: return State::Fault;
		}
	}
	return sHealthy() ? State::On : State::Fault;
}

/* App task: set PWR only when the state changes, so a factory reset's blinking isn't overridden. */
void UpdatePwr()
{
	State state = Wanted();

	/* Give the app a moment after boot before showing a problem. */
	if (state != State::On && k_uptime_get() < kGraceMs) {
		state = State::Unknown;
	}
	if (state == sState || state == State::Unknown) {
		return;
	}
	sState = state;
	switch (state) {
	case State::On:
		PwrLed().Set(true);
		break;
	case State::Activity:
		PwrLed().Blink(100, 100);
		break;
	case State::Warning:
		PwrLed().Blink(500, 500);
		break;
	default:
		PwrLed().Blink(150, 850);
		break;
	}
}

void CheckTimerHandler(k_timer *)
{
	Nrf::PostTask([] { UpdatePwr(); });
}

void RxTimerHandler(k_timer *)
{
	Nrf::PostTask([] {
		if (!atomic_get(&sRxHeld)) {
			RxLed().Set(false);
		}
	});
}

void Start()
{
	k_timer_init(&sRxTimer, RxTimerHandler, nullptr);
	/* PWR lights right away; with a check it changes pattern once the check says so. */
	PwrLed().Set(true);
	if (sHealthy || sPattern) {
		k_timer_init(&sCheckTimer, CheckTimerHandler, nullptr);
		k_timer_start(&sCheckTimer, K_MSEC(kCheckMs), K_MSEC(kCheckMs));
	}
}

} /* namespace */

void Init(HealthCheck healthy)
{
	sHealthy = healthy;
	Start();
}

void InitPattern(PwrCheck pattern)
{
	sPattern = pattern;
	Start();
}

void PacketReceived()
{
	Nrf::PostTask([] {
		RxLed().Set(true);
		k_timer_start(&sRxTimer, K_MSEC(kRxPulseMs), K_NO_WAIT);
	});
}

void SetRxActive(bool active)
{
	atomic_set(&sRxHeld, active);
	Nrf::PostTask([] { RxLed().Set(atomic_get(&sRxHeld)); });
}

} /* namespace Gateway::StatusLeds */
