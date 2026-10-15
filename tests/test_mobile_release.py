from __future__ import annotations

import pytest
from scripts.android_release_manifest import verify_signing_identity

PIN = "ab" * 32
OTHER = "cd" * 32


@pytest.mark.parametrize(
    "signer",
    [
        f"Signer #1 certificate SHA-256 digest: {PIN}",
        f"Signer #1 certificate SHA-256 digest: {PIN.upper()}",
        f"V2 Signer: certificate SHA-256 digest: {PIN}",
        f"Signer (minSdkVersion=26, maxSdkVersion=32) #1 certificate SHA-256 digest: {PIN}\n"
        f"Signer (minSdkVersion=33) #1 certificate SHA-256 digest: {PIN}",
    ],
)
def test_apk_certificate_must_match_pin_across_tool_output_formats(signer):
    verify_signing_identity("Number of signers: 1\n" + signer, PIN)


@pytest.mark.parametrize(
    "output",
    [
        f"Number of signers: 1\nSigner #1 certificate SHA-256 digest: {OTHER}",
        f"Number of signers: 2\nSigner #1 certificate SHA-256 digest: {PIN}",
        "Number of signers: 1\n",
        f"Signer #1 certificate SHA-256 digest: {PIN}",
        f"Number of signers: 1\nSigner #1 certificate SHA-256 digest: {PIN}\n"
        f"Signer #2 certificate SHA-256 digest: {OTHER}",
    ],
)
def test_missing_different_or_multiple_apk_signers_fail_closed(output):
    with pytest.raises(ValueError):
        verify_signing_identity(output, PIN)


def test_source_stamp_does_not_replace_the_apk_signing_identity():
    verify_signing_identity(
        f"Number of signers: 1\nSigner #1 certificate SHA-256 digest: {PIN}\n"
        f"Source Stamp Signer certificate SHA-256 digest: {OTHER}",
        PIN,
    )
