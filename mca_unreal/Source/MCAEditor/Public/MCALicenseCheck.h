// MCA License Check — Offline license validation for UE plugin.
//
// Ports the HMAC-SHA256 key validation from mca_core/license.py.
// Key format: MCA-XXXX-XXXX-XXXX-XXXX (base32-encoded, 10 bytes payload)
//
// Payload layout (10 bytes):
//     Bytes 0-1:  Expiry date (uint16 big-endian, days since 2025-01-01)
//     Byte 2:     Flags (bit 0 = perpetual)
//     Byte 3:     Serial number (0-255)
//     Bytes 4-9:  HMAC-SHA256 truncated to 6 bytes

#pragma once

#include "CoreMinimal.h"

/**
 * Result of a license key validation.
 */
struct FMCALicenseResult
{
	/** Whether the key is cryptographically valid AND not expired. */
	bool bValid;

	/** Whether the key never expires. */
	bool bPerpetual;

	/** Expiry date string (ISO format) or "never" if perpetual. */
	FString ExpiryDate;

	/** Days remaining until expiry, or -1 if perpetual. */
	int32 DaysRemaining;

	/** Human-readable error message if invalid. */
	FString Error;

	FMCALicenseResult()
		: bValid(false)
		, bPerpetual(false)
		, DaysRemaining(0)
	{
	}
};

/**
 * Overall license status for the editor.
 */
struct FMCALicenseStatus
{
	/** Has a valid license key. */
	bool bLicensed;

	/** Running in trial mode (no key, trial active). */
	bool bTrial;

	/** Days left on key or trial (-1 = perpetual). */
	int32 DaysRemaining;

	/** True if user must enter a key to proceed. */
	bool bNeedsKey;

	/** Human-readable status string for UI display. */
	FString Message;

	FMCALicenseStatus()
		: bLicensed(false)
		, bTrial(false)
		, DaysRemaining(0)
		, bNeedsKey(false)
	{
	}
};

/**
 * Offline license validation system.
 *
 * Mirrors the Python mca_core/license.py system so that license keys
 * work across both Maya and Unreal builds.
 */
class FMCALicenseCheck
{
public:

	/**
	 * Validate a license key string.
	 *
	 * Checks the HMAC-SHA256 signature, decodes the payload, and
	 * verifies the expiry date.
	 *
	 * @param KeyString The MCA-XXXX-XXXX-XXXX-XXXX key string.
	 * @return Validation result.
	 */
	static FMCALicenseResult ValidateKey(const FString& KeyString);

	/**
	 * Check the overall license status.
	 *
	 * Checks for a stored key first, then falls back to trial period.
	 * Stored key and trial state are persisted in UE's config system.
	 *
	 * @return License status.
	 */
	static FMCALicenseStatus CheckLicense();

	/**
	 * Store a validated license key in settings.
	 *
	 * Validates first, only stores if valid.
	 *
	 * @param KeyString The key to validate and store.
	 * @return Validation result.
	 */
	static FMCALicenseResult StoreKey(const FString& KeyString);

	/** Number of trial days. */
	static constexpr int32 TrialDays = 14;

private:

	// --- Crypto Helpers ----------------------------------------------------

	/** Compute HMAC-SHA256 and return the first 6 bytes. */
	static TArray<uint8> ComputeHMAC(const TArray<uint8>& Data);

	/** Full SHA-256 hash of a byte array. */
	static TArray<uint8> SHA256Hash(const TArray<uint8>& Data);

	// --- Base32 Helpers ----------------------------------------------------

	/** Decode a base32 string to raw bytes. */
	static bool Base32Decode(const FString& Input, TArray<uint8>& OutBytes);

	// --- Date Helpers ------------------------------------------------------

	/** Get days since the MCA epoch (2025-01-01). */
	static int32 DaysSinceEpoch();

	/** Convert epoch days to a Unix timestamp. */
	static double EpochDaysToUnix(int32 Days);

	// --- Settings Helpers --------------------------------------------------

	/** Get a string value from the editor's saved config. */
	static FString GetConfigString(const FString& Key, const FString& Default = TEXT(""));

	/** Set a string value in the editor's saved config. */
	static void SetConfigString(const FString& Key, const FString& Value);

	// --- Constants ---------------------------------------------------------

	/** HMAC signing key — must match mca_core/license.py. */
	static const uint8 HMACSecret[];
	static const int32 HMACSecretLen;

	/** Unix timestamp for 2025-01-01 00:00:00 UTC. */
	static constexpr double DateEpochUnix = 1735689600.0;

	/** Perpetual flag bit. */
	static constexpr uint8 FlagPerpetual = 0x01;
};
