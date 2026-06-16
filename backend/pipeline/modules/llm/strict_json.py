from __future__ import annotations

from typing import Any, Callable


STRICT_JSON_SYSTEM_PREFIX = """
STRICT JSON CONTRACT:
- Return exactly one JSON object and nothing else.
- Do not include markdown, comments, explanations, prose outside JSON, or code fences.
- Use double quotes for every key and string value.
- Escape any double quote that appears inside a string value.
- Put commas between every object field and every array item.
- Do not use trailing commas.
- The response must parse with Python json.loads on the first attempt.
""".strip()


def generate_strict_json(
    provider,
    system_prompt: str,
    user_prompt: str,
    max_output_tokens: int,
    *,
    schema_name: str,
    validate: Callable[[dict[str, Any]], None] | None = None,
    attempts: int = 3,
) -> dict[str, Any]:
    """Request JSON from an LLM and retry when syntax or schema validation fails."""
    if attempts < 1:
        attempts = 1

    strict_system = f"{STRICT_JSON_SYSTEM_PREFIX}\n\n{system_prompt}"
    current_user_prompt = user_prompt
    errors: list[str] = []

    for attempt in range(1, attempts + 1):
        try:
            data = provider.generate_json(strict_system, current_user_prompt, max_output_tokens)
            if validate:
                validate(data)
            return data
        except ValueError as exc:
            errors.append(f"attempt {attempt}: {exc}")
            current_user_prompt = _retry_prompt(
                original_prompt=user_prompt,
                schema_name=schema_name,
                previous_error=str(exc),
            )

    raise ValueError(f"{schema_name} JSON failed strict validation after {attempts} attempts: {'; '.join(errors)}")


def require_keys(schema_name: str, required_keys: list[str]) -> Callable[[dict[str, Any]], None]:
    """Build a schema validator that requires top-level keys."""

    def validate(data: dict[str, Any]) -> None:
        missing = [key for key in required_keys if key not in data]
        if missing:
            raise ValueError(f"{schema_name} JSON is missing required keys: {', '.join(missing)}")

    return validate


def _retry_prompt(original_prompt: str, schema_name: str, previous_error: str) -> str:
    return f"""
Your previous {schema_name} response was invalid JSON or did not match the required schema.

Error to fix:
{previous_error}

Regenerate the full response from scratch.
Return exactly one valid JSON object only.
Do not include markdown, explanations, or text outside the JSON object.
Make sure every field and array item has the correct comma separators.
Make sure all strings are double-quoted and any inner double quotes are escaped.

Original task:
{original_prompt}
""".strip()
