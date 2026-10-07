from analyze_wm163_production_restore import transfer_summary
import wm163_service_flash_live as service_fw


def test_production_restore_transfer_summary_uses_capture_backed_packetization():
    files = [
        ("0905.cfg.sig", b"abc"),
        ("0905.pro.fw.sig", b"12345"),
    ]

    summary = transfer_summary(files)

    assert summary["file_count"] == 2
    assert summary["files"] == (
        ("0905.cfg.sig", 3),
        ("0905.pro.fw.sig", 5),
    )
    assert summary["total_size"] == service_fw.session_b_total_size(files)
    assert summary["finalize_seq"] == service_fw.session_b_finalize_seq(files)
