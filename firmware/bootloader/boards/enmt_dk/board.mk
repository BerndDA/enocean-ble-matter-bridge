MCU_SUB_VARIANT = nrf52840

# MATTER.TXT and INDEX.HTM with the gateway's pairing codes (enmt_identity.c, copied by build.sh)
CFLAGS += -DBOARD_IDENTITY_FILES
C_SRC += src/boards/enmt_identity.c src/boards/enmt_settings.c $(TCRYPT_PATH)/source/sha256.c $(TCRYPT_PATH)/source/utils.c
IPATH += $(TCRYPT_PATH)/include

# SETTINGS.UF2: the app's settings partition (storage_partition of the UF2 layout,
# firmware/*/boards/promicro_nrf52840_nrf52840_uf2.overlay)
CFLAGS += -DBOARD_SETTINGS_ADDR=0xEA000 -DBOARD_SETTINGS_SIZE=0x8000

# No BLE OTA: it needs a SoftDevice, which the gateways' UF2 layout doesn't have (saves about 4.5 KB)
NO_BLE_OTA = 1

# BOOTLOAD.UF2: the installed bootloader as a bootloader update, to copy onto another board
CFLAGS += -DBOARD_BOOTLOADER_FILE

# Stage bootloader updates at 0xDF000-0xE9000 instead of 0xE0000-0xEA000, so they don't touch the
# gateways' factory data page at 0xE9000 (their app ends at 0xDF000)
CFLAGS += -DBOARD_BL_STAGING_ADDR=0xDF000

# RESTART.UF2: copied back onto the drive, the bootloader starts the app (e.g. after `gateway
# bootloader` from a remote shell, without a reset button)
CFLAGS += -DBOARD_RESTART_FILE

# Finish an update (and reset) only once the host has stopped writing for 1 s, so the copy ends
# without an I/O error on the host
CFLAGS += -DBOARD_FINISH_ON_IDLE

# Matter OTA: an image staged in the external QSPI flash is copied into place at boot
# (enmt_qspi_ota.c, enmt_ota.c; pins in board.h; OTA_PLAN.md)
CFLAGS += -DBOARD_QSPI_OTA
C_SRC += src/boards/enmt_ota.c src/boards/enmt_qspi_ota.c
