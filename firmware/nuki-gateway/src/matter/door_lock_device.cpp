/*
 * Door Lock as a bridged endpoint. See door_lock_device.h.
 */

#include "door_lock_device.h"

#include <app-common/zap-generated/cluster-objects.h>
#include <clusters/DoorLock/Metadata.h>

using namespace ::chip;
using namespace ::chip::app;
using namespace Nrf;

namespace DL = chip::app::Clusters::DoorLock;

namespace
{
DESCRIPTOR_CLUSTER_ATTRIBUTES(descriptorAttrs);
BRIDGED_DEVICE_BASIC_INFORMATION_CLUSTER_ATTRIBUTES(bridgedDeviceBasicAttrs);
POWER_SOURCE_BATTERY_CLUSTER_ATTRIBUTES(powerSourceAttrs);

DECLARE_DYNAMIC_ATTRIBUTE_LIST_BEGIN(doorLockAttrs)
DECLARE_DYNAMIC_ATTRIBUTE(DL::Attributes::LockState::Id, ENUM8, 1, ZAP_ATTRIBUTE_MASK(NULLABLE)),
	DECLARE_DYNAMIC_ATTRIBUTE(DL::Attributes::LockType::Id, ENUM8, 1, 0),
	DECLARE_DYNAMIC_ATTRIBUTE(DL::Attributes::ActuatorEnabled::Id, BOOLEAN, 1, 0),
	DECLARE_DYNAMIC_ATTRIBUTE(DL::Attributes::OperatingMode::Id, ENUM8, 1, 0),
	DECLARE_DYNAMIC_ATTRIBUTE(DL::Attributes::SupportedOperatingModes::Id, BITMAP16, 2, 0),
	DECLARE_DYNAMIC_ATTRIBUTE(DL::Attributes::FeatureMap::Id, BITMAP32, 4, 0), DECLARE_DYNAMIC_ATTRIBUTE_LIST_END();

/* Handled by the CommandHandlerInterface in nuki_matter.cpp */
constexpr CommandId doorLockIncomingCommands[] = {
	DL::Commands::LockDoor::Id,
	DL::Commands::UnlockDoor::Id,
	kInvalidCommandId,
};

DECLARE_DYNAMIC_CLUSTER_LIST_BEGIN(lockClusters)
DECLARE_DYNAMIC_CLUSTER(DL::Id, doorLockAttrs, ZAP_CLUSTER_MASK(SERVER), doorLockIncomingCommands, nullptr),
	DECLARE_DYNAMIC_CLUSTER(Clusters::Descriptor::Id, descriptorAttrs, ZAP_CLUSTER_MASK(SERVER), nullptr, nullptr),
	DECLARE_DYNAMIC_CLUSTER(Clusters::BridgedDeviceBasicInformation::Id, bridgedDeviceBasicAttrs,
				ZAP_CLUSTER_MASK(SERVER), nullptr, nullptr),
	DECLARE_DYNAMIC_CLUSTER(Clusters::PowerSource::Id, powerSourceAttrs, ZAP_CLUSTER_MASK(SERVER), nullptr, nullptr),
	DECLARE_DYNAMIC_CLUSTER_LIST_END;

DECLARE_DYNAMIC_ENDPOINT(lockEndpoint, lockClusters);

DECLARE_DYNAMIC_CLUSTER_LIST_BEGIN(openerClusters)
DECLARE_DYNAMIC_CLUSTER(DL::Id, doorLockAttrs, ZAP_CLUSTER_MASK(SERVER), doorLockIncomingCommands, nullptr),
	DECLARE_DYNAMIC_CLUSTER(Clusters::Descriptor::Id, descriptorAttrs, ZAP_CLUSTER_MASK(SERVER), nullptr, nullptr),
	DECLARE_DYNAMIC_CLUSTER(Clusters::BridgedDeviceBasicInformation::Id, bridgedDeviceBasicAttrs,
				ZAP_CLUSTER_MASK(SERVER), nullptr, nullptr),
	DECLARE_DYNAMIC_CLUSTER_LIST_END;

DECLARE_DYNAMIC_ENDPOINT(openerEndpoint, openerClusters);

constexpr uint8_t kDoorLockDeviceTypeVersion = 3;

constexpr EmberAfDeviceType kDoorLockDeviceTypes[] = {
	{ static_cast<chip::DeviceTypeId>(DoorLockDevice::kDeviceTypeDoorLock), kDoorLockDeviceTypeVersion },
	{ static_cast<chip::DeviceTypeId>(MatterBridgedDevice::DeviceType::BridgedNode),
	  MatterBridgedDevice::kDefaultDynamicEndpointVersion }
};

/* Bits cleared = supported (the spec's inverted bitmap): Normal and NoRemoteLockUnlock */
constexpr uint16_t kSupportedOperatingModes = 0xFFF6;

} /* namespace */

