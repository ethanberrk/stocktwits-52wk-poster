"""Run manually: pytest -m contract tests/contract/test_live_stocktwits.py -v"""
import pytest

from src.stocktwits import symbol_exists
from src.source.base import Candidate

pytestmark = pytest.mark.contract

def cand(ticker):
    return Candidate(ticker, "X", "NYSE", 0, 0, 0, 0, "EQUITY")

def test_live_symbol_lookup():
    assert symbol_exists(cand("AAPL")) is True
    assert symbol_exists(cand("BRK-B")) is True     # resolves via BRK.B mapping
    assert symbol_exists(cand("ZZZZZZZ9")) is False
