from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_cmd_wrappers_pause_for_double_click_users():
    for name in ("install.cmd", "start.cmd", "stop.cmd", "diagnose.cmd"):
        content = (ROOT / name).read_text(encoding="utf-8")

        assert "pause" in content.lower()
        assert "CHARTLENS_NO_PAUSE" in content
        assert "exit /b %EXIT_CODE%" in content


def test_start_script_surfaces_logs_when_services_do_not_become_ready():
    content = (ROOT / "scripts" / "start.ps1").read_text(encoding="utf-8")

    assert "Show-LogTail" in content
    assert "Service startup failed" in content
    assert "$BackendOk -and $FrontendOk" in content


def test_start_script_uses_lock_and_project_process_detection_to_prevent_duplicates():
    content = (ROOT / "scripts" / "start.ps1").read_text(encoding="utf-8")

    assert "start.lock" in content
    assert "FileMode]::CreateNew" in content
    assert "Find-ProjectProcess" in content
    assert "Get-NetTCPConnection" in content


def test_stop_script_can_stop_project_processes_without_pid_files():
    content = (ROOT / "scripts" / "stop.ps1").read_text(encoding="utf-8")

    assert "Stop-ProjectProcesses" in content
    assert "Find-ProjectProcess" in content
    assert "Get-NetTCPConnection" in content
    assert "CommandLine" in content


def test_diagnose_script_checks_dependencies_ports_and_logs():
    content = (ROOT / "scripts" / "diagnose.ps1").read_text(encoding="utf-8")

    assert "python --version" in content
    assert "node --version" in content
    assert "npm --version" in content
    assert "Test-NetConnection" in content
    assert "backend.log" in content
    assert "frontend.log" in content
    assert "OAuth config" in content
    assert "CHARTLENS_OAUTH_CLIENT_ID" in content
