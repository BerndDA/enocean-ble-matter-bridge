/*
 * Nuki Smart Lock BLE protocol. See nuki_proto.h.
 */

#include "nuki_proto.h"

#include "tweetnacl/tweetnacl.h"

#include <string.h>

/* The keyturner service UUID a92ee200-5501-11e4-916c-0800200c9a66, as the iBeacon carries it (big endian) */
static const uint8_t kBeaconUuid[16] = {0xa9, 0x2e, 0xe2, 0x00, 0x55, 0x01, 0x11, 0xe4,
					0x91, 0x6c, 0x08, 0x00, 0x20, 0x0c, 0x9a, 0x66};
/* Pairing service a92ee100-5501-11e4-916c-0800200c9a66 as in service data (little endian) */
static const uint8_t kPairingUuidLe[16] = {0x66, 0x9a, 0x0c, 0x20, 0x00, 0x08, 0x6c, 0x91,
					   0xe4, 0x11, 0x01, 0x55, 0x00, 0xe1, 0x2e, 0xa9};
/* Pairing service of the Smart Lock Ultra: a92ee300-... */
static const uint8_t kPairingUltraUuidLe[16] = {0x66, 0x9a, 0x0c, 0x20, 0x00, 0x08, 0x6c, 0x91,
						0xe4, 0x11, 0x01, 0x55, 0x00, 0xe3, 0x2e, 0xa9};

static void put_le16(uint8_t *p, uint16_t v)
{
	p[0] = (uint8_t)v;
	p[1] = (uint8_t)(v >> 8);
}

static void put_le32(uint8_t *p, uint32_t v)
{
	p[0] = (uint8_t)v;
	p[1] = (uint8_t)(v >> 8);
	p[2] = (uint8_t)(v >> 16);
	p[3] = (uint8_t)(v >> 24);
}

static uint16_t get_le16(const uint8_t *p)
{
	return (uint16_t)(p[0] | (p[1] << 8));
}

