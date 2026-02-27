"""ai_client.py — Google Gemini API 클라이언트 (google-genai SDK)"""
from google import genai
from google.genai import types


def get_gemini_response(prompt: str, api_key: str) -> str:
    """Gemini API에 프롬프트를 전송하고 응답 텍스트를 반환합니다."""
    try:
        client = genai.Client(api_key=api_key)

        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.7,
                top_p=0.95,
                top_k=40,
                max_output_tokens=8192,
            ),
        )
        return response.text

    except Exception as e:
        return f"Gemini API 오류 발생: {str(e)}"
