"""
shared — utilities shared across all Telecoupling tool modules.

Import from tool files with:
    from shared.utils import CSISError, validate_required, generate_output_dir, \
                             scan_output_directory, run_r_script
"""

from .utils import (
    CSISError,
    validate_required,
    generate_output_dir,
    scan_output_directory,
    run_r_script,
)

__all__ = [
    "CSISError",
    "validate_required",
    "generate_output_dir",
    "scan_output_directory",
    "run_r_script",
]
