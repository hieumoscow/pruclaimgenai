import re
import chainlit as cl
from dotenv import load_dotenv, find_dotenv
from typing import Optional, List, Dict, Any
from chainlit.action import Action
from datetime import datetime, date
import concurrent.futures
import asyncio
import json
import os

# Import functions from the existing codebase
from aoai_assistant_setup import ClaimResponse
from functions import get_eligible_policies, get_currencies, analyze_document, get_claim_schema, get_payout_methods
from models.common import Currency, CurrencyResponse
from models.eligible_policies import EligiblePoliciesResponse
from models.claim import Claim, ClaimTypeEnum, ClaimReceipt, ClaimDocument, ClaimDetails, ClaimPayout
from models.policy import PayoutMethodModeEnum, BankAccount
from models.receipt import AnalyzeDocumentResponse, ReceiptExtractionResult, BillItem
from models.payout_methods import PayoutMethodsResponse

# Import the OpenAI assistant API functions
from aoai_assistant_run import run_conversation, create_thread

# Load environment variables
load_dotenv(find_dotenv(), override=True)

# Get the assistant ID from environment variables
ASSISTANT_ID = os.environ.get("ASSISTANT_ID")
if not ASSISTANT_ID:
    raise ValueError("ASSISTANT_ID not found in environment variables. Run aoai_assistant_setup.py first.")

# Global variables
client_profile: EligiblePoliciesResponse = None
currency_response: CurrencyResponse = None
# Initialize an empty claim object
claim = None
thread_id = None  # Store the thread ID for the assistant conversation

# Configure authentication
@cl.password_auth_callback
def auth_callback(username: str, password: str) -> Optional[cl.User]:
    # In a real app, you'd check the password against a database
    # For this demo, we'll accept any username as a client ID with any password
    return cl.User(
        identifier=username,
        metadata={
            "client_id": username,
            "role": "client"
        }
    )

async def display_message(content: str, author: str = "System"):
    """Display a message to the user"""
    await cl.Message(
        content=content,
        author=author
    ).send()

def format_policies_info(policiesRs: EligiblePoliciesResponse):
    """Format eligible policies information into a markdown table"""
    policies_info = "### Eligible Policies\n\n"
    policies = policiesRs.policies
    
    if len(policies) > 0:
        policies_info += "| Policy ID | Policy Name | Status | Lives Assured | Claim Types |\n"
        policies_info += "|-----------|-------------|--------|--------------|-------------|\n"
        
        for policy in policies:
            policy_id = policy.policy.id
            policy_name = policy.policy.name
            
            # Get policy status
            status = "Active" if policy.policy.status.is_active else "Inactive"
            
            # Get lives assured names
            lives_assured_names = []
            for life in policy.policy.lives_assured:
                lives_assured_names.append(life.name)
            
            lives_assured_str = ", ".join(lives_assured_names) if lives_assured_names else "N/A"
            claim_types = ", ".join(policy.claim_types) if policy.claim_types else "N/A"
            
            policies_info += f"| {policy_id} | {policy_name} | {status} | {lives_assured_str} | {claim_types} |\n"
    else:
        policies_info += "No eligible policies found for this client.\n"
    
    return policies_info

def format_currencies_info(currency_response):
    """Format available currencies information into a markdown table"""
    currency_info = "### Available Currencies\n\n"
    if currency_response and currency_response.currencies:
        currency_info += "| Code | Name | Symbol |\n"
        currency_info += "|------|------|--------|\n"
        for currency in currency_response.currencies:
            currency_info += f"| {currency.code} | {currency.name} | {currency.symbol} |\n"
    else:
        currency_info += "No currencies available.\n"
    
    return currency_info

def initialize_claim(client_id: str) -> Claim:
    """Initialize a new claim object with default values"""
    # Create default empty claim
    return Claim(
        clientId=client_id,
        lifeAssured="",  # Will be set when user selects life assured
        claimType=ClaimTypeEnum.HOSPITALISATION,  # Default, will be set based on user selection
        policyId="",  # Will be set when user selects policy
        details=ClaimDetails(
            hospitalName="",
            claimingFromOtherInsurers=False,
            finalAmount=0.0
        ),
        receipts=[],
        documents=[],
        payout=ClaimPayout(
            mode=PayoutMethodModeEnum.DIRECT_CREDIT,  # Default payout method
            currency=Currency(code="SGD", name="Singapore Dollar", symbol="$"),  # Default currency
            account=BankAccount(
                name="Default Bank",
                holder=client_id,  # Use client ID as default account holder
                account_no="",  # Will be filled in later
                branch_code=None
            )
        )
    )

