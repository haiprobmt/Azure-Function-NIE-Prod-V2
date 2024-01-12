import base64
import html
import io
import re
import time
import azure.functions as func

import openai
from azure.ai.formrecognizer import DocumentAnalysisClient
from azure.core.credentials import AzureKeyCredential
from azure.identity import AzureDeveloperCliCredential
from azure.search.documents import SearchClient
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import (
    HnswParameters,
    PrioritizedFields,
    SearchableField,
    SearchField,
    SearchFieldDataType,
    SearchIndex,
    SemanticConfiguration,
    SemanticField,
    SemanticSettings,
    SimpleField,
    VectorSearch,
    VectorSearchAlgorithmConfiguration,
)
from azure.storage.blob import BlobServiceClient, ContentSettings
from pypdf import PdfReader, PdfWriter
from tenacity import retry, stop_after_attempt, wait_random_exponential
from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient
from azure.cosmos import CosmosClient
from datetime import datetime
from io import BytesIO
from getConfig import get_db_config

# Replace these values with your Azure Key Vault URL
keyvault_url = "https://nie-alex-key-vault-prod.vault.azure.net/"

# Create a SecretClient using the DefaultAzureCredential
credential = DefaultAzureCredential()
client_kv = SecretClient(vault_url=keyvault_url, credential=credential)

# Cosmos DB information
config = get_db_config()
client = CosmosClient(config['endpoint'], config['key'])
database = client.get_database_client(config['database_name'])
container_cosmos = database.get_container_client(config['container_name_files'])

