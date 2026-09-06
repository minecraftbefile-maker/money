import os
import random
import subprocess
import requests
import json
import time
import sys
import traceback
import logging
import glob
import imageio_ffmpeg
from dotenv import load_dotenv
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
import uuid

FFMPEG_PATH = imageio_ffmpeg.get_ffmpeg_exe()

logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)s] ==> %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

load_dotenv()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
FISH_AUDIO_API_KEY = os.getenv("FISH_AUDIO_API_KEY")
BACKGROUND_VIDEO_URL = os.getenv("BACKGROUND_VIDEO_URL", "https://ia600403.us.archive.org/32/items/background_202609/Background.mp4")

TEXT_AI_MODEL = "google/gemma-2-9b-it:free"
TTS_MODEL_NAME = "s2.1-pro-free"
VOICE_MODEL_ID = "55542ca9d06d4111977d1f06c905a3a5"

TOKEN_FILE = 'token.json'
SCRIPT_FILE = 'video_scripts.txt'
CLIENT_SECRETS_FILE = 'client_secrets.json'

SCOPES = ['https://www.googleapis.com/auth/youtube.upload']

LANGUAGES = {
    "ar": "العربية (Arabic)",
    "en": "الإنجليزية (English)",
    "es": "الأسبانية (Spanish)",
    "ja": "اليابانية (Japanese)",
    "ru": "الروسية (Russian)"
}

def make_request_with_proxy_rotation(method, url, **kwargs):
    try:
        response = requests.request(method, url, **kwargs)
        return response
    except Exception as e:
        logging.warning(f"Direct request failed for {url}: {e}")
        raise e

def retry_request(func, *args, retries=3, backoff=2, **kwargs):
    last_exception = None
    for attempt in range(retries):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            last_exception = e
            logging.warning(f"Attempt {attempt+1}/{retries} failed: {e}")
            if attempt < retries - 1:
                time.sleep(backoff ** attempt)
    raise last_exception

def generate_multilingual_story():
    prompt = (
        "اكتب قصة قصيرة ومشوقة جداً لفيديو شورتس مدته دقيقة. "
        "قسّم القصة لجزئين متساويين (كل جزء حوالي 300-350 حرف). "
        "أريد القصة بـ 5 لغات: العربية (ar)، الإنجليزية (en)، الأسبانية (es)، اليابانية (ja)، والروسية (ru). "
        "أرجع الرد بصيغة JSON فقط بهذا التنسيق حصراً وبدون أي كود ماركداون إضافي:\n"
        "{\n"
        '   "ar": {"title": "عنوان القصة", "tags": ["قصص", "shorts"], "parts": ["الجزء1", "الجزء2"]},\n'
        '   "en": {"title": "Title", "tags": ["story", "shorts"], "parts": ["Part1", "Part2"]},\n'
        '   "es": {"title": "Título", "tags": ["historias", "shorts"], "parts": ["Parte1", "Parte2"]},\n'
        '   "ja": {"title": "タイトル", "tags": ["物語", "shorts"], "parts": ["パート1", "パート2"]},\n'
        '   "ru": {"title": "Заголовок", "tags": ["истории", "shorts"], "parts": ["Часть1", "Часть2"]}\n'
        "}"
    )
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com",
        "X-Title": "Tales from Null AI Generator"
    }
    payload = {
        "model": TEXT_AI_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.85
    }

    def _call_api():
        response = make_request_with_proxy_rotation(
            "post",
            "https://api.openrouter.ai/api/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=60
        )
        if response.status_code != 200:
            raise Exception(f"OpenRouter API error {response.status_code}: {response.text}")
        return response.json()

    response_json = retry_request(_call_api, retries=3)
    if 'choices' not in response_json or not response_json['choices']:
        raise Exception(f"Invalid response from OpenRouter: {response_json}")

    response_text = response_json['choices'][0]['message']['content'].strip()
    response_text = response_text.replace("```json", "").replace("```", "").strip()

    story_data = json.loads(response_text)
    return story_data

def save_scripts_to_text_file(story_data):
    with open(SCRIPT_FILE, 'w', encoding='utf-8') as f:
        f.write("===================================================\n")
        f.write(f"TTS MODEL: {TTS_MODEL_NAME} | VOICE ID: {VOICE_MODEL_ID}\n")
        f.write("===================================================\n\n")
        for lang_code, lang_name in LANGUAGES.items():
            if lang_code in story_data:
                data = story_data[lang_code]
                f.write(f"--- [ {lang_name} ({lang_code.upper()}) ] ---\n")
                f.write(f"TITLE: {data.get('title', '')}\n")
                f.write(f"TAGS: {', '.join(data.get('tags', []))}\n")
                f.write("NARRATION:\n")
                for idx, part in enumerate(data.get('parts', []), 1):
                    f.write(f"   Part {idx}: {part}\n")
                f.write("\n" + "="*50 + "\n\n")

def text_to_speech_fish(text_chunk, output_filename):
    headers = {
        "Authorization": f"Bearer {FISH_AUDIO_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "text": text_chunk,
        "reference_id": VOICE_MODEL_ID,
        "model": TTS_MODEL_NAME,
        "format": "mp3"
    }

    def _call_api():
        response = make_request_with_proxy_rotation(
            "post",
            "https://api.fish.audio/v1/tts",
            headers=headers,
            json=payload,
            timeout=60
        )
        if response.status_code != 200:
            raise Exception(f"Fish Audio API error {response.status_code}: {response.text}")
        return response.content

    audio_data = retry_request(_call_api, retries=3)
    with open(output_filename, 'wb') as f:
        f.write(audio_data)

