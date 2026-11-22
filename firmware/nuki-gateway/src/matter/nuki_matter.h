/*
 * The Nuki lock in Matter: two bridged Door Lock endpoints, like the ESP32 bridge (nuki_matter).
 *
 *   Endpoint 4 "Front door"   Lock / Unlock move the bolt only. LockState follows the lock;
 *                             it keeps its value while the motor runs. Battery in Power Source.
 *   Endpoint 3 "Door opener"  Unlock pulls the latch (Nuki unlatch). It rests in Locked, shows
 *                             Unlocked for 3 s once the lock has unlatched (also when opened
 *                             from the Nuki app), and falls back to Locked after 30 s otherwise.
 *                             Lock does nothing. Apple Home has no unlatch button, and asks for
 *                             Face ID / passcode for locks, so this is the safe way to open.
 *
 * Both endpoints always exist (so the structure stays the same for controllers); they are
 * unreachable while the gateway isn't paired with a lock.
 */

#pragma once

#include <platform/CHIPDeviceLayer.h>

namespace Gateway
{
namespace NukiMatter
{

/* On the Matter thread, after BridgeManager::Init: adds the endpoints and starts the Nuki client. */
CHIP_ERROR Init();

} /* namespace NukiMatter */
} /* namespace Gateway */
