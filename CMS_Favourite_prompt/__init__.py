import logging
import json
import azure.functions as func
from azure.cosmos import CosmosClient
from datetime import datetime, timedelta
from getConfig import get_db_config

def main(req: func.HttpRequest) -> func.HttpResponse:
    logging.info('Python HTTP trigger function processed a request.')
    
    try:
        req_body = req.get_json()
    except:
        req_body = '{}'

    http_method = req.method

    config = get_db_config()
    # config = get_db_config_local()

    client = CosmosClient(config['endpoint'], config['key'])
    database = client.get_database_client(config['database_name'])
    container_favourite_prompt = database.get_container_client(config['container_name_favourite_prompt'])

    if http_method == 'GET':

        user_email = req.params.get('user_email')
        start_date = req.params.get('startDate')
        end_date = req.params.get('endDate')

        query = f'''
            SELECT
                c.favourite_prompt_id,
                c.user_email,
                c.prompt
            FROM c
            WHERE
                1 = 1
        '''

        if user_email:
            query = query + f" AND c.user_email = '{user_email}'"

        if start_date:
            start_date_convert = datetime.strptime(start_date, '%d-%m-%Y')
            query = query + f" AND NOT(c.Created_at < '{start_date_convert}')"

        if end_date:
            end_date_convert = datetime.strptime(end_date, '%d-%m-%Y') + timedelta(days=1)
            query = query + f" AND NOT(c.Created_at > '{end_date_convert}')"

        results = list(container_favourite_prompt.query_items(query, enable_cross_partition_query=True))
        favourite_prompt = []
        for i in range(len(results)):
            result = results[i]
            favourite_prompt.append(result)

        return func.HttpResponse(
            body = json.dumps(favourite_prompt)
        )

    elif http_method == 'POST':

        user_email = req_body.get("user_email")
        prompt = req_body.get("prompt")

        query = "SELECT Top 1 * FROM c Order by c.favourite_prompt_id desc"
        result_favourite_prompt = list(container_favourite_prompt.query_items(query, enable_cross_partition_query=True))

        if len(result_favourite_prompt) == 0:
            next_id = 1
        else:
            max_id = result_favourite_prompt[0]["favourite_prompt_id"]
            next_id = max_id + 1

        Created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        modified_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        data_item = {
            "id": f"Favourite Prompt - {next_id}",
            "favourite_prompt_id": next_id,  # The ID should be unique within the container
            "user_email": user_email,
            "prompt": prompt,
            "Created_at": Created_at,
            "Modified_at": modified_at
        }
        created_favourite_prompt = container_favourite_prompt.create_item(data_item)

        return func.HttpResponse(
            json.dumps(
                {
                    "favourite_prompt_id": next_id,
                    "user_email": user_email,
                    "prompt": prompt
                }
            )
        )

    elif http_method == 'DELETE':

        delete_favourite_prompt_id = req_body.get('favourite_prompt_id')
        query = f"SELECT * FROM c Where c.favourite_prompt_id = {delete_favourite_prompt_id}"

        result_fp = list(container_favourite_prompt.query_items(query, enable_cross_partition_query=True))
        result = result_fp[0]
        partition_key = result['favourite_prompt_id']
        
        items = list(container_favourite_prompt.query_items(query, enable_cross_partition_query=True))
        container_favourite_prompt.delete_item(items[0], partition_key=partition_key)

        return func.HttpResponse('{"Status":"Success Delete"}')

    elif http_method == 'PATCH':
        
        edit_favourite_prompt_id = req_body.get("favourite_prompt_id")
        new_user_email = req_body.get("user_email")
        new_prompt = req_body.get("prompt")
        
        query = f"SELECT * FROM c Where c.favourite_prompt_id = {edit_favourite_prompt_id}"
        result_prompt = list(container_favourite_prompt.query_items(query, enable_cross_partition_query=True))

        result = result_prompt[0]
        partition_key = result['favourite_prompt_id']
        item_id = result['id']
        item = container_favourite_prompt.read_item(item_id, partition_key=partition_key)

        modified_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        item['user_email'] = new_user_email
        item['prompt'] = new_prompt
        item['Modified_at'] = modified_at
        
        # UPDATE LATER BASED ON SSO AUTHORISATION TOKEN
        # item['Updated_user'] = ''
        
        # Replace the existing document with the updated one
        container_favourite_prompt.upsert_item(item)

        return func.HttpResponse('{"Status":"Success Update"}')