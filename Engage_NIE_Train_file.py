import logging
import os
import openai
import azure.functions as func
from azure.identity import DefaultAzureCredential
from azure.search.documents import SearchClient
from azure.search.documents.models import QueryType
from azure.core.credentials import AzureKeyCredential
import json
from azure.cosmos import CosmosClient
from azure.keyvault.secrets import SecretClient
from azure.storage.blob import BlobServiceClient
from io import BytesIO
import pandas as pd

# Replace these values with your Azure Key Vault URL
keyvault_url = "https://nie-alex-key-vault-prod.vault.azure.net/"
# Create a SecretClient using the DefaultAzureCredential
credential = DefaultAzureCredential()
client_kv = SecretClient(vault_url=keyvault_url, credential=credential)

# Replace these with your own values, either in environment variables or directly here
AZURE_SEARCH_SERVICE = client_kv.get_secret("alex-nie-search-service").value
AZURE_SEARCH_INDEX = client_kv.get_secret("alex-nie-search-index").value
AZURE_OPENAI_SERVICE = client_kv.get_secret("alex-nie-openai-service").value
AZURE_OPENAI_CHATGPT_DEPLOYMENT = client_kv.get_secret("alex-nie-chatgpt-deployment").value
AZURE_SEARCH_API_KEY = client_kv.get_secret("alex-nie-search-api-key").value
AZURE_OPENAI_EMB_DEPLOYMENT = client_kv.get_secret("alex-nie-openai-embedding").value

KB_FIELDS_CONTENT = "content"
KB_FIELDS_CATEGORY = "category"
KB_FIELDS_SOURCEPAGE = "sourcepage"
KB_FIELDS_SOURCEFILE = "sourcefile"

AZURE_CLIENT_ID = os.environ.get("AZURE_CLIENT_ID")
AZURE_CLIENT_SECRET = os.environ.get("AZURE_CLIENT_SECRET")
AZURE_TENANT_ID = os.environ.get("AZURE_TENANT_ID")
AZURE_SUBSCRIPTION_ID = os.environ.get("AZURE_SUBSCRIPTION_ID")


# Use the current user identity to authenticate with Azure OpenAI, Cognitive Search and Blob Storage (no secrets needed, 
# just use 'az login' locally, and managed identity when deployed on Azure). If you need to use keys, use separate AzureKeyCredential instances with the 
# keys for each service

credential = AzureKeyCredential(AZURE_SEARCH_API_KEY)

# Used by the OpenAI SDK
openai.api_base = f"https://{AZURE_OPENAI_SERVICE}.openai.azure.com"
openai.api_version = "2023-05-15"

# Comment these two lines out if using keys, set your API key in the OPENAI_API_KEY environment variable and set openai.api_type = "azure" instead
openai.api_type = "azure"
# openai.api_key = client_kv.get_secret("alex-nie-openai-key").value

# Set up clients for Cognitive Search and Storage
search_client = SearchClient(
    endpoint=f"https://{AZURE_SEARCH_SERVICE}.search.windows.net",
    index_name=AZURE_SEARCH_INDEX,
    credential=credential)

# Setup blob storage connection
connection_string = client_kv.get_secret("alex-nie-storage-connection-string").value
container_name = client_kv.get_secret("alex-nie-storage-container").value
def extract_engage_prompt(blob_name_excel):
    # Replace these variables with your actual values
    account_name = client_kv.get_secret("alex-nie-storage-account").value
    account_key = client_kv.get_secret("alex-nie-storage-key").value
    container_name_2 = client_kv.get_secret("alex-nie-container-2").value

    # Create a BlobServiceClient
    blob_service_client = BlobServiceClient(account_url=f"https://{account_name}.blob.core.windows.net", credential=account_key)

    # Get a reference to the container
    container_client = blob_service_client.get_container_client(container_name_2)

    # Get a reference to the blob
    blob_client = container_client.get_blob_client(blob_name_excel)

    # Download blob content into a BytesIO object
    blob_content = blob_client.download_blob().readall()
    blob_stream = BytesIO(blob_content)

    # Read Excel file into a pandas DataFrame
    df = pd.read_excel(blob_stream, engine='openpyxl')

    # Now you can work with the DataFrame as needed
    engages = df['Engage'].tolist()
    return engages

