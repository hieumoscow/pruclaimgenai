import streamlit as st
import os
import json
import asyncio
import concurrent.futures
from typing import Optional, List, Dict, Any
from datetime import datetime, date
from dotenv import load_dotenv, find_dotenv

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

# Initialize session state variables if they don't exist
if 'client_profile' not in st.session_state:
    st.session_state.client_profile = None
if 'currency_response' not in st.session_state:
    st.session_state.currency_response = None
if 'claim' not in st.session_state:
    st.session_state.claim = None
if 'thread_id' not in st.session_state:
    st.session_state.thread_id = None
if 'receipts_processed' not in st.session_state:
    st.session_state.receipts_processed = False
if 'assistant_response' not in st.session_state:
    st.session_state.assistant_response = None
if 'structured_data' not in st.session_state:
    st.session_state.structured_data = None
if 'receipt_results' not in st.session_state:
    st.session_state.receipt_results = []
if 'claim_receipts' not in st.session_state:
    st.session_state.claim_receipts = []


def display_message(content: str, author: str = "System"):
    """Display a message in the Streamlit app"""
    if author == "System":
        st.info(content)
    elif author == "Assistant":
        st.success(content)
    else:
        st.write(content)


def format_policies_info(policies_rs: EligiblePoliciesResponse) -> str:
    """Format eligible policies information into a markdown table"""
    policies_info = "### Eligible Policies\n\n"
    policies = policies_rs.policies
    
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


def format_currencies_info(currency_response: CurrencyResponse) -> str:
    """Format available currencies information into a markdown table"""
    if not currency_response or not currency_response.currencies:
        return "No currencies available."
    
    # Create a markdown table
    md_table = "### Available Currencies\n\n"
    md_table += "| Code | Name | Symbol |\n"
    md_table += "|------|------|--------|\n"
    
    # Add each currency to the table
    for currency in currency_response.currencies:
        md_table += f"| {currency.code} | {currency.name} | {currency.symbol} |\n"
    
    return md_table


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


def extract_receipt(file_path: str, file_name: str) -> ReceiptExtractionResult:
    """
    Extract information from a receipt file using Azure Document Intelligence.
    
    Args:
        file_path: The path to the uploaded file
        file_name: The name of the uploaded file
        
    Returns:
        ReceiptExtractionResult: The extracted receipt information
    """
    try:
        # Analyze the document
        extracted_data = analyze_document(file_path)
        
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
            file_name=file_name,
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
            file_name=file_name,
            error=str(e)
        )


def process_receipts(uploaded_files):
    """
    Process multiple receipt files in parallel.
    
    Args:
        uploaded_files: List of uploaded files from Streamlit
        
    Returns:
        tuple[str, List[ClaimReceipt], List[ReceiptExtractionResult]]: A tuple containing the summary markdown, list of claim receipts and list of receipt extraction results
    """
    # Show processing message
    st.info(f"Processing {len(uploaded_files)} receipt(s)...")
    progress_bar = st.progress(0)
    
    # Process files
    results = []
    for i, file in enumerate(uploaded_files):
        # Save the file to a temporary location
        file_path = f"/tmp/{file.name}"
        with open(file_path, "wb") as f:
            f.write(file.getbuffer())
        
        # Extract receipt information
        result = extract_receipt(file_path, file.name)
        results.append(result)
        
        # Update progress
        progress_bar.progress((i + 1) / len(uploaded_files))
    
    # Process the results
    successful_receipts = 0
    failed_receipts = 0
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
            
            # Display receipt information
            with st.expander(f"Receipt {successful_receipts + 1}"):
                st.markdown(result.md_content, unsafe_allow_html=True)
            
            successful_receipts += 1
        else:
            error_message = result.error if result.error else "Failed to extract receipt data"
            if result.currency is None:
                error_message = "Failed to extract currency information from receipt"
                
            # Display error
            with st.expander(f"Error processing receipt {failed_receipts + 1}"):
                st.error(f"⚠️ Error processing receipt '{result.file_name}': {error_message}")
            
            failed_receipts += 1
    
    # Update claim details with final amount
    if st.session_state.claim:
        st.session_state.claim.details.finalAmount = sum(receipt.amount for receipt in claim_receipts)
    
    # Show summary
    summary = f"## Receipt Processing Summary\n\n"
    summary += f"Successfully processed: {successful_receipts} receipt(s)\n"
    if failed_receipts > 0:
        summary += f"- Failed to process: {failed_receipts} receipt(s)\n"
    
    if st.session_state.claim:
        summary += f"\nTotal claim amount so far: {st.session_state.claim.details.finalAmount} {st.session_state.claim.payout.currency.code}"
    
    # Return the summary markdown and the list of claim receipts
    return summary, claim_receipts, results


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


