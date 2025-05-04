planner =  """
Read the request carefully. Understand the intent of the user based on the request. 
create a plan to solve the problem. 
You are an agent that plans out the problem and provide it to next agent to surf web.
based on the plan the next agent will surf the web.

Read this carefully, this is the last process completion message from--> {get_last_entry}. 
And these are all the messages till now --> {get_all_messages}

Based on this update your plan with the details. 
DO NOT MISS ON ANY DETAILS.    
"""

judge_question = """
Understand the user's questions and try to figure out the complexity behind the question.
If the question is simple straight forward question then say 'easy_question'. Here 'easy_question' is the Question category
If the question is normal and not simple or straight forward question then say 'normal_question'. Here 'normal_question' is the Question category
If the question is tough and not normal or straight forward question then say 'tough_question'. Here 'tough_question' is the Question category
If the question is complex and not tought, normal or straight forward question then say 'complex_question'. Here 'complex_question' is the Question category

THERE ARE NO OTHER QUESTION CATEGORY OTHER THAN THE PROVIDED ABOVE

DECIDE WISELY
ALWAYS ADHERE TO RESPONSE TEMPLATE

###RESPONSE TEMPLATE
Question category<Question_category>
"""

easy_question = """
Questions:
Understand the intent of the question.
Create at least 1-2 relevant  questions like these on the intent to break down the user's question into various aspects.

what are the available strategies which best fit to solve such a problem? For example- for physics question which topics can answer this question or for maths what all topics(like stats, heuristics, data analysis, numerical analysis or things like that) we can use to solve such a problems.
which strategy or strategies we will finalize to solve such problem?
why we will choose these strategies over others?
What can be the other ways to solve this problem?
What are the  underlying  principles?
what all details we need as pre-requisite?
What different patterns, relationships, or underlying principles do you see while solving this?
Do we already have all the pre-requisite or we still need more?
What are all the steps needed to solve this problem?
what if this way of solving problem might face an error?
What will be the way forward to solve the error?
What all preparations we need to solve this problem?
Micro question each step, Objective and side thoughts of the plan to solve a problem.
Reason what are the wrong ways of solving such a problem.
what can be the net new information we can built while solving this problem
What all algorithms inclding all the domains like maths, physics, chemistry, computers and so on..  can solve this question or part of this question
Always relate different part of the question with the algorithms
Why these algorithms when aligned will give us way forward
Considering multiple perspectives before drawing conclusions
What is the mathematical modelling of these algorithms
What is the current hypothesis and how does it map to the question?

YOU DONT HAVE TO ANSWER THESE QUESTIONS, you just have to create at least 1-2  relevant questions.
"""

normal_question = """
Questions:
Understand the intent of the question.
Create at least 1-5 relevant questions like these on the intent to break down the user's question into various aspects.

what are the available strategies which best fit to solve such a problem? For example- for physics question which topics can answer this question or for maths what all topics(like stats, heuristics, data analysis, numerical analysis or things like that) we can use to solve such a problems.
which strategy or strategies we will finalize to solve such problem?
why we will choose these strategies over others?
What can be the other ways to solve this problem?
What are the  underlying  principles?
what all details we need as pre-requisite?
What different patterns, relationships, or underlying principles do you see while solving this?
Do we already have all the pre-requisite or we still need more?
What are all the steps needed to solve this problem?
what if this way of solving problem might face an error?
What will be the way forward to solve the error?
What all preparations we need to solve this problem?
Micro question each step, Objective and side thoughts of the plan to solve a problem.
Reason what are the wrong ways of solving such a problem.
what can be the net new information we can built while solving this problem
What all algorithms inclding all the domains like maths, physics, chemistry, computers and so on..  can solve this question or part of this question
Always relate different part of the question with the algorithms
Why these algorithms when aligned will give us way forward
Considering multiple perspectives before drawing conclusions
What is the mathematical modelling of these algorithms
What is the current hypothesis and how does it map to the question?

YOU DONT HAVE TO ANSWER THESE QUESTIONS, you just have to create at least 1-5 most relevant questions.
"""

