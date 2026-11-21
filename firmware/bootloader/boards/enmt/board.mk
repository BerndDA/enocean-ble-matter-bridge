MCU_SUB_VARIANT = nrf52840

# MATTER.TXT and INDEX.HTM with the gateway's pairing codes (enmt_identity.c, copied by build.sh)
CFLAGS += -DBOARD_IDENTITY_FILES
C_SRC += src/boards/enmt_identity.c $(TCRYPT_PATH)/source/sha256.c $(TCRYPT_PATH)/source/utils.c
IPATH += $(TCRYPT_PATH)/include
