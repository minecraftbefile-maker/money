import asyncio
import concurrent.futures
import glob
import json
import logging
import os
import random
import subprocess
import sys
import time
import traceback
import uuid
import math
import textwrap
import unicodedata
from datetime import datetime, timedelta

import imageio_ffmpeg
from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
import requests

FFMPEG_PATH = imageio_ffmpeg.get_ffmpeg_exe()

logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)s] ==> %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)

load_dotenv()

# ==================== CONFIGURATION ====================
SELECTED_LANG = 'ar'
VOICE_ID = '96d5c38e80a048f590be1af21d30d20c'   # Fish Audio voice

OPENROUTER_API_KEY = os.getenv('OPENROUTER_API_KEY')
BACKGROUND_VIDEO_URL = 'https://ia600403.us.archive.org/32/items/background_202609/Background.mp4'
TARGET_DURATION = 45
PARTS_COUNT = 6

REQUEST_TIMEOUT = 45
PRECHECK_TIMEOUT = 5
MAX_RETRIES = 5

FREE_CHAT_MODELS = [
    'nvidia/nemotron-3.5-lightning:free',
    'nvidia/nemotron-3-ultra:free',
    'minimax/minimax-m3:free',
    'cohere/north-mini-code:free',
    'dots-studio/dots3-note-preview:free',
    'liquid/lfm2.5-2.6b:free',
]

TOKEN_FILE = 'token.json'
SCRIPT_FILE = 'video_scripts.txt'
CLIENT_SECRETS_FILE = 'client_secrets.json'

SCOPES = ['https://www.googleapis.com/auth/youtube.upload']
# =======================================================


def make_request_with_retries(method, url, **kwargs):
    max_retries = MAX_RETRIES
    kwargs.setdefault('timeout', REQUEST_TIMEOUT)

    for attempt in range(max_retries):
        try:
            response = requests.request(method, url, **kwargs)
            if response.status_code >= 500:
                response.raise_for_status()
            return response
        except requests.exceptions.RequestException as e:
            logging.warning(f'[Network Retry {attempt+1}/{max_retries}] Failed for {url}: {e}')
            if attempt == max_retries - 1:
                raise e
            time.sleep(1.0 * (attempt + 1))


def get_fast_working_model(headers):
    logging.info('🔍 فحص النماذج المتاحة واختبار استجابتها السريعة...')
    for model_name in FREE_CHAT_MODELS:
        try:
            test_payload = {
                'model': model_name,
                'messages': [{'role': 'user', 'content': 'hi'}],
                'max_tokens': 1
            }
            response = requests.post(
                'https://openrouter.ai/api/v1/chat/completions',
                headers=headers,
                json=test_payload,
                timeout=PRECHECK_TIMEOUT
            )
            if response.status_code == 200:
                logging.info(f'✅ النموذج المستجيب والسريع حالياً: {model_name}')
                return model_name
        except Exception:
            pass
    return FREE_CHAT_MODELS[0]


