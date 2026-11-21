MCU_SUB_VARIANT = nrf52840

# MATTER.TXT and INDEX.HTM with the gateway's pairing codes (enmt_identity.c, copied by build.sh)
CFLAGS += -DBOARD_IDENTITY_FILES
C_SRC += src/boards/enmt_identity.c $(TCRYPT_PATH)/source/sha256.c $(TCRYPT_PATH)/source/utils.c
IPATH += $(TCRYPT_PATH)/include

# SETTINGS.UF2: the app's settings partition (storage_partition of the UF2 layout,
# firmware/*/boards/promicro_nrf52840_nrf52840_uf2.overlay)
CFLAGS += -DBOARD_SETTINGS_ADDR=0xEA000 -DBOARD_SETTINGS_SIZE=0x8000

# No BLE OTA: it needs a SoftDevice, which the gateways' UF2 layout doesn't have (saves about 4.5 KB)
NO_BLE_OTA = 1
