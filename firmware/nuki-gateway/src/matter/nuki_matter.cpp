/*
 * The Nuki lock in Matter. See nuki_matter.h.
 *
 * Threads: the Nuki client calls back from its own thread; those callbacks store what changed
 * and schedule work on the Matter thread, which owns the endpoints, the timers and the reports.
 */

#include "nuki_matter.h"

#include "bridge_manager.h"
#include "door_lock_device.h"
#include "nuki_client.h"
#ifdef CONFIG_GATEWAY_STATUS_LEDS
#include "status_leds/status_leds.h"
#endif

#include <app-common/zap-generated/cluster-objects.h>
#include <app/CommandHandler.h>
#include <app/CommandHandlerInterface.h>
#include <app/CommandHandlerInterfaceRegistry.h>
#include <platform/CHIPDeviceLayer.h>
#include <system/SystemClock.h>

#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>

LOG_MODULE_REGISTER(nuki_matter, CONFIG_GATEWAY_NUKI_LOG_LEVEL);

using namespace ::chip;
using namespace ::chip::app;
using namespace ::chip::app::Clusters;
using Protocols::InteractionModel::Status;

namespace DL = chip::app::Clusters::DoorLock;

namespace Gateway
{
namespace NukiMatter
{
namespace
{

/* Endpoint 2 is the data model's placeholder (disabled by the bridge manager); dynamic ones start at 3.
 * The opener came first in the first build, so it keeps 3. */
constexpr EndpointId kOpenerEndpointId = 3;
constexpr EndpointId kLockEndpointId = 4;
constexpr uint8_t kOpenerIndex = 0;
constexpr uint8_t kLockIndex = 1;

constexpr uint8_t kLocked = to_underlying(DL::DlLockState::kLocked);
constexpr uint8_t kUnlocked = to_underlying(DL::DlLockState::kUnlocked);
constexpr uint8_t kNotFullyLocked = to_underlying(DL::DlLockState::kNotFullyLocked);

constexpr System::Clock::Seconds32 kOpenShowUnlocked{ 3 };
constexpr System::Clock::Seconds32 kOpenTimeout{ 30 };

/* Pushes state into the bridge (BridgeManager::HandleUpdate -> device -> attribute report). */
class LockProvider : public Nrf::BridgedDeviceDataProvider {
public:
	LockProvider() : BridgedDeviceDataProvider(Nrf::BridgeManager::HandleUpdate) {}

	void Init() override {}
	void NotifyUpdateState(ClusterId clusterId, AttributeId attributeId, void *data, size_t dataSize) override
	{
		if (mUpdateAttributeCallback) {
			mUpdateAttributeCallback(*this, clusterId, attributeId, data, dataSize);
		}
	}
	CHIP_ERROR UpdateState(ClusterId, AttributeId, uint8_t *) override
	{
		return CHIP_ERROR_UNSUPPORTED_CHIP_FEATURE;
	}

