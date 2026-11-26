/*
 * Matter OTA into the external QSPI flash for the EnMT UF2 bootloader, see gateway_ota.h and
 * OTA_PLAN.md. The requestor side (DefaultOTARequestor, BDXDownloader) is Matter's own, set up as
 * in NCS's samples/matter/common/src/dfu/ota/ota_util.cpp; the image processor replaces NCS's
 * MCUboot/DFU-target one (platform/nrfconnect/OTAImageProcessorImpl.cpp).
 *
 * The .ota payload is the raw app binary (zephyr.bin of a UF2-layout build). It goes to
 * ota_slot_partition 1 KB at a time, each 4 KB sector erased when the first write reaches it.
 * Finalize checks the payload against the .ota header's SHA-256 and only then writes the bootloader
 * header (enmt_ota.h) to ota_header_partition: that write commits the update. PrepareDownload and
 * Abort erase the header first, so a half-written slot is never behind a valid header.
 *
 * Stale sessions: the requestor talks to the provider over whatever secure session it finds to the
 * provider's node ID. matter-mqtt's provider (matter-controller's serve_ota) has the same node ID as
 * its controller, and we hold sessions to the controller too: the ones it started (its
 * subscription, the announce; we are CASE responder) and the one we start after a reboot to resume
 * its subscription (we are initiator). A QueryImage, ApplyUpdate or NotifyUpdateApplied sent on any
 * of those goes to the controller's socket, which never answers, and the requestor gives up. So:
 *   - before QueryImage and NotifyUpdateApplied, all sessions to the provider node are evicted, and
 *     the requestor opens a new one to the provider's own socket;
 *   - before ApplyUpdate, only the responder ones: the one initiator session left is the one the
 *     requestor opened for the query and the download.
 * Each evicted session first gets a CloseSession, so the controller drops it (and resubscribes)
 * at once instead of after its subscription's liveness timeout.
 * After an announcement the eviction waits kAnnounceAnswerDelay: the answer to the announce travels
 * on one of those sessions, and once it is evicted a lost answer can't be retransmitted.
 */

#include "gateway_ota.h"

#include "../../bootloader/enmt_ota.h"

#include "app/matter_event_handler.h"

#include <app/clusters/ota-requestor/BDXDownloader.h>
#include <app/clusters/ota-requestor/DefaultOTARequestor.h>
#include <app/clusters/ota-requestor/DefaultOTARequestorDriver.h>
#include <app/clusters/ota-requestor/DefaultOTARequestorStorage.h>
#include <app/server/Server.h>
#include <crypto/CHIPCryptoPAL.h>
#include <lib/core/OTAImageHeader.h>
#include <platform/CHIPDeviceLayer.h>
#include <platform/OTAImageProcessor.h>
#include <platform/nrfconnect/ExternalFlashManager.h>
#include <platform/nrfconnect/Reboot.h>
#include <protocols/secure_channel/Constants.h>
#include <protocols/secure_channel/StatusReport.h>

#include <zephyr/logging/log.h>
#include <zephyr/storage/flash_map.h>

#include <cstring>

LOG_MODULE_REGISTER(gateway_ota, CONFIG_CHIP_APP_LOG_LEVEL);

using namespace chip;
using namespace chip::DeviceLayer;

namespace Gateway::Ota
{
namespace
{

/* The app area of the UF2 layout (boards/promicro_nrf52840_nrf52840_uf2.overlay): 0x1000..0xdf000 */
constexpr uint32_t kAppStart = PARTITION_OFFSET(slot0_partition);
constexpr uint32_t kAppEnd = kAppStart + PARTITION_SIZE(slot0_partition);
constexpr size_t kWriteChunk = 1024;   /* slot writes: 4-byte aligned, divides the 4 KB sector */
constexpr size_t kMaxBlock = 1024;     /* DefaultOTARequestorDriver's max BDX block size */

static_assert(ENMT_OTA_PAGE % kWriteChunk == 0, "a write chunk must not cross a sector");

void PostOtaState(OtaState state)
{
	ChipDeviceEvent event;
	event.Type = DeviceEventType::kOtaStateChanged;
	event.OtaStateChanged.newState = state;
	(void)PlatformMgr().PostEvent(&event);
}

void DropStaleProviderSessions(const char *before, bool keepInitiator);

CHIP_ERROR FlashError(int rc)
{
	return rc == 0 ? CHIP_NO_ERROR : System::MapErrorZephyr(rc);
}

class StagingImageProcessor : public OTAImageProcessorInterface {
public:
	void SetDownloader(OTADownloader *downloader) { mDownloader = downloader; }

