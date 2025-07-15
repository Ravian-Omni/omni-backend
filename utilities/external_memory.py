# omni_memory.py
import pandas as pd
import subprocess
import platform

from langchain_openai import AzureChatOpenAI

# llm = AzureChatOpenAI(
#     azure_deployment="gpt-4o-mini",  # or your deployment
#     api_version="2023-06-01-preview",  # or your api version
#     temperature=0,
#     azure_endpoint= "https://newton-aoi.openai.azure.com/",
#     api_key="Cq3mVjQS5sBySSyMhRTGkoI8okh0HbOjB4UxuV4txdBkB4ANUCflJQQJ99BCACYeBjFXJ3w3AAABACOG2GEt",
# )

llm = AzureChatOpenAI(
    azure_deployment="gpt-4.1-mini",
    api_version="2025-01-01-preview",
    temperature=0.1,
    azure_endpoint="https://newton-aoi.openai.azure.com/",
    api_key="Cq3mVjQS5sBySSyMhRTGkoI8okh0HbOjB4UxuV4txdBkB4ANUCflJQQJ99BCACYeBjFXJ3w3AAABACOG2GEt",
)



# Shared DataFrame with initial empty row
shared_df = pd.DataFrame(columns=["Last_Agent", "Completion_Message", "Cumulative_Summary"])
shared_df.loc[0] = ["", "", ""]  # Initial empty row




def speak_with_siri(message):
    """Use system's text-to-speech capabilities to speak the message with Siri voice"""
    system = platform.system()
    
    if system == "Darwin":  # macOS
        # Use macOS 'say' command with Siri voice
        subprocess.run(["say", "-v", "Samantha", message])
    elif system == "Windows":
        try:
            # For Windows, we can use PowerShell's speech synthesis
            powershell_cmd = f'Add-Type -AssemblyName System.Speech; $speak = New-Object System.Speech.Synthesis.SpeechSynthesizer; $speak.SelectVoice("Microsoft Zira Desktop"); $speak.Speak("{message}");'
            subprocess.run(["powershell", "-Command", powershell_cmd], shell=True)
        except Exception as e:
            print(f"Error using Windows speech: {e}")
    else:
        # For Linux or other systems, you might need to install and configure specific TTS engines
        print("Voice notification not supported on this platform. Please install appropriate TTS software.")
        print(f"Would have spoken: {message}")


def summarize_with_llm(previous_summary, new_message):
    """
    Summarizes conversation while preserving critical details (paths, IDs, etc.).
    """
    prompt = f"""
    Previous Summary (retain VERBATIM if critical): 
    {previous_summary}

    New Message from {new_message['Agent']}:
    {new_message['Raw_Message']}

    Generate a concise summary (3-4 sentences) for the next agent. PRESERVE:
    - File paths, URLs, code snippets (e.g., `/data/file_123.csv`).
    - Error messages, IDs, or numbers (e.g., "Error 404", "Ticket #4567").
    - Commands, approvals, or decisions (e.g., "Approved PR #42").
    - Email/content snippets marked as 'IMPORTANT'.
    Discard greetings, confirmations (e.g., "Thanks!"), and irrelevant context.
    """
    response = llm.invoke(prompt)
    return response.content

def update_conversation(shared_df,agent, raw_message):
    """Updates the conversation with a new message + summarized context."""
    new_entry = {"Agent": agent, "Raw_Message": raw_message}
    
    if shared_df.empty:
        summary = summarize_with_llm("", new_entry)
    else:
        previous_summary = shared_df["Cumulative_Summary"].iloc[-1]
        summary = summarize_with_llm(previous_summary, new_entry)
    
    return summary

def add_entry(agent_name: str, message: str):
    """Add new entry to the shared memory"""
    global shared_df
    summary = update_conversation(shared_df,agent_name,message)
    new_row = {"Last_Agent": agent_name, "Completion_Message": message, "Cumulative_Summary":summary}
    shared_df.loc[len(shared_df)] = new_row
    # response=llm.invoke(f"Summarize the message in a very short, crisp and clear way  for user to understand it  what has been achieved so far --> {message} ")
    announcement = f"The agent {agent_name}  has a message for you {summary}"
    # speak_with_siri(announcement)
    return True

def get_last_entry():
    """Get last entry as a formatted string"""
    last_row = shared_df.iloc[-1]
    return f"The agent --> {last_row['Last_Agent']}, has this message to share --> {last_row['Completion_Message']}"

def get_raw_dataframe():
    """Get the raw DataFrame for direct manipulation"""
    return shared_df

def get_context():
    return shared_df.iloc[-1]["Cumulative_Summary"]

def get_all_messages():
    """Get the raw DataFrame for direct manipulation"""
    la_list=shared_df['Last_Agent'].tolist() 
    cm_list=shared_df['Completion_Message'].tolist()  
    for last_agent_name, last_agent_msg in zip(la_list, cm_list):
        return f'The agent --> {last_agent_name}, has this message to share --> {last_agent_msg}'

