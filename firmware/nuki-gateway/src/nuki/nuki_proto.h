/*
 * Nuki Smart Lock BLE protocol: message framing, encryption, pairing math and
 * parsing of the replies the gateway uses. No Zephyr or Bluetooth code, so the
 * host tests (tests/host/nuki) cover it.
 *
 * Follows the Nuki Smart Lock API v2 (https://developer.nuki.io) as implemented
 * by NukiBleEsp32 (I-Connect, MIT), which nuki_hub and the ESP32 bridge use.
 *
 *   Plain message (pairing, GDIO characteristic):
 *     command (2, LE) | payload | CRC (2, LE)
 *   Encrypted message (after pairing, USDIO characteristic):
 *     nonce (24) | auth ID (4) | length (2) | secretbox(auth ID | command | payload | CRC)
 *
 * CRC: CRC-16/CCITT-FALSE (poly 0x1021, init 0xFFFF) over everything before it.
 * Encryption: NaCl secretbox (XSalsa20-Poly1305) with the key from pairing.
 * The platform supplies nuki_sha256() and randombytes() (nuki_port.c on the device).
 */

#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define NUKI_KEY_LEN 32
#define NUKI_NONCE_LEN 24
#define NUKI_CHALLENGE_LEN 32
#define NUKI_MAC_LEN 16 /* Poly1305 tag */
#define NUKI_NAME_LEN 32
#define NUKI_LOCK_ID_LEN 16

/* Header of an encrypted message: nonce, auth ID, length */
#define NUKI_ENC_HEADER_LEN (NUKI_NONCE_LEN + 4 + 2)
/* Largest message the gateway sends or accepts (the Config reply is the largest, ~100 bytes) */
#define NUKI_MAX_MSG_LEN 256
/* Largest payload of an encrypted message that fits NUKI_MAX_MSG_LEN */
#define NUKI_MAX_PAYLOAD_LEN (NUKI_MAX_MSG_LEN - NUKI_ENC_HEADER_LEN - NUKI_MAC_LEN - 4 - 2 - 2)

/* Command identifiers (the subset the gateway sends or receives) */
enum nuki_cmd {
	NUKI_CMD_REQUEST_DATA = 0x0001,
	NUKI_CMD_PUBLIC_KEY = 0x0003,
	NUKI_CMD_CHALLENGE = 0x0004,
	NUKI_CMD_AUTH_AUTHENTICATOR = 0x0005,
	NUKI_CMD_AUTH_DATA = 0x0006,
	NUKI_CMD_AUTH_ID = 0x0007,
	NUKI_CMD_KEYTURNER_STATES = 0x000C,
	NUKI_CMD_LOCK_ACTION = 0x000D,
	NUKI_CMD_STATUS = 0x000E,
	NUKI_CMD_ERROR_REPORT = 0x0012,
	NUKI_CMD_REQUEST_CONFIG = 0x0014,
	NUKI_CMD_CONFIG = 0x0015,
	NUKI_CMD_AUTH_ID_CONFIRMATION = 0x001E,
};

/* Payload of a Status message */
enum nuki_status {
	NUKI_STATUS_COMPLETE = 0x00,
	NUKI_STATUS_ACCEPTED = 0x01,
};

/* Error codes of an Error Report (selection) */
enum nuki_error {
	NUKI_ERROR_BAD_CRC = 0xFD,
	NUKI_ERROR_BAD_LENGTH = 0xFE,
	NUKI_ERROR_UNKNOWN = 0xFF,
	NUKI_ERROR_NOT_PAIRING = 0x10,
	NUKI_ERROR_BAD_AUTHENTICATOR = 0x11,
	NUKI_ERROR_BAD_PARAMETER = 0x12,
	NUKI_ERROR_MAX_USER = 0x13,
	NUKI_ERROR_NOT_AUTHORIZED = 0x20,
	NUKI_ERROR_BAD_PIN = 0x21,
	NUKI_ERROR_BAD_NONCE = 0x22,
	NUKI_ERROR_INVALID_AUTH_ID = 0x24,
	NUKI_ERROR_DISABLED = 0x25,
	NUKI_ERROR_REMOTE_NOT_ALLOWED = 0x26,
	NUKI_ERROR_POSITION_UNKNOWN = 0x41,
	NUKI_ERROR_MOTOR_BLOCKED = 0x42,
	NUKI_ERROR_CLUTCH_FAILURE = 0x43,
	NUKI_ERROR_MOTOR_TIMEOUT = 0x44,
	NUKI_ERROR_BUSY = 0x45,
	NUKI_ERROR_CANCELED = 0x46,
	NUKI_ERROR_NOT_CALIBRATED = 0x47,
	NUKI_ERROR_MOTOR_LOW_VOLTAGE = 0x49,
	NUKI_ERROR_VOLTAGE_TOO_LOW = 0x4C,
	NUKI_ERROR_FIRMWARE_UPDATE_NEEDED = 0x4D,
};

