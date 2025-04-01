from typing import List, Optional
from pydantic import BaseModel


class RequiredDocument(BaseModel):
    """Model representing a required document for claim submission."""
    code: str
    category: str
    required: bool
    maxSizeAllowed: int
    fileTypesAllowed: List[str]


class ClaimDocumentChecklist(BaseModel):
    """Model representing a checklist of required documents for a claim type."""
    documents: List[RequiredDocument]

    def get_required_documents(self) -> List[RequiredDocument]:
        """
        Get only the required documents.
        
        Returns:
            A list of required documents
        """
        return [doc for doc in self.documents if doc.required]
    
    def get_optional_documents(self) -> List[RequiredDocument]:
        """
        Get only the optional documents.
        
        Returns:
            A list of optional documents
        """
        return [doc for doc in self.documents if not doc.required]
    
    def get_document_by_code(self, code: str) -> Optional[RequiredDocument]:
        """
        Get a document by its code.
        
        Args:
            code: The document code to look for
            
        Returns:
            The document if found, None otherwise
        """
        for doc in self.documents:
            if doc.code == code:
                return doc
        return None
