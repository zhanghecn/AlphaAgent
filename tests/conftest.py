"""Keep local tests from oversubscribing native numerical libraries."""

import os


_SINGLE_THREAD_VARIABLES = (
    "OPENBLAS_NUM_THREADS",
    "OMP_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
)

for variable in _SINGLE_THREAD_VARIABLES:
    os.environ[variable] = "1"