/* Authorization types for pairing */
enum nuki_id_type {
	NUKI_ID_TYPE_APP = 0,
	NUKI_ID_TYPE_BRIDGE = 1,
};

/* Lock actions */
enum nuki_lock_action {
	NUKI_ACTION_UNLOCK = 0x01,
	NUKI_ACTION_LOCK = 0x02,
	NUKI_ACTION_UNLATCH = 0x03,
	NUKI_ACTION_LOCK_N_GO = 0x04,
	NUKI_ACTION_LOCK_N_GO_UNLATCH = 0x05,
	NUKI_ACTION_FULL_LOCK = 0x06,
};

/* Lock states (Keyturner States, byte 1) */
enum nuki_lock_state {
	NUKI_LOCK_UNCALIBRATED = 0x00,
	NUKI_LOCK_LOCKED = 0x01,
	NUKI_LOCK_UNLOCKING = 0x02,
	NUKI_LOCK_UNLOCKED = 0x03,
	NUKI_LOCK_LOCKING = 0x04,
	NUKI_LOCK_UNLATCHED = 0x05,
	NUKI_LOCK_UNLOCKED_LOCK_N_GO = 0x06,
	NUKI_LOCK_UNLATCHING = 0x07,
	NUKI_LOCK_CALIBRATION = 0xFC,
	NUKI_LOCK_BOOT_RUN = 0xFD,
	NUKI_LOCK_MOTOR_BLOCKED = 0xFE,
	NUKI_LOCK_UNDEFINED = 0xFF,
};

/* Door sensor states (Keyturner States, byte 18) */
enum nuki_door_state {
	NUKI_DOOR_UNAVAILABLE = 0x00,
	NUKI_DOOR_DEACTIVATED = 0x01,
	NUKI_DOOR_CLOSED = 0x02,
	NUKI_DOOR_OPENED = 0x03,
	NUKI_DOOR_UNKNOWN = 0x04,
	NUKI_DOOR_CALIBRATING = 0x05,
	NUKI_DOOR_UNCALIBRATED = 0x10,
	NUKI_DOOR_TAMPERED = 0xF0,
	NUKI_DOOR_NONE = 0xFF, /* not in the message (older firmware) */
};

/* --- Framing ------------------------------------------------------------------------------------------------- */

uint16_t nuki_crc(const uint8_t *data, size_t len);

/* Builds a plain message into out. Returns its length, or 0 if it doesn't fit. */
size_t nuki_plain_build(uint8_t *out, size_t out_size, uint16_t cmd, const uint8_t *payload, size_t payload_len);

/*
 * Checks a plain message. On success (0) *cmd is the command and *payload points into msg.
 * Returns -1 if it is too short or the CRC is wrong.
 */
int nuki_plain_parse(const uint8_t *msg, size_t len, uint16_t *cmd, const uint8_t **payload, size_t *payload_len);

/*
 * Builds an encrypted message with a fresh random nonce. Returns its length, or 0 if it doesn't
 * fit (payload_len > NUKI_MAX_PAYLOAD_LEN or out_size too small).
 */
size_t nuki_encrypted_build(uint8_t *out, size_t out_size, const uint8_t key[NUKI_KEY_LEN], uint32_t auth_id,
			    uint16_t cmd, const uint8_t *payload, size_t payload_len);

/* Same, with a given nonce (for the tests). */
size_t nuki_encrypted_build_nonce(uint8_t *out, size_t out_size, const uint8_t key[NUKI_KEY_LEN],
				  uint32_t auth_id, const uint8_t nonce[NUKI_NONCE_LEN], uint16_t cmd,
				  const uint8_t *payload, size_t payload_len);

/*
 * Decrypts and checks an encrypted message. On success (0) the payload is copied to payload_out
 * (at most out_size bytes) and *auth_id, *cmd and *payload_len are set.
 * Returns -1 for a bad length, -2 if authentication fails, -3 for a bad CRC.
 */
int nuki_encrypted_parse(const uint8_t *msg, size_t len, const uint8_t key[NUKI_KEY_LEN], uint32_t *auth_id,
			 uint16_t *cmd, uint8_t *payload_out, size_t out_size, size_t *payload_len);

/* --- Pairing ------------------------------------------------------------------------------------------------- */

/* A Curve25519 key pair from randombytes(). */
void nuki_keypair(uint8_t public_key[NUKI_KEY_LEN], uint8_t secret_key[NUKI_KEY_LEN]);

/* The long-term key: HSalsa20 of the X25519 shared secret (NaCl crypto_box_beforenm). */
void nuki_shared_key(uint8_t key[NUKI_KEY_LEN], const uint8_t secret_key[NUKI_KEY_LEN],
		     const uint8_t remote_public_key[NUKI_KEY_LEN]);

/* HMAC-SHA256 with a 32-byte key. */
void nuki_hmac_sha256(uint8_t out[32], const uint8_t key[NUKI_KEY_LEN], const uint8_t *data, size_t len);

