#!/usr/bin/env python3
"""Compare two offline WM163 production-restore payload hypotheses.

No serial port is opened. No firmware can be written.

Hypothesis A is the capture-backed WM163 Service-FW Session-B payload grammar.
Hypothesis B is the independently recovered DrGrey mini2style_flash signed-file
payload grammar. The script validates the exact production archive and compares
every report/start/data/end/finalize payload byte-for-byte.

Passing this comparison strengthens the payload-format evidence only. It does
not prove the outer WM163 stock-restore transport/orchestration.
"""

from __future__ import annotations

import hashlib
import pathlib
import struct
import sys

import wm163_production_fw as production_fw
import wm163_service_flash_live as service_live
from wm163_production_restore_evidence import (
    MINI2STYLE_FINALIZE_PAYLOAD,
    MINI2STYLE_INSTALL_PUSH_CMD,
    build_mini2style_chunk,
    build_mini2style_file_end,
    build_mini2style_file_start,
    build_mini2style_report_size,
)
from wm163_service_flash_protocol import (
    CHUNK,
    session_b_file_data_payload,
    session_b_file_end_payload,
    session_b_file_start_payload,
    session_b_finalize_payload,
    session_b_finalize_seq,
    session_b_report_size_payload,
    session_b_total_size,
)


def _framed_hash(payloads) -> tuple[str, int]:
    h = hashlib.sha256()
    count = 0
    for payload in payloads:
        blob = bytes(payload)
        h.update(struct.pack("<I", len(blob)))
        h.update(blob)
        count += 1
    return h.hexdigest(), count


def compare_payload_grammars(files: list[tuple[str, bytes]]) -> dict[str, object]:
    total_size = session_b_total_size(files)

    service_payloads: list[bytes] = []
    generic_payloads: list[bytes] = []

    service_payloads.append(session_b_report_size_payload(total_size))
    generic_payloads.append(build_mini2style_report_size(total_size))

    data_records = 0
    for name, blob in files:
        service_payloads.append(session_b_file_start_payload(name, blob))
        generic_payloads.append(build_mini2style_file_start(name, len(blob)))

        for chunk_index, offset in enumerate(range(0, len(blob), CHUNK)):
            chunk = blob[offset : offset + CHUNK]
            service_payloads.append(session_b_file_data_payload(chunk_index, chunk))
            generic_payloads.append(build_mini2style_chunk(chunk_index, chunk))
            data_records += 1

        service_payloads.append(session_b_file_end_payload(blob))
        generic_payloads.append(
            build_mini2style_file_end(hashlib.md5(blob).digest())
        )

    service_payloads.append(session_b_finalize_payload())
    generic_payloads.append(MINI2STYLE_FINALIZE_PAYLOAD)

    if len(service_payloads) != len(generic_payloads):
        raise ValueError("payload record counts differ")

    for index, (service, generic) in enumerate(
        zip(service_payloads, generic_payloads)
    ):
        if service != generic:
            raise ValueError(
                f"payload grammar mismatch at record {index}: "
                f"service={service[:32].hex()} generic={generic[:32].hex()}"
            )

    service_hash, service_count = _framed_hash(service_payloads)
    generic_hash, generic_count = _framed_hash(generic_payloads)
    if service_hash != generic_hash or service_count != generic_count:
        raise ValueError("payload-stream fingerprints disagree")

    return {
        "file_count": len(files),
        "data_records": data_records,
        "payload_records_including_report_and_finalize": service_count,
        "transfer_size": total_size,
        "payload_stream_sha256": service_hash,
        "service_loader_candidate_finalize_seq": session_b_finalize_seq(files),
    }


def main() -> int:
    package = production_fw.find_repo_production_archive()
    if package is None:
        print(
            "ERROR: exact production archive not found under firmware/.",
            file=sys.stderr,
        )
        return 2

    try:
        info = production_fw.validate_production_archive(package)
        files = service_live._package_transfer_files(package)
        result = compare_payload_grammars(files)
    except Exception as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        return 3

    print("WM163 production restore OFFLINE hypothesis comparison: PASS")
    print(f"device={info.device}")
    print(f"formal={info.formal}")
    print(f"release={info.release}")
    print(f"signed_members={result['file_count']}")
    print(f"data_records={result['data_records']}")
    print(
        "payload_records_including_report_and_finalize="
        f"{result['payload_records_including_report_and_finalize']}"
    )
    print(f"transfer_size={result['transfer_size']}")
    print(f"payload_stream_sha256={result['payload_stream_sha256']}")
    print(
        "mini2style_payload_grammar_vs_wm163_session_b=BYTE_IDENTICAL"
    )
    print(
        "service_loader_candidate_finalize_seq="
        f"0x{result['service_loader_candidate_finalize_seq']:04X}"
    )
    print(
        f"generic_standard_updater_install_status_push=0x"
        f"{MINI2STYLE_INSTALL_PUSH_CMD:02X}"
    )
    print("wm163_stock_restore_outer_orchestration=UNPROVEN")
    print()
    print("NO SERIAL PORT WAS OPENED. NO FIRMWARE WAS WRITTEN.")
    print(
        "PASS means the signed-file PAYLOAD grammar is independently corroborated; "
        "it does not select or authorize a live restore transport."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
