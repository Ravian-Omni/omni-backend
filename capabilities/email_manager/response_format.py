from enum import Enum
from typing import List, Optional, Union

from pydantic import BaseModel, Field, field_validator


class TaskStatus(str, Enum):
    COMPLETED = "COMPLETED"
    PARTIALLY_COMPLETED = "PARTIALLY_COMPLETED"
    NOT_COMPLETED = "NOT_COMPLETED"
    IN_PROGRESS = "IN_PROGRESS"


class OutcomeStatus(str, Enum):
    ACHIEVED = "ACHIEVED"
    PARTIALLY_ACHIEVED = "PARTIALLY_ACHIEVED"
    NOT_ACHIEVED = "NOT_ACHIEVED"


class QualityStatus(str, Enum):
    EXCELLENT = "EXCELLENT"
    GOOD = "GOOD"
    FAIR = "FAIR"
    POOR = "POOR"


class EmailMetadata(BaseModel):
    """Model for email metadata information."""

    message_id: Optional[str] = Field(None, description="Email message ID")
    senders_email_id: Optional[str] = Field(
        None, description="Email ID (sender's email address)"
    )
    subject: str = Field(..., description="Email subject line")
    sender: str = Field(..., description="Email sender (from field)")
    date: str = Field(..., description="Email date as string")
    content_snippet: str = Field(..., description="Brief content preview")
    attachments_count: int = Field(default=0, description="Number of attachments")

    @field_validator("attachments_count")
    @classmethod
    def validate_attachments_count(cls, v: int) -> int:
        """Validate that attachments count is non-negative."""
        if v < 0:
            raise ValueError("Attachments count cannot be negative")
        return v


class EmailProcessCompletion(BaseModel):
    """
    Pydantic model for structured email agent responses.
    """

    # Status tracking
    status: TaskStatus = Field(..., description="Overall task completion status")
    outcome: OutcomeStatus = Field(
        ..., description="Whether the desired outcome was achieved"
    )
    quality: QualityStatus = Field(..., description="Quality assessment of the result")

    # Request and delivery description
    what_was_requested: str = Field(
        ..., description="Description of what was originally requested"
    )

    # Email data (can be single email or list of emails)
    email_data: Union[EmailMetadata, List[EmailMetadata]] = Field(
        ..., description="Email metadata - single email or list"
    )

    # Achievements and insights
    key_achievements: List[str] = Field(
        default_factory=list, description="List of key achievements"
    )

    # Optional fields
    additional_notes: Optional[str] = Field(
        None, description="Any additional notes or observations"
    )
    error_messages: List[str] = Field(
        default_factory=list, description="Any error messages encountered"
    )
    warnings: List[str] = Field(
        default_factory=list, description="Any warnings or caveats"
    )

    @property
    def email_count(self) -> int:
        """Returns the count of emails processed."""
        if isinstance(self.email_data, list):
            return len(self.email_data)
        return 1 if self.email_data else 0

    @property
    def has_attachments(self) -> bool:
        """Returns True if any email has attachments."""
        if isinstance(self.email_data, list):
            return any(email.attachments_count > 0 for email in self.email_data)
        return self.email_data.attachments_count > 0 if self.email_data else False

    def add_achievement(self, achievement: str) -> None:
        """Helper method to add a key achievement."""
        if achievement and achievement.strip():
            self.key_achievements.append(achievement.strip())


#     def get_summary_text(self) -> str:
#         """Generate a formatted summary text similar to the original format."""
#         summary = f"""TASK COMPLETION SUMMARY
# ======================

# STATUS: {self.status.value}
# OUTCOME: {self.outcome.value}
# QUALITY: {self.quality.value}

# WHAT WAS REQUESTED:
# {self.what_was_requested}

# WHAT WAS DELIVERED:"""

#         # Handle email data display
#         if isinstance(self.email_data, list):
#             for i, email in enumerate(self.email_data, 1):
#                 summary += f"\n\nEmail {i}:"
#                 summary += self._format_email_data(email)
#         else:
#             summary += self._format_email_data(self.email_data)

#         if self.key_achievements:
#             summary += "\n\nKEY ACHIEVEMENTS:"
#             for achievement in self.key_achievements:
#                 summary += f"\n• {achievement}"

