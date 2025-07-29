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
    
    model_config = {
        "use_enum_values": True,
        "json_encoders": {
            QuestionCategory: lambda v: v.value
        }
    }

    # class Config:
    #     """Pydantic configuration"""
    #     use_enum_values = True
    #     json_encoders = {
    #         QuestionCategory: lambda v: v.value
    #     }

    def __str__(self) -> str:
        """String representation matching the required template"""
        return f"Question_category: {self.question_category.value}"
    




class TaskStatus(str, Enum):
    COMPLETED = "completed"
    FAILED = "failed"
    IN_PROGRESS = "in_progress"
    PARTIALLY_COMPLETED = "partially_completed"

class FileInfo(BaseModel):
    """Information about a downloaded or generated file"""
    filename: str = Field(..., description="Name of the file")
    full_path: str = Field(..., description="Complete absolute path to the file")
    file_type: str = Field(..., description="File extension/type (e.g., 'pdf', 'png', 'csv')")
    size_bytes: Optional[int] = Field(None, description="File size in bytes")
    download_source: Optional[str] = Field(None, description="URL or source where file was downloaded from")
    created_during_task: bool = Field(True, description="Whether this file was created/downloaded during this task")
    
    # @validator('full_path')
    # def validate_path_exists(cls, v):
    #     """Validate that the file path exists"""
    #     if v and not os.path.exists(v):
    #         raise ValueError(f"File path does not exist: {v}")
    #     return v
    
    # @validator('file_type', pre=True)
    # def extract_file_type(cls, v, values):
    #     """Extract file type from filename if not provided"""
    #     if not v and 'filename' in values:
    #         return Path(values['filename']).suffix.lstrip('.')
    #     return v

class URLInfo(BaseModel):
    """Information about URLs visited or referenced"""
    url: str = Field(..., description="The complete URL")
    title: Optional[str] = Field(None, description="Page title if available")
    visited: bool = Field(True, description="Whether this URL was actually visited")
    relevant_to_task: bool = Field(True, description="Whether this URL is relevant to the main task")

class WebProcessCompletion(BaseModel):
    """Enhanced web browser agent response model"""
    
    # Task completion status
    task_completed: bool = Field(..., description="Whether the main task was completed successfully")
    status: TaskStatus = Field(..., description="Overall task status")
    
    # Primary response content
    final_response: str = Field(..., description="Main response or summary of what was accomplished")
    detailed_content: Optional[str] = Field(None, description="Detailed content extracted or generated")
    
    # URLs with metadata
    urls_visited: List[URLInfo] = Field(default_factory=list, description="URLs that were visited during the task")
    urls_referenced: List[str] = Field(default_factory=list, description="URLs mentioned but not necessarily visited")
    
    # Files with complete information
    downloaded_files: List[FileInfo] = Field(default_factory=list, description="Files downloaded during the task")
    generated_files: List[FileInfo] = Field(default_factory=list, description="Files generated/created during the task")
    
    # Task metadata
    task_name: str = Field(..., description="Name or description of the task")
    
    # Error handling
    error_message: Optional[str] = Field(None, description="Error message if task failed")
    warnings: List[str] = Field(default_factory=list, description="Any warnings encountered during execution")