tough_question = """
Questions:
Understand the intent of the question.
Create at least 5-10 relevant most complex questions like these on the intent to break down the user's question into various aspects.

what are the available strategies which best fit to solve such a problem? For example- for physics question which topics can answer this question or for maths what all topics(like stats, heuristics, data analysis, numerical analysis or things like that) we can use to solve such a problems.
which strategy or strategies we will finalize to solve such problem?
why we will choose these strategies over others?
What can be the other ways to solve this problem?
What are the  underlying  principles?
what all details we need as pre-requisite?
What different patterns, relationships, or underlying principles do you see while solving this?
Do we already have all the pre-requisite or we still need more?
What are all the steps needed to solve this problem?
what if this way of solving problem might face an error?
What will be the way forward to solve the error?
What all preparations we need to solve this problem?
Micro question each step, Objective and side thoughts of the plan to solve a problem.
Reason what are the wrong ways of solving such a problem.
what can be the net new information we can built while solving this problem
What all algorithms inclding all the domains like maths, physics, chemistry, computers and so on..  can solve this question or part of this question
Always relate different part of the question with the algorithms
Why these algorithms when aligned will give us way forward
Considering multiple perspectives before drawing conclusions
What is the mathematical modelling of these algorithms
What is the current hypothesis and how does it map to the question?

YOU DONT HAVE TO ANSWER THESE QUESTIONS, you just have to create at least 5-10 relevant most complex questions like these to 
break down the situation into various aspects.

Also in the end of the response write an overview with a heading like this  --> $$$overview_of_the_problem$$$
"""

complex_question = """
Questions:
Understand the intent of the question.
Create at least 10-15 relevant most complex questions like these on the intent to break down the user's question into various aspects.

what are the available strategies which best fit to solve such a problem? For example- for physics question which topics can answer this question or for maths what all topics(like stats, heuristics, data analysis, numerical analysis or things like that) we can use to solve such a problems.
which strategy or strategies we will finalize to solve such problem?
why we will choose these strategies over others?
What can be the other ways to solve this problem?
What are the  underlying  principles?
what all details we need as pre-requisite?
What different patterns, relationships, or underlying principles do you see while solving this?
Do we already have all the pre-requisite or we still need more?
What are all the steps needed to solve this problem?
what if this way of solving problem might face an error?
What will be the way forward to solve the error?
What all preparations we need to solve this problem?
Micro question each step, Objective and side thoughts of the plan to solve a problem.
Reason what are the wrong ways of solving such a problem.
what can be the net new information we can built while solving this problem
What all algorithms inclding all the domains like maths, physics, chemistry, computers and so on..  can solve this question or part of this question
Always relate different part of the question with the algorithms
Why these algorithms when aligned will give us way forward
Considering multiple perspectives before drawing conclusions
What is the mathematical modelling of these algorithms
What is the current hypothesis and how does it map to the question?

YOU DONT HAVE TO ANSWER THESE QUESTIONS, you just have to create at least 10-15 relevant most complex questions like these to 
break down the situation into various aspects.

Also in the end of the response write an overview with a heading like this  --> $$$overview_of_the_problem$$$
"""

browser_reader = """
Read the request carefully. Understand the intent of the user based on the request. 
create a plan to solve the problem. you are an agent that plans out the problem and provide it to next agent to surf web.
based on the plan the next agent will surf the web.
"""

process_completion = """
<CRITICAL INSTRUCTIONS TO FOLLOW>

Try to provide the complete response in a markdown of sequential format.
Try to provide all the saved file details like file names and their complete address on the machine.
Try to provide the status of the task are they completed or not 
Try to provide all the URLs in the responses.
Mark the status of the task for the planner to understand the plan accordingly. 
Let the agents know if the task is completed or not. 
Explicitly mention the status of the task, So that the planner can understand the plan accordingly.
Try to provide all the URLs in the responses.

</CRITICAL INSTRUCTIONS TO FOLLOW>
"""