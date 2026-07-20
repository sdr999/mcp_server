"""Sample tool: basic text statistics. Also serves as an authoring example."""
from tools_sdk import tool


@tool(name="text_analyzer", description="Analyze text and provide basic statistics")
def text_analyzer(text: str) -> str:
    """
    Analyze text and provide basic statistics.

    Args:
        text: The text to analyze

    Returns:
        Analysis results including word count, character count, etc.
    """
    try:
        word_count = len(text.split())
        char_count = len(text)
        char_count_no_spaces = len(text.replace(" ", ""))
        sentence_count = text.count(".") + text.count("!") + text.count("?")

        analysis = f"""
Text Analysis Results:
- Word count: {word_count}
- Character count: {char_count}
- Character count (no spaces): {char_count_no_spaces}
- Estimated sentence count: {sentence_count}
- Average word length: {char_count_no_spaces / word_count if word_count > 0 else 0:.2f}
        """.strip()

        return analysis
    except Exception as e:
        return f"Error analyzing text: {str(e)}"
