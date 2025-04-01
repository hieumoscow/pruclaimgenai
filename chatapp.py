from cProfile import label
import os
import tempfile
import asyncio
import chainlit as cl
from chainlit.action import Action
from dotenv import load_dotenv, find_dotenv
from typing import Dict, Any, List, Optional
import json

# Import functions from the existing codebase
from functions import (
    get_eligible_policies,
    analyze_document,
    submit_claim,
    get_required_documents
)
import aoai_assistant_run
from aoai_assistant_run import ASSISTANT_ID, create_thread

# Load environment variables
load_dotenv(find_dotenv(), override=True)

# Global variables to store state
thread_id = None
claim_data = {
    "clientId": "",
    "lifeAssuredId": "",
    "claimType": "",
    "policyId": "",
    "policyName": "",
    "details": {},
    "receipts": [],
    "documents": [],
    "payout": {}
}

# Helper function to map MIME types to file extensions
def map_mime_types_to_extensions(mime_types):
    mime_to_ext = {
        "image/jpeg": "jpg",
        "image/jpg": "jpg",
        "image/png": "png",
        "application/pdf": "pdf",
        "image/tiff": "tiff",
        "image/bmp": "bmp",
        "image/gif": "gif"
    }
    
    extensions = []
    for mime in mime_types:
        if mime in mime_to_ext:
            extensions.append(mime_to_ext[mime])
    
    # If no valid extensions found, return common defaults
    if not extensions:
        return ["jpg", "jpeg", "png", "pdf"]
    
    return extensions

# Load client IDs from the client profile data
def load_client_ids():
    try:
        with open('responses/clientprofile.json', 'r') as f:
            client_profile = json.load(f)
        
        # Extract unique client IDs
        client_ids = set()
        for policy in client_profile:
            client_ids.add(policy["policy"]["owner"]["id"])
        
        return sorted(list(client_ids))
    except Exception as e:
        print(f"Error loading client IDs: {e}")
        return ["C111", "C222", "C333"]  # Fallback default values

# Configure authentication
@cl.password_auth_callback
def auth_callback(username: str, password: str) -> Optional[cl.User]:
    # Load valid client IDs
    client_ids = load_client_ids()
    
    # Check if username is a valid client ID
    if username in client_ids:
        # In a real app, you'd check the password against a database
        # For this demo, we'll accept any password
        return cl.User(
            identifier=username,
            metadata={
                "client_id": username,
                "role": "client"
            }
        )
    return None

@cl.on_chat_start
async def start():
    global thread_id, claim_data
    
    # Reset thread_id
    thread_id = None
    
    # Get the authenticated user
    user = cl.user_session.get("user")
    client_id = user.metadata.get("client_id")
    
    # Update claim data with client ID
    claim_data["clientId"] = client_id
    
    # Welcome message
    await cl.Message(
        content=f"Welcome to PruClaim AI Assistant, {client_id}! Let's help you submit an insurance claim.",
        author="System"
    ).send()
    
    # Get client profile data - this returns a dictionary with 'eligible' and 'policies' keys
    client_profile = get_eligible_policies(client_id)
    
    # Display client profile information
    profile_info = f"## Client Profile: {client_id}\n\n"
    profile_info += "### Eligible Policies\n\n"
    
    if len(client_profile.policies) > 0:
        profile_info += "| Policy ID | Policy Name | Status | Lives Assured | Claim Types |\n"
        profile_info += "|-----------|-------------|--------|--------------|-------------|\n"
        
        for policy in client_profile.policies:
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
            
            profile_info += f"| {policy_id} | {policy_name} | {status} | {lives_assured_str} | {claim_types} |\n"
    else:
        profile_info += "No eligible policies found for this client.\n"
    
    await cl.Message(
        content=profile_info,
        author="System"
    ).send()
    
    # Show policy selection buttons
    await generate_policy_selection_buttons(client_id)
    