	void SetLockState(uint8_t state)
	{
		NotifyUpdateState(DL::Id, DL::Attributes::LockState::Id, &state, sizeof(state));
	}
};

/* Owned by the bridge manager once added */
LockProvider *sLockProvider;
LockProvider *sOpenerProvider;

/* Matter thread only */
bool sOpenPending; /* unlatch requested via the opener, not yet seen */

/* Handed from the Nuki thread to the Matter thread */
k_spinlock sLock;
nuki_keyturner_state sPendingState;
bool sStatePending;
bool sPaired;
bool sPairedPending;
bool sActionFailed; /* an opener unlatch that failed */

/* --- Matter thread ------------------------------------------------------------------------------------------- */

void OpenerSet(uint8_t state)
{
	if (sOpenerProvider) {
		sOpenerProvider->SetLockState(state);
	}
}

void OpenerRelock(System::Layer *, void *)
{
	sOpenPending = false;
	OpenerSet(kLocked);
}

void OpenerShowUnlocked()
{
	sOpenPending = false;
	DeviceLayer::SystemLayer().CancelTimer(OpenerRelock, nullptr);
	OpenerSet(kUnlocked);
	DeviceLayer::SystemLayer().StartTimer(kOpenShowUnlocked, OpenerRelock, nullptr);
}

void ApplyState(const nuki_keyturner_state &s)
{
	/* Front door. Motor running: keep the previous value; controllers show progress themselves. */
	switch (s.lock_state) {
	case NUKI_LOCK_LOCKED:
		sLockProvider->SetLockState(kLocked);
		break;
	case NUKI_LOCK_UNLOCKED:
	case NUKI_LOCK_UNLATCHED:
	case NUKI_LOCK_UNLOCKED_LOCK_N_GO:
		/* The bolt is open; whether the latch was pulled is the opener's business. */
		sLockProvider->SetLockState(kUnlocked);
		break;
	case NUKI_LOCK_MOTOR_BLOCKED:
		sLockProvider->SetLockState(kNotFullyLocked);
		break;
	case NUKI_LOCK_LOCKING:
	case NUKI_LOCK_UNLOCKING:
	case NUKI_LOCK_UNLATCHING:
		break;
	default: /* uncalibrated, calibration, boot run, undefined */
		sLockProvider->SetLockState(DoorLockDevice::kLockStateNull);
		break;
	}

	/* Unlatched (from any source, e.g. the Nuki app) or our own request done. A fast lock can be
	 * past Unlatched before the next read; then Unlocked counts while a request is pending. */
	if (s.lock_state == NUKI_LOCK_UNLATCHING || s.lock_state == NUKI_LOCK_UNLATCHED ||
	    (sOpenPending && s.lock_state == NUKI_LOCK_UNLOCKED)) {
		OpenerShowUnlocked();
	}

	/* Power Source: BatPercentRemaining in half percent */
	uint8_t pct = uint8_t(nuki_battery_percent(s.battery_raw) * 2);
	uint8_t level = nuki_battery_critical(s.battery_raw) ? 2 : 0; /* BatChargeLevelEnum: OK / critical */
	bool replace = nuki_battery_critical(s.battery_raw);

	sLockProvider->NotifyUpdateState(PowerSource::Id, PowerSource::Attributes::BatPercentRemaining::Id, &pct,
					 sizeof(pct));
	sLockProvider->NotifyUpdateState(PowerSource::Id, PowerSource::Attributes::BatChargeLevel::Id, &level,
					 sizeof(level));
	sLockProvider->NotifyUpdateState(PowerSource::Id, PowerSource::Attributes::BatReplacementNeeded::Id, &replace,
					 sizeof(replace));
}

void ApplyReachable(bool reachable)
{
	sLockProvider->NotifyReachableStatusChange(reachable);
	sOpenerProvider->NotifyReachableStatusChange(reachable);
	if (!reachable) {
		sLockProvider->SetLockState(DoorLockDevice::kLockStateNull);
	}
}

void ApplyPending(intptr_t)
{
	nuki_keyturner_state state;
	bool haveState, havePaired, paired, actionFailed;
	k_spinlock_key_t key = k_spin_lock(&sLock);

	state = sPendingState;
	haveState = sStatePending;
	havePaired = sPairedPending;
	paired = sPaired;
	actionFailed = sActionFailed;
	sStatePending = sPairedPending = sActionFailed = false;
	k_spin_unlock(&sLock, key);

	if (!sLockProvider || !sOpenerProvider) {
		return;
	}
	if (havePaired) {
		ApplyReachable(paired);
	}
	if (haveState) {
		ApplyState(state);
	}
	if (actionFailed && sOpenPending) {
		LOG_WRN("Unlatch failed: door opener back to Locked");
		DeviceLayer::SystemLayer().CancelTimer(OpenerRelock, nullptr);
		OpenerRelock(nullptr, nullptr);
	}
}

void Schedule()
{
	DeviceLayer::PlatformMgr().ScheduleWork(ApplyPending, 0);
}

/* --- Nuki thread --------------------------------------------------------------------------------------------- */

void OnNukiState(const nuki_keyturner_state &state)
{
	k_spinlock_key_t key = k_spin_lock(&sLock);

	sPendingState = state;
	sStatePending = true;
	k_spin_unlock(&sLock, key);
	Schedule();
#ifdef CONFIG_GATEWAY_STATUS_LEDS
	Gateway::StatusLeds::PacketReceived();
#endif
}

void OnNukiPaired(bool paired)
{
	k_spinlock_key_t key = k_spin_lock(&sLock);

	sPaired = paired;
	sPairedPending = true;
	k_spin_unlock(&sLock, key);
	Schedule();
}

void OnNukiActionDone(uint8_t action, Nuki::Result result)
{
	if (result == Nuki::Result::Ok || action != NUKI_ACTION_UNLATCH) {
		return;
	}
	k_spinlock_key_t key = k_spin_lock(&sLock);

	sActionFailed = true;
	k_spin_unlock(&sLock, key);
	Schedule();
}

/* --- Commands (Matter thread) -------------------------------------------------------------------------------- */

class DoorLockCommands : public CommandHandlerInterface {
public:
	DoorLockCommands() : CommandHandlerInterface(NullOptional, DL::Id) {}

