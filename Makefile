# Shortcuts for building, flashing and testing the gateways. `make` lists the targets.
# Every target sets up the SDK itself (scripts/ncs-env.sh); no need to source it first.
# Add APP=enocean-gateway for the EnOcean gateway or APP=nuki-gateway for the Nuki gateway (default: the BLE gateway), and
# BOARD=promicro or BOARD=promicro-uf2 for the Pro Micro nRF52840, BOARD=enmt for the EnMT carrier,
# BOARD=enmt-dk for the carrier build on a DK with the EnMT bootloader.

SHELL := /bin/bash
.DEFAULT_GOAL := help

# App: a folder in firmware/ (ble-gateway, enocean-gateway, nuki-gateway). An exported APP from the shell is ignored.
ifeq ($(origin APP),environment)
APP      := ble-gateway
endif
APP      ?= ble-gateway
APP_DIR  := firmware/$(APP)
ifeq ($(wildcard $(APP_DIR)/CMakeLists.txt),)
$(error APP must be one of: $(notdir $(patsubst %/CMakeLists.txt,%,$(wildcard firmware/*-gateway/CMakeLists.txt))))
endif

# Board:
#   dk            nRF52840 DK (default)
#   promicro      Pro Micro nRF52840, flashed over SWD through the DK's Debug Out header
#   promicro-uf2  Pro Micro nRF52840 with its factory UF2 bootloader, flashed over USB
#   enmt          EnMT carrier board (hardware/enocean-carrier): promicro-uf2 plus its three status
#                 LEDs (firmware/common/boards/enmt_carrier.overlay); all apps
#   enmt-dk       the enmt build on an nRF52840 DK with the EnMT bootloader (firmware/bootloader,
#                 enmt_dk): status LEDs on LED1-3, Button 1 as function button, flashed over the
#                 DK's nRF USB port (firmware/common/boards/enmt_dk.overlay); all apps
# An exported BOARD from the shell is ignored.
ifeq ($(origin BOARD),environment)
BOARD    := dk
endif
BOARD    ?= dk
ifeq ($(BOARD),dk)
TARGET   := nrf52840dk/nrf52840
SUFFIX   :=
PORT     ?= $(firstword $(wildcard /dev/cu.usbmodem000683*))
else ifeq ($(BOARD),promicro)
TARGET   := promicro_nrf52840/nrf52840
SUFFIX   := -promicro
# USB CDC port of the Pro Micro: any usbmodem port that isn't the DK's J-Link
PORT     ?= $(firstword $(filter-out /dev/cu.usbmodem000683%,$(wildcard /dev/cu.usbmodem*)))
else ifeq ($(BOARD),promicro-uf2)
TARGET   := promicro_nrf52840/nrf52840/uf2
SUFFIX   := -promicro-uf2
UF2      := 1
PORT     ?= $(firstword $(filter-out /dev/cu.usbmodem000683%,$(wildcard /dev/cu.usbmodem*)))
else ifeq ($(BOARD),enmt)
TARGET   := promicro_nrf52840/nrf52840/uf2
SUFFIX   := -enmt
UF2      := 1
PORT     ?= $(firstword $(filter-out /dev/cu.usbmodem000683%,$(wildcard /dev/cu.usbmodem*)))
BOARD_ARGS := -DEXTRA_DTC_OVERLAY_FILE=$(CURDIR)/firmware/common/boards/enmt_carrier.overlay
else ifeq ($(BOARD),enmt-dk)
TARGET   := promicro_nrf52840/nrf52840/uf2
SUFFIX   := -enmt-dk
UF2      := 1
PORT     ?= $(firstword $(filter-out /dev/cu.usbmodem000683%,$(wildcard /dev/cu.usbmodem*)))
BOARD_ARGS := -DEXTRA_DTC_OVERLAY_FILE=$(CURDIR)/firmware/common/boards/enmt_dk.overlay
else
$(error BOARD must be dk, promicro, promicro-uf2, enmt or enmt-dk)
endif

# Flash a build folder: west flash, or for promicro-uf2 the .uf2 copied to the bootloader drive
# promicro-uf2: make-uf2.py also prints the board's setup code (the firmware derives it from the chip ID).
# Without a UF2 drive, it first sends `gateway bootloader` on PORT.
ifdef UF2
flash_dir = $(NCS) python3 scripts/make-uf2.py -o $(1)/$(APP).uf2 --deploy --identity $(1) \
	$(if $(PORT),--port $(PORT)) $(1)/$(APP)/zephyr/zephyr.hex $(1)/matter_factory_data/zephyr/factory_data.hex
else
flash_dir = $(NCS) west flash -d $(1) $(2)
endif

BUILD    := $(APP_DIR)/build$(SUFFIX)
DIAG     := $(APP_DIR)/build-diag$(SUFFIX)
RELEASE  := $(APP_DIR)/build-release$(SUFFIX)

# Host unit tests: every tests/host/<name>/Makefile of the app
TESTS    := $(patsubst %/Makefile,%,$(wildcard $(APP_DIR)/tests/host/*/Makefile))

# Measurement settings (make measure MINUTES=20 THERMOSTAT=00:1A:22:0F:3F:02)
MINUTES    ?= 20
INTERVAL   ?= 60
THERMOSTAT ?=
TARGETS    ?= 18.5,18

NCS := source scripts/ncs-env.sh >/dev/null &&

.PHONY: help build flash flash-erase release release-flash ota release-ota diag diag-flash test zap term measure summary identity netlog hosts clean

help: ## List the targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  make %-12s %s\n", $$1, $$2}'

build: ## Build the app (incremental)
	@$(NCS) west build -b $(TARGET) --sysbuild -d $(BUILD) $(APP_DIR) $(if $(BOARD_ARGS),-- $(BOARD_ARGS))

flash: build ## Build and flash; keeps commissioning and stored devices
	@$(call flash_dir,$(BUILD))

flash-erase: build ## Build and flash with a full erase; the gateway must be commissioned again
ifdef UF2
	@echo "BOARD=$(BOARD) can't erase over UF2: the settings lie outside what the bootloader writes."
	@echo "Use 'make flash BOARD=$(BOARD)', then 'matter factoryreset' in the shell or hold the button 6 s."
	@exit 1
else
	@$(call flash_dir,$(BUILD),--erase)
endif

release: ## Build with prj_release.conf (no logging, watchdog, reset on fatal error) into build-release
	@$(NCS) west build -b $(TARGET) --sysbuild -d $(RELEASE) $(APP_DIR) -- -DFILE_SUFFIX=release $(BOARD_ARGS)

release-flash: release ## Build the release firmware and flash it; keeps commissioning and stored devices
	@$(call flash_dir,$(RELEASE))

# Matter OTA image (OTA_PLAN.md): only boards with the QSPI slot. Always a pristine build, as an
# incremental one can keep the previous version in the Matter library.
OTA_VER = $(shell awk -F' *= *' '/^VERSION_MAJOR/{a=$$2} /^VERSION_MINOR/{b=$$2} /^PATCHLEVEL/{c=$$2} \
	/^VERSION_TWEAK/{d=$$2} END{printf "%s.%s.%s%s", a, b, c, (d+0 ? "+" d : "")}' $(APP_DIR)/VERSION)
# $(1) build folder, $(2) extra CMake arguments, $(3) file name suffix
define ota_build
	@case "$(BOARD)" in enmt|enmt-dk) ;; *) echo "BOARD=$(BOARD) has no OTA slot: use enmt or enmt-dk"; exit 1;; esac
	@$(NCS) west build -p always -b $(TARGET) --sysbuild -d $(1) $(APP_DIR) -- $(2) $(BOARD_ARGS)
	@grep -q '^CONFIG_GATEWAY_OTA=y' $(1)/$(APP)/zephyr/.config || \
		{ echo "$(APP) is built without OTA (CONFIG_GATEWAY_OTA): no .ota image. Set APP=enocean-gateway or nuki-gateway"; exit 1; }
	@cp $(1)/$(APP)/zephyr/matter.ota $(1)/$(APP)-$(OTA_VER)-$(BOARD)$(3).ota
	@echo "OTA image: $(1)/$(APP)-$(OTA_VER)-$(BOARD)$(3).ota"
