from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field, field_validator


class StatusDecision(str, Enum):
    YES = "Yes"
    NO = "No"


class ProblemStatusResponse(BaseModel):
    decision: StatusDecision = Field(
        ...,
        title="Decision",
        description="Whether the user's question has been answered",
    )
    explanation: str = Field(
        ..., title="Explanation", description="Detailed explanation of the decision"
    )
    reason: str | None = Field(
        None,
        title="Reason",
        description="Reason why the question was not answered (only required when decision is No)",
    )
    original_query: str | None = Field(
        None,
        title="Original Query",
        description="The original user question being evaluated",
    )

    @field_validator("reason")
    @classmethod
    def validate_reason_for_no(cls, value, info):
        """Ensure reason is provided when decision is No"""
        if hasattr(info, "data") and info.data.get("decision") == StatusDecision.NO:
            if not value or not value.strip():
                raise ValueError("Reason must be provided when decision is 'No'")
        return value

    @field_validator("explanation")
    @classmethod
    def validate_explanation_format(cls, value, info):
        """Ensure explanation follows the required template format"""
        if hasattr(info, "data"):
            decision = info.data.get("decision")
            if decision == StatusDecision.YES:
                if not value.startswith("Yes, we have answered the question"):
                    return (
                        f"Yes, we have answered the question asked by the user. {value}"
                    )
            elif decision == StatusDecision.NO:
                if not value.startswith("No, we have not answered the question"):
                    return f"No, we have not answered the question asked by the user. {value}"
        return value


# File Finder Process completion Response Format
class FileInfo(BaseModel):
    """Information about a single file found by the file finder agent"""

    file_name: str = Field(
        ..., title="File Name", description="Name of the file including extension"
    )
    directory: str = Field(
        ..., title="Directory", description="Directory path where the file is located"
    )
    full_path: str = Field(
        ..., title="Full Path", description="Complete absolute path to the file"
    )
    size: str = Field(
        ...,
        title="File Size",
        description="Human-readable file size (e.g., '55.7 KB', '1.2 MB')",
    )
    last_modified: datetime = Field(
        ...,
        title="Last Modified",
        description="Date and time when the file was last modified",
    )

    @field_validator("file_name")
    @classmethod
    def validate_file_name(cls, value):
        """Ensure file name is not empty"""
        if not value or not value.strip():
            raise ValueError("File name cannot be empty")
        return value.strip()

    @field_validator("full_path")
    @classmethod
    def validate_full_path(cls, value):
        """Ensure full path contains the file name"""
        if not value or not value.strip():
            raise ValueError("Full path cannot be empty")
        return value.strip()


class FileFinderResponse(BaseModel):
    """Complete response from the file finder agent"""

    message: str = Field(
        ...,
        title="Formatted Message",
        description="Human-readable formatted message summarizing the file search results",
    )
    files_found: list[FileInfo] = Field(
        default_factory=list,
        title="Files Found",
        description="List of files found by the search",
    )
    search_successful: bool = Field(
        True,
        title="Search Successful",
        description="Whether the file search was successful",
    )
    total_files_found: int = Field(
        0, title="Total Files Found", description="Total number of files found"
    )

    @field_validator("files_found")
    @classmethod
    def validate_files_found(cls, value):
        """Ensure files_found list is valid"""
        return value or []

    def model_post_init(self, __context) -> None:
        """Auto-populate total_files_found after model creation"""
        self.total_files_found = len(self.files_found)
