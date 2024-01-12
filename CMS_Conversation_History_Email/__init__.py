import logging
import json
import azure.functions as func
from azure.cosmos import CosmosClient
from datetime import datetime, timedelta
from getConfig import get_db_config


def main(req: func.HttpRequest) -> func.HttpResponse:
    logging.info('Python HTTP trigger function processed a request.')

    config = get_db_config()
    # config = get_db_config_local()

    client = CosmosClient(config['endpoint'], config['key'])
    database = client.get_database_client(config['database_name'])
    container_conversation = database.get_container_client(config['container_name_conversation'])

    is_detailed = req.params.get("is_detailed")

    if is_detailed == "false":
        query = f'''
            SELECT
                Distinct c.User as User_Email
            FROM c
            WHERE
                1 = 1
        ''' 
    else:
        query = f'''
            SELECT
                c.User as User_Email,
                c.Persona,
                c.Session_id,
                c.Session_start,
                c.Session_end,
                c.Chat_conversation
            FROM c
            WHERE
                1 = 1
        '''   
    query = query + " Order by c.Conversation_id DESC"

    results = list(container_conversation.query_items(query, enable_cross_partition_query=True))
    
    conversation = []
    for i in range(len(results)):
        result = results[i]
        conversation.append(result)

    return func.HttpResponse(
        body = json.dumps(conversation)
    )