async def generate_policy_selection_buttons(client_id):
    """Generate policy selection buttons with status indicators."""
    # Get eligible policies
    policies = get_eligible_policies(client_id)
    
    # Create action buttons for each policy
    actions = []
    for policy in [p for p in policies.policies if p.policy.status.is_active]:
        # Create button with status indicator
        actions.append(
            Action(
                label=f"{policy.policy.name} ({policy.policy.id}) - {', '.join([life.name for life in policy.policy.lives_assured])}",
                name=f"select_policy",
                description=f"Select {policy.policy.name} - {', '.join(policy.claim_types)}",
                payload={
                    "client_id": client_id,
                    "lives_assured": [life.name for life in policy.policy.lives_assured],
                    "policy_id": policy.policy.id,
                    "policy_name": policy.policy.name,
                    "status": policy.policy.status.is_active
                }
            )
        )
    
    # Send message with policy selection buttons
    if actions:
        await cl.Message(
            content="Please select a policy to continue:",
            author="System",
            actions=actions
        ).send()
    else:
        await cl.Message(
            content="No eligible policies found for your account.",
            author="System"
        ).send()

@cl.action_callback("upload_receipt")
async def on_upload_receipt(action):
    """Handle receipt upload action."""
    # Show a file upload message
    await cl.Message(
        content="Please upload your receipt document. We support JPG, PNG, and PDF files.",
        author="System",
        elements=[
            cl.File(
                name="receipt_upload",
                accept=["image/jpeg", "image/png", "application/pdf"],
                max_files=1
            )
        ]
    ).send()

