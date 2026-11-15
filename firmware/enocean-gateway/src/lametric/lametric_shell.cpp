/*
 * Shell commands of the LaMetric client: `lametric ...`. See lametric.h.
 */

#include "lametric.h"

#include <zephyr/shell/shell.h>

#include <stdlib.h>
#include <string.h>

using namespace Gateway;

namespace
{

const char *StateName(int8_t state)
{
	return state < 0 ? "unknown" : (state ? "on" : "off");
}

int CmdStatus(const struct shell *sh, size_t, char **)
{
	LaMetric::Status s;

	LaMetric::GetStatus(s);
	if (s.mHost[0]) {
		shell_print(sh, "Clock:      %s port %u, API key %s", s.mHost, s.mPort, s.mHasApiKey ? "set" : "missing");
	} else {
		shell_print(sh, "Clock:      not set (lametric host <address> [port])");
	}
	if (s.mTrigger) {
		shell_print(sh, "Follows:    %08X (>= %u W: on, 0 W: off)", s.mTrigger, CONFIG_GATEWAY_LAMETRIC_ON_W);
	} else {
		shell_print(sh, "Follows:    nothing (lametric trigger <id>)");
	}
	shell_print(sh, "State:      wanted %s, sent %s%s", StateName(s.mWanted), StateName(s.mApplied),
		    s.mBusy ? ", request in flight" : "");
	shell_print(sh, "Radio:      widget %s", s.mWidget[0] ? s.mWidget : "not looked up yet");
	shell_print(sh, "Requests:   %u, %u failed; last HTTP status %d%s%s", s.mRequests, s.mFailures,
		    s.mLastHttpStatus, s.mLastError[0] ? ", last error: " : "", s.mLastError);
	if (s.mRetryInS) {
		shell_print(sh, "Retry in:   %u s", s.mRetryInS);
	}
	return 0;
}

int CmdHost(const struct shell *sh, size_t argc, char **argv)
{
	unsigned long port = CONFIG_GATEWAY_LAMETRIC_PORT;

	if (argc > 2) {
		char *end;

		port = strtoul(argv[2], &end, 10);
		if (*end || port == 0 || port > 65535) {
			shell_error(sh, "Invalid port: %s", argv[2]);
			return -EINVAL;
		}
	}
	if (!LaMetric::SetHost(argv[1], uint16_t(port))) {
		shell_error(sh, "Not an IPv4 or IPv6 address: %s", argv[1]);
		return -EINVAL;
	}
	return 0;
}

int CmdKey(const struct shell *sh, size_t, char **argv)
{
	if (!LaMetric::SetApiKey(argv[1])) {
		shell_error(sh, "API key too long");
		return -EINVAL;
	}
	return 0;
}

int CmdTrigger(const struct shell *sh, size_t, char **argv)
{
	char *end;
	unsigned long v = strtoul(argv[1], &end, 16);

	if (*end || strlen(argv[1]) > 8) {
		shell_error(sh, "Invalid EnOcean ID: %s (8 hex digits, e.g. 05017E43; 0 = none)", argv[1]);
		return -EINVAL;
	}
	LaMetric::SetTrigger(uint32_t(v));
	return 0;
}

int CmdOnOff(const struct shell *sh, size_t, char **argv)
{
	LaMetric::Apply(strcmp(argv[0], "on") == 0);
	shell_print(sh, "Sending; see `lametric status`");
	return 0;
}

} /* namespace */

SHELL_STATIC_SUBCMD_SET_CREATE(
	sLaMetricCommands, SHELL_CMD(status, NULL, "Settings, state and last error", CmdStatus),
	SHELL_CMD_ARG(host, NULL, "<IPv4|IPv6> [port]: the clock (port 8080 by default)", CmdHost, 2, 1),
	SHELL_CMD_ARG(key, NULL, "<API key>: from developer.lametric.com > Devices", CmdKey, 2, 0),
	SHELL_CMD_ARG(trigger, NULL, "<id>: the D2-01 actuator whose power the clock follows (0 = none)",
		      CmdTrigger, 2, 0),
	SHELL_CMD(on, NULL, "Screensaver off and radio on, now", CmdOnOff),
	SHELL_CMD(off, NULL, "Screensaver on and radio off, now", CmdOnOff), SHELL_SUBCMD_SET_END);

SHELL_CMD_REGISTER(lametric, &sLaMetricCommands, "LaMetric Time follows an actuator's power", NULL);
