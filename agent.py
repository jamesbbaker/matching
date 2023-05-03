from config import (os, openai, pinecone, time, random, deque, Dict, List,
                    load_dotenv, requests, BeautifulSoup, re, emit, PyPDF2, io,
                    datetime, timedelta)
from fake_useragent import UserAgent

# Set Variables
load_dotenv()

# Set API Keys
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY", "")
PINECONE_ENVIRONMENT = os.getenv("PINECONE_ENVIRONMENT", "us-east4-gcp")
YOUR_TABLE_NAME = os.getenv("PINECONE_INDEX_NAME")
GOOGLE_API_KEY = "AIzaSyBVvIbRW_rWi8JbqU7ZJomeSEExsH3J3Es"
GOOGLE_CSE_ID = "2470dc51a9ec44059"
NEWS_API_KEY = "baa1c0af977d4194b3cd6d94d80ead75"

# Configure OpenAI and Pinecone
openai.api_key = OPENAI_API_KEY
pinecone.init(api_key=PINECONE_API_KEY, environment=PINECONE_ENVIRONMENT)

#For task manager
GOOGLE_SEARCH_KNOWLEDGE = "You can use the command 'Perform a Google search for <search_term>' to get Google Search results. Google Search can be very helpful for learning about topics from top websites."
NEWS_API_KNOWLEDGE = "You can use the command 'Fetch news articles for <search_term>'. Use the News API to gather recent news articles relevant to your objective. This 'Fetch news articles for' returns news from the last 60 days, no need to specify date."
GPT_KNOWLEDGE = "You can request GPT-4 to use research from previous tasks related to any topic you specify. Be specific in the task to help GPT-4 understand your knowledge and craft the best outcome."

def terminate():
  global terminate_flag
  terminate_flag = True
  print('Terminating...')


