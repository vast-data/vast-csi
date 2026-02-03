"""Tests for NFS mTLS functionality using kernel keyring."""

import pytest
from unittest.mock import patch, MagicMock

from vast_csi.mtls_utils import (
    get_nfs_keyring_id,
    NFS_KEYRING_NAME,
    pem_to_der,
    load_pem_to_keyring,
    delete_from_keyring,
    load_mtls_credentials,
    delete_mtls_credentials,
    MtlsManager,
    get_xprtsec_from_mount_options,
)
from vast_csi.exceptions import XprtsecValidationError


# Sample PEM certificates for testing
# Valid self-signed certificate for testing (generated with openssl req -x509 -newkey rsa:2048 -nodes -days 365)
SAMPLE_CERT_PEM = """-----BEGIN CERTIFICATE-----
MIIDozCCAougAwIBAgIUHlXFVaNiVzG8amaL0D+AggsTnXIwDQYJKoZIhvcNAQEL
BQAwYTELMAkGA1UEBhMCVVMxEjAQBgNVBAgMCVRlc3RTdGF0ZTERMA8GA1UEBwwI
VGVzdENpdHkxEDAOBgNVBAoMB1Rlc3RPcmcxGTAXBgNVBAMMEHRlc3QuZXhhbXBs
ZS5jb20wHhcNMjYwMjAzMTMwMzA4WhcNMjcwMjAzMTMwMzA4WjBhMQswCQYDVQQG
EwJVUzESMBAGA1UECAwJVGVzdFN0YXRlMREwDwYDVQQHDAhUZXN0Q2l0eTEQMA4G
A1UECgwHVGVzdE9yZzEZMBcGA1UEAwwQdGVzdC5leGFtcGxlLmNvbTCCASIwDQYJ
KoZIhvcNAQEBBQADggEPADCCAQoCggEBAONGGJN0mZE9eEnnQSgs1Js6YBfxIGnK
htW5nPbk1Dme77wZ6zb9b6DxAIp6XcrPZx3o8BJcMN0QkP9OX2Ipd93YwPF2E5Hd
FUX4SxInvNF8lMzrVtnKhGYfZF0Qmo5qWUgWhvgs6Od5fGFs76xZAu15WlOBOhJi
Y7/zJm/z3W5PoQv34lPn9r3aAJhtu9EbputNxpEgPASzFlIE8AcOOR9ucL7DqsDr
9HPDg612Dyi8His6NpoZ9aKLzpAO86QWnNVwgdILoHrgelRGB7xrstXwRGDA35x0
iKup4olF6iwIk8eQirBT0f4aWEceqWmDYWw7hBDe9ssvVrPdc2Qs75ECAwEAAaNT
MFEwHQYDVR0OBBYEFFte4oir9n4znonAMMCeYlAcceJ5MB8GA1UdIwQYMBaAFFte
4oir9n4znonAMMCeYlAcceJ5MA8GA1UdEwEB/wQFMAMBAf8wDQYJKoZIhvcNAQEL
BQADggEBAMXtEJWPXMFq7Yh81jmXGgk+gO3F/nUEIwNm8w9eCkC5EcvResVSAwyY
EBHWeiuiInAinVjNVWF/WjFEdCNHdsB9Gt3Nn/DOD05qHnuNi1WXfpIKu1IaoxAR
Ccm+7xgsh9EhMyWgao5Gz33F4IpCANeFkK17vMJoj3rju5QykPXol+wk/tuXUNyk
DGdOtJplVysgnuiSyWA0bgywHFYQKWSqAd1yxDNCXdwiZUrv5VDtuD/L8EmcsEBe
6IEvzgKzbQJ0vMRVfrBVIbRVd24qdpOd1vaBVK1/QC7vk8RfBZri9SgcNxk1AVB3
RRg5GJI6gCPZ8i2LqIFGplY9A3MrIoo=
-----END CERTIFICATE-----"""

