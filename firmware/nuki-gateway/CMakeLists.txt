#
# Nuki-to-Matter-over-Thread gateway.
# Based on the nRF Connect SDK Matter Bridge application
# (Copyright (c) 2023 Nordic Semiconductor ASA, LicenseRef-Nordic-5-Clause).
#

cmake_minimum_required(VERSION 3.20.0)

find_package(Zephyr HINTS $ENV{ZEPHYR_BASE})

project(nuki-matter-gateway)

# Bridge core, Matter identity, network log: firmware/common
include(${CMAKE_CURRENT_SOURCE_DIR}/../common/common.cmake)

target_include_directories(app PRIVATE
  src
  src/matter
  src/nuki
)

target_sources(app PRIVATE
  src/app_task.cpp
  src/main.cpp
  src/gateway_shell.cpp
  src/matter/door_lock_device.cpp
  src/matter/nuki_matter.cpp
  src/nuki/nuki_proto.c
  src/nuki/nuki_port.c
  src/nuki/nuki_client.cpp
  src/nuki/tweetnacl/tweetnacl.c
)
target_sources_ifdef(CONFIG_SHELL app PRIVATE src/nuki/nuki_shell.cpp)

# TweetNaCl as published (public domain, tweetnacl.cr.yp.to 20140427): no warnings for code we don't change
set_source_files_properties(src/nuki/tweetnacl/tweetnacl.c PROPERTIES COMPILE_OPTIONS "-w")

ncs_configure_data_model()
