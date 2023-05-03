import os
import threading
import logging
import eventlet
from replit import db
import pinecone
from flask import Flask, render_template, request, session, redirect, make_response, url_for, jsonify
from flask_socketio import SocketIO, disconnect, join_room
import agent
from flask_dance.contrib.google import make_google_blueprint, google
from oauth2client.client import GoogleCredentials
from flask_dance.consumer import oauth_authorized
from werkzeug.security import generate_password_hash, check_password_hash
import random
import stripe
import json
from copy import deepcopy
from flask_mail import Mail, Message
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadTimeSignature

stripe.api_key = os.getenv('STRIPE_API_KEY')

TOKENS_BY_PRODUCT_ID = {
  "price_1MyTmBJt9Voxe5t4z5q1bl9u": 20,
  "price_1MzSB2Jt9Voxe5t4Lg2byENy": 100,
  "price_1MzULGJt9Voxe5t4uMbiD7sd": 300
}

os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'

eventlet.monkey_patch()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('FLASK_SECRET')

app.config['MAIL_SERVER'] = 'smtp.office365.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USERNAME'] = os.environ.get('MAIL_USERNAME')
app.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASSWORD')
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USE_SSL'] = False

mail = Mail(app)

app.logger.setLevel(logging.ERROR)
logging.getLogger('engineio').setLevel(logging.ERROR)
log = logging.getLogger('werkzeug')
log.disabled = True

app.config['GOOGLE_OAUTH_CLIENT_ID'] = os.getenv('GOOGLE_OAUTH_CLIENT_ID')
app.config['GOOGLE_OAUTH_CLIENT_SECRET'] = os.getenv(
  'GOOGLE_OAUTH_CLIENT_SECRET')
google_blueprint = make_google_blueprint(scope=[
  'https://www.googleapis.com/auth/userinfo.email', 'openid',
  'https://www.googleapis.com/auth/userinfo.profile'
])
app.register_blueprint(google_blueprint, url_prefix='/login/google')

socketio = SocketIO(app, async_mode='eventlet')

PINECONE_API_KEY = os.getenv("PINECONE_API_KEY", "")
PINECONE_ENVIRONMENT = os.getenv("PINECONE_ENVIRONMENT", "us-east4-gcp")

print('Setting up Pinecone...')
pinecone.init(api_key=PINECONE_API_KEY, environment=PINECONE_ENVIRONMENT)

index = os.getenv('PINECONE_INDEX_NAME')
# if index in pinecone.list_indexes():
#   print('Deleting existing index...')
#   pinecone.delete_index(index)

# print('Creating new Pinecone index (brain)...')
# pinecone.create_index(index,
#                       dimension=1536,
#                       metric="cosine",
#                       pod_type="p1")


agent_threads = {}
agent_locks = {}

def terminate_agent(email):
    if email in agent_threads:
        agent.terminate()
        agent_threads[email].join()
        del agent_threads[email]


def run_agent(socketio_instance, max_steps, objective, email, index):

  def callback(event_name, data):
    print('Callback:' + event_name)
    socketio.emit(event_name, data, room=email)
    if event_name == 'update_refined_outcome':
      update_refined_outcome(data)
    if event_name == 'finished':
      finished(data)
    if event_name == 'task':
      update_task(data)
    if event_name == 'new_ref':
      update_refs(data)

  agent_id = email

  if email not in agent_locks:
    agent_locks[email] = threading.Lock()

  with agent_locks[email]:
    print('Terminating prior agents...')
    terminate_agent(email)
    agent_thread = threading.Thread(target=agent.main,
                                    args=(callback, objective, max_steps,
                                          agent_id, index))
    agent_thread.daemon = True
    print('Starting new agent...')
    agent_thread.start()

    agent_threads[email] = agent_thread


@app.route('/delete_output', methods=['POST'])
def delete_output():
  data = request.json
  index = data['index']
  email = session['email']
  del db[email]['agents'][str(index)]
  terminate_agent(email)
  print('Successfully ended agent')

  return redirect(url_for('home'))


@app.route('/minimize', methods=['POST'])
def minimize():
  try:
    print('Minimizing agent...')

    return redirect(url_for('home'))

  except Exception as e:
    print("Error in minimize:", e)  # Add this line to print the error
    return jsonify({"error": str(e)}), 500