# Valid RSA private key for testing (PKCS#8 format, matches the certificate above)
SAMPLE_KEY_PEM = """-----BEGIN PRIVATE KEY-----
MIIEvgIBADANBgkqhkiG9w0BAQEFAASCBKgwggSkAgEAAoIBAQDjRhiTdJmRPXhJ
50EoLNSbOmAX8SBpyobVuZz25NQ5nu+8Ges2/W+g8QCKel3Kz2cd6PASXDDdEJD/
Tl9iKXfd2MDxdhOR3RVF+EsSJ7zRfJTM61bZyoRmH2RdEJqOallIFob4LOjneXxh
bO+sWQLteVpTgToSYmO/8yZv891uT6EL9+JT5/a92gCYbbvRG6brTcaRIDwEsxZS
BPAHDjkfbnC+w6rA6/Rzw4Otdg8ovB4rOjaaGfWii86QDvOkFpzVcIHSC6B64HpU
Rge8a7LV8ERgwN+cdIirqeKJReosCJPHkIqwU9H+GlhHHqlpg2FsO4QQ3vbLL1az
3XNkLO+RAgMBAAECggEAIBVleMN4E68iy66wCF+JGpS7ZgXYdowW9sA/hAG6Ypv+
PzFFfuYjcQvfRgKPj7GHCWDjKyRakt/jfYxvHf4OpCxqKGwWcnv2+dawT6gjw/Wb
UpunuhJtwwuMG9sxMQjwVk3f0H8T2JbSKTVmAZAwlUeRVG0kvohR3pIRC12DaoPi
X73FUtk26M+Pxj3/3H9hSgS0b0+vNPy6xVA9brGdmReIJo46J6T0//aD3JfD6T70
9oLbpoh6X+tPW/hx7PUMssxm59pY+0upjhcooNd3fLA9btHFNpdvQM5JD1AcFI8y
iJroRwH/fAdhNTwITXN3y3QiuTRelSTLbw9FBbOIxQKBgQD9Zfl03hVjQRBe7of1
Qb5AF4L8tGU0X0Z2uUgsxhnL0qK1kPsp5RDUNIC9pGPPngO1hIxXdHqGciuNC+Zl
S7cQU3uxb9c8O626N3259Ls6/0TgnNXu0axmAXqTaY74l+Z1ZtOeCjVmLDoTfMlx
7dVvDG9uxa7jsQIpu2+K2fBFJwKBgQDlm3Tf8cW5pQa2UhYV9g2mw2SPegRHPhXT
wTNplYY5l3BDe3Qf/xr2foeKQ4WobpLc9NzxuxinJ+Fu9lLp3Afz9pz3viNcORfG
kQjw7Sl7PN1qOriIbTym2al6mK+qJF92RlGX0nei5JqIMpbiA3AwLvg2iQUd/YSE
HAWklz7IhwKBgAtQODj9iVrrFr4GTE+o5cOaySBbNYGHF3BJiW1mUtSEzPrqRCx0
q7Gtvmm5IzOrzGKYTmPBMY87HbKoa1rubHfwIj+jzKpFx9XekGBzCsDxkLOujOai
ud28Byr5tYZn0cRAGQafUg8DvnwMQDoz8imJFpiNfudvibcvRSWf4VhVAoGBAIQB
AgqWB2UZuWgsfUIW+fY8M55BOiBzUz0wwAwdyNNne0Vwvmx+z9OTHv2goEEbgRfD
NxtKw3umc/bFaxnERFZAHDJagB3PPRoN3CQXVVfiwDEInXrhwpLyZHt1ONkKnE91
UgeFGv7tiuJuo0xBSciJ2G4SDH0XeY4yRhRAV/oVAoGBALFOoiOh8Nrwdu4EMxe2
vD4pmMuRap04Q/i3gnF9tGXGyRKJlqFRnIN+cFjnesz8B5JgpMWYeoxwOmpGHsBh
2m7271YOAMPF6uBXlNZ1bbGHW2EsnIOUTNTN39c+UAQJ2g9CFa0va7ULTE4JHP5x
/zlsgxjcXY2QWHslbxE3FwS2
-----END PRIVATE KEY-----"""


