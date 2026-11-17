"""Event-driven backtester — part of the AI Workflow Portfolio."""
__version__ = "0.1.0"
from .data import load_csv, resample, synthetic_ticks  # noqa: E402
from .engine import Backtest, ExecConfig, LookaheadError, Result, Strategy, run_kernel  # noqa: E402
from .strategies import (CUSTOM_TEMPLATE, BollingerReversion, CodeStrategy, DonchianBreakout, LeakyStrategy,  # noqa: E402
                         MACross, VolTargetMomentum)
