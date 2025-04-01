import os
import json
import asyncio
import re
from dotenv import load_dotenv, find_dotenv
from openai import AzureOpenAI
from aoai_assistant_setup import ClaimResponse
from functions import (
    get_eligible_policies,
    get_currencies,
    get_required_documents,
    get_claim_schema,
    get_payout_methods
)

# Define ClaimStatus enum to match the one in aoai_assistant_setup.py
class ClaimStatus:
    GATHERING_REQUIRED = "GATHERING_REQUIRED"
    GATHERING_OPTIONAL = "GATHERING_OPTIONAL"
    COMPLETED = "COMPLETED"

# Force reload of environment variables
load_dotenv(find_dotenv(), override=True)

# Initialize the Azure OpenAI client
client = AzureOpenAI(
    api_key=os.environ["AZURE_OPENAI_API_KEY"],  
    api_version=os.environ["AZURE_OPENAI_API_VERSION"],
    azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"]
)

# Get the assistant ID from environment variables or use a default
ASSISTANT_ID = os.environ.get("ASSISTANT_ID", "asst_Ow9Jg3aTxPDCLQRGbxmQBSgn")

def create_thread():
    """
    Create a new thread for conversation with the assistant.
    
    Returns:
        str: The ID of the newly created thread
    """
    thread = client.beta.threads.create()
    return thread.id
    
async def wait_for_run_completion(thread_id, run_id):
    while True:
        run = client.beta.threads.runs.retrieve(
            thread_id=thread_id,
            run_id=run_id
        )
        
        if run.status == "completed":
            return run
        elif run.status == "requires_action":
            # Handle tool calls
            tool_outputs = []
            for tool_call in run.required_action.submit_tool_outputs.tool_calls:
                function_name = tool_call.function.name
                function_args = json.loads(tool_call.function.arguments)
                
                # Call the appropriate function
                if function_name == "get_eligible_policies":
                    # If client_id is provided in context but not in args, use the context one
                    if "client_id" not in function_args:
                        function_args["client_id"] = None
                    output = get_eligible_policies(client_id=function_args.get("client_id"))
                elif function_name == "get_currencies":
                    output = get_currencies()
                elif function_name == "submit_claim":
                    # Add context information if not provided in args
                    if "client_id" not in function_args:
                        function_args["client_id"] = None
                    if "life_assured_id" not in function_args:
                        function_args["life_assured_id"] = None
                        
                    output = submit_claim(
                        client_id=function_args.get("client_id"),
                        life_assured_id=function_args.get("life_assured_id"),
                        claim_type=function_args.get("claim_type"),
                        policy_id=function_args.get("policy_id"),
                        claim_details=function_args.get("claim_details"),
                        receipts=function_args.get("receipts"),
                        payout=function_args.get("payout")
                    )
                elif function_name == "get_required_documents":
                    output = get_required_documents(
                        claim_type=function_args.get("claim_type")
                    )
                elif function_name == "get_claim_schema":
                    output = get_claim_schema(
                        claim_type=function_args.get("claim_type")
                    )
                elif function_name == "get_payout_methods":
                    output = get_payout_methods(
                        policy_id=function_args.get("policy_id")
                    )
                else:
                    output = {"error": f"Function {function_name} not implemented"}
                
                # Convert Pydantic model to dict for JSON serialization
                if hasattr(output, "model_dump"):
                    output = output.model_dump()
                
                tool_outputs.append({
                    "tool_call_id": tool_call.id,
                    "output": str(output)
                })

                print("Output:", output)
                print("Tool Outputs:", tool_outputs)
            
            # Submit the tool outputs
            run = client.beta.threads.runs.submit_tool_outputs(
                thread_id=thread_id,
                run_id=run.id,
                tool_outputs=tool_outputs
            )
        elif run.status in ["failed", "cancelled", "expired"]:
            return run
        
        await asyncio.sleep(1)

async def run_conversation(assistant_id, user_input, thread_id=None) -> tuple[str, str, ClaimResponse]:
    """
    Run a conversation with the assistant.
    
    Args:
        assistant_id (str): The ID of the assistant to use
        user_input (str): The user's input message
        thread_id (str, optional): The ID of an existing thread to continue
        
    Returns:
        tuple: (thread_id, assistant_response, structured_data)
    """
    # Create a new thread if one doesn't exist
    if thread_id is None:
        thread = client.beta.threads.create()
        thread_id = thread.id
        print(f"Created new thread: {thread_id}")
    else:
        print(f"Using existing thread: {thread_id}")
    
    # Add the user's message to the thread
    message = client.beta.threads.messages.create(
        thread_id=thread_id,
        role="user",
        content=user_input
    )
    
    run = client.beta.threads.runs.create(
        thread_id=thread_id,
        assistant_id=assistant_id,
    )
    # Wait for the run to complete
    run = await wait_for_run_completion(thread_id, run.id)
    
    # Get the assistant's response
    messages = client.beta.threads.messages.list(
        thread_id=thread_id,
        order="desc",
        limit=1
    )
    
    assistant_response = ""
    structured_data = None
    
    for message in messages.data:
        if message.role == "assistant":
            # Extract the text content
            for content in message.content:
                if content.type == "text":
                    assistant_response = content.text.value
    
    print("Assistant Response:", messages)
    
    # Try to parse the JSON from the assistant response
    try:
        # First, try to parse the entire response as JSON
        json_data = json.loads(assistant_response)
        structured_data = ClaimResponse.model_validate(json_data)
    except json.JSONDecodeError:
        # If that fails, try to extract JSON using regex
        print(f"Error: Could not parse structured data from assistant response: {assistant_response}")
    
    return thread_id, assistant_response, structured_data

async def main():
    # Example usage
    thread_id = None
    while True:
        user_input = input("You: ")
        if user_input.lower() in ["exit", "quit", "bye"]:
            break
        
        thread_id, response, structured_data = await run_conversation(ASSISTANT_ID, user_input, thread_id)
        print(f"Assistant: {response}")
        if structured_data:
            print("Structured Data:")
            print(json.dumps(structured_data, indent=4))

if __name__ == "__main__":
    asyncio.run(main())
