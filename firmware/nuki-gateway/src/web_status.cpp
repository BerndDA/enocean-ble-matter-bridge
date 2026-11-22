/*
 * Status JSON of the Nuki gateway for the web page (src/web/index.html). See web_status.h.
 */

#include "web_status.h"

#include "bridge_manager.h"
#include "door_lock_device.h"
#include "nuki_client.h"
#include "nuki_matter.h"
#include "web/status_json.h"

#include <zephyr/bluetooth/addr.h>
#include <zephyr/kernel.h>

#include <stdio.h>

using Gateway::Web::Json;
namespace Nuki = Gateway::Nuki;

namespace
{

/* Matter thread: the endpoints are only touched there. */
void WriteEndpoint(Json &j, chip::EndpointId endpoint)
{
	uint8_t index;
	auto *device = static_cast<DoorLockDevice *>(Nrf::BridgeManager::Instance().GetDevice(endpoint, index));

	if (!device) {
		return;
	}
	j.Open(nullptr, '{');
	j.Int("endpoint", endpoint);
	j.Str("name", device->GetNodeLabel());
	j.Str("role", device->GetRole() == DoorLockDevice::Role::Lock ? "lock" : "opener");
	j.Bool("reachable", device->GetIsReachable());
	switch (device->GetLockState()) {
	case 0: j.Str("state", "not fully locked"); break;
	case 1: j.Str("state", "locked"); break;
	case 2: j.Str("state", "unlocked"); break;
	case 3: j.Str("state", "unlatched"); break;
	default: j.Null("state"); break;
	}
	j.Close('}');
}

void WriteNuki(Json &j)
{
	Nuki::Snapshot s;
	const int64_t now = k_uptime_get();
	char text[BT_ADDR_LE_STR_LEN];

	Nuki::GetSnapshot(s);
	j.Open("nuki", '{');
	j.Bool("paired", s.mPaired);
	j.Bool("searching", s.mSearching);
	j.Bool("busy", s.mBusy);
	if (s.mPaired) {
		bt_addr_le_to_str(&s.mAddr, text, sizeof(text));
		j.Str("address", text, 17);
		j.Int("authId", s.mAuthId);
	}
	if (s.mLastBeaconMs) {
		j.Int("rssi", s.mRssi);
		j.Int("beaconAgoS", (now - s.mLastBeaconMs) / 1000);
	} else {
		j.Null("rssi");
		j.Null("beaconAgoS");
	}

	if (s.mHaveState) {
		j.Open("lock", '{');
		j.Str("state", nuki_lock_state_str(s.mState.lock_state));
		j.Int("code", s.mState.lock_state);
		j.Str("door", nuki_door_state_str(s.mState.door_state));
		j.Bool("doorSensor", s.mState.door_state != NUKI_DOOR_UNAVAILABLE && s.mState.door_state != NUKI_DOOR_NONE);
		j.Int("battery", nuki_battery_percent(s.mState.battery_raw));
		j.Bool("critical", nuki_battery_critical(s.mState.battery_raw));
		j.Bool("charging", nuki_battery_charging(s.mState.battery_raw));
		j.Int("agoS", (now - s.mStateMs) / 1000);
		j.Close('}');
	} else {
		j.Null("lock");
	}

	if (s.mHaveInfo) {
		j.Open("info", '{');
		j.Str("name", s.mInfo.name);
		snprintf(text, sizeof(text), "%08X", unsigned(s.mInfo.nuki_id));
		j.Str("nukiId", text);
		snprintf(text, sizeof(text), "%u.%u.%u", s.mInfo.firmware[0], s.mInfo.firmware[1], s.mInfo.firmware[2]);
		j.Str("firmware", text);
		snprintf(text, sizeof(text), "%u.%u", s.mInfo.hardware[0], s.mInfo.hardware[1]);
		j.Str("hardware", text);
		j.Close('}');
	} else {
		j.Null("info");
	}

	j.Int("requests", s.mRequests);
	j.Int("failures", s.mFailures);
	j.Str("lastResult", Nuki::ResultStr(s.mLastResult));
	if (s.mLastResult == Nuki::Result::LockError) {
		j.Str("lastError", nuki_error_str(s.mLastError));
	} else {
		j.Null("lastError");
	}
	j.Int("connects", s.mConnects);
	j.Int("connectFailures", s.mConnectFailures);
	if (s.mConnects) {
		snprintf(text, sizeof(text), "0x%02X", s.mLastDisconnectReason);
		j.Str("lastDisconnect", text);
	} else {
		j.Null("lastDisconnect");
	}
	j.Bool("scanning", s.mScanning);
	j.Int("advertisements", s.mAdvertisements);
	j.Int("scanError", s.mScanError);
	j.Str("name", CONFIG_GATEWAY_NUKI_NAME);
	j.Close('}');
}

} /* namespace */

namespace Gateway
{

size_t WriteWebStatus(char *buf, size_t size)
{
	Json j(buf, size);

	j.Open(nullptr, '{');
	Gateway::Web::WriteCommonStatus(j);
	WriteNuki(j);
	/* Front door first, then the opener */
	j.Open("endpoints", '[');
	WriteEndpoint(j, Gateway::NukiMatter::kLockEndpointId);
	WriteEndpoint(j, Gateway::NukiMatter::kOpenerEndpointId);
	j.Close(']');
	j.Close('}');
	return j.Done();
}

} /* namespace Gateway */
