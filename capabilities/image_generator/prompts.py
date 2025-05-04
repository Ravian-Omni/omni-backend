user_intent = """
Based on the user's input understand the user intent and pass it to the next agent
the intent should be well explained 

Read this carefully, this is the last process completion message from--> {get_last_entry}. 
And these are all the messages till now --> {get_all_messages}

###RESPONSE TEMPLATE
Intent --> <intent>
"""

image_prompt_generator = """
Based on the intent provided try to write the best prompt to so that we can generate generate the images with that single prompt.

This prompt will be passed to the next agent to create the images.
Image generator prompt --> <prompt>
"""

process_completion = """
Respond back with tabular format for sequential info.
ALways provide the tabular response in JSON format. For example data head should be shown in JSON and so all the tabular information should be processsed in JSON only
Sequential information should be provided with complete information.
"""