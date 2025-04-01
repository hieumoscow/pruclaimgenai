import os
import json
import asyncio
from dotenv import load_dotenv, find_dotenv
from openai import AzureOpenAI
from typing import List, Dict, Any, Optional, Tuple
from datetime import date

# Import functions from the existing codebase
from functions import get_claim_schema
from models.common import Currency
from models.eligible_policies import EligiblePoliciesResponse
from models.claim import Claim, ClaimTypeEnum, ClaimReceipt, ClaimDocument

# Force reload of environment variables
load_dotenv(find_dotenv(), override=True)

# Initialize the Azure OpenAI client
client = AzureOpenAI(
    api_key=os.environ["AZURE_OPENAI_API_KEY"],  
    api_version=os.environ["AZURE_OPENAI_API_VERSION"],
    azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"]
)

# Get the assistant ID from environment variables
ASSISTANT_ID = os.environ.get("ASSISTANT_ID")
if not ASSISTANT_ID:
    raise ValueError("ASSISTANT_ID not found in environment variables. Run aoai_assistant_setup.py first.")

def create_thread():
    """
    Create a new thread for conversation with the assistant.
    
    Returns:
        str: The ID of the newly created thread
    """
    thread = client.beta.threads.create()
    return thread.id

def determine_claim_type(
    client_profile: Dict[str, Any], 
    receipts: List[Dict[str, Any]]
) -> ClaimTypeEnum:
    """
    Determine the appropriate claim type based on receipt data and policy information.
    
    Args:
        client_profile: The client's profile with eligible policies
        receipts: List of processed receipts
        
    Returns:
        ClaimTypeEnum: The determined claim type
    """
    # Extract available claim types from the client profile
    available_claim_types = []
    for policy in client_profile.get("policies", []):
        if policy.get("claim_types"):
            available_claim_types.extend(policy.get("claim_types"))
    
    # Check if there's a hospital stay in any of the receipts
    has_hospital_stay = any(
        receipt.get("admissionDate") is not None and 
        receipt.get("dischargeDate") is not None and
        receipt.get("hospitalName") is not None
        for receipt in receipts
    )
    
    # Check if any receipt mentions an accident
    is_accident = any(
        "accident" in receipt.get("description", "").lower() 
        for receipt in receipts 
        if receipt.get("description")
    )
    
    # Check if any receipt mentions dental work
    is_dental = any(
        "dental" in receipt.get("description", "").lower() 
        for receipt in receipts 
        if receipt.get("description")
    )
    
    # Determine the claim type based on the data
    if has_hospital_stay:
        if is_accident and "ACCIDENT_HOSPITALISATION" in available_claim_types:
            return ClaimTypeEnum.ACCIDENT_HOSPITALISATION
        elif "HOSPITALISATION" in available_claim_types:
            return ClaimTypeEnum.HOSPITALISATION
        elif "PRU_SHIELD" in available_claim_types:
            return ClaimTypeEnum.PRU_SHIELD
    else:
        if is_accident and "ACCIDENT_NON_HOSPITALISATION" in available_claim_types:
            return ClaimTypeEnum.ACCIDENT_NON_HOSPITALISATION
        elif is_dental and "DENTAL" in available_claim_types:
            return ClaimTypeEnum.DENTAL
        elif "OUTPATIENT" in available_claim_types:
            return ClaimTypeEnum.OUTPATIENT
    
    # Default to HOSPITALISATION if we can't determine
    if "HOSPITALISATION" in available_claim_types:
        return ClaimTypeEnum.HOSPITALISATION
    
    # If HOSPITALISATION is not available, use the first available claim type
    if available_claim_types:
        return ClaimTypeEnum(available_claim_types[0])
    
    # Last resort
    return ClaimTypeEnum.HOSPITALISATION

