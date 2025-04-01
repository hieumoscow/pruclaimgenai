from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field

from models.common import Address, Currency
from models.policy import PayoutMethodModeEnum, BankAccount


class ClaimTypeEnum(str, Enum):
    HOSPITALISATION = "HOSPITALISATION"
    OUTPATIENT = "OUTPATIENT"


class Status(BaseModel):
    type: str
    isActive: bool
    systemStatus: str

class LifeAssured(BaseModel):
    id: str
    name: str
    subRole: str

class Owner(BaseModel):
    id: str
    name: str

class Policy(BaseModel):
    id: str
    code: str
    name: str
    status: Status
    livesAssured: List[LifeAssured]
    owner: Owner

class DocumentCategory(BaseModel):
    type: str
    description: str

class DocumentChecklistItem(BaseModel):
    documentCategory: DocumentCategory
    required: bool
    maxSizeAllowed: int
    fileTypesAllowed: List[str]


class Hospital(BaseModel):
    id: str
    name: str
    type: str
    address: Address


class LifeAssuredParty(BaseModel):
    id: str
    name: str
    policy_ids: List[str]

class ClaimCategoryEnum(str, Enum):
    REIMBURSEMENT = "REIMBURSEMENT"
    CASHLESS = "CASHLESS"

class ClaimDetails(BaseModel):
    hospitalName: str
    claimingFromOtherInsurers: bool
    finalAmount: float

class ClaimDocumentType(str, Enum):
    RECEIPT = "RECEIPT"
    MEDICAL_REPORT = "MEDICAL_REPORT"
    SPECIALIST_REPORT = "SPECIALIST_REPORT"
    HOSPITAL_BILL = "HOSPITAL_BILL"
    OTHERS = "OTHERS"

class ClaimDocument(BaseModel):
    type: ClaimDocumentType
    id: str

class ClaimReceipt(BaseModel):
    number: str
    receiptDate: date
    admissionDate: Optional[date] = None
    dischargeDate: Optional[date] = None
    hospitalName: str
    currency: Currency
    amount: float
    documents: List[ClaimDocument]

class ClaimPayout(BaseModel):
    mode: PayoutMethodModeEnum
    currency: Currency
    account: BankAccount

class Claim(BaseModel):
    clientId: str # client (owner) id
    lifeAssured: str # life assured id
    claimType: ClaimTypeEnum
    policyId: str # chosen policy id
    details: ClaimDetails
    receipts: List[ClaimReceipt]
    documents: List[ClaimDocument]
    payout: ClaimPayout

class ClaimDraft(BaseModel):
    id: Optional[str] = Field(None, alias="_id")
    clientId: str # client (owner) id
    lifeAssured: Optional[str] = None # life assured id
    lifeAssuredName: Optional[str] = None # life assured name
    claimType: Optional[ClaimTypeEnum] = None
    policyId: Optional[str] = None # chosen policy id
    policyName: Optional[str] = None # policy name
    details: Optional[ClaimDetails] = None
    receipts: Optional[List[ClaimReceipt]] = None
    documents: Optional[List[ClaimDocument]] = None
    payout: Optional[ClaimPayout] = None



class ClaimSubmitResponse(BaseModel):
    lifeAssured: LifeAssuredParty
    transactionType: str
    claimId: str
    claimType: ClaimTypeEnum
    submissionDate: datetime
    policyIds: List[str]