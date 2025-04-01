from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field
from models.common import Currency


class BillItem(BaseModel):
    """Model representing a bill item from a receipt."""
    service: str = Field(default="")
    detail: str = Field(default="")
    amount: str = Field(default="")


class ExtractedField(BaseModel):
    """Model representing an extracted field from a document."""
    type: str
    value_string: Optional[str] = Field(default=None, alias="valueString")
    value_array: Optional[List[Any]] = Field(default=None, alias="valueArray")
    value_object: Optional[Dict[str, Any]] = Field(default=None, alias="valueObject")
    confidence: float = Field(default=0.0)
    spans: Optional[List[Dict[str, int]]] = Field(default=None)
    source: Optional[str] = Field(default=None)


class DocumentFields(BaseModel):
    """Model representing all fields extracted from a document."""
    receipt_number: Optional[ExtractedField] = Field(default=None, alias="ReceiptNumber")
    receipt_date: Optional[ExtractedField] = Field(default=None, alias="ReceiptDate")
    admission_date: Optional[ExtractedField] = Field(default=None, alias="AdmissionDate")
    discharge_date: Optional[ExtractedField] = Field(default=None, alias="DischargeDate")
    hospital: Optional[ExtractedField] = Field(default=None, alias="Hospital")
    currency: Optional[ExtractedField] = Field(default=None, alias="Currency")
    bill_amount: Optional[ExtractedField] = Field(default=None, alias="BillAmount")
    gst: Optional[ExtractedField] = Field(default=None, alias="GST")
    bill_items: Optional[ExtractedField] = Field(default=None, alias="BillItems")


class DocumentContent(BaseModel):
    """Model representing the content of an analyzed document."""
    markdown: str
    fields: DocumentFields
    kind: str
    start_page_number: int = Field(alias="startPageNumber")
    end_page_number: int = Field(alias="endPageNumber")
    unit: str
    pages: List[Dict[str, Any]]


class AnalyzeDocumentResult(BaseModel):
    """Model representing the result of document analysis."""
    analyzer_id: str = Field(alias="analyzerId")
    api_version: str = Field(alias="apiVersion")
    created_at: str = Field(alias="createdAt")
    warnings: List[str]
    contents: List[DocumentContent]


class AnalyzeDocumentResponse(BaseModel):
    """Model representing the response from the document analysis API."""
    id: str
    status: str
    result: AnalyzeDocumentResult


class ReceiptExtractionResult(BaseModel):
    """Model representing the result of receipt extraction."""
    success: bool
    file_name: str
    file_path: Optional[str] = None
    receipt_number: Optional[str] = None
    receipt_date: Optional[str] = None
    admission_date: Optional[str] = None
    discharge_date: Optional[str] = None
    hospital: Optional[str] = None
    currency: Optional[Currency] = None
    amount: Optional[float] = None
    md_content: Optional[str] = None
    extracted_data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    bill_items: Optional[List[BillItem]] = None
