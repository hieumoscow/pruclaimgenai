from enum import Enum
from typing import List, Optional
from pydantic import BaseModel


class NationalIdTypeEnum(str, Enum):
    NRIC = "NRIC"
    FIN = "FIN"
    PASSPORT = "PASSPORT"


class Country(BaseModel):
    code: str
    name: str


class Address(BaseModel):
    line1: str
    line2: Optional[str] = None
    city: str
    state: Optional[str] = None
    postalCode: str
    country: Country


class Currency(BaseModel):
    code: str
    name: str
    symbol: str


class CurrencyResponse(BaseModel):
    currencies: List[Currency] = []