def parse_date(date_str: str) -> Optional[date]:
    """Parse a date string into a date object"""
    if not date_str:
        return None
    
    # Try different date formats
    date_formats = [
        "%d/%m/%Y",  # 31/12/2023
        "%d-%m-%Y",  # 31-12-2023
        "%Y-%m-%d",  # 2023-12-31
        "%Y/%m/%d",  # 2023/12/31
        "%d %b %Y",  # 31 Dec 2023
        "%d %B %Y",  # 31 December 2023
        "%b %d, %Y", # Dec 31, 2023
        "%B %d, %Y"  # December 31, 2023
    ]
    
    # Clean the date string
    date_str = date_str.strip()
    
    # Try each format
    for fmt in date_formats:
        try:
            return datetime.strptime(date_str, fmt).date()
        except ValueError:
            continue
    
    # If all formats fail, return None
    return None


async def run_assistant(user_message):
    """Run the conversation with the assistant"""
    with st.spinner("Analyzing your claim data..."):
        thread_id, assistant_response, structured_data = await run_conversation(
            assistant_id=ASSISTANT_ID,
            user_input=user_message
        )
        
        st.session_state.thread_id = thread_id
        st.session_state.assistant_response = assistant_response
        st.session_state.structured_data = structured_data
        
        return structured_data


def main():
    st.set_page_config(
        page_title="PruClaim AI Assistant",
        page_icon="🏥",
        layout="wide"
    )
    
    st.title("PruClaim AI Assistant")
    
    # Sidebar for authentication
    with st.sidebar:
        st.header("Authentication")
        client_id = st.text_input("Client ID", value="C111")
        if st.button("Login"):
            # Initialize the claim with the client ID
            st.session_state.claim = initialize_claim(client_id)
            
            # Get client profile data
            st.session_state.client_profile = get_eligible_policies(client_id)
            
            # Get currencies
            st.session_state.currency_response = get_currencies()
            
            st.success(f"Logged in as {client_id}")
    
    # Main content area
    if st.session_state.claim:
        # Display client profile
        st.header(f"Client Profile: {st.session_state.claim.clientId}")
        
        # Display eligible policies
        if st.session_state.client_profile:
            st.markdown(format_policies_info(st.session_state.client_profile))
        
        # File upload section
        if not st.session_state.receipts_processed:
            st.header("Upload Receipts")
            st.write("Please upload a receipt as proof of claim. This will help us process your claim faster.")
            
            uploaded_files = st.file_uploader(
                "Upload receipts",
                accept_multiple_files=True,
                type=["jpg", "jpeg", "png", "pdf"]
            )
            
            if uploaded_files and st.button("Process Receipts"):
                # Process receipts
                summary, claim_receipts, receipt_results = process_receipts(uploaded_files)
                
                # Update session state
                st.session_state.claim_receipts = claim_receipts
                st.session_state.receipt_results = receipt_results
                st.session_state.receipts_processed = True
                
                # Update claim with receipts
                st.session_state.claim.receipts.extend(claim_receipts)
                
                # Update claim details with hospital name if available
                if claim_receipts and claim_receipts[0].hospitalName:
                    st.session_state.claim.details.hospitalName = claim_receipts[0].hospitalName
                
                # Display summary
                st.markdown(summary)
                
                # Analyze button
                st.button("Analyze Claim", on_click=lambda: st.session_state.update({"analyze_clicked": True}))
        
        # Analyze claim if receipts are processed and analyze button is clicked
        if st.session_state.receipts_processed and st.session_state.get("analyze_clicked", False):            
            # Create a message for the assistant with all the data
            # Convert Pydantic models to dict
            policies_data = [policy.model_dump() for policy in st.session_state.client_profile.policies]
            currencies_data = st.session_state.currency_response.model_dump()
            
            # Handle date serialization in receipts
            receipts_data = []
            for receipt in st.session_state.claim.receipts:
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
            for claim_extraction in st.session_state.receipt_results:
                if claim_extraction.md_content:
                    claim_extractions_data.append(claim_extraction.md_content)
            
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
Total claim amount: {st.session_state.claim.details.finalAmount} {st.session_state.claim.payout.currency.code}

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
            
            # Run the assistant
            asyncio.run(run_assistant(user_message))
            
            # Display the formatted message
            if st.session_state.structured_data:
                formatted_message = format_message(st.session_state.structured_data)
                st.markdown(formatted_message)
                
            # Keep receipt extractions visible
            st.header("Receipt Extractions")
            for i, result in enumerate(st.session_state.receipt_results):
                with st.expander(f"Receipt {i + 1}"):
                    st.markdown(result.md_content, unsafe_allow_html=True)
    else:
        st.info("Please log in using the sidebar to start.")


if __name__ == "__main__":
    main()