class TestGetNfsKeyringId:
    """Tests for get_nfs_keyring_id function."""
    
    def test_success_find_nfs_keyring(self):
        """Test successful retrieval of .nfs: keyring ID from /proc/keys."""
        mock_proc_keys = """0a1b2c3d I--Q---     1 perm 1f3f0000     0     0 keyring   .nfs: 1
04820d22 I--Q---     6 perm 3f030000  1000  1001 keyring   _ses: 1
"""
        with patch("builtins.open", MagicMock(return_value=MagicMock(__enter__=lambda s: MagicMock(read=lambda: mock_proc_keys), __exit__=lambda *a: None))), \
             patch("vast_csi.mtls_utils.subprocess.run"):
            # Call __wrapped__ to bypass timecache
            result = get_nfs_keyring_id.__wrapped__()
            assert result == 0x0a1b2c3d

    def test_nfs_keyring_not_found_raises(self):
        """Test that missing .nfs: keyring raises RuntimeError."""
        mock_proc_keys = """04820d22 I--Q---     6 perm 3f030000  1000  1001 keyring   _ses: 1
"""
        with patch("builtins.open", MagicMock(return_value=MagicMock(__enter__=lambda s: MagicMock(read=lambda: mock_proc_keys), __exit__=lambda *a: None))):
            # Call __wrapped__ to bypass timecache
            with pytest.raises(RuntimeError, match="Could not find .nfs: keyring"):
                get_nfs_keyring_id.__wrapped__()


class TestPemToDer:
    """Tests for PEM to DER conversion - real conversion tests."""

    def test_convert_certificate(self):
        """Test converting a real PEM certificate to DER format."""
        result = pem_to_der(SAMPLE_CERT_PEM)
        assert isinstance(result, bytes)
        assert len(result) > 0
        assert result[0:1] == b'\x30'
        assert len(result) < len(SAMPLE_CERT_PEM)

    def test_convert_private_key(self):
        """Test converting a real PEM private key to DER format."""
        result = pem_to_der(SAMPLE_KEY_PEM)
        assert isinstance(result, bytes)
        assert len(result) > 0
        assert result[0:1] == b'\x30'
        assert len(result) < len(SAMPLE_KEY_PEM)

    def test_invalid_pem_content(self):
        """Test with invalid PEM content."""
        invalid_pem = "This is not a valid PEM"
        with pytest.raises(ValueError, match="Invalid PEM content"):
            pem_to_der(invalid_pem)


class TestLoadCertToKeyring:
    """Tests for loading certificates into kernel keyring."""

    def test_load_certificate_success_no_existing(self):
        """Test loading certificate when no existing key present."""
        der_content = b'\x30\x82\x01\x0a'  # Sample DER content

        # Mock subprocess.Popen for keyctl padd
        mock_proc = MagicMock()
        mock_proc.communicate.return_value = (b'123456', b'')
        mock_proc.returncode = 0

        # Mock KeyctlWrapper for setperm
        mock_keyctl_wrapper = MagicMock()

        with patch("vast_csi.mtls_utils.search_in_keyring", return_value=None), \
             patch("vast_csi.mtls_utils.get_nfs_keyring_id", return_value=0x3a2), \
             patch("vast_csi.mtls_utils.pem_to_der", return_value=der_content), \
             patch("vast_csi.mtls_utils.subprocess.Popen", return_value=mock_proc), \
             patch("vast_csi.mtls_utils.KeyctlWrapper", return_value=mock_keyctl_wrapper):

            result = load_pem_to_keyring(SAMPLE_CERT_PEM, "nfs-client-cert")

            # Verify
            assert result == 123456
            # Should have called Popen with keyctl padd
            mock_proc.communicate.assert_called_once()
            # Should have called setperm via KeyctlWrapper
            mock_keyctl_wrapper._system.assert_called_once()
    
    def test_load_certificate_reuse_existing(self):
        """Test reusing existing key when already loaded."""
        # If key already exists in keyring, just return its serial
        with patch("vast_csi.mtls_utils.search_in_keyring", return_value=999888):
            result = load_pem_to_keyring(SAMPLE_CERT_PEM, "nfs-client-cert")
            # Should return existing key serial
            assert result == 999888