def generate_story():
    story_themes = [
        'قصة غامضة وقعت في قرية قديمة وتسلّط الضوء على سر لم يُكشف وطريقة حله',
        'موقف إنساني مؤثر وصدمة وتطورات درامية غير متوقعة حتى النهاية',
        'لغز تاريخي قصير أو حكاية شعبية مجهولة مليئة بالأحداث والتشويق العميق',
    ]
    selected_theme = random.choice(story_themes)
    random_id = random.randint(10000, 99999)

    headers = {
        'Authorization': f'Bearer {OPENROUTER_API_KEY}',
        'Content-Type': 'application/json',
        'HTTP-Referer': 'https://github.com',
        'X-Title': 'Tales AI Generator',
    }

    active_model = get_fast_working_model(headers)

    lang_prompts = {
        'ar': (
            f'ألف قصة باللغة العربية مدتها حوالي {TARGET_DURATION} ثانية، مستوحاة من: "{selected_theme}" (مرجع: {random_id}).\n'
            f'الشرط الأهم: قسّم القصة تماماً إلى {PARTS_COUNT} أجزاء قصيرة جداً (كل جزء لا يتجاوز 8 كلمات).\n'
            'تأكد من أن كل جزء ينتهي بعلامة ترقيم (نقطة أو علامة تعجب أو استفهام) ولا تقطع كلمة في النهاية.\n'
            'تجنب تماماً استخدام الرموز الخاصة مثل النقطتين الرأسيتين (:) داخل النصوص لضمان توافقها مع الصوت.\n'
            'أرجع الرد بصيغة JSON فقط:\n'
            f'{{"title": "عنوان", "tags": ["قصص"], "parts": ["جزء 1", "جزء 2", "... حتى {PARTS_COUNT}"]}}'
        ),
        'en': (
            f'Write a short story of about {TARGET_DURATION} seconds strictly in English based on: "{selected_theme}" (Ref: {random_id}).\n'
            f'CRITICAL RULE: Split the story into exactly {PARTS_COUNT} very short parts (max 8 words each).\n'
            'Ensure each part ends with a punctuation mark (period, exclamation, or question) and do not cut words at the end.\n'
            'Avoid special punctuation marks like colons or question marks inside text chunks.\n'
            'Return ONLY JSON:\n'
            f'{{"title": "Title", "tags": ["story"], "parts": ["Part 1", "Part 2", "... up to {PARTS_COUNT}"]}}'
        ),
        'es': (
            f'Escribe un cuento en español de unos {TARGET_DURATION} segundos basado en: "{selected_theme}" (Ref: {random_id}).\n'
            f'REGLA CRÍTICA: Divide la historia exactamente en {PARTS_COUNT} partes muy cortas (máximo 8 palabras cada una).\n'
            'Asegúrate de que cada parte termine con un signo de puntuación (punto, exclamación o interrogación) y no cortes palabras al final.\n'
            'Devuelve SOLO JSON:\n'
            f'{{"title": "Título", "tags": ["historias"], "parts": ["Parte 1", "... hasta {PARTS_COUNT}"]}}'
        ),
        'ja': (
            f'テーマ "{selected_theme}" に基いて、約{TARGET_DURATION}秒の短いストーリーを日本語で作成してください (Ref: {random_id}).\n'
            f'重要なルール: ストーリーを正確に {PARTS_COUNT} の非常に短い部分に分割してください。\n'
            '各部分は句読点（ピリオド、感嘆符、疑問符）で終わり、単語を途中で切らないでください。\n'
            'JSON形式のみで返してください:\n'
            f'{{"title": "タイトル", "tags": ["物語"], "parts": ["パート1", "..."]}}'
        ),
        'ru': (
            f'Напишите короткий рассказ примерно на {TARGET_DURATION} секунд на русском языке на основе: "{selected_theme}" (Ref: {random_id}).\n'
            f'ВАЖНОЕ ПРАВИЛО: Разделите историю ровно на {PARTS_COUNT} очень коротких частей (не более 8 слов каждая).\n'
            'Убедитесь, что каждая часть заканчивается знаком препинания (точкой, восклицательным или вопросительным знаком) и не обрезайте слова.\n'
            'Верните ТОЛЬКО JSON:\n'
            f'{{"title": "Заголовок", "tags": ["истории"], "parts": ["Часть 1", "..."]}}'
        )
    }

    lang_prompt = lang_prompts.get(SELECTED_LANG, lang_prompts['ar'])
    models_to_try = [active_model] + [m for m in FREE_CHAT_MODELS if m != active_model]

    for model_name in models_to_try:
        try:
            response = make_request_with_retries(
                'post', 'https://openrouter.ai/api/v1/chat/completions',
                headers=headers, json={'model': model_name, 'messages': [{'role': 'user', 'content': lang_prompt}], 'temperature': 0.8},
                timeout=REQUEST_TIMEOUT
            )
            if response.status_code == 200:
                text = response.json()['choices'][0]['message']['content'].strip()
                text = text.replace('```json', '').replace('```', '').strip()
                start_idx, end_idx = text.find('{'), text.rfind('}')
                if start_idx != -1 and end_idx != -1:
                    parsed = json.loads(text[start_idx:end_idx+1])
                    if 'parts' in parsed and len(parsed['parts']) > 0:
                        cleaned_parts = [p.replace(':', ' -').replace('؟', '').replace('!', '.') for p in parsed['parts']]
                        for i, p in enumerate(cleaned_parts):
                            if p and p[-1] not in '.!?،':
                                cleaned_parts[i] = p + '.'
                        parsed['parts'] = cleaned_parts
                        return parsed
        except Exception:
            pass

    raise Exception(f'Failed to generate story for language: {SELECTED_LANG}')


