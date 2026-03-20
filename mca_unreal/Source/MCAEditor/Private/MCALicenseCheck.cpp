// MCA License Check — Offline license validation implementation.
//
// Ports the HMAC-SHA256 key validation from mca_core/license.py to C++.
// Uses OpenSSL (bundled with UE) for HMAC-SHA256 and UE's config system
// for persistence. No external dependencies beyond what UE ships.

#include "MCALicenseCheck.h"

#include "HAL/PlatformTime.h"
#include "Misc/DateTime.h"
#include "Misc/ConfigCacheIni.h"

THIRD_PARTY_INCLUDES_START
#include <openssl/hmac.h>
#include <openssl/sha.h>
THIRD_PARTY_INCLUDES_END


// --- HMAC Secret ---
// Must match _HMAC_SECRET in mca_core/license.py exactly.
// Compiled into the .dll so it's not human-readable in distribution.
const uint8 FMCALicenseCheck::HMACSecret[] = {
	'm', 'c', 'a', '-', 'e', 'd', 'i', 't', 'o', 'r',
	'-', '2', '0', '2', '6', '-', 'b', 'e', 't', 'a',
	'-', 'h', 'm', 'a', 'c', '-', 's', 'i', 'g', 'n',
	'i', 'n', 'g', '-', 'k', 'e', 'y', '-', 'v', '1'
};
const int32 FMCALicenseCheck::HMACSecretLen = 40;


// ============================================================================
// Crypto Helpers
// ============================================================================

TArray<uint8> FMCALicenseCheck::SHA256Hash(const TArray<uint8>& Data)
{
	// Full SHA-256 hash using OpenSSL.
	uint8 Digest[SHA256_DIGEST_LENGTH];
	SHA256(Data.GetData(), Data.Num(), Digest);

	TArray<uint8> Result;
	Result.Append(Digest, SHA256_DIGEST_LENGTH);
	return Result;
}


TArray<uint8> FMCALicenseCheck::ComputeHMAC(const TArray<uint8>& Data)
{
	// HMAC-SHA256 using OpenSSL, truncated to first 6 bytes.
	unsigned int DigestLen = 0;
	uint8 Digest[EVP_MAX_MD_SIZE];

	HMAC(
		EVP_sha256(),
		HMACSecret, HMACSecretLen,
		Data.GetData(), Data.Num(),
		Digest, &DigestLen
	);

	// Return only the first 6 bytes (48 bits), matching the Python implementation.
	TArray<uint8> Truncated;
	Truncated.Append(Digest, 6);
	return Truncated;
}


// ============================================================================
// Base32 Decoding
// ============================================================================

bool FMCALicenseCheck::Base32Decode(const FString& Input, TArray<uint8>& OutBytes)
{
	// RFC 4648 base32 alphabet: A-Z = 0-25, 2-7 = 26-31.
	// Decodes groups of 8 chars into 5 bytes.

	OutBytes.Empty();

	auto CharToValue = [](TCHAR C) -> int32
	{
		if (C >= TEXT('A') && C <= TEXT('Z')) return C - TEXT('A');
		if (C >= TEXT('a') && C <= TEXT('z')) return C - TEXT('a');
		if (C >= TEXT('2') && C <= TEXT('7')) return C - TEXT('2') + 26;
		return -1;
	};

	// Pad input to a multiple of 8 characters.
	FString Padded = Input;
	while (Padded.Len() % 8 != 0)
	{
		Padded += TEXT("=");
	}

	// Process in 8-character blocks.
	for (int32 i = 0; i < Padded.Len(); i += 8)
	{
		uint8 Values[8];
		int32 ValidCount = 0;

		for (int32 j = 0; j < 8; ++j)
		{
			TCHAR C = Padded[i + j];
			if (C == TEXT('='))
			{
				Values[j] = 0;
			}
			else
			{
				int32 Val = CharToValue(C);
				if (Val < 0)
				{
					return false;
				}
				Values[j] = (uint8)Val;
				ValidCount = j + 1;
			}
		}

		// Decode the 8 five-bit values into up to 5 bytes.
		uint8 Decoded[5];
		Decoded[0] = (Values[0] << 3) | (Values[1] >> 2);
		Decoded[1] = (Values[1] << 6) | (Values[2] << 1) | (Values[3] >> 4);
		Decoded[2] = (Values[3] << 4) | (Values[4] >> 1);
		Decoded[3] = (Values[4] << 7) | (Values[5] << 2) | (Values[6] >> 3);
		Decoded[4] = (Values[6] << 5) | Values[7];

		// Number of output bytes depends on how many valid input chars we had.
		int32 OutputCount = 0;
		if (ValidCount >= 2) OutputCount = 1;
		if (ValidCount >= 4) OutputCount = 2;
		if (ValidCount >= 5) OutputCount = 3;
		if (ValidCount >= 7) OutputCount = 4;
		if (ValidCount >= 8) OutputCount = 5;

		for (int32 j = 0; j < OutputCount; ++j)
		{
			OutBytes.Add(Decoded[j]);
		}
	}

	return true;
}


