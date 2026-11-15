/*
 * LaMetric Time client. See lametric.h.
 *
 * All state is under the OpenThread lock: the TCP callbacks run in the OpenThread context with it
 * held, the work item and the public functions take it. One request at a time; the work item
 * starts it, the callbacks fill in the result, and the work item finishes it (an endpoint is not
 * deinitialized inside its own callbacks).
 */

#include "lametric.h"

#include <platform/CHIPDeviceLayer.h>

#include <openthread/ip6.h>
#include <openthread/nat64.h>
#include <openthread/tcp.h>

#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>
#include <zephyr/net/openthread.h>
#include <zephyr/settings/settings.h>

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

LOG_MODULE_REGISTER(lametric, LOG_LEVEL_INF);

namespace Gateway::LaMetric
{
namespace
{
constexpr char kRadioApp[] = "com.lametric.radio";
constexpr int64_t kTimeoutMs = 10000;
constexpr uint32_t kRetryMinS = 30;
constexpr uint32_t kRetryMaxS = 600;
constexpr size_t kMaxApiKey = 72;

enum class Step : uint8_t { kScreensaver, kFindWidget, kRadio, kDone };
enum class Phase : uint8_t { kIdle, kConnecting, kWaiting, kFinished };

/* Settings, "lametric/..." */
struct Config {
	char mHost[40];
	uint16_t mPort = CONFIG_GATEWAY_LAMETRIC_PORT;
	char mApiKey[kMaxApiKey + 1];
	uint32_t mTrigger;
};

Config sConfig;
char sAuth[((4 + kMaxApiKey + 2) / 3) * 4 + 1]; /* base64 of "dev:<key>" */

/* What the clock should show, and what it was last set to (-1 = unknown) */
int8_t sWanted = -1;
int8_t sApplied = -1;
/* The steps towards sSequence; restarted when sWanted changes */
int8_t sSequence = -1;
Step sStep = Step::kScreensaver;
char sWidget[40];

/*
 * Picks one value out of a JSON response, byte by byte as it arrives: the string after "key"
 * (quoted), or the object body after "key" up to its '}' (not quoted). Enough for the flat
 * responses of the clock; the first match wins.
 */
struct Capture {
	const char *mKey;
	bool mQuoted;
	uint8_t mMatch;
	uint8_t mState; /* 0 = looking for the key, 1 = after it, 2 = in the value, 3 = done */
	size_t mLength;
	char mValue[64];

	void Reset()
	{
		mMatch = 0;
		mState = 0;
		mLength = 0;
		mValue[0] = '\0';
	}

	bool Done() const { return mState == 3; }

