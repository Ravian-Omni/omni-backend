python_coder_description = """ This tool will be used to write any sort of python code."""

email_manager_description = """ This tool will be used for managing emails. It can perform the following tasks
          can reply to emails
          can send out emails with attachments"
          can read emails from the inbox and also save the attachments,
          can search emails based on subject, sender, date, etc."""

file_finder_description = """This tool Can find any file from the local MAC OS system"""

web_browser_description = """This tool will be used to search the web
Can be used to get real time information about any subject,
          It has all the credentials for all the website that user want you to surf
          It can be used for any question or topic that needs a web searching capability
 """

Image_generator_description = """It generates image from text as suggested by user """


def capability_descriptions():

    return {
        "python_coder": python_coder_description,
        "email_manager": email_manager_description,
        "file_finder": file_finder_description,
        "web_browser": web_browser_description,
        "image_generator": Image_generator_description
    }

if __name__ == "__main__":
    # Retrieve all capabilities and their descriptions
    all_caps = capability_descriptions()

    # Print all capabilities and their descriptions
    for capability, description in all_caps.items():
        print(f"Capability: {capability}\nDescription: {description}\n")  