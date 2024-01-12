import logging
import azure.functions as func
import json
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
    search_MOE,
    upload_stream_to_blob_storage,
    create_word_document_in_memory,
    containers_storage_account
    )

###################################################
## This function used for creating a lesson plan ##
###################################################

def main(req: func.HttpRequest) -> func.HttpResponse:
    logging.info('Python HTTP trigger function processed a request.')
    
    req_body = req.get_json()
    session_id = req_body.get("session_id")
    user_email = req_body.get("user_email")
    duration = req_body.get("durationInMins")
    student_level_subjects = req_body.get("studentLevel")
    task_topic = req_body.get("topics")

    # Execute the query to check the persona
    query = f"SELECT Top 1 * FROM c WHERE c.User_info['mail'] = '{user_email}' Order by c.User_id desc"
    results = list(cosmos_db_retrieve('nie-alex-cosmos-user').query_items(query, enable_cross_partition_query=True))
    persona = results[0]['Persona']
    user_name = results[0]['User_info']['givenName']
    Created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if not user_email:
        try:
            req_body = req.get_json()
        except ValueError:
            pass
        else:
            user_email = req_body.get('user_email')

    if user_email:
        # Engage prompts
        messages = read_file_blob("engage_MOE.json")
        data_list = json.loads(messages)
        messages = data_list

        prompt = f"""
                    You are given a sentence in which will contain a subject title, here are the steps to achieve it:
                        step 1: refer the following examples and tell me how do you understand it
                            example 1: if the given sentence is: primary 5, Physical Education then the subject is "physic" because the Physical Education refers to the physic topic.
                            example 2: if the given sentence is: primary 4 Science Education then the subject is "Science" because the Science refers to the Science topic.
                            example 3: if the given sentence is: primary 6 English then the subject is "English" because the English refers to the English topic.
                            example 4: if the given sentence is: primary 6, Mathematics then the subject is "Mathematics" because the Mathematics refers to the Mathematics topic.
                            example 5: if the given sentence is: primary 6 Social Studies then the subject is "Social Studies" because the Social Studies refers to the Social Studies topic.
                        step 2: after understanding the step 1, tell me how do you identify the subject for this sentence: ```{student_level_subjects}```
                    Return the subject name in a json format with the structure:
                    {{
                        "subject": <subject name>
                    }}
                    """
        response_subject = send_message([{"role": "user", "content": prompt}])

        # Execute the query to check the persona
        query = f"SELECT Top 1 * FROM c WHERE c.User_info['mail'] = '{user_email}' Order by c.User_id desc"
        results = list(cosmos_db_retrieve('nie-alex-cosmos-user').query_items(query, enable_cross_partition_query=True))
        persona = results[0]['Persona']

        # Engage prompts
        messages = read_file_blob("engage_MOE.json")
        data_list = json.loads(messages)
        messages = data_list

        controversial_check_prompt = f"Write me a {duration} minutes lesson plan for {student_level_subjects} students on {task_topic}"
        controversial_content = "I'm sorry, you are asking an information related to a sensitive or controversial topics. If you have any other question you would like assistance with, please let me know and I'll be happy to help"
        try:
            controversial_check = f"Please check if the prompt refers to a sensitive or controversial topics: ```{controversial_check_prompt}``` then respond with a Y or N character, with no punctuation: \
                                    Y - if the prompt refers to a sensitive and controversial topic \
                                    N - otherwise"
            controversial_check_message = [({"role": "user", "content": controversial_check})]
            response = send_message(controversial_check_message, temperature = 0.0, max_response_tokens = 50)
        except:
            return func.HttpResponse( json.dumps({'controversial_content': controversial_content}), mimetype="application/json", status_code=500)
        if response == 'Y':
            return func.HttpResponse( json.dumps({'controversial_content': controversial_content}), mimetype="application/json", status_code=500)
        else:

            # Extract subject
            subjects = json.loads(response_subject)['subject']

            # Extract student level
            student_level = student_level_subjects.split(' ')[0].split(',')[0]
            Camel_letter_student_level = student_level[0].upper()
            student_level = Camel_letter_student_level + student_level[1:]

            duration = int(duration)

            # Defining the system prompt
            system_message = """
            You are a faculty AI who helps MOE teacher designing a lesson plan for students.
            Answer ONLY with the facts listed in the list of sources below. 
            If there isn't enough information below, say you don't know. Do not generate answers that don't use the sources below. 
            If asking a clarifying question to the user would help, ask the question.
            Be detailed in your answers.
            """

            # # Engage prompts subject
            search_prompt = f"How do you understand the content of the {subjects} subject"
            search_response = search_MOE(search_prompt, f"category eq 'MOE {student_level} SOW'")

            messages.append({"role": "system", "content": system_message})
            messages.append({"role": "user", "content": search_prompt + '\n' + search_response})
            response = send_message(messages, max_response_tokens = 2048)
            messages[-1]['content'] = search_prompt
            messages.append({"role": "assistant", "content": response})
            # Explore prompt
            #Extract explore and elaborate from the 5Es excel file 
            Lesson_developement_example = """Example:
                                                Introduction: \
                                                    1. The teacher presents a video on gravity to the class. \
                                                    2. The teacher questions students on details of the video segments. \
                                                Acquisition: \
                                                    1. Teacher to use objects and show students how gravity works in our daily lives. \
                                                Inquiry and Collaboration: \
                                                    1. The teacher provides students with other objects for hands-on experiments. \
                                                    2. After obtaining the items, students proceed to carry out the experiment.
                                            """
            prompt_explore = extract_engage_prompt("MOE 5Es Prompts.xlsx", 'Explore')

            prompt_explore_elaborate = prompt_explore.format(duration = duration, student_level_subjects = subjects, task_topic = task_topic)
            messages.append({"role": "user", "content": prompt_explore_elaborate})
            response = send_message(messages, max_response_tokens = 4096)
            messages.append({"role": "assistant", "content": response})

            json_prompt = extract_engage_prompt("MOE 5Es Prompts.xlsx", 'Elaborate')

            prompt_json_prompt = json_prompt.format(example = Lesson_developement_example)
            messages.append({"role": "user", "content": prompt_json_prompt})
            response = send_message(messages, max_response_tokens = 4096)
            messages.append({"role": "assistant", "content": response})

            response_1 = json.loads(response)
            Reflective_repsonse = response_1['Reflective question']
            response_lesson = {key: value for key, value in response_1.items() if key != "Reflective question"}
            messages[-1]['content'] = json.dumps(response_lesson)
            final_repsonse = latest_response(messages)

            user_message = search_MOE(response, "category eq 'MOE Knowledge Base'")

            prompt_explanation = f"""Based on the searched sources as below:
                        ```{user_message}``` and ```{search_response}```
                        - List out all the related the sourcefiles.
                        - Explain in details for your explanations about the referred sourcefiles.
                        - Giving the conclusion after you explain all.
                        Return the outcome in Json object with 'sourcefiles', 'explanations', 'conclusion' are the keys. The values of 'sourcefiles' and 'explanations' are in the lists, the value of 'conclusion' is a string.
                    """
            messages.append({"role": "user", "content": prompt_explanation})

            response = send_message(messages, max_response_tokens = 4096)
            messages.append({"role": "assistant", "content": response})

            Reference_explanation = response
            Reference_explanation = json.loads(response)
            results_pages = list(set(Reference_explanation['sourcefiles']))
            explanations = Reference_explanation['explanations']
            conclusion = Reference_explanation['conclusion']

            Reference_explanation_final = []
            try:
                for i in range(len(results_pages)):
                # for blob_name in results_pages:
                    blob_name = results_pages[i]
                    download_url = generate_blob_download_url(blob_name)
                    Reference_explanation_final.append({'File name': results_pages[i], 'Explanation': explanations[i], 'Blob_Url': download_url})
            except Exception as e:
                # print(e)
                Reference_explanation_final = []
            Input = ''
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

            Prompt = f'Write me a {duration} minutes lesson plan for {subjects} students on {task_topic}'

            Historical_conversation = [
                {"role": "user", "content": Prompt},
                {"role": "assistant", "content": final_repsonse},
                {"role": "assistant", "content": Reflective_repsonse}
            ]
            Chat_conversation = {
                "Question": Prompt,
                "Response": final_repsonse,
                "Word_content": final_repsonse,
                "Created_at": Created_at,
                "Activity": "Guided Course"
            }
            Created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
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
            # Reflective_repsonse = translate_to_en_uk('words.txt', Reflective_repsonse)

            return func.HttpResponse( json.dumps({'response': final_repsonse, 'Reference_explanation': Reference_explanation_final, 'Conclusion': conclusion, 'Reflective_repsonce': Reflective_repsonse}), mimetype="application/json", )
    else:
        return func.HttpResponse(
            "This HTTP triggered function executed successfully. Pass a name in the query string or in the request body for a personalized response.",
            status_code=200
        )
