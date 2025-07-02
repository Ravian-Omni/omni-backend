from pydantic import BaseModel, Field, model_validator


# omni_planner_response_format = {
#     "$defs": {
#         "Task": {
#             "type": "object",
#             "title": "Task",
#             "properties": {
#                 "task_id": {
#                     "title": "Task ID",
#                     "type": "integer"
#                 },
#                 "task": {
#                     "title": "Task",
#                     "type": "string"
#                 },
#                 "capability": {
#                     "title": "Capability",
#                     "type": "string",
#                     "enum": [
#                         "web_browser",
#                         "python_coder",
#                         "email_sender",
#                         "file_finder",
#                         "dashboard_server",
#                         "image_generator",
#                         "mac_os_use"
#                     ]
#                 },
#                 "status": {
#                     "title": "Status",
#                     "type": "string",
#                     "enum": ["pending", "in_progress", "completed"]
#                 },
#                 "details": {
#                     "title": "Details",
#                     "type": "string"
#                 }
#             },
#             "required": ["task_id", "task", "capability", "status", "details"]
#         }
#     },
#     "title": "PlannerResponse",
#     "type": "object",
#     "properties": {
#         "user_request": {
#             "title": "User Request",
#             "type": "string"
#         },
#         "breakdown": {
#             "title": "Breakdown",
#             "type": "array",
#             "items": {
#                 "$ref": "#/$defs/Task"
#             }
#         },
#         "overall_strategy": {
#             "title": "Overall Strategy",
#             "type": "string"
#         }
#     },
#     "required": ["user_request", "breakdown", "overall_strategy"]
# }


from pydantic import BaseModel, Field
from typing import List, Optional
from enum import Enum



class Capability(str, Enum):
    WEB_BROWSER = "web_browser"
    PYTHON_CODER = "python_coder"
    EMAIL_SENDER = "email_sender"
    FILE_FINDER = "file_finder"
    IMAGE_GENERATOR = "image_generator"
    MANUAL_VERIFICATION = "manual_verification"


