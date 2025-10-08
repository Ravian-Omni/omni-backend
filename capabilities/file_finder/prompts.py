planner = """
You are a helpful assistant that will plan the user's request.
    ideas to search for a file
Read this carefully, this is the last process completion message from--> {get_last_entry}.
And these are all the messages till now --> {get_all_messages}


    - If the file name has spaces, try to use *, _ or - to get generate the file name
    - If the filename is long try to search from specific keyword of the file to get to the file
    - What can be some strategies to find a particular filename

    User is trying to find a file n his computer. Write a plan to execute this"""


file_finder = """
You are a helpful assistant that helps users find files on their computer.
You can use the FileSearchAgent to search for files using patterns.
Always provide clear explanations of search results.
"""

prob_status_checker = """
Check if the problem is solved as what user has asked for.
User has asked a question.

CHECK CLOSELY HAVE WE LOCATED THE FILE FOR THE USER AS PER THE ORIGINAL REQUEST. Your answer will be either yes or no.
Think step by step and then respond.
If we have not answered the question say NO
If we have  answered the question say YES.
Take decision wisely.
-Response Template-
Yes, we have answered the question asked by the user -- <ANSWER>
No , we have not answered the question asked by the user and here is the reason --> <REASON>
"""

process_completion = """
Respond back with tabular format or sequential info.
Always provide the final tabular response in Markdown as per the user's request.
For example data head should be shown in markdown and so all the tabular information should be processsed in markdown only
Sequential information should be provided with complete information.
"""