class TestLoadMtlsCredentials:
    """Tests for loading complete mTLS credentials."""

    @patch('vast_csi.mtls_utils.load_pem_to_keyring')
    def test_load_both_credentials(self, mock_load_pem):
        """Test loading both certificate and private key with per-volume key names."""
        # Return different serials for each call (cert first, then key)
        mock_load_pem.side_effect = [123456, 789012]

        volume_id = "pvc-test-volume"
        cert_serial, privkey_serial = load_mtls_credentials(
            SAMPLE_CERT_PEM,
            SAMPLE_KEY_PEM,
            volume_id
        )

        assert cert_serial == 123456
        assert privkey_serial == 789012

        # Verify load_pem_to_keyring was called twice with per-volume key names
        assert mock_load_pem.call_count == 2
        first_call, second_call = mock_load_pem.call_args_list
        assert f"vast-client-cert-{volume_id}" in first_call[0][1]
        assert f"vast-client-privkey-{volume_id}" in second_call[0][1]

    @patch('vast_csi.mtls_utils.load_pem_to_keyring')
    def test_load_credentials_cert_fails(self, mock_load_pem):
        """Test handling certificate loading failure."""
        mock_load_pem.side_effect = Exception("Failed to load certificate")

        with pytest.raises(Exception, match="Failed to load certificate"):
            load_mtls_credentials(SAMPLE_CERT_PEM, SAMPLE_KEY_PEM, "test-volume")


class TestDeleteFromKeyring:
    """Tests for delete_from_keyring function."""

    def test_delete_existing_key(self):
        """Test deleting an existing key."""
        with patch('vast_csi.mtls_utils.search_in_keyring', return_value=123456), \
             patch('vast_csi.mtls_utils.subprocess.run'):
            delete_from_keyring("nfs-client-cert")

    def test_delete_nonexistent_key_idempotent(self):
        """Test that deleting a non-existent key is idempotent (no error)."""
        with patch('vast_csi.mtls_utils.search_in_keyring', return_value=None):
            # Should not raise exception
            delete_from_keyring("nfs-client-cert")
            # No error should be raised, function completes silently


class TestDeleteMtlsCredentials:
    """Tests for delete_mtls_credentials function."""

    @patch('vast_csi.mtls_utils.delete_from_keyring')
    def test_delete_success(self, mock_delete):
        """Test successful deletion of mTLS credentials with per-volume key names."""
        volume_id = "pvc-test-volume-123"
        delete_mtls_credentials(volume_id)

        # Verify delete_from_keyring was called twice (cert + privkey)
        assert mock_delete.call_count == 2
        calls = mock_delete.call_args_list
        
        # Check that correct per-volume key names were used
        assert f"vast-client-cert-{volume_id}" in calls[0][0][0]
        assert f"vast-client-privkey-{volume_id}" in calls[1][0][0]


