import logging
import json
import azure.functions as func
from azure.cosmos import CosmosClient
from datetime import datetime, timedelta
from getConfig import get_db_config
import math

def main(req: func.HttpRequest) -> func.HttpResponse:
    logging.info('Python HTTP trigger function processed a request.')

    http_method = req.method

    config = get_db_config()
    # config = get_db_config_local()

    client = CosmosClient(config['endpoint'], config['key'])
    database = client.get_database_client(config['database_name'])
    container_conversation = database.get_container_client(config['container_name_conversation'])
    
    if http_method == 'GET':

        user_email = req.params.get("user_email")
        session_id = req.params.get("session_id")
        # activity = req.params.get("activity")
        start_date = req.params.get("startDate")
        end_date = req.params.get("endDate")
        is_detailed = req.params.get("is_detailed")
        persona = req.params.get("persona")

        current_pages = int(req.params.get("page_number") or 1)
        content_per_pages = int(req.params.get("content_per_pages") or 20)

        if is_detailed == "true":
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
        else:
            query = f'''
                SELECT
                    c.User as User_Email,
                    c.Persona,
                    c.Session_id,
                    c.Session_start,
                    c.Session_end
                FROM c
                WHERE
                    1 = 1
            '''

        if persona:
            query = query + f" AND c.Persona = '{persona}'"

        if user_email:
            query = query + f" AND c.User = '{user_email}'"

        # if activity:
        #     query = query + f" AND c.Activity = '{activity}'"

        if session_id:
            query = query + f" AND c.Session_id = '{session_id}'"

        if start_date:
            start_date_convert = datetime.strptime(start_date, '%d-%m-%Y')
            query = query + f" AND NOT(c.Session_start < '{start_date_convert}')"

        if end_date:
            end_date_convert = datetime.strptime(end_date, '%d-%m-%Y') + timedelta(days=1)
            query = query + f" AND NOT(c.Session_start > '{end_date_convert}')"
        
        query = query + " Order by c.Conversation_id DESC"

        # Get total pages
        results = list(container_conversation.query_items(query, enable_cross_partition_query=True))
        total_id = len(results)
        total_pages = math.ceil(total_id / content_per_pages)

        # 2023-12-15 QUANG
        query = query + f" OFFSET {(current_pages-1)*content_per_pages} LIMIT {content_per_pages}"

        results = list(container_conversation.query_items(query, enable_cross_partition_query=True))
        
        conversation = []
        for i in range(len(results)):
            result = results[i]
            conversation.append(result)

        return func.HttpResponse(
            body = json.dumps({"conversation info": conversation, "total_pages": total_pages}), mimetype="application/json", )