#         return summary

#     def _format_email_data(self, email: EmailMetadata) -> str:
#         """Format individual email data for display."""
#         email_id = email.message_id or email.email_id or ""
#         return f"""
# - message_id/email_id: {email_id}
# - subject: "{email.subject}"
# - from: "{email.sender}"
# - date: {email.date}
# - content snippet: "{email.content_snippet}"
# - attachments_count: {email.attachments_count}"""


class EmailIntent(str, Enum):
    """Enumeration of supported email intents."""

    SEND_EMAIL = "SEND_EMAIL"
    READ_EMAIL = "READ_EMAIL"
    REPLY_EMAIL = "REPLY_EMAIL"
    SEARCH_EMAIL = "SEARCH_EMAIL"


class IntentClassifier(BaseModel):
    """
    Pydantic model for Intent Classification Agent responses.
    """

    # Core classification fields
    intent: EmailIntent = Field(..., description="The classified intent category")
    reasoning: str = Field(
        ..., description="Brief explanation of why this intent was chosen"
    )
    next_action: str = Field(
        ..., description="What should happen next based on the classified intent"
    )

    # Optional metadata
    confidence_score: Optional[float] = Field(
        None,
        description="Confidence score (0.0-1.0) for the classification",
        ge=0.0,
        le=1.0,
    )
    user_input: Optional[str] = Field(
        None, description="The original user input that was classified"
    )
    # extracted_entities: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Any entities extracted from the user input")

    @field_validator("reasoning")
    @classmethod
    def validate_reasoning(cls, v: str) -> str:
        """Validate that reasoning is not empty."""
        if not v or not v.strip():
            raise ValueError("Reasoning cannot be empty")
        return v.strip()

    @field_validator("next_action")
    @classmethod
    def validate_next_action(cls, v: str) -> str:
        """Validate that next_action is not empty."""
        if not v or not v.strip():
            raise ValueError("Next action cannot be empty")
        return v.strip()

    def get_formatted_response(self) -> str:
        """Generate the formatted response as specified in the prompt."""
        return f"""INTENT: {self.intent.value}
REASONING: {self.reasoning}
NEXT_ACTION: {self.next_action}"""

    # def add_entity(self, key: str, value: Any) -> None:
    #     """Helper method to add extracted entities."""
    #     if self.extracted_entities is None:
    #         self.extracted_entities = {}
    #     self.extracted_entities[key] = value

    def get_intent_description(self) -> str:
        """Get a human-readable description of the intent."""
        descriptions = {
            EmailIntent.SEND_EMAIL: "User wants to send a new email (with or without attachments)",
            EmailIntent.READ_EMAIL: "User wants to read/fetch emails from inbox",
            EmailIntent.REPLY_EMAIL: "User wants to reply to a specific email",
            EmailIntent.SEARCH_EMAIL: "User wants to search for specific emails",
        }
        return descriptions.get(self.intent, "Unknown intent")

    @classmethod
    def create_send_email_response(cls, reasoning: str, next_action: str, **kwargs):
        """Factory method for SEND_EMAIL intent."""
        return cls(
            intent=EmailIntent.SEND_EMAIL,
            reasoning=reasoning,
            next_action=next_action,
            **kwargs,
        )

    @classmethod
    def create_read_email_response(cls, reasoning: str, next_action: str, **kwargs):
        """Factory method for READ_EMAIL intent."""
        return cls(
            intent=EmailIntent.READ_EMAIL,
            reasoning=reasoning,
            next_action=next_action,
            **kwargs,
        )

    @classmethod
    def create_reply_email_response(cls, reasoning: str, next_action: str, **kwargs):
        """Factory method for REPLY_EMAIL intent."""
        return cls(
            intent=EmailIntent.REPLY_EMAIL,
            reasoning=reasoning,
            next_action=next_action,
            **kwargs,
        )

    @classmethod
    def create_search_email_response(cls, reasoning: str, next_action: str, **kwargs):
        """Factory method for SEARCH_EMAIL intent."""
        return cls(
            intent=EmailIntent.SEARCH_EMAIL,
            reasoning=reasoning,
            next_action=next_action,
            **kwargs,
        )
