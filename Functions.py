import os
import openai
from azure.identity import DefaultAzureCredential
from azure.search.documents import SearchClient
from azure.search.documents.models import QueryType
from azure.core.credentials import AzureKeyCredential
from azure.cosmos import CosmosClient
from azure.keyvault.secrets import SecretClient
from azure.storage.blob import BlobServiceClient
import re
from docx import Document
from io import BytesIO
import pandas as pd
import json

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

KB_FIELDS_CONTENT = os.environ.get("KB_FIELDS_CONTENT") or "content"
KB_FIELDS_CATEGORY = os.environ.get("KB_FIELDS_CATEGORY") or "category"
KB_FIELDS_SOURCEPAGE = os.environ.get("KB_FIELDS_SOURCEPAGE") or "sourcepage"
KB_FIELDS_SOURCEFILE = os.environ.get("KB_FIELDS_SOURCEPAGE") or "sourcefile"

AZURE_CLIENT_ID = os.environ.get("AZURE_CLIENT_ID")
AZURE_CLIENT_SECRET = os.environ.get("AZURE_CLIENT_SECRET")
AZURE_TENANT_ID = os.environ.get("AZURE_TENANT_ID")
AZURE_SUBSCRIPTION_ID = os.environ.get("AZURE_SUBSCRIPTION_ID")

# # Used by the OpenAI SDK
openai.api_base = f"https://{AZURE_OPENAI_SERVICE}.openai.azure.com"
openai.api_version = "2023-07-01 preview"
# # Comment these two lines out if using keys, set your API key in the OPENAI_API_KEY environment variable and set openai.api_type = "azure" instead
openai.api_type = "azure"
openai.api_key = client_kv.get_secret("alex-nie-openai-key").value


connection_string = client_kv.get_secret("alex-nie-storage-connection-string").value
storage_account_name = client_kv.get_secret("alex-nie-storage-account").value
storage_account_key = client_kv.get_secret("alex-nie-storage-key").value

#List of containers from Azure storage account
def containers_storage_account(container_name):
    return client_kv.get_secret(f"{container_name}").value

#This function used for get the container name
def cosmos_db_retrieve(container_name):
    database_name_kv = client_kv.get_secret("alex-nie-cosmosdb-name").value 
    container_name_kv = client_kv.get_secret(f"{container_name}").value
    key = client_kv.get_secret("alex-nie-cosmosdb-key").value
    endpoint = f"https://{database_name_kv}.documents.azure.com/"
    client = CosmosClient(endpoint, key)
    database = client.get_database_client(database_name_kv)
    container = database.get_container_client(container_name_kv)
    return container


#This function used for print the conversation
def print_conversation(messages):
    for message in messages:
        print(f"[{message['role'].upper()}]")
        print(message['content'])
        print()

def send_message_json_conversational_chat_external(messages, prompt, temperature = 0.5, max_response_tokens=2048):
    system_prompt = "You are a friendly AI assistant named ALEX who helps teacher to answer their questions in anything."
    messages.append({'role': 'system', 'content': system_prompt})
    messages.append({'role': 'user', 'content': prompt})
    response = openai.ChatCompletion.create(
        engine=AZURE_OPENAI_CHATGPT_DEPLOYMENT,
        messages=messages,
        temperature=temperature,
        max_tokens=max_response_tokens
    )
    return response['choices'][0]['message']['content']

def get_url_reference(messages, temperature = 0.0, max_response_tokens=512):
    check_source = """Please list out maximum 5 reference resources in URLs for the above response, do not try to return an irrelevant ones? \
                        return the outcome in a json object with the following structure:
                    {{"References": <a list of URLs>}}
                    """
    messages.append({'role': 'user', 'content': check_source})
    response_url = openai.ChatCompletion.create(
        engine=AZURE_OPENAI_CHATGPT_DEPLOYMENT,
        messages=messages,
        temperature=temperature,
        max_tokens=max_response_tokens
    )
    return json.loads(response_url['choices'][0]['message']['content'])

def check_internal_resource(messages, search_prompt):
    # system_prompt_course_internal = f"""You are an intelligent faculty named ALEX who assists teacher to answer their questions based on the provided sources."""
    # chat_check = [{"role": "system", "content": system_prompt_course_internal}]
    search_prompt_final = f"""Check the context of the conversation: {messages} related to the source: {search_prompt} then respond with a Y or N character, with no punctuation: \
                                Y - if the question related to the source \
                                N - otherwise
                            """
    chat_check = [({"role": "user", "content": search_prompt_final})]
    response_check = openai.ChatCompletion.create(
        engine=AZURE_OPENAI_CHATGPT_DEPLOYMENT,
        messages=chat_check,
        temperature=0.0,
        max_tokens=10
    )
    return response_check['choices'][0]['message']['content']