def update_refined_outcome(data):
  print('Updated output!')
  email = data['email']
  index = data['index']

  agent = db[email]['agents'][str(index)]
  agent['objective'] = data['objective']
  agent['output'] = data['refined_outcome']
  agent['steps'] = data['max_steps']
  agent['completed_tasks'] = data['completed_tasks']
  agent['task'] = data['task']
  agent['task_list'] = data['task_list']
  agent['references'] = data['references']
  agent['status'] = 'Searching...'


def update_task(data):
  print('Updated task!')
  email = data['email']
  index = data['index']

  agent = db[email]['agents'][str(index)]
  agent['objective'] = data['objective']
  agent['output'] = data['output']
  agent['steps'] = data['max_steps']
  agent['completed_tasks'] = data['completed_tasks']
  agent['task'] = data['task']
  agent['task_list'] = data['task_list']
  agent['references'] = data['references']
  agent['status'] = 'Searching...'


def finished(data):
  print('Finished!')

  email = data['email']
  index = data['index']

  db[email]['agents'][str(index)]['objective'] = data['objective']
  db[email]['agents'][str(index)]['output'] = data['output']
  db[email]['agents'][str(index)]['steps'] = data['max_steps']
  db[email]['agents'][str(index)]['completed_tasks'] = data['completed_tasks']
  db[email]['agents'][str(index)]['task'] = 'Completed.'
  db[email]['agents'][str(index)]['task_list'] = 'Completed.'
  db[email]['agents'][str(index)]['references'] = data['references']
  db[email]['agents'][str(index)]['status'] = 'Completed.'


def update_refs(data):
  print('Updated refs!')
  email = data['email']
  url = data['url']
  reference = data['reference']
  summary = data['result']
  index = data['index']

  # Append new ref with a numbered key to the end of refs
  ref_number = len(db[email]['agents'][str(index)]['refs']) + 1
  new_ref = {
    ref_number: {
      'url': url,
      'reference': reference,
      'summary': summary
    }
  }
  db[email]['agents'][str(index)]['refs'].append(new_ref)

  db[email]['tokens'] = db[email]['tokens'] - 1
  print('Tokens: ' + str(db[email]['tokens']))


@socketio.on('connect')
def on_connect():
  email = request.args.get('email')  # Use the email query parameter
  if not email:
    print("Disconnected due to missing email argument")
    disconnect()
  else:
    print(f"Connected, joining room for email: {email}")
    join_room(email)


# Create a user class
class User:
  def __init__(self, email, password, google_id=None):
    self.email = email
    self.password = password
    self.google_id = google_id

  def save(self):
    db[self.email] = {
      'password': self.password,
      'google_id': self.google_id,
      'tokens': 10
    }

  @staticmethod
  def get_by_email(email):
    if email in db:
      user_data = db[email]
      return User(email, user_data['password'], user_data['google_id'])
    return None

  @staticmethod
  def get_by_google_id(google_id):
    for key in db.keys():
      if 'google_id' in db[key] and db[key]['google_id'] == google_id:
        user_data = db[key]
        return User(key, user_data['password'], user_data['google_id'])
    return None
    

  def send_confirmation_email(self, token):
      msg = Message('Confirm your email', sender='james@tolimanai.com', recipients=[self.email])
      confirm_url = url_for('confirm_email', token=token, _external=True)
      msg.body = f'Thank you for signing up to use Toliman AI! Please confirm your email by clicking the following link: {confirm_url}'
      mail.send(msg)


@app.route('/login', methods=['GET', 'POST'])
def login():
  if request.method == 'POST':
    email = request.form.get('email')
    password = request.form.get('password')
    user = User.get_by_email(email)
    if user and check_password_hash(user.password, password):
      session['email'] = email
      return redirect(url_for('create_bot'))
    else:
      image_number = random.randint(1, 6)
      return render_template('login.html',
                             error='Invalid email or password',
                             image_number=image_number)
  image_number = random.randint(1, 6)
  return render_template('login.html', image_number=image_number)