	void InvokeCommand(HandlerContext &ctx) override
	{
		const EndpointId endpoint = ctx.mRequestPath.mEndpointId;

		if (endpoint != kLockEndpointId && endpoint != kOpenerEndpointId) {
			return; /* not handled */
		}
		switch (ctx.mRequestPath.mCommandId) {
		case DL::Commands::LockDoor::Id:
			HandleCommand<DL::Commands::LockDoor::DecodableType>(
				ctx, [endpoint](HandlerContext &c, const auto &) { Respond(c, Lock(endpoint)); });
			break;
		case DL::Commands::UnlockDoor::Id:
			HandleCommand<DL::Commands::UnlockDoor::DecodableType>(
				ctx, [endpoint](HandlerContext &c, const auto &) { Respond(c, Unlock(endpoint)); });
			break;
		default:
			break;
		}
	}

private:
	static void Respond(HandlerContext &ctx, Status status)
	{
		ctx.mCommandHandler.AddStatus(ctx.mRequestPath, status);
	}

	static Status Queue(uint8_t action)
	{
		const int err = Nuki::LockAction(action);

		if (err) {
			LOG_WRN("Lock action 0x%02x not queued (%d)", action, err);
			return Status::Failure;
		}
		return Status::Success;
	}

	static Status Lock(EndpointId endpoint)
	{
		if (endpoint == kOpenerEndpointId) {
			/* Nothing to lock: just back to the resting state */
			LOG_INF("Matter: lock on the door opener, no-op");
			DeviceLayer::SystemLayer().CancelTimer(OpenerRelock, nullptr);
			OpenerRelock(nullptr, nullptr);
			return Status::Success;
		}
		LOG_INF("Matter: lock");
		return Queue(NUKI_ACTION_LOCK);
	}

	static Status Unlock(EndpointId endpoint)
	{
		if (endpoint == kOpenerEndpointId) {
			LOG_INF("Matter: door opener, unlatch");
			const Status status = Queue(NUKI_ACTION_UNLATCH);

			if (status == Status::Success) {
				sOpenPending = true;
				/* If the lock never reports the unlatch, fall back to Locked. */
				DeviceLayer::SystemLayer().CancelTimer(OpenerRelock, nullptr);
				DeviceLayer::SystemLayer().StartTimer(kOpenTimeout, OpenerRelock, nullptr);
			}
			return status;
		}
		LOG_INF("Matter: unlock");
		return Queue(NUKI_ACTION_UNLOCK);
	}
};

DoorLockCommands sCommands;

CHIP_ERROR AddEndpoint(DoorLockDevice::Role role, const char *uniqueId, const char *label, uint8_t index,
		       EndpointId endpointId, LockProvider *&providerOut)
{
	Nrf::MatterBridgedDevice *device = Platform::New<DoorLockDevice>(uniqueId, label, role);
	auto *provider = Platform::New<LockProvider>();

	if (!device || !provider) {
		Platform::Delete(device);
		Platform::Delete(provider);
		return CHIP_ERROR_NO_MEMORY;
	}

	uint8_t indexes[] = { index };
	uint16_t endpoints[] = { endpointId };
	/* On failure the bridge manager deletes the device and the provider. */
	ReturnErrorOnFailure(Nrf::BridgeManager::Instance().AddBridgedDevices(&device, provider, 1, indexes, endpoints));
	providerOut = provider;
	LOG_INF("'%s' on endpoint %u", label, endpointId);
	return CHIP_NO_ERROR;
}

} /* namespace */

CHIP_ERROR Init()
{
	ReturnErrorOnFailure(AddEndpoint(DoorLockDevice::Role::Lock, "nuki-lock", CONFIG_GATEWAY_NUKI_LOCK_LABEL,
					 kLockIndex, kLockEndpointId, sLockProvider));
	ReturnErrorOnFailure(AddEndpoint(DoorLockDevice::Role::Opener, "nuki-opener", CONFIG_GATEWAY_NUKI_OPENER_LABEL,
					 kOpenerIndex, kOpenerEndpointId, sOpenerProvider));
	/* The opener has no state of its own and rests in Locked. */
	OpenerSet(kLocked);

	ReturnErrorOnFailure(CommandHandlerInterfaceRegistry::Instance().RegisterCommandHandler(&sCommands));

	Nuki::Callbacks callbacks = {};

	callbacks.mState = OnNukiState;
	callbacks.mPaired = OnNukiPaired;
	callbacks.mActionDone = OnNukiActionDone;
	Nuki::Init(callbacks);

	/* Reachable while paired */
	Nuki::Snapshot snapshot;

	Nuki::GetSnapshot(snapshot);
	ApplyReachable(snapshot.mPaired);
	return CHIP_NO_ERROR;
}

} /* namespace NukiMatter */
} /* namespace Gateway */
