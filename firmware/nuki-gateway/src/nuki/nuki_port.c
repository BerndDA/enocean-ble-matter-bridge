/*
 * Platform hooks of the Nuki protocol code (nuki_proto.h) on the device: SHA-256 and random
 * numbers from PSA Crypto, which the Matter stack has already initialized.
 */

#include "nuki_proto.h"

#include <psa/crypto.h>
#include <zephyr/logging/log.h>
#include <zephyr/random/random.h>

LOG_MODULE_DECLARE(nuki, CONFIG_GATEWAY_NUKI_LOG_LEVEL);

void nuki_sha256(uint8_t out[32], const uint8_t *a, size_t a_len, const uint8_t *b, size_t b_len)
{
	psa_hash_operation_t op = PSA_HASH_OPERATION_INIT;
	size_t len = 0;
	psa_status_t status = psa_hash_setup(&op, PSA_ALG_SHA_256);

	if (status == PSA_SUCCESS) {
		status = psa_hash_update(&op, a, a_len);
	}
	if (status == PSA_SUCCESS && b_len) {
		status = psa_hash_update(&op, b, b_len);
	}
	if (status == PSA_SUCCESS) {
		status = psa_hash_finish(&op, out, 32, &len);
	}
	if (status != PSA_SUCCESS) {
		/* Leaves a wrong digest: the lock then rejects the authenticator. */
		LOG_ERR("SHA-256 failed (%d)", (int)status);
		psa_hash_abort(&op);
	}
}

void randombytes(uint8_t *buf, unsigned long long len)
{
	if (psa_generate_random(buf, (size_t)len) != PSA_SUCCESS) {
		/* Not expected: Matter needs PSA's RNG as well. Fall back to the CSPRNG driver. */
		LOG_WRN("PSA random failed, using sys_csrand_get");
		if (sys_csrand_get(buf, (size_t)len) != 0) {
			LOG_ERR("No random numbers");
			k_panic();
		}
	}
}
