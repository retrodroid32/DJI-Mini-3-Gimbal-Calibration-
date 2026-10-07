import pytest

from wm163_production_fw import (
    EXPECTED_ANTIROLLBACK,
    EXPECTED_ANTIROLLBACK_EXT,
    EXPECTED_ARCHIVE_MD5,
    EXPECTED_ARCHIVE_SHA256,
    EXPECTED_ARCHIVE_SIZE,
    EXPECTED_DEVICE,
    EXPECTED_ENFORCE,
    EXPECTED_FORMAL,
    EXPECTED_MODULE_VERSIONS,
    validate_production_info,
)
from wm163_service_fw_inspect import ModuleInfo, PackageInfo


def _known_info(**overrides):
    modules = tuple(
        ModuleInfo(
            module_id=module_id,
            version=version,
            order=index,
            wait=0,
            size=1,
            md5="00",
            filename=f"{module_id}.sig",
        )
        for index, (module_id, version) in enumerate(EXPECTED_MODULE_VERSIONS, start=1)
    )
    values = dict(
        device=EXPECTED_DEVICE,
        formal=EXPECTED_FORMAL,
        release=EXPECTED_FORMAL,
        antirollback=EXPECTED_ANTIROLLBACK,
        antirollback_ext=EXPECTED_ANTIROLLBACK_EXT,
        enforce=EXPECTED_ENFORCE,
        modules=modules,
        md5=EXPECTED_ARCHIVE_MD5,
        sha256=EXPECTED_ARCHIVE_SHA256,
    )
    values.update(overrides)
    return PackageInfo(**values)


def test_accepts_exact_verified_wm163_production_metadata():
    info = _known_info()
    assert validate_production_info(info, archive_size=EXPECTED_ARCHIVE_SIZE) is info


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        ("device", "wm162", "wrong device"),
        ("formal", "01.00.0400", "wrong production formal/release"),
        ("release", "01.00.0400", "wrong production formal/release"),
        ("md5", "0" * 32, "archive MD5"),
        ("sha256", "0" * 64, "archive SHA256"),
        ("antirollback", "1", "unexpected antirollback"),
        ("antirollback_ext", "cn:1", "unexpected antirollback_ext"),
        ("enforce", "1", "unexpected enforce"),
    ],
)
def test_rejects_identity_hash_and_policy_mismatches(field, value, match):
    with pytest.raises(ValueError, match=match):
        validate_production_info(
            _known_info(**{field: value}),
            archive_size=EXPECTED_ARCHIVE_SIZE,
        )


def test_rejects_wrong_archive_size():
    with pytest.raises(ValueError, match="wrong archive size"):
        validate_production_info(_known_info(), archive_size=EXPECTED_ARCHIVE_SIZE - 1)


def test_rejects_wrong_module_version_set():
    modules = list(_known_info().modules)
    first = modules[1]
    modules[1] = ModuleInfo(
        module_id=first.module_id,
        version="03.04.11.31",
        order=first.order,
        wait=first.wait,
        size=first.size,
        md5=first.md5,
        filename=first.filename,
    )
    with pytest.raises(ValueError, match="production module set mismatch"):
        validate_production_info(
            _known_info(modules=tuple(modules)),
            archive_size=EXPECTED_ARCHIVE_SIZE,
        )
