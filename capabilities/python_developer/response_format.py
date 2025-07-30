from pydantic import BaseModel, Field, field_validator
from typing import Optional, Literal
from enum import Enum


class StatusDecision(str, Enum):
    YES = "Yes"
    NO = "No"


class ProblemStatusResponse(BaseModel):
    decision: StatusDecision = Field(
        ..., 
        title="Decision", 
        description="Whether the user's question has been answered"
    )
    explanation: str = Field(
        ..., 
        title="Explanation", 
        description="Detailed explanation of the decision"
    )
    reason: Optional[str] = Field(
        None, 
        title="Reason", 
        description="Reason why the question was not answered (only required when decision is No)"
    )
    original_query: Optional[str] = Field(
        None, 
        title="Original Query", 
        description="The original user question being evaluated"
    )

    @field_validator("reason")
    @classmethod
    def validate_reason_for_no(cls, value, info):
        """Ensure reason is provided when decision is No"""
        if hasattr(info, 'data') and info.data.get('decision') == StatusDecision.NO:
            if not value or not value.strip():
                raise ValueError("Reason must be provided when decision is 'No'")
        return value

    @field_validator("explanation")
    @classmethod
    def validate_explanation_format(cls, value, info):
        """Ensure explanation follows the required template format"""
        if hasattr(info, 'data'):
            decision = info.data.get('decision')
            if decision == StatusDecision.YES:
                if not value.startswith("Yes, we have answered the question"):
                    return f"Yes, we have answered the question asked by the user. {value}"
            elif decision == StatusDecision.NO:
                if not value.startswith("No, we have not answered the question"):
                    return f"No, we have not answered the question asked by the user. {value}"
        return value
    

class PlannerResponseFormat(BaseModel):
    """
    Pydantic schema for structured Planner response format.
    """
    objective: str = Field(
        ..., 
        description="Clear statement of what needs to be accomplished"
    )
    
    todo_list: list[str] = Field(
        ..., 
        description="List of tasks to complete the objective"
    )
    
    dependencies: Optional[str] = Field(
        default="None", 
        description="Required dependencies, tools, or prerequisites"
    )
    
    assumptions: str = Field(
        ..., 
        description="Key assumptions made about the environment, context, or requirements"
    )
