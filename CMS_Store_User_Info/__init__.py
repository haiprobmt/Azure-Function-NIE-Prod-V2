import logging
import azure.functions as func
import json
from azure.cosmos import CosmosClient
from datetime import datetime
from getConfig import get_db_config

def main(req: func.HttpRequest) -> func.HttpResponse:
    logging.info('Python HTTP trigger function processed a request.')

    req_body = req.get_json()
    user_data = req_body.get("user_data")
    persona = req_body.get("persona")
    custom_instruction = req_body.get("custom_instruction")
    is_pass_onboarding = req_body.get("is_pass_onboarding")
    is_consent = req_body.get('is_consent')
    if(is_consent is None):
        is_consent = False

    # Cosmos DB information
    config = get_db_config()
    client = CosmosClient(config['endpoint'], config['key'])
    database = client.get_database_client(config['database_name'])
    container = database.get_container_client(config['container_name_user'])
    
    if not user_data:
        try:
            req_body = req.get_json()
        except ValueError:
            pass
        else:
            user_data = req_body.get('user_data')
    returned_user_info = []
    # Store user infor into CosmosDB
    query_column = 'mail'
    user_email = user_data[f'{query_column}']
    # print(user_email)
    query = f"SELECT Top 1 * FROM c where c.User_info.{query_column} = '{user_email}'"
    # Execute the query
    # try:
    results = list(container.query_items(query, enable_cross_partition_query=True))
    if len(results) > 0:
        user_email_db = results[0]['User_info'][f'{query_column}']
        if user_email == user_email_db:
            print('This user already exists in the database!')
            result = results[0]
            partition_key = result['User_id']
            item_id = result['id']
            item = container.read_item(item_id, partition_key=partition_key)
            if persona is not None:
                # query = f"SELECT TOP 1 * FROM c WHERE c.User_info.{query_column} = '{user_email}'"
                # results = list(container.query_items(query, enable_cross_partition_query=True))
                # returned_user_info.append({
                #     "User_info": user_data,
                #     "Persona": results[0]['Persona'],
                #     "custom_instruction": results[0]['Custom_instruction'],
                #     "is_pass_onboarding": results[0]['is_pass_onboarding'],
                #     "Created_at": results[0]['Created_at'],
                #     "Modified_at": results[0]['Modified_at']
                # })
                new_user_data = user_data
                new_persona = persona
                new_Custom_instruction = custom_instruction
                new_is_pass_onboarding = is_pass_onboarding
                new_is_consent = is_consent
                modified_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                item['User_info'] = new_user_data
                item['Persona'] = new_persona
                item['Custom_instruction'] = new_Custom_instruction
                item['is_pass_onboarding'] = new_is_pass_onboarding
                item['Modified_at'] = modified_at
                item['Updated_user'] = user_email
                item['is_consent'] = new_is_consent
                container.upsert_item(item)
        else:
            max_id = results[0]["User_id"]
            next_id = max_id + 1
            Created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            modified_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            data_item = {
                "id": f"User - {next_id}",
                "User_id": next_id,  # The ID should be unique within the container
                "User_info": user_data,
                "Persona": persona,
                "Custom_instruction": custom_instruction,
                "is_pass_onboarding": is_pass_onboarding,
                "Created_at": Created_at,
                "Modified_at": modified_at,
                "is_consent":is_consent
                # Add more properties as needed
            }
            container.upsert_item(data_item)
    else:
        query = f"SELECT TOP 1 * FROM c order by c.User_id desc"
        results = list(container.query_items(query, enable_cross_partition_query=True))
        if len(results) == 0:
            next_id = 1
        else:
            max_id = results[0]["User_id"]
            next_id = max_id + 1
        Created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        modified_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        data_item = {
            "id": f"User - {next_id}",
            "User_id": next_id,  # The ID should be unique within the container
            "User_info": user_data,
            "Persona": persona,
            "Custom_instruction": custom_instruction,
            "is_pass_onboarding": is_pass_onboarding,
            "Created_at": Created_at,
            "Modified_at": modified_at,
            "is_consent":is_consent
            # Add more properties as needed
        }
        container.create_item(data_item)

    query = f"SELECT TOP 1 * FROM c WHERE c.User_info.{query_column} = '{user_email}'"
    results = list(container.query_items(query, enable_cross_partition_query=True))
    try:
        returned_user_info.append({
        "User_info": user_data,
        "Persona": results[0]['Persona'],
        "custom_instruction": results[0]['Custom_instruction'],
        "is_pass_onboarding": results[0]['is_pass_onboarding'],
        "Created_at": results[0]['Created_at'],
        "Modified_at": results[0]['Modified_at'],
        "is_consent":results[0]["is_consent"]
    })
    except:
        results[0]["is_consent"] = False
        returned_user_info.append({
            "User_info": user_data,
            "Persona": results[0]['Persona'],
            "custom_instruction": results[0]['Custom_instruction'],
            "is_pass_onboarding": results[0]['is_pass_onboarding'],
            "Created_at": results[0]['Created_at'],
            "Modified_at": results[0]['Modified_at'],
            "is_consent":results[0]["is_consent"]
        }) 
    return func.HttpResponse( json.dumps({"user_information": returned_user_info}) )