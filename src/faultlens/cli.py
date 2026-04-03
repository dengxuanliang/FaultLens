from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional, Sequence

from faultlens.config import load_settings
from faultlens.orchestrator import finalize_outputs, run_analysis



def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="faultlens")
    subparsers = parser.add_subparsers(dest="command")

    analyze = subparsers.add_parser("analyze")
    analyze.add_argument("--input", nargs=2, required=True)
    analyze.add_argument("--output-dir")
    analyze.add_argument("--case-id")
    analyze.add_argument("--env-file")
    analyze.add_argument("--model")
    analyze.add_argument("--base-url")
    analyze.add_argument("--api-key")
    analyze.add_argument("--llm-max-workers", type=int)
    analyze.add_argument("--llm-max-retries", type=int)
    analyze.add_argument("--llm-retry-backoff-seconds", type=int)
    analyze.add_argument("--llm-retry-on-5xx", dest="llm_retry_on_5xx", action="store_true")
    analyze.add_argument("--no-llm-retry-on-5xx", dest="llm_retry_on_5xx", action="store_false")
    analyze.set_defaults(llm_retry_on_5xx=None)
    analyze.add_argument("--resume", action="store_true")
    analyze.add_argument("--disable-checkpoints", action="store_true", help="deprecated no-op")

    rerender = subparsers.add_parser("rerender")
    rerender.add_argument("--output-dir", required=True)
    return parser



def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(list(argv) if argv is not None else None)
    except SystemExit as exc:
        return int(exc.code)

    if args.command == "rerender":
        finalize_outputs(output_dir=Path(args.output_dir))
        return 0

    if args.command != "analyze":
        parser.print_help()
        return 2

    settings = load_settings(
        env_path=Path(args.env_file) if args.env_file else None,
        api_key=args.api_key,
        base_url=args.base_url,
        model=args.model,
        output_dir=Path(args.output_dir) if args.output_dir else None,
        llm_max_workers=args.llm_max_workers,
        llm_max_retries=args.llm_max_retries,
        llm_retry_backoff_seconds=args.llm_retry_backoff_seconds,
        llm_retry_on_5xx=args.llm_retry_on_5xx,
        resume=True if args.resume else None,
        enable_checkpoints=False if args.disable_checkpoints else None,
    )
    run_analysis(
        input_paths=[Path(path) for path in args.input],
        settings=settings,
        output_dir=settings.output_dir,
        case_id=args.case_id,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
