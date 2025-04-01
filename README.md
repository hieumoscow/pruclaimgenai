# PruClaim GenAI - Insurance Claim Processing Application

PruClaim GenAI is an intelligent insurance claim processing application that leverages Azure Document Intelligence and OpenAI to automate and streamline the claim submission process.

## Features

- **Receipt Processing**: Upload and process multiple receipts in parallel
- **Intelligent Data Extraction**: Extract key information from receipts using Azure Document Intelligence
- **Automated Claim Type Determination**: AI-powered analysis to determine the appropriate claim type
- **Schema Validation**: Structured data models with Pydantic for robust validation
- **Dual Interface**: Choose between Chainlit (chat-based) or Streamlit (web-based) interfaces

## Prerequisites

- Python 3.9+
- Azure OpenAI API access
- Azure Document Intelligence API access
- Required API keys configured in `.env` file

## Setup

1. Clone the repository
2. Install the required dependencies:
   ```
   pip install -r requirements.txt
   ```
3. Configure your `.env` file with the necessary API keys:
   ```
   AZURE_OPENAI_ENDPOINT=your_openai_endpoint
   AZURE_OPENAI_API_KEY=your_openai_api_key
   AZURE_OPENAI_API_VERSION=2025-03-01-preview
   ASSISTANT_ID=your_assistant_id
   AZURE_CONTENT_UNDERSTANDING_ENDPOINT=your_document_intelligence_endpoint
   AZURE_CONTENT_UNDERSTANDING_SUBSCRIPTION_KEY=your_document_intelligence_key
   ```

## Running the Application

### Setup the OpenAI Assistant

Before running the application, you need to set up the OpenAI Assistant:

```bash
python aoai_assistant_setup.py
```

This will create an assistant with the necessary tools and instructions, and update your `.env` file with the assistant ID.

### Running the Chat Interface (Chainlit)

To run the application with the chat-based interface:

```bash
chainlit run chatapp.py
```

This will start a local web server with a chat interface for interacting with the application.

### Running the Web Interface (Streamlit)

Alternatively, you can use the Streamlit interface for a more traditional web application experience:

```bash
streamlit run streamlitapp.py
```

## Usage

1. Log in with a client ID (any ID is accepted in the demo mode)
2. Upload one or more receipt images or PDFs
3. The system will automatically extract information from the receipts
4. The AI will analyze the receipts and determine the appropriate claim type
5. Review the claim analysis and extracted information
6. The system will provide a filled claim schema based on the analysis

## Data Models

The application uses structured Pydantic models for data validation:

- **Receipt Models**: Structured representation of receipt data and extraction results
- **Claim Models**: Comprehensive models for claim data, including receipts, payout information, and claim details
- **Policy Models**: Models for eligible policies and related information

## Architecture

- **Azure Document Intelligence**: Used for extracting structured data from receipts
- **Azure OpenAI**: Powers the intelligent claim type determination and schema filling
- **Chainlit/Streamlit**: Provides the user interface
- **Pydantic**: Ensures data validation and structured data handling

## License

This project is proprietary and confidential.
