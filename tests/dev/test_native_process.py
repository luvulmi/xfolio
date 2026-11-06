"""Windows PowerShell 5.1의 실제 stderr 경계를 외부 통신 없이 검사한다."""

import json
import shutil
import subprocess
import sys
import textwrap

import pytest

from tests.support.paths import ROOT


def ps_literal(value):
    return "'" + str(value).replace("'", "''") + "'"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows PowerShell regression")
@pytest.mark.parametrize("child_exit", [0, 7])
def test_calendar_warning_keeps_running_and_preserves_native_exit(tmp_path, child_exit):
    powershell = shutil.which("powershell.exe")
    if powershell is None:
        pytest.skip("Windows PowerShell 5.1 required")
    folder = tmp_path / "로그 경로 with spaces"
    folder.mkdir()
    child = folder / "calendar_warning.py"
    child.write_text(
        textwrap.dedent(
            f"""\
            import socket
            import time
            from pathlib import Path

            def forbidden(*args, **kwargs):
                raise AssertionError("external_network_forbidden")
            socket.socket.connect = forbidden
            socket.getaddrinfo = forbidden
            from xfolio.domestic.calendar import local_calendar
            print("started", flush=True)
            local_calendar()
            time.sleep(0.5)
            print("완료", flush=True)
            Path(__file__).with_suffix(".finished").touch()
            raise SystemExit({child_exit})
            """
        ),
        encoding="utf-8",
    )
    stdout, stderr = folder / "stdout.log", folder / "stderr.log"
    wrapper = folder / "wrapper.ps1"
    wrapper.write_text(
        "$ErrorActionPreference = 'Stop'\n"
        f". {ps_literal(ROOT / 'scripts/dev/native_process.ps1')}\n"
        f"$nativeExit = Invoke-XFolioPython -Python {ps_literal(sys.executable)} "
        f"-Script {ps_literal(child)} -StdoutPath {ps_literal(stdout)} "
        f"-StderrPath {ps_literal(stderr)}\n"
        "Write-Output (ConvertTo-Json @{exit_code=$nativeExit} -Compress)\n"
        "exit $nativeExit\n",
        encoding="utf-8-sig",  # Windows PowerShell 5.1의 유니코드 경로.
    )
    result = subprocess.run(
        [
            powershell,
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(wrapper),
        ],
        cwd=ROOT,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == child_exit
    assert json.loads(result.stdout)["exit_code"] == child_exit
    assert child.with_suffix(".finished").exists()
    assert "started" in stdout.read_text(encoding="utf-8-sig")
    assert "완료" in stdout.read_text(encoding="utf-8-sig")
    assert "UserWarning" in stderr.read_text(encoding="utf-8-sig")
    assert b"NativeCommandError" not in result.stderr
