/*
 * LaMetric Time follows the power of one D2-01 actuator (the kitchen radio):
 *
 *   power >= CONFIG_GATEWAY_LAMETRIC_ON_W   screensaver off, radio app plays
 *   power == 0 W                            screensaver on, radio app stops
 *
 * Only the screensaver's "enabled" is changed: its modes (e.g. time based) and the display
 * brightness stay as configured on the clock.
 *
 * The clock is reached through its local REST API (plain HTTP, port 8080 by default, basic auth
 * "dev:<API key>"), on OpenThread's TCP. The clock has an IPv4 address on the home network; the
 * gateway synthesizes an IPv6 address from it with the NAT64 prefix the border router publishes in
 * the Thread network data. An IPv6 address of the clock works too.
 *
 * Requests, one at a time:
 *   PUT  /api/v2/device/display                                  {"screensaver":{"enabled":false|true}}
 *   GET  /api/v2/device/apps/com.lametric.radio                  once, for the radio widget ID
 *   POST /api/v2/device/apps/com.lametric.radio/widgets/<id>/actions   {"id":"radio.play"} / "radio.stop"
 *
 * Only changes are sent (the first power value after a start counts as one). A failed request is
 * retried after 30 s, doubling up to 10 min; a new power state restarts at once.
 *
 * Host, API key and the actuator are set in the shell (`lametric ...`) and kept in the settings.
 */

#pragma once

#include <stddef.h>
#include <stdint.h>

namespace Gateway::LaMetric
{

/* Loads the settings. Call once Thread is initialized. */
void Init();

/* A power value measured by an EnOcean actuator. Matter thread. */
void OnPower(uint32_t id, uint32_t watts);

/* --- Shell --- */

/* @p host: IPv4 or IPv6 address of the clock. False if it is not an address. */
bool SetHost(const char *host, uint16_t port);
bool SetApiKey(const char *key);
void SetTrigger(uint32_t id);
/* Sends on (screensaver off, radio plays) or off now, as if the power had changed. */
void Apply(bool on);

struct Status {
	char mHost[40];
	uint16_t mPort;
	bool mHasApiKey;
	uint32_t mTrigger; /* 0 = none */
	int8_t mWanted;	   /* -1 = no power value yet, 0 = off, 1 = on */
	int8_t mApplied;   /* -1 = unknown */
	bool mBusy;
	char mWidget[40];  /* radio widget ID, empty until found */
	int mLastHttpStatus;
	char mLastError[112];
	uint32_t mRetryInS; /* 0 = no retry pending */
	uint32_t mRequests;
	uint32_t mFailures;
};

void GetStatus(Status &out);

} /* namespace Gateway::LaMetric */
