from autodev.llm.prompts import build_prompt


def test_BUILD_PROMPT():
    code = "some_code_here"
    module_name = "autodev.llm.prompts"
    job_type = "add_tests"

    prompt = build_prompt(job_type, code, module_name)
    assert "generate comprehensive pytest tests including edge cases." in prompt
    assert f"The module is importable as `{module_name}`." in prompt

def test_BUILD_PROMPT_with_error():
    code = "some_code_here"
    module_name = "autodev.llm.prompts"
    job_type = "add_tests"
    error = "Your previous attempt failed with this error: Some error message."

    prompt = build_prompt(job_type, code, module_name, error)
    assert "Some error message" in prompt
