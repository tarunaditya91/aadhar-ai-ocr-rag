import streamlit as st
import easyocr
import numpy as np
import cv2
import json
import re
import psycopg2
import os
from groq import Groq

from dotenv import load_dotenv
import os

load_dotenv()  # 🔥 MUST ADD


# =========================
# CONFIG
# =========================

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
# DB_URL = os.getenv("DB_URL")
DB_URL = os.getenv("DB_URL") or st.secrets["DB_URL"]

reader = easyocr.Reader(['en'])
client = Groq(api_key=GROQ_API_KEY)

st.title("🪪 Aadhaar Verification System")

# =========================
# LLM FUNCTIONS
# =========================

def build_prompt(text):
    return f"""
Extract Aadhaar details from the text below.

Return ONLY JSON in this format:
{{
  "name": "",
  "dob": "",
  "aadhaar": "",
  "gender": ""
}}

Text:
{text}
"""

def call_llm(prompt):
    response = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[{"role": "user", "content": prompt}],
        temperature=0
    )
    return response.choices[0].message.content


# =========================
# DB FUNCTIONS
# =========================

def get_connection():
    return psycopg2.connect(DB_URL)

def check_aadhaar(aadhaar):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT * FROM aadhar_data WHERE aadhaar = %s",
        (aadhaar,)
    )

    result = cursor.fetchone()
    conn.close()
    return result


# =========================
# MATCHING LOGIC
# =========================

def calculate_match_score(db_data, extracted_data):
    score = 0
    total = 4

    if db_data[1].lower() == extracted_data["name"].lower():
        score += 1

    if db_data[2] == extracted_data["dob"]:
        score += 1

    if db_data[3].replace(" ", "") == extracted_data["aadhaar"].replace(" ", ""):
        score += 1

    if db_data[4].lower() == extracted_data["gender"].lower():
        score += 1

    percentage = (score / total) * 100
    return score, percentage


# =========================
# MAIN PROCESS FUNCTION
# =========================

def process_image(file_bytes):

    # Save temp image
    with open("temp.png", "wb") as f:
        f.write(file_bytes)

    # OCR using EasyOCR
    results = reader.readtext("temp.png")
    ocr_text = " ".join([res[1] for res in results])

    st.subheader("📝 Extracted Text")
    st.write(ocr_text)

    # LLM
    response = call_llm(build_prompt(ocr_text))

    match = re.search(r"\{.*\}", response, re.DOTALL)

    if not match:
        return {"error": "Invalid LLM response"}

    data = json.loads(match.group())

    data["aadhaar"] = data["aadhaar"].replace(" ", "")

    # DB Check
    db_result = check_aadhaar(data["aadhaar"])

    if db_result:
        score, percent = calculate_match_score(db_result, data)

        return {
            "status": "matched",
            "percentage": percent,
            "data": data
        }
    else:
        return {
            "status": "not_found",
            "data": data
        }


# =========================
# RESULT DISPLAY
# =========================

def show_result(result):
    st.subheader("📊 Result")

    if result.get("status") == "matched":
        st.success("✅ Match Found")
        st.write(f"Match Percentage: {result.get('percentage', 0)}%")
    else:
        st.warning("❌ No Match Found")

    data = result.get("data", {})

    st.write("### Extracted Details:")
    st.write(f"👤 Name: {data.get('name', '-')}")
    st.write(f"📅 DOB: {data.get('dob', '-')}")
    st.write(f"🆔 Aadhaar: {data.get('aadhaar', '-')}")
    st.write(f"⚧ Gender: {data.get('gender', '-')}")


# =========================
# UI
# =========================

uploaded_file = st.file_uploader("📤 Upload Aadhaar Image", type=["png", "jpg", "jpeg"])

if uploaded_file:
    st.image(uploaded_file, caption="Uploaded Image", use_column_width=True)

    if st.button("Verify Aadhaar"):
        result = process_image(uploaded_file.getvalue())
        show_result(result) 