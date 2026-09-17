from __future__ import annotations

from click.testing import CliRunner

from provena.cli.main import cli


def test_help_lists_all_top_level_commands() -> None:
    result = CliRunner().invoke(cli, ["--help"])

    assert result.exit_code == 0
    for command in ("audit", "verify", "report", "retain", "migrate", "mcp"):
        assert command in result.output