async def extract_receipt(file: cl.File):
    """Extract information from a receipt document."""
    global thread_id
    
    try:
        # Create an animated loading message
        animation_task = await send_animated_message(
            base_msg=f"Processing receipt: {file.name}",
            frames=["🌑", "🌒", "🌓", "🌔", "🌕", "🌖", "🌗", "🌘"],
            interval=0.3  # Faster animation
        )
        
        # animation_task.start()
        
        try:
            # Use the file path directly from the File object
            file_path = file.path
            
            # Analyze the document
            extracted_data = analyze_document(file_path)
            
            # Cancel the animation task
            animation_task.cancel()
            
            # Send a completion message
            await cl.Message(
                content=f"Receipt processed successfully: {file.name}",
                author="System"
            ).send()
            
            if extracted_data:
                # Get the fields from the correct path in the extracted data
                fields = {}
                if "result" in extracted_data and "contents" in extracted_data["result"]:
                    if extracted_data["result"]["contents"] and len(extracted_data["result"]["contents"]) > 0:
                        fields = extracted_data["result"]["contents"][0].get("fields", {})
                
                # Create a simplified view of the extracted data
                simplified_data = {
                    "Receipt Number": fields.get("ReceiptNumber", {}).get("valueString", ""),
                    "Receipt Date": fields.get("ReceiptDate", {}).get("valueString", ""),
                    "Admission Date": fields.get("AdmissionDate", {}).get("valueString", ""),
                    "Discharge Date": fields.get("DischargeDate", {}).get("valueString", ""),
                    "Hospital": fields.get("Hospital", {}).get("valueString", ""),
                    "Currency": fields.get("Currency", {}).get("valueString", "SGD"),
                    "Bill Amount": fields.get("BillAmount", {}).get("valueString", "0"),
                    "GST": fields.get("GST", {}).get("valueString", "")
                }
                
                # Format the extracted data as a markdown table
                md_content = f"## Extracted Receipt Information\n\n"
                md_content += "| Field | Value | Confidence |\n"
                md_content += "|-------|-------|------------|\n"
                
                for key, value in simplified_data.items():
                    field_key = key.replace(" ", "")  # Convert to format matching the API response
                    confidence = fields.get(field_key, {}).get("confidence", 0) if field_key in fields else 0
                    confidence_str = f"{confidence:.2f}" if confidence else "N/A"
                    md_content += f"| {key} | {value} | {confidence_str} |\n"
                
                # Check for bill items
                bill_items = fields.get("BillItems", {}).get("valueArray", [])
                if bill_items:
                    md_content += "\n### Bill Items\n\n"
                    md_content += "| Service | Detail | Amount |\n"
                    md_content += "|---------|--------|--------|\n"
                    
                    for item in bill_items:
                        value_object = item.get("valueObject", {})
                        
                        # Extract values
                        service_text = value_object.get("ItemService", {}).get("valueString", "")
                        detail_text = value_object.get("ItemDetail", {}).get("valueString", "")
                        amount_text = value_object.get("ItemAmount", {}).get("valueString", "")
                        
                        md_content += f"| {service_text} | {detail_text} | {amount_text} |\n"
                
                # Send a new message with the extracted information
                await cl.Message(
                    content=md_content,
                    author="System"
                ).send()
                
                # Create a receipt object with the extracted data
                receipt = {
                    "number": simplified_data["Receipt Number"],
                    "receiptDate": simplified_data["Receipt Date"],
                    "admissionDate": simplified_data["Admission Date"] or simplified_data["Receipt Date"],
                    "dischargeDate": simplified_data["Discharge Date"] or simplified_data["Receipt Date"],
                    "hospitalName": simplified_data["Hospital"],
                    "currency": {
                        "code": simplified_data["Currency"],
                        "name": "Singapore Dollar",
                        "symbol": "$"
                    },
                    "amount": float(simplified_data["Bill Amount"].replace(",", "") if simplified_data["Bill Amount"] else 0),
                    "documents": [
                        {
                            "type": "RECEIPT",
                            "id": file.name
                        }
                    ]
                }
                
                # Update claim data with receipt information
                if "receipts" not in claim_data:
                    claim_data["receipts"] = []
                
                # Check if receipt already exists
                receipt_exists = False
                for i, existing_receipt in enumerate(claim_data.get("receipts", [])):
                    if existing_receipt.get("number") == receipt["number"]:
                        # Update existing receipt
                        claim_data["receipts"][i] = receipt
                        receipt_exists = True
                        break
                
                # Add new receipt if it doesn't exist
                if not receipt_exists:
                    claim_data["receipts"].append(receipt)
                
                # Also update the details section with hospital name
                if "details" not in claim_data:
                    claim_data["details"] = {}
                
                claim_data["details"]["hospitalName"] = receipt["hospitalName"]
                
                # Add document to documents array
                if "documents" not in claim_data:
                    claim_data["documents"] = []
                
                # Check if document already exists in claim data
                doc_exists = False
                for i, existing_doc in enumerate(claim_data.get("documents", [])):
                    if existing_doc.get("type") == "RECEIPT":
                        # Update existing document
                        claim_data["documents"][i] = {
                            "type": "RECEIPT",
                            "id": file.name
                        }
                        doc_exists = True
                        break
                
                # Add new document if it doesn't exist
                if not doc_exists:
                    claim_data["documents"].append({
                        "type": "RECEIPT",
                        "id": file.name
                    })
                
                # Display claim data in a formatted way
                claim_data_md = f"## Current Claim Data\n\n"
                
                # Basic claim information
                claim_data_md += "### Basic Information\n\n"
                claim_data_md += f"- **Client ID**: {claim_data.get('clientId', 'Not set')}\n"
                claim_data_md += f"- **Policy ID**: {claim_data.get('policyId', 'Not set')}\n"
                claim_data_md += f"- **Policy Name**: {claim_data.get('policyName', 'Not set')}\n"
                claim_data_md += f"- **Life Assured ID**: {claim_data.get('lifeAssuredId', 'Not set')}\n"
                claim_data_md += f"- **Life Assured Name**: {claim_data.get('lifeAssuredName', 'Not set')}\n"
                
                # Receipt information
                if claim_data.get('receipts'):
                    claim_data_md += "\n### Receipts\n\n"
                    for i, receipt in enumerate(claim_data['receipts']):
                        claim_data_md += f"**Receipt {i+1}**:\n"
                        claim_data_md += f"- Number: {receipt.get('number', 'Not available')}\n"
                        claim_data_md += f"- Date: {receipt.get('receiptDate', 'Not available')}\n"
                        claim_data_md += f"- Hospital: {receipt.get('hospitalName', 'Not available')}\n"
                        claim_data_md += f"- Amount: {receipt.get('amount', '0')} {receipt.get('currency', {}).get('code', 'SGD')}\n"
                
                # Documents information
                if claim_data.get('documents'):
                    claim_data_md += "\n### Documents\n\n"
                    for i, doc in enumerate(claim_data['documents']):
                        claim_data_md += f"- {doc.get('type', 'Unknown')}: {doc.get('id', 'No ID')}\n"
                
                # Send claim data summary
                await cl.Message(
                    content=claim_data_md,
                    author="System"
                ).send()
                
                # Initialize the assistant if not already initialized
                if not thread_id:
                    thread_id = await initialize_assistant()
                
                # Pass the claim data to the assistant and ask for required documents
                assistant_response = await send_to_assistant(
                    f"I've selected policy {claim_data.get('policyName')} and uploaded a receipt for {claim_data.get('details', {}).get('hospitalName', 'hospital care')}. Please tell me what documents I need to upload to complete my claim submission.",
                    claim_data=claim_data
                )
                
                # Send the assistant's response to the user
                await cl.Message(
                    content=assistant_response,
                    author="Assistant"
                ).send()
                
                # Instead of immediately showing the confirm submission button,
                # we'll let the assistant guide the user through document uploads
            else:
                # Send a message if no data was extracted
                await cl.Message(
                    content=f"No data could be extracted from the receipt: {file.name}",
                    author="System"
                ).send()
        except Exception as e:
            # Send an error message for inner try block
            await cl.Message(
                content=f"Error processing receipt data: {str(e)}",
                author="System"
            ).send()
    except Exception as e:
        # Send an error message for outer try block
        await cl.Message(
            content=f"Error processing receipt: {str(e)}",
            author="System"
        ).send()

