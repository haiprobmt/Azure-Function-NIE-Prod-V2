import logging
import azure.functions as func
import json
from datetime import datetime
from datetime import datetime
import re
from Functions import (
    read_file_blob,
    extract_engage_prompt,
    send_message,
    latest_response,
    search,
    generate_blob_download_url,
    cosmos_db_retrieve,
    translate_to_en_uk,
    upload_stream_to_blob_storage,
    create_word_document_in_memory,
    containers_storage_account
    )

######################################################
## This function used for creating a course outline ##
######################################################

def main(req: func.HttpRequest) -> func.HttpResponse:
    logging.info('Python HTTP trigger function processed a request.')

    req_body = req.get_json()
    Input = req_body.get("prompt")
    session_id = req_body.get("session_id")
    user_email = req_body.get("user_email")

    # Execute the query to check the persona
    query = f"SELECT Top 1 * FROM c WHERE c.User_info['mail'] = '{user_email}' Order by c.User_id desc"
    results = list(cosmos_db_retrieve('nie-alex-cosmos-user').query_items(query, enable_cross_partition_query=True))
    persona = results[0]['Persona']
    user_name = results[0]['User_info']['givenName']
    Created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if not Input:
        try:
            req_body = req.get_json()
        except ValueError:
            pass
        else:
            Input = req_body.get('prompt')

    if Input:
        # Engage prompts
        messages_TE21 = read_file_blob("engage_NIE.json")
        data_list = json.loads(messages_TE21)
        messages_TE21 = data_list

        # Explore prompt
        Input_1 = Input.replace('-', ' ')
        res = [int(i) for i in Input_1.split() if i.isdigit()]
        first_n_weeks = res[0] - 1

        controversial_content = "I'm sorry, you are asking an information related to a sensitive or controversial topics. If you have any other question you would like assistance with, please let me know and I'll be happy to help"
        try:
            controversial_check = f"Please check if the prompt refers to a sensitive or controversial topics: ```{Input}``` then respond with a Y or N character, with no punctuation: \
                                    Y - if the prompt refers to a sensitive and controversial topic \
                                    N - otherwise"
            controversial_check_message = [({"role": "user", "content": controversial_check})]
            response = send_message(controversial_check_message, temperature = 0.0, max_response_tokens = 50)
        except:
            return func.HttpResponse( json.dumps({'controversial_content': controversial_content}), mimetype="application/json", status_code=500)
        if response == 'Y':
            return func.HttpResponse( json.dumps({'controversial_content': controversial_content}), mimetype="application/json", status_code=500)
        else:
            #Extract explore and elaborate from the 5Es excel file 
            prompt_explore = extract_engage_prompt("NIE 5Es Prompts.xlsx", 'Explore')
            prompt_explore_final = prompt_explore.format(Input = Input, first_n_weeks = first_n_weeks)

            messages_TE21.append({"role": "user", "content": prompt_explore_final})
            response = send_message(messages_TE21, max_response_tokens = 3072)
            messages_TE21.append({"role": "assistant", "content": response})
            Values_TE21_prompt = """Based on the above understandings and the course outline you just created. \
                                    Follow these steps to return the answer: \
                                        Step 1: For each ILO, analyse it and provide the relevant values along with their numbered points. \
                                                Return in the following format: \
                                                    ILO: <the ILO content> \
                                                    Value: <the relevant Value> \
                                                    Numbered point: <the relevant numbered points> \
                                                    Explanation: <Explain the reflection of the ILO to the Value>
                                        Step 2: Based on the result from Step 1, return the relevant Values and their numbered points in Json object as below: \
                                                {{
                                                    "Values": [
                                                            {{
                                                                "Value name": < \
                                                                                if the value is Commitment to the learner then return 'Value 1: Commitment to the learner', \
                                                                                if the value is Commitment to the profession then return 'Value 2: Commitment to the profession', \
                                                                                if the value is Commitment to the community then return 'Value 3: Commitment to the community'>, \
                                                                "Numbering Points": <return the numbered points for example: \
                                                                                        1.1 Believing all children can learn, \
                                                                                        1.2 Nurturing every learner holistically. \
                                                                                    Do not return in a list, return a string of values delimited by comma>
                                                            }}
                                                        ]
                                                }}
                                """
            messages_TE21.append({"role": "user", "content": Values_TE21_prompt})
            response = send_message(messages_TE21, max_response_tokens = 2048)
            Values_outcome = json.loads(response.split('Step 2:')[-1])
            # Values_outcome = json.loads(response)

            # Engage prompts
            messages = read_file_blob("engage_NIE.json")
            data_list = json.loads(messages)
            messages = data_list

            # Explore prompt
            Input_1 = Input.replace('-', ' ')
            res = [int(i) for i in Input_1.split() if i.isdigit()]
            first_n_weeks = res[0] - 1

            #Extract explore and elaborate from the 5Es excel file 
            prompt_explore = extract_engage_prompt("NIE 5Es Prompts.xlsx", 'Explore')
            prompt_explore_final = prompt_explore.format(Input = Input, first_n_weeks = first_n_weeks)
            messages.append({"role": "user", "content": prompt_explore_final})
            response = send_message(messages, max_response_tokens = 3072)
            messages.append({"role": "assistant", "content": response})

            prompt_elaborate = extract_engage_prompt("NIE 5Es Prompts.xlsx", 'Elaborate')
            messages.append({"role": "user", "content": prompt_elaborate})
            response = send_message(messages, max_response_tokens = 4096)
            
            #Convert to json to get the reflective question
            response_1 = json.loads(response)
            # Insert the new key-value pair before the existing "values" key
            response_1['TE21']['Values'] = Values_outcome['Values']
            # Convert the modified dictionary back to a JSON string
            Final_Course_outcome = json.dumps(response_1, indent=2)

            Reflective_repsonse = response_1['Reflective question']
            response_course = {key: value for key, value in response_1.items() if key != "Reflective question"}

            messages.append({"role": "assistant", "content": response})
            messages[-1]['content'] = json.dumps(response_course)

            final_repsonse = Final_Course_outcome

            prompt_search = "Based on the course you just created, analyze its content and search the relevant sources"

            user_message = search(prompt_search, 'NIE', 'category')

            prompt_explanation = f"""Based on the searched sources as below:
                    ```{user_message}```
                    Provide the sourcefiles and their explanations followng the instruction steps:
                    step 1: List out all the related the sourcefiles
                    step 2: Explain your thought process using the sources you have referenced.
                    step 3: Giving the conclusion after you explain all
                    Format your response as a JSON object with 'sourcefiles', 'explanations', 'conclusion' are the keys in which 'sourcefiles' and 'explanations' values are the list, 'conclusion' value is the text.
                    """
            messages.append({"role": "user", "content": prompt_explanation})

            response = send_message(messages, max_response_tokens = 3072)
            messages.append({"role": "assistant", "content": response})

            Reference_explanation = response
            Reference_explanation = json.loads(response)
            results_pages = Reference_explanation['sourcefiles']
            explanations = Reference_explanation['explanations']
            conclusion = Reference_explanation['conclusion']
            Reference_explanation_final = []
            try:
                for i in range(len(results_pages)):
                # for blob_name in results_pages:
                    blob_name = results_pages[i]
                    download_url = generate_blob_download_url(blob_name)
                    Reference_explanation_final.append({'File name': results_pages[i], 'Explanation': explanations[i], 'Blob_Url': download_url})
            except:
                Reference_explanation_final = []

            #Save the word_content to blob storage
            timestamp = re.sub('[ \-:]', '_', Created_at)
            docx_file_name = user_name + '_' + session_id + '_' + persona + '_' + timestamp
            # Blob Storage information
            container_name = containers_storage_account('alex-nie-container-docs')
            blob_name = docx_file_name + '.docx'

            # Create Word document in memory
            doc_stream = create_word_document_in_memory(Input)

            # Upload document to Azure Blob Storage
            upload_stream_to_blob_storage(container_name, doc_stream, blob_name, Created_at, user_name, session_id)
                
            query = "SELECT Top 1 * FROM c Order by c.Conversation_id desc"
            # Execute the query
            results = list(cosmos_db_retrieve('alex-nie-cosmosdb-container-conversation').query_items(query, enable_cross_partition_query=True))
            if len(results) == 0:
                next_id = 1
            else:
                max_id = results[0]["Conversation_id"]
                next_id = max_id + 1

            Created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            Historical_conversation = [
                {"role": "user", "content": Input},
                {"role": "assistant", "content": final_repsonse},
                {"role": "assistant", "content": Reflective_repsonse}
            ]
            Chat_conversation = {
                "Question": Input,
                "Response": final_repsonse,
                "Word_content": final_repsonse,
                "Created_at": Created_at,
                "Activity": "Guided Course"
            }
            outcome = {
                "id": f"Conversation - {next_id}",
                "Conversation_id": next_id,
                "Conversation_history": Historical_conversation,
                "Chat_conversation": [Chat_conversation],
                "User": user_email,
                "Persona": persona,
                "Session_id": session_id,
                "Session_start": Created_at
            }

            # Insert the document into the container
            cosmos_db_retrieve('alex-nie-cosmosdb-container-conversation').create_item(body=outcome)

            final_repsonse = translate_to_en_uk('words.txt', final_repsonse)

            return func.HttpResponse( json.dumps({'response': final_repsonse, 'Reference_explanation': Reference_explanation_final, 'Conclusion': conclusion, 'Reflective_repsonce': Reflective_repsonse}), mimetype="application/json", )
    
    else:
        return func.HttpResponse(
            "This HTTP triggered function executed successfully. Pass a name in the query text or in the request body for a personalized response.",
            status_code=200
        )
    
        