class TestMtlsManagerDeleteCredentials:
    """Tests for MtlsManager.delete_credentials method."""

    @patch('vast_csi.mtls_utils.delete_mtls_credentials')
    def test_delete_credentials_success(self, mock_delete_mtls):
        """Test successful deletion of mTLS credentials from keyring."""
        manager = MtlsManager(
            mtls_client_cert=SAMPLE_CERT_PEM,
            mtls_client_privkey=SAMPLE_KEY_PEM,
            xprtsec="mtls"
        )

        volume_id = "pvc-test-volume-123"
        manager.delete_credentials(volume_id)

        # Verify delete_mtls_credentials was called with volume_id
        mock_delete_mtls.assert_called_once_with(volume_id)

    @patch('vast_csi.mtls_utils.delete_mtls_credentials')
    def test_delete_credentials_static_method(self, mock_delete_mtls):
        """Test delete_credentials is a static method that always attempts deletion."""
        volume_id = "pvc-test-volume-123"
        MtlsManager.delete_credentials(volume_id)

        # Should always attempt deletion (static method, no credential check)
        mock_delete_mtls.assert_called_once_with(volume_id)

    @patch('vast_csi.mtls_utils.delete_mtls_credentials')
    def test_delete_credentials_failure(self, mock_delete_mtls):
        """Test delete_credentials propagates exceptions."""
        manager = MtlsManager(
            mtls_client_cert=SAMPLE_CERT_PEM,
            mtls_client_privkey=SAMPLE_KEY_PEM,
            xprtsec="mtls"
        )

        mock_delete_mtls.side_effect = Exception("Keyring not accessible")

        volume_id = "pvc-test-volume-123"
        # Exception should be propagated
        with pytest.raises(Exception, match="Keyring not accessible"):
            manager.delete_credentials(volume_id)

        mock_delete_mtls.assert_called_once_with(volume_id)


class TestMtlsManagerXprtsecModes:
    """Tests for MtlsManager xprtsec modes (tls/mtls) with auto-detection of credential mode."""

    def test_empty_xprtsec_returns_no_flags(self):
        """Test that empty xprtsec returns no mount flags."""
        manager = MtlsManager(xprtsec="")
        flags = manager.to_mount_flags("test-volume")
        assert flags == []

    def test_tls_mode_returns_empty_flags(self):
        manager = MtlsManager(xprtsec="tls")
        flags = manager.to_mount_flags("test-volume")
        assert flags == []  # xprtsec=tls is already in StorageClass mountOptions

    def test_tls_mode_no_credentials_needed(self):
        """Test TLS-only mode doesn't require credentials."""
        manager = MtlsManager(xprtsec="tls")
        assert not manager.has_credentials()
        assert manager.requires_tls()
        assert not manager.requires_mtls()

    def test_mtls_without_credentials_returns_empty_flags(self):
        manager = MtlsManager(xprtsec="mtls")
        
        flags = manager.to_mount_flags("test-volume")
        
        assert flags == []

    @patch('vast_csi.mtls_utils.load_mtls_credentials')
    def test_mtls_with_credentials_returns_cert_serials(self, mock_load_creds):
        mock_load_creds.return_value = (123456, 789012)
        
        manager = MtlsManager(
            mtls_client_cert=SAMPLE_CERT_PEM,
            mtls_client_privkey=SAMPLE_KEY_PEM,
            xprtsec="mtls"
        )
        
        flags = manager.to_mount_flags("test-volume")

        assert "cert_serial=0x1e240" in flags  # 123456 in hex
        assert "privkey_serial=0xc0a14" in flags  # 789012 in hex
        assert len(flags) == 2  # Only cert_serial and privkey_serial

    def test_requires_tls_returns_true_for_tls(self):
        """Test requires_tls returns True for TLS mode."""
        manager = MtlsManager(xprtsec="tls")
        assert manager.requires_tls()

    def test_requires_tls_returns_true_for_mtls(self):
        """Test requires_tls returns True for mTLS mode."""
        manager = MtlsManager(
            mtls_client_cert=SAMPLE_CERT_PEM,
            mtls_client_privkey=SAMPLE_KEY_PEM,
            xprtsec="mtls"
        )
        assert manager.requires_tls()

    def test_requires_tls_returns_false_for_empty(self):
        """Test requires_tls returns False for empty xprtsec."""
        manager = MtlsManager(xprtsec="")
        assert not manager.requires_tls()

    def test_requires_mtls_with_mtls_xprtsec(self):
        """Test requires_mtls returns True for xprtsec=mtls regardless of credentials."""
        manager = MtlsManager(xprtsec="mtls")
        assert manager.requires_mtls()

    def test_dump_and_load_data_with_xprtsec(self):
        """Test serialization preserves xprtsec and credentials."""
        manager = MtlsManager(
            mtls_client_cert=SAMPLE_CERT_PEM,
            mtls_client_privkey=SAMPLE_KEY_PEM,
            xprtsec="mtls"
        )
        
        data = manager.dump_data()
        assert data["xprtsec"] == "mtls"
        
        restored = MtlsManager.load_data(data)
        assert restored.xprtsec == "mtls"
        assert restored.mtls_client_cert == SAMPLE_CERT_PEM

    def test_valid_xprtsec_values(self):
        """Test only valid xprtsec values are accepted."""
        for value in ("", "tls", "mtls"):
            manager = MtlsManager(xprtsec=value)
            assert manager.xprtsec == value


