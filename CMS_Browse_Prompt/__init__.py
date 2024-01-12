import logging
import json
import azure.functions as func
from azure.cosmos import CosmosClient
from datetime import datetime
from getConfig import get_db_config

# Cosmos DB information
config = get_db_config()
client = CosmosClient(config['endpoint'], config['key'])
database = client.get_database_client(config['database_name'])
container_prompt_category = database.get_container_client(config['container_name_prompt_category'])
container_category = database.get_container_client(config['container_name_category'])

def main(req: func.HttpRequest) -> func.HttpResponse:
    logging.info('Python HTTP trigger function processed a request.')
    
    http_method = req.method
    def update_prompt(User_email):
        query_category = f"Select c.Category_id, c.Category from c"
        results_category = list(container_category.query_items(query_category, enable_cross_partition_query=True))
        query_prompt_category = f"SELECT * FROM c"
        results_prompt_category = list(container_prompt_category.query_items(query_prompt_category, enable_cross_partition_query=True))
        len_result = len(results_prompt_category)
        for i in range(len(results_category)):
            result = results_category[i]
            category_id = result['Category_id']
            category = result['Category']
            for j in range(len_result):
                result_prompt = results_prompt_category[j]
                category_prompt = result_prompt['Category']
                item_id = result_prompt['id']
                partition_key = result_prompt['Prompt_id']
                for x in range(len(category_prompt)):
                    Category_id = category_prompt[x]['Category_id']
                    Category_prompt = category_prompt[x]['Category']
                    if Category_id == category_id:
                        item = container_prompt_category.read_item(item_id, partition_key=partition_key)
                        # Update the "Category" field
                        new_category = category
                        # new_category_id = category_id
                        modified_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        item['Category'][x]['Category'] = new_category
                        # item['Category'][x]['Category_id'] = new_category_id
                        item['Modified_at'] = modified_at
                        item['Updated_user'] = User_email
                        # Replace the existing document with the updated one
                        container_prompt_category.upsert_item(item)
    if http_method == 'PATCH':
        # Handle PATCH request
        req_body = req.get_json()
        edit_value = req_body.get("edit_value")
        edit_prompt_id = edit_value['id']
        user_email = edit_value['User_email']
        query = f"SELECT * FROM c Where c.Prompt_id = {edit_prompt_id}"
        results_prompt_category = list(container_prompt_category.query_items(query, enable_cross_partition_query=True))
        result = results_prompt_category[0]
        partition_key = result['Prompt_id']
        item_id = result['id']
        item = container_prompt_category.read_item(item_id, partition_key=partition_key)
        # Update the "Category" field
        new_prompt = edit_value['Prompt']
        new_category = edit_value['Category']
        modified_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        item['Category'] = new_category
        item['Prompt'] = new_prompt
        item['Modified_at'] = modified_at
        item['Updated_user'] = user_email
        # Replace the existing document with the updated one
        container_prompt_category.upsert_item(item)
        update_prompt(user_email)
        return func.HttpResponse( f"The Prompt with ID is {partition_key} has been updated successfully!" )
    elif http_method == 'DELETE':
        # Handle DELETE request
        req_body = req.get_json()
        delete_value = req_body.get("delete_value")
        delete_prompt_id = delete_value['id']
        query = f"SELECT * FROM c Where c.Prompt_id = {delete_prompt_id}"
        results_prompt_category = list(container_prompt_category.query_items(query, enable_cross_partition_query=True))
        result = results_prompt_category[0]
        partition_key = result['Prompt_id']
        items = list(container_prompt_category.query_items(query, enable_cross_partition_query=True))
        container_prompt_category.delete_item(items[0], partition_key=partition_key)
        return func.HttpResponse( f"The Prompt with ID is {partition_key} has been deleted successfully!" )
    elif http_method == 'POST':
        # Handle POST request
        req_body = req.get_json()
        create_value = req_body.get("create_value")
        query = "SELECT Top 1 * FROM c Order by c.Prompt_id desc"
        results_prompt_category = list(container_prompt_category.query_items(query, enable_cross_partition_query=True))
        Prompt = create_value['Prompt']
        Category = create_value['Category']
        Persona = create_value['Persona']
        if len(results_prompt_category) == 0:
            next_id = 1
        else:
            max_id = results_prompt_category[0]["Prompt_id"]
            next_id = max_id + 1
        Created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        modified_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        data_item = {
            "id": f"Prompt - {next_id}",
            "Prompt_id": next_id,  # The ID should be unique within the container
            "Prompt": Prompt,
            "Category": Category,
            "Created_at": Created_at,
            "Modified_at": modified_at,
            "Persona": Persona
            # Add more properties as needed
        }
        container_prompt_category.create_item(data_item)
        return func.HttpResponse( json.dumps( f"The new Prompt with ID is {next_id} has been created successfully!" ) )
    elif http_method == 'GET':
        category_ids = req.params.get("category_ids")
        if not category_ids:
            query = f"SELECT * FROM c"
            results = list(container_prompt_category.query_items(query, enable_cross_partition_query=True))
            prompt_list = results
            return func.HttpResponse( json.dumps({"prompt_list": prompt_list}), mimetype="application/json", )
        else:
            category_ids_list = category_ids.split(',')
            if len(category_ids_list) == 1:
                prompt_list = []
                query = f"SELECT * FROM c"
                results = list(container_prompt_category.query_items(query, enable_cross_partition_query=True))
                prompt_category = [(id['Prompt_id'], [id['Category_id'] for id in id['Category']]) for id in results]
                prompt_id_list = []
                id = int(category_ids)
                for result in prompt_category:
                    if id in result[1]:
                        prompt_id = result[0]
                        prompt_id_list.append(prompt_id)
                        if len(prompt_id_list) == 1:
                            prompt_id_final = '(' + str(prompt_id_list[0]) + ')'
                        else:
                            prompt_id_final = tuple(set(prompt_id_list))
                query = f"SELECT * FROM c where c.Prompt_id in {prompt_id_final}"
                results = list(container_prompt_category.query_items(query, enable_cross_partition_query=True))
                prompt_list = results
                return func.HttpResponse( json.dumps({"prompt_list": prompt_list}), mimetype="application/json", )
            else:
                category_ids = category_ids.split(',')
                prompt_list = []
                query = f"SELECT * FROM c"
                results = list(container_prompt_category.query_items(query, enable_cross_partition_query=True))
                prompt_category = [(id['Prompt_id'], [id['Category_id'] for id in id['Category']]) for id in results]
                prompt_id_list = []
                for id in category_ids:
                    id = int(id)
                    for result in prompt_category:
                        if id in result[1]:
                            prompt_id = result[0]
                            prompt_id_list.append(prompt_id)
                            prompt_id_final = tuple(set(prompt_id_list))
                query = f"SELECT * FROM c where c.Prompt_id in {prompt_id_final}"
                results = list(container_prompt_category.query_items(query, enable_cross_partition_query=True))
                prompt_list = results
                return func.HttpResponse( json.dumps({"prompt_list": prompt_list}), mimetype="application/json", )
        
