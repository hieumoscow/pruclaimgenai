from enum import Enum
from typing import List, Optional
from pydantic import BaseModel


class PayoutMethodModeEnum(str, Enum):
    DIRECT_CREDIT = "DIRECT_CREDIT"
    CHEQUE = "CHEQUE"
    PAYNOW = "PAYNOW"


class PayoutMethodStatusEnum(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class BankAccount(BaseModel):
    name: str
    holder: str
    branch_code: Optional[str] = None
    account_no: str
