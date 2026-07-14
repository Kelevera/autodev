"""Prompt templates for LLM-driven code improvements.

Every template demands raw code or raw JSON — never markdown fences or prose —
so responses can be written straight to disk after validation.
"""

SYSTEM_PROMPT = (
    "You are autodev, an automated software engineer that maintains a Python codebase. "
    "You always return exactly what is asked for: raw Python code or raw JSON. "
    "Never wrap output in markdown fences. Never add explanations."
)

TEST_GENERATION_PROMPT = """\
Given this Python module, generate comprehensive pytest tests including edge cases.
The module is importable as `{module_name}`.
Requirements:
- Import the code under test from `{module_name}`.
- Only test public functions and classes that actually exist in the module.
- Include at least one edge case per function where meaningful.
Return ONLY valid Python code for the test file, no markdown, no explanation.

{code}
"""

REFACTOR_PROMPT = """\
Given this complex Python module, refactor it to reduce cyclomatic complexity and
improve readability. Add type hints. Preserve the public API and behavior exactly:
all existing function/class names, signatures, and return values must keep working.
Return ONLY the complete refactored module code, no markdown, no explanation.

{code}
"""

DOCSTRING_PROMPT = """\
Add Google-style docstrings and type hints to this Python code.
Do not change any behavior, names, signatures, or logic — only add docstrings
and type annotations.
Return ONLY the complete updated code, no markdown, no explanation.

{code}
"""

REVIEW_PROMPT = """\
Review this git diff. Assess quality, potential bugs, and test coverage.
Return ONLY a JSON object with keys: approved (bool), issues (list of strings),
confidence (float between 0 and 1). No markdown, no explanation.

{diff}
"""

RETRY_SUFFIX = """\

Your previous attempt failed with this error:
{error}

Fix the problem. Return ONLY valid Python code, no markdown, no explanation.
"""

_PROMPT_FOR_JOB = {
    "add_tests": TEST_GENERATION_PROMPT,
    "refactor": REFACTOR_PROMPT,
    "add_docstrings": DOCSTRING_PROMPT,
}


def build_prompt(job_type: str, code: str, module_name: str = "", error: str = "") -> str:
    """Render the prompt for a job type, optionally appending a retry error."""
    template = _PROMPT_FOR_JOB[job_type]
    prompt = template.format(code=code, module_name=module_name)
    if error:
        prompt += RETRY_SUFFIX.format(error=error[-2000:])
    return prompt