async def extract_receipt(file: cl.File) -> ReceiptExtractionResult:
    """
    Extract information from a receipt file using Azure Document Intelligence.
    
    Args:
        file: The uploaded file
        
    Returns:
        ReceiptExtractionResult: The extracted receipt information
    """
    try:
        # Get the file path
        file_path = file.path
        
        # Analyze the document
        extracted_data = analyze_document(file_path)

        print(f"Extracted data: {extracted_data}")
        
        # Parse the response as AnalyzeDocumentResponse
        response = AnalyzeDocumentResponse.model_validate(extracted_data)
        
        # Get the first content
        content = response.result.contents[0]
        fields = content.fields
        
        # Extract the markdown content
        md_content = content.markdown
        
        # Extract key fields
        receipt_number = fields.receipt_number.value_string if fields.receipt_number else ""
        receipt_date_str = fields.receipt_date.value_string if fields.receipt_date else ""
        admission_date_str = fields.admission_date.value_string if fields.admission_date else ""
        discharge_date_str = fields.discharge_date.value_string if fields.discharge_date else ""
        hospital = fields.hospital.value_string if fields.hospital else ""
        
        # Default currency to SGD if not found
        currency_code = "SGD"
        if fields.currency and fields.currency.value_string:
            currency_code = fields.currency.value_string
            
        bill_amount_str = fields.bill_amount.value_string if fields.bill_amount else "0.0"
        
        # Convert bill amount to float
        bill_amount = 0.0
        try:
            # Remove currency symbol and commas
            cleaned_amount = bill_amount_str.replace("$", "").replace(",", "").strip()
            bill_amount = float(cleaned_amount)
        except ValueError:
            bill_amount = 0.0
            
        # Create currency object using the Currency model
        currency_obj = Currency(
            code=currency_code,
            name=f"{currency_code} Currency",
            symbol="$" if currency_code == "SGD" else currency_code
        )

        
        # Create markdown content for display
        md_content += "\n### Receipt Details\n\n"
        md_content += "| Field | Value |\n"
        md_content += "|-------|-------|\n"
        
        # Create simplified data for display
        simplified_data = {
            "Receipt Number": receipt_number,
            "Receipt Date": receipt_date_str,
            "Admission Date": admission_date_str,
            "Discharge Date": discharge_date_str,
            "Hospital": hospital,
            "Currency": currency_code,
            "Bill Amount": bill_amount_str,
            "GST": fields.gst.value_string if fields.gst else ""
        }
        
        for key, value in simplified_data.items():
            field_key = key.replace(" ", "")  # Convert to format matching the API response
            confidence = getattr(fields, field_key.lower(), None)
            confidence_str = f"{confidence.confidence:.2f}" if confidence and hasattr(confidence, 'confidence') else "N/A"
            md_content += f"| {key} | {value} |\n"
        
        # Extract bill items
        bill_items = []
        if fields.bill_items and fields.bill_items.value_array:
            md_content += "\n### Bill Items\n\n"
            md_content += "| Service | Detail | Amount |\n"
            md_content += "|---------|--------|--------|\n"
            
            for item in fields.bill_items.value_array:
                value_object = item.get("valueObject", {})
                
                # Extract values
                service_text = value_object.get("ItemService", {}).get("valueString", "")
                detail_text = value_object.get("ItemDetail", {}).get("valueString", "")
                amount_text = value_object.get("ItemAmount", {}).get("valueString", "")
                
                # Add to markdown
                md_content += f"| {service_text} | {detail_text} | {amount_text} |\n"
                
                # Create BillItem object
                bill_item = BillItem(
                    service=service_text,
                    detail=detail_text,
                    amount=amount_text
                )
                bill_items.append(bill_item)
        
        # Return the extracted data and receipt information
        return ReceiptExtractionResult(
            success=True,
            file_name=file.name,
            file_path=file_path,
            receipt_number=receipt_number,
            receipt_date=receipt_date_str,
            admission_date=admission_date_str,
            discharge_date=discharge_date_str,
            hospital=hospital,
            currency=currency_obj,
            amount=bill_amount,
            md_content=md_content,
            extracted_data=extracted_data,
            bill_items=bill_items
        )
    except Exception as e:
        return ReceiptExtractionResult(
            success=False,
            file_name=file.name,
            error=str(e)
        )

