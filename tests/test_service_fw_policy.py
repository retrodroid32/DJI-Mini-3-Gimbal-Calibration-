from wm163_service_fw_policy import (
    SERVICE_FW_LIBRARY,
    ServiceFw,
    arb_allows,
    has_service_fw,
    parse_version,
    select_service_fw,
)


def test_recovered_catalog_mapping():
    assert SERVICE_FW_LIBRARY["WM162"][0].version == "20.00.0800"
    assert SERVICE_FW_LIBRARY["WM162"][0].filename == "mini3pro_service.bin"
    assert SERVICE_FW_LIBRARY["WM163"][0].version == "30.00.0100"
    assert SERVICE_FW_LIBRARY["WM163"][0].filename == "mini3_service.bin"
    assert SERVICE_FW_LIBRARY["WA1617"][0].version == "20.07.0700"
    assert SERVICE_FW_LIBRARY["WA1617"][0].filename == "mini4k_service.bin"


def test_parse_version_matches_recovered_normalization():
    assert parse_version(None) == ()
    assert parse_version("") == ()
    assert parse_version("30.00.0100") == (30, 0, 100)
    assert parse_version("30_00-0100") == (30, 0, 100)
    assert parse_version("V30.00.0100") == (0, 100)
    assert parse_version("30.foo.0100") == (30, 100)


def test_recovered_arb_predicate_is_service_ge_public():
    assert arb_allows("30.00.0100", "01.00.0500")
    assert arb_allows("30.00.0100", "30.00.0100")
    assert not arb_allows("30.00.0100", "31.00.0000")


def test_wm163_selects_only_mini3_service_image():
    fw, note = select_service_fw(" wm163 ", "01.00.0500")
    assert fw is not None
    assert fw.version == "30.00.0100"
    assert fw.filename == "mini3_service.bin"
    assert "ARB compatible" in note


def test_wm163_does_not_cross_select_wm162():
    fw, _ = select_service_fw("WM162", "01.00.0500")
    assert fw is not None
    assert fw.filename == "mini3pro_service.bin"
    fw2, _ = select_service_fw("WM163", "01.00.0500")
    assert fw2 is not None
    assert fw2.filename != fw.filename


def test_blocks_when_newest_service_is_older_than_public():
    fw, note = select_service_fw("WM163", "31.00.0000")
    assert fw is None
    assert "ARB bloquea" in note
    assert "30.00.0100" in note


def test_selects_newest_eligible_candidate():
    lib = {
        "WM163": (
            ServiceFw("20.00.0100", "old.bin"),
            ServiceFw("30.00.0100", "new.bin"),
            ServiceFw("40.00.0100", "future.bin"),
        )
    }
    fw, _ = select_service_fw("wm163", "25.00.0000", lib)
    assert fw is not None
    assert fw.filename == "future.bin"


def test_has_service_fw_is_catalog_only_not_arb_gate():
    assert has_service_fw("WM163")
    assert has_service_fw(" wm163 ")
    assert not has_service_fw("UNKNOWN")

    # Recovered DrGrey behavior: availability is independent of public FW.
    # ARB enforcement belongs to select_service_fw(), not has_service_fw().
    fw, _ = select_service_fw("WM163", "31.00.0000")
    assert fw is None


def test_manifest_derived_arb_guard_uses_aircraft_formal_version_only():
    from wm163_service_fw_policy import select_service_fw_from_aircraft_manifest

    fw, note = select_service_fw_from_aircraft_manifest(
        "WM163", {"formal": "01.00.0500"}
    )
    assert fw is not None
    assert fw.filename == "mini3_service.bin"
    assert "ARB compatible" in note

    fw2, note2 = select_service_fw_from_aircraft_manifest(
        "WM163", {"firmware": {"formal": "31.00.0000"}}
    )
    assert fw2 is None
    assert "ARB bloquea" in note2


def test_manifest_derived_arb_guard_fails_closed_without_formal():
    from wm163_service_fw_policy import select_service_fw_from_aircraft_manifest

    fw, note = select_service_fw_from_aircraft_manifest("WM163", None)
    assert fw is None
    assert "cfg.sig FORMAL" in note

    fw2, note2 = select_service_fw_from_aircraft_manifest(
        "WM163",
        {
            "modules": [
                {"id": "0306", "app": "0x03040b22"},
                {"id": "0100", "app": "0x01400098"},
            ]
        },
    )
    assert fw2 is None
    assert "Module app/loader versions are not valid substitutes" in note2