def fill_schema(
    claim_type: ClaimTypeEnum,
    client_profile: Dict[str, Any],
    currency_response: Dict[str, Any],
    receipts: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Fill the claim schema with data from receipts and client profile.
    
    Args:
        claim_type: The determined claim type
        client_profile: The client's profile with eligible policies
        currency_response: Available currencies
        receipts: List of processed receipts
        
    Returns:
        Dict[str, Any]: The filled schema
    """
    # Get the schema for the claim type
    schema = get_claim_schema(claim_type)
    
    # Create a copy of the schema to fill
    filled_schema = schema.copy()
    
    # Fill basic information
    if "policyNumber" in filled_schema:
        # Use the first policy from the client profile
        if client_profile.get("policies") and len(client_profile["policies"]) > 0:
            filled_schema["policyNumber"] = client_profile["policies"][0].get("policy_id", "")
    
    if "lifeAssured" in filled_schema:
        # Use the first life assured from the first policy
        if (client_profile.get("policies") and 
            len(client_profile["policies"]) > 0 and 
            client_profile["policies"][0].get("lives_assured") and 
            len(client_profile["policies"][0]["lives_assured"]) > 0):
            filled_schema["lifeAssured"] = client_profile["policies"][0]["lives_assured"][0].get("name", "")
    
    # Fill currency information
    if "currency" in filled_schema:
        # Use the currency from the first receipt
        if receipts and len(receipts) > 0 and receipts[0].get("currency"):
            filled_schema["currency"] = receipts[0]["currency"].get("code", "SGD")
    
    # Fill receipt-specific information
    if "receiptNumber" in filled_schema and receipts and len(receipts) > 0:
        filled_schema["receiptNumber"] = receipts[0].get("number", "")
    
    if "receiptDate" in filled_schema and receipts and len(receipts) > 0:
        filled_schema["receiptDate"] = receipts[0].get("receiptDate", "")
    
    if "hospitalName" in filled_schema and receipts and len(receipts) > 0:
        filled_schema["hospitalName"] = receipts[0].get("hospitalName", "")
    
    if "admissionDate" in filled_schema and receipts and len(receipts) > 0:
        filled_schema["admissionDate"] = receipts[0].get("admissionDate", "")
    
    if "dischargeDate" in filled_schema and receipts and len(receipts) > 0:
        filled_schema["dischargeDate"] = receipts[0].get("dischargeDate", "")
    
    if "claimAmount" in filled_schema and receipts and len(receipts) > 0:
        filled_schema["claimAmount"] = receipts[0].get("amount", 0)
    
    # Fill total amount
    if "totalAmount" in filled_schema and receipts:
        filled_schema["totalAmount"] = sum(receipt.get("amount", 0) for receipt in receipts)
    
    return filled_schema

async def determine_claim_type_and_fill_schema(
    client_profile: EligiblePoliciesResponse,
    currency_response: Dict[str, Any],
    summary: str,
    receipts: List[ClaimReceipt]
) -> Tuple[ClaimTypeEnum, Dict[str, Any]]:
    """
    Determine the appropriate claim type and fill the schema.
    
    Args:
        client_profile: The client's profile with eligible policies
        currency_response: Available currencies
        summary: Summary of the receipt processing
        receipts: List of processed receipts
        
    Returns:
        tuple: (determined_claim_type, filled_schema)
    """
    # Format the client profile data
    formatted_client_profile = {
        "policies": []
    }
    
    for policy in client_profile.policies:
        policy_dict = {
            "policy_id": policy.policy.id,
            "policy_name": policy.policy.name,
            "status": "Active" if policy.policy.status.is_active else "Inactive",
            "lives_assured": [{"id": life.id, "name": life.name} for life in policy.policy.lives_assured],
            "claim_types": policy.claim_types
        }
        formatted_client_profile["policies"].append(policy_dict)
    
    # Format the receipts data
    formatted_receipts = []
    for receipt in receipts:
        receipt_dict = {
            "number": receipt.number,
            "receiptDate": receipt.receiptDate.isoformat() if isinstance(receipt.receiptDate, date) else receipt.receiptDate,
            "admissionDate": receipt.admissionDate.isoformat() if isinstance(receipt.admissionDate, date) else receipt.admissionDate,
            "dischargeDate": receipt.dischargeDate.isoformat() if isinstance(receipt.dischargeDate, date) else receipt.dischargeDate,
            "hospitalName": receipt.hospitalName,
            "currency": {
                "code": receipt.currency.code,
                "name": receipt.currency.name,
                "symbol": receipt.currency.symbol
            },
            "amount": receipt.amount
        }
        formatted_receipts.append(receipt_dict)
    
    # Determine the claim type
    claim_type = determine_claim_type(formatted_client_profile, formatted_receipts)
    
    # Fill the schema
    filled_schema = fill_schema(claim_type, formatted_client_profile, currency_response, formatted_receipts)
    
    return claim_type, filled_schema

async def main():
    """
    Example usage of the claim schema agent.
    """
    # Sample data - replace with actual data from your application
    from functions import get_eligible_policies, get_currencies
    
    client_id = "S1234567D"
    
    # Get client profile
    client_profile = get_eligible_policies(client_id)
    
    # Get currencies
    currency_response = get_currencies()
    
    # Sample receipt
    receipt_document = ClaimDocument(
        type="RECEIPT",
        id="receipt_1"
    )
    
    receipt = ClaimReceipt(
        number="R12345",
        receiptDate=date(2025, 3, 30),
        admissionDate=date(2025, 3, 25),
        dischargeDate=date(2025, 3, 28),
        hospitalName="Singapore General Hospital",
        currency=Currency(code="SGD", name="Singapore Dollar", symbol="$"),
        amount=1500.00,
        documents=[receipt_document]
    )
    
    # Sample summary
    summary = """
## Receipt Processing Summary

- Successfully processed: 1 receipt(s)

Total claim amount: 1500.0 SGD
"""
    
    try:
        # Determine claim type and fill schema
        claim_type, filled_schema = await determine_claim_type_and_fill_schema(
            client_profile=client_profile,
            currency_response=currency_response.model_dump(),
            summary=summary,
            receipts=[receipt]
        )
        
        print(f"Determined claim type: {claim_type}")
        print("Filled schema:")
        print(json.dumps(filled_schema, indent=2))
        
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(main())