// ============================================================================
// Date Helpers
// ============================================================================

int32 FMCALicenseCheck::DaysSinceEpoch()
{
	// Current time as days since 2025-01-01 UTC.
	FDateTime Now = FDateTime::UtcNow();
	int64 UnixTimestamp = Now.ToUnixTimestamp();
	return (int32)((UnixTimestamp - (int64)DateEpochUnix) / 86400);
}


double FMCALicenseCheck::EpochDaysToUnix(int32 Days)
{
	return DateEpochUnix + ((double)Days * 86400.0);
}


// ============================================================================
// Settings Helpers
// ============================================================================

FString FMCALicenseCheck::GetConfigString(const FString& Key, const FString& Default)
{
	// Store license data in the editor's saved config under [MCAEditor].
	FString Value;
	if (GConfig && GConfig->GetString(TEXT("MCAEditor"), *Key, Value, GEditorPerProjectIni))
	{
		return Value;
	}
	return Default;
}


void FMCALicenseCheck::SetConfigString(const FString& Key, const FString& Value)
{
	if (GConfig)
	{
		GConfig->SetString(TEXT("MCAEditor"), *Key, *Value, GEditorPerProjectIni);
		GConfig->Flush(false, GEditorPerProjectIni);
	}
}


// ============================================================================
// Key Validation
// ============================================================================

FMCALicenseResult FMCALicenseCheck::ValidateKey(const FString& KeyString)
{
	FMCALicenseResult Result;

	// --- Clean up the key string ---
	FString Cleaned = KeyString.TrimStartAndEnd().ToUpper();

	// Strip the MCA- prefix if present.
	if (Cleaned.StartsWith(TEXT("MCA-")))
	{
		Cleaned = Cleaned.Mid(4);
	}

	// Remove all dashes.
	Cleaned.ReplaceInline(TEXT("-"), TEXT(""));

	// --- Validate character set (A-Z, 2-7 only) ---
	for (int32 i = 0; i < Cleaned.Len(); ++i)
	{
		TCHAR C = Cleaned[i];
		bool bValidChar = (C >= TEXT('A') && C <= TEXT('Z')) || (C >= TEXT('2') && C <= TEXT('7'));
		if (!bValidChar)
		{
			Result.Error = TEXT("Key contains invalid characters");
			return Result;
		}
	}

	// Must be exactly 16 base32 characters (encodes 10 bytes).
	if (Cleaned.Len() != 16)
	{
		Result.Error = FString::Printf(TEXT("Key payload must be 16 characters, got %d"), Cleaned.Len());
		return Result;
	}

	// --- Base32 decode ---
	TArray<uint8> KeyBytes;
	if (!Base32Decode(Cleaned, KeyBytes))
	{
		Result.Error = TEXT("Invalid key format");
		return Result;
	}

	if (KeyBytes.Num() != 10)
	{
		Result.Error = TEXT("Invalid key length");
		return Result;
	}

	// --- Split into payload (4 bytes) and signature (6 bytes) ---
	TArray<uint8> Payload;
	Payload.Append(KeyBytes.GetData(), 4);

	TArray<uint8> Signature;
	Signature.Append(KeyBytes.GetData() + 4, 6);

	// --- Verify HMAC signature ---
	TArray<uint8> ExpectedSig = ComputeHMAC(Payload);

	if (ExpectedSig.Num() != Signature.Num() ||
		FMemory::Memcmp(ExpectedSig.GetData(), Signature.GetData(), Signature.Num()) != 0)
	{
		Result.Error = TEXT("Invalid license key");
		return Result;
	}

	// --- Unpack the payload ---
	// Bytes 0-1: expiry days (uint16 big-endian).
	uint16 ExpiryDays = ((uint16)Payload[0] << 8) | (uint16)Payload[1];

	// Byte 2: flags.
	uint8 Flags = Payload[2];
	bool bIsPerpetual = (Flags & FlagPerpetual) != 0;

	// Byte 3: serial (not used for validation).

	Result.bPerpetual = bIsPerpetual;

	if (bIsPerpetual)
	{
		// Perpetual keys are always valid once the signature checks out.
		Result.bValid = true;
		Result.ExpiryDate = TEXT("never");
		Result.DaysRemaining = -1;
	}
	else
	{
		// Convert expiry days to a date string.
		double ExpiryUnix = EpochDaysToUnix((int32)ExpiryDays);
		FDateTime ExpiryDateTime = FDateTime::FromUnixTimestamp((int64)ExpiryUnix);
		Result.ExpiryDate = ExpiryDateTime.ToString(TEXT("%Y-%m-%d"));

		int32 Remaining = (int32)ExpiryDays - DaysSinceEpoch();
		Result.DaysRemaining = Remaining;

		if (Remaining < 0)
		{
			Result.bValid = false;
			Result.Error = FString::Printf(TEXT("License key expired on %s"), *Result.ExpiryDate);
		}
		else
		{
			Result.bValid = true;
		}
	}

	return Result;
}