async def process_receipts(files: List[cl.File]) -> tuple[str,tuple[List[ClaimReceipt],List[ReceiptExtractionResult]]]:
    """
    Process multiple receipt files in parallel.
    
    Args:
        files: List of uploaded files
        
    Returns:
        tuple[str, tuple[List[ClaimReceipt], List[ReceiptExtractionResult]]]: A tuple containing the summary markdown, tuple of claim receipts and receipt extraction results
    """
    # Create a processing message
    processing_msg = await cl.Message(
        content=f"Processing {len(files)} receipt(s)...",
        author="System"
    ).send()
    
    # Create and start tasks for truly parallel processing
    tasks = []
    for file in files:
        task = asyncio.create_task(extract_receipt(file))
        tasks.append(task)
    
    # Wait for all tasks to complete
    results = await asyncio.gather(*tasks)
    
    # Update processing message
    processing_msg.content = f"Finished processing {len(files)} receipt(s)"
    await processing_msg.update()
    
    # Process the results
    successful_receipts = 0
    failed_receipts = 0
    receipt_elements = []
    claim_receipts = []
    
    
    for result in results:
        if result.success and result.currency is not None:
            # Create a ClaimDocument for the receipt
            document_id = f"receipt_{successful_receipts + 1}"
            receipt_document = ClaimDocument(
                type="RECEIPT",
                id=document_id
            )
            
            # Create a ClaimReceipt object
            receipt = ClaimReceipt(
                number=result.receipt_number or document_id,
                receiptDate=parse_date(result.receipt_date) if result.receipt_date else date.today(),
                admissionDate=parse_date(result.admission_date) if result.admission_date else None,
                dischargeDate=parse_date(result.discharge_date) if result.discharge_date else None,
                hospitalName=result.hospital or "Unknown Hospital",
                currency=result.currency,
                amount=result.amount or 0.0,
                documents=[receipt_document]
            )
            claim_receipts.append(receipt)
            
            receipt_elements.append(
                cl.Text(
                    name=f"Receipt {successful_receipts + 1}",
                    content=result.md_content,
                    display="inline"
                )
            )
            successful_receipts += 1
        else:
            error_message = result.error if result.error else "Failed to extract receipt data"
            if result.currency is None:
                error_message = "Failed to extract currency information from receipt"
                
            receipt_elements.append(
                cl.Text(
                    name=f"receipt_error_{failed_receipts + 1}",
                    content=f"⚠️ Error processing receipt '{result.file_name}': {error_message}",
                    display="inline"
                )
            )
            failed_receipts += 1
    
    claim.details.finalAmount = sum(receipt.amount for receipt in claim_receipts)
    # Display all receipt information in a single message with elements
    if receipt_elements:
        await cl.Message(
            content="## Extracted Receipt Information",
            author="System",
            elements=receipt_elements
        ).send()
    
    # Show summary
    summary = f"## Receipt Processing Summary\n\n"
    summary += f"Successfully processed: {successful_receipts} receipt(s)\n"
    if failed_receipts > 0:
        summary += f"- Failed to process: {failed_receipts} receipt(s)\n"
    
    summary += f"\nTotal claim amount so far: {claim.details.finalAmount} {claim.payout.currency.code}"
    
    results_tuple = (claim_receipts, results)
    # Return the summary markdown and the list of claim receipts
    return summary, results_tuple