class TestXprtsecValidation:
    """Tests for xprtsec validation against view policy settings.
    
    Validation is NFS version agnostic. Required view policy settings:
    - xprtsec=""     : nfs_enforce_tls=False, nfs_enforce_mtls=False
    - xprtsec="tls"  : nfs_enforce_tls=True, nfs_enforce_tls_relaxed=True, nfs_enforce_mtls=False
    - xprtsec="mtls" : nfs_enforce_tls=True, nfs_enforce_tls_relaxed=True, nfs_enforce_mtls=True
    """

    def _create_mock_view_policy(
        self,
        name="test-policy",
        nfs_enforce_tls=False,
        nfs_enforce_tls_relaxed=False,
        nfs_enforce_mtls=False,
    ):
        """Create a mock view policy object with the specified TLS settings."""
        policy = MagicMock()
        policy.name = name
        policy.nfs_enforce_tls = nfs_enforce_tls
        policy.nfs_enforce_tls_relaxed = nfs_enforce_tls_relaxed
        policy.nfs_enforce_mtls = nfs_enforce_mtls
        return policy

    # Tests for validate_xprtsec_view_policy - Plain NFS (xprtsec="")

    def test_plain_nfs_with_non_enforcing_policy_passes(self):
        """Plain NFS with policy that doesn't enforce TLS/mTLS passes."""
        from vast_csi.mtls_utils import validate_xprtsec_view_policy

        policy = self._create_mock_view_policy(
            nfs_enforce_tls=False,
            nfs_enforce_mtls=False,
        )
        validate_xprtsec_view_policy(policy, "")

    def test_plain_nfs_with_tls_enforcing_policy_fails(self):
        """Plain NFS with nfs_enforce_tls=True fails."""
        from vast_csi.mtls_utils import validate_xprtsec_view_policy
        from vast_csi.exceptions import XprtsecValidationError

        policy = self._create_mock_view_policy(
            nfs_enforce_tls=True,
            nfs_enforce_mtls=False,
        )
        with pytest.raises(XprtsecValidationError, match="nfs_enforce_tls=True"):
            validate_xprtsec_view_policy(policy, "")

    def test_plain_nfs_with_mtls_enforcing_policy_fails(self):
        """Plain NFS with nfs_enforce_mtls=True fails."""
        from vast_csi.mtls_utils import validate_xprtsec_view_policy
        from vast_csi.exceptions import XprtsecValidationError

        policy = self._create_mock_view_policy(
            nfs_enforce_tls=False,
            nfs_enforce_mtls=True,
        )
        with pytest.raises(XprtsecValidationError, match="nfs_enforce_mtls=True"):
            validate_xprtsec_view_policy(policy, "")

    # Tests for validate_xprtsec_view_policy - TLS mode (xprtsec="tls")

    def test_tls_mode_correct_policy_passes(self):
        """TLS mode with correct policy settings passes."""
        from vast_csi.mtls_utils import validate_xprtsec_view_policy

        policy = self._create_mock_view_policy(
            nfs_enforce_tls=True,
            nfs_enforce_tls_relaxed=True,
            nfs_enforce_mtls=False,
        )
        validate_xprtsec_view_policy(policy, "tls")

    def test_tls_mode_without_enforce_tls_fails(self):
        """TLS mode with nfs_enforce_tls=False fails."""
        from vast_csi.mtls_utils import validate_xprtsec_view_policy
        from vast_csi.exceptions import XprtsecValidationError

        policy = self._create_mock_view_policy(
            nfs_enforce_tls=False,
            nfs_enforce_tls_relaxed=True,
            nfs_enforce_mtls=False,
        )
        with pytest.raises(XprtsecValidationError, match="nfs_enforce_tls=False.*requires nfs_enforce_tls=True"):
            validate_xprtsec_view_policy(policy, "tls")

    def test_tls_mode_nfsv3_without_relaxed_fails(self):
        """TLS mode with NFSv3 and nfs_enforce_tls_relaxed=False fails."""
        from vast_csi.mtls_utils import validate_xprtsec_view_policy
        from vast_csi.exceptions import XprtsecValidationError

        policy = self._create_mock_view_policy(
            nfs_enforce_tls=True,
            nfs_enforce_tls_relaxed=False,
            nfs_enforce_mtls=False,
        )
        with pytest.raises(XprtsecValidationError, match="nfs_enforce_tls_relaxed=False.*NFSv3.*requires nfs_enforce_tls_relaxed=True"):
            validate_xprtsec_view_policy(policy, "tls", is_nfs4=False)

    def test_tls_mode_nfsv4_ignores_relaxed(self):
        """TLS mode with NFSv4 ignores nfs_enforce_tls_relaxed=False."""
        from vast_csi.mtls_utils import validate_xprtsec_view_policy

        policy = self._create_mock_view_policy(
            nfs_enforce_tls=True,
            nfs_enforce_tls_relaxed=False,  # Should be ignored for NFSv4
            nfs_enforce_mtls=False,
        )
        validate_xprtsec_view_policy(policy, "tls", is_nfs4=True)

    def test_tls_mode_with_mtls_enforced_fails(self):
        """TLS mode with nfs_enforce_mtls=True fails."""
        from vast_csi.mtls_utils import validate_xprtsec_view_policy
        from vast_csi.exceptions import XprtsecValidationError

        policy = self._create_mock_view_policy(
            nfs_enforce_tls=True,
            nfs_enforce_tls_relaxed=True,
            nfs_enforce_mtls=True,
        )
        with pytest.raises(XprtsecValidationError, match="nfs_enforce_mtls=True.*requires nfs_enforce_mtls=False"):
            validate_xprtsec_view_policy(policy, "tls")

    # Tests for validate_xprtsec_view_policy - mTLS mode (xprtsec="mtls")

    def test_mtls_mode_correct_policy_passes(self):
        """mTLS mode with correct policy settings passes."""
        from vast_csi.mtls_utils import validate_xprtsec_view_policy

        policy = self._create_mock_view_policy(
            nfs_enforce_tls=True,
            nfs_enforce_tls_relaxed=True,
            nfs_enforce_mtls=True,
        )
        validate_xprtsec_view_policy(policy, "mtls")

    def test_mtls_mode_without_enforce_tls_fails(self):
        """mTLS mode with nfs_enforce_tls=False fails."""
        from vast_csi.mtls_utils import validate_xprtsec_view_policy
        from vast_csi.exceptions import XprtsecValidationError

        policy = self._create_mock_view_policy(
            nfs_enforce_tls=False,
            nfs_enforce_tls_relaxed=True,
            nfs_enforce_mtls=True,
        )
        with pytest.raises(XprtsecValidationError, match="nfs_enforce_tls=False.*requires nfs_enforce_tls=True"):
            validate_xprtsec_view_policy(policy, "mtls")

    def test_mtls_mode_nfsv3_without_relaxed_fails(self):
        """mTLS mode with NFSv3 and nfs_enforce_tls_relaxed=False fails."""
        from vast_csi.mtls_utils import validate_xprtsec_view_policy
        from vast_csi.exceptions import XprtsecValidationError

        policy = self._create_mock_view_policy(
            nfs_enforce_tls=True,
            nfs_enforce_tls_relaxed=False,
            nfs_enforce_mtls=True,
        )
        with pytest.raises(XprtsecValidationError, match="nfs_enforce_tls_relaxed=False.*NFSv3.*requires nfs_enforce_tls_relaxed=True"):
            validate_xprtsec_view_policy(policy, "mtls", is_nfs4=False)

    def test_mtls_mode_nfsv4_ignores_relaxed(self):
        """mTLS mode with NFSv4 ignores nfs_enforce_tls_relaxed=False."""
        from vast_csi.mtls_utils import validate_xprtsec_view_policy

        policy = self._create_mock_view_policy(
            nfs_enforce_tls=True,
            nfs_enforce_tls_relaxed=False,  # Should be ignored for NFSv4
            nfs_enforce_mtls=True,
        )
        validate_xprtsec_view_policy(policy, "mtls", is_nfs4=True)

    def test_mtls_mode_without_enforce_mtls_fails(self):
        """mTLS mode with nfs_enforce_mtls=False fails."""
        from vast_csi.mtls_utils import validate_xprtsec_view_policy
        from vast_csi.exceptions import XprtsecValidationError

        policy = self._create_mock_view_policy(
            nfs_enforce_tls=True,
            nfs_enforce_tls_relaxed=True,
            nfs_enforce_mtls=False,
        )
        with pytest.raises(XprtsecValidationError, match="nfs_enforce_mtls=False.*requires nfs_enforce_mtls=True"):
            validate_xprtsec_view_policy(policy, "mtls")


