from fastapi import FastAPI, UploadFile, File
import shutil
import cv2
import pytesseract
import json
import re
import psycopg2
from groq import Groq

# =========================
# CONFIG
# =========================

pytesseract.pytesseract.tesseract_cmd = "/opt/homebrew/bin/tesseract"
from dotenv import load_dotenv
import os

load_dotenv()  # 🔥 this line is missing in your code




app = FastAPI()

import os

GROQ_API_KEY = os.getenv("GROQ_API_KEY")

DB_URL = os.getenv("DB_URL")


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

Return ONLY JSON.
Do not add explanation.
Do not use ```json.
Return ONLY JSON.
Do not add explanation.
Do not use ```json.
Return ONLY JSON.
Do not add explanation.
Do not use ```json.

Text:
{text}
"""


def call_llm(prompt):
    client = Groq(api_key=GROQ_API_KEY)

    response = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[{"role": "user", "content": prompt}],
        temperature=0
    )

    return response.choices[0].message.content


# =========================
# DB FUNCTIONS
# =========================

# def get_connection():
#     return psycopg2.connect(DB_URL)

def get_connection():
    try:
        conn = psycopg2.connect(
            DB_URL,
            sslmode="require",
            connect_timeout=10
        )
        print("✅ DB CONNECTED")
        return conn
    except Exception as e:
        import traceback
        print("❌ FULL DB ERROR:")
        traceback.print_exc()   # 🔥 THIS LINE IS KEY
        return None


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

def process_aadhar(image_path):

    # OCR
    img = cv2.imread(image_path)

    if img is None:
        return {"error": "Image not found"}

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    _, thresh = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY)

    ocr_text = pytesseract.image_to_string(thresh)

    # LLM
    response = call_llm(build_prompt(ocr_text))

    # Clean JSON
    match = re.search(r"\{.*\}", response, re.DOTALL)

    if not match:
        return {"error": "LLM did not return valid JSON"}

    data = json.loads(match.group())

    # Normalize Aadhaar
    data["aadhaar"] = data["aadhaar"].replace(" ", "")

    # DB Check
    db_result = check_aadhaar(data["aadhaar"])

    if db_result:
        score, percent = calculate_match_score(db_result, data)

        return {
            "status": "matched",
            "score": score,
            "percentage": percent,
            "data": data
        }
    else:
        return {
            "status": "not_found",
            "data": data
        }


# =========================
# API ENDPOINT
# =========================

@app.post("/verify-aadhar")
async def verify_aadhar(file: UploadFile = File(...)):

    file_path = f"temp_{file.filename}"

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    result = process_aadhar(file_path)

    return result


# =========================
# TEST API
# =========================

@app.get("/")
def home():
    return {"message": "Aadhaar API running 🚀"}