def generate_confirmation_token(email, password_hash):
    serializer = URLSafeTimedSerializer(app.secret_key)
    data = {'email': email, 'password_hash': password_hash}
    return serializer.dumps(data, salt='email-confirmation')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    message = request.args.get('message', '')
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        user = User.get_by_email(email)
        if user:
            image_number = random.randint(1, 6)
            message = 'Email already exists'
            return render_template('signup.html',
                                   error=message,
                                   image_number=image_number)
        else:
            password_hash = generate_password_hash(password)
            session['unconfirmed_user'] = {
                'email': email,
                'password': password_hash
            }
            token = generate_confirmation_token(email, password_hash)
            user = User(email, password_hash)
            user.send_confirmation_email(token)
            message = 'A confirmation email has been sent to your email address. Please follow the instructions in the email to confirm your account.'
            return render_template('signup.html', message=message)
    image_number = random.randint(1, 6)
    return render_template('signup.html', image_number=image_number, message=message)

@app.route('/confirm/<token>')
def confirm_email(token):
    data = confirm_token(token)
    if not data:
        message = 'The confirmation link is invalid or has expired.'
        return redirect(url_for('signup', message=message))
    else:
        email = data['email']
        user = User.get_by_email(email)
        if user:
            message = 'Your email has already been confirmed. You can log in.'
        else:
            user = User(email, data['password_hash'])
            user.save()
        return redirect(url_for('home'))

def confirm_token(token, expiration=3600):
    serializer = URLSafeTimedSerializer(app.secret_key)
    try:
        data = serializer.loads(token, salt='email-confirmation', max_age=expiration)
    except (SignatureExpired, BadTimeSignature):
        return None
    return data

@app.route('/login/google/google/authorized')
def google_auth_callback():
  if not google.authorized:
    return redirect(url_for('google.login'))
  resp = google.get('/oauth2/v2/userinfo')
  google_id = resp.json()['id']
  user = User.get_by_google_id(google_id)
  if not user:
    email = resp.json()['email']
    user = User(email, None, 'google', google_id)
    user.save()
  session['email'] = user.email
  return redirect(url_for('create_bot'))


@oauth_authorized.connect_via(google_blueprint)
def google_logged_in(blueprint, token):
  credentials = GoogleCredentials(token['access_token'], None, None, None,
                                  None, None, None)
  resp = google.get('/oauth2/v2/userinfo')
  google_id = resp.json()['id']
  user = User.get_by_google_id(google_id)
  if not user:
    email = resp.json()['email']
    user = User(email, None, google_id)
    user.save()
  session['email'] = user.email


@app.route('/output')
def output():

  if 'email' not in session:
    return redirect(url_for('login'))

  if session['email'] not in db.keys():
    return redirect(url_for('login'))

  max_steps = request.args.get('max_steps')
  index = request.args.get('index')
  objective = request.args.get('objective').strip()
  completed_tasks = request.args.get('completed_tasks')
  task = request.args.get('task')
  task_list = request.args.get('task_list')
  status = request.args.get('status')
  email = session['email']
  image_number = random.randint(1, 6)
  tokens = db[session['email']]['tokens']
  return render_template('index.html',
                         MAX_STEPS=max_steps,
                         OBJECTIVE=objective,
                         image_number=image_number,
                         tokens=tokens,
                         email=email,
                         task=task,
                         task_list=task_list,
                         completed_tasks=completed_tasks,
                         index=index,
                         status=status)


@app.route('/get_refs', methods=['POST'])
def get_refs():
  data = request.get_json()
  email = data['email']
  index = data['index']

  refs = db[email]['agents'][str(index)]['refs']
  refs_list = [{k: dict(v)} for ref in refs for k, v in ref.items()]

  return jsonify(refs=json.dumps(refs_list))


@app.route('/get_output', methods=['POST'])
def get_output():
  data = request.get_json()
  email = data['email']
  index = data['index']

  # Retrieve refs from the database
  output = db[email]['agents'][str(index)]['output']
  return jsonify(output=output)


@app.route('/home')
def home():
  if 'email' not in session:
    return redirect(url_for('login'))

  if session['email'] not in db.keys():
    return redirect(url_for('login'))

  agents = None
  if 'agents' in db[session['email']]:
    agents = db[session['email']]['agents']

  image_number = random.randint(1, 6)
  purchase_success = request.args.get('purchase_success', False)
  tokens = db[session['email']]['tokens']
  return render_template('home.html',
                         image_number=image_number,
                         purchase_success=purchase_success,
                         tokens=tokens,
                         agents=agents)