class TestGetXprtsecFromMountOptions:
    """Tests for get_xprtsec_from_mount_options utility function."""

    def test_extracts_mtls_from_comma_separated_string(self):
        """Test extraction from comma-separated mount options string."""
        result = get_xprtsec_from_mount_options("nfsvers=4.1,xprtsec=mtls,hard")
        assert result == "mtls"

    def test_extracts_tls_from_comma_separated_string(self):
        """Test extraction of TLS mode."""
        result = get_xprtsec_from_mount_options("xprtsec=tls,nfsvers=4.2")
        assert result == "tls"

    def test_extracts_from_list(self):
        """Test extraction from list of mount options."""
        result = get_xprtsec_from_mount_options(["nfsvers=4.1", "xprtsec=mtls", "hard"])
        assert result == "mtls"

    def test_returns_empty_when_not_present(self):
        """Test returns empty string when xprtsec not in options."""
        result = get_xprtsec_from_mount_options("nfsvers=4.1,hard,timeo=600")
        assert result == ""

    def test_returns_empty_for_empty_string(self):
        """Test returns empty string for empty input."""
        result = get_xprtsec_from_mount_options("")
        assert result == ""

    def test_returns_empty_for_none(self):
        """Test returns empty string for None input."""
        result = get_xprtsec_from_mount_options(None)
        assert result == ""

    def test_xprtsec_only(self):
        """Test when xprtsec is the only option."""
        result = get_xprtsec_from_mount_options("xprtsec=mtls")
        assert result == "mtls"

    def test_handles_xprtsec_at_end(self):
        """Test extraction when xprtsec is at the end."""
        result = get_xprtsec_from_mount_options("nfsvers=4.1,hard,xprtsec=mtls")
        assert result == "mtls"

    def test_ignores_xprtsec_without_value(self):
        """Test ignores xprtsec without a value."""
        result = get_xprtsec_from_mount_options("xprtsec=,nfsvers=4.1")
        assert result == ""

    def test_raises_error_for_invalid_xprtsec_value(self):
        """Test raises XprtsecValidationError for invalid xprtsec value."""
        with pytest.raises(XprtsecValidationError, match="Invalid xprtsec value: 'hello'"):
            get_xprtsec_from_mount_options("xprtsec=hello,nfsvers=4.1")

    def test_raises_error_for_invalid_xprtsec_in_list(self):
        """Test raises XprtsecValidationError for invalid xprtsec value in list."""
        with pytest.raises(XprtsecValidationError, match="Invalid xprtsec value"):
            get_xprtsec_from_mount_options(["nfsvers=4.1", "xprtsec=invalid"])