endef

ota: ## Pristine debug build and its Matter OTA image <app>-<version>-<board>-debug.ota (enmt, enmt-dk)
	$(call ota_build,$(BUILD),,-debug)

release-ota: ## Pristine release build and its Matter OTA image <app>-<version>-<board>.ota (enmt, enmt-dk)
	$(call ota_build,$(RELEASE),-DFILE_SUFFIX=release,)

diag: ## Build the diagnostics firmware (stack, heap, thread statistics) into build-diag
	@$(NCS) west build -b $(TARGET) --sysbuild -d $(DIAG) $(APP_DIR) -- -DEXTRA_CONF_FILE=diag.conf $(BOARD_ARGS)

diag-flash: diag ## Build and flash the diagnostics firmware
	@$(call flash_dir,$(DIAG))

test: ## Run the app's host unit tests (BTHome parser, ESP3/EEP parser, Nuki protocol)
	@$(foreach t,$(TESTS),$(MAKE) --no-print-directory -C $(t) &&) true

zap: ## Regenerate the Matter data model code after editing bridge.zap
	@$(NCS) cd $(APP_DIR) && west zap-generate -z src/default_zap/bridge.zap
	@# Enabled clusters decide which server sources CMake adds; make the next build re-run CMake.
	@touch $(APP_DIR)/CMakeLists.txt

term: ## Open the gateway shell (115200 baud; Ctrl+X quits). Close nRF Terminal first
	@test -n "$(PORT)" || { echo "No serial port found for BOARD=$(BOARD); set PORT=/dev/cu.usbmodem..."; exit 1; }
	@$(NCS) python3 -m serial.tools.miniterm --raw --eol CR --exit-char 24 $(PORT) 115200

identity: ## Show the board's Matter setup code (from the UF2 drive, the J-Link, or CHIP_ID=<16 hex digits>)
	@$(NCS) python3 scripts/make-uf2.py --identity $(BUILD) \
		$(if $(CHIP_ID),--chip-id $(CHIP_ID),$(if $(UF2),,--jlink))

netlog: ## Show a gateway's log over the network (debug builds); SERIAL=<part>, DEBUG=1, HOST=<IPv6>
	@python3 scripts/netlog.py $(if $(SERIAL),--serial $(SERIAL)) $(if $(DEBUG),--debug) $(if $(HOST),--host $(HOST))

hosts: ## List the Matter nodes with hostname, IPv6 addresses and status page (mDNS)
	@python3 scripts/matter-hosts.py

measure: ## Capture diagnostics (needs `make diag-flash`); MINUTES, INTERVAL, THERMOSTAT, TARGETS
	@$(NCS) python3 scripts/diag-capture.py --minutes $(MINUTES) --interval $(INTERVAL) \
		$(if $(THERMOSTAT),--thermostat $(THERMOSTAT) --targets $(TARGETS))

summary: ## Summarize the newest capture in measurements/
	@python3 scripts/diag-summary.py $$(ls -t measurements/diag-*.log | head -1)

clean: ## Delete the build folders of BOARD (build, build-diag, build-release) and the test build
	rm -rf $(BUILD) $(DIAG) $(RELEASE) $(addsuffix /build,$(TESTS))