#This function used for create a response from chatGPT
def send_message(messages, temperature = 0.2, max_response_tokens=1024):
    openai.api_version = "2023-07-01-preview"
    response = openai.ChatCompletion.create(
        engine=AZURE_OPENAI_CHATGPT_DEPLOYMENT,
        messages=messages,
        temperature=temperature,
        max_tokens=max_response_tokens
    )
    return response['choices'][0]['message']['content']

#This function used to print the last response from a conversation
def latest_response(messages):
    last_reponse = len(messages)
    for i in range(0, len(messages) + 1):
        if i == last_reponse:     
            response = messages[i-1]['content']
    return response

#This function used to read a file from Azure blob storage
def read_file_blob(blob_name):
    blob_service_client = BlobServiceClient.from_connection_string(connection_string)
    blob_name = blob_name
    container_name = client_kv.get_secret("alex-nie-storage-container").value
    container_client = blob_service_client.get_container_client(container_name)
    blob_client = container_client.get_blob_client(blob_name)
    blob_data = blob_client.download_blob()
    content = blob_data.readall()
    # <text> = content.decode("utf-8")
    return content

#This function used to translate US English to UK English
def translate_to_en_uk(blob_name, response):
    def is_camel_case(s):
        return s != s.lower() and s != s.upper() and "_" not in s
    content = read_file_blob(blob_name)
    words_mapping = content.decode("utf-8")
    for row in words_mapping.split('\n'):
        mapping = row.strip().split("\t")
        word_uk = mapping[0].strip()
        word_us = mapping[-1].strip()
        response = str(response)
        response_word = response.replace('"', '').replace(':','').replace('.','').replace(',','').replace('\n','')
        response_words = response_word.split(' ')
        for word in response_words:
            if is_camel_case(word):
                if word_us.lower() == word.lower():
                    Camel_letter = word_uk[0].upper()
                    word_uk = Camel_letter + word_uk[1:]
                    response_uk = response.replace(word, word_uk)
                    response = response_uk
                    break
                else:
                    response
            else:
                if word_us.lower() == word.lower():
                    response_uk = response.replace(word, word_uk)
                    response = response_uk
                    break
                else:
                    response
    return response

