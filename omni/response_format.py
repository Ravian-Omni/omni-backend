omni_planner_response_format = {
    "$defs": {
        "Task": {
            "type": "object",
            "title": "Task",
            "properties": {
                "task_id": {
                    "title": "Task ID",
                    "type": "integer"
                },
                "task": {
                    "title": "Task",
                    "type": "string"
                },
                "capability": {
                    "title": "Capability",
                    "type": "string",
                    "enum": [
                        "web_browser",
                        "python_coder",
                        "email_sender",
                        "file_finder",
                        "image_generator"
                    ]
                },
                "status": {
                    "title": "Status",
                    "type": "string",
                    "enum": ["pending", "in_progress", "completed"]
                },
                "details": {
                    "title": "Details",
                    "type": "string"
                }
            },
            "required": ["task_id", "task", "capability", "status", "details"]
        }
    },
    "title": "PlannerResponse",
    "type": "object",
    "properties": {
        "user_request": {
            "title": "User Request",
            "type": "string"
        },
        "breakdown": {
            "title": "Breakdown",
            "type": "array",
            "items": {
                "$ref": "#/$defs/Task"
            }
        },
        "overall_strategy": {
            "title": "Overall Strategy",
            "type": "string"
        }
    },
    "required": ["user_request", "breakdown", "overall_strategy"]
}