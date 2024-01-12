import logging
import azure.functions as func
import json
from datetime import datetime
from Functions import (
    send_message,
    cosmos_db_retrieve,
    translate_to_en_uk,
    read_file_blob,
    search
    )

################################################################################
## This function used to refine a highlighted paragraph from the course/lesson ##
################################################################################

def main(req: func.HttpRequest) -> func.HttpResponse:
    logging.info('Python HTTP trigger function processed a request.')

    ## Checking the authorization
    # token = req.headers.get('Authorization')
    # if not validate_token(token):
    #     return func.HttpResponse(status_code = 401, body = 'Not Authorized error!')

    req_body = req.get_json()
    user_email = req_body.get("user_email")
    word_content = req_body.get("word_content")
    highlighted_content = req_body.get("highlighted_content")
    prompt = req_body.get("prompt")
    session_id = req_body.get("session_id")
    activity = req_body.get("activity")
    
    # Execute the query to check the persona
    query = f"SELECT Top 1 * FROM c WHERE c.User_info['mail'] = '{user_email}' Order by c.User_id desc"
    results = list(cosmos_db_retrieve('nie-alex-cosmos-user').query_items(query, enable_cross_partition_query=True))
    persona = results[0]['Persona']
    if persona == 'NIE':
        # Engage prompts
        messages = read_file_blob("engage_NIE.json")
        data_list = json.loads(messages)
        messages = data_list
    elif persona == 'MOE':
         # Engage prompts
        messages = read_file_blob("engage_MOE.json")
        data_list = json.loads(messages)
        messages = data_list
    
    controversial_content = "I'm sorry, you are asking an information related to a sensitive or controversial topics. If you have any other question you would like assistance with, please let me know and I'll be happy to help"
    try:
        controversial_check = f"Please check if the prompt refers to a sensitive or controversial topics: ```{prompt}``` then respond with a Y or N character, with no punctuation: \
                                Y - if the prompt refers to a sensitive and controversial topic \
                                N - otherwise"
        controversial_check_message = [({"role": "user", "content": controversial_check})]
        response = send_message(controversial_check_message, temperature = 0.0, max_response_tokens = 50)
    except:
        return func.HttpResponse( json.dumps({'controversial_content': controversial_content}), mimetype="application/json", status_code=500)
    if response == 'Y':
        return func.HttpResponse( json.dumps({'controversial_content': controversial_content}), mimetype="application/json", status_code=500)
    else:
        query = f"SELECT Top 1 * FROM c where c.User = '{user_email}' and c.Session_id = '{session_id}' order by c.Conversation_id desc"
        # Execute the query
        results = list(cosmos_db_retrieve('alex-nie-cosmosdb-container-conversation').query_items(query, enable_cross_partition_query=True))
        if len(results) > 0:
            conversation = []
            system_prompt = f"""You are a faculty AI who assists the teachers to answer their question about the generated course/lesson.\n
                            There will be a paragraph extracted from the given course/lesson in which the user will ask some questions about it.\n
                            Make sure you answer following the context of the conversation.\n
                            course/lesson:
                            {word_content}
                            paragraph:
                            {highlighted_content}
                            """
            # search_info = search(prompt, 'NIE', 'category') if persona == 'NIE' else search(prompt, 'MOE Knowledge Base', 'category')
            conversation.append({'role': 'system', 'content': system_prompt})
            conversation.append({'role': 'user', 'content': prompt})
            response = send_message(conversation)

            # Execute the query
            query = f"SELECT top 1 * FROM c Where c.Session_id = '{session_id}' and c.User = '{user_email}' order by c.Conversation_id desc"
            results = list(cosmos_db_retrieve('alex-nie-cosmosdb-container-conversation').query_items(query, enable_cross_partition_query=True))
            chat_final = results[0]['Conversation_history']
            chat_final.append({'role': 'user', 'content': prompt})
            chat_final.append({'role': 'assistant', 'content': response})

            Created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            Chat_conversation = {
                "Question": prompt,
                "Response": response,
                "Word_content": word_content,
                "Created_at": Created_at,
                "Activity": activity
            }

            Append_Chat_conversation = results[0]['Chat_conversation']
            Append_Chat_conversation.append(Chat_conversation)

            partition_key = results[0]['Conversation_id']
            item_id = results[0]['id']
            item = cosmos_db_retrieve('alex-nie-cosmosdb-container-conversation').read_item(item_id, partition_key=partition_key)
            session_end = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            item['Conversation_history'] = chat_final
            item['Chat_conversation'] = Append_Chat_conversation
            item['Session_end'] = session_end
            cosmos_db_retrieve('alex-nie-cosmosdb-container-conversation').upsert_item(item)
            response_final = translate_to_en_uk('words.txt', response)
            return func.HttpResponse( json.dumps( {'Responses': {'Responses': response_final}} ), mimetype="application/json", )
        else:
            conversation = []
            system_prompt = f"""You are a faculty AI who assists the teachers to answer their question about the generated course/lesson.\n
                            There will be a paragraph extracted from the given course/lesson in which the user will ask some questions about it.\n
                            Make sure you answer following the context of the conversation.\n
                            course/lesson:
                            {word_content}
                            paragraph:
                            {highlighted_content}
                            """
            # search_info = search(prompt, 'NIE', 'category') if persona == 'NIE' else search(prompt, 'MOE Knowledge Base', 'category')
            conversation.append({'role': 'system', 'content': system_prompt})
            conversation.append({'role': 'user', 'content': prompt})
            response = send_message(conversation)

            # Execute the query
            query = f"SELECT top 1 * FROM c Where c.Session_id = '{session_id}' and c.User = '{user_email}' order by c.Conversation_id desc"
            results = list(cosmos_db_retrieve('alex-nie-cosmosdb-container-conversation').query_items(query, enable_cross_partition_query=True))
            chat_final = []
            chat_final.append({'role': 'system', 'content': system_prompt})
            chat_final.append({'role': 'user', 'content': prompt})
            chat_final.append({'role': 'assistant', 'content': response})

            Created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            Chat_conversation = {
                "Question": prompt,
                "Response": response,
                "Word_content": word_content,
                "Created_at": Created_at,
                "Activity": activity
            }

            # Execute the query
            query = "SELECT Top 1 * FROM c Order by c.Conversation_id desc"
            results = list(cosmos_db_retrieve('alex-nie-cosmosdb-container-conversation').query_items(query, enable_cross_partition_query=True))
            if len(results) == 0:
                next_id = 1
            else:
                max_id = results[0]["Conversation_id"]
                next_id = max_id + 1
            outcome = {
                "id": f"Conversation - {next_id}",
                "Conversation_id": next_id,
                "Conversation_history": chat_final,
                "Chat_conversation": [Chat_conversation],
                "User": user_email,
                "Persona": persona,
                "Session_id": session_id,
                "Session_start": Created_at
            }

            # Insert the document into the container
            cosmos_db_retrieve('alex-nie-cosmosdb-container-conversation').create_item(body=outcome)
            response_final = translate_to_en_uk('words.txt', response)
            return func.HttpResponse( json.dumps( {'Responses': {'Responses': response_final}} ), mimetype="application/json", )