"""Command-line entry point for local synthetic match generation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from receipts_common.bus import LocalEventBus

from .demo import verify_demo, write_demo
from .realism import parse_seeds, write_report
from .simulation import generate_match
from .streaming import StreamControl, stream_events


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="generator",
        description="Generate a deterministic synthetic match stream.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    generate = subparsers.add_parser("generate", help="write a validated JSONL event stream")
    generate.add_argument("--seed", type=int, required=True)
    generate.add_argument("--minutes", type=int, default=90)
    generate.add_argument("--hz", type=int, default=5)
    generate.add_argument("--no-tracking", action="store_true")
    generate.add_argument("--out", type=Path)

    report = subparsers.add_parser("report", help="evaluate a seeded batch against realism targets")
    report.add_argument("--seeds", default="1-200")
    report.add_argument("--out", type=Path, default=Path("docs/data-validation.md"))

    stream = subparsers.add_parser("stream", help="publish a paced match to the local bus")
    stream.add_argument("--seed", type=int, required=True)
    stream.add_argument("--minutes", type=int, default=90)
    stream.add_argument("--hz", type=int, default=5)
    stream.add_argument("--speed", type=float, default=1.0)
    stream.add_argument("--from-seq", type=int, default=1)
    stream.add_argument("--sink", choices=("local",), default="local")

    demo = subparsers.add_parser("find-demo-seed", help="select and save a narrative-rich demo")
    demo.add_argument("--seeds", default="1-500")
    demo.add_argument("--config", type=Path, default=Path("config/demo.json"))
    demo.add_argument("--cut", type=Path, default=Path("tests/golden/demo-20min.jsonl"))
    demo.add_argument("--golden", type=Path, default=Path("tests/golden/demo-20min.sha256"))

    verify = subparsers.add_parser(
        "verify-demo", help="verify committed demo config and golden cut"
    )
    verify.add_argument("--config", type=Path, default=Path("config/demo.json"))
    verify.add_argument("--cut", type=Path, default=Path("tests/golden/demo-20min.jsonl"))
    verify.add_argument("--golden", type=Path, default=Path("tests/golden/demo-20min.sha256"))
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        if args.command == "generate":
            events = generate_match(
                args.seed, args.minutes, args.hz, include_tracking=not args.no_tracking
            )
            _write_jsonl(events, args.out)
        elif args.command == "report":
            seeds = parse_seeds(args.seeds)
            passed, failures = write_report(seeds, args.out)
            if not passed:
                print(f"generator report failed metrics: {failures}", file=sys.stderr)
                return 1
            print(f"Realism report passed for {len(seeds)} seeds: {args.out}")
        elif args.command == "stream":
            events = generate_match(args.seed, args.minutes, args.hz)
            bus = LocalEventBus()
            count = stream_events(
                events,
                bus,
                speed=args.speed,
                from_seq=args.from_seq,
                control=StreamControl(),
            )
            for record in bus.records("events"):
                _write_jsonl([record.doc], None)
            print(f"Published {count} events to the local EventBus.", file=sys.stderr)
        elif args.command == "find-demo-seed":
            seeds = parse_seeds(args.seeds)
            candidate = write_demo(seeds, args.config, args.cut, args.golden)
            print(
                f"Selected seed {candidate.seed} (score {candidate.score}/4); "
                f"wrote {args.config} and {args.cut}"
            )
        elif args.command == "verify-demo":
            passed, result = verify_demo(args.config, args.cut, args.golden)
            if not passed:
                print(f"generator demo verification failed: {result}", file=sys.stderr)
                return 1
            print(f"Demo artifacts verified: {result}")
    except (OSError, ValueError) as exc:
        print(f"generator: {exc}", file=sys.stderr)
        return 1
    return 0


def _write_jsonl(events: list[dict], path: Path | None) -> None:
    if path:
        path.parent.mkdir(parents=True, exist_ok=True)
    target = path.open("w", encoding="utf-8", newline="\n") if path else sys.stdout
    try:
        for event in events:
            line = json.dumps(event, sort_keys=True, separators=(",", ":"), allow_nan=False)
            target.write(line + "\n")
    finally:
        if path:
            target.close()


if __name__ == "__main__":
    raise SystemExit(main())