@cl.on_message
async def on_message(message: cl.Message):
    global thread_id, claim_data
    
    # Get client ID from user session
    user = cl.user_session.get("user")
    client_id = user.metadata.get("client_id")
    

    
    # Initialize the assistant if not already initialized
    if not thread_id:
        thread_id = await initialize_assistant()
    
    # Extract policy ID if mentioned
    if "policy" in message.content.lower():
        policies = get_eligible_policies(client_id)
        for policy in policies.policies:
            if policy.policy.id in message.content:
                claim_data["policyId"] = policy.policy.id
                claim_data["policyName"] = policy.policy.name
                break
    
    # Send the message to the assistant
    await send_to_assistant(message.content)

@cl.action_callback("select_policy")
async def on_select_policy(action):
    """Handle policy selection."""
    global claim_data
    
    # Extract policy ID from action value
    policy_id = action.payload["policy_id"]
    policy_name = action.payload["policy_name"]
    lives_assured = action.payload["lives_assured"]
    
    # Get client ID from user session
    user = cl.user_session.get("user")
    client_id = user.metadata.get("client_id")
    
    # Get eligible policies
    policies = get_eligible_policies(client_id)
    
    # Find the selected policy
    selected_policy = None
    for policy in policies.policies:
        if policy.policy.id == policy_id:
            selected_policy = policy
            break
    
    if selected_policy:
        # Update claim data with policy information
        claim_data["policyId"] = policy_id
        claim_data["policyName"] = policy_name
        
        # Send confirmation message
        await cl.Message(
            content=f"You've selected policy: {policy_name} ({policy_id})\nLives assured: {', '.join(lives_assured)}",
            author="System"
        ).send()
        
        # Check if policy is active
        if not selected_policy.policy.status.is_active:
            await cl.Message(
                content="⚠️ Note: The selected policy is inactive. Claims for inactive policies may not be processed.",
                author="System"
            ).send()
        
        # If there are multiple lives assured, show selection buttons
        if len(selected_policy.policy.lives_assured) > 1:
            # Create action buttons for each life assured
            actions = []
            for life in selected_policy.policy.lives_assured:
                actions.append(
                    Action(
                        name=f"{life.name} ({life.id})",
                        value=f"select_life_{life.id}",
                        description=f"Select {life.name} as life assured",
                        payload={
                            "life_id": life.id,
                            "life_name": life.name
                        }
                    )
                )
            
            # Send message with life assured selection buttons
            await cl.Message(
                content="Please select a life assured to continue:",
                author="System",
                actions=actions
            ).send()
        elif len(selected_policy.policy.lives_assured) == 1:
            # Automatically select the only life assured
            life = selected_policy.policy.lives_assured[0]
            claim_data["lifeAssuredId"] = life.id
            claim_data["lifeAssuredName"] = life.name
            
            # await cl.Message(
            #     content=f"Life assured automatically selected: {life.name} ({life.id})",
            #     author="System"
            # ).send()
            
            files = None
            # Proceed to receipt upload
            while files == None:
                files = await cl.AskFileMessage(
                    content="Please upload a receipt as proof of claim. This will help us process your claim faster.", accept=["image/jpeg", "image/png", "application/pdf"]
                ).send()

            receipt_file = files[0]
            # Analyze the receipt
            await extract_receipt(receipt_file)

        else:
            await cl.Message(
                content="No lives assured found for this policy. Please contact customer support.",
                author="System"
            ).send()
    else:
        await cl.Message(
            content=f"Policy with ID {policy_id} not found.",
            author="System"
        ).send()

