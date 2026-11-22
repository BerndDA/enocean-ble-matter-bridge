/*
 * Door Lock (0x000A) as a bridged endpoint, with the Door Lock cluster served by this code:
 * attributes through HandleRead (external attribute storage), commands through the
 * CommandHandlerInterface in nuki_matter.cpp. The SDK's Door Lock server isn't used.
 *
 * Minimal cluster: LockState, LockType (deadbolt), ActuatorEnabled, OperatingMode (normal),
 * SupportedOperatingModes; no features (no PIN, no users, no unbolting); LockDoor and UnlockDoor.
 *
 * Role Lock carries a Power Source cluster (the lock's battery); role Opener has none.
 */

#pragma once

#include "matter_bridged_device.h"

class DoorLockDevice : public Nrf::MatterBridgedDevice {
public:
	enum class Role : uint8_t { Lock, Opener };

	static constexpr uint16_t kDeviceTypeDoorLock = 0x000A;
	/* DoorLock.LockState as stored: 0 not fully locked, 1 locked, 2 unlocked, 3 unlatched, 0xFF null */
	static constexpr uint8_t kLockStateNull = 0xFF;

	DoorLockDevice(const char *uniqueID, const char *nodeLabel, Role role);

	Role GetRole() const { return mRole; }
	uint8_t GetLockState() const { return mLockState; }

	uint16_t GetDeviceType() const override { return kDeviceTypeDoorLock; }
	const char *GetVendorName() const override { return "Nuki"; }
	const char *GetProductName() const override
	{
		return mRole == Role::Lock ? "Smart Lock" : "Smart Lock (door opener)";
	}
	CHIP_ERROR HandleRead(chip::ClusterId clusterId, chip::AttributeId attributeId, uint8_t *buffer,
			      uint16_t maxReadLength) override;
	CHIP_ERROR HandleWrite(chip::ClusterId clusterId, chip::AttributeId attributeId, uint8_t *buffer,
			       size_t size) override;
	CHIP_ERROR HandleAttributeChange(chip::ClusterId clusterId, chip::AttributeId attributeId, void *data,
					 size_t dataSize) override;

private:
	Role mRole;
	uint8_t mLockState = kLockStateNull;
};
