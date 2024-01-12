import logging
import json
import azure.functions as func
from azure.cosmos import CosmosClient
from datetime import datetime
import binascii, os
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
    container_user = database.get_container_client(config['container_name_user'])

    if http_method == 'POST':

        user_name = req_body.get("username")
        password = req_body.get("password")

        check_query = f"SELECT * FROM c Where c.User_info.username = '{user_name}' AND c.User_info.password = '{password}'"
        result_check = list(container_user.query_items(check_query, enable_cross_partition_query=True))
        
        if len(result_check) == 0:
            return func.HttpResponse('{"Status":"User Not Found. Please Try logging again"}')

        result = result_check[0]
        partition_key = result['User_id']
        item_id = result['id']
        item = container_user.read_item(item_id, partition_key=partition_key)
        item['User_info']['token'] = binascii.hexlify(os.urandom(20)).decode()

        container_user.upsert_item(item)

        query = f'''
        SELECT VALUE {{
            user_id: c.User_id,
            username: c.User_info.username,
            password: c.User_info.password,
            name: c.User_info.name,
            email: c.User_info.email,
            token: c.User_info.token
        }}
        FROM c
        Where
            c.User_info.username = '{user_name}'
            AND c.User_info.password = '{password}'
            AND c.User_type = 'Admin'
        '''
        results = list(container_user.query_items(query, enable_cross_partition_query=True))
        return func.HttpResponse(body = json.dumps(results))