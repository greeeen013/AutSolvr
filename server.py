import os
import json
import logging
from flask import Flask, request, jsonify
from PIL import Image
import pytesseract
from thefuzz import process, fuzz
import google.generativeai as genai
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Load environment variables
load_dotenv()
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
if GOOGLE_API_KEY:
    try:
        genai.configure(api_key=GOOGLE_API_KEY)
    except Exception as e:
         logging.error(f"Failed to configure Gemini: {e}")
else:
    logging.warning("GOOGLE_API_KEY not found in .env processing.")

app = Flask(__name__)

# Configuration
# Users might need to set the tesseract path if it's not in PATH
# Common default installation path for Windows
tesseract_path = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
if os.path.exists(tesseract_path):
    pytesseract.pytesseract.tesseract_cmd = tesseract_path
else:
    tesseract_path_x86 = r'C:\Program Files (x86)\Tesseract-OCR\tesseract.exe'
    if os.path.exists(tesseract_path_x86):
        pytesseract.pytesseract.tesseract_cmd = tesseract_path_x86
    else:
        # Fallback to local user appdata or just warn
        logging.warning(f"Tesseract not found in {tesseract_path} or {tesseract_path_x86}. Hoping it's in PATH.")

DATA_FILE = 'answers.json'

def load_data():
    """Loads the question/answer data from answers.json."""
    try:
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data.get('questions', [])
    except Exception as e:
        logging.error(f"Failed to load {DATA_FILE}: {e}")
        return []

QUESTIONS_DB = load_data()

def get_answers_from_gemini(image):
    """Fallback to Gemini to find answers in the image."""
    if not GOOGLE_API_KEY:
        logging.error("Cannot use Gemini fallback: No API Key.")
        return []
    
    try:
        logging.info("Querying Gemini for answers...")
        model = genai.GenerativeModel('gemini-2.0-flash')
        
        prompt = (
            "Analyze this image which contains a multiple-choice question. "
            "Identify the correct answer(s). "
            "Return ONLY the exact text of the correct answer(s), one per line. "
            "Do not include any explanation or numbering."
        )
        
        response = model.generate_content([prompt, image])
        
        if response.text:
            answers = [line.strip() for line in response.text.split('\n') if line.strip()]
            logging.info(f"Gemini suggests answers: {answers}")
            return answers
    except Exception as e:
        logging.error(f"Gemini API error: {e}")
    
    return []

@app.route('/solve', methods=['POST'])
def solve():
    if 'image' not in request.files:
        return jsonify({'error': 'No image part'}), 400
    
    file = request.files['image']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400

    try:
        image = Image.open(file.stream)
        
        # 1. OCR processing
        # Use local tessdata config via environment variable
        cwd = os.getcwd()
        local_tessdata = os.path.join(cwd, "tessdata")
        if os.path.exists(os.path.join(local_tessdata, "ces.traineddata")):
            os.environ["TESSDATA_PREFIX"] = local_tessdata
        
        ocr_data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT, lang='ces')
        
        # Build a list of valid words and their spatial info
        valid_words = []
        for i in range(len(ocr_data['text'])):
            text = ocr_data['text'][i].strip()
            if text and int(ocr_data['conf'][i]) > 0:
                valid_words.append({
                    'text': text,
                    'x': ocr_data['left'][i],
                    'y': ocr_data['top'][i],
                    'w': ocr_data['width'][i],
                    'h': ocr_data['height'][i]
                })

        # Reconstruct full text for searching, but keep track of indices
        # We join with spaces, so we need to account for that in mapping if we use indices
        # Simplified: valid_words is our sequence.
        full_text_list = [w['text'] for w in valid_words]
        full_text_str = " ".join(full_text_list)
        
        logging.info(f"OCR extracted text length: {len(full_text_str)}")

        # 2. Find Question
        question_texts = [q['text'] for q in QUESTIONS_DB]
        match_result = process.extractOne(full_text_str, question_texts, scorer=fuzz.partial_ratio)
        
        best_match_q = None
        if match_result:
            matched_text, score = match_result
            if score > 60: # Lower threshold to be safe, fuzzy match is powerful
                logging.info(f"Found question match: '{matched_text[:30]}...' with score {score}")
                for q in QUESTIONS_DB:
                    if q['text'] == matched_text:
                        best_match_q = q
                        break
            else:
                 logging.warning(f"Best match score too low: {score}")

        correct_answers = []
        if best_match_q:
             correct_answers = [a['text'] for a in best_match_q['answers'] if a['isCorrect']]
        else:
             logging.info("Question not found in DB. Attempting Gemini fallback.")
             correct_answers = get_answers_from_gemini(image)

        if not correct_answers:
             return jsonify({'error': 'Question not found and fallback failed'}), 404

        # 3. Find Correct Answers (Logic merged above)
        logging.info(f"Looking for answers: {len(correct_answers)} found required.")
        
        click_coordinates = []

        # 4. Locate Answers on Screen
        # Strategy: Search for the answer text within the full_text_str.
        # Use fuzzy search to find the *best matching substring* in the OCR text.
        # Then map that substring back to the list of words.

        for answer in correct_answers:
            # We want to find where 'answer' appears in 'full_text_str'
            # process.extractOne with the answer against segments of text could work,
            # or simply fuzz.partial_ratio of answer vs full_text isn't enough to give location.
            
            # Use a sliding window of words to find the best match for this answer
            target_len = len(answer.split())
            best_window_score = 0
            best_window_idx = -1
            best_window_len = 0
            
            # We assume the answer in OCR might have +/- a few words
            # Widen the search window significantly to handle OCR fragmentation or checking
            min_len = max(1, int(target_len * 0.6))
            max_len = int(target_len * 2.0) + 2
            
            best_candidate_text = ""

            # Optimization: only scan windows if we have enough words
            if len(valid_words) >= min_len:
                for length in range(min_len, max_len + 1):
                    for i in range(len(valid_words) - length + 1):
                        window_text = " ".join([w['text'] for w in valid_words[i : i + length]])
                        score = fuzz.ratio(answer, window_text)
                        
                        if score > best_window_score:
                            best_window_score = score
                            best_window_idx = i
                            best_window_len = length
                            best_candidate_text = window_text
            
            if best_window_score > 65: # Good confidence match (slightly lowered)
                # Calculate center of this block
                words_in_window = valid_words[best_window_idx : best_window_idx + best_window_len]
                
                # Bounding box of the phrase
                min_x = min(w['x'] for w in words_in_window)
                min_y = min(w['y'] for w in words_in_window)
                max_x = max(w['x'] + w['w'] for w in words_in_window)
                max_y = max(w['y'] + w['h'] for w in words_in_window)
                
                center_x = min_x + (max_x - min_x) // 2
                center_y = min_y + (max_y - min_y) // 2
                
                click_coordinates.append({"x": center_x, "y": center_y, "text": answer})
                logging.info(f"Found answer: '{answer}' at {center_x}, {center_y} (Score: {best_window_score})")
            else:
                logging.warning(f"Could not find answer on screen: '{answer[:20]}...' Best score: {best_window_score} for '{best_candidate_text[:30]}...'")

        return jsonify(click_coordinates)

    except Exception as e:
        logging.error(f"Error processing image: {e}")
        # import traceback
        # traceback.print_exc()
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    # Threaded=True for handling multiple requests (though client is single user)
    app.run(host='0.0.0.0', port=5000, debug=True)
