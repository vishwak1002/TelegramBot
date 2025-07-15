from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel,Field
import os
import sys
import httpx # For making HTTP requests to Telegram API
import logging

from google.adk.agents import Agent
from google.adk.tools import google_search

# Add the project directory to sys.path to allow importing agent.py
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

# Import your ADK agent class from agent.py
from agent import MyGoogleSearchAgent
global user_id
# Attempt to load environment variables from .env file
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    print("Warning: python-dotenv not found. Ensure environment variables are set manually.")

# Configure logging for better visibility
logging.basicConfig(level=logging.INFO, stream=sys.stdout)
logger = logging.getLogger(__name__)

# --- Environment Variable Validation and Retrieval ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
logger.info(f"TELEGRAM_BOT_TOKEN: {TELEGRAM_BOT_TOKEN}")
if not TELEGRAM_BOT_TOKEN:
    logger.error("TELEGRAM_BOT_TOKEN environment variable not set. Please set it in .env or your environment.")
    sys.exit(1) # Exit if token is missing

TELEGRAM_API_BASE_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

# --- FastAPI App Initialization ---
app = FastAPI(
    title="ADK Telegram Bot Demo with Google Search",
    description="A simple web and Telegram interface for an ADK agent using FastAPI and Google Search.",
    version="1.0.0",
)

# --- Initialize ADK Agent and Session Service ---
session_service = InMemorySessionService()

adk_agent = Agent(
    name="search_assistant",
    model="gemini-2.0-flash", # Or your preferred Gemini model
    instruction="You are a helpful assistant. Answer user questions using Google Search when needed.",
    description="An assistant that can search the web.",
    tools=[google_search]
)
APP_NAME = "MyTelegramADKBot"
adk_runner = Runner(agent=adk_agent,session_service=session_service,app_name=APP_NAME)

# --- Pydantic Model for Telegram Update ---
# This mirrors the structure of an incoming Telegram webhook update
class Message(BaseModel):
    message_id: int
    from_user: dict  = Field(alias='from') # 'from' is a reserved keyword in Python
    chat: dict
    date: int
    text: str




class CallbackQuery(BaseModel):
    id: str
    from_user: dict
    message: Message = None # Optional, for inline keyboard callbacks
    data: str

class TelegramUpdate(BaseModel):
    update_id: int
    message: Message = None # Optional for messages
    callback_query: CallbackQuery = None # Optional for inline keyboard callbacks

# --- FastAPI Client for outbound Telegram API calls ---
# Use httpx.AsyncClient for efficient asynchronous requests
telegram_http_client = httpx.AsyncClient()

# --- Utility function to send messages to Telegram ---
async def send_telegram_message(chat_id: int, text: str):
    url = f"{TELEGRAM_API_BASE_URL}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text
    }
    try:
        response = await telegram_http_client.post(url, json=payload, timeout=10)
        response.raise_for_status() # Raise an exception for HTTP errors (4xx or 5xx)
        logger.info(f"Sent message to Telegram chat {chat_id}: {text}")
    except httpx.HTTPStatusError as e:
        logger.error(f"Telegram API responded with error {e.response.status_code} for chat {chat_id}: {e.response.text}")
        raise
    except httpx.RequestError as e:
        logger.error(f"An error occurred while requesting Telegram API for chat {chat_id}: {e}")
        raise

# --- Telegram Webhook Endpoint ---
@app.post("/telegram-webhook", summary="Telegram Bot Webhook endpoint")
async def telegram_webhook(update: TelegramUpdate):
    """
    Receives incoming updates from Telegram and processes them with the ADK agent.
    """
    logger.info(f"Received Telegram update: {update.dict()}")

    if update.message:
        # Handle regular text messages
        chat_id = update.message.chat['id']
        user_text = update.message.text
        user_id = str(update.message.from_user['id']) # Use sender's ID as user_id for ADK session
        logger.info(f"Message from chat {chat_id} (User: {user_id}): {user_text}")

        try:
            # Process the message with the ADK agent
            # Using run_sync as ADK methods are generally synchronous unless explicitly async
            new_message_content = types.Content(role="user",
                parts=[types.Part(text=user_text)] # Single part for plain text
            )

            session_found = False
            try:
                # Attempt to retrieve the session. If it raises ValueError, it means it doesn't exist.
                # Note: get_session itself might not be async, but runner methods often are.
                # For InMemorySessionService, get_session is synchronous.
                session_service.get_session(app_name = APP_NAME,user_id=user_id,session_id=user_id)
                logger.info(f"Session {user_id} found in InMemorySessionService. Continuing existing session.")
                session_found = False
                 # Delete the session to start a new one
            except ValueError:
                session_found = False # Session not found, proceed to create

            if not session_found:
                logger.info(f"Session {user_id} not found in InMemorySessionService. Starting a new session.")
                # The start_session method of InMemorySessionService is synchronous
                # but if you were using a different service, it might be async and need await.
                example_session = await session_service.create_session(
                            app_name=APP_NAME,
                                user_id=user_id,session_id=user_id)
                # --- EXPLICIT SESSION MANAGEMENT START ---)  
                logger.info(f"New session {user_id} explicitly started.")
            else:
                logger.info(f"Session {user_id} found. Continuing existing session.")
            # --- EXPLICIT SESSION MANAGEMENT END ---
            logger.info(f"Inside webhook, session_service object ID: {id(session_service)}")
            logger.info(f"New message content: {new_message_content}")
            response_generator = adk_runner.run_async(
                user_id=user_id,
                session_id=user_id,
                new_message=new_message_content, # <--- Use new_message
            )
            full_response = ""

            async for event in adk_runner.run_async(
                user_id=user_id,
                session_id=user_id,
                new_message=new_message_content, # <--- Use new_message
            ):
        # print(f"Event: {event.type}, Author: {event.author}") # Uncomment for detailed logging
                if event.is_final_response() and event.content and event.content.parts:
            # For output_schema, the content is the JSON string itself
                    logging.info(event.content.parts)
                    full_response = event.content.parts[0].text

            logger.info(f"ADK generated response for Telegram: {full_response}")

            # Send the ADK's response back to Telegram
            await send_telegram_message(chat_id, full_response)

        except Exception as e:
            logger.error(f"Error processing Telegram message for user {user_id}: {e}")
            import traceback
            traceback.print_exc()
            await send_telegram_message(chat_id, "Sorry, an internal error occurred while processing your request.")

    elif update.callback_query:
        # Handle callback queries (e.g., from inline keyboards) if your bot uses them
        chat_id = update.callback_query.message.chat['id'] if update.callback_query.message else update.callback_query.from_user['id']
        callback_data = update.callback_query.data
        user_id = str(update.callback_query.from_user['id'])
        logger.info(f"Callback query from chat {chat_id} (User: {user_id}): {callback_data}")
        await send_telegram_message(chat_id, f"Received callback: {callback_data}") # Basic acknowledgement

    # Telegram expects a 200 OK response quickly
    return Response(status_code=200)




