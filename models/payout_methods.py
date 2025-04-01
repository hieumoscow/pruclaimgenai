from typing import List, Optional
from pydantic import BaseModel


class Currency(BaseModel):
    code: str
    name: str
    symbol: str


class Account(BaseModel):
    name: str
    branch_code: Optional[str] = None
    account_no: str
    account_name: Optional[str] = None
    swift_code: Optional[str] = None
    aba_routing_number: Optional[str] = None
    routing_code: Optional[str] = None
    address: Optional[str] = None


class PayoutMethod(BaseModel):
    id: str
    mode: str
    currency: Currency
    account: Account
    name: str
    address: Optional[str] = None
    uniqueId: Optional[str] = None
    uniqueIdType: Optional[str] = None
    status: str
    
    def get_display_name(self) -> str:
        """Returns a formatted display name for the payout method"""
        return f"{self.mode} - {self.account.name} ({self.account.account_no})"


class PayoutMethodsResponse(BaseModel):
    methods: List[PayoutMethod]
