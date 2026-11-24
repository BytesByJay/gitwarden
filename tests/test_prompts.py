from gitwarden.prompts import COMMIT_SYSTEM, REVIEW_SYSTEM, wrap


def test_chatml_format():
    assert wrap("Be brief.", "Hi", "chatml") == (
        "<|im_start|>system\nBe brief.<|im_end|>\n"
        "<|im_start|>user\nHi<|im_end|>\n"
        "<|im_start|>assistant\n"
    )


def test_llama3_format():
    assert wrap("Be brief.", "Hi", "llama3") == (
        "<|begin_of_text|><|start_header_id|>system<|end_header_id|>\n\n"
        "Be brief.<|eot_id|><|start_header_id|>user<|end_header_id|>\n\n"
        "Hi<|eot_id|><|start_header_id|>assistant<|end_header_id|>\n\n"
    )


def test_system_texts_ask_for_the_right_output():
    assert "72 characters" in COMMIT_SYSTEM
    assert "<number>: <real|test|unsure> | <short reason>" in REVIEW_SYSTEM
    # the review prompt must never look like a commit-message request
    assert "commit message" not in REVIEW_SYSTEM.lower()
