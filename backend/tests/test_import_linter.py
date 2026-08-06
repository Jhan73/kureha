import os
from pathlib import Path

from click.testing import CliRunner

from importlinter.cli import lint_imports_command

BACKEND_ROOT = Path(__file__).resolve().parent.parent


def test_import_linter_contracts_are_kept() -> None:
    cwd = os.getcwd()
    os.chdir(BACKEND_ROOT)
    try:
        result = CliRunner().invoke(lint_imports_command, [])
    finally:
        os.chdir(cwd)

    assert result.exit_code == 0, (
        "import-linter contracts broken (module boundaries):\n"
        f"{result.output}"
    )