def send_message(messages, model_name, max_response_tokens=2048):
    response = openai.ChatCompletion.create(
    engine=model_name,
    messages=messages,
    temperature=0.0,
    max_tokens=max_response_tokens
    )
    return response['choices'][0]['message']['content']
def train_prompts(blob_name_excel):
    # Engage training

    # Defining the system prompt
    system_message = f"""
        You are a faculty AI who helps teachers to answer their question.
        Answer ONLY with the facts listed in the list of sources below. 
        If there isn't enough information below, say you don't know. Do not generate answers that don't use the sources below. 
        If asking a clarifying question to the user would help, ask the question.
        Give a detailed response."""

    engages = extract_engage_prompt(blob_name_excel)

    messages=[{"role": "system", "content": system_message}]
    for prompt_engage in engages:
        if 'TE21' in prompt_engage:
            messages_engage = [{"role": "system", "content": system_message}]
            # Exclude category, to simulate scenarios where there's a set of docs you can't see
            exclude_category = 'NIE Knowledge Base_TE21 Framework.pdf'
            query_vector = openai.Embedding.create(engine=AZURE_OPENAI_EMB_DEPLOYMENT, input=prompt_engage)["data"][0]["embedding"]
            filter = "sourcefile eq '{}'".format(exclude_category.replace("'", "''")) if exclude_category else None
            r = search_client.search(prompt_engage, 
                                    filter=filter,
                                    query_type=QueryType.SEMANTIC, 
                                    query_language="en-us", 
                                    query_speller="lexicon", 
                                    semantic_configuration_name="default", 
                                    top=5,
                                    vector=query_vector if query_vector else None, 
                                    top_k=50 if query_vector else None,
                                    vector_fields="embedding" if query_vector else None
                                    )
            results = [doc[KB_FIELDS_SOURCEFILE] + ": " + doc[KB_FIELDS_CONTENT].replace("\n", "").replace("\r", "") for doc in r]
            content = "\n".join(results)
            user_message = prompt_engage + " \nSOURCES:\n" + content

            # Create the list of messages. role can be either "user" or "assistant" 
            messages_engage.append({"role": "user", "content": user_message})
            response = send_message(messages_engage, AZURE_OPENAI_CHATGPT_DEPLOYMENT)
            messages.append({"role": "user", "content": prompt_engage})
            messages.append({"role": "assistant", "content": response})
        elif 'V3SK' in prompt_engage:
            messages_engage = [{"role": "system", "content": system_message}]
            # Exclude category, to simulate scenarios where there's a set of docs you can't see
            exclude_category = 'NIE Knowledge Base_TE21_Framework_Values.pdf'
            query_vector = openai.Embedding.create(engine=AZURE_OPENAI_EMB_DEPLOYMENT, input=prompt_engage)["data"][0]["embedding"]
            filter = "sourcefile eq '{}'".format(exclude_category.replace("'", "''")) if exclude_category else None
            r = search_client.search(prompt_engage, 
                                    filter=filter,
                                    query_type=QueryType.SEMANTIC, 
                                    query_language="en-us", 
                                    query_speller="lexicon", 
                                    semantic_configuration_name="default", 
                                    top=10,
                                    vector=query_vector if query_vector else None, 
                                    top_k=50 if query_vector else None,
                                    vector_fields="embedding" if query_vector else None
                                    )
            results = [doc[KB_FIELDS_SOURCEPAGE] + ": " + doc[KB_FIELDS_CONTENT].replace("\n", "").replace("\r", "") for doc in r]
            content = "\n".join(results)
            user_message = prompt_engage + " \nSOURCES:\n" + content

            # Create the list of messages. role can be either "user" or "assistant" 
            messages_engage.append({"role": "user", "content": user_message})
            response = send_message(messages_engage, AZURE_OPENAI_CHATGPT_DEPLOYMENT)
            messages.append({"role": "user", "content": prompt_engage})
            messages.append({"role": "assistant", "content": response})
        elif '5Cs' in prompt_engage:
            messages_engage = [{"role": "system", "content": system_message}]
            # Exclude category, to simulate scenarios where there's a set of docs you can't see
            exclude_category = 'NIE Knowledge Base_5Cs.pdf'
            query_vector = openai.Embedding.create(engine=AZURE_OPENAI_EMB_DEPLOYMENT, input=prompt_engage)["data"][0]["embedding"]
            filter = "sourcefile eq '{}'".format(exclude_category.replace("'", "''")) if exclude_category else None
            r = search_client.search(prompt_engage, 
                                    filter=filter,
                                    query_type=QueryType.SEMANTIC, 
                                    query_language="en-us", 
                                    query_speller="lexicon", 
                                    semantic_configuration_name="default", 
                                    top=5,
                                    vector=query_vector if query_vector else None, 
                                    top_k=50 if query_vector else None,
                                    vector_fields="embedding" if query_vector else None
                                    )
            results = [doc[KB_FIELDS_SOURCEFILE] + ": " + doc[KB_FIELDS_CONTENT].replace("\n", "").replace("\r", "") for doc in r]
            content = "\n".join(results)
            user_message = prompt_engage + " \nSOURCES:\n" + content

            # Create the list of messages. role can be either "user" or "assistant" 
            messages_engage.append({"role": "user", "content": user_message})
            response = send_message(messages_engage, AZURE_OPENAI_CHATGPT_DEPLOYMENT)
            messages.append({"role": "user", "content": prompt_engage})
            messages.append({"role": "assistant", "content": response})
        else:
            messages_engage = [{"role": "system", "content": system_message}]
            # Exclude category, to simulate scenarios where there's a set of docs you can't see
            exclude_category = 'NIE'
            query_vector = openai.Embedding.create(engine=AZURE_OPENAI_EMB_DEPLOYMENT, input=prompt_engage)["data"][0]["embedding"]
            filter = "category eq '{}'".format(exclude_category.replace("'", "''")) if exclude_category else None
            r = search_client.search(prompt_engage, 
                                    filter=filter,
                                    query_type=QueryType.SEMANTIC, 
                                    query_language="en-us", 
                                    query_speller="lexicon", 
                                    semantic_configuration_name="default", 
                                    top=5,
                                    vector=query_vector if query_vector else None, 
                                    top_k=50 if query_vector else None,
                                    vector_fields="embedding" if query_vector else None
                                    )
            results = [doc[KB_FIELDS_SOURCEFILE] + ": " + doc[KB_FIELDS_CONTENT].replace("\n", "").replace("\r", "") for doc in r]
            content = "\n".join(results)
            user_message = prompt_engage + " \nSOURCES:\n" + content

            # Create the list of messages. role can be either "user" or "assistant" 
            messages_engage.append({"role": "user", "content": user_message})
            response = send_message(messages_engage, AZURE_OPENAI_CHATGPT_DEPLOYMENT)
            messages.append({"role": "user", "content": prompt_engage})
            messages.append({"role": "assistant", "content": response})
    return messages
def save_file(blob_name, blob_name_excel):
    # open file in write mode
    # blob_name = 'engage_NIE.json'
    blob_service_client = BlobServiceClient.from_connection_string(connection_string)
    container_client = blob_service_client.get_container_client(container_name)
    json_data = json.dumps(train_prompts(blob_name_excel))
    data_bytes = json_data.encode("utf-8")

    # Upload the JSON data as a block blob
    container_client.upload_blob(name=blob_name, data=data_bytes, blob_type="BlockBlob", overwrite = True)
    return('The file has been indexed!')