# --- Startup Event ---
@app.on_event("startup")
async def startup_event():
    """
    Verify environment variables when the FastAPI application starts.
    This is also where you might set the Telegram webhook if you want it automated.
    """
    # Environment variable checks (repeated from agent.py for app-level check)
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        print("Warning: python-dotenv not found. Ensure environment variables are set manually.")
        sys.exit(1)

# Configure logging for better visibility
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    logger = logging.getLogger(__name__)
    logger.info("FastAPI application starting... Verifying environment variables. ")
    logger.info(f"TELEGRAM_BOT_TOKEN: {TELEGRAM_BOT_TOKEN}")
    if not  os.getenv("GOOGLE_API_KEY"):
        logger.error(" GOOGLE_API_KEY must be set.")
        sys.exit(1)
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN environment variable not set.")
        sys.exit(1)
        
    if not os.getenv("TELEGRAM_CONNECT_URL"):
        logger.error("TELEGRAM_CONNECT_URL environment variable not set.")
        sys.exit(1)
    logger.info("--- FastAPI Web Server for ADK Demo (with Telegram) Started ---")
    logger.info("Access your web chat UI at: http://127.0.0.1:8000/")
    logger.info("Access interactive API docs (Swagger UI) at: http://127.0.0.1:8000/docs")
    logger.info("To enable Telegram webhook, you need a public URL (e.g., via ngrok) and then run the set_webhook_url function.")
    set_telegram_webhook(os.getenv("TELEGRAM_CONNECT_URL"))
    get_telegram_webhook_info()

@app.on_event("shutdown")
async def shutdown_event():
    await telegram_http_client.aclose()
    logger.info("FastAPI application shutting down. HTTPX client closed.")
    delete_telegram_webhook()
    
    




async def set_telegram_webhook(webhook_url: str):
    # Create a new httpx.AsyncClient for this function's scope
    async with httpx.AsyncClient() as client:
        logger.info(f"Attempting to set Telegram webhook to: {webhook_url}/telegram-webhook")
        url = f"{TELEGRAM_API_BASE_URL}/setWebhook"
        payload = {"url": f"{webhook_url}/telegram-webhook"}

        try:
            response = await client.post(url, json=payload, timeout=10)
            response.raise_for_status()
            result = response.json()
            if result.get("ok"):
                logger.info(f"Telegram webhook set successfully: {result.get('description')}")
            else:
                logger.error(f"Failed to set Telegram webhook: {result.get('description', 'Unknown error')}")
        except httpx.HTTPStatusError as e:
            logger.error(f"Error setting webhook (HTTP Status {e.response.status_code}): {e.response.text}")
        except httpx.RequestError as e:
            logger.error(f"Network error setting webhook: {e}")

async def get_telegram_webhook_info():
    # Create a new httpx.AsyncClient for this function's scope
    async with httpx.AsyncClient() as client:
        logger.info("Attempting to get Telegram webhook info...")
        url = f"{TELEGRAM_API_BASE_URL}/getWebhookInfo"
        try:
            response = await client.get(url, timeout=10)
            response.raise_for_status()
            result = response.json()
            if result.get("ok"):
                logger.info(f"Telegram Webhook Info: {result.get('result')}")
            else:
                logger.error(f"Failed to get Telegram webhook info: {result.get('description', 'Unknown error')}")
        except httpx.HTTPStatusError as e:
            logger.error(f"Error getting webhook info (HTTP Status {e.response.status_code}): {e.response.text}")
        except httpx.RequestError as e:
            logger.error(f"Network error getting webhook info: {e}")

async def delete_telegram_webhook():
    # Create a new httpx.AsyncClient for this function's scope
    async with httpx.AsyncClient() as client:
        logger.info("Attempting to delete Telegram webhook...")
        url = f"{TELEGRAM_API_BASE_URL}/deleteWebhook"
        try:
            response = await client.post(url, timeout=10)
            response.raise_for_status()
            result = response.json()
            if result.get("ok"):
                logger.info(f"Telegram webhook deleted successfully: {result.get('description')}")
            else:
                logger.error(f"Failed to delete Telegram webhook: {result.get('description', 'Unknown error')}")
        except httpx.HTTPStatusError as e:
            logger.error(f"Error deleting webhook (HTTP Status {e.response.status_code}): {e.response.text}")
        except httpx.RequestError as e:
            logger.error(f"Network error deleting webhook: {e}")

#