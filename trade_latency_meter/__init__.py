"""Stage stopwatch for trading-bot hot paths. Standard library only."""
from .meter import Handle, Meter, measure_overhead

__version__ = "0.1.0"
__all__ = ["Meter", "Handle", "measure_overhead", "__version__"]
