/*
 * Bluetooth LE client for one Nuki Smart Lock. See nuki_client.h.
 *
 * The Nuki thread runs every exchange step by step and blocks on k_event bits set by the
 * Bluetooth callbacks. Indications go through sRx to the thread. The scan callback (Bluetooth
 * RX thread) only records the lock's beacon and queues a state read.
 */

#include "nuki_client.h"

#include <bluetooth/gatt_dm.h>
#include <zephyr/bluetooth/bluetooth.h>
#include <zephyr/bluetooth/conn.h>
#include <zephyr/bluetooth/gatt.h>
#include <zephyr/bluetooth/hci.h>
#include <zephyr/bluetooth/uuid.h>
#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>
#include <zephyr/net_buf.h>
#include <zephyr/settings/settings.h>
#include <zephyr/sys/atomic.h>

#include <errno.h>
#include <string.h>

LOG_MODULE_REGISTER(nuki, CONFIG_GATEWAY_NUKI_LOG_LEVEL);

namespace Gateway
{
namespace Nuki
{
namespace
{

/* Pairing service and its General Data Input/Output characteristic (plain messages) */
const bt_uuid_128 kPairingServiceUuid =
	BT_UUID_INIT_128(BT_UUID_128_ENCODE(0xa92ee100, 0x5501, 0x11e4, 0x916c, 0x0800200c9a66));
const bt_uuid_128 kGdioUuid =
	BT_UUID_INIT_128(BT_UUID_128_ENCODE(0xa92ee101, 0x5501, 0x11e4, 0x916c, 0x0800200c9a66));
/* Keyturner service and its User-Specific Data Input/Output characteristic (encrypted messages) */
const bt_uuid_128 kKeyturnerServiceUuid =
	BT_UUID_INIT_128(BT_UUID_128_ENCODE(0xa92ee200, 0x5501, 0x11e4, 0x916c, 0x0800200c9a66));
const bt_uuid_128 kUsdioUuid =
	BT_UUID_INIT_128(BT_UUID_128_ENCODE(0xa92ee202, 0x5501, 0x11e4, 0x916c, 0x0800200c9a66));

constexpr k_timeout_t kConnectTimeout = K_SECONDS(12);
constexpr uint16_t kConnectScanTimeout10ms = 1000; /* 10 s to find the lock's advertisement */
constexpr k_timeout_t kStepTimeout = K_SECONDS(5); /* MTU, discovery, subscribe, write */
constexpr k_timeout_t kReplyTimeout = K_SECONDS(10);
constexpr k_timeout_t kActionTimeout = K_SECONDS(30); /* accepted -> complete: the motor runs */
constexpr k_timeout_t kDisconnectTimeout = K_SECONDS(10); /* > the 4 s supervision timeout */
constexpr k_timeout_t kRetryDelay = K_SECONDS(1);

constexpr uint8_t kCredVersion = 1;
constexpr const char *kCredKey = "nuki/cred";

#if defined(CONFIG_GATEWAY_NUKI_ID_TYPE_BRIDGE)
constexpr uint8_t kIdType = NUKI_ID_TYPE_BRIDGE;
#else
constexpr uint8_t kIdType = NUKI_ID_TYPE_APP;
#endif

enum class RequestType : uint8_t { Pair, LockAction, RefreshState, RefreshInfo };

struct Request {
	RequestType mType;
	uint8_t mArg;
};

K_MSGQ_DEFINE(sRequests, sizeof(Request), 6, 4);

/* An indication, or a zero-length entry for "disconnected" */
struct RxMsg {
	uint16_t mLen;
	uint8_t mData[NUKI_MAX_MSG_LEN];
};

K_MSGQ_DEFINE(sRx, sizeof(RxMsg), 4, 4);

enum Event : uint32_t {
	kEvtConnected = BIT(0),
	kEvtConnectFailed = BIT(1),
	kEvtDisconnected = BIT(2),
	kEvtMtuDone = BIT(3),
	kEvtDiscovered = BIT(4),
	kEvtFailed = BIT(5), /* discovery, subscribe or write failed */
	kEvtSubscribed = BIT(6),
	kEvtWritten = BIT(7),
	kEvtPairingFound = BIT(8),
	kEvtAll = 0x1FF,
};

K_EVENT_DEFINE(sEvents);

struct StoredCred {
	uint8_t mVersion;
	bt_addr_le_t mAddr;
	uint32_t mAuthId;
	uint8_t mKey[NUKI_KEY_LEN];
};

Callbacks sCallbacks;

K_THREAD_STACK_DEFINE(sStack, CONFIG_GATEWAY_NUKI_STACK_SIZE);
k_thread sThread;

/* Shared with the shell (GetSnapshot) and the scan callback; guarded by sLock. */
k_spinlock sLock;
Snapshot sSnap;
bool sSearching; /* scan callback: report a lock in pairing mode */
bt_addr_le_t sFoundAddr;
bool sBeaconFlag; /* last state-changed bit of the beacon */
bool sUltraWarned;

/* Nuki thread only */
StoredCred sCred;
bool sScanning;
bool sScanActive;
bt_conn *sConn;
uint16_t sValueHandle;
bt_gatt_subscribe_params sSubscribeParams;
bt_gatt_exchange_params sMtuParams;
bt_gatt_write_params sWriteParams;
uint8_t sTx[NUKI_MAX_MSG_LEN];
const bt_uuid *sWantedChar;
atomic_t sStateQueued; /* a RefreshState is waiting in sRequests */

/* --- Bluetooth callbacks (Bluetooth RX thread / GATT DM) ---------------------------------------------------- */

void OnConnected(bt_conn *conn, uint8_t err)
{
	if (conn != sConn) {
		return;
	}
	if (err) {
		LOG_INF("Connect failed (HCI 0x%02x)", err);
	}
	k_event_post(&sEvents, err ? kEvtConnectFailed : kEvtConnected);
}

void OnDisconnected(bt_conn *conn, uint8_t reason)
{
	if (conn != sConn) {
		return;
	}
	/* 0x08 supervision timeout and 0x3e "failed to establish" point to range; 0x13: the lock closed it. */
	LOG_INF("Disconnected (reason 0x%02x)", reason);

	/* Wakes a thread waiting for a reply. */
	static RxMsg sMarker;

	sMarker.mLen = 0;
	k_msgq_put(&sRx, &sMarker, K_NO_WAIT);
	k_event_post(&sEvents, kEvtDisconnected);
}

BT_CONN_CB_DEFINE(nuki_conn_callbacks) = {
	.connected = OnConnected,
	.disconnected = OnDisconnected,
};

void OnMtu(bt_conn *, uint8_t err, bt_gatt_exchange_params *)
{
	if (err) {
		LOG_WRN("MTU exchange failed (ATT 0x%02x)", err);
	}
	k_event_post(&sEvents, kEvtMtuDone);
}

void OnDiscoveryCompleted(bt_gatt_dm *dm, void *)
{
	const bt_gatt_dm_attr *chr = bt_gatt_dm_char_by_uuid(dm, sWantedChar);
	const bt_gatt_dm_attr *value = chr ? bt_gatt_dm_desc_by_uuid(dm, chr, sWantedChar) : nullptr;
	const bt_gatt_dm_attr *ccc = chr ? bt_gatt_dm_desc_by_uuid(dm, chr, BT_UUID_GATT_CCC) : nullptr;

	if (value && ccc) {
		sValueHandle = value->handle;
		sSubscribeParams.value_handle = value->handle;
		sSubscribeParams.ccc_handle = ccc->handle;
	}
	bt_gatt_dm_data_release(dm);

	if (value && ccc) {
		k_event_post(&sEvents, kEvtDiscovered);
	} else {
		LOG_WRN("Nuki characteristic not found");
		k_event_post(&sEvents, kEvtFailed);
	}
}

void OnServiceNotFound(bt_conn *, void *)
{
	LOG_WRN("Nuki service not found");
	k_event_post(&sEvents, kEvtFailed);
}

void OnDiscoveryError(bt_conn *, int err, void *)
{
	LOG_WRN("Discovery failed (%d)", err);
	k_event_post(&sEvents, kEvtFailed);
}

const bt_gatt_dm_cb kDiscoveryCallbacks = {
	.completed = OnDiscoveryCompleted,
	.service_not_found = OnServiceNotFound,
	.error_found = OnDiscoveryError,
};

uint8_t OnIndication(bt_conn *, bt_gatt_subscribe_params *, const void *data, uint16_t length)
{
	if (!data) {
		return BT_GATT_ITER_STOP; /* unsubscribed */
	}
	if (length == 0 || length > NUKI_MAX_MSG_LEN) {
		LOG_WRN("Dropped indication of %u bytes", length);
		return BT_GATT_ITER_CONTINUE;
	}

	static RxMsg sMsg; /* one Bluetooth RX thread: no concurrent use */

	sMsg.mLen = length;
	memcpy(sMsg.mData, data, length);
	if (k_msgq_put(&sRx, &sMsg, K_NO_WAIT) != 0) {
		LOG_WRN("Receive queue full, indication dropped");
	}
	return BT_GATT_ITER_CONTINUE;
}

void OnSubscribed(bt_conn *, uint8_t err, bt_gatt_subscribe_params *)
{
	if (err) {
		LOG_WRN("Subscribe failed (ATT 0x%02x)", err);
	}
	k_event_post(&sEvents, err ? kEvtFailed : kEvtSubscribed);
}

void OnWritten(bt_conn *, uint8_t err, bt_gatt_write_params *)
{
	if (err) {
		LOG_WRN("Write failed (ATT 0x%02x)", err);
	}
	k_event_post(&sEvents, err ? kEvtFailed : kEvtWritten);
}

bool QueueStateRead();

void OnScanRecv(const bt_le_scan_recv_info *info, net_buf_simple *buf)
{
	nuki_adv adv;

	nuki_adv_parse(buf->data, buf->len, &adv);
	if (adv.kind == NUKI_ADV_OTHER) {
		return;
	}

	bool readState = false;
	bool pairingFound = false;
	bool ultraFound = false;
	k_spinlock_key_t key = k_spin_lock(&sLock);

	if (adv.kind == NUKI_ADV_PAIRING && sSearching) {
		sSearching = false;
		bt_addr_le_copy(&sFoundAddr, info->addr);
		pairingFound = true;
	} else if (adv.kind == NUKI_ADV_PAIRING_ULTRA && sSearching && !sUltraWarned) {
		sUltraWarned = true;
		ultraFound = true;
	} else if (adv.kind == NUKI_ADV_BEACON && sSnap.mPaired && bt_addr_le_eq(info->addr, &sSnap.mAddr)) {
		sSnap.mRssi = info->rssi;
		sSnap.mLastBeaconMs = k_uptime_get();
		/* The flag stays set until the state has been read; react once per change. */
		readState = adv.state_changed && !sBeaconFlag;
		sBeaconFlag = adv.state_changed;
	}
	k_spin_unlock(&sLock, key);

	/* Kernel calls and logging outside the spinlock */
	if (pairingFound) {
		k_event_post(&sEvents, kEvtPairingFound);
	}
	if (ultraFound) {
		LOG_WRN("A Smart Lock Ultra / 5th generation is in pairing mode: not supported (PIN pairing)");
	}
	if (readState) {
		LOG_DBG("Beacon: new state");
		QueueStateRead();
	}
}

bt_le_scan_cb sScanCallbacks = {
	.recv = OnScanRecv,
};

/* --- Requests ------------------------------------------------------------------------------------------------ */

int Queue(RequestType type, uint8_t arg = 0)
{
	const Request request{ type, arg };

	return k_msgq_put(&sRequests, &request, K_NO_WAIT) == 0 ? 0 : -ENOMEM;
}

bool QueueStateRead()
{
	if (atomic_set(&sStateQueued, 1)) {
		return true; /* one is already waiting */
	}
	if (Queue(RequestType::RefreshState) != 0) {
		atomic_clear(&sStateQueued);
		return false;
	}
	return true;
}

bool IsPaired()
{
	k_spinlock_key_t key = k_spin_lock(&sLock);
	const bool paired = sSnap.mPaired;

	k_spin_unlock(&sLock, key);
	return paired;
}

/* --- Credentials --------------------------------------------------------------------------------------------- */

int LoadCred(const char *key, size_t len, settings_read_cb read, void *cbArg, void *)
{
	if (strcmp(key, "cred") == 0 && len == sizeof(StoredCred)) {
		StoredCred cred;

		if (read(cbArg, &cred, sizeof(cred)) == sizeof(cred) && cred.mVersion == kCredVersion) {
			sCred = cred;
		}
	}
	return 0;
}

void PublishPaired(bool paired)
{
	k_spinlock_key_t key = k_spin_lock(&sLock);

	sSnap.mPaired = paired;
	if (paired) {
		bt_addr_le_copy(&sSnap.mAddr, &sCred.mAddr);
		sSnap.mAuthId = sCred.mAuthId;
	} else {
		sSnap.mHaveState = false;
		sSnap.mHaveInfo = false;
		sSnap.mLastBeaconMs = 0;
	}
	sBeaconFlag = false;
	k_spin_unlock(&sLock, key);
}

/* --- Scanning (Nuki thread) ---------------------------------------------------------------------------------- */

void ScanStop()
{
	if (sScanning) {
		const int err = bt_le_scan_stop();

		if (err && err != -EALREADY) {
			LOG_WRN("Scan stop failed (%d)", err);
		}
		sScanning = false;
	}
}

/* Active: while searching a lock in pairing mode (its service data may sit in the scan response). */
void ScanStart(bool active)
{
	if (sScanning && sScanActive == active) {
		return;
	}
	ScanStop();

	const bt_le_scan_param param = {
		.type = active ? BT_LE_SCAN_TYPE_ACTIVE : BT_LE_SCAN_TYPE_PASSIVE,
		/* No duplicate filter: the beacon's state bit changes without other changes. */
		.options = BT_LE_SCAN_OPT_NONE,
		.interval = CONFIG_GATEWAY_NUKI_SCAN_INTERVAL,
		.window = CONFIG_GATEWAY_NUKI_SCAN_WINDOW,
	};
	const int err = bt_le_scan_start(&param, nullptr);

	if (err) {
		LOG_WRN("Scan start failed (%d)", err);
		return;
	}
	sScanning = true;
	sScanActive = active;
}

/* --- Connection (Nuki thread) -------------------------------------------------------------------------------- */

bool Wait(uint32_t events, k_timeout_t timeout, uint32_t *got = nullptr)
{
	const uint32_t e = k_event_wait(&sEvents, events, false, timeout);

	if (got) {
		*got = e;
	}
	return e != 0;
}

/*
 * Ends the connection and releases it once the host reports it gone. Returns false if it is still
 * alive after kDisconnectTimeout: then sConn is kept, and so are sSubscribeParams, which the host
 * keeps in its subscription list until the disconnect. Reusing them earlier corrupts that list.
 */
bool Disconnect()
{
	/* Set when the connection is gone. A connection cancelled while still being created ends
	 * with a failed connect, not a disconnect. */
	constexpr uint32_t kGone = kEvtDisconnected | kEvtConnectFailed;

	if (!sConn) {
		return true;
	}
	if (!k_event_test(&sEvents, kGone)) {
		const int err = bt_conn_disconnect(sConn, BT_HCI_ERR_REMOTE_USER_TERM_CONN);

		if (err && err != -ENOTCONN) {
			LOG_WRN("Disconnect failed (%d)", err);
		}
		/* If the lock doesn't answer, the link ends with the supervision timeout (4 s). */
		if (!Wait(kGone, kDisconnectTimeout)) {
			LOG_ERR("Connection still not closed");
			return false;
		}
	}
	bt_conn_unref(sConn);
	sConn = nullptr;
	return true;
}

Result Connect(const bt_addr_le_t &addr, const bt_uuid *service, const bt_uuid *characteristic)
{
	char text[BT_ADDR_LE_STR_LEN];
	uint32_t got;

	bt_addr_le_to_str(&addr, text, sizeof(text));
	LOG_DBG("Connecting to %s", text);

	/* The previous connection must be gone (see Disconnect). */
	if (!Disconnect()) {
		return Result::ConnectFailed;
	}

	/* The Bluetooth host creates no connection while a scan runs. */
	ScanStop();
	k_event_clear(&sEvents, kEvtAll);
	k_msgq_purge(&sRx);
	memset(&sSubscribeParams, 0, sizeof(sSubscribeParams));
	sWantedChar = characteristic;

	/* 50 % duty while connecting leaves Thread its share of the radio. */
	bt_conn_le_create_param createParam = BT_CONN_LE_CREATE_PARAM_INIT(
		BT_CONN_LE_OPT_NONE, BT_GAP_SCAN_FAST_INTERVAL, BT_GAP_SCAN_FAST_WINDOW);
	createParam.timeout = kConnectScanTimeout10ms;
	/* 30..50 ms interval, no latency, 4 s supervision timeout */
	const bt_le_conn_param connParam = BT_LE_CONN_PARAM_INIT(24, 40, 0, 400);

	int err = bt_conn_le_create(&addr, &createParam, &connParam, &sConn);

	if (err) {
		LOG_WRN("Connection create failed (%d)", err);
		sConn = nullptr;
		return Result::ConnectFailed;
	}
	if (!Wait(kEvtConnected | kEvtConnectFailed, kConnectTimeout, &got) || (got & kEvtConnectFailed)) {
		LOG_INF("Lock %s not reached", text);
		Disconnect();
		return Result::ConnectFailed;
	}

	/* Nuki messages are longer than the default 20 bytes per write. */
	sMtuParams.func = OnMtu;
	err = bt_gatt_exchange_mtu(sConn, &sMtuParams);
	if (err == 0) {
		Wait(kEvtMtuDone | kEvtDisconnected, kStepTimeout);
	} else if (err != -EALREADY) {
		LOG_WRN("MTU exchange start failed (%d)", err);
	}
	if (k_event_test(&sEvents, kEvtDisconnected)) {
		Disconnect();
		return Result::Disconnected;
	}
	LOG_DBG("ATT MTU %u", bt_gatt_get_mtu(sConn));

	err = bt_gatt_dm_start(sConn, service, &kDiscoveryCallbacks, nullptr);
	if (err) {
		LOG_WRN("Discovery start failed (%d)", err);
		Disconnect();
		return err == -ENOTCONN ? Result::Disconnected : Result::Protocol;
	}
	if (!Wait(kEvtDiscovered | kEvtFailed | kEvtDisconnected, kStepTimeout, &got) || !(got & kEvtDiscovered)) {
		Disconnect();
		return got & kEvtDisconnected ? Result::Disconnected : Result::Protocol;
	}

	sSubscribeParams.notify = OnIndication;
	sSubscribeParams.subscribe = OnSubscribed;
	sSubscribeParams.value = BT_GATT_CCC_INDICATE;
	err = bt_gatt_subscribe(sConn, &sSubscribeParams);
	if (err) {
		LOG_WRN("Subscribe start failed (%d)", err);
		Disconnect();
		return Result::Protocol;
	}
	if (!Wait(kEvtSubscribed | kEvtFailed | kEvtDisconnected, kStepTimeout, &got) || !(got & kEvtSubscribed)) {
		Disconnect();
		return got & kEvtDisconnected ? Result::Disconnected : Result::Protocol;
	}
	return Result::Ok;
}

Result Write(size_t len)
{
	uint32_t got;

	k_event_clear(&sEvents, kEvtWritten | kEvtFailed);
	sWriteParams.func = OnWritten;
	sWriteParams.handle = sValueHandle;
	sWriteParams.offset = 0;
	sWriteParams.data = sTx;
	sWriteParams.length = uint16_t(len);

	const int err = bt_gatt_write(sConn, &sWriteParams);

	if (err) {
		LOG_WRN("Write start failed (%d)", err);
		return Result::Protocol;
	}
	if (!Wait(kEvtWritten | kEvtFailed | kEvtDisconnected, kStepTimeout, &got)) {
		return Result::Timeout;
	}
	if (got & kEvtWritten) {
		return Result::Ok;
	}
	return got & kEvtDisconnected ? Result::Disconnected : Result::Protocol;
}

/* --- Messages (Nuki thread) ---------------------------------------------------------------------------------- */

struct Message {
	uint16_t mCmd;
	size_t mLen;
	uint8_t mPayload[NUKI_MAX_PAYLOAD_LEN];
};

Result SendPlain(uint16_t cmd, const uint8_t *payload, size_t len)
{
	const size_t n = nuki_plain_build(sTx, sizeof(sTx), cmd, payload, len);

	return n ? Write(n) : Result::Protocol;
}

Result SendEncrypted(uint16_t cmd, const uint8_t *payload, size_t len)
{
	const size_t n = nuki_encrypted_build(sTx, sizeof(sTx), sCred.mKey, sCred.mAuthId, cmd, payload, len);

	return n ? Write(n) : Result::Protocol;
}

void RecordError(const Message &msg)
{
	uint8_t error;
	uint16_t cmd;

	if (nuki_parse_error(msg.mPayload, msg.mLen, &error, &cmd) != 0) {
		error = NUKI_ERROR_UNKNOWN;
		cmd = 0;
	}
	LOG_WRN("Lock reports error 0x%02x (%s) for command 0x%04x", error, nuki_error_str(error), cmd);

	k_spinlock_key_t key = k_spin_lock(&sLock);

	sSnap.mLastError = error;
	k_spin_unlock(&sLock, key);
}

/* Next message from the lock. An Error Report is returned as Result::LockError (and recorded). */
Result Receive(Message &msg, bool encrypted, k_timeout_t timeout)
{
	static RxMsg sIn; /* Nuki thread only; too large for its stack next to Message */
	const k_timepoint_t end = sys_timepoint_calc(timeout);

	for (;;) {
		if (k_msgq_get(&sRx, &sIn, sys_timepoint_timeout(end)) != 0) {
			LOG_WRN("No reply from the lock");
			return Result::Timeout;
		}
		if (sIn.mLen == 0) {
			LOG_WRN("Lock disconnected");
			return Result::Disconnected;
		}

		int err;

		if (encrypted) {
			uint32_t authId;

			err = nuki_encrypted_parse(sIn.mData, sIn.mLen, sCred.mKey, &authId, &msg.mCmd, msg.mPayload,
						   sizeof(msg.mPayload), &msg.mLen);
		} else {
			const uint8_t *payload;

			err = nuki_plain_parse(sIn.mData, sIn.mLen, &msg.mCmd, &payload, &msg.mLen);
			if (err == 0) {
				msg.mLen = MIN(msg.mLen, sizeof(msg.mPayload));
				memcpy(msg.mPayload, payload, msg.mLen);
			}
		}
		if (err) {
			/* A plain Error Report can also come on the encrypted channel (e.g. a bad auth ID). */
			const uint8_t *payload;

			if (encrypted && nuki_plain_parse(sIn.mData, sIn.mLen, &msg.mCmd, &payload, &msg.mLen) == 0 &&
			    msg.mCmd == NUKI_CMD_ERROR_REPORT) {
				msg.mLen = MIN(msg.mLen, sizeof(msg.mPayload));
				memcpy(msg.mPayload, payload, msg.mLen);
			} else {
				LOG_WRN("Dropped a message of %u bytes (error %d)", sIn.mLen, err);
				continue;
			}
		}
		LOG_DBG("Received command 0x%04x, %u bytes", msg.mCmd, msg.mLen);
		if (msg.mCmd == NUKI_CMD_ERROR_REPORT) {
			RecordError(msg);
			return Result::LockError;
		}
		return Result::Ok;
	}
}

/* Waits for a given command; others are logged and skipped. */
Result Expect(Message &msg, uint16_t cmd, size_t minLen, bool encrypted, k_timeout_t timeout = kReplyTimeout)
{
	const k_timepoint_t end = sys_timepoint_calc(timeout);

	for (;;) {
		const Result r = Receive(msg, encrypted, sys_timepoint_timeout(end));

		if (r != Result::Ok) {
			return r;
		}
		if (msg.mCmd == cmd) {
			if (msg.mLen < minLen) {
				LOG_WRN("Command 0x%04x too short (%u bytes)", cmd, msg.mLen);
				return Result::Protocol;
			}
			return Result::Ok;
		}
		LOG_INF("Skipped command 0x%04x while waiting for 0x%04x", msg.mCmd, cmd);
	}
}

/* --- Exchanges (Nuki thread) --------------------------------------------------------------------------------- */

#define TRY(expr)                                                                                                  \
	do {                                                                                                       \
		const Result _r = (expr);                                                                          \
		if (_r != Result::Ok) {                                                                            \
			return _r;                                                                                 \
		}                                                                                                  \
	} while (0)

void PublishState(const nuki_keyturner_state &state)
{
	k_spinlock_key_t key = k_spin_lock(&sLock);

	sSnap.mState = state;
	sSnap.mHaveState = true;
	sSnap.mStateMs = k_uptime_get();
	k_spin_unlock(&sLock, key);

	LOG_INF("State: %s, door 0x%02x, battery %u %%%s", nuki_lock_state_str(state.lock_state), state.door_state,
		nuki_battery_percent(state.battery_raw), nuki_battery_critical(state.battery_raw) ? " (critical)" : "");
	if (sCallbacks.mState) {
		sCallbacks.mState(state);
	}
}

/* Request Data for the keyturner states, then publish them (on an open connection). */
Result ReadState(Message &msg)
{
	const uint8_t request[] = { NUKI_CMD_KEYTURNER_STATES & 0xFF, NUKI_CMD_KEYTURNER_STATES >> 8 };
	nuki_keyturner_state state;

	TRY(SendEncrypted(NUKI_CMD_REQUEST_DATA, request, sizeof(request)));
	TRY(Expect(msg, NUKI_CMD_KEYTURNER_STATES, 0, true));
	if (nuki_parse_keyturner_state(msg.mPayload, msg.mLen, &state) != 0) {
		LOG_WRN("Keyturner states too short (%u bytes)", msg.mLen);
		return Result::Protocol;
	}
	PublishState(state);
	return Result::Ok;
}

/* Request Data for a challenge: the nonce that the next command must carry. */
Result Challenge(Message &msg, uint8_t nonce[NUKI_CHALLENGE_LEN])
{
	const uint8_t request[] = { NUKI_CMD_CHALLENGE & 0xFF, NUKI_CMD_CHALLENGE >> 8 };

	TRY(SendEncrypted(NUKI_CMD_REQUEST_DATA, request, sizeof(request)));
	TRY(Expect(msg, NUKI_CMD_CHALLENGE, NUKI_CHALLENGE_LEN, true));
	memcpy(nonce, msg.mPayload, NUKI_CHALLENGE_LEN);
	return Result::Ok;
}

Result DoRefreshState(Message &msg)
{
	TRY(Connect(sCred.mAddr, &kKeyturnerServiceUuid.uuid, &kUsdioUuid.uuid));
	const Result r = ReadState(msg);

	Disconnect();
	return r;
}

Result DoRefreshInfoOnce(Message &msg)
{
	uint8_t nonce[NUKI_CHALLENGE_LEN];
	nuki_config config;

	TRY(Challenge(msg, nonce));
	TRY(SendEncrypted(NUKI_CMD_REQUEST_CONFIG, nonce, sizeof(nonce)));
	TRY(Expect(msg, NUKI_CMD_CONFIG, 0, true));
	if (nuki_parse_config(msg.mPayload, msg.mLen, &config) != 0) {
		LOG_WRN("Config too short (%u bytes)", msg.mLen);
		return Result::Protocol;
	}

	k_spinlock_key_t key = k_spin_lock(&sLock);

	sSnap.mInfo = config;
	sSnap.mHaveInfo = true;
	k_spin_unlock(&sLock, key);

	LOG_INF("Lock '%s', Nuki ID %08X, firmware %u.%u.%u, hardware %u.%u", config.name, config.nuki_id,
		config.firmware[0], config.firmware[1], config.firmware[2], config.hardware[0], config.hardware[1]);
	if (sCallbacks.mInfo) {
		sCallbacks.mInfo(config);
	}
	return Result::Ok;
}

Result DoRefreshInfo(Message &msg)
{
	TRY(Connect(sCred.mAddr, &kKeyturnerServiceUuid.uuid, &kUsdioUuid.uuid));
	const Result r = DoRefreshInfoOnce(msg);

	Disconnect();
	return r;
}

Result DoLockActionOnce(Message &msg, uint8_t action)
{
	uint8_t nonce[NUKI_CHALLENGE_LEN];

	TRY(Challenge(msg, nonce));

	/* Lock Action: action | app ID | flags | nonce */
	uint8_t payload[1 + 4 + 1 + NUKI_CHALLENGE_LEN];
	const uint32_t appId = CONFIG_GATEWAY_NUKI_APP_ID;

	payload[0] = action;
	payload[1] = uint8_t(appId);
	payload[2] = uint8_t(appId >> 8);
	payload[3] = uint8_t(appId >> 16);
	payload[4] = uint8_t(appId >> 24);
	payload[5] = 0;
	memcpy(&payload[6], nonce, sizeof(nonce));
	TRY(SendEncrypted(NUKI_CMD_LOCK_ACTION, payload, sizeof(payload)));

	/* Status Accepted, then (keyturner states while the motor runs, and) Status Complete. */
	const k_timepoint_t end = sys_timepoint_calc(kActionTimeout);

	for (;;) {
		TRY(Receive(msg, true, sys_timepoint_timeout(end)));
		if (msg.mCmd == NUKI_CMD_STATUS && msg.mLen >= 1) {
			if (msg.mPayload[0] == NUKI_STATUS_COMPLETE) {
				break;
			}
			LOG_DBG("Lock action accepted");
		} else if (msg.mCmd == NUKI_CMD_KEYTURNER_STATES) {
			nuki_keyturner_state state;

			if (nuki_parse_keyturner_state(msg.mPayload, msg.mLen, &state) == 0) {
				PublishState(state);
			}
		} else {
			LOG_INF("Skipped command 0x%04x during the lock action", msg.mCmd);
		}
	}
	LOG_INF("Lock action 0x%02x complete", action);

	/* The final state, on the same connection. Failing here doesn't fail the action. */
	if (ReadState(msg) != Result::Ok) {
		QueueStateRead();
	}
	return Result::Ok;
}

Result DoLockAction(Message &msg, uint8_t action)
{
	TRY(Connect(sCred.mAddr, &kKeyturnerServiceUuid.uuid, &kUsdioUuid.uuid));
	const Result r = DoLockActionOnce(msg, action);

	Disconnect();
	return r;
}

/* Looks for a lock in pairing mode (button held 5 s). */
Result SearchPairingLock(bt_addr_le_t &addr)
{
	k_spinlock_key_t key = k_spin_lock(&sLock);

	sSearching = true;
	sSnap.mSearching = true;
	sUltraWarned = false;
	k_spin_unlock(&sLock, key);

	LOG_INF("Looking for a Nuki in pairing mode for %d s (hold its button for 5 s)",
		CONFIG_GATEWAY_NUKI_PAIRING_SEARCH_S);
	k_event_clear(&sEvents, kEvtPairingFound);
	ScanStart(true);

	const bool found = Wait(kEvtPairingFound, K_SECONDS(CONFIG_GATEWAY_NUKI_PAIRING_SEARCH_S));

	ScanStop();
	key = k_spin_lock(&sLock);
	sSearching = false;
	sSnap.mSearching = false;
	bt_addr_le_copy(&addr, &sFoundAddr);
	k_spin_unlock(&sLock, key);

	if (!found) {
		LOG_WRN("No Nuki in pairing mode found");
		return Result::NotFound;
	}

	char text[BT_ADDR_LE_STR_LEN];

	bt_addr_le_to_str(&addr, text, sizeof(text));
	LOG_INF("Nuki in pairing mode: %s", text);
	return Result::Ok;
}

Result PairExchange(Message &msg, const uint8_t ownPk[NUKI_KEY_LEN], const uint8_t ownSk[NUKI_KEY_LEN],
		    StoredCred &cred)
{
	uint8_t lockPk[NUKI_KEY_LEN];
	uint8_t buf[NUKI_AUTH_DATA_LEN];
	uint8_t nonce[32];

	/* Request the lock's public key, send ours */
	const uint8_t request[] = { NUKI_CMD_PUBLIC_KEY & 0xFF, NUKI_CMD_PUBLIC_KEY >> 8 };

	TRY(SendPlain(NUKI_CMD_REQUEST_DATA, request, sizeof(request)));
	TRY(Expect(msg, NUKI_CMD_PUBLIC_KEY, NUKI_KEY_LEN, false));
	memcpy(lockPk, msg.mPayload, NUKI_KEY_LEN);
	TRY(SendPlain(NUKI_CMD_PUBLIC_KEY, ownPk, NUKI_KEY_LEN));

	/* The lock answers with a challenge; meanwhile derive the key. */
	nuki_shared_key(cred.mKey, ownSk, lockPk);

	TRY(Expect(msg, NUKI_CMD_CHALLENGE, NUKI_CHALLENGE_LEN, false));
	nuki_pair_authenticator(buf, cred.mKey, ownPk, lockPk, msg.mPayload);
	TRY(SendPlain(NUKI_CMD_AUTH_AUTHENTICATOR, buf, 32));

	TRY(Expect(msg, NUKI_CMD_CHALLENGE, NUKI_CHALLENGE_LEN, false));
	randombytes(nonce, sizeof(nonce));
	nuki_pair_auth_data(buf, cred.mKey, kIdType, CONFIG_GATEWAY_NUKI_APP_ID, CONFIG_GATEWAY_NUKI_NAME, nonce,
			    msg.mPayload);
	TRY(SendPlain(NUKI_CMD_AUTH_DATA, buf, NUKI_AUTH_DATA_LEN));

	nuki_auth_id id;

	TRY(Expect(msg, NUKI_CMD_AUTH_ID, 0, false));
	if (nuki_parse_auth_id(msg.mPayload, msg.mLen, &id) != 0) {
		LOG_WRN("Authorization ID too short (%u bytes)", msg.mLen);
		return Result::Protocol;
	}
	nuki_pair_auth_id_confirm(buf, cred.mKey, id.auth_id, id.nonce);
	TRY(SendPlain(NUKI_CMD_AUTH_ID_CONFIRMATION, buf, NUKI_AUTH_ID_CONFIRM_LEN));

	TRY(Expect(msg, NUKI_CMD_STATUS, 1, false));
	if (msg.mPayload[0] != NUKI_STATUS_COMPLETE) {
		LOG_WRN("Pairing ended with status 0x%02x", msg.mPayload[0]);
		return Result::Protocol;
	}
	cred.mAuthId = id.auth_id;
	return Result::Ok;
}

Result DoPair(Message &msg)
{
	if (IsPaired()) {
		LOG_INF("Already paired");
		return Result::Ok;
	}

	bt_addr_le_t addr;

	TRY(SearchPairingLock(addr));

	uint8_t pk[NUKI_KEY_LEN];
	uint8_t sk[NUKI_KEY_LEN];
	StoredCred cred = {};
	const int64_t start = k_uptime_get();

	nuki_keypair(pk, sk);
	LOG_INF("Key pair in %lld ms", k_uptime_get() - start);

	Result r = Connect(addr, &kPairingServiceUuid.uuid, &kGdioUuid.uuid);

	if (r == Result::Ok) {
		r = PairExchange(msg, pk, sk, cred);
		Disconnect();
	}
	memset(sk, 0, sizeof(sk));

	if (r != Result::Ok) {
		memset(&cred, 0, sizeof(cred));
		return r;
	}

	cred.mVersion = kCredVersion;
	bt_addr_le_copy(&cred.mAddr, &addr);
	const int err = settings_save_one(kCredKey, &cred, sizeof(cred));

	if (err) {
		LOG_ERR("Storing the pairing failed (%d)", err);
	}
	sCred = cred;
	memset(&cred, 0, sizeof(cred));
	PublishPaired(true);
	LOG_INF("Paired, authorization ID %u", sCred.mAuthId);
	if (sCallbacks.mPaired) {
		sCallbacks.mPaired(true);
	}

	/* What the bridge shows first: name, versions and the current state */
	QueueStateRead();
	Queue(RequestType::RefreshInfo);
	return Result::Ok;
}

/* Retries what may fail for radio reasons: not reached, no reply, dropped connection, lock busy. */
bool Retryable(Result r)
{
	if (r == Result::ConnectFailed || r == Result::Timeout || r == Result::Disconnected) {
		return true;
	}
	if (r == Result::LockError) {
		k_spinlock_key_t key = k_spin_lock(&sLock);
		const bool busy = sSnap.mLastError == NUKI_ERROR_BUSY;

		k_spin_unlock(&sLock, key);
		return busy;
	}
	return false;
}

void Handle(const Request &request)
{
	static Message sMsg; /* Nuki thread only */
	Result r = Result::NotPaired;

	if (request.mType == RequestType::RefreshState) {
		atomic_clear(&sStateQueued);
	}

	k_spinlock_key_t key = k_spin_lock(&sLock);

	sSnap.mBusy = true;
	sSnap.mRequests++;
	k_spin_unlock(&sLock, key);

	if (request.mType == RequestType::Pair) {
		r = DoPair(sMsg);
	} else if (IsPaired()) {
		const int attempts = request.mType == RequestType::LockAction ? CONFIG_GATEWAY_NUKI_ACTION_ATTEMPTS : 2;

		for (int attempt = 1; attempt <= attempts; attempt++) {
			switch (request.mType) {
			case RequestType::LockAction:
				r = DoLockAction(sMsg, request.mArg);
				break;
			case RequestType::RefreshState:
				r = DoRefreshState(sMsg);
				break;
			case RequestType::RefreshInfo:
				r = DoRefreshInfo(sMsg);
				break;
			default:
				break;
			}
			if (r == Result::Ok || !Retryable(r) || attempt == attempts) {
				break;
			}
			LOG_INF("Attempt %d failed (%s), retrying", attempt, ResultStr(r));
			k_sleep(kRetryDelay);
		}
	}

	if (r != Result::Ok) {
		LOG_WRN("Request %u failed: %s", unsigned(request.mType), ResultStr(r));
	}
	key = k_spin_lock(&sLock);
	sSnap.mBusy = false;
	sSnap.mLastResult = r;
	if (r != Result::Ok) {
		sSnap.mFailures++;
	}
	k_spin_unlock(&sLock, key);

	if (request.mType == RequestType::LockAction && sCallbacks.mActionDone) {
		sCallbacks.mActionDone(request.mArg, r);
	}
}

void ThreadMain(void *, void *, void *)
{
	const k_timeout_t pollInterval = K_SECONDS(CONFIG_GATEWAY_NUKI_POLL_INTERVAL_S);
	k_timepoint_t nextPoll = sys_timepoint_calc(pollInterval);

	if (IsPaired()) {
		QueueStateRead();
		Queue(RequestType::RefreshInfo);
	}

	for (;;) {
		Request request;

		/* Watch the beacon while idle and paired. */
		if (IsPaired()) {
			ScanStart(false);
		} else {
			ScanStop();
		}

		if (k_msgq_get(&sRequests, &request, sys_timepoint_timeout(nextPoll)) != 0) {
			if (!IsPaired()) {
				nextPoll = sys_timepoint_calc(pollInterval);
				continue;
			}
			request = Request{ RequestType::RefreshState, 0 };
			atomic_set(&sStateQueued, 1);
		}
		Handle(request);
		if (request.mType == RequestType::RefreshState || request.mType == RequestType::LockAction) {
			nextPoll = sys_timepoint_calc(pollInterval);
		}
	}
}

} /* namespace */

const char *ResultStr(Result result)
{
	switch (result) {
	case Result::Ok: return "ok";
	case Result::NotPaired: return "not paired";
	case Result::NotFound: return "no lock in pairing mode";
	case Result::ConnectFailed: return "lock not reached";
	case Result::Timeout: return "timeout";
	case Result::Disconnected: return "disconnected";
	case Result::Protocol: return "protocol error";
	case Result::LockError: return "lock error";
	}
	return "?";
}

int Init(const Callbacks &callbacks)
{
	sCallbacks = callbacks;

	const int err = settings_load_subtree_direct("nuki", LoadCred, nullptr);

	if (err) {
		LOG_WRN("Loading the pairing failed (%d)", err);
	}
	if (sCred.mVersion == kCredVersion) {
		char text[BT_ADDR_LE_STR_LEN];

		bt_addr_le_to_str(&sCred.mAddr, text, sizeof(text));
		LOG_INF("Paired with %s, authorization ID %u", text, sCred.mAuthId);
		PublishPaired(true);
	} else {
		LOG_INF("Not paired: `nuki pair`, then hold the lock's button for 5 s");
	}

	bt_le_scan_cb_register(&sScanCallbacks);
	k_thread_create(&sThread, sStack, K_THREAD_STACK_SIZEOF(sStack), ThreadMain, nullptr, nullptr, nullptr,
			K_LOWEST_APPLICATION_THREAD_PRIO, 0, K_NO_WAIT);
	k_thread_name_set(&sThread, "nuki");
	return 0;
}

int Pair()
{
	if (IsPaired()) {
		return -EALREADY;
	}
	return Queue(RequestType::Pair);
}

int LockAction(uint8_t action)
{
	if (!IsPaired()) {
		return -EPERM;
	}
	return Queue(RequestType::LockAction, action);
}

int RefreshState()
{
	if (!IsPaired()) {
		return -EPERM;
	}
	return QueueStateRead() ? 0 : -ENOMEM;
}

int RefreshInfo()
{
	if (!IsPaired()) {
		return -EPERM;
	}
	return Queue(RequestType::RefreshInfo);
}

void Unpair()
{
	/* The thread reads sCred only while paired; after this it treats requests as "not paired". */
	PublishPaired(false);
	settings_delete(kCredKey);
	LOG_INF("Pairing removed. Also remove the authorization '%s' in the Nuki app.", CONFIG_GATEWAY_NUKI_NAME);
	if (sCallbacks.mPaired) {
		sCallbacks.mPaired(false);
	}
}

void GetSnapshot(Snapshot &out)
{
	k_spinlock_key_t key = k_spin_lock(&sLock);

	out = sSnap;
	k_spin_unlock(&sLock, key);
}

} /* namespace Nuki */
} /* namespace Gateway */