def process_audio_for_language(lang_data, lang_code):
    parts = lang_data['parts']
    part_files = []
    unique_prefix = uuid.uuid4().hex[:8]
    final_audio = f"final_audio_{lang_code}_{unique_prefix}.mp3"

    try:
        for i, text in enumerate(parts):
            part_name = f"temp_{lang_code}_{i+1}_{unique_prefix}.mp3"
            text_to_speech_fish(text, part_name)
            part_files.append(part_name)

        list_file = f"list_{lang_code}_{unique_prefix}.txt"
        with open(list_file, 'w', encoding='utf-8') as f:
            for pf in part_files:
                f.write(f"file '{pf}'\n")

        subprocess.run(
            [FFMPEG_PATH, '-y', '-f', 'concat', '-safe', '0', '-i', list_file,
             '-c:a', 'libmp3lame', '-q:a', '2', final_audio],
            check=True,
            capture_output=True
        )
        return final_audio
    finally:
        for pf in part_files:
            if os.path.exists(pf):
                os.remove(pf)
        if 'list_file' in locals() and os.path.exists(list_file):
            os.remove(list_file)

def download_and_prepare_background():
    if not BACKGROUND_VIDEO_URL:
        raise Exception("BACKGROUND_VIDEO_URL is missing!")
    
    logging.info("Downloading background video from Internet Archive...")
    source_video = f"source_bg_{uuid.uuid4().hex[:8]}.mp4"
    
    response = requests.get(BACKGROUND_VIDEO_URL, stream=True, timeout=120)
    if response.status_code != 200:
        raise Exception(f"Failed to download background video, status code: {response.status_code}")
    
    with open(source_video, 'wb') as f:
        for chunk in response.iter_content(chunk_size=8192):
            if chunk:
                f.write(chunk)

    duration = 4200.0
    try:
        cmd_probe = [FFMPEG_PATH, '-i', source_video]
        result = subprocess.run(cmd_probe, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
        for line in result.stderr.splitlines():
            if "Duration:" in line:
                parts = line.split("Duration:")[1].split(",")[0].strip().split(":")
                duration = float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
                break
    except Exception as e:
        logging.warning(f"Duration extraction failed: {e}")

    max_start = int(duration) - 65
    start_time = random.randint(0, max_start if max_start > 0 else 0)
    output_slice = f"temp_background_slice_{uuid.uuid4().hex[:8]}.mp4"

    cmd_cut = [
        FFMPEG_PATH, '-y',
        '-ss', str(start_time),
        '-i', source_video,
        '-t', '60',
        '-c:v', 'libx264',
        '-c:a', 'aac',
        output_slice
    ]
    subprocess.run(cmd_cut, check=True, capture_output=True)
    
    if os.path.exists(source_video):
        os.remove(source_video)
        
    return output_slice

def render_video_ffmpeg(bg_video, main_audio, output_video):
    cmd = [
        FFMPEG_PATH, '-y',
        '-i', bg_video,
        '-i', main_audio,
        '-c:v', 'copy',
        '-c:a', 'aac',
        '-b:a', '192k',
        '-shortest',
        output_video
    ]
    subprocess.run(cmd, check=True, capture_output=True)

def get_youtube_service():
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(CLIENT_SECRETS_FILE):
                raise Exception(f"Missing {CLIENT_SECRETS_FILE}")
            flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRETS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, 'w') as token:
            token.write(creds.to_json())
    return build('youtube', 'v3', credentials=creds)

def upload_to_youtube(video_path, title, tags):
    youtube = get_youtube_service()
    body = {
        'snippet': {
            'title': title,
            'description': f"{title}\n\n#shorts",
            'tags': tags,
            'categoryId': '27'
        },
        'status': {
            'privacyStatus': 'public',
            'selfDeclaredMadeForKids': False
        }
    }
    media = MediaFileUpload(video_path, chunksize=5*1024*1024, resumable=True)
    request = youtube.videos().insert(part='snippet,status', body=body, media_body=media)
    response = None
    while response is None:
        status, response = request.next_chunk()
    return response['id']

def run_pipeline():
    generated_files = []
    try:
        logging.info("====================================")
        logging.info("Starting new automation cycle...")
        logging.info("====================================")

        story_data = generate_multilingual_story()
        save_scripts_to_text_file(story_data)

        audio_files = {}
        for lang_code in LANGUAGES.keys():
            if lang_code in story_data:
                audio_file = process_audio_for_language(story_data[lang_code], lang_code)
                audio_files[lang_code] = audio_file
                generated_files.append(audio_file)

        bg_video = download_and_prepare_background()
        generated_files.append(bg_video)

        output_video = f"final_shorts_{uuid.uuid4().hex[:8]}.mp4"
        render_video_ffmpeg(bg_video, audio_files["ar"], output_video)
        generated_files.append(output_video)

        ar_title = story_data["ar"]["title"]
        ar_tags = story_data["ar"]["tags"]
        upload_to_youtube(output_video, ar_title, ar_tags)

        logging.info("Automation cycle completed successfully!")

    except Exception as e:
        logging.error(f"Cycle failed: {str(e)}")
        logging.error(traceback.format_exc())
    finally:
        for f in generated_files:
            if os.path.exists(f):
                try:
                    os.remove(f)
                except OSError:
                    pass
        for pattern in ["temp_*.mp4", "temp_*.mp3", "final_audio_*.mp3", "final_shorts_*.mp4", "list_*.txt", "source_bg_*.mp4"]:
            for f in glob.glob(pattern):
                try:
                    os.remove(f)
                except:
                    pass
        logging.info("Cleanup completed.")

if __name__ == '__main__':
    run_pipeline()
