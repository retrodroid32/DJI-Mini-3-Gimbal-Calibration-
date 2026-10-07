from wm163_private_fw import (
    PRIVATE_FIRMWARE_DIR,
    SERVICE_PACKAGE_FILENAME,
    SESSION_A_LOADER_FILENAME,
    find_private_service_inputs,
)


def test_private_service_inputs_find_exact_local_files(tmp_path):
    private_dir = tmp_path / PRIVATE_FIRMWARE_DIR
    private_dir.mkdir()

    package = private_dir / SERVICE_PACKAGE_FILENAME
    loader = private_dir / SESSION_A_LOADER_FILENAME
    package.write_bytes(b"service")
    loader.write_bytes(b"loader")

    found = find_private_service_inputs(tmp_path)

    assert found.complete
    assert found.package == package
    assert found.loader == loader


def test_private_service_inputs_are_optional_and_exact_named(tmp_path):
    private_dir = tmp_path / PRIVATE_FIRMWARE_DIR
    private_dir.mkdir()

    (private_dir / "wrong_service_name.bin").write_bytes(b"service")
    (private_dir / "wrong_loader_name.bin").write_bytes(b"loader")

    found = find_private_service_inputs(tmp_path)

    assert not found.complete
    assert found.package is None
    assert found.loader is None