async def handle_receipt(file: cl.File):
    """Store receipt file information without extraction."""
    global claim
    
    try:
        # Create a simple receipt document
        document_id = f"receipt_{len(claim.receipts) + 1}"
        receipt_document = ClaimDocument(
            type="RECEIPT",
            id=document_id
        )
        
        # Create a basic receipt with minimal information
        receipt = ClaimReceipt(
            number=document_id,  # Use document ID as a placeholder
            receiptDate=date.today(),
            admissionDate=date.today(),
            dischargeDate=date.today(),
            hospitalName="",  # Will be filled in later
            currency=Currency(code="SGD", name="Singapore Dollar", symbol="$"),  # Default currency
            amount=0.0,  # Will be filled in later
            documents=[receipt_document]
        )
        
        # Add the receipt to the claim
        claim.receipts.append(receipt)
        
        # Confirm receipt was added
        await cl.Message(
            content=f"Receipt '{file.name}' has been added to your claim. You can provide details later.",
            author="System"
        ).send()
        
    except Exception as e:
        await cl.Message(
            content=f"Error adding receipt: {str(e)}",
            author="System"
        ).send()

@cl.on_chat_start
async def start():
    global client_profile, currency_response, claim
    
    # Get the authenticated user
    user = cl.user_session.get("user")
    client_id = user.metadata.get("client_id")
    
    # Initialize the claim with the client ID
    claim = initialize_claim(client_id)
    
    # Display welcome message
    await display_message(f"Welcome to PruClaim AI Assistant, {client_id}! Let's help you submit an insurance claim.")
    
    # Get client profile data
    client_profile = get_eligible_policies(client_id)
    
    # Get currencies
    currency_response = get_currencies()
    
    # Display client profile header
    await display_message(f"## Client Profile: {client_id}")
    
    # Display eligible policies information
    policies_info = format_policies_info(client_profile)
    await display_message(policies_info)
    
    # Display currency information
    currency_info = format_currencies_info(currency_response)
    # await display_message(currency_info)
    
    # Go directly to receipt upload request - only once
    files = None
    while files == None:
        files = await cl.AskFileMessage(
            content="Please upload a receipt as proof of claim. This will help us process your claim faster.", 
            accept=["image/jpeg", "image/png", "application/pdf"],
            max_size_mb=10,  # Add 10MB file size limit
            max_files=5
        ).send()

    # Process all receipts in parallel with extraction and get the results
    summary, receipts_tuple = await process_receipts(files)
    receipts = receipts_tuple[0]
    claim_extractions = receipts_tuple[1]
    
    # Update the claim with the processed receipts
    claim.receipts.extend(receipts)
    
    # Update claim details with hospital name if available
    if receipts and receipts[0].hospitalName:
        claim.details.hospitalName = receipts[0].hospitalName
    
    # Update claim details with final amount
    claim.details.finalAmount = sum(receipt.amount for receipt in receipts)
    
    # Display the summary
    await cl.Message(content=summary, author="System").send()

    # Show processing message
    processing_msg = await cl.Message(
        content="Analyzing your receipts and determining the appropriate claim type...",
        author="System"
    ).send()
    
    # try:
    # Create a message for the assistant with all the data
    # Convert Pydantic models to dict
    policies_data = [policy.model_dump() for policy in client_profile.policies]
    currencies_data = currency_response.model_dump()
    
    # Handle date serialization in receipts
    receipts_data = []
    for receipt in claim.receipts:
        receipt_dict = receipt.model_dump()
        # Convert date objects to strings to avoid JSON serialization issues
        if isinstance(receipt_dict.get('receiptDate'), date):
            receipt_dict['receiptDate'] = receipt_dict['receiptDate'].isoformat()
        if isinstance(receipt_dict.get('admissionDate'), date):
            receipt_dict['admissionDate'] = receipt_dict['admissionDate'].isoformat()
        if isinstance(receipt_dict.get('dischargeDate'), date):
            receipt_dict['dischargeDate'] = receipt_dict['dischargeDate'].isoformat()
        receipts_data.append(receipt_dict)
    
    claim_extractions_data = []
    for claim_extraction in claim_extractions:
        markdown = claim_extraction.md_content
        claim_extractions_data.append(markdown)
        

    
    user_message = f"""
I need you to analyze this insurance claim data, determine the appropriate claim type, and fill the schema.

## Client Profile:
```json
{json.dumps(policies_data, indent=2)}
```

## Available Currencies:
```json
{json.dumps(currencies_data, indent=2)}
```

## Receipt Processing Summary:
Total claim amount: {claim.details.finalAmount} {claim.payout.currency.code}

## Receipts filled in Claim:
```json
{json.dumps(receipts_data, indent=2)}
```

## Receipt Extractions:
```json
{json.dumps(claim_extractions_data, indent=2)}
```

Please follow these steps:
1. Analyze the receipt data to determine the most appropriate claim type
4. Fill in the schema with information from the receipts, client profile, and payout methods
5. Return the filled schema in your response

Include your reasoning for the claim type determination and payout method selection in your message.
Comment any discrepancies between the Receipt Extractions & Client Profile Especially the name on the extraction vs logged in user. The name is important, call it out.
Provide a brief analysis what what were the info that was not captured in the filled schema, meaning Delta between Receipts filled in Claim and Receipt Extractions.

"""
    print(user_message)

    
    
    # Run the conversation with the assistant
    thread_id, assistant_response, structured_data = await run_conversation(
        assistant_id=ASSISTANT_ID,
        user_input=user_message
    )
    # await cl.Message(content=f"Assistant: {assistant_response}", author="Assistant").send()
                
    # await cl.Message(content=f"Structured Data: {structured_data}", author="Assistant").send()

        
    # except Exception as e:
    #     # Handle any errors
    #     await cl.Message(content=f"Error determining claim type: {str(e)}").send()

    # Format and display the structured data
    formatted_message = format_message(structured_data)
    await cl.Message(content=formatted_message, author="Assistant").send()

    # get 