DoorLockDevice::DoorLockDevice(const char *uniqueID, const char *nodeLabel, Role role)
	: MatterBridgedDevice(uniqueID, nodeLabel), mRole(role)
{
	mDeviceTypeList = kDoorLockDeviceTypes;
	mDeviceTypeListSize = ARRAY_SIZE(kDoorLockDeviceTypes);
	if (role == Role::Lock) {
		mEp = &lockEndpoint;
		mDataVersionSize = MATTER_ARRAY_SIZE(lockClusters);
		EnablePowerSource();
	} else {
		mEp = &openerEndpoint;
		mDataVersionSize = MATTER_ARRAY_SIZE(openerClusters);
	}
	mDataVersion = static_cast<DataVersion *>(chip::Platform::MemoryAlloc(sizeof(DataVersion) * mDataVersionSize));
}

CHIP_ERROR DoorLockDevice::HandleRead(ClusterId clusterId, AttributeId attributeId, uint8_t *buffer,
				      uint16_t maxReadLength)
{
	VerifyOrReturnError(clusterId == DL::Id, CHIP_ERROR_INVALID_ARGUMENT);

	switch (attributeId) {
	case DL::Attributes::LockState::Id:
		return CopyAttribute(&mLockState, sizeof(mLockState), buffer, maxReadLength);
	case DL::Attributes::LockType::Id: {
		const uint8_t value = to_underlying(DL::DlLockType::kDeadBolt);
		return CopyAttribute(&value, sizeof(value), buffer, maxReadLength);
	}
	case DL::Attributes::ActuatorEnabled::Id: {
		const bool value = true;
		return CopyAttribute(&value, sizeof(value), buffer, maxReadLength);
	}
	case DL::Attributes::OperatingMode::Id: {
		const uint8_t value = to_underlying(DL::OperatingModeEnum::kNormal);
		return CopyAttribute(&value, sizeof(value), buffer, maxReadLength);
	}
	case DL::Attributes::SupportedOperatingModes::Id:
		return CopyAttribute(&kSupportedOperatingModes, sizeof(kSupportedOperatingModes), buffer, maxReadLength);
	case DL::Attributes::FeatureMap::Id: {
		const uint32_t value = 0;
		return CopyAttribute(&value, sizeof(value), buffer, maxReadLength);
	}
	case DL::Attributes::ClusterRevision::Id: {
		const uint16_t value = DL::kRevision;
		return CopyAttribute(&value, sizeof(value), buffer, maxReadLength);
	}
	default:
		return CHIP_ERROR_INVALID_ARGUMENT;
	}
}

CHIP_ERROR DoorLockDevice::HandleWrite(ClusterId clusterId, AttributeId attributeId, uint8_t *buffer, size_t size)
{
	/* Only the node label is writable (Bridged Device Basic Information). */
	if (clusterId == Clusters::BridgedDeviceBasicInformation::Id) {
		return HandleWriteDeviceBasicInformation(clusterId, attributeId, buffer, size);
	}
	return CHIP_ERROR_INVALID_ARGUMENT;
}

CHIP_ERROR DoorLockDevice::HandleAttributeChange(ClusterId clusterId, AttributeId attributeId, void *data,
						 size_t dataSize)
{
	VerifyOrReturnError(data, CHIP_ERROR_INVALID_ARGUMENT);

	switch (clusterId) {
	case Clusters::BridgedDeviceBasicInformation::Id:
		return HandleWriteDeviceBasicInformation(clusterId, attributeId, data, dataSize);
	case DL::Id:
		VerifyOrReturnError(attributeId == DL::Attributes::LockState::Id && dataSize == 1,
				    CHIP_ERROR_INVALID_ARGUMENT);
		mLockState = *static_cast<uint8_t *>(data);
		return CHIP_NO_ERROR;
	default:
		return CHIP_ERROR_INVALID_ARGUMENT;
	}
}