	CHIP_ERROR PrepareDownload() override;
	CHIP_ERROR Finalize() override;
	CHIP_ERROR Apply() override;
	CHIP_ERROR Abort() override;
	CHIP_ERROR ProcessBlock(ByteSpan &block) override;
	bool IsFirstImageRun() override;
	CHIP_ERROR ConfirmCurrentImage() override;

private:
	CHIP_ERROR Open();
	void Close();
	CHIP_ERROR EraseHeader();
	CHIP_ERROR PrepareDownloadImpl();
	CHIP_ERROR ProcessHeader(ByteSpan &block);
	CHIP_ERROR Write(const uint8_t *data, size_t size);
	CHIP_ERROR WriteChunk();
	CHIP_ERROR FinalizeImpl();
	void Fail(CHIP_ERROR err);

	OTADownloader *mDownloader = nullptr;
	const flash_area *mSlot = nullptr;
	const flash_area *mHeader = nullptr;

	OTAImageHeaderParser mHeaderParser;
	uint32_t mVersion = 0;
	bool mHasDigest = false;
	uint8_t mExpectedDigest[Crypto::kSHA256_Hash_Length];
	Crypto::Hash_SHA256_stream mHash;

	uint32_t mSlotOffset = 0; /* bytes written to the slot */
	size_t mChunkLen = 0;
	uint8_t mChunk[kWriteChunk] __aligned(4);
	uint8_t mBlock[kMaxBlock];
};

CHIP_ERROR StagingImageProcessor::Open()
{
	if (!mSlot) {
		ReturnErrorOnFailure(FlashError(flash_area_open(PARTITION_ID(ota_slot_partition), &mSlot)));
	}
	if (!mHeader) {
		ReturnErrorOnFailure(FlashError(flash_area_open(PARTITION_ID(ota_header_partition), &mHeader)));
	}
	ExternalFlashManager::GetInstance().DoAction(ExternalFlashManager::Action::WAKE_UP);
	return CHIP_NO_ERROR;
}

void StagingImageProcessor::Close()
{
	ExternalFlashManager::GetInstance().DoAction(ExternalFlashManager::Action::SLEEP);
}

CHIP_ERROR StagingImageProcessor::EraseHeader()
{
	return FlashError(flash_area_erase(mHeader, 0, ENMT_OTA_PAGE));
}

CHIP_ERROR StagingImageProcessor::PrepareDownload()
{
	VerifyOrReturnError(mDownloader != nullptr, CHIP_ERROR_INCORRECT_STATE);
	return SystemLayer().ScheduleLambda([this] {
		CHIP_ERROR err = PrepareDownloadImpl();
		if (err != CHIP_NO_ERROR) {
			LOG_ERR("OTA: prepare failed: %" CHIP_ERROR_FORMAT, err.Format());
			Close();
		}
		mDownloader->OnPreparedForDownload(err);
	});
}

CHIP_ERROR StagingImageProcessor::PrepareDownloadImpl()
{
	ReturnErrorOnFailure(Open());
	ReturnErrorOnFailure(EraseHeader());
	mHeaderParser.Init();
	mParams = {};
	mVersion = 0;
	mHasDigest = false;
	mSlotOffset = 0;
	mChunkLen = 0;
	ReturnErrorOnFailure(mHash.Begin());
	PostOtaState(kOtaDownloadInProgress);
	return CHIP_NO_ERROR;
}

/* The .ota header comes first; once decoded, the rest of the block is payload. */
CHIP_ERROR StagingImageProcessor::ProcessHeader(ByteSpan &block)
{
	VerifyOrReturnError(mHeaderParser.IsInitialized(), CHIP_NO_ERROR);

	OTAImageHeader header;
	CHIP_ERROR err = mHeaderParser.AccumulateAndDecode(block, header);
	VerifyOrReturnError(err != CHIP_ERROR_BUFFER_TOO_SMALL, CHIP_NO_ERROR); /* needs more data */
	ReturnErrorOnFailure(err);

	uint16_t vendorId = 0;
	uint16_t productId = 0;
	ReturnErrorOnFailure(GetDeviceInstanceInfoProvider()->GetVendorId(vendorId));
	ReturnErrorOnFailure(GetDeviceInstanceInfoProvider()->GetProductId(productId));
	if (header.mVendorId != vendorId || header.mProductId != productId) {
		LOG_ERR("OTA: image for %04x:%04x, this is %04x:%04x", header.mVendorId, header.mProductId,
			vendorId, productId);
		return CHIP_ERROR_INCORRECT_STATE;
	}
	if (header.mPayloadSize == 0 || header.mPayloadSize > mSlot->fa_size ||
	    header.mPayloadSize > kAppEnd - kAppStart) {
		LOG_ERR("OTA: payload of %u bytes doesn't fit", static_cast<unsigned>(header.mPayloadSize));
		return CHIP_ERROR_BUFFER_TOO_SMALL;
	}
	if (header.mImageDigestType != OTAImageDigestType::kSha256 ||
	    header.mImageDigest.size() != sizeof(mExpectedDigest)) {
		LOG_ERR("OTA: image without a SHA-256 digest");
		return CHIP_ERROR_INVALID_ARGUMENT;
	}
	memcpy(mExpectedDigest, header.mImageDigest.data(), sizeof(mExpectedDigest));
	mHasDigest = true;
	mVersion = header.mSoftwareVersion;
	mParams.totalFileBytes = header.mPayloadSize;
	LOG_INF("OTA: downloading version %u, %u bytes", static_cast<unsigned>(mVersion),
		static_cast<unsigned>(header.mPayloadSize));
	mHeaderParser.Clear(); /* header.mImageDigest pointed into the parser's buffer */
	return CHIP_NO_ERROR;
}

CHIP_ERROR StagingImageProcessor::WriteChunk()
{
	if (mSlotOffset % ENMT_OTA_PAGE == 0) {
		ReturnErrorOnFailure(FlashError(flash_area_erase(mSlot, mSlotOffset, ENMT_OTA_PAGE)));
	}
	/* The last chunk may be short: pad it to whole words with erased flash */
	size_t const len = (mChunkLen + 3) & ~size_t(3);
	memset(mChunk + mChunkLen, 0xff, len - mChunkLen);
	ReturnErrorOnFailure(FlashError(flash_area_write(mSlot, mSlotOffset, mChunk, len)));
	mSlotOffset += len;
	mChunkLen = 0;
	return CHIP_NO_ERROR;
}

CHIP_ERROR StagingImageProcessor::Write(const uint8_t *data, size_t size)
{
	VerifyOrReturnError(mParams.downloadedBytes + size <= mParams.totalFileBytes, CHIP_ERROR_BUFFER_TOO_SMALL);
	ReturnErrorOnFailure(mHash.AddData(ByteSpan(data, size)));
	mParams.downloadedBytes += size;
	while (size > 0) {
		size_t const n = std::min(size, kWriteChunk - mChunkLen);
		memcpy(mChunk + mChunkLen, data, n);
		mChunkLen += n;
		data += n;
		size -= n;
		if (mChunkLen == kWriteChunk) {
			ReturnErrorOnFailure(WriteChunk());
		}
	}
	return CHIP_NO_ERROR;
}

void StagingImageProcessor::Fail(CHIP_ERROR err)
{
	LOG_ERR("OTA: download failed: %" CHIP_ERROR_FORMAT, err.Format());
	mDownloader->EndDownload(err);
	PostOtaState(kOtaDownloadFailed);
}

CHIP_ERROR StagingImageProcessor::ProcessBlock(ByteSpan &block)
{
	VerifyOrReturnError(mDownloader != nullptr, CHIP_ERROR_INCORRECT_STATE);

	CHIP_ERROR err = ProcessHeader(block);
	if (err == CHIP_NO_ERROR && block.size() > sizeof(mBlock)) {
		err = CHIP_ERROR_BUFFER_TOO_SMALL;
	}
	if (err != CHIP_NO_ERROR) {
		SystemLayer().ScheduleLambda([this, err] { Fail(err); });
		return err;
	}

	/* The block is only valid during this call: copy it, fetch the next one, then write */
	size_t const size = block.size();
	memcpy(mBlock, block.data(), size);
	return SystemLayer().ScheduleLambda([this, size] {
		bool const last = mParams.totalFileBytes > 0 && mParams.downloadedBytes + size >= mParams.totalFileBytes;
		CHIP_ERROR e = last ? CHIP_NO_ERROR : mDownloader->FetchNextData();
		if (e == CHIP_NO_ERROR && size > 0) {
			e = Write(mBlock, size);
		}
		if (e != CHIP_NO_ERROR) {
			Fail(e);
		}
	});
}

CHIP_ERROR StagingImageProcessor::FinalizeImpl()
{
	VerifyOrReturnError(mHasDigest && mParams.downloadedBytes == mParams.totalFileBytes, CHIP_ERROR_INCORRECT_STATE);
	if (mChunkLen > 0) {
		ReturnErrorOnFailure(WriteChunk());
	}

	enmt_ota_header_t header = {};
	MutableByteSpan digest(header.sha256);
	ReturnErrorOnFailure(mHash.Finish(digest));
	if (memcmp(header.sha256, mExpectedDigest, sizeof(header.sha256)) != 0) {
		LOG_ERR("OTA: SHA-256 of the payload doesn't match the .ota header");
		return CHIP_ERROR_INTEGRITY_CHECK_FAILED;
	}

	/* Commit: from here on the bootloader installs the image at the next reset */
	header.magic = ENMT_OTA_MAGIC;
	header.header_version = ENMT_OTA_HEADER_VERSION;
	header.load_addr = kAppStart;
	header.size = static_cast<uint32_t>(mParams.totalFileBytes);
	header.sw_version = mVersion;
	static_assert(sizeof(header) % 4 == 0, "QSPI writes whole words");
	ReturnErrorOnFailure(FlashError(flash_area_write(mHeader, 0, &header, sizeof(header))));
	LOG_INF("OTA: version %u staged, %u bytes", static_cast<unsigned>(mVersion),
		static_cast<unsigned>(header.size));
	return CHIP_NO_ERROR;
}

CHIP_ERROR StagingImageProcessor::Finalize()
{
	return SystemLayer().ScheduleLambda([this] {
		CHIP_ERROR err = FinalizeImpl();
		Close();
		if (err != CHIP_NO_ERROR) {
			/* No header written: Apply() refuses, and the requestor reports the failure */
			LOG_ERR("OTA: finalize failed: %" CHIP_ERROR_FORMAT, err.Format());
			PostOtaState(kOtaDownloadFailed);
			return;
		}
		PostOtaState(kOtaDownloadComplete);
	});
}

CHIP_ERROR StagingImageProcessor::Abort()
{
	return SystemLayer().ScheduleLambda([this] {
		if (Open() == CHIP_NO_ERROR) {
			(void)EraseHeader();
		}
		Close();
		mHash.Clear();
		PostOtaState(kOtaDownloadAborted);
	});
}

CHIP_ERROR StagingImageProcessor::Apply()
{
	PostOtaState(kOtaApplyInProgress);

	/* Only reboot into the bootloader if a complete image has been committed */
	enmt_ota_header_t header;
	CHIP_ERROR err = Open();
	if (err == CHIP_NO_ERROR) {
		err = FlashError(flash_area_read(mHeader, 0, &header, sizeof(header)));
	}
	Close();
	if (err == CHIP_NO_ERROR && !enmt_ota_header_ok(&header, kAppStart, kAppEnd)) {
		err = CHIP_ERROR_INCORRECT_STATE;
	}
	if (err != CHIP_NO_ERROR) {
		LOG_ERR("OTA: nothing staged to apply");
		PostOtaState(kOtaApplyFailed);
		return err;
	}

	LOG_INF("OTA: rebooting into the bootloader to install version %u",
		static_cast<unsigned>(header.sw_version));
	return SystemLayer().StartTimer(
		System::Clock::Milliseconds32(CHIP_DEVICE_CONFIG_OTA_REQUESTOR_REBOOT_DELAY_MS),
		[](System::Layer *, void *) {
			PlatformMgr().HandleServerShuttingDown();
			k_msleep(CHIP_DEVICE_CONFIG_SERVER_SHUTDOWN_ACTIONS_SLEEP_MS);
			Reboot(SoftwareRebootReason::kSoftwareUpdate);
		},
		nullptr);
}

bool StagingImageProcessor::IsFirstImageRun()
{
	OTARequestorInterface *requestor = GetRequestorInstance();
	VerifyOrReturnError(requestor != nullptr, false);

	uint32_t currentVersion;
	VerifyOrReturnError(ConfigurationMgr().GetSoftwareVersion(currentVersion) == CHIP_NO_ERROR, false);

	return requestor->GetCurrentUpdateState() == OTARequestorInterface::OTAUpdateStateEnum::kApplying &&
	       requestor->GetTargetVersion() == currentVersion;
}

CHIP_ERROR StagingImageProcessor::ConfirmCurrentImage()
{
	/* Nothing to confirm: the bootloader verified the copy and erased the header. The driver
	 * sends NotifyUpdateApplied right after this. */
	DropStaleProviderSessions("NotifyUpdateApplied", false);
	PostOtaState(kOtaApplyComplete);
	return CHIP_NO_ERROR;
}

/* Tells the peer the session is closed (Matter Core 4.11.1.4): a StatusReport without MRP, as the
 * session is evicted right after. Best effort: if it is lost, the peer finds out by a timeout. */
void SendCloseSession(Transport::SecureSession *session)
{
	using namespace Protocols::SecureChannel;
	Messaging::ExchangeContext *ec =
		Server::GetInstance().GetExchangeManager().NewContext(SessionHandle(*session), nullptr);
	VerifyOrReturn(ec != nullptr);

	StatusReport report(GeneralStatusCode::kSuccess, Id, kProtocolCodeCloseSession);
	Encoding::LittleEndian::PacketBufferWriter buf(System::PacketBufferHandle::New(report.Size()));
	report.WriteToBuffer(buf);
	System::PacketBufferHandle msg = buf.Finalize();
	CHIP_ERROR err = msg.IsNull() ? CHIP_ERROR_NO_MEMORY
				      : ec->SendMessage(MsgType::StatusReport, std::move(msg),
							Messaging::SendFlags(Messaging::SendMessageFlags::kNoAutoRequestAck));
	if (err != CHIP_NO_ERROR) {
		ec->Close(); /* on success it has closed itself */
	}
}

/* Evicts sessions to the current provider's node (see the top): all of them, or with
 * keepInitiator only the ones the peer started. */
void DropStaleProviderSessions(const char *before, bool keepInitiator)
{
	OTARequestorInterface *requestor = GetRequestorInstance();
	VerifyOrReturn(requestor != nullptr);
	Optional<OTARequestorInterface::ProviderLocationType> provider;
	requestor->GetProviderLocation(provider);
	VerifyOrReturn(provider.HasValue());

	ScopedNodeId const node(provider.Value().providerNodeID, provider.Value().fabricIndex);
	unsigned dropped = 0;
	Server::GetInstance().GetSecureSessionManager().ForEachMatchingSession(node, [&](auto *session) {
		if (session->GetSecureSessionType() == Transport::SecureSession::Type::kCASE &&
		    !(keepInitiator && session->GetCryptoContext().IsInitiator())) {
			if (session->IsActiveSession()) {
				SendCloseSession(session);
			}
			session->MarkForEviction();
			dropped++;
		}
	});
	if (dropped > 0) {
		LOG_INF("OTA: dropped %u session(s) to the provider's node before %s", dropped, before);
	}
}

class StagingRequestorDriver : public DefaultOTARequestorDriver {
public:
	/* Both deferred: the requestor may call them from a callback on the session being evicted */
	void SendQueryImage() override
	{
		SystemLayer().CancelTimer(QueryImageNow, this);
		if (SystemLayer().StartTimer(kAnnounceAnswerDelay, QueryImageNow, this) != CHIP_NO_ERROR) {
			SystemLayer().ScheduleLambda([this] { QueryImageNow(nullptr, this); });
		}
	}

