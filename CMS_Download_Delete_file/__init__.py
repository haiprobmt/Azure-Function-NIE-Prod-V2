import logging
import azure.functions as func
from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient
from datetime import datetime
from azure.storage.blob import BlobServiceClient, generate_blob_sas, BlobSasPermissions
from datetime import datetime, timedelta
import json
import requests
from azure.cosmos import CosmosClient
from getConfig import get_db_config

# Replace these values with your Azure Key Vault URL
keyvault_url = "https://nie-alex-key-vault-prod.vault.azure.net/"
# Create a SecretClient using the DefaultAzureCredential
credential = DefaultAzureCredential()
client_kv = SecretClient(vault_url=keyvault_url, credential=credential)

AZURE_SEARCH_SERVICE = client_kv.get_secret("alex-nie-search-service").value
AZURE_SEARCH_INDEX = client_kv.get_secret("alex-nie-search-index").value
AZURE_SEARCH_API_KEY = client_kv.get_secret("alex-nie-search-api-key").value

#Storage account infomation
connection_string = client_kv.get_secret("alex-nie-storage-connection-string").value
account_name = client_kv.get_secret("alex-nie-storage-account").value
account_key = client_kv.get_secret("alex-nie-storage-key").value
container_name_sa = client_kv.get_secret("alex-nie-storage-container").value
container_name_sa_2 = client_kv.get_secret("alex-nie-container-2").value

#Cosmos DB infomation
config = get_db_config()
client = CosmosClient(config['endpoint'], config['key'])
database = client.get_database_client(config['database_name'])
container_cosmos = database.get_container_client(config['container_name_files'])


def main(req: func.HttpRequest) -> func.HttpResponse:
    logging.info('Python HTTP trigger function processed a request.')
    
    req_method = req.method
    blob_id = req.params.get('blob_id')

    if req_method == 'GET':
        if not blob_id:
            # Cosmos DB information
            query = "SELECT * FROM c"
            results = list(container_cosmos.query_items(query, enable_cross_partition_query=True))
            return func.HttpResponse(json.dumps({"File list": results}), mimetype="application/json",)

        else:
            query = f"SELECT c.File_name FROM c where c.File_id = {blob_id}"
            results = list(container_cosmos.query_items(query, enable_cross_partition_query=True))
            blob_name = results[0]['File_name']
            def generate_blob_download_url(account_name, container_name, blob_name, account_key, expiration_minutes=15):
                # Create a BlobServiceClient
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
            
            # blob_name = "NIE Knowledge Base_5Cs.pdf"

            download_url = generate_blob_download_url(account_name = account_name, container_name = container_name_sa_2, blob_name = blob_name, account_key = account_key)
            return func.HttpResponse(json.dumps({"Download URL": download_url}), mimetype="application/json",)
    if req_method == 'DELETE':
        if not blob_id:
            return func.HttpResponse(json.dumps({f"Response": f"There is no file to delete, please select the file!"}), mimetype="application/json",)           
        else: 
            query = f"SELECT c.File_name FROM c where c.File_id = {blob_id}"
            results = list(container_cosmos.query_items(query, enable_cross_partition_query=True))
            blob_name = results[0]['File_name']   
            # Delete the document from Index

            # Define the search API endpoint
            api_version = "2023-07-01-Preview"
            search = "*"
            filter = f"sourcefile eq '{blob_name}'"

            # Define the API endpoints for search and delete
            search_endpoint = f"https://{AZURE_SEARCH_SERVICE}.search.windows.net/indexes/{AZURE_SEARCH_INDEX}/docs?api-version={api_version}&search={search}&%24filter={filter}&%24select=id"
            delete_endpoint = f"https://{AZURE_SEARCH_SERVICE}.search.windows.net/indexes/{AZURE_SEARCH_INDEX}/docs/index?api-version={api_version}"

            # Make the GET request to the search API
            headers = {
                "api-key": AZURE_SEARCH_API_KEY
            }

            response = requests.get(search_endpoint, headers=headers)
            # Check if the request was successful (status code 200)
            if response.status_code == 200:
                # Parse the response JSON
                search_results = response.json()

                # Extract the 'id' values from the search results
                id_list = [result['id'] for result in search_results['value']]

                # Prepare the request body for deleting documents
                request_body = {
                    "value": [{"@search.action": "delete", "id": doc_id} for doc_id in id_list]
                }

                # Make the POST request to delete documents
                delete_response = requests.post(delete_endpoint, headers=headers, json=request_body)

                # Check if the delete request was successful (status code 200)
                if delete_response.status_code == 200:
                    print("Documents deleted successfully.")
                else:
                    print(f"Error deleting documents: {delete_response.status_code}")
            else:
                print(f"Error: Request failed with status code {response.status_code}")
            
            # Delete the document from blob storage
            try:
                # Delete chunked files from blob storage

                # Create a BlobServiceClient using the connection string
                blob_service_client = BlobServiceClient.from_connection_string(connection_string)

                # Create a ContainerClient
                container_client = blob_service_client.get_container_client(container_name_sa)

                # List blobs in the container
                blob_list = container_client.list_blobs()

                # Iterate through the blobs and delete PDF files
                for blob in blob_list:
                    delete_blob_name = blob.name                 
                    if delete_blob_name.startswith(blob_name.split(".pdf")[0]):
                        blob_client = container_client.get_blob_client(delete_blob_name)
                        blob_client.delete_blob()
                        print(f"Deleted chunked PDF blobs: {delete_blob_name}")

                # Delete main files from blob storage
                
                # Create a BlobServiceClient using the connection string
                blob_service_client = BlobServiceClient.from_connection_string(connection_string)

                # Create a ContainerClient
                container_client = blob_service_client.get_container_client(container_name_sa_2)

                # List blobs in the container
                blob_list = container_client.list_blobs()

                # Iterate through the blobs and delete PDF files
                for blob in blob_list:
                    delete_blob_name = blob.name
                    if delete_blob_name == blob_name:
                        blob_client = container_client.get_blob_client(delete_blob_name)
                        blob_client.delete_blob()
                        print(f"Deleted PDF blob: {delete_blob_name}")

                # Delete item file from CosmosDB
                query = f"SELECT top 1 * FROM c Where c.File_name = '{blob_name}'"
                result_category = list(container_cosmos.query_items(query, enable_cross_partition_query=True))

                result = result_category[0]
                partition_key = result['File_id']
                item_id = result['id']
                item = container_cosmos.read_item(item_id, partition_key=partition_key)
                
                # UPDATE LATER BASED ON SSO AUTHORISATION TOKEN
                # item['Updated_user'] = ''
                
                # Replace the existing document with the updated one
                container_cosmos.delete_item(item, partition_key=partition_key)
            except Exception as e:
                print(f"Error: {e}")
            return func.HttpResponse(json.dumps({f"Response": f"The file {blob_name} has been deleted!"}), mimetype="application/json",)
