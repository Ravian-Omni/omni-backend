
from pydantic import BaseModel, Field, field_validator
from typing import List, Optional
from enum import Enum


class CompletionStatus(str, Enum):
    COMPLETED = "COMPLETED"
    PARTIALLY_COMPLETED = "PARTIALLY_COMPLETED"
    NOT_COMPLETED = "NOT_COMPLETED"


class OutcomeStatus(str, Enum):
    ACHIEVED = "ACHIEVED"
    PARTIALLY_ACHIEVED = "PARTIALLY_ACHIEVED"
    NOT_ACHIEVED = "NOT_ACHIEVED"


class ProcessStep(BaseModel):
    step_name: str = Field(..., description="Name of the process step")
    description: str = Field(..., description="Description of what happened in this step")


class image_data(BaseModel):
    """
    Pydantic model for structured agent responses with image generation capabilities.
    """
    
    # Core response content
    summary: str = Field(..., description="Main summary of the task completion")
    
    # Status tracking
    completion_status: CompletionStatus = Field(..., description="Overall completion status of the task")
    outcome_status: OutcomeStatus = Field(..., description="Whether the desired outcome was achieved")
    
    # Image-related fields
    full_image_paths: List[str] = Field(default_factory=list, description="List of all generated image file paths")
    
    # Process documentation
    process_steps: List[ProcessStep] = Field(default_factory=list, description="Detailed steps of the process")
    
    # Insights and learning
    key_insights: List[str] = Field(default_factory=list, description="Key insights and lessons learned")
    
    # Optional fields
    validation_notes: Optional[str] = Field(None, description="Notes about validation or quality checks")
    recommendations: Optional[str] = Field(None, description="Recommendations for next steps or improvements")
    error_messages: List[str] = Field(default_factory=list, description="Any error messages encountered")
    
    @property
    def image_count(self) -> int:
        """Returns the count of generated images."""
        return len(self.full_image_paths)
    
    @field_validator('full_image_paths')
    @classmethod
    def validate_image_paths(cls, v: List[str]) -> List[str]:
        """Validate that all image paths are non-empty strings."""
        if v:
            for path in v:
                if not isinstance(path, str) or not path.strip():
                    raise ValueError("All image paths must be non-empty strings")
        return v
    
    def add_process_step(self, step_name: str, description: str) -> None:
        """Helper method to add a process step."""
        self.process_steps.append(ProcessStep(step_name=step_name, description=description))
    
    def add_image_path(self, path: str) -> None:
        """Helper method to add an image path."""
        if path and path.strip():
            self.full_image_paths.append(path.strip())
    
    def add_insight(self, insight: str) -> None:
        """Helper method to add a key insight."""
        if insight and insight.strip():
            self.key_insights.append(insight.strip())