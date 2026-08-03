from help_parser import parse_help

CODEX_HELP = r"""
Codex CLI

If no subcommand is specified, options will be forwarded to the interactive CLI.

Usage: codex [OPTIONS] [PROMPT]
       codex [OPTIONS] <COMMAND> [ARGS]

Commands:
  exec            Run Codex non-interactively [aliases: e]
  review          Run a code review non-interactively
  delete          Permanently delete a saved session by id or session name
  help            Print this message or the help of the given subcommand(s)

Arguments:
  [PROMPT]
          Optional user prompt to start the session

Options:
  -c, --config <key=value>
          Override a configuration value. Repeatable.

  -m, --model <MODEL>
          Model the agent should use

  -s, --sandbox <SANDBOX_MODE>
          Select the sandbox policy

          [possible values: read-only, workspace-write, danger-full-access]

      --search
          Enable live web search

      --dangerously-bypass-approvals-and-sandbox
          Skip all confirmation prompts and execute commands without sandboxing. EXTREMELY DANGEROUS.

  -h, --help
          Print help
"""


def test_parse_codex_commands_options_and_choices():
    schema = parse_help(CODEX_HELP, executable="codex")
    assert schema["title"] == "Codex CLI"
    assert schema["usage"].startswith("codex [OPTIONS]")
    assert [item["name"] for item in schema["commands"]] == ["exec", "review", "delete", "help"]
    assert next(item for item in schema["commands"] if item["name"] == "delete")["risk"] == "destructive"

    sandbox = next(item for item in schema["options"] if item["flag"] == "--sandbox")
    assert sandbox["takes_value"] is True
    assert sandbox["value_name"] == "SANDBOX_MODE"
    assert sandbox["choices"] == ["read-only", "workspace-write", "danger-full-access"]

    search = next(item for item in schema["options"] if item["flag"] == "--search")
    assert search["takes_value"] is False

    bypass = next(item for item in schema["options"] if item["flag"].startswith("--dangerously"))
    assert bypass["risk"] == "dangerous"


def test_parse_commander_style_help():
    schema = parse_help(
        """Gemini CLI\nUsage: gemini [options] [command]\n\nCommands:\n  chat <prompt>   Start chat\n  config          Manage configuration\n\nOptions:\n  -m, --model <name>   Select model\n  --debug              Enable debug output\n""",
        executable="gemini",
    )
    assert len(schema["commands"]) == 2
    assert len(schema["options"]) == 2
    assert schema["options"][0]["flag"] == "--model"


def test_parse_defaults_environment_deprecation_and_global_scope():
    schema = parse_help(
        """Example CLI
Usage: example [OPTIONS] COMMAND

Global Options:
  --region <REGION>  Region to use [env: EXAMPLE_REGION] [default: eu-west-1]
  --old              Deprecated compatibility mode

Commands:
  deploy <FILE>      Deploy a file
""",
        executable="example",
    )
    region = next(item for item in schema["options"] if item["flag"] == "--region")
    assert region["default"] == "eu-west-1"
    assert region["environment"] == "EXAMPLE_REGION"
    assert region["scope"] == "global"
    assert next(item for item in schema["options"] if item["flag"] == "--old")["deprecated"] is True
    assert schema["commands"][0]["arguments"][0]["name"] == "FILE"
    assert schema["parser"] == "heuristic-v3"


def test_parse_negatable_and_brace_choices():
    schema = parse_help(
        """Tool
Options:
  --[no-]color       Toggle colors
  --format {text,json,yaml}  Output format
""",
        executable="tool",
    )
    color = next(item for item in schema["options"] if item["flag"] == "--color")
    assert color["negatable"] is True
    assert color["flags"] == ["--color", "--no-color"]
    output = next(item for item in schema["options"] if item["flag"] == "--format")
    assert output["choices"] == ["text", "json", "yaml"]
