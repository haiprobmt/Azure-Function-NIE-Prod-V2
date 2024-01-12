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

    if http_method == 'GET':

        query = '''
        SELECT VALUE {
            user_id: c.User_id,
            username: c.User_info.username,
            name: c.User_info.name,
            email: c.User_info.email
        }
        FROM c
        WHERE c.User_type = 'Admin'
        '''
        
        # Execute the query
        results = list(container_user.query_items(query, enable_cross_partition_query=True))
        
        return func.HttpResponse(body = json.dumps(results))

    elif http_method == 'PATCH':
        edit_user_id = req_body.get("User_id")
        new_password = req_body.get("password")
        new_name = req_body.get("name")
        new_email = req_body.get("email")
        
        query = f"SELECT * FROM c Where c.User_id = {edit_user_id}"
        result_user = list(container_user.query_items(query, enable_cross_partition_query=True))

        result = result_user[0]
        partition_key = result['User_id']
        item_id = result['id']
        item = container_user.read_item(item_id, partition_key=partition_key)

        modified_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        item['User_info']['password'] = new_password
        item['User_info']['name'] = new_name
        item['User_info']['email'] = new_email
        item['Modified_at'] = modified_at
        
        # UPDATE LATER BASED ON SSO AUTHORISATION TOKEN
        # item['Updated_user'] = ''
        
        # Replace the existing document with the updated one
        container_user.upsert_item(item)

        # UPDATE RELATED PROMPT
        return func.HttpResponse('{"Status":"Success Update"}')

    elif http_method == 'DELETE':

        # 20231107 QUANG - CHECK THE JSON KEY
        delete_user_id = req_body.get('User_id')
        query = f"SELECT * FROM c Where c.User_id = {delete_user_id}"

        result_user = list(container_user.query_items(query, enable_cross_partition_query=True))
        result = result_user[0]
        partition_key = result['User_id']
        
        items = list(container_user.query_items(query, enable_cross_partition_query=True))
        container_user.delete_item(items[0], partition_key=partition_key)

        return func.HttpResponse('{"Status":"Success Delete"}')

    elif http_method == 'POST':
        # Handle POST request
        new_user_name = req_body.get("username")
        new_password = req_body.get("password")
        new_name = req_body.get("name")
        new_email = req_body.get("email")

        # CHECK IF USERNAME ALREADY TAKEN
        check_query = f"SELECT * FROM c Where c.User_info.username = '{new_user_name}'"
        result_check = list(container_user.query_items(check_query, enable_cross_partition_query=True))
        
        if len(result_check) > 0:
            return func.HttpResponse('{"Status":"Failed Addition"}')

        # ADDED USER DATA
        query = "SELECT TOP 1 * FROM c ORDER BY c.User_id DESC"
        result_category = list(container_user.query_items(query, enable_cross_partition_query=True))

        if len(result_category) == 0:
            next_id = 1
        else:
            max_id = result_category[0]["User_id"]
            next_id = max_id + 1

        Created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        modified_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        data_item = {
            "id": f"User - {next_id}",
            "User_id": next_id,  # The ID should be unique within the container
            "User_info": {
                "username": new_user_name,
                "password": new_password,
                "name": new_name,
                "email": new_email,
                "token": binascii.hexlify(os.urandom(20)).decode()
            },
            "User_type": "Admin",
            "Created_at": Created_at,
            "Modified_at": modified_at
        }
        container_user.create_item(data_item)

        return func.HttpResponse('{"Status":"Add succesful"}')