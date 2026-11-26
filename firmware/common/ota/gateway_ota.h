/*
 * Matter OTA without MCUboot (OTA_PLAN.md): the OTA requestor downloads the image over BDX into
 * the external QSPI flash, writes the header that commits it, and reboots; the EnMT UF2 bootloader
 * (firmware/bootloader, enmt_qspi_ota.c) copies it into place.
 *
 * Boards with the partitions ota_header_partition and ota_slot_partition in their devicetree
 * (common/boards/enmt_dk.overlay, enmt_carrier.overlay) build with CONFIG_GATEWAY_OTA.
 */

#pragma once

#include <lib/core/CHIPError.h>

namespace Gateway::Ota
{

/* Before Nrf::Matter::StartServer(): sets the OTA requestor up once the server is ready. */
CHIP_ERROR Init();

} // namespace Gateway::Ota
