# Fails the build if the app binary doesn't contain its own version string (cmake -P script, run
# before zephyr/matter.ota is generated; common.cmake).
#
# Why: after a VERSION bump, an incremental build gives a .ota header with the new version, but
# Matter's separately built library can keep the old one compiled in (it doesn't track
# app_version.h). The device then reports the old version after the update, the OTA requestor
# never confirms it, and a provider would offer the same update again and again.
#   cmake -DBIN=zephyr.bin -DVERSION_STRING=0.1.0+3 -P check_version.cmake

file(STRINGS "${BIN}" found REGEX "^[0-9]+\\.[0-9]+\\.[0-9]+[-+.a-zA-Z0-9]*$")
list(FIND found "${VERSION_STRING}" index)
if(index EQUAL -1)
  message(FATAL_ERROR
    "${BIN} doesn't contain its version string '${VERSION_STRING}' (found: ${found}). "
    "Matter's library kept an older version after a VERSION change: rebuild from scratch "
    "(west build -p, or delete the build folder).")
endif()