/* Authorization Authenticator payload: HMAC(key, own public key | lock public key | challenge). */
void nuki_pair_authenticator(uint8_t out[32], const uint8_t key[NUKI_KEY_LEN], const uint8_t own_pk[NUKI_KEY_LEN],
			     const uint8_t lock_pk[NUKI_KEY_LEN], const uint8_t challenge[NUKI_CHALLENGE_LEN]);

#define NUKI_AUTH_DATA_LEN (32 + 1 + 4 + NUKI_NAME_LEN + 32)

/*
 * Authorization Data payload (101 bytes): authenticator | ID type | app ID | name | nonce,
 * authenticator = HMAC(key, ID type | app ID | name | nonce | challenge).
 * nonce: 32 random bytes chosen by the caller.
 */
void nuki_pair_auth_data(uint8_t out[NUKI_AUTH_DATA_LEN], const uint8_t key[NUKI_KEY_LEN], uint8_t id_type,
			 uint32_t app_id, const char *name, const uint8_t nonce[32],
			 const uint8_t challenge[NUKI_CHALLENGE_LEN]);

/* Fields of the Authorization ID message (84 bytes: authenticator | auth ID | lock ID | nonce). */
struct nuki_auth_id {
	uint32_t auth_id;
	uint8_t lock_id[NUKI_LOCK_ID_LEN];
	uint8_t nonce[NUKI_CHALLENGE_LEN];
};

/* Returns 0, or -1 if the payload is too short. */
int nuki_parse_auth_id(const uint8_t *payload, size_t len, struct nuki_auth_id *out);

#define NUKI_AUTH_ID_CONFIRM_LEN (32 + 4)

/* Authorization ID Confirmation payload: HMAC(key, auth ID | nonce) | auth ID. */
void nuki_pair_auth_id_confirm(uint8_t out[NUKI_AUTH_ID_CONFIRM_LEN], const uint8_t key[NUKI_KEY_LEN],
			       uint32_t auth_id, const uint8_t nonce[NUKI_CHALLENGE_LEN]);

/* --- Replies ------------------------------------------------------------------------------------------------- */

struct nuki_keyturner_state {
	uint8_t nuki_state; /* 0 uninitialized, 1 pairing mode, 2 door mode, 4 maintenance */
	uint8_t lock_state; /* enum nuki_lock_state */
	uint8_t trigger;
	uint8_t battery_raw; /* critical battery state byte */
	uint8_t last_action;
	uint8_t last_trigger;
	uint8_t last_completion;
	uint8_t door_state; /* enum nuki_door_state; NUKI_DOOR_NONE if absent */
};

/* Returns 0, or -1 if the payload is shorter than the 18 bytes every lock sends. */
int nuki_parse_keyturner_state(const uint8_t *payload, size_t len, struct nuki_keyturner_state *out);

/* Battery charge in percent (0..100) from the critical battery state byte. */
uint8_t nuki_battery_percent(uint8_t battery_raw);
bool nuki_battery_critical(uint8_t battery_raw);
bool nuki_battery_charging(uint8_t battery_raw);

struct nuki_config {
	uint32_t nuki_id;
	char name[NUKI_NAME_LEN + 1];
	uint8_t firmware[3];
	uint8_t hardware[2];
};

/* Returns 0, or -1 if the payload is too short to hold the firmware and hardware versions. */
int nuki_parse_config(const uint8_t *payload, size_t len, struct nuki_config *out);

/* Error Report payload: error code, then the command it refers to. Returns 0, or -1 if too short. */
int nuki_parse_error(const uint8_t *payload, size_t len, uint8_t *error, uint16_t *cmd);

const char *nuki_lock_state_str(uint8_t lock_state);
const char *nuki_error_str(uint8_t error);

/* --- Advertisements ------------------------------------------------------------------------------------------ */

enum nuki_adv_kind {
	NUKI_ADV_OTHER = 0,
	NUKI_ADV_PAIRING, /* service data of the pairing service: the lock is in pairing mode */
	NUKI_ADV_PAIRING_ULTRA, /* the same for the Smart Lock Ultra / 5th generation (PIN pairing) */
	NUKI_ADV_BEACON, /* iBeacon with the keyturner service UUID */
};

struct nuki_adv {
	enum nuki_adv_kind kind;
	bool state_changed; /* beacon: bit 0 of the TX power byte, set while new state is waiting */
};

/* Parses advertising data (AD structures). */
void nuki_adv_parse(const uint8_t *data, size_t len, struct nuki_adv *out);

/* --- Platform ------------------------------------------------------------------------------------------------ */

/* SHA-256 of a | b (b may be empty). Supplied by the platform. */
void nuki_sha256(uint8_t out[32], const uint8_t *a, size_t a_len, const uint8_t *b, size_t b_len);

/* Fills buf with random bytes. Supplied by the platform (TweetNaCl calls it as well). */
void randombytes(uint8_t *buf, unsigned long long len);

#ifdef __cplusplus
}
#endif
