from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional, Sequence

from faultlens.config import load_settings
from faultlens.orchestrator import run_analysis


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="faultlens")
    subparsers = parser.add_subparsers(dest="command")

    analyze = subparsers.add_parser("analyze")
    analyze.add_argument("--input", nargs=2, required=True)
    analyze.add_argument("--output-dir", default="outputs")
    analyze.add_argument("--case-id")
    analyze.add_argument("--env-file")
    analyze.add_argument("--model")
    analyze.add_argument("--base-url")
    analyze.add_argument("--api-key")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(list(argv) if argv is not None else None)
    except SystemExit as exc:
        return int(exc.code)

    if args.command != "analyze":
        parser.print_help()
        return 2

    settings = load_settings(
        env_path=Path(args.env_file) if args.env_file else None,
        api_key=args.api_key,
        base_url=args.base_url,
        model=args.model,
        output_dir=Path(args.output_dir),
    )
    run_analysis(
        input_paths=[Path(path) for path in args.input],
        settings=settings,
        output_dir=Path(args.output_dir),
        case_id=args.case_id,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
