"""The texts we send to the local model, and the chat formats small models expect.

A model only follows instructions well when the prompt uses the exact chat
format it was trained on, so `wrap()` adds that format around our text.
"""

COMMIT_SYSTEM = (
    "You write git commit messages. Write a commit message for the change below. "
    "First line: a summary of at most 72 characters in the imperative mood "
    "(for example 'Add login rate limit'). Then a blank line, then at most 3 short "
    "bullet points starting with '- '. Output only the commit message, nothing else."
)

REVIEW_SYSTEM = (
    "You help a developer judge findings from a secret scanner. Each finding shows "
    "the rule, the file path and the line, with the secret partly hidden by * characters. "
    "For each finding write exactly one line in this form: "
    "<number>: <real|test|unsure> | <short reason>. "
    "Say 'test' only when the path or the names clearly show test, example or "
    "placeholder data. Output nothing else."
)

CHECK_SYSTEM = "You are a helpful assistant."
CHECK_QUESTION = "Reply with the single word OK."


def wrap(system: str, user: str, prompt_format: str) -> str:
    """Put the system and user text into the model's chat format, ready for its answer."""
    if prompt_format == "llama3":
        return (
            "<|begin_of_text|><|start_header_id|>system<|end_header_id|>\n\n"
            f"{system}<|eot_id|><|start_header_id|>user<|end_header_id|>\n\n"
            f"{user}<|eot_id|><|start_header_id|>assistant<|end_header_id|>\n\n"
        )
    # chatml: the format used by Qwen models
    return (
        f"<|im_start|>system\n{system}<|im_end|>\n"
        f"<|im_start|>user\n{user}<|im_end|>\n"
        "<|im_start|>assistant\n"
    )