@app.route('/landing')
def landing_page():
  image_number = 1
  return render_template('landing_page.html', image_number=image_number)


@app.route('/', methods=['GET', 'POST'])
def index():
  return redirect(url_for('landing_page'))  # Redirect to the landing page


@app.route('/create-bot', methods=['GET', 'POST'])
def create_bot():

  if 'email' not in session:
    return redirect(url_for('login'))

  if session['email'] not in db.keys():
    return redirect(url_for('login'))

  if request.method == 'POST':
    print('Creating bot...')
    max_steps = int(request.form.get('max_steps'))
    objective = request.form.get('objective')
    email = session['email']
    index = 1
    if 'agents' not in db[email]:
      db[email]['agents'] = {
        index: {
          'objective': objective,
          'output': 'Pending.',
          'completed_tasks': 'Pending.',
          'steps': int(max_steps / 3 + 1),
          'references': 'Pending.',
          'task_list': 'Pending.',
          'task': 'Pending.',
          'refs': [],
          'status': 'Searching...',
          'id': email + '_' + str(index)
        }
      }
    else:
      index = max([int(key)
                   for key in db[email]['agents'].keys()], default=0) + 1
      db[email]['agents'][index] = {
        'objective': objective,
        'output': 'Pending.',
        'completed_tasks': 'Pending.',
        'steps': int(max_steps / 3 + 1),
        'references': 'Pending.',
        'task_list': 'Pending.',
        'task': 'Pending.',
        'refs': [],
        'status': 'Searching...',
        'id': email + '_' + str(index)
      }

    run_agent(socketio, int(max_steps / 3 + 1), objective, email, index)

    tokens = db[session['email']]['tokens']
    return redirect(
      url_for('output',
              max_steps=max_steps,
              objective=objective,
              completed_tasks='Pending.',
              task_list='Pending.',
              task='Pending.',
              index=index,
              status='Searching...'))

  image_number = random.randint(1, 6)
  tokens = db[session['email']]['tokens']
  return render_template('create_bot.html',
                         image_number=image_number,
                         tokens=tokens)


@app.route('/terms')
def terms():
  image_number = random.randint(1, 6)
  return render_template('terms.html', image_number=image_number)


@app.route('/privacy')
def privacy():
  image_number = random.randint(1, 6)
  return render_template('privacy-policy.html', image_number=image_number)


@app.route('/current_agent/<int:index>')
def current_agent(index):
  if 'email' not in session:
    return redirect(url_for('login'))

  if session['email'] not in db.keys():
    return redirect(url_for('login'))

  max_steps = db[session['email']]['agents'][str(index)]['steps']
  objective = db[session['email']]['agents'][str(index)]['objective']
  completed_tasks = db[session['email']]['agents'][str(
    index)]['completed_tasks']
  task_list = db[session['email']]['agents'][str(index)]['task_list']
  task = db[session['email']]['agents'][str(index)]['task']
  status = db[session['email']]['agents'][str(index)]['status']

  return redirect(
    url_for('output',
            max_steps=max_steps,
            objective=objective,
            completed_tasks=completed_tasks,
            task_list=task_list,
            task=task,
            index=index,
            status=status))


@app.route('/tokens')
def tokens():

  if 'email' not in session:
    return redirect(url_for('login'))

  if session['email'] not in db.keys():
    return redirect(url_for('login'))

  image_number = random.randint(1, 6)
  tokens = db[session['email']]['tokens']
  return render_template('tokens.html',
                         image_number=image_number,
                         tokens=tokens)


@app.route('/learn')
def learn():
  image_number = random.randint(1, 6)
  return render_template('learn.html', image_number=image_number)


