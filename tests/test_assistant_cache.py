import struct

from wm163_assistant_cache import (
    PREFERRED_PRODUCTION_FORMAL,
    find_wm163_assistant_firmware,
)


def _signed_cfg(formal: str, module_names: list[str]) -> bytes:
    modules = "".join(
        (
            f'<module id="{100 + idx:04d}" version="01.00.00.{idx:02d}" '
            f'order="{idx}" wait="0" size="1" md5="00">{name}</module>'
        )
        for idx, name in enumerate(module_names, start=1)
    )
    xml = (
        '<?xml version="1.0"?>'
        '<dji><device id="wm163">'
        f'<firmware formal="{formal}">'
        f'<release version="{formal}" antirollback="0" antirollback_ext="cn:0" enforce="0">'
        f'{modules}'
        '</release></firmware></device></dji>'
    ).encode()

    blob = bytearray(32 + len(xml))
    blob[:4] = b"IM*H"
    blob[32:] = xml
    struct.pack_into("<I", blob, 8, len(blob))
    struct.pack_into("<I", blob, 28, len(blob))
    return bytes(blob)


def _make_cache(root, formal: str, complete: bool = True):
    folder = root / formal
    folder.mkdir(parents=True)

    names = [
        "wm163_0905_v01.00.01.27.pro.fw.sig",
        "wm163_0306_v03.04.11.34.pro.fw.sig",
        "wm163_1200_v01.10.02.15.pro.fw.sig",
        "wm163_1100_v10.75.00.17.pro.fw.sig",
        "wm163_0105_v12.07.00.12.pro.fw.sig",
        "wm163_0100_v01.64.01.52.pro.fw.sig",
    ]
    (folder / "wm163.cfg.sig").write_bytes(_signed_cfg(formal, names))

    limit = len(names) if complete else len(names) - 1
    for name in names[:limit]:
        (folder / name).write_bytes(b"x")

    return folder


def test_prefers_complete_exact_wm163_01000500_cache(tmp_path):
    _make_cache(tmp_path, "01.00.0400", complete=True)
    expected = _make_cache(tmp_path, PREFERRED_PRODUCTION_FORMAL, complete=True)

    matches = find_wm163_assistant_firmware(roots=[tmp_path])

    assert matches
    best = matches[0]
    assert best.kind == "module-set"
    assert best.formal == "01.00.0500"
    assert best.release == "01.00.0500"
    assert best.complete
    assert best.root == expected
    assert len(best.module_files) == 6


def test_reports_incomplete_cache_without_claiming_complete(tmp_path):
    expected = _make_cache(tmp_path, PREFERRED_PRODUCTION_FORMAL, complete=False)

    matches = find_wm163_assistant_firmware(roots=[tmp_path])

    assert matches
    best = matches[0]
    assert best.root == expected
    assert not best.complete
    assert len(best.missing_modules) == 1
