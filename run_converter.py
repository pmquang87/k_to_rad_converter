from k2rad import convert

# ── Set your input file path here ─────────────────────────────────────────────
INPUT_K = r"C:\Users\pmqua\PycharmProjects\k_to_rad_converter\implicit_hr-anlenkung\6kN_symmestry-boundary\implicit_hr-anlenkung.k"

# Optional: set a custom output stem (default = same folder/name as input)
OUTPUT_STEM = None   # e.g. r"output\BendTest" to write to a different location
# ──────────────────────────────────────────────────────────────────────────────

result = convert(INPUT_K, output_stem=OUTPUT_STEM)

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