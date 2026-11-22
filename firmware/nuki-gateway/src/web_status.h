/*
 * Status JSON of the Nuki gateway for the web page (src/web/index.html):
 * system, Thread, Matter, the lock (Bluetooth link, state, battery) and the two Matter endpoints.
 */

#pragma once

#include <stddef.h>

namespace Gateway
{

/* A Gateway::Web::StatusWriter: Matter thread, returns 0 if the JSON does not fit. */
size_t WriteWebStatus(char *buf, size_t size);

} /* namespace Gateway */