@app.route('/stripe_webhook', methods=['POST'])
def stripe_webhook():
  payload = request.data
  event = None

  try:
    event = stripe.Event.construct_from(json.loads(payload), stripe.api_key)
  except ValueError as e:
    print("Invalid payload")
    print(e)
    return jsonify({"status": "error", "message": "Invalid payload"}), 400

  if event.type == 'checkout.session.completed':
    checkout_session = event.data.object
    email = checkout_session.get('customer_email') or checkout_session.get(
      'customer_details', {}).get('email')

    if email is None:
      print("Email not found in session object")
      return jsonify({"status": "error", "message": "Email not found"}), 400

    line_items = stripe.checkout.Session.list_line_items(checkout_session.id)
    purchased_product_id = line_items.data[0].price.id

    # Get the number of tokens based on the purchased product's ID
    tokens_to_add = TOKENS_BY_PRODUCT_ID.get(purchased_product_id, 0)

    print(f"Adding {tokens_to_add} tokens to user {email}")

    # Update the user's token balance in the Replit database
    user = User.get_by_email(email)
    if user:
      if 'tokens' not in db[email]:
        db[email]['tokens'] = 0
      db[email]['tokens'] += tokens_to_add

  return jsonify({
    "status": "success",
    "message": "Webhook event received"
  }), 200


@app.route('/purchase_success')
def purchase_success():
  return redirect(url_for('home', purchase_success=True))


@app.route('/create-checkout-session', methods=['POST'])
def create_checkout_session():

  # Authenticate the user and get their email
  email = session['email']

  data = json.loads(request.data)
  price_id = data['priceId']

  try:
    checkout_session = stripe.checkout.Session.create(
      payment_method_types=['card'],
      line_items=[{
        'price': price_id,
        'quantity': 1,
      }],
      customer_email=
      email,  # Pass the customer email to the Stripe Checkout Session
      mode='payment',
      success_url=url_for('purchase_success', _external=True) +
      "?session_id={CHECKOUT_SESSION_ID}",
      cancel_url=url_for('tokens', _external=True),
    )
    return jsonify({"id": checkout_session.id})
  except Exception as e:
    return jsonify({"error": str(e)}), 400


@app.route('/gallery')
def gallery():
  image_number = random.randint(1, 6)
  colors = [{
    'bg': '#4B0082',
    'text': 'white'
  }, {
    'bg': '#6A5ACD',
    'text': 'white'
  }, {
    'bg': '#9370DB',
    'text': 'black'
  }, {
    'bg': '#B0C4DE',
    'text': 'black'
  }, {
    'bg': '#4682B4',
    'text': 'white'
  }, {
    'bg': '#6495ED',
    'text': 'black'
  }, {
    'bg': '#87CEFA',
    'text': 'black'
  }, {
    'bg': '#ADD8E6',
    'text': 'black'
  }]
  if 'gallery_agents' not in db:
    db['gallery_agents'] = []
  approved_agents = [
    agent for agent in db['gallery_agents']
    if agent.get('approved', False) == True
  ]
  return render_template('gallery.html',
                         image_number=image_number,
                         approved_agents=approved_agents,
                         colors=colors)


@app.route("/gallery_approval")
def gallery_approval():
  if 'gallery_agents' not in db:
    db['gallery_agents'] = []
  gallery_agents = db['gallery_agents']
  return render_template("gallery_approval.html",
                         gallery_agents=gallery_agents)


@app.route("/approve_agent", methods=["POST"])
def approve_agent():
  agent_id = request.args.get("id")
  for a in db["gallery_agents"]:
    if a["id"] == agent_id:
      a["approved"] = True
      break
  return "OK"


@app.route("/reject_agent", methods=["POST"])
def reject_agent():
  agent_id = request.args.get("id")
  db["gallery_agents"] = [
    a for a in db["gallery_agents"] if a["id"] != agent_id
  ]
  return "OK"


@app.route("/share_agent", methods=["POST"])
def share_agent():
  data = request.json
  title = data["title"]
  description = data["description"]
  author = data["author"]
  email = data["email"]
  index = data["index"]
  agent_data = db[email]["agents"][index]
  agent_data.update({
    "title": title,
    "description": description,
    "author": author
  })
  if "gallery_agents" not in db:
    db["gallery_agents"] = []
  db["gallery_agents"].append(agent_data)
  return "OK"


print('Starting app...')
socketio.run(app,
             host='0.0.0.0',
             port=int(os.environ.get('PORT', 3000)),
             log_output=False)
