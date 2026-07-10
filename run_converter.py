"""Convenience script: convert a single .k file without the full CLI.

Usage:
    python run_converter.py path/to/model.k [output/stem]

Or set INPUT_K below to a hardcoded path and run with no arguments.
"""

import sys
from pathlib import Path

try:
    from k2rad import convert
except ImportError:                              # running from an odd CWD
    sys.path.insert(0, str(Path(__file__).parent))
    from k2rad import convert

# ── Optional: set a default input file path here ──────────────────────────────
INPUT_K = None       # e.g. r"implicit_hr-anlenkung/implicit_hr-anlenkung.k"
OUTPUT_STEM = None   # e.g. r"output/BendTest"; None = same folder/name as input
# ──────────────────────────────────────────────────────────────────────────────


def main() -> int:
    input_k = sys.argv[1] if len(sys.argv) > 1 else INPUT_K
    output_stem = sys.argv[2] if len(sys.argv) > 2 else OUTPUT_STEM

    if not input_k:
        print("Usage: python run_converter.py path/to/model.k [output/stem]",
              file=sys.stderr)
        return 1

    result = convert(input_k, output_stem=output_stem)

    print(f"Starter -> {result.starter_path}")
    print(f"Engine  -> {result.engine_path}")

    if result.skipped_keywords:
        print(f"\nSkipped keywords ({len(result.skipped_keywords)}):")
        for kw in result.skipped_keywords:
            print(f"  *{kw}")

    if result.warnings:
        print(f"\nWarnings ({len(result.warnings)}):")
        for w in result.warnings:
            print(f"  {w}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
