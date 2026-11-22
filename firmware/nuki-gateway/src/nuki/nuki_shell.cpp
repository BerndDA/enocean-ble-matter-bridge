/*
 * `nuki ...` shell commands:
 *   nuki status                  pairing, last state, beacon, counters
 *   nuki pair                    pair with a lock in pairing mode (hold its button for 5 s)
 *   nuki unpair                  forget the pairing
 *   nuki lock|unlock|unlatch     lock actions
 *   nuki state                   read the state now
 *   nuki info                    read name, Nuki ID and versions
 * Requests run in the Nuki thread; their results appear in the log.
 */

#include "nuki_client.h"

#include <zephyr/kernel.h>
#include <zephyr/shell/shell.h>

#include <errno.h>

using namespace Gateway;

namespace
{

int Report(const shell *sh, int err, const char *what)
{
	switch (err) {
	case 0:
		shell_print(sh, "%s queued; the result appears in the log", what);
		return 0;
	case -EALREADY:
		shell_print(sh, "Already paired (nuki unpair first)");
		return 0;
	case -EPERM:
		shell_error(sh, "Not paired: nuki pair");
		return err;
	default:
		shell_error(sh, "%s not queued (%d)", what, err);
		return err;
	}
}

int CmdStatus(const shell *sh, size_t, char **)
{
	Nuki::Snapshot s;
	const int64_t now = k_uptime_get();

	Nuki::GetSnapshot(s);
	if (!s.mPaired) {
		shell_print(sh, "Not paired%s", s.mSearching ? ", looking for a lock in pairing mode" : "");
	} else {
		char addr[BT_ADDR_LE_STR_LEN];

		bt_addr_le_to_str(&s.mAddr, addr, sizeof(addr));
		shell_print(sh, "Paired with %s, authorization ID %u", addr, s.mAuthId);
		if (s.mLastBeaconMs) {
			shell_print(sh, "Beacon: %d dBm, %lld s ago", s.mRssi, (now - s.mLastBeaconMs) / 1000);
		} else {
			shell_print(sh, "Beacon: not heard yet");
		}
	}
	if (s.mHaveInfo) {
		shell_print(sh, "Lock: '%s', Nuki ID %08X, firmware %u.%u.%u, hardware %u.%u", s.mInfo.name,
			    s.mInfo.nuki_id, s.mInfo.firmware[0], s.mInfo.firmware[1], s.mInfo.firmware[2],
			    s.mInfo.hardware[0], s.mInfo.hardware[1]);
	}
	if (s.mHaveState) {
		shell_print(sh, "State: %s, door %s, battery %u %%%s%s (%lld s ago)",
			    nuki_lock_state_str(s.mState.lock_state), nuki_door_state_str(s.mState.door_state),
			    nuki_battery_percent(s.mState.battery_raw),
			    nuki_battery_critical(s.mState.battery_raw) ? ", critical" : "",
			    nuki_battery_charging(s.mState.battery_raw) ? ", charging" : "", (now - s.mStateMs) / 1000);
	}
	shell_print(sh, "Requests: %u, failed %u, last: %s%s", s.mRequests, s.mFailures, Nuki::ResultStr(s.mLastResult),
		    s.mBusy ? " (one running)" : "");
	shell_print(sh, "Connections: %u, failed %u, last disconnect reason 0x%02x", s.mConnects, s.mConnectFailures,
		    s.mLastDisconnectReason);
	shell_print(sh, "Scan: %s, %u advertisements received%s", s.mScanning ? "on" : "off", s.mAdvertisements,
		    s.mScanError ? " (last start failed)" : "");
	if (s.mScanError) {
		shell_print(sh, "Last scan start error: %d", s.mScanError);
	}
	if (s.mLastResult == Nuki::Result::LockError) {
		shell_print(sh, "Last lock error: 0x%02x (%s)", s.mLastError, nuki_error_str(s.mLastError));
	}
	return 0;
}

int CmdPair(const shell *sh, size_t, char **)
{
	const int err = Nuki::Pair();

	if (err == 0) {
		shell_print(sh, "Now hold the lock's button for 5 s (pairing mode)");
	}
	return Report(sh, err, "Pairing");
}

int CmdUnpair(const shell *sh, size_t, char **)
{
	Nuki::Unpair();
	shell_print(sh, "Pairing removed. Also remove the gateway's authorization in the Nuki app.");
	return 0;
}

int CmdLock(const shell *sh, size_t, char **)
{
	return Report(sh, Nuki::LockAction(NUKI_ACTION_LOCK), "Lock");
}

int CmdUnlock(const shell *sh, size_t, char **)
{
	return Report(sh, Nuki::LockAction(NUKI_ACTION_UNLOCK), "Unlock");
}

int CmdUnlatch(const shell *sh, size_t, char **)
{
	return Report(sh, Nuki::LockAction(NUKI_ACTION_UNLATCH), "Unlatch");
}

int CmdState(const shell *sh, size_t, char **)
{
	return Report(sh, Nuki::RefreshState(), "State read");
}

int CmdInfo(const shell *sh, size_t, char **)
{
	return Report(sh, Nuki::RefreshInfo(), "Info read");
}

} /* namespace */

SHELL_STATIC_SUBCMD_SET_CREATE(
	sub_nuki, SHELL_CMD_ARG(status, NULL, "Pairing, last state, beacon, counters.", CmdStatus, 1, 0),
	SHELL_CMD_ARG(pair, NULL, "Pair with a lock in pairing mode (hold its button for 5 s).", CmdPair, 1, 0),
	SHELL_CMD_ARG(unpair, NULL, "Forget the pairing.", CmdUnpair, 1, 0),
	SHELL_CMD_ARG(lock, NULL, "Lock.", CmdLock, 1, 0),
	SHELL_CMD_ARG(unlock, NULL, "Unlock (bolt only, the door stays shut).", CmdUnlock, 1, 0),
	SHELL_CMD_ARG(unlatch, NULL, "Unlock and pull the latch (opens the door).", CmdUnlatch, 1, 0),
	SHELL_CMD_ARG(state, NULL, "Read the lock state now.", CmdState, 1, 0),
	SHELL_CMD_ARG(info, NULL, "Read name, Nuki ID and versions.", CmdInfo, 1, 0), SHELL_SUBCMD_SET_END);

SHELL_CMD_REGISTER(nuki, &sub_nuki, "Nuki Smart Lock", NULL);