@cl.action_callback("select_life_*")
async def on_select_life_assured(action):
    """Handle life assured selection."""
    global claim_data
    
    # Extract life assured ID from action value
    life_id = action.value.replace("select_life_", "")
    
    # Get client ID from user session
    user = cl.user_session.get("user")
    client_id = user.metadata.get("client_id")
    
    # Get eligible policies
    policies = get_eligible_policies(client_id)
    
    # Find the selected policy and life assured
    selected_life = None
    policy_id = claim_data.get("policyId")
    
    if policy_id:
        for policy in policies.policies:
            if policy.policy.id == policy_id:
                for life in policy.policy.lives_assured:
                    if life.id == life_id:
                        selected_life = life
                        break
                break
    
    if selected_life:
        # Update claim data with life assured information
        claim_data["lifeAssuredId"] = life_id
        claim_data["lifeAssuredName"] = selected_life.name
        
        # Send confirmation message
        await cl.Message(
            content=f"You've selected life assured: {selected_life.name} ({life_id})",
            author="System"
        ).send()
        
        # Prompt user to continue with claim submission
        await cl.Message(
            content="You can now continue with your claim submission. Please provide details about your claim.",
            author="System"
        ).send()
    else:
        await cl.Message(
            content=f"Life assured with ID {life_id} not found.",
            author="System"
        ).send()

async def initialize_assistant():
    """Initialize the AI assistant and create a new thread."""
    try:
        # Initialize the assistant
        thread_id = aoai_assistant_run.create_thread()
        return thread_id
    except Exception as e:
        # Send a new error message
        await cl.Message(
            content=f"❌ Error initializing AI assistant: {str(e)}",
            author="System"
        ).send()
        return None