def save_script_to_text_file(story_data):
    with open(SCRIPT_FILE, 'w', encoding='utf-8') as f:
        f.write(f'--- [ Language: {SELECTED_LANG.upper()} ] ---\n')
        for idx, part in enumerate(story_data.get('parts', []), 1):
            f.write(f'   {idx}: {part}\n')
        f.write('\n')


def text_to_speech_fish_audio(text_chunk, output_filename):
    """
    Attempt TTS using a list of models from OpenRouter.
    Falls back to the next model if the current one fails after retries.
    """
    # Normalise and sanitise
    text_chunk = unicodedata.normalize('NFKC', text_chunk)
    text_chunk = ''.join(ch for ch in text_chunk if unicodedata.category(ch)[0] != 'C')
    text_chunk = text_chunk.strip()
    if not text_chunk:
        raise ValueError("Empty text after sanitization")

    # ---- Model configurations (model name + voice) ----
    models = [
        {'model': 'fish-audio/s2.1-pro-free:free', 'voice': VOICE_ID},
        {'model': 'deepgram/flux-tts:free', 'voice': 'flux-alexis-en'},   # fallback
        # Add more fallbacks here if desired, e.g. google-tts, etc.
    ]

    url = 'https://openrouter.ai/api/v1/audio/speech'
    headers = {
        'Authorization': f'Bearer {OPENROUTER_API_KEY}',
        'Content-Type': 'application/json',
        'HTTP-Referer': 'https://github.com'
    }

    last_error = None

    for model_config in models:
        model_name = model_config['model']
        voice = model_config['voice']

        logging.info(f'Trying TTS model: {model_name} with voice: {voice}')

        payload = {
            'model': model_name,
            'input': text_chunk,
            'voice': voice,
            'response_format': 'mp3'
        }

        for attempt in range(MAX_RETRIES):
            try:
                response = requests.post(url, headers=headers, json=payload, timeout=30)

                # ---- Rate‑limit handling ----
                if response.status_code == 429:
                    reset_timestamp = response.headers.get('X-RateLimit-Reset')
                    remaining = response.headers.get('X-RateLimit-Remaining', '0')
                    limit = response.headers.get('X-RateLimit-Limit', '?')
                    logging.warning(
                        f'Rate limit hit for {model_name} (remaining {remaining}/{limit}). '
                        f'Reset at {reset_timestamp} (epoch ms)'
                    )
                    if reset_timestamp:
                        reset_epoch = int(reset_timestamp) / 1000.0   # convert ms to seconds
                        now = time.time()
                        wait_seconds = max(0, reset_epoch - now) + 1  # +1 for safety
                        if wait_seconds > 1:
                            wait_minutes = wait_seconds / 60
                            logging.info(f'Sleeping for {wait_minutes:.1f} minutes until rate limit resets...')
                            time.sleep(wait_seconds)
                            # After sleeping, retry (continue loop)
                            continue
                    # If no reset header, use exponential backoff
                    time.sleep((2 ** attempt) * 2)
                    continue

                if response.status_code == 200:
                    if len(response.content) > 500:
                        with open(output_filename, 'wb') as f:
                            f.write(response.content)
                        logging.info(f'TTS succeeded with {model_name} for chunk: {text_chunk[:30]}...')
                        return   # success, exit function
                    else:
                        logging.warning(f'TTS returned tiny file ({len(response.content)} bytes) for chunk: {text_chunk[:30]}')
                else:
                    error_body = response.text[:300]
                    logging.error(f'TTS API error {response.status_code} for {model_name}: {error_body}')
                    last_error = f"Status {response.status_code}: {error_body}"
            except Exception as e:
                logging.warning(f'TTS attempt {attempt+1} with {model_name} failed: {e}')
                last_error = str(e)
            time.sleep((attempt + 1) * 1.5)

        # If we exit the retry loop for this model, log and move to the next
        logging.warning(f'All retries failed for model {model_name}, trying next fallback...')

    # ---- If all models fail, raise exception (will be caught by process_single_part) ----
    raise Exception(f'TTS failed for chunk: "{text_chunk[:50]}" after trying all models. Last error: {last_error}')


