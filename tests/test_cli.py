from faultlens.cli import main


def test_cli_requires_two_input_files(capsys):
    exit_code = main(["analyze", "--input", "only-one.jsonl"])
    assert exit_code == 2
