import logging
import requests
import azure.functions as func
from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient
import requests

# Replace these values with your Azure Key Vault URL
keyvault_url = "https://nie-alex-key-vault-prod.vault.azure.net/"
# Create a SecretClient using the DefaultAzureCredential
credential = DefaultAzureCredential()
client_kv = SecretClient(vault_url=keyvault_url, credential=credential)
# Replace these with your own values, either in environment variables or directly here
client_id = client_kv.get_secret("alex-nie-client-id").value
client_secret = client_kv.get_secret("alex-nie-client-secret").value

def main(req: func.HttpRequest) -> func.HttpResponse:
    logging.info('Python HTTP trigger function processed a request.')

    assertion = req.params.get('assertion')
    
    if not assertion:
        try:
            req_body = req.get_json()
        except ValueError:
            pass
        else:
            assertion = req_body.get('assertion')
    if assertion:
        def get_microsoft_oauth2_token(client_id, client_secret, assertion):
            token_url = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
            token_data = {
                "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                "client_id": client_id,
                "client_secret": client_secret,
                "assertion": assertion,
                "scope": "User.Read",
                "requested_token_use": "on_behalf_of"
            }

            response = requests.post(token_url, data=token_data)
            if response.status_code == 200:
                token_info = response.json()
                access_token = token_info["access_token"]
                return access_token
            else:
                print("Error getting access token:", response.text)
                return None

        access_token = get_microsoft_oauth2_token(client_id, client_secret, assertion)
        if access_token:
            return func.HttpResponse(access_token)
    else:
        return func.HttpResponse(
             "This HTTP triggered function executed successfully. Pass a name in the query string or in the request body for a personalized response.",
             status_code=200
        )
