from pydantic import BaseModel, HttpUrl ,Field
from enum import Enum
from typing import List, Optional






class QuestionCategory(str, Enum):
    """Enum for question classification categories"""
    FACTUAL = "factual"
    EXPLORATORY = "exploratory"


class QuestionClassification(BaseModel):
    """
    Pydantic model for question classification response from browser agent
    """
    question_category: QuestionCategory = Field(
        ...,
        description="Classification of the question as either FACTUAL or EXPLORATORY"
    )
    confidence: Optional[float] = Field(
        None,
        ge=0.0,
        le=1.0,
        description="Optional confidence score between 0.0 and 1.0"
    )
    reasoning: Optional[str] = Field(
        None,
        description="Optional brief explanation for the classification"
    )

    class Config:
        """Pydantic configuration"""
        use_enum_values = True
        json_encoders = {
            QuestionCategory: lambda v: v.value
        }

    def __str__(self) -> str:
        """String representation matching the required template"""
        return f"Question_category: {self.question_category.value}"
    




class TaskStatus(str, Enum):
    COMPLETED = "completed"
    FAILED = "failed"
    IN_PROGRESS = "in_progress"

class webprocess_completion(BaseModel):
    """Simple agent response model"""
    
    # Task completion
    task_completed: bool
    status: TaskStatus
    
    # Response content
    final_response: str
    content: Optional[str] = None
    
    # URLs and files
    urls: List[str] = []
    files: List[str] = []  # Complete file paths
    
    # Task details
    task_name: str
    error_message: Optional[str] = None