@cl.on_message
async def on_message(message: cl.Message):
    # Echo the message back to the user
    response = f"You said: {message.content}"
    await display_message(response)

def format_message(structured_data: ClaimResponse) -> str:
    """
    Format the structured data from the assistant into a readable message.
    
    Args:
        structured_data: The ClaimResponse object from the assistant
        
    Returns:
        str: A formatted message for display
    """
    if not structured_data:
        return "Error: Could not parse structured data from assistant response"
    
    # Extract data from the ClaimResponse
    claim_data = structured_data.claim_data
    status = structured_data.status
    message = structured_data.message
    
    # Format the claim type information
    claim_type_str = claim_data.get("claim_type", "Unknown")
    
    # Format the payout information
    payout = claim_data.get("payout", {})
    payout_mode = payout.get("mode", "Unknown")
    payout_currency = payout.get("currency", {}).get("code", "Unknown")
    
    # Format the account information if available
    account_info = ""
    if account := payout.get("account"):
        account_name = account.get("name", "Unknown")
        account_no = account.get("account_no", "Unknown")
        account_info = f"{account_name} ({account_no})"
    
    # Format the receipt information
    receipts = claim_data.get("receipts", [])
    receipt_count = len(receipts)
    total_amount = claim_data.get("details", {}).get("finalAmount", 0)
    currency_code = receipts[0].get("currency", {}).get("code", "Unknown") if receipts else "Unknown"
    
    # Build the formatted message with tables
    formatted_message = f"""## Claim Analysis

| Category | Details |
|----------|---------|
| **Claim Type** | {claim_type_str} |
| **Status** | {status} |
| **Total Amount** | {total_amount} {currency_code} |
| **Receipt Count** | {receipt_count} |

| Payout Information | Details |
|-------------------|---------|
| **Method** | {payout_mode} |
| **Currency** | {payout_currency} |
| **Account** | {account_info} |

### Analysis
{message}

### Claim Schema
```json
{json.dumps(claim_data, indent=2)}
```
"""
    
    return formatted_message

def parse_date(date_str: str) -> date:
    """Parse a date string into a date object"""
    if not date_str or date_str.strip() == '':
        return None
    
    # Try different date formats
    formats = [
        "%d/%m/%Y",       # 31/01/2023, 14/06/2024
        "%Y-%m-%d",       # 2023-01-31
        "%d-%m-%Y",       # 31-01-2023
        "%d %b %Y",       # 31 Jan 2023
        "%d %B %Y",       # 31 January 2023
        "%b %d, %Y",      # Jan 31, 2023
        "%B %d, %Y",      # January 31, 2023
        "%m/%d/%Y",       # 01/31/2023
        "%Y/%m/%d"        # 2023/01/31
    ]
    
    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt).date()
        except ValueError:
            continue
    
    # If all parsing attempts fail, log the issue and return today's date
    print(f"Warning: Could not parse date string '{date_str}', using today's date instead")
    return date.today()
