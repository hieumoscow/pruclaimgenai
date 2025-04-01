import os
from dotenv import load_dotenv, find_dotenv
from enum import Enum
from pydantic import BaseModel, Field
from typing import List, Dict, Optional

# Force reload of environment variables
load_dotenv(find_dotenv(), override=True)

from openai import AzureOpenAI
    
client = AzureOpenAI(
    api_key=os.environ["AZURE_OPENAI_API_KEY"],  
    api_version=os.environ["AZURE_OPENAI_API_VERSION"],
    azure_endpoint = os.environ["AZURE_OPENAI_ENDPOINT"]
    )

print("AzureOpenAI endpoint: ", os.environ["AZURE_OPENAI_ENDPOINT"])
print("AzureOpenAI API version: ", os.environ["AZURE_OPENAI_API_VERSION"])
# print("AzureOpenAI API key: ", os.environ["AZURE_OPENAI_API_KEY"])

# Define ClaimStatus enum for the response
class ClaimStatus(str, Enum):
    GATHERING_REQUIRED = "GATHERING_REQUIRED"  # Still collecting mandatory information
    GATHERING_OPTIONAL = "GATHERING_OPTIONAL"  # All required fields filled, collecting optional info
    COMPLETED = "COMPLETED"  # Ready for submission

# Define the response model
class ClaimResponse(BaseModel):
    claim_data: Dict  # Will contain claim data
    status: ClaimStatus
    message: str

assistant = client.beta.assistants.create(
    model="gpt-4o",
    name="PruClaim-agent",
    instructions="""You are a Prudential insurance claim submission assistant. Guide users through the claim process efficiently.

Your main responsibilities include:
1. Analyzing receipt data to determine the appropriate claim type
2. Filling in the claim schema with information from receipts and policy data
3. Guiding users through the claim submission process

When analyzing receipts and determining claim types, follow these guidelines:
- HOSPITALISATION: For claims involving hospital stays with admission and discharge dates
- OUTPATIENT: For claims involving doctor visits without hospital admission

For claim type determination, consider:
- If there are admission and discharge dates, it's likely a HOSPITALISATION claim
- If there's no hospital stay information, it's likely an OUTPATIENT claim
- Check which claim types are available in the user's policies

After determining the claim type, use the get_claim_schema function to retrieve the appropriate schema, then fill it with:
- Policy information (policy number, life assured)
- Receipt details (dates, hospital name, amounts)
- Currency information
- Total claim amount

For payout methods, use the get_payout_methods function to:
- Retrieve available payout methods for the selected policy
- Select the most appropriate payout method based on user preferences
- Include the payout method details in the claim schema
- Ensure the currency of the payout method matches the claim currency

For document collection, focus on these document types based on claim type:
- HOSPITALISATION: medical reports, discharge summaries
- OUTPATIENT: referral letters, specialist reports

Your response will be structured according to a specific JSON schema. Always include the required fields: claim_data, status, and message.

In the claim_data field, always include:
- claim_type: The determined claim type (either "HOSPITALISATION" or "OUTPATIENT")
- All fields from the claim schema filled with available information

Maintain a professional tone and guide users step-by-step through the claim process.""",
    tools=[
        {
            "type": "function",
            "function": {
                "name": "get_currencies",
                "description": "Get available currencies",
                "parameters": {
                    "type": "object",
                    "properties": {}
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "get_claim_schema",
                "description": "Get the schema for a specific claim type",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "claim_type": {
                            "type": "string",
                            "description": "The type of claim (HOSPITALISATION or OUTPATIENT)"
                        }
                    },
                    "required": ["claim_type"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "get_required_documents",
                "description": "Get the list of required documents for a specific claim type",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "claim_type": {
                            "type": "string",
                            "description": "The type of claim (HOSPITALISATION or OUTPATIENT)"
                        }
                    },
                    "required": ["claim_type"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "get_payout_methods",
                "description": "Get available payout methods for a specific policy",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "policy_id": {
                            "type": "string",
                            "description": "The ID of the policy to get payout methods for"
                        }
                    },
                    "required": ["policy_id"]
                }
            }
        }
    ],
    response_format={
        'type': 'json_schema',
        'json_schema': {
            "name": "ClaimResponse",
            "schema": ClaimResponse.model_json_schema()
        }
    }
)

print("\nAssistant created successfully!")
print(f"Assistant ID: {assistant.id}")

# Save the assistant ID to the .env file
with open('.env', 'r') as f:
    env_lines = f.readlines()

# Check if ASSISTANT_ID already exists in the .env file
assistant_id_exists = False
for i, line in enumerate(env_lines):
    if line.startswith('ASSISTANT_ID='):
        env_lines[i] = f'ASSISTANT_ID={assistant.id}\n'
        assistant_id_exists = True
        break

# If ASSISTANT_ID doesn't exist, add it
if not assistant_id_exists:
    env_lines.append(f'ASSISTANT_ID={assistant.id}\n')

# Write the updated .env file
with open('.env', 'w') as f:
    f.writelines(env_lines)

print("Assistant ID saved to .env file")