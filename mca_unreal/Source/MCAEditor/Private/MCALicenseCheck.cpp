// MCA License Check — Offline license validation implementation.
//
// Ports the HMAC-SHA256 key validation from mca_core/license.py to C++.
// SHA-256 and HMAC are implemented inline (no OpenSSL dependency) to avoid
// header conflicts with UE's namespace definitions.

#include "MCALicenseCheck.h"

#include "HAL/PlatformTime.h"
#include "Misc/DateTime.h"
#include "Misc/ConfigCacheIni.h"


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
// Inline SHA-256 Implementation (FIPS 180-4)
// ============================================================================
// Self-contained to avoid OpenSSL header conflicts with UE's `namespace UI`.

namespace
{

// SHA-256 round constants.
static const uint32 K256[64] = {
	0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5,
	0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
	0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3,
	0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
	0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc,
	0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
	0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7,
	0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
	0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13,
	0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
	0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3,
	0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
	0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5,
	0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
	0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208,
	0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
};

FORCEINLINE uint32 RotR(uint32 X, int N) { return (X >> N) | (X << (32 - N)); }
FORCEINLINE uint32 Ch(uint32 X, uint32 Y, uint32 Z) { return (X & Y) ^ (~X & Z); }
FORCEINLINE uint32 Maj(uint32 X, uint32 Y, uint32 Z) { return (X & Y) ^ (X & Z) ^ (Y & Z); }
FORCEINLINE uint32 Sigma0(uint32 X) { return RotR(X, 2) ^ RotR(X, 13) ^ RotR(X, 22); }
FORCEINLINE uint32 Sigma1(uint32 X) { return RotR(X, 6) ^ RotR(X, 11) ^ RotR(X, 25); }
FORCEINLINE uint32 sigma0(uint32 X) { return RotR(X, 7) ^ RotR(X, 18) ^ (X >> 3); }
FORCEINLINE uint32 sigma1(uint32 X) { return RotR(X, 17) ^ RotR(X, 19) ^ (X >> 10); }

// Compute SHA-256 of an arbitrary-length message.
void ComputeSHA256(const uint8* Data, int32 DataLen, uint8 OutDigest[32])
{
	// Initial hash values (first 32 bits of the fractional parts of the
	// square roots of the first 8 primes).
	uint32 H[8] = {
		0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
		0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19,
	};

	// Pre-processing: pad the message to a multiple of 64 bytes.
	// Layout: message + 0x80 + zeros + 8-byte big-endian bit length.
	uint64 BitLen = (uint64)DataLen * 8;
	int32 PaddedLen = ((DataLen + 9 + 63) / 64) * 64;

	TArray<uint8> Padded;
	Padded.SetNumZeroed(PaddedLen);
	FMemory::Memcpy(Padded.GetData(), Data, DataLen);
	Padded[DataLen] = 0x80;

	// Append bit length as big-endian uint64 at the end.
	for (int32 i = 0; i < 8; ++i)
	{
		Padded[PaddedLen - 1 - i] = (uint8)(BitLen >> (i * 8));
	}

	// Process each 64-byte block.
	for (int32 Block = 0; Block < PaddedLen; Block += 64)
	{
		const uint8* M = Padded.GetData() + Block;

		// Prepare the message schedule (W[0..63]).
		uint32 W[64];
		for (int32 t = 0; t < 16; ++t)
		{
			W[t] = ((uint32)M[t * 4] << 24) | ((uint32)M[t * 4 + 1] << 16) |
			        ((uint32)M[t * 4 + 2] << 8) | (uint32)M[t * 4 + 3];
		}
		for (int32 t = 16; t < 64; ++t)
		{
			W[t] = sigma1(W[t - 2]) + W[t - 7] + sigma0(W[t - 15]) + W[t - 16];
		}

		// Initialize working variables.
		uint32 a = H[0], b = H[1], c = H[2], d = H[3];
		uint32 e = H[4], f = H[5], g = H[6], h = H[7];

		// 64 rounds.
		for (int32 t = 0; t < 64; ++t)
		{
			uint32 T1 = h + Sigma1(e) + Ch(e, f, g) + K256[t] + W[t];
			uint32 T2 = Sigma0(a) + Maj(a, b, c);
			h = g; g = f; f = e; e = d + T1;
			d = c; c = b; b = a; a = T1 + T2;
		}

		// Update hash values.
		H[0] += a; H[1] += b; H[2] += c; H[3] += d;
		H[4] += e; H[5] += f; H[6] += g; H[7] += h;
	}

	// Produce the 32-byte digest.
	for (int32 i = 0; i < 8; ++i)
	{
		OutDigest[i * 4 + 0] = (uint8)(H[i] >> 24);
		OutDigest[i * 4 + 1] = (uint8)(H[i] >> 16);
		OutDigest[i * 4 + 2] = (uint8)(H[i] >> 8);
		OutDigest[i * 4 + 3] = (uint8)(H[i]);
	}
}

} // anonymous namespace


// ============================================================================
// Crypto Helpers
// ============================================================================

TArray<uint8> FMCALicenseCheck::SHA256Hash(const TArray<uint8>& Data)
{
	uint8 Digest[32];
	ComputeSHA256(Data.GetData(), Data.Num(), Digest);

	TArray<uint8> Result;
	Result.Append(Digest, 32);
	return Result;
}


TArray<uint8> FMCALicenseCheck::ComputeHMAC(const TArray<uint8>& Data)
{
	// HMAC-SHA256 per RFC 2104.
	// Block size for SHA-256 is 64 bytes.
	constexpr int32 BlockSize = 64;

	// Prepare the key block (zero-padded to BlockSize).
	// Our key is 40 bytes, fits directly.
	TArray<uint8> KeyBlock;
	KeyBlock.SetNumZeroed(BlockSize);

	if (HMACSecretLen <= BlockSize)
	{
		FMemory::Memcpy(KeyBlock.GetData(), HMACSecret, HMACSecretLen);
	}
	else
	{
		// Key > block size: hash it first.
		TArray<uint8> KeyBytes;
		KeyBytes.Append(HMACSecret, HMACSecretLen);
		TArray<uint8> HashedKey = SHA256Hash(KeyBytes);
		FMemory::Memcpy(KeyBlock.GetData(), HashedKey.GetData(), FMath::Min(HashedKey.Num(), BlockSize));
	}

	// Inner hash: SHA256( (key XOR ipad) || data ).
	TArray<uint8> InnerInput;
	InnerInput.Reserve(BlockSize + Data.Num());
	for (int32 i = 0; i < BlockSize; ++i)
	{
		InnerInput.Add(KeyBlock[i] ^ 0x36);
	}
	InnerInput.Append(Data);
	TArray<uint8> InnerHash = SHA256Hash(InnerInput);

	// Outer hash: SHA256( (key XOR opad) || inner_hash ).
	TArray<uint8> OuterInput;
	OuterInput.Reserve(BlockSize + 32);
	for (int32 i = 0; i < BlockSize; ++i)
	{
		OuterInput.Add(KeyBlock[i] ^ 0x5c);
	}
	OuterInput.Append(InnerHash);
	TArray<uint8> FullHMAC = SHA256Hash(OuterInput);

	// Return only the first 6 bytes (48 bits), matching the Python implementation.
	TArray<uint8> Truncated;
	Truncated.Append(FullHMAC.GetData(), 6);
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
