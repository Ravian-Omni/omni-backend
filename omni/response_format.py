from pydantic import BaseModel, Field, model_validator
from .country_data import country_codes
from .omni_handlers import _get_user_country
country = _get_user_country(country_codes)


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
    details_of_generated_files: Optional[str] = None
    complete_location_generated_files: Optional[str] = None


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

class UserCountry(BaseModel):
    """
    Pydantic model for user country information.
    """
    country_code: Optional[str] = Field(
        None,
        description="ISO country code (e.g., 'US', 'GB', 'IN')",
        example="US"
    )
    country_name: Optional[str] = Field(
        None,
        description="Full country name",
        example="Great Britain"
    )
    
    @classmethod
    def detect_country(cls) -> 'UserCountry':
        """Detect user's country using the imported function."""
        try:
            country = _get_user_country(country_codes)
            return cls(
                country_code=country.get('code') if isinstance(country, dict) else None,
                country_name=country.get('name') if isinstance(country, dict) else str(country) if country else None
            )
        except Exception:
            return cls(country_code=None, country_name=None)

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
        description="The complete original user question ",
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


    user_country_code: str = Field(
        ...,
        description=country["code"]
    )
    user_country_name: str = Field(
        ...,
        description=country["name"]
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








from pydantic import BaseModel, Field, field_validator
from typing import List, Optional, Dict, Any
from enum import Enum

class Status(str, Enum):
    COMPLETED = "COMPLETED"
    IN_PROGRESS = "IN_PROGRESS"
    FAILED = "FAILED"
    PARTIALLY_COMPLETED = "PARTIALLY_COMPLETED"


class SolutionStep(BaseModel):
    """Individual step in the problem-solving process."""
    step_number: int = Field(..., description="Sequential number of the step")
    step_title: str = Field(..., description="Title/name of the step")
    description: str = Field(..., description="Detailed description of what happens in this step")
    solution_details: Optional[str] = Field(None, description="Detailed solution and process")
    result: Optional[str] = Field(None, description="Result of this step")


class FileOutput(BaseModel):
    """Information about generated files."""
    file_name: str = Field(..., description="Name of the generated file")
    file_type: str = Field(..., description="Type of file (txt, json, pdf, etc.)")
    file_path: str = Field(..., description="Complete path to the file")
    description: Optional[str] = Field(None, description="Description of file contents")


class process_completion_response(BaseModel):
    """
    Pydantic model for process_completion agent responses.
    """
    
    # Core task information
    task_id: int = Field(..., description="Unique identifier for the task")
    task: str = Field(..., description="Description of the mathematical problem/task")
    status: Status = Field(..., description="Current status of the task")
    
    # Solution process
    solution_steps: List[SolutionStep] = Field(default_factory=list, description="All steps taken to solve the problem")
    
    # Results and details
    details: str = Field(..., description="General details about the solution process")
    detailed_result: str = Field(..., description="Comprehensive result with all calculations")
    
    # Final answers
    final_answers: List[str] = Field(default_factory=list, description="Final numerical or symbolic answers")
    
    # File outputs
    details_of_generated_files: Optional[str] = Field(None, description="Description of files that were generated")
    complete_location_generated_files: Optional[str] = Field(None, description="Complete path to directory containing generated files")
    generated_files: List[FileOutput] = Field(default_factory=list, description="List of generated files with details")
    
    # Summary and insights
    summary: str = Field(..., description="Summary of the problem-solving process")
    insights: List[str] = Field(default_factory=list, description="Key insights from the solution process")
    learnings: List[str] = Field(default_factory=list, description="Learnings and observations")
    
    # Additional metadata
    accuracy_notes: Optional[str] = Field(None, description="Notes about solution accuracy and precision")
    validation_performed: bool = Field(False, description="Whether the solution was validated")
    
    @field_validator('solution_steps')
    @classmethod
    def validate_solution_steps(cls, v: List[SolutionStep]) -> List[SolutionStep]:
        """Validate that step numbers are sequential."""
        if v:
            step_numbers = [step.step_number for step in v]
            if step_numbers != list(range(1, len(step_numbers) + 1)):
                raise ValueError("Step numbers must be sequential starting from 1")
        return v
    
    @field_validator('final_answers')
    @classmethod
    def validate_final_answers(cls, v: List[str]) -> List[str]:
        """Validate that final answers are non-empty strings."""
        if v:
            for answer in v:
                if not isinstance(answer, str) or not answer.strip():
                    raise ValueError("All final answers must be non-empty strings")
        return v
    
    @property
    def step_count(self) -> int:
        """Returns the total number of solution steps."""
        return len(self.solution_steps)
    
    @property
    def file_count(self) -> int:
        """Returns the total number of generated files."""
        return len(self.generated_files)
    
    def add_solution_step(self, step_title: str, description: str, 
                         equation_before: Optional[str] = None,
                         equation_after: Optional[str] = None,
                         calculation_details: Optional[str] = None,
                         result: Optional[str] = None) -> None:
        """Helper method to add a solution step."""
        step_number = len(self.solution_steps) + 1
        step = SolutionStep(
            step_number=step_number,
            step_title=step_title,
            description=description,
            equation_before=equation_before,
            equation_after=equation_after,
            calculation_details=calculation_details,
            result=result
        )
        self.solution_steps.append(step)
    
    def add_file_output(self, file_name: str, file_type: str, file_path: str, 
                       description: Optional[str] = None) -> None:
        """Helper method to add a generated file."""
        file_output = FileOutput(
            file_name=file_name,
            file_type=file_type,
            file_path=file_path,
            description=description
        )
        self.generated_files.append(file_output)
    
    def add_insight(self, insight: str) -> None:
        """Helper method to add an insight."""
        if insight and insight.strip():
            self.insights.append(insight.strip())
    
    def add_learning(self, learning: str) -> None:
        """Helper method to add a learning."""
        if learning and learning.strip():
            self.learnings.append(learning.strip())

