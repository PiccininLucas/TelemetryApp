"""Pure analysis: numpy arrays in, numbers out.

Hard rule, enforced by `tests/test_architecture.py`: this package must not
import `duckdb`, `pandas`, PySide6/Qt, or anything from the `application`,
`infrastructure` or `presentation` layers.

Two things depend on that isolation. Every formula here can be tested against
synthetic data without the game installed, and a live data source could feed the
same functions later without a single equation being touched.
"""
