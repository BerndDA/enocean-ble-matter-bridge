/*
 * Nuki-to-Matter-over-Thread gateway.
 * Based on the nRF Connect SDK Matter Bridge application
 * (Copyright (c) 2023 Nordic Semiconductor ASA, LicenseRef-Nordic-5-Clause).
 *
 * The lock appears as two bridged Door Lock endpoints (src/matter/nuki_matter.h) and in the shell (`nuki ...`).
 */

#include "app_task.h"
#include "nuki_client.h"
#include "nuki_matter.h"
#ifdef CONFIG_GATEWAY_IDENTITY_FROM_CHIP_ID
#include "identity/chip_id_identity.h"
#endif
#ifdef CONFIG_GATEWAY_NET_LOG
#include "netlog/net_log.h"
#endif
#ifdef CONFIG_GATEWAY_STATUS_LEDS
#include "status_leds/status_leds.h"
#endif
#ifdef CONFIG_GATEWAY_WEB
#include "web/web_server.h"
#include "web_status.h"
#endif

#include "ota/gateway_ota.h"
#include "app/matter_init.h"
#include "app/task_executor.h"
#include "board/board.h"
#include "bridge_manager.h"
#include "bridge_storage_manager.h"
#include "clusters/identify.h"

#include <zephyr/logging/log.h>

LOG_MODULE_DECLARE(app, CONFIG_CHIP_APP_LOG_LEVEL);

using namespace ::chip;
using namespace ::chip::app;
using namespace ::chip::DeviceLayer;

namespace
{

constexpr EndpointId kBridgeEndpointId = 1;

/* Trigger effect is enabled for the bridge device */
Nrf::Matter::IdentifyCluster sIdentifyCluster(kBridgeEndpointId, true);

#ifndef CONFIG_CHIP_FACTORY_RESET_ERASE_SETTINGS
void AppFactoryResetHandler(const ChipDeviceEvent *event, intptr_t /* unused */)
{
	switch (event->Type) {
	case DeviceEventType::kFactoryReset:
		Nrf::BridgeStorageManager::Instance().FactoryReset();
		break;
	default:
		break;
	}
}
#endif

#ifdef CONFIG_GATEWAY_IDENTITY_FROM_CHIP_ID
Gateway::ChipIdFactoryDataProvider sChipIdFactoryDataProvider;
#endif

#ifdef CONFIG_GATEWAY_STATUS_LEDS
/* The lock beacons every few seconds; this long without one means it's out of reach. */
constexpr int64_t kBeaconLostMs = 60 * 1000;

/*
 * PWR (red):  on               paired, the lock is heard and the last request went through
 *             fast blink       looking for a lock in pairing mode (`nuki pair`)
 *             slow even blink  paired, but the lock isn't reached (no beacon for 60 s,
 *                              or the last request failed to connect)
 *             short flash      not paired
 * RX (yellow) is on while a connection to the lock is open (nuki_matter.cpp).
 */
Gateway::StatusLeds::Pwr PwrPattern()
{
	using Gateway::StatusLeds::Pwr;
	using Gateway::Nuki::Result;
	Gateway::Nuki::Snapshot s;

	Gateway::Nuki::GetSnapshot(s);
	if (s.mSearching) {
		return Pwr::Activity;
	}
	if (!s.mPaired) {
		return Pwr::Fault;
	}
	const bool beaconLost = s.mLastBeaconMs == 0 || k_uptime_get() - s.mLastBeaconMs > kBeaconLostMs;
	const bool unreachable = s.mLastResult == Result::ConnectFailed || s.mLastResult == Result::Timeout ||
				 s.mLastResult == Result::Disconnected;

	return beaconLost || unreachable ? Pwr::Warning : Pwr::On;
}
#endif

} /* namespace */

CHIP_ERROR AppTask::RestoreBridgedDevices()
{
	/* The door lock endpoints are fixed and added by NukiMatter::Init, not stored. */
	return CHIP_NO_ERROR;
}

CHIP_ERROR AppTask::Init()
{
	/* Initialize Matter stack */
	ReturnErrorOnFailure(Nrf::Matter::PrepareServer(Nrf::Matter::InitData{
#ifdef CONFIG_GATEWAY_IDENTITY_FROM_CHIP_ID
		.mFactoryDataProvider = &sChipIdFactoryDataProvider,
#endif
		.mPostServerInitClbk = [] {
		CHIP_ERROR err = Nrf::BridgeManager::Instance().Init(RestoreBridgedDevices);
		if (err != CHIP_NO_ERROR) {
			LOG_ERR("BridgeManager initialization failed");
			return err;
		}

		/* Door lock endpoints and the Nuki client; Bluetooth is up now (Matter's commissioning peripheral). */
		/* Not fatal: Matter keeps running (and can be reached for a fix). */
		err = Gateway::NukiMatter::Init();
		if (err != CHIP_NO_ERROR) {
			LOG_ERR("Nuki endpoints initialization failed: %" CHIP_ERROR_FORMAT, err.Format());
		}
#ifdef CONFIG_GATEWAY_NET_LOG
		Gateway::NetLog::Init();
#endif
#ifdef CONFIG_GATEWAY_WEB
		Gateway::Web::Init(Gateway::WriteWebStatus);
#endif
		return CHIP_NO_ERROR;
	} }));

	if (!Nrf::GetBoard().Init()) {
		LOG_ERR("User interface initialization failed.");
		return CHIP_ERROR_INCORRECT_STATE;
	}
#ifdef CONFIG_GATEWAY_STATUS_LEDS
	Gateway::StatusLeds::InitPattern(PwrPattern);
#endif

	/* Register Matter event handler that controls the connectivity status LED based on the captured Matter
	 * network state. */
	ReturnErrorOnFailure(Nrf::Matter::RegisterEventHandler(Nrf::Board::DefaultMatterEventHandler, 0));

#ifndef CONFIG_CHIP_FACTORY_RESET_ERASE_SETTINGS
	/* The whole settings partition is not erased on factory reset; clean up the bridge storage. */
	ReturnErrorOnFailure(Nrf::Matter::RegisterEventHandler(AppFactoryResetHandler, 0));
#endif

	ReturnErrorOnFailure(sIdentifyCluster.Init());

#ifdef CONFIG_GATEWAY_OTA
	ReturnErrorOnFailure(Gateway::Ota::Init());
#endif

	return Nrf::Matter::StartServer();
}

CHIP_ERROR AppTask::StartApp()
{
	ReturnErrorOnFailure(Init());

	while (true) {
		Nrf::DispatchNextTask();
	}

	return CHIP_NO_ERROR;
}
