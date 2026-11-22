/*
 * Host unit tests for the Nuki protocol (src/nuki/nuki_proto.c). Build and run with `make` in this folder.
 *
 * libsodium (Homebrew: brew install libsodium) is the reference: messages built with the gateway's
 * TweetNaCl code are opened with libsodium and the other way round, and libsodium plays the lock's
 * side of the pairing.
 */

#include "nuki_proto.h"

#include <sodium.h>

#include <stdio.h>
#include <string.h>

static int failures;
static int checks;

#define CHECK(cond)                                                                                \
	do {                                                                                       \
		checks++;                                                                          \
		if (!(cond)) {                                                                     \
			failures++;                                                                \
			printf("  FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond);                   \
		}                                                                                  \
	} while (0)

#define CHECK_EQ(a, b)                                                                             \
	do {                                                                                       \
		long long _a = (long long)(a), _b = (long long)(b);                                \
		checks++;                                                                          \
		if (_a != _b) {                                                                    \
			failures++;                                                                \
			printf("  FAIL %s:%d: %s == %lld, expected %lld\n", __FILE__, __LINE__, #a, \
			       _a, _b);                                                            \
		}                                                                                  \
	} while (0)

#define RUN(test)                                                                                  \
	do {                                                                                       \
		printf("%s\n", #test);                                                             \
		test();                                                                            \
	} while (0)

/* --- Platform hooks (nuki_port.c on the device) -------------------------------------------------------------- */

void nuki_sha256(uint8_t out[32], const uint8_t *a, size_t a_len, const uint8_t *b, size_t b_len)
{
	crypto_hash_sha256_state st;

	crypto_hash_sha256_init(&st);
	crypto_hash_sha256_update(&st, a, a_len);
	if (b_len) {
		crypto_hash_sha256_update(&st, b, b_len);
	}
	crypto_hash_sha256_final(&st, out);
}

void randombytes(uint8_t *buf, unsigned long long len)
{
	randombytes_buf(buf, (size_t)len);
}

/* --- Helpers ------------------------------------------------------------------------------------------------- */

static size_t from_hex(const char *hex, uint8_t *out, size_t max)
{
	size_t n = 0;

	while (hex[0] && hex[1] && n < max) {
		unsigned v;

		sscanf(hex, "%2x", &v);
		out[n++] = (uint8_t)v;
		hex += 2;
	}
	return n;
}

/* --- Framing ------------------------------------------------------------------------------------------------- */

static void test_crc_and_plain(void)
{
	/* The API documentation's example: Request Data for the public key is 01 00 03 00 27 A7. */
	const uint8_t payload[] = {0x03, 0x00};
	const uint8_t expected[] = {0x01, 0x00, 0x03, 0x00, 0x27, 0xA7};
	uint8_t msg[16];

	CHECK_EQ(nuki_plain_build(msg, sizeof(msg), NUKI_CMD_REQUEST_DATA, payload, sizeof(payload)), 6);
	CHECK(memcmp(msg, expected, sizeof(expected)) == 0);

	/* CRC-16/CCITT-FALSE check value */
	CHECK_EQ(nuki_crc((const uint8_t *)"123456789", 9), 0x29B1);

	uint16_t cmd;
	const uint8_t *p;
	size_t plen;

	CHECK_EQ(nuki_plain_parse(expected, sizeof(expected), &cmd, &p, &plen), 0);
	CHECK_EQ(cmd, NUKI_CMD_REQUEST_DATA);
	CHECK_EQ(plen, 2);
	CHECK_EQ(p[0], 0x03);

	uint8_t bad[sizeof(expected)];

	memcpy(bad, expected, sizeof(bad));
	bad[2] ^= 1;
	CHECK_EQ(nuki_plain_parse(bad, sizeof(bad), &cmd, &p, &plen), -1);
	CHECK_EQ(nuki_plain_parse(expected, 3, &cmd, &p, &plen), -1);
	CHECK_EQ(nuki_plain_build(msg, 5, NUKI_CMD_REQUEST_DATA, payload, sizeof(payload)), 0);
}

static void test_encrypted_against_libsodium(void)
{
	uint8_t key[32], nonce[24];
	const uint8_t payload[] = {0x0C, 0x00};
	uint8_t msg[NUKI_MAX_MSG_LEN];

	randombytes_buf(key, sizeof(key));
	randombytes_buf(nonce, sizeof(nonce));

	const size_t len = nuki_encrypted_build_nonce(msg, sizeof(msg), key, 0x11223344, nonce,
						      NUKI_CMD_REQUEST_DATA, payload, sizeof(payload));
	/* header 30 + tag 16 + auth ID 4 + command 2 + payload 2 + CRC 2 */
	CHECK_EQ(len, 30 + 16 + 10);
	CHECK(memcmp(msg, nonce, 24) == 0);
	CHECK_EQ(msg[24], 0x44);
	CHECK_EQ(msg[27], 0x11);
	CHECK_EQ(msg[28] | (msg[29] << 8), 16 + 10);

	/* libsodium opens it: auth ID | command | payload | CRC */
	uint8_t plain[64];

	CHECK_EQ(crypto_secretbox_open_easy(plain, &msg[30], len - 30, nonce, key), 0);
	const uint8_t expected_plain[] = {0x44, 0x33, 0x22, 0x11, 0x01, 0x00, 0x0C, 0x00};

	CHECK(memcmp(plain, expected_plain, sizeof(expected_plain)) == 0);
	CHECK_EQ(plain[8] | (plain[9] << 8), nuki_crc(plain, 8));

	/* A message sealed by libsodium (as the lock does) is opened by the gateway. */
	uint8_t lock_plain[4 + 2 + 3 + 2] = {0x44, 0x33, 0x22, 0x11, 0x0E, 0x00, 0x01, 0x02, 0x03};
	const uint16_t crc = nuki_crc(lock_plain, 9);

	lock_plain[9] = (uint8_t)crc;
	lock_plain[10] = (uint8_t)(crc >> 8);

	uint8_t lock_msg[128];

	randombytes_buf(lock_msg, 24);
	memcpy(&lock_msg[24], "\x44\x33\x22\x11", 4);
	lock_msg[28] = sizeof(lock_plain) + 16;
	lock_msg[29] = 0;
	crypto_secretbox_easy(&lock_msg[30], lock_plain, sizeof(lock_plain), lock_msg, key);

	const size_t lock_len = 30 + 16 + sizeof(lock_plain);
	uint32_t auth_id;
	uint16_t cmd;
	uint8_t out[16];
	size_t out_len;

	CHECK_EQ(nuki_encrypted_parse(lock_msg, lock_len, key, &auth_id, &cmd, out, sizeof(out), &out_len), 0);
	CHECK_EQ(auth_id, 0x11223344);
	CHECK_EQ(cmd, NUKI_CMD_STATUS);
	CHECK_EQ(out_len, 3);
	CHECK_EQ(out[2], 0x03);

	/* Tampered ciphertext, wrong key, bad lengths */
	lock_msg[40] ^= 0x80;
	CHECK_EQ(nuki_encrypted_parse(lock_msg, lock_len, key, &auth_id, &cmd, out, sizeof(out), &out_len), -2);
	lock_msg[40] ^= 0x80;
	key[0] ^= 1;
	CHECK_EQ(nuki_encrypted_parse(lock_msg, lock_len, key, &auth_id, &cmd, out, sizeof(out), &out_len), -2);
	key[0] ^= 1;
	CHECK_EQ(nuki_encrypted_parse(lock_msg, lock_len - 1, key, &auth_id, &cmd, out, sizeof(out), &out_len), -1);
	CHECK_EQ(nuki_encrypted_parse(lock_msg, 20, key, &auth_id, &cmd, out, sizeof(out), &out_len), -1);

	/* Bad CRC inside a correctly sealed message */
	lock_plain[9] ^= 1;
	crypto_secretbox_easy(&lock_msg[30], lock_plain, sizeof(lock_plain), lock_msg, key);
	CHECK_EQ(nuki_encrypted_parse(lock_msg, lock_len, key, &auth_id, &cmd, out, sizeof(out), &out_len), -3);

	/* Round trip with the gateway's own builder, a payload as long as allowed */
	uint8_t big[NUKI_MAX_PAYLOAD_LEN];
	uint8_t big_out[NUKI_MAX_PAYLOAD_LEN];

	randombytes_buf(big, sizeof(big));
	const size_t big_len = nuki_encrypted_build(msg, sizeof(msg), key, 7, NUKI_CMD_CONFIG, big, sizeof(big));

	CHECK_EQ(big_len, NUKI_MAX_MSG_LEN);
	CHECK_EQ(nuki_encrypted_parse(msg, big_len, key, &auth_id, &cmd, big_out, sizeof(big_out), &out_len), 0);
	CHECK_EQ(out_len, sizeof(big));
	CHECK(memcmp(big, big_out, sizeof(big)) == 0);
	CHECK_EQ(nuki_encrypted_build(msg, sizeof(msg), key, 7, NUKI_CMD_CONFIG, big, sizeof(big) + 1), 0);
}

/* --- Pairing ------------------------------------------------------------------------------------------------- */

static void test_shared_key(void)
{
	/* NaCl's crypto_box test vector (Alice's secret key, Bob's public key) */
	uint8_t alice_sk[32], bob_pk[32], expected[32], k[32];

	from_hex("77076d0a7318a57d3c16c17251b26645df4c2f87ebc0992ab177fba51db92c2a", alice_sk, 32);
	from_hex("de9edb7d7b7dc1b4d35b61c2ece435373f8343c85b78674dadfc7e146f882b4f", bob_pk, 32);
	from_hex("1b27556473e985d462cd51197a9a46c76009549eac6474f206c4ee0844f68389", expected, 32);
	nuki_shared_key(k, alice_sk, bob_pk);
	CHECK(memcmp(k, expected, 32) == 0);

	/* Both sides of a fresh key pair agree, and libsodium agrees */
	uint8_t gw_pk[32], gw_sk[32], lock_pk[32], lock_sk[32], k_gw[32], k_lock[32];

	nuki_keypair(gw_pk, gw_sk);
	crypto_box_keypair(lock_pk, lock_sk);
	nuki_shared_key(k_gw, gw_sk, lock_pk);
	CHECK_EQ(crypto_box_beforenm(k_lock, gw_pk, lock_sk), 0);
	CHECK(memcmp(k_gw, k_lock, 32) == 0);
}

static void test_hmac(void)
{
	uint8_t key[32], data[150], ours[32], ref[32];

	randombytes_buf(key, sizeof(key));
	randombytes_buf(data, sizeof(data));
	for (size_t len = 0; len <= sizeof(data); len += 25) {
		nuki_hmac_sha256(ours, key, data, len);
		crypto_auth_hmacsha256(ref, data, len, key);
		CHECK(memcmp(ours, ref, 32) == 0);
	}
}

/* The whole pairing, with the lock side computed independently with libsodium. */
static void test_pairing_flow(void)
{
	uint8_t gw_pk[32], gw_sk[32], lock_pk[32], lock_sk[32];
	uint8_t k_gw[32], k_lock[32];

	nuki_keypair(gw_pk, gw_sk);
	crypto_box_keypair(lock_pk, lock_sk);
	nuki_shared_key(k_gw, gw_sk, lock_pk);
	CHECK_EQ(crypto_box_beforenm(k_lock, gw_pk, lock_sk), 0);

	/* Step 1: authenticator over both public keys and the lock's first challenge */
	uint8_t challenge[32], auth[32], ref[32], r[96];

	randombytes_buf(challenge, sizeof(challenge));
	nuki_pair_authenticator(auth, k_gw, gw_pk, lock_pk, challenge);
	memcpy(r, gw_pk, 32);
	memcpy(&r[32], lock_pk, 32);
	memcpy(&r[64], challenge, 32);
	crypto_auth_hmacsha256(ref, r, sizeof(r), k_lock);
	CHECK(memcmp(auth, ref, 32) == 0);

	/* Step 2: authorization data for a second challenge */
	uint8_t nonce[32], data[NUKI_AUTH_DATA_LEN];

	randombytes_buf(challenge, sizeof(challenge));
	randombytes_buf(nonce, sizeof(nonce));
	nuki_pair_auth_data(data, k_gw, NUKI_ID_TYPE_APP, 2020003, "Thread Gateway", nonce, challenge);
	CHECK_EQ(data[32], NUKI_ID_TYPE_APP);
	CHECK_EQ(data[33] | (data[34] << 8) | (data[35] << 16) | ((uint32_t)data[36] << 24), 2020003);
	CHECK(memcmp(&data[37], "Thread Gateway", 14) == 0);
	CHECK_EQ(data[37 + 14], 0);
	CHECK(memcmp(&data[69], nonce, 32) == 0);

	uint8_t signed_data[101];

	memcpy(signed_data, &data[32], 69);
	memcpy(&signed_data[69], challenge, 32);
	crypto_auth_hmacsha256(ref, signed_data, sizeof(signed_data), k_lock);
	CHECK(memcmp(data, ref, 32) == 0);

	/* Step 3: the lock's authorization ID message */
	uint8_t auth_id_msg[84];
	struct nuki_auth_id id;

	randombytes_buf(auth_id_msg, sizeof(auth_id_msg));
	memcpy(&auth_id_msg[32], "\x2a\x00\x00\x00", 4);
	CHECK_EQ(nuki_parse_auth_id(auth_id_msg, sizeof(auth_id_msg), &id), 0);
	CHECK_EQ(id.auth_id, 42);
	CHECK(memcmp(id.lock_id, &auth_id_msg[36], 16) == 0);
	CHECK(memcmp(id.nonce, &auth_id_msg[52], 32) == 0);
	CHECK_EQ(nuki_parse_auth_id(auth_id_msg, 83, &id), -1);

	/* Step 4: confirmation */
	uint8_t confirm[NUKI_AUTH_ID_CONFIRM_LEN], c[36];

	nuki_pair_auth_id_confirm(confirm, k_gw, id.auth_id, id.nonce);
	memcpy(c, "\x2a\x00\x00\x00", 4);
	memcpy(&c[4], id.nonce, 32);
	crypto_auth_hmacsha256(ref, c, sizeof(c), k_lock);
	CHECK(memcmp(confirm, ref, 32) == 0);
	CHECK(memcmp(&confirm[32], "\x2a\x00\x00\x00", 4) == 0);
}

/* --- Replies ------------------------------------------------------------------------------------------------- */

static void test_keyturner_state(void)
{
	/* Door mode, unlocked, trigger button; battery 0x6E = 54 %, last action unlock; door closed */
	const uint8_t p[] = {0x02, 0x03, 0x02, 0xEA, 0x07, 0x0B, 0x16, 0x0A, 0x1E, 0x00, 0x3C, 0x00,
			     0x6E, 0x05, 0x00, 0x01, 0x02, 0x00, 0x02, 0x00, 0x00};
	struct nuki_keyturner_state s;

	CHECK_EQ(nuki_parse_keyturner_state(p, sizeof(p), &s), 0);
	CHECK_EQ(s.nuki_state, 2);
	CHECK_EQ(s.lock_state, NUKI_LOCK_UNLOCKED);
	CHECK_EQ(s.battery_raw, 0x6E);
	CHECK_EQ(nuki_battery_percent(s.battery_raw), 54);
	CHECK(!nuki_battery_critical(s.battery_raw));
	CHECK(nuki_battery_charging(s.battery_raw));
	CHECK_EQ(s.last_action, NUKI_ACTION_UNLOCK);
	CHECK_EQ(s.door_state, NUKI_DOOR_CLOSED);

	/* Older firmware: no door sensor byte */
	CHECK_EQ(nuki_parse_keyturner_state(p, 18, &s), 0);
	CHECK_EQ(s.door_state, NUKI_DOOR_NONE);
	CHECK_EQ(nuki_parse_keyturner_state(p, 17, &s), -1);

	CHECK_EQ(nuki_battery_percent(0xC8), 100);
	CHECK_EQ(nuki_battery_percent(0xFC), 100);
	CHECK(nuki_battery_critical(0x01));
}

static void test_config(void)
{
	uint8_t p[80] = {0};
	struct nuki_config c;

	p[0] = 0x78;
	p[1] = 0x56;
	p[2] = 0x34;
	p[3] = 0x12;
	memcpy(&p[4], "Front door", 10);
	p[66] = 4;
	p[67] = 10;
	p[68] = 5;
	p[69] = 8;
	p[70] = 3;
	CHECK_EQ(nuki_parse_config(p, sizeof(p), &c), 0);
	CHECK_EQ(c.nuki_id, 0x12345678);
	CHECK(strcmp(c.name, "Front door") == 0);
	CHECK_EQ(c.firmware[0], 4);
	CHECK_EQ(c.firmware[1], 10);
	CHECK_EQ(c.firmware[2], 5);
	CHECK_EQ(c.hardware[0], 8);
	CHECK_EQ(c.hardware[1], 3);
	CHECK_EQ(nuki_parse_config(p, 70, &c), -1);

	/* A name filling all 32 bytes stays terminated */
	memset(&p[4], 'x', 32);
	CHECK_EQ(nuki_parse_config(p, sizeof(p), &c), 0);
	CHECK_EQ(strlen(c.name), 32);

	uint8_t err;
	uint16_t cmd;
	const uint8_t e[] = {0x45, 0x0D, 0x00};

	CHECK_EQ(nuki_parse_error(e, sizeof(e), &err, &cmd), 0);
	CHECK_EQ(err, NUKI_ERROR_BUSY);
	CHECK_EQ(cmd, NUKI_CMD_LOCK_ACTION);
	CHECK_EQ(nuki_parse_error(e, 2, &err, &cmd), -1);
}

/* --- Advertisements ------------------------------------------------------------------------------------------ */

static void test_adv(void)
{
	struct nuki_adv a;

	/* Flags, then the iBeacon: 4C 00 02 15, UUID a92ee200-..., major, minor, TX power C4 / C5 */
	uint8_t beacon[3 + 27] = {0x02, 0x01, 0x06, 0x1A, 0xFF, 0x4C, 0x00, 0x02, 0x15,
				  0xa9, 0x2e, 0xe2, 0x00, 0x55, 0x01, 0x11, 0xe4, 0x91, 0x6c,
				  0x08, 0x00, 0x20, 0x0c, 0x9a, 0x66, 0x12, 0x34, 0x56, 0x78, 0xC4};

	nuki_adv_parse(beacon, sizeof(beacon), &a);
	CHECK_EQ(a.kind, NUKI_ADV_BEACON);
	CHECK(!a.state_changed);
	beacon[sizeof(beacon) - 1] = 0xC5;
	nuki_adv_parse(beacon, sizeof(beacon), &a);
	CHECK_EQ(a.kind, NUKI_ADV_BEACON);
	CHECK(a.state_changed);

	/* Another iBeacon UUID */
	beacon[9] = 0xa8;
	nuki_adv_parse(beacon, sizeof(beacon), &a);
	CHECK_EQ(a.kind, NUKI_ADV_OTHER);

	/* Service data for the pairing service a92ee100-... (UUID little endian, then data) */
	const uint8_t pairing[] = {0x02, 0x01, 0x06, 0x12, 0x21, 0x66, 0x9a, 0x0c, 0x20, 0x00, 0x08,
				   0x6c, 0x91, 0xe4, 0x11, 0x01, 0x55, 0x00, 0xe1, 0x2e, 0xa9, 0x00};

	nuki_adv_parse(pairing, sizeof(pairing), &a);
	CHECK_EQ(a.kind, NUKI_ADV_PAIRING);

	uint8_t ultra[sizeof(pairing)];

	memcpy(ultra, pairing, sizeof(ultra));
	ultra[18] = 0xe3;
	nuki_adv_parse(ultra, sizeof(ultra), &a);
	CHECK_EQ(a.kind, NUKI_ADV_PAIRING_ULTRA);

	/* Truncated and malformed data */
	nuki_adv_parse(pairing, 10, &a);
	CHECK_EQ(a.kind, NUKI_ADV_OTHER);
	const uint8_t zero_len[] = {0x00, 0x21, 0x66};

	nuki_adv_parse(zero_len, sizeof(zero_len), &a);
	CHECK_EQ(a.kind, NUKI_ADV_OTHER);
}

int main(void)
{
	if (sodium_init() < 0) {
		printf("libsodium init failed\n");
		return 1;
	}

	RUN(test_crc_and_plain);
	RUN(test_encrypted_against_libsodium);
	RUN(test_shared_key);
	RUN(test_hmac);
	RUN(test_pairing_flow);
	RUN(test_keyturner_state);
	RUN(test_config);
	RUN(test_adv);

	printf("%d checks, %d failures\n", checks, failures);
	return failures ? 1 : 0;
}