	void Feed(char ch)
	{
		switch (mState) {
		case 0:
			mMatch = (ch == mKey[mMatch]) ? mMatch + 1 : (ch == mKey[0] ? 1 : 0);
			if (mKey[mMatch] == '\0') {
				mState = 1;
			}
			break;
		case 1:
			if (ch == (mQuoted ? '"' : '{')) {
				mState = 2;
				mLength = 0;
			} else if (ch != ':' && ch != ' ' && ch != '\r' && ch != '\n' && ch != '\t' &&
				   !(mQuoted && ch == '{')) {
				/* Not the value we want (e.g. "widgets": {}): look further */
				mState = 0;
				mMatch = 0;
			}
			break;
		case 2:
			if (ch == (mQuoted ? '"' : '}')) {
				mValue[mLength] = '\0';
				mState = 3;
			} else if (mLength < sizeof(mValue) - 1) {
				mValue[mLength++] = ch;
			}
			break;
		default:
			break;
		}
	}
};

/* The request in flight */
otTcpEndpoint sEndpoint;
uint8_t sReceiveBuffer[1024];
char sRequest[640];
otLinkedBuffer sRequestBuffer;
Phase sPhase = Phase::kIdle;
Step sRequestStep;
int64_t sStartMs;
char sStatusLine[16];
size_t sStatusLength;
int sHttpStatus;
/* "widgets": { "<id>": ... }, "errors": [ { "message": "..." } ] */
Capture sWidgetCapture{ "\"widgets\"", true };
Capture sMessageCapture{ "\"message\"", true };

/* Retries */
uint32_t sRetryS = kRetryMinS;
int64_t sRetryAtMs;
int sLastHttpStatus;
char sLastError[112];
uint32_t sRequests;
uint32_t sFailures;

k_work_delayable sWork;

class OtLock {
public:
	OtLock() { chip::DeviceLayer::ThreadStackMgr().LockThreadStack(); }
	~OtLock() { chip::DeviceLayer::ThreadStackMgr().UnlockThreadStack(); }
};

void Base64(const uint8_t *in, size_t length, char *out)
{
	static const char kAlphabet[] = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

	for (size_t i = 0; i < length; i += 3) {
		const uint32_t v = (uint32_t(in[i]) << 16) | (i + 1 < length ? uint32_t(in[i + 1]) << 8 : 0) |
				   (i + 2 < length ? uint32_t(in[i + 2]) : 0);

		*out++ = kAlphabet[(v >> 18) & 0x3F];
		*out++ = kAlphabet[(v >> 12) & 0x3F];
		*out++ = i + 1 < length ? kAlphabet[(v >> 6) & 0x3F] : '=';
		*out++ = i + 2 < length ? kAlphabet[v & 0x3F] : '=';
	}
	*out = '\0';
}

void UpdateAuth()
{
	char plain[4 + kMaxApiKey + 1];
	const int n = snprintf(plain, sizeof(plain), "dev:%s", sConfig.mApiKey);

	Base64(reinterpret_cast<const uint8_t *>(plain), size_t(n), sAuth);
}

bool IsConfigured()
{
	return sConfig.mHost[0] && sConfig.mApiKey[0];
}

void Schedule(k_timeout_t delay)
{
	k_work_reschedule(&sWork, delay);
}

void SetError(const char *error)
{
	snprintf(sLastError, sizeof(sLastError), "%s", error);
}

/* The clock's address: an IPv6 address as is, an IPv4 address through the NAT64 prefix. */
bool ResolveHost(otIp6Address &out)
{
	otIp4Address ip4;

	if (otIp6AddressFromString(sConfig.mHost, &out) == OT_ERROR_NONE) {
		return true;
	}
	if (otIp4AddressFromString(sConfig.mHost, &ip4) != OT_ERROR_NONE) {
		SetError("host is not an IP address");
		return false;
	}
	if (otNat64SynthesizeIp6Address(openthread_get_default_instance(), &ip4, &out) != OT_ERROR_NONE) {
		SetError("no NAT64 prefix in the Thread network");
		return false;
	}
	return true;
}

/* --- OpenThread callbacks (OpenThread context, lock held) --- */

void OnEstablished(otTcpEndpoint *endpoint)
{
	sRequestBuffer = { nullptr, reinterpret_cast<const uint8_t *>(sRequest), strlen(sRequest) };
	sPhase = Phase::kWaiting;
	if (otTcpSendByReference(endpoint, &sRequestBuffer, 0) != OT_ERROR_NONE) {
		SetError("send failed");
		sPhase = Phase::kFinished;
		Schedule(K_NO_WAIT);
	}
}

void OnReceiveAvailable(otTcpEndpoint *endpoint, size_t, bool endOfStream, size_t)
{
	const otLinkedBuffer *buffer;
	size_t total = 0;

	if (otTcpReceiveByReference(endpoint, &buffer) != OT_ERROR_NONE) {
		return;
	}
	for (; buffer; buffer = buffer->mNext) {
		for (size_t i = 0; i < buffer->mLength; i++) {
			const char ch = char(buffer->mData[i]);

			if (sStatusLength < sizeof(sStatusLine) - 1) {
				sStatusLine[sStatusLength++] = ch;
			}
			if (sRequestStep == Step::kFindWidget) {
				sWidgetCapture.Feed(ch);
			}
			sMessageCapture.Feed(ch);
		}
		total += buffer->mLength;
	}
	otTcpCommitReceive(endpoint, total, 0);

	if (endOfStream && sPhase != Phase::kFinished) {
		sPhase = Phase::kFinished;
		Schedule(K_NO_WAIT);
	}
}

void OnDisconnected(otTcpEndpoint *, otTcpDisconnectedReason reason)
{
	if (sPhase == Phase::kConnecting) {
		SetError(reason == OT_TCP_DISCONNECTED_REASON_REFUSED ? "connection refused" : "cannot connect");
	}
	if (sPhase != Phase::kFinished) {
		sPhase = Phase::kFinished;
		Schedule(K_NO_WAIT);
	}
}

/* --- Work item (system work queue, lock held) --- */

bool StartRequest(Step step)
{
	const bool on = sSequence == 1;
	const char *method;
	char path[96];
	char body[96] = "";

	switch (step) {
	case Step::kScreensaver:
		/* Only "enabled": the clock keeps the screensaver modes and its brightness */
		method = "PUT";
		snprintf(path, sizeof(path), "/api/v2/device/display");
		snprintf(body, sizeof(body), "{\"screensaver\":{\"enabled\":%s}}", on ? "false" : "true");
		break;
	case Step::kFindWidget:
		method = "GET";
		snprintf(path, sizeof(path), "/api/v2/device/apps/%s", kRadioApp);
		break;
	case Step::kRadio:
		method = "POST";
		snprintf(path, sizeof(path), "/api/v2/device/apps/%s/widgets/%s/actions", kRadioApp, sWidget);
		snprintf(body, sizeof(body), "{\"id\":\"%s\"}", on ? "radio.play" : "radio.stop");
		break;
	default:
		return false;
	}

	const int n = snprintf(sRequest, sizeof(sRequest),
			       "%s %s HTTP/1.1\r\nHost: %s:%u\r\nAuthorization: Basic %s\r\n"
			       "Accept: application/json\r\n%sContent-Length: %u\r\nConnection: close\r\n\r\n%s",
			       method, path, sConfig.mHost, sConfig.mPort, sAuth,
			       body[0] ? "Content-Type: application/json\r\n" : "", unsigned(strlen(body)), body);
	if (n <= 0 || size_t(n) >= sizeof(sRequest)) {
		SetError("request too long");
		return false;
	}

	otSockAddr peer = {};

	if (!ResolveHost(peer.mAddress)) {
		return false;
	}
	peer.mPort = sConfig.mPort;

	otTcpEndpointInitializeArgs args = {};

	args.mEstablishedCallback = OnEstablished;
	args.mReceiveAvailableCallback = OnReceiveAvailable;
	args.mDisconnectedCallback = OnDisconnected;
	args.mReceiveBuffer = sReceiveBuffer;
	args.mReceiveBufferSize = sizeof(sReceiveBuffer);
	if (otTcpEndpointInitialize(openthread_get_default_instance(), &sEndpoint, &args) != OT_ERROR_NONE) {
		SetError("no TCP endpoint");
		return false;
	}

	sRequestStep = step;
	sStatusLength = 0;
	sHttpStatus = 0;
	sWidgetCapture.Reset();
	sMessageCapture.Reset();
	sLastError[0] = '\0';
	sStartMs = k_uptime_get();
	sPhase = Phase::kConnecting;
	sRequests++;

	if (otTcpConnect(&sEndpoint, &peer, OT_TCP_CONNECT_NO_FAST_OPEN) != OT_ERROR_NONE) {
		otTcpEndpointDeinitialize(&sEndpoint);
		sPhase = Phase::kIdle;
		SetError("connect failed");
		return false;
	}
	LOG_DBG("lametric: %s %s", method, path);
	Schedule(K_MSEC(kTimeoutMs));
	return true;
}

/* Ends the request; true if it did what it should. */
bool FinishRequest()
{
	otTcpAbort(&sEndpoint);
	otTcpEndpointDeinitialize(&sEndpoint);
	sPhase = Phase::kIdle;

	sStatusLine[sStatusLength] = '\0';
	if (strncmp(sStatusLine, "HTTP/1.", 7) == 0 && sStatusLength >= 12) {
		sHttpStatus = atoi(sStatusLine + 9);
	}
	sLastHttpStatus = sHttpStatus;

	if (sHttpStatus == 0) {
		if (!sLastError[0]) {
			SetError("no HTTP response");
		}
		return false;
	}
	if (sHttpStatus < 200 || sHttpStatus > 299) {
		snprintf(sLastError, sizeof(sLastError), "HTTP %d%s%s%s", sHttpStatus,
			 sHttpStatus == 401 ? " (wrong API key?)" : "", sMessageCapture.Done() ? ": " : "",
			 sMessageCapture.Done() ? sMessageCapture.mValue : "");
		/* The widget may be gone (radio app removed and added again): look it up anew. */
		if (sRequestStep == Step::kRadio && sHttpStatus == 404) {
			sWidget[0] = '\0';
		}
		return false;
	}
	if (sRequestStep == Step::kFindWidget) {
		if (!sWidgetCapture.Done() || !sWidgetCapture.mValue[0] ||
		    sWidgetCapture.mLength >= sizeof(sWidget)) {
			SetError("radio app not installed");
			return false;
		}
		snprintf(sWidget, sizeof(sWidget), "%s", sWidgetCapture.mValue);
		LOG_INF("lametric: radio widget %s", sWidget);
	}
	return true;
}

Step NextStep(Step done)
{
	switch (done) {
	case Step::kScreensaver:
		return sWidget[0] ? Step::kRadio : Step::kFindWidget;
	case Step::kFindWidget:
		return Step::kRadio;
	default:
		return Step::kDone;
	}
}

void Run(k_work *)
{
	OtLock lock;
	const int64_t now = k_uptime_get();

	if (sPhase == Phase::kConnecting || sPhase == Phase::kWaiting) {
		if (now - sStartMs < kTimeoutMs) {
			/* Woken early (a new power value): keep the timeout */
			Schedule(K_MSEC(kTimeoutMs - (now - sStartMs)));
			return;
		}
		SetError(sPhase == Phase::kConnecting ? "connect timeout" : "response timeout");
		sPhase = Phase::kFinished;
	}

	if (sPhase == Phase::kFinished) {
		if (FinishRequest()) {
			sStep = NextStep(sRequestStep);
			sRetryS = kRetryMinS;
			sRetryAtMs = 0;
			if (sStep == Step::kDone && sSequence == sWanted) {
				sApplied = sSequence;
				LOG_INF("lametric: %s", sApplied ? "screensaver off, radio plays"
								 : "screensaver on, radio stopped");
			}
		} else {
			sFailures++;
			LOG_WRN("lametric: request failed: %s, retry in %u s", sLastError, sRetryS);
			sRetryAtMs = now + int64_t(sRetryS) * 1000;
			sRetryS = MIN(sRetryS * 2, kRetryMaxS);
		}
	}

	if (sWanted < 0 || !IsConfigured()) {
		return;
	}
	if (sSequence != sWanted) {
		/* New target: start over (also after a retry wait, at once) */
		sSequence = sWanted;
		sStep = Step::kScreensaver;
		sRetryAtMs = 0;
		sRetryS = kRetryMinS;
	}
	if (sStep == Step::kDone) {
		return;
	}
	if (sRetryAtMs && now < sRetryAtMs) {
		Schedule(K_MSEC(sRetryAtMs - now));
		return;
	}
	if (!StartRequest(sStep)) {
		sFailures++;
		LOG_WRN("lametric: %s, retry in %u s", sLastError, sRetryS);
		sRetryAtMs = now + int64_t(sRetryS) * 1000;
		Schedule(K_SECONDS(sRetryS));
		sRetryS = MIN(sRetryS * 2, kRetryMaxS);
	}
}

void Want(bool on)
{
	sWanted = on ? 1 : 0;
	/* Already sent: nothing to do. Otherwise Run starts over, or carries on after the request in
	 * flight or the retry wait. */
	if (sSequence == sWanted && sStep == Step::kDone) {
		return;
	}
	Schedule(K_NO_WAIT);
}

/* --- Settings --- */

int LoadSetting(const char *key, size_t length, settings_read_cb read, void *arg, void *)
{
	if (strcmp(key, "host") == 0 && length < sizeof(sConfig.mHost)) {
		memset(sConfig.mHost, 0, sizeof(sConfig.mHost));
		read(arg, sConfig.mHost, length);
	} else if (strcmp(key, "key") == 0 && length < sizeof(sConfig.mApiKey)) {
		memset(sConfig.mApiKey, 0, sizeof(sConfig.mApiKey));
		read(arg, sConfig.mApiKey, length);
	} else if (strcmp(key, "port") == 0 && length == sizeof(sConfig.mPort)) {
		read(arg, &sConfig.mPort, length);
	} else if (strcmp(key, "trigger") == 0 && length == sizeof(sConfig.mTrigger)) {
		read(arg, &sConfig.mTrigger, length);
	}
	return 0;
}

void Save(const char *key, const void *value, size_t length)
{
	char name[24];

	snprintf(name, sizeof(name), "lametric/%s", key);
	if (settings_save_one(name, value, length) != 0) {
		LOG_ERR("lametric: cannot save %s", name);
	}
}
} /* namespace */

void Init()
{
	k_work_init_delayable(&sWork, Run);
	settings_load_subtree_direct("lametric", LoadSetting, nullptr);

	OtLock lock;
	UpdateAuth();
	if (IsConfigured()) {
		LOG_INF("lametric: %s:%u follows %08X", sConfig.mHost, sConfig.mPort, sConfig.mTrigger);
	}
}

void OnPower(uint32_t id, uint32_t watts)
{
	if (id == 0) {
		return;
	}
	OtLock lock;

	if (id != sConfig.mTrigger) {
		return;
	}
	if (watts >= CONFIG_GATEWAY_LAMETRIC_ON_W) {
		Want(true);
	} else if (watts == 0) {
		Want(false);
	}
}

bool SetHost(const char *host, uint16_t port)
{
	otIp6Address ip6;
	otIp4Address ip4;

	if (strlen(host) >= sizeof(sConfig.mHost) ||
	    (otIp6AddressFromString(host, &ip6) != OT_ERROR_NONE && otIp4AddressFromString(host, &ip4) != OT_ERROR_NONE)) {
		return false;
	}
	{
		OtLock lock;
		memset(sConfig.mHost, 0, sizeof(sConfig.mHost));
		strcpy(sConfig.mHost, host);
		sConfig.mPort = port;
		/* Another clock may have another widget */
		sWidget[0] = '\0';
		sApplied = -1;
		sSequence = -1;
		Schedule(K_NO_WAIT);
	}
	Save("host", sConfig.mHost, strlen(sConfig.mHost));
	Save("port", &sConfig.mPort, sizeof(sConfig.mPort));
	return true;
}

bool SetApiKey(const char *key)
{
	if (strlen(key) > kMaxApiKey) {
		return false;
	}
	{
		OtLock lock;
		memset(sConfig.mApiKey, 0, sizeof(sConfig.mApiKey));
		strcpy(sConfig.mApiKey, key);
		UpdateAuth();
		sApplied = -1;
		sSequence = -1;
		Schedule(K_NO_WAIT);
	}
	Save("key", sConfig.mApiKey, strlen(sConfig.mApiKey));
	return true;
}

void SetTrigger(uint32_t id)
{
	{
		OtLock lock;
		sConfig.mTrigger = id;
	}
	Save("trigger", &sConfig.mTrigger, sizeof(sConfig.mTrigger));
}

void Apply(bool on)
{
	OtLock lock;

	/* Send even if the clock is believed to be in that state already */
	sApplied = -1;
	sSequence = -1;
	sWanted = on ? 1 : 0;
	Schedule(K_NO_WAIT);
}

void GetStatus(Status &out)
{
	OtLock lock;
	const int64_t now = k_uptime_get();

	out = {};
	snprintf(out.mHost, sizeof(out.mHost), "%s", sConfig.mHost);
	out.mPort = sConfig.mPort;
	out.mHasApiKey = sConfig.mApiKey[0] != '\0';
	out.mTrigger = sConfig.mTrigger;
	out.mWanted = sWanted;
	out.mApplied = sApplied;
	out.mBusy = sPhase != Phase::kIdle;
	snprintf(out.mWidget, sizeof(out.mWidget), "%s", sWidget);
	out.mLastHttpStatus = sLastHttpStatus;
	snprintf(out.mLastError, sizeof(out.mLastError), "%s", sLastError);
	out.mRetryInS = (sRetryAtMs && sRetryAtMs > now && sStep != Step::kDone) ? uint32_t((sRetryAtMs - now) / 1000) : 0;
	out.mRequests = sRequests;
	out.mFailures = sFailures;
}

} /* namespace Gateway::LaMetric */
