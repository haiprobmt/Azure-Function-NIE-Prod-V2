import logging
import json
import azure.functions as func
from azure.cosmos import CosmosClient
import json
from azure.cosmos import CosmosClient
from getConfig import get_db_config

def main(req: func.HttpRequest) -> func.HttpResponse:
    logging.info('Python HTTP trigger function processed a request.')

    category = req.params.get('category')
    type = req.params.get('type')
    user_email = req.params.get('user_email')
    
    if not user_email:
        try:
            req_body = req.get_json()
        except:
            req_body = '{}'
    if user_email:
        # Cosmos DB information
        config = get_db_config()
        client = CosmosClient(config['endpoint'], config['key'])
        database = client.get_database_client(config['database_name'])
        container = database.get_container_client(config['container_name_files'])

        query = f"SELECT Top 1 * FROM c where c.Uploaded_by = '{user_email}' and c.Category = '{category}' and c.Type = '{type}'"
            
        # Execute the query
        results = list(container.query_items(query, enable_cross_partition_query=True))
        file_info = []
        for i in range(len(results)):
            result = results[i]
            file_info.append(result)
        
        return func.HttpResponse( json.dumps({'response': file_info}), mimetype="application/json",)
    else:
        return func.HttpResponse(
                "This HTTP triggered function executed successfully. Pass a name in the query string or in the request body for a personalized response.",
                status_code=200
        )
