from enum import Enum

from pydantic import BaseModel, Field


class CompletionStatus(str, Enum):
    """Enum for image generation completion status."""

    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


class OutcomeStatus(str, Enum):
    """Enum for outcome achievement status."""

    ACHIEVED = "ACHIEVED"
    PARTIAL = "PARTIAL"
    NOT_ACHIEVED = "NOT_ACHIEVED"


class NextAction(str, Enum):
    """Enum for recommended next action after image generation."""

    READY_FOR_NEW_REQUESTS = "Ready for new requests"
    REGENERATION_NEEDED = "Regeneration needed"
    ERROR_RESOLUTION_REQUIRED = "Error resolution required"


class GeneratedImage(BaseModel):
    """Model for generated image information."""

    filename: str = Field(
        ..., description="Name of the generated image file with extension"
    )
    file_path: str = Field(..., description="Full path or URL to the generated image")

    # class Config:
    #     schema_extra = {
    #         "example": {
    #             "filename": "german_shepherd_portrait.jpg",
    #             "file_path": "/images/gen_001.jpg"
    #         }
    #     }
    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "filename": "german_shepherd_portrait.jpg",
                    "file_path": "/images/gen_001.jpg",
                }
            ]
        }
    }


class ProcessCompletionResponse(BaseModel):
    """Model for image generation process completion response."""

    status: CompletionStatus = Field(
        ..., description="Overall completion status of image generation"
    )
    outcome: OutcomeStatus = Field(
        ..., description="Whether the generated images meet user requirements"
    )
    generated_images: list[GeneratedImage] = Field(
        default_factory=list, description="List of successfully generated images"
    )
    summary: str = Field(
        ..., description="Brief 1-2 sentence summary of generation results"
    )
    issues: str | None = Field(
        default="NONE",
        description="Critical issues encountered during generation, or 'NONE' if no issues",
    )
    next_action: NextAction = Field(
        ..., description="Recommended next step for the user"
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "status": "COMPLETED",
                    "outcome": "ACHIEVED",
                    "generated_images": [
                        {
                            "filename": "german_shepherd_portrait.jpg",
                            "file_path": "/images/gen_001.jpg",
                        }
                    ],
                    "summary": "Generated photorealistic German Shepherd portrait with accurate breed characteristics and professional lighting.",
                    "issues": "NONE",
                    "next_action": "Ready for new requests",
                }
            ]
        }
    }
    # class Config:
    #     schema_extra = {
    #         "example": {
    #             "status": "COMPLETED",
    #             "outcome": "ACHIEVED",
    #             "generated_images": [
    #                 {
    #                     "filename": "german_shepherd_portrait.jpg",
    #                     "file_path": "/images/gen_001.jpg"
    #                 }
    #             ],
    #             "summary": "Generated photorealistic German Shepherd portrait with accurate breed characteristics and professional lighting.",
    #             "issues": "NONE",
    #             "next_action": "Ready for new requests"
    #         }
    #     }


# Additional response examples for different scenarios
class CompletionResponseExamples:
    """Collection of example responses for different completion scenarios."""

    SUCCESS_EXAMPLE = ProcessCompletionResponse(
        status=CompletionStatus.COMPLETED,
        outcome=OutcomeStatus.ACHIEVED,
        generated_images=[
            GeneratedImage(
                filename="german_shepherd_portrait.jpg", file_path="/images/gen_001.jpg"
            )
        ],
        summary="Generated photorealistic German Shepherd portrait with accurate breed characteristics and professional lighting.",
        issues="NONE",
        next_action=NextAction.READY_FOR_NEW_REQUESTS,
    )

    PARTIAL_EXAMPLE = ProcessCompletionResponse(
        status=CompletionStatus.PARTIAL,
        outcome=OutcomeStatus.PARTIAL,
        generated_images=[
            GeneratedImage(filename="logo_design.jpg", file_path="/images/gen_002.jpg")
        ],
        summary="Generated cartoon sun logo but colors are less vibrant than requested.",
        issues="Color saturation below specifications",
        next_action=NextAction.REGENERATION_NEEDED,
    )

    FAILED_EXAMPLE = ProcessCompletionResponse(
        status=CompletionStatus.FAILED,
        outcome=OutcomeStatus.NOT_ACHIEVED,
        generated_images=[],
        summary="Image generation failed due to prompt complexity.",
        issues="Prompt parsing error, model timeout",
        next_action=NextAction.ERROR_RESOLUTION_REQUIRED,
    )


# Usage example for integration
def validate_completion_response(response_data: dict) -> ProcessCompletionResponse:
    """Validate and parse the completion agent response.

    Args:
        response_data: Raw response dictionary from the completion agent

    Returns:
        ProcessCompletionResponse: Validated response object

    Raises:
        ValidationError: If response data doesn't match schema
    """
    return ProcessCompletionResponse(**response_data)


# JSON Schema generation for API documentation
def get_json_schema():
    """Generate JSON schema for API documentation."""
    return ProcessCompletionResponse.schema()


# Example usage in your application
if __name__ == "__main__":
    # Example of how to use the schema
    response_data = {
        "status": "COMPLETED",
        "outcome": "ACHIEVED",
        "generated_images": [
            {
                "filename": "german_shepherd_portrait.jpg",
                "file_path": "/images/gen_001.jpg",
            }
        ],
        "summary": "Generated photorealistic German Shepherd portrait with accurate breed characteristics.",
        "issues": "NONE",
        "next_action": "Ready for new requests",
    }

    # Validate the response
    validated_response = ProcessCompletionResponse(**response_data)
    print(validated_response.json(indent=2))

    # Generate JSON schema
    schema = ProcessCompletionResponse.schema()
    print("\nJSON Schema:")
    print(schema)
