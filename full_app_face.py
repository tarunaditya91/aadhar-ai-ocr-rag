import streamlit as st
import easyocr
import json
import re
import psycopg2
import os
import requests
import tempfile
from groq import Groq
from dotenv import load_dotenv
from difflib import SequenceMatcher
import face_recognition

load_dotenv()

# =========================
# CONFIG
# =========================

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
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

Return ONLY JSON:
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
    try:
        return psycopg2.connect(DB_URL, sslmode="require", connect_timeout=10)
    except Exception as e:
        st.error(f"DB Error: {e}")
        return None

def check_aadhaar(aadhaar):
    conn = get_connection()
    if conn is None:
        return None

    cursor = conn.cursor()
    cursor.execute("SELECT * FROM aadhar_data WHERE aadhaar = %s", (aadhaar,))
    result = cursor.fetchone()

    cursor.close()
    conn.close()

    return result

# =========================
# HELPERS
# =========================

def normalize_text(text):
    return re.sub(r"\s+", " ", text.strip().lower()) if text else ""

def normalize_date(date):
    return re.sub(r"[-.]", "/", date) if date else ""

def normalize_aadhaar(aadhaar):
    return re.sub(r"\D", "", aadhaar)

def similar(a, b):
    return SequenceMatcher(None, a, b).ratio()

# =========================
# MATCHING LOGIC
# =========================

def calculate_match_score(db, ext):
    score = 0

    if similar(normalize_text(db[1]), normalize_text(ext["name"])) > 0.8:
        score += 1

    if normalize_date(db[2]) == normalize_date(ext["dob"]):
        score += 1

    if normalize_aadhaar(db[3]) == normalize_aadhaar(ext["aadhaar"]):
        score += 1

    if normalize_text(db[4]) == normalize_text(ext["gender"]):
        score += 1

    return score, (score / 4) * 100

# =========================
# 🔥 FACE MATCHING (UPDATED)
# =========================

def compare_faces(uploaded_path, db_image_url):
    try:
        # Download DB image
        response = requests.get(db_image_url, timeout=10)

        if response.status_code != 200:
            return False, "DB image not accessible"

        with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as f:
            f.write(response.content)
            db_path = f.name

        # Load images
        img1 = face_recognition.load_image_file(uploaded_path)
        img2 = face_recognition.load_image_file(db_path)

        # Get encodings
        enc1 = face_recognition.face_encodings(img1)
        enc2 = face_recognition.face_encodings(img2)

        # Debug
        print("Uploaded faces:", len(enc1))
        print("DB faces:", len(enc2))

        if len(enc1) == 0:
            return False, "No face in uploaded image"

        if len(enc2) == 0:
            return False, "No face in DB image"

        # 🔥 Distance-based matching
        distance = face_recognition.face_distance([enc1[0]], enc2[0])[0]

        print("Face distance:", distance)

        if distance < 0.5:
            return True, f"Match (distance={distance:.2f})"
        else:
            return False, f"No match (distance={distance:.2f})"

    except Exception as e:
        return False, f"Error: {e}"

# =========================
# MAIN FUNCTION
# =========================

def process_image(file_bytes):

    # Save uploaded image
    with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as f:
        f.write(file_bytes)
        img_path = f.name

    # OCR
    results = reader.readtext(img_path)
    text = " ".join([r[1] for r in results])

    st.subheader("📝 OCR Text")
    st.write(text)

    # LLM
    response = call_llm(build_prompt(text))
    match = re.search(r"\{.*\}", response, re.DOTALL)

    if not match:
        return {"error": "LLM parsing failed"}

    data = json.loads(match.group())
    data["aadhaar"] = normalize_aadhaar(data.get("aadhaar", ""))

    # DB lookup
    db = check_aadhaar(data["aadhaar"])

    if not db:
        return {"status": "not_found", "data": data}

    # Text match
    score, percent = calculate_match_score(db, data)

    # 🔥 FACE MATCH
    # face_match, face_msg = compare_faces(img_path, db[5])
    face_match = False
    face_msg = "Face matching disabled in cloud"

    return {
        "status": "matched",
        "percentage": percent,
        "face_match": face_match,
        "face_msg": face_msg,
        "data": data
    }

# =========================
# UI
# =========================

def show_result(res):
    st.subheader("📊 Result")

    if res.get("error"):
        st.error(res["error"])
        return

    if res["status"] == "matched":
        st.success("✅ Text Match Found")
        st.write(f"Match %: {res['percentage']}%")

        if res["face_match"]:
            st.success(f"🧠 Face Match: {res['face_msg']}")
        else:
            st.error(f"❌ Face Match Failed: {res['face_msg']}")

    else:
        st.warning("❌ No record found in DB")

    data = res.get("data", {})
    st.write("### Extracted Data")
    st.write(data)

# =========================
# STREAMLIT
# =========================

file = st.file_uploader("Upload Aadhaar", type=["jpg", "png", "jpeg"])

if file:
    st.image(file)

    if st.button("Verify"):
        result = process_image(file.getvalue())
        show_result(result)