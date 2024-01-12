from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient

def get_db_config():
    keyvault_url = "https://nie-alex-key-vault-prod.vault.azure.net/"
    credential = DefaultAzureCredential()
    client_kv = SecretClient(vault_url=keyvault_url, credential=credential)

    return {
        'database_name' : client_kv.get_secret("alex-nie-cosmosdb-database").value,
        'container_name_category' : client_kv.get_secret("alex-nie-cosmosdb-category").value,
        'container_name_prompt_category' : client_kv.get_secret("nie-alex-cosmos-prompt-category").value,
        'container_name_favourite_prompt' : client_kv.get_secret("nie-alex-cosmos-favourite-prompt").value,
        'container_name_user' : client_kv.get_secret("nie-alex-cosmos-user").value,
        'container_name_conversation' : client_kv.get_secret("alex-nie-cosmosdb-container-conversation").value,
        'container_name_files' : client_kv.get_secret("nie-alex-cosmosdb-uploaded-files").value,
        'key' : client_kv.get_secret("alex-nie-cosmosdb-key").value,
        'endpoint' : f"https://{client_kv.get_secret('alex-nie-cosmosdb-name').value}.documents.azure.com/",
        'client_id' : client_kv.get_secret("alex-nie-client-id").value,
        'client_secret' : client_kv.get_secret("alex-nie-client-secret").value
    }