async def main(req: func.HttpRequest) -> func.HttpResponse:
    
    req_method = req.method
    if req_method == 'POST':
        category = req.params.get('category')
        type = req.params.get('type')
        user_email = req.params.get('user_email')
        if not category:
            try:
                req_body = req.get_json()
            except ValueError:
                pass
            else:
                category = req_body.get('category')

        if category:
            AZURE_STORAGE_ACCOUNT = client_kv.get_secret("alex-nie-storage-account").value
            container = client_kv.get_secret("alex-nie-storage-container").value
            container_2 = client_kv.get_secret("alex-nie-container-2").value
            storagekey = client_kv.get_secret("alex-nie-storage-key").value
            AZURE_TENANT_ID = client_kv.get_secret("alex-nie-tenantid").value
            AZURE_SEARCH_SERVICE = client_kv.get_secret("alex-nie-search-service").value
            AZURE_SEARCH_INDEX = client_kv.get_secret("alex-nie-search-index").value
            AZURE_SEARCH_API_KEY = client_kv.get_secret("alex-nie-search-api-key").value
            openaiservice = client_kv.get_secret("alex-nie-openai-service").value
            openaideployment = client_kv.get_secret("alex-nie-openai-embedding").value
            openaikey = client_kv.get_secret("alex-nie-openai-key").value
            formrecognizerservice = client_kv.get_secret("alex-nie-formrecognizerservice").value
            formrecognizerkey = client_kv.get_secret("alex-nie-formrecognizerkey").value
            category = category
            verbose = True
            novectors = True
            remove = True
            removeall = False
            skipblobs = False
            localpdfparser = True
            
            filename = req.files.get("File")
            if not filename:
                return func.HttpResponse("No file provided", status_code=400)

            else:
                if '.xlsx' in filename.filename:
                    if 'NIE' in filename.filename:
                        connection_string = client_kv.get_secret("alex-nie-storage-connection-string").value
                        # container_name = client_kv.get_secret("alex-nie-storage-container").value
                        blob_name = filename.filename
                        blob_service_client = BlobServiceClient.from_connection_string(connection_string)
                        container_client = blob_service_client.get_container_client(container_2)
                        excel_data = io.BytesIO(filename.read())
                        blob_client = container_client.get_blob_client(blob_name)
                        blob_client.upload_blob(excel_data, overwrite=True)
                        from Engage_NIE_Train_file import save_file
                        save_file('engage_NIE.json', filename.filename)
                    if 'MOE' in filename.filename:
                        connection_string = client_kv.get_secret("alex-nie-storage-connection-string").value
                        # container_name = client_kv.get_secret("alex-nie-storage-container").value
                        blob_name = filename.filename
                        blob_service_client = BlobServiceClient.from_connection_string(connection_string)
                        container_client = blob_service_client.get_container_client(container_2)
                        excel_data = io.BytesIO(filename.read())
                        blob_client = container_client.get_blob_client(blob_name)
                        blob_client.upload_blob(excel_data, overwrite=True)
                        from Engage_MOE_Train_file import save_file
                        save_file('engage_MOE.json', filename.filename)
                    # Store uploaded file information into CosmosDB
                    query = "SELECT Top 1 * FROM c Order by c.File_id desc"
                    # Execute the query
                    results = list(container_cosmos.query_items(query, enable_cross_partition_query=True))
                    if len(results) == 0:
                        next_id = 1
                    else:
                        max_id = results[0]["File_id"]
                        next_id = max_id + 1

                    query_1 = "SELECT distinct c.File_name FROM c"
                    results_1 = list(container_cosmos.query_items(query_1, enable_cross_partition_query=True))
                    if filename.filename in [File_name['File_name'] for File_name in results_1]:
                        print("The file already exists in the database!")
                    else:
                        Created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        outcome = {
                            "id": f"File - {next_id}",
                            "File_id": next_id,
                            "File_name": filename.filename,
                            "Type": type,
                            "Category": category,
                            "Uploaded_by": user_email,
                            "Uploaded_at": Created_at,
                        }
                        # Insert the document into the container
                        container_cosmos.create_item(body=outcome)
                    return func.HttpResponse(f"The file {filename.filename} uploaded successfully")
                else:
                    container_name = client_kv.get_secret("alex-nie-storage-container").value
                    MAX_SECTION_LENGTH = 1000
                    SENTENCE_SEARCH_LIMIT = 100
                    SECTION_OVERLAP = 100

                    azd_credential = AzureDeveloperCliCredential() if AZURE_TENANT_ID is None else AzureDeveloperCliCredential(tenant_id=AZURE_TENANT_ID, process_timeout=60)
                    default_creds = azd_credential if AZURE_SEARCH_API_KEY is None or storagekey is None else None
                    search_creds = default_creds if AZURE_SEARCH_API_KEY is None else AzureKeyCredential(AZURE_SEARCH_API_KEY)
                    use_vectors = novectors

                    storage_creds = default_creds if storagekey is None else storagekey

                    if not localpdfparser:
                        # check if Azure Form Recognizer credentials are provided
                        if formrecognizerservice is None:
                            print("Error: Azure Form Recognizer service is not provided. Please provide formrecognizerservice or use --localpdfparser for local pypdf parser.")
                            exit(1)
                        formrecognizer_creds = default_creds if formrecognizerkey is None else AzureKeyCredential(formrecognizerkey)

                    if use_vectors:
                        if openaikey is None:
                            openai.api_key = azd_credential.get_token("https://cognitiveservices.azure.com/.default").token
                            openai.api_type = "azure_ad"
                        else:
                            openai.api_type = "azure"
                            openai.api_key = openaikey

                        openai.api_base = f"https://{openaiservice}.openai.azure.com"
                        openai.api_version = "2023-05-15"

                    def blob_name_from_file_page(filename, page = 0):
                        if len(re.findall(".pdf", str(filename))) > 0:
                                return filename_name + f"-{page}" + ".pdf"
                        else:
                            return filename_name

                    def upload_blobs(filename):
                        blob_service = BlobServiceClient(account_url=f"https://{AZURE_STORAGE_ACCOUNT}.blob.core.windows.net", credential=storage_creds)
                        blob_container = blob_service.get_container_client(container)
                        if not blob_container.exists():
                            blob_container.create_container()

                        # if file is PDF split into pages and upload each page as a separate blob
                        if len(re.findall(".pdf", str(filename))) > 0:
                            reader = PdfReader(filename)
                            pages = reader.pages
                            for i in range(len(pages)):
                                blob_name = blob_name_from_file_page(filename, i)
                                print(f"\tUploading blob for page {i} -> {blob_name}")
                                f = io.BytesIO()
                                writer = PdfWriter()
                                writer.add_page(pages[i])
                                writer.write(f)
                                f.seek(0)
                                blob_container.upload_blob(blob_name, f, overwrite=True)
                        else:
                            blob_name = blob_name_from_file_page(filename)
                            blob_container.upload_blob(blob_name, overwrite=True)

                    def blob_exists(container_name, blob_name):
                        try:
                            # Create a ContainerClient to interact with the container
                            container_client = BlobServiceClient.get_container_client(container_name)

                            # Check if the blob exists by attempting to get its properties
                            blob_client = container_client.get_blob_client(blob_name)
                            blob_properties = blob_client.get_blob_properties()
                            return True

                        except Exception as e:
                            # If an exception is raised, the blob doesn't exist
                            return False
                    def remove_blobs(filename):
                        if verbose: print(f"Removing blobs for '{filename or '<all>'}'")
                        blob_service = BlobServiceClient(account_url=f"https://{AZURE_STORAGE_ACCOUNT}.blob.core.windows.net", credential=storage_creds)
                        blob_container = blob_service.get_container_client(container)
                        if blob_container.exists():
                            if filename is None:
                                blobs = blob_container.list_blob_names()
                                for b in blobs:
                                    if verbose: print(f"\tRemoving blob {b}")
                                    blob_container.delete_blob(b)
                            else:
                                reader = PdfReader(filename)
                                pages = reader.pages
                                for i in range(len(pages)):
                                    blobs = blob_name_from_file_page(filename, i)
                                    if blob_exists(container, blobs):
                                        if verbose: print(f"\tRemoving blob {blobs}")
                                        blob_container.delete_blob(blobs)
                                    else:
                                        if verbose: print(f"\tThere is no blob {blobs}")

                    def table_to_html(table):
                        table_html = "<table>"
                        rows = [sorted([cell for cell in table.cells if cell.row_index == i], key=lambda cell: cell.column_index) for i in range(table.row_count)]
                        for row_cells in rows:
                            table_html += "<tr>"
                            for cell in row_cells:
                                tag = "th" if (cell.kind == "columnHeader" or cell.kind == "rowHeader") else "td"
                                cell_spans = ""
                                if cell.column_span > 1: cell_spans += f" colSpan={cell.column_span}"
                                if cell.row_span > 1: cell_spans += f" rowSpan={cell.row_span}"
                                table_html += f"<{tag}{cell_spans}>{html.escape(cell.content)}</{tag}>"
                            table_html +="</tr>"
                        table_html += "</table>"
                        return table_html

                    def get_document_text(filename):
                        offset = 0
                        page_map = []
                        if localpdfparser:
                            reader = PdfReader(filename)
                            pages = reader.pages
                            for page_num, p in enumerate(pages):
                                page_text = p.extract_text()
                                page_map.append((page_num, offset, page_text))
                                offset += len(page_text)
                        else:
                            if verbose: print(f"Extracting text from '{filename}' using Azure Form Recognizer")
                            form_recognizer_client = DocumentAnalysisClient(endpoint=f"https://{formrecognizerservice}.cognitiveservices.azure.com/", credential=formrecognizer_creds, headers={"x-ms-useragent": "azure-search-chat-demo/1.0.0"})
                            with open(filename, "rb") as f:
                                poller = form_recognizer_client.begin_analyze_document("prebuilt-layout", document = f)
                            form_recognizer_results = poller.result()

                            for page_num, page in enumerate(form_recognizer_results.pages):
                                tables_on_page = [table for table in form_recognizer_results.tables if table.bounding_regions[0].page_number == page_num + 1]

                                # mark all positions of the table spans in the page
                                page_offset = page.spans[0].offset
                                page_length = page.spans[0].length
                                table_chars = [-1]*page_length
                                for table_id, table in enumerate(tables_on_page):
                                    for span in table.spans:
                                        # replace all table spans with "table_id" in table_chars array
                                        for i in range(span.length):
                                            idx = span.offset - page_offset + i
                                            if idx >=0 and idx < page_length:
                                                table_chars[idx] = table_id

                                # build page text by replacing charcters in table spans with table html
                                page_text = ""
                                added_tables = set()
                                for idx, table_id in enumerate(table_chars):
                                    if table_id == -1:
                                        page_text += form_recognizer_results.content[page_offset + idx]
                                    elif table_id not in added_tables:
                                        page_text += table_to_html(tables_on_page[table_id])
                                        added_tables.add(table_id)

                                page_text += " "
                                page_map.append((page_num, offset, page_text))
                                offset += len(page_text)

                        return page_map

                    def split_text(page_map):
                        SENTENCE_ENDINGS = [".", "!", "?"]
                        WORDS_BREAKS = [",", ";", ":", " ", "(", ")", "[", "]", "{", "}", "\t", "\n"]
                        if verbose: print(f"Splitting '{filename}' into sections")

                        def find_page(offset):
                            num_pages = len(page_map)
                            for i in range(num_pages - 1):
                                if offset >= page_map[i][1] and offset < page_map[i + 1][1]:
                                    return i
                            return num_pages - 1

                        all_text = "".join(p[2] for p in page_map)
                        length = len(all_text)
                        start = 0
                        end = length
                        while start + SECTION_OVERLAP < length:
                            last_word = -1
                            end = start + MAX_SECTION_LENGTH

                            if end > length:
                                end = length
                            else:
                                # Try to find the end of the sentence
                                while end < length and (end - start - MAX_SECTION_LENGTH) < SENTENCE_SEARCH_LIMIT and all_text[end] not in SENTENCE_ENDINGS:
                                    if all_text[end] in WORDS_BREAKS:
                                        last_word = end
                                    end += 1
                                if end < length and all_text[end] not in SENTENCE_ENDINGS and last_word > 0:
                                    end = last_word # Fall back to at least keeping a whole word
                            if end < length:
                                end += 1

                            # Try to find the start of the sentence or at least a whole word boundary
                            last_word = -1
                            while start > 0 and start > end - MAX_SECTION_LENGTH - 2 * SENTENCE_SEARCH_LIMIT and all_text[start] not in SENTENCE_ENDINGS:
                                if all_text[start] in WORDS_BREAKS:
                                    last_word = start
                                start -= 1
                            if all_text[start] not in SENTENCE_ENDINGS and last_word > 0:
                                start = last_word
                            if start > 0:
                                start += 1

                            section_text = all_text[start:end]
                            yield (section_text, find_page(start))

                            last_table_start = section_text.rfind("<table")
                            if (last_table_start > 2 * SENTENCE_SEARCH_LIMIT and last_table_start > section_text.rfind("</table")):
                                # If the section ends with an unclosed table, we need to start the next section with the table.
                                # If table starts inside SENTENCE_SEARCH_LIMIT, we ignore it, as that will cause an infinite loop for tables longer than MAX_SECTION_LENGTH
                                # If last table starts inside SECTION_OVERLAP, keep overlapping
                                if verbose: print(f"Section ends with unclosed table, starting next section with the table at page {find_page(start)} offset {start} table start {last_table_start}")
                                start = min(end - SECTION_OVERLAP, start + last_table_start)
                            else:
                                start = end - SECTION_OVERLAP

                        if start + SECTION_OVERLAP < end:
                            yield (all_text[start:end], find_page(start))

                    def filename_to_id(filename):
                        filename_ascii = re.sub("[^0-9a-zA-Z_-]", "_", filename)
                        filename_hash = base64.b16encode(filename.encode('utf-8')).decode('ascii')
                        return f"file-{filename_ascii}-{filename_hash}"

                    def create_sections(filename, page_map, use_vectors):
                        file_id = filename_to_id(filename)
                        for i, (content, pagenum) in enumerate(split_text(page_map)):
                            section = {
                                "id": f"{file_id}-page-{i}",
                                "content": content,
                                "category": category,
                                "sourcepage": blob_name_from_file_page(filename, pagenum),
                                "sourcefile": filename
                            }
                            if use_vectors:
                                section["embedding"] = compute_embedding(content)
                            yield section

                    def before_retry_sleep(retry_state):
                        if verbose: print("Rate limited on the OpenAI embeddings API, sleeping before retrying...")

                    @retry(wait=wait_random_exponential(min=1, max=60), stop=stop_after_attempt(15), before_sleep=before_retry_sleep)
                    def compute_embedding(text):
                        return openai.Embedding.create(engine=openaideployment, input=text)["data"][0]["embedding"]

                    def create_search_index():
                        index = AZURE_SEARCH_INDEX
                        if verbose: print(f"Ensuring search index {AZURE_SEARCH_INDEX} exists")
                        index_client = SearchIndexClient(endpoint=f"https://{AZURE_SEARCH_SERVICE}.search.windows.net/",
                                                        credential=search_creds)
                        if index not in index_client.list_index_names():
                            index = SearchIndex(
                                name=index,
                                fields=[
                                    SimpleField(name="id", type="Edm.String", key=True),
                                    SearchableField(name="content", type="Edm.String", analyzer_name="en.microsoft"),
                                    SearchField(name="embedding", type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
                                                hidden=False, searchable=True, filterable=False, sortable=False, facetable=False,
                                                vector_search_dimensions=1536, vector_search_configuration="default"),
                                    SimpleField(name="category", type="Edm.String", filterable=True, facetable=True),
                                    SimpleField(name="sourcepage", type="Edm.String", filterable=True, facetable=True),
                                    SimpleField(name="sourcefile", type="Edm.String", filterable=True, facetable=True)
                                ],
                                semantic_settings=SemanticSettings(
                                    configurations=[SemanticConfiguration(
                                        name='default',
                                        prioritized_fields=PrioritizedFields(
                                            title_field=None, prioritized_content_fields=[SemanticField(field_name='content')]))]),
                                    vector_search=VectorSearch(
                                        algorithm_configurations=[
                                            VectorSearchAlgorithmConfiguration(
                                                name="default",
                                                kind="hnsw",
                                                hnsw_parameters=HnswParameters(metric="cosine")
                                            )
                                        ]
                                    )
                                )
                            if verbose: print(f"Creating {index} search index")
                            index_client.create_index(index)
                        else:
                            if verbose: print(f"Search index {index} already exists")

                    def index_sections(filename, sections):
                        if verbose: print(f"Indexing sections from '{filename}' into search index '{AZURE_SEARCH_INDEX}'")
                        search_client = SearchClient(endpoint=f"https://{AZURE_SEARCH_SERVICE}.search.windows.net/",
                                                        index_name=AZURE_SEARCH_INDEX,
                                                        credential=search_creds)
                        i = 0
                        batch = []
                        for s in sections:
                            batch.append(s)
                            i += 1
                            if i % 1000 == 0:
                                results = search_client.upload_documents(documents=batch)
                                succeeded = sum([1 for r in results if r.succeeded])
                                if verbose: print(f"\tIndexed {len(results)} sections, {succeeded} succeeded")
                                batch = []

                        if len(batch) > 0:
                            results = search_client.upload_documents(documents=batch)
                            succeeded = sum([1 for r in results if r.succeeded])
                            if verbose: print(f"\tIndexed {len(results)} sections, {succeeded} succeeded")

                    def remove_from_index(filename):
                        if verbose: print(f"Removing sections from '{filename or '<all>'}' from search index '{AZURE_SEARCH_INDEX}'")
                        search_client = SearchClient(endpoint=f"https://{AZURE_SEARCH_SERVICE}.search.windows.net/",
                                                        index_name=AZURE_SEARCH_INDEX,
                                                        credential=search_creds)
                        while True:
                            filter = None if filename is None else f"sourcefile eq '{filename}'"
                            r = search_client.search("", filter=filter, top=1000, include_total_count=True)
                            if r.get_count() == 0:
                                break
                            r = search_client.delete_documents(documents=[{ "id": d["id"] } for d in r])
                            if verbose: print(f"\tRemoved {len(r)} sections from index")
                            # It can take a few seconds for search results to reflect changes, so wait a bit
                            time.sleep(2)

                        # Use the current user identity to connect to Azure services unless a key is explicitly set for any of them
                    # try:
                    if removeall:
                        remove_blobs(None)
                        remove_from_index(None)
                    else:
                        filename_name = filename.filename
                        if not remove:
                            create_search_index()

                        print("Processing files...")
                        if verbose: print(f"Processing '{filename_name}'")
                        if remove:
                            remove_blobs(filename)
                            remove_from_index(filename_name)
                            if not skipblobs:
                                upload_blobs(filename)
                            page_map = get_document_text(filename)
                            sections = create_sections(filename_name, page_map, use_vectors)
                            index_sections(filename_name, sections)
                        elif removeall:
                            remove_blobs(None)
                            remove_from_index(None)

                    # Upload the original file into blob storage
                    blob_service = BlobServiceClient(account_url=f"https://{AZURE_STORAGE_ACCOUNT}.blob.core.windows.net", credential=storage_creds)
                    blob_container = blob_service.get_container_client(container_2)
                    blob_name = filename.filename
                    # Read the entire PDF file into a byte stream
                    reader = PdfReader(filename)
                    pages = reader.pages
                    # Create a BytesIO stream to store the merged PDF content
                    merged_pdf = BytesIO()
                    writer = PdfWriter()

                    # Merge all pages into a single PDF
                    for i in range(len(pages)):
                        writer.add_page(pages[i])

                    # Write the merged PDF content to the BytesIO stream
                    writer.write(merged_pdf)
                    merged_pdf.seek(0)
                    blob_container.upload_blob(blob_name, merged_pdf, overwrite=True)

                    print(f"File '{blob_name}' uploaded to blob '{blob_name}' in container '{container_name}'.")

                    # Store uploaded file information into CosmosDB
                    query = "SELECT Top 1 * FROM c Order by c.File_id desc"
                    # Execute the query
                    results = list(container_cosmos.query_items(query, enable_cross_partition_query=True))
                    if len(results) == 0:
                        next_id = 1
                    else:
                        max_id = results[0]["File_id"]
                        next_id = max_id + 1

                    query_1 = "SELECT distinct c.File_name FROM c"
                    results_1 = list(container_cosmos.query_items(query_1, enable_cross_partition_query=True))
                    if filename.filename in [File_name['File_name'] for File_name in results_1]:
                        print("The file already exists in the database!")
                    else:
                        Created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        outcome = {
                            "id": f"File - {next_id}",
                            "File_id": next_id,
                            "File_name": filename.filename,
                            "Type": type,
                            "Category": category,
                            "Uploaded_by": user_email,
                            "Uploaded_at": Created_at,
                        }
                        # Insert the document into the container
                        container_cosmos.create_item(body=outcome)
                        return func.HttpResponse("File uploaded successfully")
                    # except Exception as e:
                    #     return func.HttpResponse(f"An error occurred: {str(e)}", status_code=500)
            
            # Update the existing files
    elif req_method == 'PATCH':
        try:
            req_body = req.get_json()
            category_edit = req_body.get("category")
            type_edit = req_body.get("type")
            user_email_edit = req_body.get("user_email")

            edit_File_name = filename.filename
            
            query = f"SELECT top 1 * FROM c Where c.File_name = {edit_File_name}"
            result_category = list(container_cosmos.query_items(query, enable_cross_partition_query=True))

            result = result_category[0]
            partition_key = result['File_id']
            item_id = result['id']
            item = container_cosmos.read_item(item_id, partition_key=partition_key)

            modified_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            item['Modified_at'] = modified_at
            item['Category'] = category_edit
            item['Type'] = type_edit
            item['Modified_by'] = user_email_edit
            item['Modified_at'] = Created_at
            
            # UPDATE LATER BASED ON SSO AUTHORISATION TOKEN
            # item['Updated_user'] = ''
            
            # Replace the existing document with the updated one
            container_cosmos.upsert_item(item)
            return func.HttpResponse("File uploaded successfully")
        except Exception as e:
            return func.HttpResponse(f"An error occurred: {str(e)}", status_code=500)
    