async def send_to_assistant(message_content, claim_data=None):
    """Send a message to the AI assistant and handle the response."""
    global thread_id
    
    try:
        # Get the response from the assistant
        thread_id, assistant_response, structured_data = await aoai_assistant_run.run_conversation(
            assistant_id=aoai_assistant_run.ASSISTANT_ID,
            user_input=message_content,
            thread_id=thread_id,
            client_id=cl.user_session.get("user").metadata.get("client_id"),
            claim_data=claim_data
        )
        
        # Send the assistant's response to the user
        await cl.Message(content=assistant_response, author="Assistant").send()
        
        # Check if there's an action to perform
        if structured_data and structured_data.get("action") == "upload_document":
            # Create an action for document upload
            await cl.Message(
                content=f"I need you to upload a {structured_data.get('document_category', '').replace('_', ' ').title()} document.",
                author="Assistant",
                actions=[
                    Action(
                        name=f"Upload {structured_data.get('document_category', '').replace('_', ' ').title()}",
                        value="upload_document",
                        description=f"Upload a {structured_data.get('document_category', '').replace('_', ' ').title()} document",
                        payload={
                            "document_type": structured_data.get("document_type"),
                            "document_category": structured_data.get("document_category"),
                            "required": structured_data.get("required", False),
                            "file_types": structured_data.get("file_types", ["image/jpeg", "image/png", "application/pdf"]),
                            "max_size": structured_data.get("max_size", 10485760)
                        }
                    )
                ]
            ).send()
        
        return structured_data
    except Exception as e:
        # Send an error message
        error_message = f"Error communicating with the assistant: {str(e)}"
        await cl.Message(content=error_message, author="System").send()
        return {"message": error_message, "status": "ERROR"}

async def send_animated_message(
    base_msg: str,
    frames: List[str],
    interval: float = 0.8,
    duration: float = None
) -> asyncio.Task:
    """Displays an animated message optimized for performance.
    
    Args:
        base_msg: The base message text
        frames: Animation frames (emojis or symbols)
        interval: Time between animation frames
        duration: Optional duration to run animation (None for indefinite)
        
    Returns:
        tuple: (message, animation_task)
    """
    msg = cl.Message(content=base_msg, author="System")
    await msg.send()
    
    progress = 0
    bar_length = 12  # Optimal length for the progress bar
    
    async def animate():
        nonlocal progress
        try:
            while True:
                # Optimized progress calculation
                current_frame = frames[progress % len(frames)]
                progress_bar = "▣" * (progress % bar_length) + "▢" * (bar_length - (progress % bar_length))
                
                # Single update operation
                new_content = f"{current_frame} {base_msg}\n{progress_bar}"
                msg.content = new_content
                await msg.update()
                
                progress += 1
                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            # Final static display
            final_content = f"✅ {base_msg} - Complete"
            msg.content = final_content
            await msg.update()
            return
    
    # Start animation task
    animation_task = asyncio.create_task(animate())
    
    # If duration is provided, schedule cancellation
    if duration is not None:
        async def cancel_after_duration():
            await asyncio.sleep(duration)
            if not animation_task.done():
                animation_task.cancel()
                try:
                    await animation_task
                except asyncio.CancelledError:
                    pass
        
        asyncio.create_task(cancel_after_duration())
    
    return animation_task

@cl.action_callback("upload_document")
async def on_upload_document(action):
    """Handle document upload action."""
    document_type = action.payload.get("document_type")
    document_category = action.payload.get("document_category")
    required = action.payload.get("required", False)
    file_types = action.payload.get("file_types", ["image/jpeg", "image/png", "application/pdf"])
    max_size = action.payload.get("max_size", 10485760)  # Default to 10MB
    
    # Format file types for display
    file_types_display = ", ".join([ft.split("/")[1].upper() for ft in file_types])
    
    # Show a file upload message
    await cl.Message(
        content=f"Please upload your {document_category.replace('_', ' ').title()} document. We support {file_types_display} files.",
        author="System",
        elements=[
            cl.File(
                name=f"{document_type}_upload",
                accept=file_types,
                max_files=1,
                max_size_mb=max_size // (1024 * 1024)  # Convert bytes to MB
            )
        ]
    ).send()

