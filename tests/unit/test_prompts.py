"""Every persona prompt must survive str.format (literal braces doubled), or that persona cannot start."""

from src.agent_runtime.personas import PERSONAS

FIELDS = dict(working_directory="w", file_location="f", artifacts_dir="a", python_executable="p", today="t", custom_instructions="")


def test_persona_prompts_format():
    for persona in PERSONAS.values():
        assert "{working_directory}" not in persona.system_prompt.format(**FIELDS), persona.name