static uint32_t get_le32(const uint8_t *p)
{
	return (uint32_t)p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

/* --- Framing ------------------------------------------------------------------------------------------------- */

uint16_t nuki_crc(const uint8_t *data, size_t len)
{
	uint16_t crc = 0xFFFF;

	for (size_t i = 0; i < len; i++) {
		crc ^= (uint16_t)data[i] << 8;
		for (int b = 0; b < 8; b++) {
			crc = (crc & 0x8000) ? (uint16_t)((crc << 1) ^ 0x1021) : (uint16_t)(crc << 1);
		}
	}
	return crc;
}

size_t nuki_plain_build(uint8_t *out, size_t out_size, uint16_t cmd, const uint8_t *payload, size_t payload_len)
{
	const size_t len = 2 + payload_len + 2;

	if (len > out_size) {
		return 0;
	}
	put_le16(out, cmd);
	if (payload_len) {
		memcpy(&out[2], payload, payload_len);
	}
	put_le16(&out[2 + payload_len], nuki_crc(out, 2 + payload_len));
	return len;
}

int nuki_plain_parse(const uint8_t *msg, size_t len, uint16_t *cmd, const uint8_t **payload, size_t *payload_len)
{
	if (len < 4 || nuki_crc(msg, len - 2) != get_le16(&msg[len - 2])) {
		return -1;
	}
	*cmd = get_le16(msg);
	*payload = &msg[2];
	*payload_len = len - 4;
	return 0;
}

size_t nuki_encrypted_build_nonce(uint8_t *out, size_t out_size, const uint8_t key[NUKI_KEY_LEN],
				  uint32_t auth_id, const uint8_t nonce[NUKI_NONCE_LEN], uint16_t cmd,
				  const uint8_t *payload, size_t payload_len)
{
	/* NaCl's secretbox wants 32 zero bytes before the plaintext and leaves 16 before the ciphertext. */
	uint8_t plain[crypto_secretbox_ZEROBYTES + 4 + 2 + NUKI_MAX_PAYLOAD_LEN + 2];
	uint8_t cipher[sizeof(plain)];
	const size_t plain_len = 4 + 2 + payload_len + 2;
	const size_t enc_len = plain_len + NUKI_MAC_LEN;
	uint8_t *p = &plain[crypto_secretbox_ZEROBYTES];

	if (payload_len > NUKI_MAX_PAYLOAD_LEN || NUKI_ENC_HEADER_LEN + enc_len > out_size) {
		return 0;
	}

	memset(plain, 0, crypto_secretbox_ZEROBYTES);
	put_le32(p, auth_id);
	put_le16(&p[4], cmd);
	if (payload_len) {
		memcpy(&p[6], payload, payload_len);
	}
	put_le16(&p[6 + payload_len], nuki_crc(p, 6 + payload_len));

	crypto_secretbox(cipher, plain, crypto_secretbox_ZEROBYTES + plain_len, nonce, key);

	memcpy(out, nonce, NUKI_NONCE_LEN);
	put_le32(&out[NUKI_NONCE_LEN], auth_id);
	put_le16(&out[NUKI_NONCE_LEN + 4], (uint16_t)enc_len);
	memcpy(&out[NUKI_ENC_HEADER_LEN], &cipher[crypto_secretbox_BOXZEROBYTES], enc_len);
	return NUKI_ENC_HEADER_LEN + enc_len;
}

size_t nuki_encrypted_build(uint8_t *out, size_t out_size, const uint8_t key[NUKI_KEY_LEN], uint32_t auth_id,
			    uint16_t cmd, const uint8_t *payload, size_t payload_len)
{
	uint8_t nonce[NUKI_NONCE_LEN];

	randombytes(nonce, sizeof(nonce));
	return nuki_encrypted_build_nonce(out, out_size, key, auth_id, nonce, cmd, payload, payload_len);
}

int nuki_encrypted_parse(const uint8_t *msg, size_t len, const uint8_t key[NUKI_KEY_LEN], uint32_t *auth_id,
			 uint16_t *cmd, uint8_t *payload_out, size_t out_size, size_t *payload_len)
{
	uint8_t cipher[crypto_secretbox_BOXZEROBYTES + NUKI_MAX_MSG_LEN];
	uint8_t plain[sizeof(cipher)];

	if (len < NUKI_ENC_HEADER_LEN) {
		return -1;
	}
	const size_t enc_len = get_le16(&msg[NUKI_NONCE_LEN + 4]);

	/* At least auth ID, command and CRC behind the tag */
	if (enc_len < NUKI_MAC_LEN + 8 || enc_len > len - NUKI_ENC_HEADER_LEN || enc_len > NUKI_MAX_MSG_LEN) {
		return -1;
	}

	memset(cipher, 0, crypto_secretbox_BOXZEROBYTES);
	memcpy(&cipher[crypto_secretbox_BOXZEROBYTES], &msg[NUKI_ENC_HEADER_LEN], enc_len);
	if (crypto_secretbox_open(plain, cipher, crypto_secretbox_BOXZEROBYTES + enc_len, msg, key) != 0) {
		return -2;
	}

	const uint8_t *p = &plain[crypto_secretbox_ZEROBYTES];
	const size_t plain_len = enc_len - NUKI_MAC_LEN;

	if (nuki_crc(p, plain_len - 2) != get_le16(&p[plain_len - 2])) {
		return -3;
	}

	const size_t n = plain_len - 8;

	*auth_id = get_le32(p);
	*cmd = get_le16(&p[4]);
	*payload_len = n < out_size ? n : out_size;
	memcpy(payload_out, &p[6], *payload_len);
	return 0;
}

/* --- Pairing ------------------------------------------------------------------------------------------------- */

void nuki_keypair(uint8_t public_key[NUKI_KEY_LEN], uint8_t secret_key[NUKI_KEY_LEN])
{
	crypto_box_keypair(public_key, secret_key);
}

void nuki_shared_key(uint8_t key[NUKI_KEY_LEN], const uint8_t secret_key[NUKI_KEY_LEN],
		     const uint8_t remote_public_key[NUKI_KEY_LEN])
{
	crypto_box_beforenm(key, remote_public_key, secret_key);
}

void nuki_hmac_sha256(uint8_t out[32], const uint8_t key[NUKI_KEY_LEN], const uint8_t *data, size_t len)
{
	uint8_t pad[64];
	uint8_t inner[32];

	/* The key (32 bytes) is shorter than the block (64), so it is used zero-padded as is. */
	memset(pad, 0x36, sizeof(pad));
	for (size_t i = 0; i < NUKI_KEY_LEN; i++) {
		pad[i] ^= key[i];
	}
	nuki_sha256(inner, pad, sizeof(pad), data, len);

	memset(pad, 0x5c, sizeof(pad));
	for (size_t i = 0; i < NUKI_KEY_LEN; i++) {
		pad[i] ^= key[i];
	}
	nuki_sha256(out, pad, sizeof(pad), inner, sizeof(inner));
}

void nuki_pair_authenticator(uint8_t out[32], const uint8_t key[NUKI_KEY_LEN], const uint8_t own_pk[NUKI_KEY_LEN],
			     const uint8_t lock_pk[NUKI_KEY_LEN], const uint8_t challenge[NUKI_CHALLENGE_LEN])
{
	uint8_t r[NUKI_KEY_LEN * 2 + NUKI_CHALLENGE_LEN];

	memcpy(r, own_pk, NUKI_KEY_LEN);
	memcpy(&r[NUKI_KEY_LEN], lock_pk, NUKI_KEY_LEN);
	memcpy(&r[NUKI_KEY_LEN * 2], challenge, NUKI_CHALLENGE_LEN);
	nuki_hmac_sha256(out, key, r, sizeof(r));
}

void nuki_pair_auth_data(uint8_t out[NUKI_AUTH_DATA_LEN], const uint8_t key[NUKI_KEY_LEN], uint8_t id_type,
			 uint32_t app_id, const char *name, const uint8_t nonce[32],
			 const uint8_t challenge[NUKI_CHALLENGE_LEN])
{
	/* Signed data: ID type | app ID | name | nonce | challenge */
	uint8_t data[1 + 4 + NUKI_NAME_LEN + 32 + NUKI_CHALLENGE_LEN] = {0};
	const size_t name_len = strnlen(name, NUKI_NAME_LEN);

	data[0] = id_type;
	put_le32(&data[1], app_id);
	memcpy(&data[5], name, name_len);
	memcpy(&data[5 + NUKI_NAME_LEN], nonce, 32);
	memcpy(&data[5 + NUKI_NAME_LEN + 32], challenge, NUKI_CHALLENGE_LEN);

	/* Message: authenticator | ID type | app ID | name | nonce */
	nuki_hmac_sha256(out, key, data, sizeof(data));
	memcpy(&out[32], data, 1 + 4 + NUKI_NAME_LEN + 32);
}

int nuki_parse_auth_id(const uint8_t *payload, size_t len, struct nuki_auth_id *out)
{
	if (len < 32 + 4 + NUKI_LOCK_ID_LEN + NUKI_CHALLENGE_LEN) {
		return -1;
	}
	out->auth_id = get_le32(&payload[32]);
	memcpy(out->lock_id, &payload[36], NUKI_LOCK_ID_LEN);
	memcpy(out->nonce, &payload[36 + NUKI_LOCK_ID_LEN], NUKI_CHALLENGE_LEN);
	return 0;
}

void nuki_pair_auth_id_confirm(uint8_t out[NUKI_AUTH_ID_CONFIRM_LEN], const uint8_t key[NUKI_KEY_LEN],
			       uint32_t auth_id, const uint8_t nonce[NUKI_CHALLENGE_LEN])
{
	uint8_t data[4 + NUKI_CHALLENGE_LEN];

	put_le32(data, auth_id);
	memcpy(&data[4], nonce, NUKI_CHALLENGE_LEN);
	nuki_hmac_sha256(out, key, data, sizeof(data));
	put_le32(&out[32], auth_id);
}

/* --- Replies ------------------------------------------------------------------------------------------------- */

int nuki_parse_keyturner_state(const uint8_t *payload, size_t len, struct nuki_keyturner_state *out)
{
	/* 0 nuki state, 1 lock state, 2 trigger, 3..9 time, 10..11 time zone, 12 battery,
	 * 13 config update count, 14 lock 'n' go timer, 15 last action, 16 its trigger,
	 * 17 its completion status, 18 door sensor state (newer firmware), ... */
	if (len < 18) {
		return -1;
	}
	out->nuki_state = payload[0];
	out->lock_state = payload[1];
	out->trigger = payload[2];
	out->battery_raw = payload[12];
	out->last_action = payload[15];
	out->last_trigger = payload[16];
	out->last_completion = payload[17];
	out->door_state = len > 18 ? payload[18] : NUKI_DOOR_NONE;
	return 0;
}

uint8_t nuki_battery_percent(uint8_t battery_raw)
{
	const uint8_t pct = (uint8_t)((battery_raw & 0xFC) >> 1);

	return pct > 100 ? 100 : pct;
}

bool nuki_battery_critical(uint8_t battery_raw)
{
	return battery_raw & 0x01;
}

bool nuki_battery_charging(uint8_t battery_raw)
{
	return battery_raw & 0x02;
}

int nuki_parse_config(const uint8_t *payload, size_t len, struct nuki_config *out)
{
	/* 0 Nuki ID (4), 4 name (32), 36 latitude, 40 longitude, 44..48 settings, 49..55 time,
	 * 56 time zone offset, 58 DST, 59..62 fob, 63 single lock, 64 advertising mode,
	 * 65 has keypad, 66 firmware (3), 69 hardware (2), ... */
	if (len < 71) {
		return -1;
	}
	out->nuki_id = get_le32(payload);
	memcpy(out->name, &payload[4], NUKI_NAME_LEN);
	out->name[NUKI_NAME_LEN] = '\0';
	memcpy(out->firmware, &payload[66], 3);
	memcpy(out->hardware, &payload[69], 2);
	return 0;
}

int nuki_parse_error(const uint8_t *payload, size_t len, uint8_t *error, uint16_t *cmd)
{
	if (len < 3) {
		return -1;
	}
	*error = payload[0];
	*cmd = get_le16(&payload[1]);
	return 0;
}

const char *nuki_lock_state_str(uint8_t lock_state)
{
	switch (lock_state) {
	case NUKI_LOCK_UNCALIBRATED: return "uncalibrated";
	case NUKI_LOCK_LOCKED: return "locked";
	case NUKI_LOCK_UNLOCKING: return "unlocking";
	case NUKI_LOCK_UNLOCKED: return "unlocked";
	case NUKI_LOCK_LOCKING: return "locking";
	case NUKI_LOCK_UNLATCHED: return "unlatched";
	case NUKI_LOCK_UNLOCKED_LOCK_N_GO: return "unlocked (lock 'n' go)";
	case NUKI_LOCK_UNLATCHING: return "unlatching";
	case NUKI_LOCK_CALIBRATION: return "calibration";
	case NUKI_LOCK_BOOT_RUN: return "boot run";
	case NUKI_LOCK_MOTOR_BLOCKED: return "motor blocked";
	default: return "undefined";
	}
}

const char *nuki_error_str(uint8_t error)
{
	switch (error) {
	case NUKI_ERROR_BAD_CRC: return "bad CRC";
	case NUKI_ERROR_BAD_LENGTH: return "bad length";
	case NUKI_ERROR_UNKNOWN: return "unknown";
	case NUKI_ERROR_NOT_PAIRING: return "not in pairing mode";
	case NUKI_ERROR_BAD_AUTHENTICATOR: return "bad authenticator";
	case NUKI_ERROR_BAD_PARAMETER: return "bad parameter";
	case NUKI_ERROR_MAX_USER: return "too many users";
	case NUKI_ERROR_NOT_AUTHORIZED: return "not authorized";
	case NUKI_ERROR_BAD_PIN: return "bad PIN";
	case NUKI_ERROR_BAD_NONCE: return "bad nonce";
	case NUKI_ERROR_INVALID_AUTH_ID: return "invalid authorization ID";
	case NUKI_ERROR_DISABLED: return "authorization disabled";
	case NUKI_ERROR_REMOTE_NOT_ALLOWED: return "remote access not allowed";
	case NUKI_ERROR_POSITION_UNKNOWN: return "position unknown";
	case NUKI_ERROR_MOTOR_BLOCKED: return "motor blocked";
	case NUKI_ERROR_CLUTCH_FAILURE: return "clutch failure";
	case NUKI_ERROR_MOTOR_TIMEOUT: return "motor timeout";
	case NUKI_ERROR_BUSY: return "busy";
	case NUKI_ERROR_CANCELED: return "canceled";
	case NUKI_ERROR_NOT_CALIBRATED: return "not calibrated";
	case NUKI_ERROR_MOTOR_LOW_VOLTAGE: return "motor low voltage";
	case NUKI_ERROR_VOLTAGE_TOO_LOW: return "voltage too low";
	case NUKI_ERROR_FIRMWARE_UPDATE_NEEDED: return "firmware update needed";
	default: return "other";
	}
}

/* --- Advertisements ------------------------------------------------------------------------------------------ */

void nuki_adv_parse(const uint8_t *data, size_t len, struct nuki_adv *out)
{
	out->kind = NUKI_ADV_OTHER;
	out->state_changed = false;

	for (size_t i = 0; i + 1 < len;) {
		const uint8_t field_len = data[i];

		if (field_len == 0 || i + 1 + field_len > len) {
			return;
		}
		const uint8_t type = data[i + 1];
		const uint8_t *v = &data[i + 2];
		const size_t vlen = field_len - 1u;

		if (type == 0x21 && vlen >= 16) { /* service data, 128-bit UUID */
			if (memcmp(v, kPairingUuidLe, 16) == 0) {
				out->kind = NUKI_ADV_PAIRING;
				return;
			}
			if (memcmp(v, kPairingUltraUuidLe, 16) == 0) {
				out->kind = NUKI_ADV_PAIRING_ULTRA;
				return;
			}
		} else if (type == 0xFF && vlen == 25 && v[0] == 0x4C && v[1] == 0x00 && v[2] == 0x02 &&
			   v[3] == 0x15 && memcmp(&v[4], kBeaconUuid, 16) == 0) {
			/* Apple iBeacon: company 0x004C, type 0x02, length 0x15, UUID, major, minor, TX power */
			out->kind = NUKI_ADV_BEACON;
			out->state_changed = v[24] & 0x01;
			return;
		}
		i += 1u + field_len;
	}
}
