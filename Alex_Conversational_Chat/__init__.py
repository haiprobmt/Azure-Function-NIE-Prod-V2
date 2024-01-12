import logging
import azure.functions as func
import json
from datetime import datetime
import re
from Functions import (
    send_message,
    search,
    generate_blob_download_url,
    cosmos_db_retrieve,
    extract_url,
    upload_stream_to_blob_storage,
    create_word_document_in_memory,
    containers_storage_account,
    translate_to_en_uk,
    send_message_json_conversational_chat_external,
    check_internal_resource,
    get_url_reference
    )

#######################################################################################################
## This function used for creating a conversational chat, the conversational chat takes place when \ ##
## either the course outline/lesson has been created or directly asking a question.                  ##
#######################################################################################################

def main(req: func.HttpRequest) -> func.HttpResponse:
    logging.info('Python HTTP trigger function processed a request.')

    req_body = req.get_json()
    word_content = req_body.get("word_content")
    prompt = req_body.get("prompt")
    session_id = req_body.get("session_id")
    user_email = req_body.get("user_email")
    custom_prompt = req_body.get("custom_prompt")
    activity = req_body.get("activity")

    # Execute the query to check the user information
    query = f"SELECT Top 1 * FROM c WHERE c.User_info['mail'] = '{user_email}' Order by c.User_id desc"
    results = list(cosmos_db_retrieve('nie-alex-cosmos-user').query_items(query, enable_cross_partition_query=True))
    persona = results[0]['Persona']
    user_name = results[0]['User_info']['givenName']

    if not session_id:
        try:
            req_body = req.get_json()
        except ValueError:
            pass
        else:
            session_id = req_body.get('session_id')

    if session_id:

        Created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # If there is no word_content -> this is a direct conversation chat, the user can ask anything
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
            if not word_content:           
                query = f"SELECT top 1 * FROM c Where c.Session_id = '{session_id}' and c.User = '{user_email}' order by c.Conversation_id desc"
                results = list(cosmos_db_retrieve('alex-nie-cosmosdb-container-conversation').query_items(query, enable_cross_partition_query=True))

                try:
                    Conversation = results[0]['Conversation_history']  
                except:
                    Conversation = []

                # Check if the question relate to the knowledge base or not           
                search_prompt = search(prompt, 'NIE', 'category') if persona == 'NIE' else search(prompt, 'MOE Knowledge Base', 'category')
                response_check = check_internal_resource(prompt, search_prompt)

                # Search the external sources
                # system_prompt_course_external = "You are a friendly AI assistant named ALEX who helps teacher to answer their questions in anything"
                # Conversation.append({"role": "system", "content": system_prompt_course_external})
                Conversation.append({"role": "user", "content": prompt})
                external_responses = send_message_json_conversational_chat_external(Conversation, prompt, max_response_tokens = 4096)
                Conversation.append({'role': 'assistant', 'content': external_responses})

                try:
                    external_sources = get_url_reference(Conversation)['References']
                except:
                    external_sources = []

                # Extract the external sources
                external_source_final = []
                if len(external_sources) > 0:
                    for source in external_sources:
                        if source != 'None' and '.pdf' not in source and 'https' in source:
                            url = extract_url(source)['url']
                            external_source_final.append({'File name': url, 'Blob_Url': url})
                        else:
                            continue
                else:
                    external_source_final = []
                
                # If the prompt doesn't relate to the knowledge base -> return the answer using the external sources
                if response_check == 'N':
                    resources_external = '\n'.join(list(set([source['File name'] for source in external_source_final])))
                    response_final = external_responses + '\n' + 'References:' + '\n' + resources_external

                    Conversation[-1]['content'] = response_final

                    last_response = []
                    last_response.append({'Responses': external_responses,'References': external_source_final})

                    del Conversation[-3:]

                    Conversation.append({'role': 'user', 'content': prompt})
                    Conversation.append({'role': 'assistant', 'content': external_responses})

                    response_final = external_responses

                # If the prompt relates to the knowledge base -> keep searching to combine the internal and external sources
                else: 
                    del Conversation[-3:]

                    if custom_prompt:
                        system_prompt_course_internal = f"""You are an intelligent faculty named ALEX who assists teacher to answer their questions based on the provided sources.
                                                        Answer ONLY with the facts listed in the list of sources below as much as possible.
                                                        Use the friendly tone in your answer
                                                        {custom_prompt}. 
                                                        """   
                    else:
                        system_prompt_course_internal = f"""You are an intelligent faculty named ALEX who assists teacher to answer their questions based on the provided sources.
                                                        Answer ONLY with the facts listed in the list of sources below as much as possible.
                                                        Use the friendly tone in your answer
                                                        """  
                    Conversation.append({"role": "system", "content": system_prompt_course_internal})
                    source_file_prompt = f"""```{search_prompt}```
                            Give the outcome in Json format with 'Responses' and 'References' are the keys, the value of Responses is a string and the values of References is the list of sourcefiles.
                            """
                    Conversation.append({'role': 'user', 'content': source_file_prompt})
                    response_internal = send_message(Conversation, temperature = 0.5, max_response_tokens = 4096)
                    response_internal = json.loads(response_internal)
                    internal_sources = list(set(response_internal['References']))
                    internal_responses = response_internal['Responses']

                    internal_sources_final = []
                    for i in range(len(internal_sources)):
                        blob_name = internal_sources[i]
                        download_url = generate_blob_download_url(blob_name)
                        internal_sources_final.append({'File name': internal_sources[i], 'Blob_Url': download_url})      

                    # Combine External and Internal sources referred
                    last_response = []
                    last_response.append({'Responses': internal_responses,'References': internal_sources_final + external_source_final})

                    if len(internal_sources_final) == 0:
                        if len(external_source_final) == 0:
                            response_final = internal_responses
                        else:
                            resources_external = '\n'.join(list(set([source['File name'] for source in external_source_final])))
                            response_final = internal_responses + '\n' + 'References:' + '\n' + resources_external
                    else:
                        resources_final = '\n'.join(list(set([ source['File name'] for source in last_response[0]['References']])))
                        response_final = internal_responses + '\n' + 'References:' + '\n' + resources_final

                    # Delete system and user prompts    
                    del Conversation[-2:]

                    Conversation.append({'role': 'user', 'content': prompt})
                    Conversation.append({'role': 'assistant', 'content': response_final})

                # Update the conversation into database
                Chat_conversation = {
                    "Question": prompt,
                    "Response": response_final,
                    "Word_content": word_content,
                    "Created_at": Created_at,
                    "Activity": activity
                }

                # If the input session exists in the database -> update the conversation
                if len(results) > 0:
                    print('no word content_existing conversation')

                    Append_Chat_conversation = results[0]['Chat_conversation']
                    Append_Chat_conversation.append(Chat_conversation)

                    result = results[0]
                    partition_key = result['Conversation_id']
                    item_id = result['id']
                    item = cosmos_db_retrieve('alex-nie-cosmosdb-container-conversation').read_item(item_id, partition_key=partition_key)
                    # Update new data
                    modified_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    item['Conversation_history'] = Conversation
                    item['Chat_conversation'] = Append_Chat_conversation
                    item['Session_end'] = modified_at
                    cosmos_db_retrieve('alex-nie-cosmosdb-container-conversation').upsert_item(item)
                
                # If the input session doesn't exist in the database -> create a new conversation
                else:
                    print('no word content_not existing conversation')

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
                        "Conversation_history": Conversation,
                        "Chat_conversation": [Chat_conversation],
                        "User": user_email,
                        "Persona": persona,
                        "Session_id": session_id,
                        "Session_start": Created_at
                    }

                    # Insert the document into the container
                    cosmos_db_retrieve('alex-nie-cosmosdb-container-conversation').create_item(body=outcome)

                translated_response = last_response[0]['Responses']
                references = last_response[0]['References']
                responses = translate_to_en_uk('words.txt', translated_response)
                final_response = {'Responses': responses, 'References': references}

                return func.HttpResponse( json.dumps({'Responses': final_response}), mimetype="application/json", )
            
            # If there is a word_content -> this is a course/lesson-based conversation chat
            else:
                # If the activity is Guided Course means the user has been created a course/lesson then use the conversation chat
                if activity == 'Guided Course':
                    query = f"SELECT top 1 * FROM c Where c.Session_id = '{session_id}' and c.User = '{user_email}' order by c.Conversation_id desc"
                    # Execute the query
                    results = list(cosmos_db_retrieve('alex-nie-cosmosdb-container-conversation').query_items(query, enable_cross_partition_query=True))
                    Conversation = results[0]['Conversation_history']

                # If the activity isn't a Guided Course means the users use their own course/lesson and paste to the word document to chat with it
                else:
                    Conversation = [{'role': 'user', 'content': 'Based on the information that you have, please you help me to create a course outline or lesson plan'}]
                    Conversation.append({'role': 'assistant', 'content': word_content})
                    Reflective_prompt = "At the end of the course, you ask a reflective question to help the user find which are the points needed to be improved."
                    Conversation.append({'role': 'user', 'content': Reflective_prompt})
                    response = send_message(Conversation, max_response_tokens = 4096)
                    Conversation.append({"role": "assistant", "content": response})
            
                search_prompt = search(prompt, 'NIE', 'category') if persona == 'NIE' else search(prompt, 'MOE Knowledge Base', 'category')
                response_check = check_internal_resource(prompt, search_prompt)

                # Search the external sources
                system_prompt_course_external = "You are a friendly AI assistant named ALEX who helps teacher to answer their questions in anything"
                Conversation.append({"role": "system", "content": system_prompt_course_external})
                Conversation.append({"role": "user", "content": prompt})
                external_responses = send_message_json_conversational_chat_external(Conversation, prompt, max_response_tokens = 4096)
                Conversation.append({'role': 'assistant', 'content': external_responses})

                try:
                    external_sources = get_url_reference(Conversation)['References']
                except:
                    external_sources = []

                # Extract the external sources
                external_source_final = []
                if len(external_sources) > 0:
                    for source in external_sources:
                        if source != 'None' and '.pdf' not in source and 'https' in source:
                            url = extract_url(source)['url']
                            external_source_final.append({'File name': url, 'Blob_Url': url})
                        else:
                            continue
                else:
                    external_source_final = []
                
                # If the prompt doesn't relate to the knowledge base -> return the answer using the external sources
                if response_check == 'N':
                    resources_external = '\n'.join(list(set([source['File name'] for source in external_source_final])))
                    response_final = external_responses + '\n' + 'References:' + '\n' + resources_external

                    Conversation[-1]['content'] = response_final

                    last_response = []
                    last_response.append({'Responses': external_responses,'References': external_source_final})

                    del Conversation[-3:]

                    Conversation.append({'role': 'user', 'content': prompt})
                    Conversation.append({'role': 'assistant', 'content': external_responses})

                    response_final = external_responses

                # If the prompt relates to the knowledge base -> keep searching to combine the internal and external sources
                else: 
                    del Conversation[-3:]

                    if custom_prompt:
                        system_prompt_course_internal = f"""You are an intelligent faculty named ALEX who assists teacher to answer their questions based on the provided sources.
                                                        Answer ONLY with the facts listed in the list of sources below as much as possible.
                                                        Use the friendly tone in your answer
                                                        {custom_prompt}. 
                                                        """   
                    else:
                        system_prompt_course_internal = f"""You are an intelligent faculty named ALEX who assists teacher to answer their questions based on the provided sources.
                                                        Answer ONLY with the facts listed in the list of sources below as much as possible.
                                                        Use the friendly tone in your answer
                                                        """  
                    Conversation.append({"role": "system", "content": system_prompt_course_internal})
                    source_file_prompt = f"""```{search_prompt}```
                            Give the outcome in Json format with 'Responses' and 'References' are the keys, the value of Responses is a string and the values of References is the list of sourcefiles.
                            """
                    Conversation.append({'role': 'user', 'content': source_file_prompt})
                    response_internal = send_message(Conversation, temperature = 0.5, max_response_tokens = 4096)
                    response_internal = json.loads(response_internal)
                    internal_sources = list(set(response_internal['References']))
                    internal_responses = response_internal['Responses']

                    internal_sources_final = []
                    for i in range(len(internal_sources)):
                        blob_name = internal_sources[i]
                        download_url = generate_blob_download_url(blob_name)
                        internal_sources_final.append({'File name': internal_sources[i], 'Blob_Url': download_url})      

                    # Combine External and Internal sources referred
                    last_response = []
                    last_response.append({'Responses': internal_responses,'References': internal_sources_final + external_source_final})

                    if len(internal_sources_final) == 0:
                        if len(external_source_final) == 0:
                            response_final = internal_responses
                        else:
                            resources_external = '\n'.join(list(set([source['File name'] for source in external_source_final])))
                            response_final = internal_responses + '\n' + 'References:' + '\n' + resources_external
                    else:
                        resources_final = '\n'.join(list(set([ source['File name'] for source in last_response[0]['References']])))
                        response_final = internal_responses + '\n' + 'References:' + '\n' + resources_final

                    # Delete system and user prompts    
                    del Conversation[-2:]

                    Conversation.append({'role': 'user', 'content': prompt})
                    Conversation.append({'role': 'assistant', 'content': response_final})

                #Save the word_content to blob storage
                timestamp = re.sub('[ \-:]', '_', Created_at)
                docx_file_name = user_name + '_' + session_id + '_' + persona + '_' + timestamp
                # Blob Storage information
                container_name = containers_storage_account('alex-nie-container-docs')
                blob_name = docx_file_name + '.docx'

                # Create Word document in memory
                doc_stream = create_word_document_in_memory(word_content)

                # Upload document to Azure Blob Storage
                upload_stream_to_blob_storage(container_name, doc_stream, blob_name, Created_at, user_name, session_id)

                Created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                
                Chat_conversation = {
                    "Question": prompt,
                    "Response": response_final,
                    "Word_content": word_content,
                    "Created_at": Created_at,
                    "Activity": activity
                }

                query = f"SELECT top 1 * FROM c Where c.Session_id = '{session_id}' and c.User = '{user_email}' order by c.Conversation_id desc"
                results = list(cosmos_db_retrieve('alex-nie-cosmosdb-container-conversation').query_items(query, enable_cross_partition_query=True))
                if len(results) > 0:
                    print('Word content_exist conversation')               
                    Append_Chat_conversation = results[0]['Chat_conversation']
                    Append_Chat_conversation.append(Chat_conversation)

                    result = results[0]
                    partition_key = result['Conversation_id']
                    item_id = result['id']
                    item = cosmos_db_retrieve('alex-nie-cosmosdb-container-conversation').read_item(item_id, partition_key=partition_key)
                    # Update new data
                    modified_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    item['Conversation_history'] = Conversation
                    item['Chat_conversation'] = Append_Chat_conversation
                    item['Session_end'] = modified_at
                    cosmos_db_retrieve('alex-nie-cosmosdb-container-conversation').upsert_item(item)
                else:
                    print('word content_not existing conversation')
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
                        "Conversation_history": Conversation,
                        "Chat_conversation": [Chat_conversation],
                        "User": user_email,
                        "Persona": persona,
                        "Session_id": session_id,
                        "Session_start": Created_at
                    }

                    # Insert the document into the container
                    cosmos_db_retrieve('alex-nie-cosmosdb-container-conversation').create_item(body=outcome)

                translated_response = last_response[0]['Responses']
                references = last_response[0]['References']
                responses = translate_to_en_uk('words.txt', translated_response)
                final_response = {'Responses': responses, 'References': references}
                return func.HttpResponse( json.dumps({'Responses': final_response}), mimetype="application/json", )
    else:
        return func.HttpResponse(
            "This HTTP triggered function executed successfully. Pass a name in the query text or in the request body for a personalized response.",
            status_code=200
        )