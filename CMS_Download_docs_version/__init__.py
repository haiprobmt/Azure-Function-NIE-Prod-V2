import logging
import azure.functions as func
from azure.keyvault.secrets import SecretClient
from azure.storage.blob import BlobServiceClient
from azure.identity import DefaultAzureCredential
import zipfile
import io

# Replace these values with your Azure Key Vault URL
keyvault_url = "https://nie-alex-key-vault-prod.vault.azure.net/"
# Create a SecretClient using the DefaultAzureCredential
credential = DefaultAzureCredential()
client_kv = SecretClient(vault_url=keyvault_url, credential=credential)

connection_string = client_kv.get_secret("alex-nie-storage-connection-string").value
container_name = client_kv.get_secret("alex-nie-container-docs").value

def main(req: func.HttpRequest) -> func.HttpResponse:
    logging.info('Python HTTP trigger function processed a request.')

    session_id = req.params.get('session_id')
    if not session_id:
        try:
            req_body = req.get_json()
        except ValueError:
            pass
        else:
            session_id = req_body.get('session_id')

    if session_id:   
        # Create a BlobServiceClient
        blob_service_client = BlobServiceClient.from_connection_string(connection_string)
    
        # Get the container
        container_client = blob_service_client.get_container_client(container_name)
    
        # List blobs in the container
        blobs = container_client.list_blobs()
    
        # Create a BytesIO buffer for the zip file
        zip_buffer = io.BytesIO()

        list_created_at = []
        download_list = []
        # Create a BlobServiceClient
        blob_service_client = BlobServiceClient.from_connection_string(connection_string)
        # Get the container
        container_client = blob_service_client.get_container_client(container_name)
        # List blobs in the container
        blobs = container_client.list_blobs()
        for blob in blobs:    
            stored_session_id = blob.name.split('/')[2]
            if stored_session_id == session_id:
                stored_user_name = blob.name.split('/')[0]
                stored_created_at = int(blob.name.split('/')[-1].split('.docx')[0][-8:].replace('_',''))
                list_created_at.append(stored_created_at)
                download_list.append(blob.name)
        list_final = list(zip(download_list, list_created_at))
        sorted_data = sorted(list_final, key=lambda x: x[1], reverse=True)

        blob_list = [blob_name[0] for blob_name in sorted_data]
    
        # Create a ZipFile object
        with zipfile.ZipFile(zip_buffer, 'a', zipfile.ZIP_DEFLATED, False) as zip_file:
            for blob in blob_list:
                stored_session_id = blob.split('/')[2]
                if stored_session_id == session_id:
                    stored_user_name = blob.split('/')[0]
                    stored_created_at = blob.split('/')[-1]
                    # Download the blob data
                    blob_data = container_client.get_blob_client(blob).download_blob().readall()                      
                    # Add the blob data to the zip file
                    zip_file.writestr(blob, blob_data)
            
            file_name = stored_user_name + '_' + session_id
            # Set the appropriate headers for the HTTP response
            headers = {
                        "Content-Disposition": f"attachment; filename={file_name}.zip",
                        "Content-Type": "application/zip",
                    }
        
            # Seek to the beginning of the zip buffer
        zip_buffer.seek(0)
        
        # Return the HTTP response with the zip file
        return func.HttpResponse(zip_buffer.read(), status_code=200, headers=headers)
    else:
        return func.HttpResponse(
             "This HTTP triggered function executed successfully. Pass a name in the query string or in the request body for a personalized response.",
             status_code=200
        )