class Status(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


class Task(BaseModel):
    task_id: int
    task: str
    capability: Capability
    status: Status
    details: str
    detailed_result: str


class PlannerResponse(BaseModel):
    user_request: str
    breakdown: List[Task]
    overall_strategy: str





# omni_agent_aligner_rf={
#   "$defs": {
#     "Step": {
#       "properties": {
#         "question": {
#           "title": "Question",
#           "type": "string"
#         },
#         "thought": {
#           "title": "Thought",
#           "type": "string"
#         },
#         "action": {
#           "title": "Action",
#           "type": "string",
#           "enum": ["agent_router", "process_completion"]
#         }
#       },
#       "required": [
#         "question",
#         "thought",
#         "action"
#       ],
#       "title": "Step",
#       "type": "object"
#     }
#   },
#   "properties": {
#     "steps": {
#       "items": {
#         "$ref": "#/$defs/Step"
#       },
#       "title": "Steps",
#       "type": "array"
#     },
#     "final_answer": {
#       "title": "Final Answer",
#       "type": "string",
#       "enum": ["agent_router", "process_completion"]
#     }
#   },
#   "required": [
#     "steps",
#     "final_answer"
#   ],
#   "title": "AgentSelectionResponse",
#   "type": "object"
# }



# from pydantic import BaseModel, Field
# from typing import List, Literal

# class Step(BaseModel):
#     question: str = Field(..., title="Question")
#     thought: str = Field(..., title="Thought")
#     action: Literal["agent_router", "process_completion"] = Field(..., title="Action")

# class AgentSelectionResponse(BaseModel):
#     steps: List[Step] = Field(..., title="Steps")
#     final_answer: Literal["agent_router", "process_completion"] = Field(..., title="Final Answer")

#############################################
# Omni Agent Orchetrator Response Format    #
                                            #
#############################################


from pydantic import BaseModel, Field, field_validator
from typing import List, Literal

AllowedAgents = Literal["Planner_Agent", "agent_router", "process_completion", "manual_verification"]

class Step(BaseModel):
    question: str = Field(..., title="Question" , min_length=1)
    thought: str = Field(..., title="Thought", min_length=1)
    action: AllowedAgents = Field(..., title="Action", min_length=1)

class AgentSelectionResponse(BaseModel):
    steps: List[Step] = Field(..., title="Steps")
    final_answer: AllowedAgents = Field(..., title="Final Answer")

    @field_validator("final_answer")
    @classmethod
    def validate_single_agent_final(cls, value):
        if value not in ("Planner_Agent", "agent_router", "process_completion", "manual_verification"):
            raise ValueError("Final answer must be one of: Planner_Agent, agent_router, process_completion, manual_verification")
        return value

    @field_validator("steps")
    @classmethod
    def validate_single_agent_in_steps(cls, steps):
        for step in steps:
            if step.action not in ("Planner_Agent", "agent_router", "process_completion", "manual_verification"):
                raise ValueError("Each step's action must be one of: Planner_Agent, agent_router, process_completion, manual_verification")
        return steps

# from pydantic import BaseModel, Field, validator
# from typing import List, Literal

# AllowedAgents = Literal["Planner_Agent", "agent_router", "process_completion", "manual_verification"]

# class Step(BaseModel):
#     question: str = Field(..., title="Question")
#     thought: str = Field(..., title="Thought")
#     action: AllowedAgents = Field(..., title="Action")

# class AgentSelectionResponse(BaseModel):
#     steps: List[Step] = Field(..., title="Steps")
#     final_answer: AllowedAgents = Field(..., title="Final Answer")

#     @validator("final_answer")
#     def validate_single_agent_final(cls, value):
#         if value not in ("Planner_Agent", "agent_router", "process_completion", "manual_verification"):
#             raise ValueError("Final answer must be one of: agent_router, process_completion")
#         return value

#     @validator("steps", each_item=True)
#     def validate_single_agent_in_steps(cls, step):
#         if step.action not in ("Planner_Agent", "agent_router", "process_completion", "manual_verification"):
#             raise ValueError("Each step's action must be one of: agent_router, process_completion")
#         return step
    



from pydantic import BaseModel, Field, field_validator
from typing import List, Dict, Optional, Any
from enum import Enum


class Capability(str, Enum):
    PYTHON_CODER = "python_coder"
    EMAIL_SENDER = "email_sender"
    FILE_FINDER = "file_finder"
    WEB_BROWSER = "web_browser"
    IMAGE_GENERATOR = "image_generator"


class TaskCapabilityMapping(BaseModel):
    task: str = Field(..., title="Task", description="The complete details of the task needs to be executed")
    capability: Capability = Field(..., title="Capability", description="The capability to handle this task")
    task_id: Optional[int] = Field(None, title="Task ID", description="Optional task identifier")
    priority: Optional[int] = Field(None, title="Priority", description="Task priority for execution order")

    @field_validator("capability")
    @classmethod
    def validate_capability(cls, value):
        """Ensure only valid capabilities are assigned"""
        valid_capabilities = [
            Capability.PYTHON_CODER,
            Capability.EMAIL_SENDER,
            Capability.FILE_FINDER,
            Capability.WEB_BROWSER,
            Capability.IMAGE_GENERATOR
        ]
        if value not in valid_capabilities:
            raise ValueError(f"Capability must be one of: {[c.value for c in valid_capabilities]}")
        return value


class CapabilityRoutingResponse(BaseModel):
    task_assignments: List[TaskCapabilityMapping] = Field(
        ..., 
        title="Task Assignments", 
        description="List of task to capability mappings"
    )
    execution_notes: Optional[str] = Field(
        None, 
        title="Execution Notes", 
        description="Additional notes about task dependencies or parallel execution"
    )
    has_dependencies: bool = Field(
        False, 
        title="Has Dependencies", 
        description="Whether tasks have dependencies requiring sequential execution"
    )

    @field_validator("task_assignments")
    @classmethod
    def validate_non_empty_assignments(cls, value):
        """Ensure at least one task assignment is provided"""
        if not value:
            raise ValueError("At least one task assignment must be provided")
        return value
    



# class QuestionType(str, Enum):
#     """Enumeration of question classification types."""
#     CONVERSATION = "conversation"
#     TASK_ORIENTED = "task_oriented"


# class ConfidenceLevel(str, Enum):
#     """Enumeration of confidence levels for classification."""
#     HIGH = "High"
#     MEDIUM = "Medium"
#     LOW = "Low"


# class QuestionClassification(BaseModel):
#     """
#     Pydantic model for question classification results.
    
#     This model represents the output of a classification agent that
#     determines whether a user question is conversational or task-oriented.
#     """
    
#     classification: QuestionType = Field(
#         ...,
#         description="The primary classification of the question",
#         example=QuestionType.CONVERSATION
#     )
    
#     confidence: ConfidenceLevel = Field(
#         ...,
#         description="Confidence level of the classification decision",
#         example=ConfidenceLevel.HIGH
#     )
    
#     reasoning: str = Field(
#         ...,
#         min_length=10,
#         max_length=500,
#         description="Brief explanation of the classification decision",
#         example="Simple greeting seeking casual interaction"
#     )
    
#     original_question: str = Field(
#         ...,
#         min_length=1,
#         description="The original user question being classified",
#         example="How are you doing today?"
#     )
    
#     complexity_score: Optional[int] = Field(
#         None,
#         ge=1,
#         le=10,
#         description="Optional complexity score from 1-10, where 1 is simple and 10 is highly complex"
#     )
    
#     suggested_response_type: Optional[str] = Field(
#         None,
#         description="Optional suggestion for how to respond to this type of question"
#     )



from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class QuestionType(str, Enum):
    """Enumeration of question classification types."""
    CONVERSATION = "conversation"
    TASK_ORIENTED = "task_oriented"


class ConfidenceLevel(str, Enum):
    """Enumeration of confidence levels for classification."""
    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"


class QuestionClassification(BaseModel):
    """
    Pydantic model for question classification results.
    
    IMPORTANT FOR LLM: When setting eta_minutes, use this mapping based on complexity_score:
    - complexity_score 1: "1-5 minutes"
    - complexity_score 2: "5-12 minutes" 
    - complexity_score 3: "15-20 minutes"
    - complexity_score 4: "15-25 minutes"
    - complexity_score 5: "20-30 minutes"
    - complexity_score 6: "30-40 minutes"
    - complexity_score 7: "40-60 minutes"
    - complexity_score 8: "50-80 minutes"
    - complexity_score 9: "60-120 minutes"
    - complexity_score 10: "120-150 minutes"
    """
    classification: QuestionType = Field(
        ...,
        description="The primary classification of the question",
        example=QuestionType.CONVERSATION
    )
    confidence: ConfidenceLevel = Field(
        ...,
        description="Confidence level of the classification decision",
        example=ConfidenceLevel.HIGH
    )
    reasoning: str = Field(
        ...,
        min_length=10,
        max_length=500,
        description="Brief explanation of the classification decision",
        example="Simple greeting seeking casual interaction"
    )
    original_question: str = Field(
        ...,
        min_length=1,
        description="The original user question being classified",
        example="How are you doing today?"
    )
    complexity_score: Optional[int] = Field(
        None,
        ge=1,
        le=10,
        description="Optional complexity score from 1-10, where 1 is simple and 10 is highly complex"
    )
    suggested_response_type: Optional[str] = Field(
        None,
        description="Optional suggestion for how to respond to this type of question"
    )
    eta_minutes: Optional[str] = Field(
        None,
        description=(
            "Estimated time to complete the task. MUST correspond to complexity_score: "
            "1='1-5 minutes', 2='5-12 minutes', 3='15-20 minutes', 4='15-25 minutes', "
            "5='20-30 minutes', 6='30-40 minutes', 7='40-60 minutes', 8='50-80 minutes', "
            "9='60-120 minutes', 10='120-150 minutes'"
        ),
        example="15-20 minutes"
    )


# Alternative: Create a mapping that you can reference in your LLM prompt
COMPLEXITY_TO_ETA = {
    1: "1-5 minutes",
    2: "5-12 minutes",
    3: "15-20 minutes",
    4: "15-25 minutes", 
    5: "20-30 minutes",
    6: "30-40 minutes",
    7: "40-60 minutes",
    8: "50-80 minutes",
    9: "60-120 minutes",
    10: "120-150 minutes"
}


#Agent Caller Response format
# Define the exact structure you want
class FunctionCall(BaseModel):
    name: str
    arguments: str
    
    class Config:
        extra = "forbid"

class AgentCallerResponse(BaseModel):
    function_calls: List[FunctionCall]
    
    class Config:
        extra = "forbid"
