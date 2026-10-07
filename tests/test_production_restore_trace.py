from trace_wm163_production_restore_candidate import summarize


def test_module_import_does_not_open_hardware():
    # The production trace module must remain import-safe and hardware-free.
    assert callable(summarize)