@cl.on_message
async def on_message(message: cl.Message):
    global thread_id, claim_data
    
    # Get client ID from user session
    user = cl.user_session.get("user")
    client_id = user.metadata.get("client_id")
    
    # Check if there are files attached to the message
    if message.elements and len(message.elements) > 0 and isinstance(message.elements[0], cl.File):
        file = message.elements[0]
        file_name = file.name
        
        # Check if this is a receipt upload or a document upload
        if "receipt" in file_name.lower() or file.name.startswith("receipt"):
            # Process as receipt
            await extract_receipt(file)
        else:
            # Process as document
            await process_document(file)
        
        return
    
    # Initialize the assistant if not already initialized
    if not thread_id:
        thread_id = await initialize_assistant()
    
    # Send the message to the assistant
    await send_to_assistant(message.content)

async def process_document(file: cl.File):
    """Process an uploaded document and add it to claim data."""
    global claim_data
    
    # Create an animated loading message
    loading_msg, animation_task = await send_animated_message(
        base_msg=f"Processing document: {file.name}",
        frames=["🌑", "🌒", "🌓", "🌔", "🌕", "🌖", "🌗", "🌘"],
        interval=0.3  # Faster animation
    )
    
    try:
        # Use the file path directly from the File object
        file_path = file.path
        
        # Determine document type from filename or ask user
        document_type = "UNKNOWN"
        if "medical" in file.name.lower():
            document_type = "MEDICAL_REPORT"
        elif "specialist" in file.name.lower():
            document_type = "SPECIALIST_REPORT"
        elif "referral" in file.name.lower():
            document_type = "REFERRAL_LETTER"
        elif "discharge" in file.name.lower():
            document_type = "DISCHARGE_SUMMARY"
        
        # Cancel the animation task
        if not animation_task.done():
            animation_task.cancel()
            try:
                await animation_task
            except asyncio.CancelledError:
                pass
        
        # Send a completion message
        await cl.Message(
            content=f"✅ Document processed successfully: {file.name}",
            author="System"
        ).send()
        
        # Add document to documents array in claim data
        if "documents" not in claim_data:
            claim_data["documents"] = []
        
        # Add new document
        claim_data["documents"].append({
            "type": document_type,
            "id": file.name,
            "path": file_path
        })
        
        # Display updated claim data
        claim_data_md = f"## Updated Claim Data\n\n"
        claim_data_md += "### Documents\n\n"
        for i, doc in enumerate(claim_data.get("documents", [])):
            claim_data_md += f"- {doc.get('type', 'Unknown')}: {doc.get('id', 'No ID')}\n"
        
        await cl.Message(
            content=claim_data_md,
            author="System"
        ).send()
        
        # Send message to assistant to continue the flow
        if thread_id:
            await send_to_assistant(
                f"I've uploaded a {document_type.replace('_', ' ').title()} document. What else do I need to provide?",
                claim_data=claim_data
            )
        
        # Check if we should show the confirm submission button
        # This could be determined by the assistant's response or a threshold of documents
        required_docs = get_required_documents(claim_data.get("claimType", "HOSPITALISATION"))
        required_doc_codes = [doc["code"] for doc in required_docs if doc["required"]]
        uploaded_doc_types = [doc["type"] for doc in claim_data.get("documents", [])]
        
        # Check if all required documents are uploaded
        all_required_uploaded = all(code in uploaded_doc_types for code in required_doc_codes)
        
        if all_required_uploaded:
            # Add confirm submission button
            await cl.Message(
                content="You've uploaded all required documents. Would you like to submit your claim now?",
                author="System",
                actions=[
                    Action(
                        name="Confirm Submission",
                        value="confirm_submission",
                        description="Submit your claim",
                        payload={"claim_data": claim_data}
                    ),
                    Action(
                        name="Cancel",
                        value="cancel_submission",
                        description="Cancel claim submission",
                        payload={}
                    )
                ]
            ).send()
    
    except Exception as e:
        # Send an error message
        await cl.Message(
            content=f"Error processing document: {str(e)}",
            author="System"
        ).send()