def format_srt_time(seconds):
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int(round((seconds - int(seconds)) * 1000))
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def get_audio_duration(audio_path):
    try:
        res = subprocess.run([FFMPEG_PATH, '-i', audio_path], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        for line in res.stderr.splitlines():
            if 'Duration:' in line:
                parts = line.split('Duration:')[1].split(',')[0].strip().split(':')
                return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
    except Exception:
        pass
    return 3.0


def process_single_part(i, text, unique_prefix):
    part_name = f'temp_{SELECTED_LANG}_{i+1}_{unique_prefix}.mp3'
    try:
        text_to_speech_fish_audio(text, part_name)
    except Exception as e:
        logging.error(f'TTS failed for part {i+1}: {e}. Creating silent audio placeholder.')
        subprocess.run(
            [FFMPEG_PATH, '-y', '-f', 'lavfi', '-i', 'anullsrc=r=44100:cl=mono', '-t', '2', '-q:a', '2', part_name],
            check=True,
            capture_output=True
        )
    duration = get_audio_duration(part_name)
    wrapped_text = "\n".join(textwrap.wrap(text, width=30))
    return i, part_name, duration, wrapped_text


def process_audio_and_subtitles(story_data):
    parts = story_data.get('parts', [])
    unique_prefix = uuid.uuid4().hex[:8]
    
    final_audio = f'final_audio_{SELECTED_LANG}_{unique_prefix}.mp3'
    srt_file = f'subtitles_{SELECTED_LANG}_{unique_prefix}.srt'
    
    part_files = [None] * len(parts)
    subtitle_entries = [None] * len(parts)
    durations = [0.0] * len(parts)

    # --- Process TTS sequentially to avoid rate limits ---
    logging.info('⚡ Generating audio chunks sequentially to respect rate limits...')
    for i, text in enumerate(parts):
        part_name = f'temp_{SELECTED_LANG}_{i+1}_{unique_prefix}.mp3'
        try:
            text_to_speech_fish_audio(text, part_name)
        except Exception as e:
            logging.error(f'TTS failed for part {i+1}: {e}. Creating silent audio placeholder.')
            subprocess.run(
                [FFMPEG_PATH, '-y', '-f', 'lavfi', '-i', 'anullsrc=r=44100:cl=mono', '-t', '2', '-q:a', '2', part_name],
                check=True,
                capture_output=True
            )
        duration = get_audio_duration(part_name)
        part_files[i] = part_name
        durations[i] = duration
        wrapped_text = "\n".join(textwrap.wrap(text, width=30))
        # small delay between requests to avoid burst
        time.sleep(0.5)

    current_time = 0.0
    for i in range(len(parts)):
        start_time_str = format_srt_time(current_time)
        end_time_str = format_srt_time(current_time + durations[i])
        wrapped_text = "\n".join(textwrap.wrap(parts[i], width=30))
        subtitle_entries[i] = f"{i+1}\n{start_time_str} --> {end_time_str}\n{wrapped_text}\n"
        current_time += durations[i]

    try:
        with open(srt_file, 'w', encoding='utf-8') as srt_f:
            srt_f.write("\n".join(subtitle_entries))

        list_file = f'list_{SELECTED_LANG}_{unique_prefix}.txt'
        with open(list_file, 'w', encoding='utf-8') as f:
            for pf in part_files:
                f.write(f"file '{pf}'\n")

        subprocess.run(
            [FFMPEG_PATH, '-y', '-f', 'concat', '-safe', '0', '-i', list_file, '-c:a', 'libmp3lame', '-q:a', '2', final_audio],
            check=True, capture_output=True
        )
        return final_audio, srt_file
    finally:
        for pf in part_files:
            if pf and os.path.exists(pf): os.remove(pf)
        if 'list_file' in locals() and os.path.exists(list_file): os.remove(list_file)


def download_and_prepare_background(audio_duration):
    if not BACKGROUND_VIDEO_URL: raise Exception('BACKGROUND_VIDEO_URL is missing!')

    run_bg_source = f'source_bg_{uuid.uuid4().hex[:8]}.mp4'
    response = make_request_with_retries('get', BACKGROUND_VIDEO_URL, stream=True, timeout=60)
    with open(run_bg_source, 'wb') as f:
        for chunk in response.iter_content(chunk_size=8192):
            if chunk: f.write(chunk)

    total_video_duration = 4200.0
    try:
        cmd_probe = [FFMPEG_PATH, '-i', run_bg_source]
        res = subprocess.run(cmd_probe, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        for line in res.stderr.splitlines():
            if 'Duration:' in line:
                parts = line.split('Duration:')[1].split(',')[0].strip().split(':')
                total_video_duration = float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
                break
    except Exception: pass

    required_duration = int(audio_duration) + 1
    max_start = int(total_video_duration) - required_duration
    start_time = random.randint(0, max_start if max_start > 0 else 0)
    
    output_slice = f'temp_bg_slice_{uuid.uuid4().hex[:8]}.mp4'
    subprocess.run(
        [FFMPEG_PATH, '-y', '-ss', str(start_time), '-i', run_bg_source, '-t', str(required_duration), '-c:v', 'libx264', '-c:a', 'aac', output_slice],
        check=True, capture_output=True
    )
    
    if os.path.exists(run_bg_source):
        os.remove(run_bg_source)
        
    return output_slice


def render_video_with_subtitles(bg_video, main_audio, srt_file, output_video):
    safe_srt = srt_file.replace('\\', '/')
    style = "FontName=Arial,FontSize=24,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=3,Outline=2,Shadow=1,Alignment=10"
    vf_cmd = f"subtitles='{safe_srt}':force_style='{style}'"

    cmd = [
        FFMPEG_PATH, '-y', 
        '-i', bg_video, 
        '-i', main_audio,
        '-map', '0:v:0', '-map', '1:a:0', 
        '-vf', vf_cmd, 
        '-c:v', 'libx264', '-preset', 'ultrafast', 
        '-c:a', 'aac', '-b:a', '192k', 
        '-shortest', output_video
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
            flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRETS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, 'w') as token: token.write(creds.to_json())
    return build('youtube', 'v3', credentials=creds)


def upload_to_youtube(video_path, title, tags):
    youtube = get_youtube_service()
    body = {
        'snippet': {'title': title, 'description': f'{title}\n\nGenerated via automated pipeline.', 'tags': tags, 'categoryId': '27'},
        'status': {'privacyStatus': 'public', 'selfDeclaredMadeForKids': False},
    }
    media = MediaFileUpload(video_path, chunksize=5*1024*1024, resumable=True)
    request = youtube.videos().insert(part='snippet,status', body=body, media_body=media)
    response = None
    while response is None: status, response = request.next_chunk()
    logging.info(f"Video uploaded successfully to regular videos feed! ID: {response['id']}")
    return response['id']


def run_pipeline():
    generated_files = []
    try:
        logging.info(f'🚀 Starting Lightning-Fast Video Pipeline for language: [{SELECTED_LANG.upper()}]...')
        story_data = generate_story()
        save_script_to_text_file(story_data)

        audio_file, srt_file = process_audio_and_subtitles(story_data)
        generated_files.extend([audio_file, srt_file])

        audio_duration = get_audio_duration(audio_file)
        
        logging.info('🎬 Preparing background & rendering video with ultrafast preset...')
        lang_bg_video = download_and_prepare_background(audio_duration)
        generated_files.append(lang_bg_video)

        output_video = f'final_video_{SELECTED_LANG}_{uuid.uuid4().hex[:8]}.mp4'
        render_video_with_subtitles(lang_bg_video, audio_file, srt_file, output_video)
        generated_files.append(output_video)

        title = story_data.get('title', f'Amazing Story {SELECTED_LANG.upper()}')
        tags = story_data.get('tags', ['story', 'narrative'])

        upload_to_youtube(output_video, title, tags)
        logging.info(f'✅ Successfully published [{SELECTED_LANG.upper()}] video at maximum speed!')

    except Exception as e:
        logging.error(f'Cycle failed: {str(e)}')
        logging.error(traceback.format_exc())
    finally:
        for f in generated_files:
            if os.path.exists(f):
                try: os.remove(f)
                except OSError: pass
        for pattern in ['temp_*.mp4', 'temp_*.mp3', 'final_audio_*.mp3', 'final_video_*.mp4', 'list_*.txt', 'subtitles_*.srt', 'temp_bg_*.mp4', 'source_bg_*.mp4']:
            for f in glob.glob(pattern):
                try: os.remove(f)
                except: pass
        logging.info('🧹 Cleanup completed.')

if __name__ == '__main__':
    run_pipeline()