def main(socketio_instance, objective, max_steps, agent_id, index):

  namespace = agent_id
  agent_index = index
  OBJECTIVE = objective
  MAX_STEPS = max_steps
  terminate_flag = False
  print('Agent is now running...')

  TASK_MANAGER_INSTRUCTIONS = f"""You are a research and writing task manager AI that has been tasked with achieving an objective over a set number of steps.

You have {str(MAX_STEPS)} Google Searches and GPT-4 summarization steps to accomplish this goal. You have to use GPT-4 to summarize and output results on step {str(MAX_STEPS)}.

Create the best plan necessary to achieve your objective."""

  #Initialize the Pinecone Index with the table name
  index = pinecone.Index(YOUR_TABLE_NAME)
  index.delete(deleteAll='true', namespace=namespace)

  # Task list
  global task_list
  task_list = deque([])
  global refined_outcome
  refined_outcome = ''

  completed_tasks = []
  this_task_id = 1
  updated_output = None
  suggestions = None
  references = []
  response = None
  extracted_urls = []

  def parse_completed_tasks(completed_tasks: list) -> str:
    completed_tasks_str = "\n".join(
      [f"{i+1}. {task}" for i, task in enumerate(completed_tasks)])
    return completed_tasks_str.lstrip()

  def truncate_text(text, max_length):
    if len(text) > max_length:
      return text[:max_length]
    else:
      return text

  def get_ada_embedding(text):
    text = text.replace("\n", " ")
    return openai.Embedding.create(
      input=[text], model="text-embedding-ada-002")["data"][0]["embedding"]

  def summarize_with_gpt3(text: str, task: str, max_tokens: int = 1000):
    text = text[:11000]
    prompt = f"""Extract specific info that could be helpful to write an output based on the following task and objective:
    
    Task: {task}

    Objective: {OBJECTIVE}
    
    Text (extract information): {text}

    Write a short title (10 words max) + the author or organization + summary of the key information related to the task and objective including 2-3 quotes from the website relevant to the objective. The summary should include bullet points with specific information from the text and why it's relevant. Facts, data, and details are best.

    Your output should be in the following format (with \n indicating a line space):
    'Title:
    Author:
    Summary:'"""
    summary = openai_call(prompt, use_gpt4=False, max_tokens=1000)
    return summary

  def references_bot(prior_references: str,
                     source: str,
                     new_info: str,
                     max_tokens: int = 1200):
    prompt = f"""Write an APA reference for the new research. Do not make up references. Always output 1 reference (do not output old references.) Use the following format (NEW REFERENCE:'[X] reference', X is 1, 2, 3, etc.) [X] should be the next number based on the old references numbers (e.g. if old references has 2 references make new reference '[3] ...'):
    
    Old references: {prior_references}
    
    Research for new references: {new_info}

    New reference source (includes info on URL and Title): {source}
    
    NEW REFERENCE:"""
    summary = openai_call(prompt, use_gpt4=False, max_tokens=1200)
    print('New references: ' + summary)
    return summary

  def google_search(search_term, api_key, cse_id, **kwargs):
    base_url = "https://www.googleapis.com/customsearch/v1"
    payload = {"key": api_key, "cx": cse_id, "q": search_term, **kwargs}
    response = requests.get(base_url, params=payload)

    json_data = response.json()
    if "items" in json_data:
      return [{
        'url': r['link'],
        'title': r['title'],
        'description': r['snippet']
      } for r in json_data["items"]]
    else:
      print("No items in JSON response. JSON data:", json_data)
      return 'No return'

  def browse_urls(url: str, task: str):
    extracted_information = ''
    url = re.sub(r"'+$", "", url)
    if not url.startswith("http"):
      url = "https://" + url
    try:
      print('Extracting information from: ' + url)
      ua = UserAgent()

      headers = {'User-Agent': ua.random}
      response = requests.get(url, headers=headers, timeout=10)
      if response.status_code == 200:
        if url.endswith('.pdf'):
          with io.BytesIO(response.content) as f:
            pdf_reader = PyPDF2.PdfReader(f)
            text = ''
            for page_num in range(len(pdf_reader.pages)):
              text += pdf_reader.pages[page_num].extract_text()
        else:
          content = response.content
          soup = BeautifulSoup(content, 'html.parser')
          if soup.body:
            text = soup.body.get_text(separator=' ', strip=True)
          else:
            text = soup.get_text(separator=' ', strip=True)

        summary_input = {'url': url, 'info': text}
        summarized_text = summarize_with_gpt3(str(summary_input),
                                              task,
                                              max_tokens=1500)
        extracted_information = summarized_text
      else:
        print('Status code of browse URL not 200:' + str(response.status_code))
        print(response)
        return 'Could not access URL', url
    except (requests.exceptions.RequestException,
            requests.exceptions.InvalidURL) as e:
      print(f"Error while trying to access {url}: {e}")
      return 'Could not access URL', url
    return extracted_information, url

  def extract_urls(task: str, task_result: str, extracted_urls):
    prompt = f"""You are an AI assistant to extract a useful URL from results that might be helpful to browse based on task. Do not select a URL from the 'Do not search list' section. Always select a new URL (never repeat from 'Do not search list'.) New information is always helpful.
  
      Task: {task}

      Do not search list: {extracted_urls}
  
      Select URL list (most helpful URL that is not on do not search list): {task_result}
  
      Your output should be in the format 'https://example1.com'. Do not include text before or after the URL."""
    url = openai_call(prompt, use_gpt4=False, max_tokens=500)
    return url

  def execution_agent(objective: str,
                      task: str,
                      reasoning: str,
                      refs: str,
                      extracted_urls: list,
                      gpt_version: str = 'gpt-3') -> str:
    new_reference = ''
    combined_text = []
    if "Perform a Google search" in task or "Fetch news articles" in task:
      if "Perform a Google search" in task:
        search_term = task.split("search for ")[1]
        search_term = search_term.replace('"', '')
        search_data = google_search(search_term,
                                    GOOGLE_API_KEY,
                                    GOOGLE_CSE_ID,
                                    num=10)
      else:
        search_term = task.split("search for ")[1]
        search_term = search_term.replace('"', '')
        search_data = google_search(search_term,
                                    GOOGLE_API_KEY,
                                    GOOGLE_CSE_ID,
                                    num=10)
      total_count = 0
      successful_browse_count = 0
      while successful_browse_count < 3:   
        total_count += 1
        if (total_count >= 10):
          break
        url_to_browse = extract_urls(task, str(search_data), extracted_urls)
        extracted_info, browsed_url = browse_urls(url_to_browse, task)
        extracted_urls.append(browsed_url)

        if extracted_info != 'Could not access URL':
          new_reference = references_bot(prior_references=str(refs),
                                         source=str(search_data),
                                         new_info=extracted_info)
          refs.append(new_reference)
          result_id = f"{agent_id}_{this_task_id}"
          combined_text.append(extracted_info)
          vector = extracted_info
          index.upsert([(result_id, get_ada_embedding(vector), {
            "task": task,
            "result": extracted_info,
            "url": url_to_browse,
            "reference": new_reference
          })],
                       namespace=namespace)
          socketio_instance(
            'new_ref', {
              'result': extracted_info,
              'url': url_to_browse,
              'reference': new_reference,
              'index': agent_index,
              'email': agent_id
            })
          successful_browse_count += 1
    else:
      extracted_info = context_agent(task, YOUR_TABLE_NAME, 5, namespace)

    response = refine_outcome(objective,
                              combined_text,
                              reasoning,
                              refined_outcome,
                              refs=str(refs))

    if "1) UPDATED OUTPUT:" in response.upper(
    ) and "2) SUGGESTIONS FOR RESEARCH MANAGER:" in response.upper():
      parts = response.split("1) UPDATED OUTPUT:", 1)[1].split(
        "2) SUGGESTIONS FOR RESEARCH MANAGER:", 1)
      updated_output = parts[0].strip()
      suggestions = parts[1].strip()
    else:
      updated_output = response
      suggestions = "Index out of bounds. Shared output and suggestions in updated output."

    return updated_output, suggestions, refs, extracted_urls

  def refine_outcome(objective: str, research: str, reasoning: str,
                     prior_refined_outcome: str, refs: str):
    prompt = f"""You are an research writing AI with goal achieving objective: {objective}. 
  
     Use the research below to improve the output towards the objective. Do not remove prior references. Add new ones based on the new research to strengthen research. Never make up information for which you do not have references. Do not include a references section as it will be included seperately.

     Be creative, useful, and concise to combine the knowledge from research into the best draft output as possible. Use new information to further validate or change the opinions in the writing depending on the circumstances. In 'Suggestions for research manager', share a new area for it to research to further improve the output.
      
      You are just one helper in a multi step process, so just improve the outcome incrementally.  It is step {str(this_task_id)}/{str(MAX_STEPS)}. In your suggestions to research manager, only give suggestions for {str(MAX_STEPS - this_task_id)} more tasks.
      
      Research: {research}
      
      Draft output: {prior_refined_outcome}  

      References: {refs}
  
      Answer the following format (use exact syntax with uppercase for list items, normal case for answers):
      '1) UPDATED OUTPUT:
      2) SUGGESTIONS FOR RESEARCH MANAGER:"""
    updated_outcome = openai_call(prompt, use_gpt4=True, max_tokens=2000)
    return updated_outcome

  def openai_call(prompt: str,
                  use_gpt4: bool = False,
                  temperature: float = 0.7,
                  max_tokens: int = 100):
    for _ in range(3):  # Retry up to 3 times
      try:
        if not use_gpt4:
          # Call GPT-3 DaVinci model
          messages = [{"role": "user", "content": prompt}]
          response = openai.ChatCompletion.create(model='gpt-3.5-turbo',
                                                  messages=messages)
          return response.choices[0].message.content.strip()
        else:
          # Call GPT-4 chat model
          messages = [{"role": "user", "content": prompt}]
          response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            n=1,
            stop=None,
          )
          return response.choices[0].message.content.strip()
      except (openai.error.APIError, openai.error.RateLimitError) as e:
        if e.http_code == 502 or isinstance(e, openai.error.RateLimitError):
          sleep_duration = random.uniform(1, 5)
          time.sleep(
            sleep_duration
          )  # Wait for a random duration between 1 and 5 seconds before retrying
        else:
          raise e  # Re-raise the exception if it's not a 502 error or RateLimitError
    raise Exception("Failed to get response from OpenAI API after 3 retries")

  def task_creation_agent(objective: str, suggestions: str,
                          completed_tasks: List[str]):

    prompt = f"""You are an AI task manager in charge of planning research tasks to achieve your objective: {objective}. Research the most useful information to add to the output. Design queries to dig deeper into new subjects. Your goal is to get to the best outcome possible.
    
    The next task is {str(int(this_task_id))}.
    
    Completed tasks (do not include): {', '.join(completed_tasks)}.
  
    Task {str(MAX_STEPS)} should be 'Create final output with GPT4, _____'.
    
    Suggestions from research AI (research AI does not have full context so use with caution): {suggestions} 

    Current draft: {refined_outcome}
    
    Tools to draw from (You must use the very specific syntax outlined for each): 
    1. {GOOGLE_SEARCH_KNOWLEDGE}
    2. {GPT_KNOWLEDGE}
    
    Return the result as two parts:
    A numbered task list starting with {str(int(this_task_id))} and ending with {MAX_STEPS}. It can be anywhere from 1 task to 20 tasks depending on max steps of {MAX_STEPS} and next step of {str(int(this_task_id))}.
    Reasoning: Explain the reasoning behind the changes to the task list or initial draft.
    
    Answer in the following format:
    '{str(int(this_task_id))}. (Next task)
    #. ...
    {MAX_STEPS}. GPT4 create final output task
    Reasoning:'
    
    Example (step 1/3):
    '1. Perform a Google search for "getting started with next.js"
     2. Perform a Google search for "next.js tutorials in Github"
     3. Create final output with GPT-4, synthesizing information from Google search results'"""
    response = openai_call(prompt, True, max_tokens=2000)

    response_parts = response.split("Reasoning:")
    tasks_response = response_parts[0]
    reasoning_response = response_parts[1]

    new_tasks = tasks_response.split('\n')

    task_list.clear()
    for task_string in new_tasks:
      task_parts = task_string.strip().split(".", 1)
      if len(task_parts) == 2:
        task_id = task_parts[0].strip()
        task_name = task_parts[1].strip()
        task_list.append({"task_id": task_id, "task_name": task_name})

    return task_list, reasoning_response

  def context_agent(query: str, index: str, n: int, namespace):
    query_embedding = get_ada_embedding(query)
    index = pinecone.Index(index_name=index)
    results = index.query(query_embedding,
                          top_k=n,
                          include_metadata=True,
                          namespace=namespace)
    sorted_results = sorted(results.matches,
                            key=lambda x: x.score,
                            reverse=True)
    return [(str(item.metadata['result'])) for item in sorted_results]

  # Add the first task
  first_task = {"task_id": 1, "task_name": 'TASK 1 TBD'}

  if terminate_flag:
    return

  task_list.append(first_task)

  tasks, reasoning_response = task_creation_agent(
    OBJECTIVE, suggestions=TASK_MANAGER_INSTRUCTIONS, completed_tasks='-')

  output_string = ""
  for t in task_list:
    output_string += str(t['task_id']) + '. ' + t['task_name'] + '\n'

  socketio_instance('task_list', {'task_list': output_string})
  socketio_instance('reasoning', {'reasoning': reasoning_response})

  completed_tasks_string = ""

  for i in range(1, MAX_STEPS + 1):

    if terminate_flag:
      break

    # Step 1: Pull the first task
    task = task_list.popleft()

    socketio_instance(
      'task', {
        'objective': OBJECTIVE,
        'output': refined_outcome,
        'completed_tasks': completed_tasks_string,
        'max_steps': str(MAX_STEPS),
        'email': agent_id,
        'index': str(agent_index),
        'references': str(references),
        'task_list': output_string.lstrip(),
        'task': str(this_task_id) + ". " + task['task_name']
      })

    refs = []
    updated_output = ''
    suggestions = ''

    if (this_task_id == MAX_STEPS):
      updated_output, suggestions, refs, extracted_urls = execution_agent(
        OBJECTIVE,
        task["task_name"],
        reasoning=
        'This is the last step of the process. Prepare your best final output using available references. Be as useful and clever as possible with your information to prepare the best answer.',
        refs=references,
        extracted_urls=extracted_urls)
    else:
      updated_output, suggestions, refs, extracted_urls = execution_agent(
        OBJECTIVE,
        task["task_name"],
        reasoning=reasoning_response,
        refs=references,
        extracted_urls=extracted_urls)

    refined_outcome = updated_output
    references = refs

    if terminate_flag:
      break

    # print("\033[93m\033[1m" + "\n*****UPDATED OUTPUT*****\n" +
    #       "\033[0m\033[0m")
    # print(refined_outcome)

    # print("\033[93m\033[1m" + "\n*****UPDATED REFS*****\n" + "\033[0m\033[0m")
    # print(str(references))

    socketio_instance('references', {'references': str(references)})

    completed_tasks.append(task['task_name'])

    completed_tasks_string = parse_completed_tasks(completed_tasks)

    socketio_instance(
      'update_refined_outcome', {
        'objective': OBJECTIVE,
        'refined_outcome': refined_outcome,
        'completed_tasks': completed_tasks_string,
        'max_steps': str(MAX_STEPS),
        'email': agent_id,
        'index': str(agent_index),
        'references': str(references),
        'task_list': output_string.lstrip(),
        'task': str(this_task_id) + ". " + task['task_name']
      })

    socketio_instance('completed_tasks',
                      {'completed_tasks': completed_tasks_string})

    # print("\033[93m\033[1m" + "\n*****SUGGESTIONS FOR TASK MANAGER*****\n" +
    #       "\033[0m\033[0m")
    # print(suggestions)

    socketio_instance('suggestions', {'suggestions': suggestions})

    # print("\033[93m\033[1m" + "\n*****RUNNING TASK MANAGER*****\n" +
    #       "\033[0m\033[0m")

    this_task_id = this_task_id + 1

    if (this_task_id == MAX_STEPS + 1):
      print('FINISHED!')
      print('i:' + str(i))
      print('this_task_id:' + str(this_task_id))
      socketio_instance(
        'finished', {
          'objective': OBJECTIVE,
          'output': refined_outcome,
          'completed_tasks': completed_tasks_string,
          'max_steps': str(MAX_STEPS),
          'email': agent_id,
          'index': str(agent_index),
          'references': str(references),
          'task_list': output_string.lstrip(),
          'task': str(this_task_id) + ". " + task['task_name']
        })
      break

    if (this_task_id == MAX_STEPS):
      tasks, reasoning_response = task_creation_agent(
        OBJECTIVE,
        "The next task is the last task. Output only the last task: GPT-4 to create the final output. It is task number: "
        + str(MAX_STEPS),
        completed_tasks=completed_tasks)

    else:
      tasks, reasoning_response = task_creation_agent(
        OBJECTIVE, suggestions, completed_tasks=completed_tasks)

    output_string = ""
    for t in task_list:
      output_string += str(t['task_id']) + '. ' + t['task_name'] + '\n'

    # print("\033[93m\033[1m" + "\n*****TASK LIST*****\n" + "\033[0m\033[0m")
    # print(output_string.lstrip())

    socketio_instance('task_list', {'task_list': output_string.lstrip()})

    # print("\033[93m\033[1m" + "\n*****REASONING*****\n" + "\033[0m\033[0m")
    # print(reasoning_response)

    socketio_instance('reasoning', {'reasoning': reasoning_response})
