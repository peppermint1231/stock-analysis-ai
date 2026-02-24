
import google.generativeai as genai
import streamlit as st

def get_gemini_response(prompt, api_key):
    """
    Sends the prompt to Google Gemini API and returns the response text.
    Uses 'gemini-1.5-flash' model for speed and efficiency.
    """
    try:
        genai.configure(api_key=api_key)
        
        # Generation Config
        generation_config = {
            "temperature": 0.7,
            "top_p": 0.95,
            "top_k": 40,
            "max_output_tokens": 8192,
        }
        
        # Safety Settings (Block mostly nothing for financial analysis context, but be safe)
        safety_settings = [
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
        ]

        model = genai.GenerativeModel(
            model_name="gemini-2.0-flash",
            generation_config=generation_config,
            safety_settings=safety_settings
        )

        response = model.generate_content(prompt)
        return response.text
        
    except Exception as e:
        return f"Gemini API 오류 발생: {str(e)}"
