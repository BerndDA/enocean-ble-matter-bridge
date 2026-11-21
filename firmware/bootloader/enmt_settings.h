/*
 * Read-only lookup in the app's settings partition (Zephyr settings on NVS), for values the
 * bootloader shows on the UF2 drive. See enmt_settings.c.
 */

#ifndef ENMT_SETTINGS_H
#define ENMT_SETTINGS_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

// The newest value stored under a settings name (e.g. "ot/3"). False if the name isn't there,
// was deleted, or the area isn't Zephyr NVS with sectors of sector_size bytes.
bool enmt_settings_find(const uint8_t* area, size_t size, size_t sector_size, const char* name,
                        const uint8_t** value, size_t* len);

// The Thread extended address from OpenThread's network info ("ot/3"). False if the gateway
// hasn't joined a Thread network yet.
bool enmt_thread_ext_addr(const uint8_t* area, size_t size, size_t sector_size, uint8_t ext_addr[8]);

#endif // ENMT_SETTINGS_H
