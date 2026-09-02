import importlib


def load_defs(monkeypatch):
    monkeypatch.setenv("WRC_START_DATE", "15/01/2025")
    monkeypatch.setenv("WRC_END_DATE", "10/03/2025")
    monkeypatch.setenv("WRC_BODIES", "body_a,body_b")
    monkeypatch.setenv("PARTITION_SIZE", "month")
    import orchestration.dagster_defs as defs
    return importlib.reload(defs)


def test_create_monthly_partition_keys_closes_over_partial_months(monkeypatch):
    defs = load_defs(monkeypatch)

    assert defs.create_monthly_partition_keys(
        defs.parse_date("15/01/2025"), defs.parse_date("10/03/2025")
    ) == ["2025-01", "2025-02", "2025-03"]


def test_partition_dates_clips_first_and_last_month(monkeypatch):
    defs = load_defs(monkeypatch)

    assert defs.partition_dates("2025-01") == (
        defs.parse_date("15/01/2025"),
        defs.parse_date("31/01/2025"),
    )
    assert defs.partition_dates("2025-03") == (
        defs.parse_date("01/03/2025"),
        defs.parse_date("10/03/2025"),
    )


def test_partition_dates_handles_leap_year(monkeypatch):
    defs = load_defs(monkeypatch)
    assert defs.partition_dates("2025-02")[1].isoformat() == "2025-02-28"


def test_run_command_raises_on_nonzero_exit(monkeypatch):
    defs = load_defs(monkeypatch)

    class Result:
        returncode = 7
        stdout = "stdout"
        stderr = "stderr"

    monkeypatch.setattr(defs.subprocess, "run", lambda *args, **kwargs: Result())

    class Context:
        class Log:
            def info(self, value):
                pass

            def error(self, value):
                self.last = value

        log = Log()

    import pytest
    with pytest.raises(RuntimeError, match="failed with return code 7"):
        defs.run_command(["fake"], "operation", Context())