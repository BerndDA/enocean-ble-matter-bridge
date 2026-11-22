/*
 * Bluetooth LE client for one Nuki Smart Lock (3rd/4th generation; not the Ultra, which pairs with a PIN).
 *
 * One thread does everything that waits on the lock: pairing, lock actions and reading the state.
 * Each request is one short connection: connect, discover the service, subscribe to indications,
 * exchange messages (nuki_proto.h), disconnect. In between, a passive scan watches the lock's
 * iBeacon; when it flags new state, the state is read. A poll every
 * CONFIG_GATEWAY_NUKI_POLL_INTERVAL_S is the safety net.
 *
 * The pairing (key, authorization ID, address) is kept in the settings under "nuki/cred".
 */

#pragma once

#include "nuki_proto.h"

#include <zephyr/bluetooth/addr.h>

#include <stdint.h>

namespace Gateway
{
namespace Nuki
{

enum class Result : uint8_t {
	Ok,
	NotPaired,
	NotFound, /* no lock in pairing mode */
	ConnectFailed,
	Timeout,
	Disconnected,
	Protocol, /* unexpected or malformed message */
	LockError, /* the lock sent an Error Report: see Snapshot::mLastError */
};

const char *ResultStr(Result result);

/* Called from the Nuki thread. Any of them may be null. */
struct Callbacks {
	void (*mState)(const nuki_keyturner_state &state);
	void (*mInfo)(const nuki_config &config);
	void (*mActionDone)(uint8_t action, Result result);
	void (*mPaired)(bool paired);
	void (*mConnection)(bool open); /* a connection to the lock opened / closed */
};

/* Loads the pairing and starts the thread. Call once Bluetooth is enabled (after the Matter server init). */
int Init(const Callbacks &callbacks);

/*
 * Requests run one at a time in order. Each returns 0 when queued, -ENOMEM if the queue is
 * full, or -EPERM if the gateway isn't paired (Pair: -EALREADY if it is).
 */
int Pair();
int LockAction(uint8_t action); /* enum nuki_lock_action */
int RefreshState();
int RefreshInfo();

/* Forgets the pairing. The authorization stays in the lock: remove it in the Nuki app. */
void Unpair();

struct Snapshot {
	bool mPaired;
	bool mBusy; /* a request is running */
	bool mSearching; /* looking for a lock in pairing mode */
	bt_addr_le_t mAddr;
	uint32_t mAuthId;
	int8_t mRssi;
	int64_t mLastBeaconMs; /* uptime, 0 = none yet */
	bool mHaveState;
	nuki_keyturner_state mState;
	int64_t mStateMs;
	bool mHaveInfo;
	nuki_config mInfo;
	uint8_t mLastError; /* from the last Error Report */
	Result mLastResult;
	uint32_t mRequests;
	uint32_t mFailures;
	uint32_t mConnects; /* connection attempts */
	uint32_t mConnectFailures; /* attempts that ended before the Nuki service was ready */
	uint8_t mLastDisconnectReason; /* HCI reason of the last disconnect or failed connect */
	bool mScanning; /* the beacon scan runs */
	uint32_t mAdvertisements; /* received by the scan, from any device */
	int mScanError; /* of the last failed scan start, 0 = none */
};

void GetSnapshot(Snapshot &out);

} /* namespace Nuki */
} /* namespace Gateway */
