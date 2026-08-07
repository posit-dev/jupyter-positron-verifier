"""Tests for the entitlement checker configuration and failure classification."""

import asyncio

from jupyter_positron_verifier import entitlement as entitlement_module
from jupyter_positron_verifier.entitlement import EntitlementChecker


def _fake_license_manager(tmp_path, body: str):
    """Write an executable stand-in for license-manager and return its path."""
    script = tmp_path / "license-manager"
    script.write_text(f"#!/bin/sh\n{body}\n")
    script.chmod(0o755)
    return str(script)


class TestEntitlementFromEnv:
    def test_skip_env_var_is_ignored(self, monkeypatch):
        # POSITRON_SKIP_ENTITLEMENT_CHECK was removed; setting it must not
        # grant a valid entitlement when no license-manager is configured.
        monkeypatch.setenv("POSITRON_SKIP_ENTITLEMENT_CHECK", "1")
        monkeypatch.delenv("POSITRON_LICENSE_MANAGER_PATH", raising=False)
        checker = EntitlementChecker.from_env()
        result = asyncio.run(checker.check())
        assert result.valid is False

    def test_missing_license_manager_path_is_invalid(self, monkeypatch):
        monkeypatch.delenv("POSITRON_LICENSE_MANAGER_PATH", raising=False)
        checker = EntitlementChecker.from_env()
        result = asyncio.run(checker.check())
        assert result.valid is False


class TestFailureClassification:
    """A failed check must say whether license-manager actually answered."""

    def test_valid_license_is_determinate(self, tmp_path):
        path = _fake_license_manager(
            tmp_path, 'echo \'{"status":"activated","licensee":"Acme","issuer":"Posit"}\''
        )
        result = asyncio.run(EntitlementChecker(path).check())
        assert (result.valid, result.determinate, result.licensee) == (True, True, "Acme")

    def test_negative_answer_is_determinate(self, tmp_path):
        # license-manager answered "no" -- retrying will not help.
        path = _fake_license_manager(tmp_path, 'echo \'{"status":"expired"}\'')
        result = asyncio.run(EntitlementChecker(path).check())
        assert (result.valid, result.determinate) == (False, True)

    def test_missing_path_is_determinate(self):
        result = asyncio.run(EntitlementChecker(None).check())
        assert (result.valid, result.determinate) == (False, True)

    def test_missing_binary_is_determinate(self, tmp_path):
        result = asyncio.run(EntitlementChecker(str(tmp_path / "nope")).check())
        assert (result.valid, result.determinate) == (False, True)

    def test_non_executable_binary_is_determinate(self, tmp_path):
        script = tmp_path / "license-manager"
        script.write_text("#!/bin/sh\ntrue\n")
        script.chmod(0o644)
        result = asyncio.run(EntitlementChecker(str(script)).check())
        assert (result.valid, result.determinate) == (False, True)

    def test_unparseable_output_is_indeterminate(self, tmp_path):
        path = _fake_license_manager(tmp_path, "echo 'this is not json'")
        result = asyncio.run(EntitlementChecker(path).check())
        assert (result.valid, result.determinate) == (False, False)

    def test_timeout_is_indeterminate(self, tmp_path, monkeypatch):
        async def _timeout(coro, *args, **kwargs):
            coro.close()  # avoid "coroutine was never awaited"
            raise asyncio.TimeoutError

        monkeypatch.setattr(entitlement_module.asyncio, "wait_for", _timeout)
        path = _fake_license_manager(tmp_path, "true")
        result = asyncio.run(EntitlementChecker(path).check())
        assert (result.valid, result.determinate) == (False, False)


class TestCaching:
    def test_indeterminate_result_is_not_cached(self, tmp_path):
        # A transient failure must not deny mints for the whole cache TTL: the
        # next check should re-run license-manager rather than reuse the miss.
        script = tmp_path / "license-manager"
        checker = EntitlementChecker(str(script))

        script.write_text("#!/bin/sh\necho 'not json'\n")
        script.chmod(0o755)
        assert asyncio.run(checker.check()).determinate is False

        script.write_text('#!/bin/sh\necho \'{"status":"activated","licensee":"Acme"}\'\n')
        script.chmod(0o755)
        assert asyncio.run(checker.check()).valid is True

    def test_determinate_result_is_cached(self, tmp_path):
        script = tmp_path / "license-manager"
        checker = EntitlementChecker(str(script))

        script.write_text('#!/bin/sh\necho \'{"status":"activated","licensee":"Acme"}\'\n')
        script.chmod(0o755)
        assert asyncio.run(checker.check()).valid is True

        # Replacing the binary with a denial is not observed within the TTL.
        script.write_text('#!/bin/sh\necho \'{"status":"expired"}\'\n')
        script.chmod(0o755)
        assert asyncio.run(checker.check()).valid is True
