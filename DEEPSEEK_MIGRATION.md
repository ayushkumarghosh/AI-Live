# DeepSeek / OpenRouter Notes

DeepSeek support is optional in the current manual transcript app.

The visible overlay buttons use Gemini by default:

- Text Input
- Code Analysis
- General Analysis
- Repeat Analysis

`chat.py` still includes `analyze_with_deepseek_model()` for future or external use. Because DeepSeek models do not accept the app's screenshot/audio inputs directly, that helper first asks Gemini to describe screenshots, then sends a text-only prompt to OpenRouter.

## Environment

Use `DEEPSEEK` for the OpenRouter API key:

```env
DEEPSEEK=your_openrouter_api_key_here
```

`OPENROUTER_API_KEY` is also accepted as a fallback for compatibility.

## Current Status

- No overlay button calls DeepSeek directly.
- DeepSeek chat history is separate from Gemini chat history.
- Clearing history resets both histories.
- Runtime dependencies do not include a separate OpenRouter package; calls use `requests`.