// ============================================================================
// License Status Check
// ============================================================================

FMCALicenseStatus FMCALicenseCheck::CheckLicense()
{
	FMCALicenseStatus Status;

	// --- Check for a stored license key ---
	FString StoredKey = GetConfigString(TEXT("LicenseKey"));

	if (!StoredKey.IsEmpty())
	{
		FMCALicenseResult KeyResult = ValidateKey(StoredKey);

		if (KeyResult.bValid)
		{
			Status.bLicensed = true;
			Status.bTrial = false;
			Status.DaysRemaining = KeyResult.DaysRemaining;
			Status.bNeedsKey = false;

			if (KeyResult.bPerpetual)
			{
				Status.Message = TEXT("Licensed (perpetual)");
			}
			else
			{
				Status.Message = FString::Printf(TEXT("Licensed (expires %s)"), *KeyResult.ExpiryDate);
			}

			return Status;
		}

		// Stored key is invalid or expired — fall through to trial check.
		UE_LOG(LogTemp, Warning, TEXT("MCAEditor: Stored license key invalid: %s"), *KeyResult.Error);
	}

	// --- No valid key — check trial period ---
	FString FirstLaunchStr = GetConfigString(TEXT("FirstLaunchDate"));

	if (FirstLaunchStr.IsEmpty())
	{
		// First ever launch — start the trial clock.
		FDateTime Now = FDateTime::UtcNow();
		FirstLaunchStr = Now.ToIso8601();
		SetConfigString(TEXT("FirstLaunchDate"), FirstLaunchStr);

		UE_LOG(LogTemp, Log, TEXT("MCAEditor: Trial started — %d days"), TrialDays);

		Status.bLicensed = false;
		Status.bTrial = true;
		Status.DaysRemaining = TrialDays;
		Status.bNeedsKey = false;
		Status.Message = FString::Printf(TEXT("Trial (%d days remaining)"), TrialDays);
		return Status;
	}

	// --- Parse the stored first-launch date ---
	FDateTime FirstLaunch;
	if (!FDateTime::ParseIso8601(*FirstLaunchStr, FirstLaunch))
	{
		// Corrupted date — treat as expired for safety.
		UE_LOG(LogTemp, Warning, TEXT("MCAEditor: Corrupted FirstLaunchDate: %s"), *FirstLaunchStr);

		Status.bLicensed = false;
		Status.bTrial = false;
		Status.DaysRemaining = 0;
		Status.bNeedsKey = true;
		Status.Message = TEXT("Trial expired — please enter a license key");
		return Status;
	}

	// Calculate elapsed days.
	FTimespan Elapsed = FDateTime::UtcNow() - FirstLaunch;
	int32 ElapsedDays = (int32)Elapsed.GetTotalDays();
	int32 Remaining = TrialDays - ElapsedDays;

	if (Remaining > 0)
	{
		// Trial still active.
		Status.bLicensed = false;
		Status.bTrial = true;
		Status.DaysRemaining = Remaining;
		Status.bNeedsKey = false;
		Status.Message = FString::Printf(TEXT("Trial (%d days remaining)"), Remaining);
	}
	else
	{
		// Trial expired.
		Status.bLicensed = false;
		Status.bTrial = false;
		Status.DaysRemaining = 0;
		Status.bNeedsKey = true;
		Status.Message = TEXT("Trial expired — please enter a license key");
	}

	return Status;
}


// ============================================================================
// Key Storage
// ============================================================================

FMCALicenseResult FMCALicenseCheck::StoreKey(const FString& KeyString)
{
	FMCALicenseResult Result = ValidateKey(KeyString);

	if (Result.bValid)
	{
		// Store the cleaned key.
		FString CleanKey = KeyString.TrimStartAndEnd().ToUpper();
		SetConfigString(TEXT("LicenseKey"), CleanKey);

		UE_LOG(LogTemp, Log, TEXT("MCAEditor: License key stored (expires: %s)"), *Result.ExpiryDate);
	}
	else
	{
		UE_LOG(LogTemp, Warning, TEXT("MCAEditor: Attempted to store invalid key: %s"), *Result.Error);
	}

	return Result;
}
