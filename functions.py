import os
import json
import requests
from typing import Any, Dict, List, Callable
from dotenv import load_dotenv, find_dotenv
from datetime import datetime
from AzureContentUnderstandingClient import Settings, AzureContentUnderstandingClient
from models import claim
from models.claim_documents import ClaimDocumentChecklist, RequiredDocument
from models.eligible_policies import EligiblePoliciesResponse
from models.common import Currency, CurrencyResponse
from models.payout_methods import PayoutMethod, PayoutMethodsResponse
from models.claim import ClaimTypeEnum

# Load environment variables
load_dotenv(find_dotenv(), override=True)

# API configuration
API_BASE_URL = "https://domain-services.agreeablewater-b30d4436.southeastasia.azurecontainerapps.io"
HEADERS = {
    "Content-Type": "application/json",
    "Lbu-Header": "COE",
    "X-API-Key": os.environ.get("API_KEY", "")  # Get API key from environment variables
}

# Check if API_KEY is set
if not HEADERS["X-API-Key"]:
    print("Warning: API_KEY environment variable is not set. API calls may fail.")


def get_eligible_policies(client_id: str) -> EligiblePoliciesResponse:
    """
    Get eligible policies for a specific client.
    
    :param client_id: The client ID to get eligible policies for
    :return: EligiblePoliciesResponse containing eligible policies
    """
    # Call the API to get eligible policies
    url = f"{API_BASE_URL}/policy/v1/policies/eligible/health?client_id={client_id}"
    
    try:
        response = requests.get(url, headers=HEADERS)
        response.raise_for_status()  # Raise an exception for 4XX/5XX responses
        
        # Convert API response to Pydantic model
        return EligiblePoliciesResponse.model_validate({"policies": response.json()})
    except requests.exceptions.RequestException as e:
        print(f"Error fetching eligible policies: {e}")
        return EligiblePoliciesResponse()


def get_currencies() -> CurrencyResponse:
    """
    Get list of available currencies.
    
    :return: CurrencyResponse containing list of currencies
    """
    # Call the API to get currencies
    url = f"{API_BASE_URL}/claim/v1/currencies"
    try:
        response = requests.get(url, headers=HEADERS)
        response.raise_for_status()  # Raise an exception for 4XX/5XX responses
        
        # Use model_validate to parse the API response
        currency_response = CurrencyResponse.model_validate({"currencies": response.json()})
        return currency_response
    except requests.exceptions.RequestException as e:
        print(f"Error fetching currencies: {e}")
        return CurrencyResponse()


def get_required_documents(claim_type: str) -> ClaimDocumentChecklist:
    """
    Get the list of required documents for a specific claim type.
    
    :param claim_type: The type of claim (HOSPITALISATION, OUTPATIENT, etc.)
    :return: ClaimDocumentChecklist containing required documents
    """
    url = f"{API_BASE_URL}/claim/v1/claim-documents/checklist?claim_type={claim_type}"
    print(f"Fetching required documents: {url}, Headers: {HEADERS}")
    try:
        response = requests.get(url, headers=HEADERS)
        print(f"Response: {response}")
        if response.status_code == 200:
            # Convert API response to ClaimDocumentChecklist model
            response_data = response.json()
            return ClaimDocumentChecklist.model_validate({"documents": response_data})
        else:
            print(f"Error fetching required documents: {response.status_code}")
            return ClaimDocumentChecklist(documents=[])
    except Exception as e:
        print(f"Exception while fetching required documents: {str(e)}")
        return ClaimDocumentChecklist(documents=[])


def get_payout_methods(policy_id: str) -> PayoutMethodsResponse:
    """
    Fetches available payout methods for a policy.
    
    Args:
        policy_id (str): The policy ID to fetch payout methods for
        
    Returns:
        PayoutMethodsResponse: A response containing a list of PayoutMethod objects
    """
    url = f"{API_BASE_URL}/policy/{policy_id}/payouts/methods?transaction_type=CLAIM"
    
    try:
        response = requests.get(url, headers=HEADERS)
        response.raise_for_status()
        
        # Use model_validate to parse the API response
        response_data = response.json()
        payout_methods_response = PayoutMethodsResponse.model_validate({"methods": response_data})
        print(payout_methods_response)
        return payout_methods_response
    except requests.exceptions.RequestException as e:
        print(f"Error fetching payout methods: {e}")
        return []


