"""
Quick profiling helper.

Usage:
  python -m scripts.profile --module offside_bot --func main
"""
from __future__ import annotations

import argparse
import cProfile
import importlib
import pstats
import sys


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--module", required=True, help="Module to import (e.g., offside_bot.__main__)")
    parser.add_argument("--func", required=True, help="Callable to run (e.g., main)")
    args = parser.parse_args()

    mod = importlib.import_module(args.module)
    func = getattr(mod, args.func, None)
    if not func:
        print(f"Function {args.func} not found in module {args.module}")
        sys.exit(1)

    profiler = cProfile.Profile()
    profiler.enable()
    func()
    profiler.disable()
    stats = pstats.Stats(profiler).sort_stats("cumulative")
    stats.print_stats(20)


if __name__ == "__main__":
    main()
