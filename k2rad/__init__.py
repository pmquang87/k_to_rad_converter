"""
k2rad  –  LS-DYNA .k → OpenRadioss .rad converter.

Usage::

    from k2rad import convert
    result = convert("model.k")
    print(result.starter_path, result.engine_path)
    for w in result.warnings:
        print("WARNING:", w)
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from .parser import parse_k_file
from .handlers import dispatch
from .state import ConversionState
from .writer import build_starter, build_engine


@dataclass
class ConversionResult:
    starter_path: str
    engine_path: str
    warnings: List[str]
    skipped_keywords: List[str]


def convert(
    input_path: str,
    output_stem: Optional[str] = None,
    units: tuple = ("kg", "m", "s"),
) -> ConversionResult:
    """Convert a LS-DYNA .k file to OpenRadioss Starter + Engine .rad files.

    Parameters
    ----------
    input_path : str
        Path to the LS-DYNA keyword file (.k).
    output_stem : str, optional
        Base path for output files (without ``_0000.rad`` / ``_0001.rad``).
        Defaults to *input_path* with the extension removed.
    units : tuple of (mass, length, time)
        Unit strings for the /BEGIN header.  Defaults to SI (kg, m, s).
        The writer currently always emits "kg  m  s"; pass custom values
        to override the header only (solver uses input units).

    Returns
    -------
    ConversionResult
        Paths of the two generated files plus any warnings.
    """
    input_path = str(input_path)
    if output_stem is None:
        stem = Path(input_path).with_suffix("")
        output_stem = str(stem)

    starter_path = output_stem + "_0000.rad"
    engine_path  = output_stem + "_0001.rad"

    # 1. Parse
    blocks = parse_k_file(input_path)

    # 2. Dispatch each block to fill state
    state = ConversionState()
    for block in blocks:
        dispatch(block, state)

    # 3. Generate output text
    starter_text = build_starter(state)
    engine_text  = build_engine(state)

    # 4. Write files
    with open(starter_path, "w", newline="\n") as fh:
        fh.write(starter_text)
    with open(engine_path, "w", newline="\n") as fh:
        fh.write(engine_text)

    return ConversionResult(
        starter_path=starter_path,
        engine_path=engine_path,
        warnings=list(state.warnings),
        skipped_keywords=sorted(set(state.skipped_keywords)),
    )


__all__ = ["convert", "ConversionResult"]
