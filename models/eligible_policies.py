from typing import List, Optional
from pydantic import BaseModel, Field


class Coverage(BaseModel):
    """Coverage details for a life assured"""
    medical_minor: bool = Field(..., alias="medicalMinor")
    medical_major: bool = Field(..., alias="medicalMajor")


class Person(BaseModel):
    """Person model representing a life assured or policy owner"""
    id: str
    name: str
    coverage: Optional[Coverage] = None


class PolicyStatus(BaseModel):
    """Status of a policy"""
    type: str
    is_active: bool = Field(..., alias="isActive")


class Policy(BaseModel):
    """Policy details"""
    id: str
    code: str
    name: str
    status: PolicyStatus
    lives_assured: List[Person] = Field(..., alias="livesAssured")
    owner: Person


class EligiblePolicy(BaseModel):
    """Eligible policy for health claims"""
    policy: Policy
    category: str
    claim_types: List[str] = Field(..., alias="claimTypes")


class EligiblePoliciesResponse(BaseModel):
    """Response model for eligible policies endpoint"""
    policies: List[EligiblePolicy] = Field(default_factory=list)
