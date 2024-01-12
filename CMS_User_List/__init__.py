import logging
import azure.functions as func
import json
from azure.cosmos import CosmosClient
from getConfig import get_db_config

def main(req: func.HttpRequest) -> func.HttpResponse:
    logging.info('Python HTTP trigger function processed a request.')
    
    http_method = req.method

     # Cosmos DB information
    config = get_db_config()
    client = CosmosClient(config['endpoint'], config['key'])
    database = client.get_database_client(config['database_name'])
    container = database.get_container_client(config['container_name_user'])

    if http_method == 'GET':
        user_email = req.params.get("user_email")
        query = f"SELECT TOP 1 * FROM c WHERE c.Updated_user = '{user_email}'"
        results = list(container.query_items(query, enable_cross_partition_query=True))
        return func.HttpResponse( json.dumps(results[0]) )