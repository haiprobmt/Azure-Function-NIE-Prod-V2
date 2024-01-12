import logging
import json
import azure.functions as func
from azure.cosmos import CosmosClient
from datetime import datetime
from getConfig import get_db_config

def main(req: func.HttpRequest) -> func.HttpResponse:
    logging.info('Python HTTP trigger function processed a request.')
    
    try:
        req_body = req.get_json()
    except:
        req_body = '{}'

    http_method = req.method

    # config = get_db_config()
    config = get_db_config()

    client = CosmosClient(config['endpoint'], config['key'])
    database = client.get_database_client(config['database_name'])
    container_category = database.get_container_client(config['container_name_category'])
    container_prompt_category = database.get_container_client(config['container_name_prompt_category'])

    if http_method == 'GET':

        query = f"SELECT * FROM c"
        
        # Execute the query
        results = list(container_category.query_items(query, enable_cross_partition_query=True))
        category = []
        for i in range(len(results)):
            result = results[i]
            category.append(result)
        
        return func.HttpResponse(
            body = json.dumps(category)
        )
    
    elif http_method == 'POST':

        # Handle POST request
        category = req_body.get("category")
        query = "SELECT Top 1 * FROM c Order by c.Category_id desc"
        result_category = list(container_category.query_items(query, enable_cross_partition_query=True))

        if len(result_category) == 0:
            next_id = 1
        else:
            max_id = result_category[0]["Category_id"]
            next_id = max_id + 1

        Created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        modified_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        data_item = {
            "id": f"Category - {next_id}",
            "Category_id": next_id,  # The ID should be unique within the container
            "Category": category,
            "Created_at": Created_at,
            "Modified_at": modified_at
        }
        created_prompt_category = container_category.create_item(data_item)

        return func.HttpResponse(json.dumps(created_prompt_category))

    elif http_method == 'PATCH':
        
        edit_category_id = req_body.get("Category_id")
        new_category = req_body.get("Category")
        
        query = f"SELECT * FROM c Where c.Category_id = {edit_category_id}"
        result_category = list(container_category.query_items(query, enable_cross_partition_query=True))

        result = result_category[0]
        partition_key = result['Category_id']
        item_id = result['id']
        item = container_category.read_item(item_id, partition_key=partition_key)

        modified_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        item['Category'] = new_category
        item['Modified_at'] = modified_at
        
        # UPDATE LATER BASED ON SSO AUTHORISATION TOKEN
        # item['Updated_user'] = ''
        
        # Replace the existing document with the updated one
        container_category.upsert_item(item)

        # UPDATE RELATED PROMPT
        prompt_query = f'SELECT * FROM c WHERE ARRAY_CONTAINS(ARRAY(SELECT DISTINCT VALUE p.Category_id FROM p IN c.Category), {edit_category_id})'
        result_prompt = list(container_prompt_category.query_items(prompt_query, enable_cross_partition_query=True))
        for result in result_prompt:
            partition_key = result['Prompt_id']
            item_id = result['id']
            item = container_prompt_category.read_item(item_id, partition_key=partition_key)
            for i in item['Category']:
                if i['Category_id'] == edit_category_id:
                    i['Category'] = new_category
            item['Modified_at'] = modified_at
            container_prompt_category.upsert_item(item)

        return func.HttpResponse('{"Status":"Success Update"}')
        
    elif http_method == 'DELETE':

        # 20231107 QUANG - CHECK THE JSON KEY
        delete_category_id = req_body.get('Category_id')
        query = f"SELECT * FROM c Where c.Category_id = {delete_category_id}"

        result_category = list(container_category.query_items(query, enable_cross_partition_query=True))
        result = result_category[0]
        partition_key = result['Category_id']
        
        items = list(container_category.query_items(query, enable_cross_partition_query=True))
        container_category.delete_item(items[0], partition_key=partition_key)

        # UPDATE RELATED PROMPT
        prompt_query = f'SELECT * FROM c WHERE ARRAY_CONTAINS(ARRAY(SELECT DISTINCT VALUE p.Category_id FROM p IN c.Category), {delete_category_id})'
        result_prompt = list(container_prompt_category.query_items(prompt_query, enable_cross_partition_query=True))
        for result in result_prompt:
            partition_key = result['Prompt_id']
            item_id = result['id']
            item = container_prompt_category.read_item(item_id, partition_key=partition_key)
            
            updated_category = []
            
            for i in item['Category']:
                if i['Category_id'] != delete_category_id:
                    updated_category.append(i)

            item['Category'] = updated_category
            item['Modified_at'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            container_prompt_category.upsert_item(item)

        return func.HttpResponse('{"Status":"Success Delete"}')