	void UpdateDownloaded() override
	{
		SystemLayer().ScheduleLambda([this] {
			DropStaleProviderSessions("ApplyUpdate", true);
			DefaultOTARequestorDriver::UpdateDownloaded();
		});
	}

private:
	/* Time for the announce's answer (and MRP retransmissions of it) before its session goes */
	static constexpr System::Clock::Timeout kAnnounceAnswerDelay = System::Clock::Seconds16(3);

	static void QueryImageNow(System::Layer *, void *context)
	{
		DropStaleProviderSessions("QueryImage", false);
		static_cast<StagingRequestorDriver *>(context)->DefaultOTARequestorDriver::SendQueryImage();
	}
};

DefaultOTARequestorStorage sRequestorStorage;
StagingRequestorDriver sRequestorDriver;
BDXDownloader sDownloader;
DefaultOTARequestor sRequestor;
StagingImageProcessor sImageProcessor;

void InitRequestor()
{
	VerifyOrReturn(GetRequestorInstance() == nullptr);

	sImageProcessor.SetDownloader(&sDownloader);
	sDownloader.SetImageProcessorDelegate(&sImageProcessor);
	sRequestorStorage.Init(Server::GetInstance().GetPersistentStorage());
	sRequestor.Init(Server::GetInstance(), sRequestorStorage, sRequestorDriver, sDownloader);
	SetRequestorInstance(&sRequestor);
	sRequestorDriver.Init(&sRequestor, &sImageProcessor);
	LOG_INF("OTA requestor ready (staging in QSPI flash)");
}

void EventHandler(const ChipDeviceEvent *event, intptr_t)
{
	if (event->Type == DeviceEventType::kServerReady) {
		InitRequestor();
	}
}

} // namespace

CHIP_ERROR Init()
{
	return Nrf::Matter::RegisterEventHandler(EventHandler, 0);
}

} // namespace Gateway::Ota
