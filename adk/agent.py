from google.adk.agents import Agent
from google.adk.runners import Runner
from google.adk.tools import google_search
import os # To read environment variables


try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    print("Warning: python-dotenv not found. Environment variables must be set manually.")

class MyGoogleSearchAgent(Agent):
    def __init__(self, **kwargs):
        super().__init__(
            name="MyWebDemoAgent",
            instruction= """
           You are a helpful assistant. Answer user questions using Google Search when needed.
            """,
            model="gemini-2.0-flash", # Ensure this model is available in your GOOGLE_CLOUD_LOCATION
            tools=[google_search], # Add the Google Search tool here
            **kwargs
        )

    # The `run` method here is mainly for the agent's overall behavior.
    # The LLM's function calling capability, guided by your 'instruction'

    def run(self, input: str, **kwargs) -> str:
        # The ADK Runner handles the LLM's tool orchestration.
        # This method's explicit return might only be used if the LLM
        # doesn't decide to use a tool or for initial conversational turns.
        # For an agent with tools, the LLM determines the flow.
        return "Thinking... I might need to search for that."

if __name__ == "__main__":
    # --- Verify Environment Variables are set for Google Cloud/Vertex AI ---
    runner = Runner(agent=MyGoogleSearchAgent())
    runner.run() # This launches a simple command-line interface for testing