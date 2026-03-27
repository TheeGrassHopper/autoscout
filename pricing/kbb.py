"""
pricing/kbb.py
Shared PriceEstimate dataclass used across all pricing modules.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class PriceEstimate:
    source: str
    make: str
    model: str
    year: int
    mileage: int
    trade_in_low: Optional[int] = None
    trade_in_high: Optional[int] = None
    private_party_low: Optional[int] = None
    private_party_high: Optional[int] = None
    retail_low: Optional[int] = None
    retail_high: Optional[int] = None
    fair_market_value: Optional[int] = None  # midpoint used for scoring
    confidence: str = "low"   # low / medium / high

    def to_dict(self) -> dict:
        return self.__dict__.copy()