#This function used to search document from Azure Index
def search(prompt, exclude_category, field):
    credential = AzureKeyCredential(AZURE_SEARCH_API_KEY)
    # # Used by the OpenAI SDK
    openai.api_base = f"https://{AZURE_OPENAI_SERVICE}.openai.azure.com"
    openai.api_version = "2023-05-15"
    openai.api_type = "azure"
    openai.api_key = client_kv.get_secret("alex-nie-openai-key").value
    # Set up clients for Cognitive Search and Storage
    search_client = SearchClient(
        endpoint=f"https://{AZURE_SEARCH_SERVICE}.search.windows.net",
        index_name=AZURE_SEARCH_INDEX,
        credential=credential)   
    query_vector = openai.Embedding.create(engine=AZURE_OPENAI_EMB_DEPLOYMENT, input=prompt)["data"][0]["embedding"]
    filter = "{field} eq '{exclude_category}'".format(field = field, exclude_category = exclude_category) if exclude_category else None
    r = search_client.search(prompt, 
                            filter=filter,
                            query_type=QueryType.SIMPLE, 
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
    user_message = prompt + "\n SOURCES:\n" + content
    return user_message

def search_MOE(prompt, filter):
    credential = AzureKeyCredential(AZURE_SEARCH_API_KEY)
    # # Used by the OpenAI SDK
    openai.api_base = f"https://{AZURE_OPENAI_SERVICE}.openai.azure.com"
    openai.api_version = "2023-05-15"
    openai.api_type = "azure"
    openai.api_key = client_kv.get_secret("alex-nie-openai-key").value
    # Set up clients for Cognitive Search and Storage
    search_client = SearchClient(
        endpoint=f"https://{AZURE_SEARCH_SERVICE}.search.windows.net",
        index_name=AZURE_SEARCH_INDEX,
        credential=credential)   
    query_vector = openai.Embedding.create(engine=AZURE_OPENAI_EMB_DEPLOYMENT, input=prompt)["data"][0]["embedding"]
    filter = "{filter}".format(filter = filter) if filter else None
    r = search_client.search(prompt, 
                            filter=filter,
                            query_type=QueryType.SIMPLE, 
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
    user_message = "SOURCES:\n" + content
    return user_message

#This function used to search document and only return the sources
def search_docs_source(prompt, exclude_category):
    credential = AzureKeyCredential(AZURE_SEARCH_API_KEY)
    # # Used by the OpenAI SDK
    openai.api_base = f"https://{AZURE_OPENAI_SERVICE}.openai.azure.com"
    openai.api_version = "2023-05-15"
    openai.api_type = "azure"
    openai.api_key = client_kv.get_secret("alex-nie-openai-key").value
    # Set up clients for Cognitive Search and Storage
    search_client = SearchClient(
        endpoint=f"https://{AZURE_SEARCH_SERVICE}.search.windows.net",
        index_name=AZURE_SEARCH_INDEX,
        credential=credential) 
    query_vector = openai.Embedding.create(engine=AZURE_OPENAI_EMB_DEPLOYMENT, input=prompt)["data"][0]["embedding"]
    filter = "category eq '{}'".format(exclude_category.replace("'", "''")) if exclude_category else None
    r = search_client.search(prompt, 
                            filter=filter,
                            query_type=QueryType.SIMPLE, 
                            query_language="en-us", 
                            query_speller="lexicon", 
                            semantic_configuration_name="default", 
                            top=10,
                            vector=query_vector if query_vector else None, 
                            top_k=50 if query_vector else None,
                            vector_fields="embedding" if query_vector else None
                            )
    results = [doc[KB_FIELDS_SOURCEFILE] + ": " + doc[KB_FIELDS_CONTENT].replace("\n", "").replace("\r", "") for doc in r]
    sources = list(set([source.split(':')[0] for source in results]))
    return "\n".join(sources)

#This function used to create a URL with SAS to download a file from Azure blob storage
def generate_blob_download_url(blob_name, expiration_minutes=15):
        from azure.storage.blob import BlobServiceClient, generate_blob_sas, BlobSasPermissions
        from datetime import datetime, timedelta
        account_name = client_kv.get_secret("alex-nie-storage-account").value
        container_name = client_kv.get_secret("alex-nie-container-2").value
        account_key = client_kv.get_secret("alex-nie-storage-key").value

        blob_service_client = BlobServiceClient(account_url=f"https://{account_name}.blob.core.windows.net", credential=account_key)

        # Get a reference to the blob
        blob_client = blob_service_client.get_blob_client(container=container_name, blob=blob_name)

        # Generate a SAS token with read permission and expiration time
        sas_token = generate_blob_sas(
            blob_client.account_name,
            container_name,
            blob_name,
            account_key=account_key,
            permission=BlobSasPermissions(read=True),
            expiry=datetime.utcnow() + timedelta(minutes=expiration_minutes)
        )
        # Construct the download URL with SAS token
        download_url = blob_client.url + "?" + sas_token
        return download_url

#This function used to extract a URL from an external source
def extract_url(input_string):
    url_pattern = re.compile(r'https?://\S+')
    match = url_pattern.search(input_string)
    if match:
        url = match.group()
        return {'url': url, 'file_name': str(input_string).replace(url, '')}
    
# Function to create a Word document in memory
def create_word_document_in_memory(text):
    doc = Document()
    doc.add_paragraph(text)
    # Save the document to a BytesIO stream
    stream = BytesIO()
    doc.save(stream)
    stream.seek(0)  # Reset the stream position to the beginning
    return stream

# Function to upload a stream to Azure Blob Storage
def upload_stream_to_blob_storage(container_name, stream, blob_name, Created_at, user_name, session_id):
    blob_service_client = BlobServiceClient.from_connection_string(connection_string)
    container_client = blob_service_client.get_container_client(container_name)
    Created_date = Created_at.split(' ')[0]
    blob_name = f"{user_name}/{Created_date}/{session_id}/{blob_name}"
    container_client.upload_blob(name=blob_name, data=stream)

# Function to extract the engage prompts from the 5Es excel file
def extract_engage_prompt(blob_name, prompt_type):
    # Replace these variables with your actual values
    # Create a BlobServiceClient
    blob_service_client = BlobServiceClient(account_url=f"https://{storage_account_name}.blob.core.windows.net", credential=storage_account_key)
    # Get a reference to the container
    container_name = containers_storage_account('alex-nie-container-2')
    container_client = blob_service_client.get_container_client(container_name)
    # Get a reference to the blob
    blob_client = container_client.get_blob_client(blob_name)
    # Download blob content into a BytesIO object
    blob_content = blob_client.download_blob().readall()
    blob_stream = BytesIO(blob_content)
    # Read Excel file into a pandas DataFrame
    df = pd.read_excel(blob_stream, engine='openpyxl')

    # Now you can work with the DataFrame as needed
    prompts = df[f'{prompt_type}'].tolist()
    for prompt in prompts:
        if str(prompt) != 'nan':
            return prompt
        else:
            break