def analyze_document(file_path: str) -> Dict[str, Any]:
    """
    Analyze a document (receipt, medical report, etc.) using Azure Content Understanding API.
    
    :param file_path: Path to the document file
    :return: Dictionary containing extracted information from the document
    """
    try:
        # Check if file exists
        if not os.path.exists(file_path):
            return {
                "success": False,
                "error": f"File not found: {file_path}",
                "message": "Please provide a valid file path"
            }
        
        # Initialize Azure Content Understanding client
        settings = Settings(
            endpoint=os.environ["AZURE_CONTENT_UNDERSTANDING_ENDPOINT"],
            api_version="2024-12-01-preview",
            subscription_key=os.environ["AZURE_CONTENT_UNDERSTANDING_SUBSCRIPTION_KEY"],
            analyzer_id="hclaim",
            file_location=file_path
        )
        
        client = AzureContentUnderstandingClient(
            settings.endpoint,
            settings.api_version,
            subscription_key=settings.subscription_key,
            token_provider=settings.token_provider,
        )
        
        print(f"Analyzing document: {file_path}")
        
        # Make the API call
        response = client.begin_analyze(settings.analyzer_id, settings.file_location)
        result = client.poll_result(
            response,
            timeout_seconds=60,
            polling_interval_seconds=1,
        )
        
        return result
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "message": "An error occurred while analyzing the document"
        }


def get_claim_schema(claim_type: ClaimTypeEnum) -> Dict[str, Any]:
    """
    Fetch the appropriate JSON schema based on the claim type.
    
    Args:
        claim_type (ClaimTypeEnum): The type of claim (HOSPITALISATION or OUTPATIENT)
        
    Returns:
        Dict[str, Any]: The JSON schema for the specified claim type
    
    Raises:
        ValueError: If the claim type is not supported
    """
    # Validate claim type
    if claim_type not in [ClaimTypeEnum.HOSPITALISATION, ClaimTypeEnum.OUTPATIENT]:
        raise ValueError(f"Unsupported claim type: {claim_type}. Must be one of: {', '.join([e.value for e in ClaimTypeEnum])}")
    
    claim_file = ""
    if(claim_type == ClaimTypeEnum.HOSPITALISATION):
        claim_file="hospitalisation.json"
    elif(claim_type == ClaimTypeEnum.OUTPATIENT):
        claim_file="outpatient.json"

    # Determine the schema file path - use the current file's directory as base
    current_dir = os.path.dirname(os.path.abspath(__file__))
    schema_file = os.path.join(
        current_dir,
        "models", 
        "schemas", 
        f"{claim_file}"
    )
    
    print(f"Looking for schema file at: {schema_file}")
    
    # Check if the schema file exists
    if not os.path.exists(schema_file):
        raise FileNotFoundError(f"Schema file not found: {schema_file}")
    
    # Load and return the schema
    try:
        with open(schema_file, 'r') as f:
            schema = json.load(f)
        return schema
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in schema file: {e}")
    except Exception as e:
        raise Exception(f"Error loading schema file: {e}")


# Test function 
def test_function(param: str, func):
    """
    Generic test function that calls the provided function with the parameter if needed.
    
    Args:
        param: Parameter to pass to the function (if the function accepts parameters)
        func: Function to test
    """
    print(f"Testing function with parameter: {param}")
    try:
        # Check if the function takes parameters
        import inspect
        sig = inspect.signature(func)
        
        if len(sig.parameters) > 0:
            result = func(param)
        else:
            result = func()
            
        print(f"Result: {result}\n\n")
    except Exception as e:
        print(f"Error: {e}")


def main():
    """
    Main function to demonstrate the usage of the API functions.
    This can be used to test the API functions directly by running this file.
    """
    print("PruClaim GenAI API Functions Test")
    print("-" * 50)
    
    # Test getting eligible policies
    test_function("C111", get_eligible_policies)
    
    # Test getting currencies
    test_function(None, get_currencies)

    # Test payout methods
    test_function("P111111", get_payout_methods)
    
    # Test getting claim schema
    print("\nTesting get_claim_schema")
    try:
        # Test HOSPITALISATION schema
        hosp_schema = get_claim_schema(ClaimTypeEnum.HOSPITALISATION)
        print(f"HOSPITALISATION schema title: {hosp_schema.get('title', 'Unknown')}")
        print(f"HOSPITALISATION schema properties: {len(hosp_schema.get('properties', {}))}")
        
        # Test OUTPATIENT schema
        outpatient_schema = get_claim_schema(ClaimTypeEnum.OUTPATIENT)
        print(f"OUTPATIENT schema: {outpatient_schema}")
        print(f"OUTPATIENT schema properties: {len(outpatient_schema.get('properties', {}))}")
    except Exception as e:
        print(f"Error testing get_claim_schema: {e}")
    
    print("\nTests completed")


if __name__ == "__main__":
    main()
