import asyncio
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
import edge_tts
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

OPENROUTER_API_KEY = os.getenv('OPENROUTER_API_KEY')
BACKGROUND_VIDEO_URL = os.getenv(
    'BACKGROUND_VIDEO_URL',
    'https://ia600403.us.archive.org/32/items/background_202609/Background.mp4',
)

FREE_CHAT_MODELS = [
    'nvidia/nemotron-3.5-lightning:free',
    'nvidia/nemotron-3-ultra:free',
    'minimax/minimax-m3:free',
    'cohere/north-mini-code:free',
    'inclusionai/ling-3.0-flash-sante:free',
    'inclusionai/ling-3.0-flash-fin:free',
    'dots-studio/dots3-note-preview:free',
    'liquid/lfm2.5-2.6b:free',
]

EDGE_VOICES = {
    'ar': 'ar-EG-SalmaNeural',
    'en': 'en-US-ChristopherNeural',
    'es': 'es-ES-AlvaroNeural',
    'ja': 'ja-JP-KeitaNeural',
    'ru': 'ru-RU-DmitryNeural',
}

TOKEN_FILE = 'token.json'
SCRIPT_FILE = 'video_scripts.txt'
CLIENT_SECRETS_FILE = 'client_secrets.json'

SCOPES = ['https://www.googleapis.com/auth/youtube.upload']

LANGUAGES = {
    'ar': 'العربية (Arabic)',
    'en': 'الإنجليزية (English)',
    'es': 'الأسبانية (Spanish)',
    'ja': 'اليابانية (Japanese)',
    'ru': 'الروسية (Russian)',
}


def make_request_with_proxy_rotation(method, url, **kwargs):
  max_retries = 5
  kwargs.setdefault('timeout', 45)

  for attempt in range(max_retries):
    try:
      response = requests.request(method, url, **kwargs)
      if response.status_code >= 500:
        response.raise_for_status()
      return response
    except requests.exceptions.RequestException as e:
      logging.warning(
          f'[Network Retry {attempt+1}/{max_retries}] Failed for {url}: {e}'
      )
      if attempt == max_retries - 1:
        logging.error('[Fatal Error] Connection attempts failed.')
        raise e
      sleep_time = 5 * (attempt + 1)
      time.sleep(sleep_time)


def generate_multilingual_story():
  prompt = (
      'اكتب قصة قصيرة ومشوقة جداً لفيديو شورتس مدته دقيقة. '
      'قسّم القصة لجزئين متساويين (كل جزء حوالي 300-350 حرف). '
      'أريد القصة بـ 5 لغات: العربية (ar)، الإنجليزية (en)، الأسبانية'
      ' (es)، اليابانية (ja)، والروسية (ru). '
      'أرجع الرد بصيغة JSON فقط بهذا التنسيق حصراً وبدون أي كود ماركداون'
      ' إضافي:\n'
      '{\n'
      '   "ar": {"title": "عنوان القصة", "tags": ["قصص", "shorts"], "parts":'
      ' ["الجزء1", "الجزء2"]},\n'
      '   "en": {"title": "Title", "tags": ["story", "shorts"], "parts":'
      ' ["Part1", "Part2"]},\n'
      '   "es": {"title": "Título", "tags": ["historias", "shorts"], "parts":'
      ' ["Parte1", "Parte2"]},\n'
      '   "ja": {"title": "タイトル", "tags": ["物語", "shorts"], "parts":'
      ' ["パート1", "パート2"]},\n'
      '   "ru": {"title": "Заголовок", "tags": ["истории", "shorts"], "parts":'
      ' ["Часть1", "Часть2"]}\n'
      '}'
  )
  headers = {
      'Authorization': f'Bearer {OPENROUTER_API_KEY}',
      'Content-Type': 'application/json',
      'HTTP-Referer': 'https://github.com',
      'X-Title': 'Tales AI Generator',
  }

  last_exception = None
  for model_name in FREE_CHAT_MODELS:
    logging.info(f'Trying text AI model: {model_name}')
    payload = {
        'model': model_name,
        'messages': [{'role': 'user', 'content': prompt}],
        'temperature': 0.85,
    }

    try:
      response = make_request_with_proxy_rotation(
          'post',
          'https://openrouter.ai/api/v1/chat/completions',
          headers=headers,
          json=payload,
          timeout=60,
      )
      if response.status_code == 200:
        response_json = response.json()
        if 'choices' in response_json and response_json['choices']:
          response_text = (
              response_json['choices'][0]['message']['content'].strip()
          )
          response_text = (
              response_text.replace('```json', '').replace('```', '').strip()
          )
          return json.loads(response_text)

      logging.warning(
          f'Model {model_name} failed with status {response.status_code}:'
          f' {response.text}'
      )
    except Exception as e:
      logging.warning(f'Error with model {model_name}: {e}')
      last_exception = e
      time.sleep(2)

  raise Exception(f'All free AI models failed. Last error: {last_exception}')


def save_scripts_to_text_file(story_data):
  with open(SCRIPT_FILE, 'w', encoding='utf-8') as f:
    f.write('===================================================\n')
    f.write('TTS ENGINE: Edge TTS (Free Neural Voices)\n')
    f.write('===================================================\n\n')
    for lang_code, lang_name in LANGUAGES.items():
      if lang_code in story_data:
        data = story_data[lang_code]
        f.write(f'--- [ {lang_name} ({lang_code.upper()}) ] ---\n')
        f.write(f"TITLE: {data.get('title', '')}\n")
        f.write(f"TAGS: {', '.join(data.get('tags', []))}\n")
        f.write('NARRATION:\n')
        for idx, part in enumerate(data.get('parts', []), 1):
          f.write(f'   Part {idx}: {part}\n')
        f.write('\n' + '=' * 50 + '\n\n')


async def generate_edge_tts(text, output_file, lang_code):
  voice = EDGE_VOICES.get(lang_code, 'en-US-ChristopherNeural')
  communicate = edge_tts.Communicate(text, voice)
  await communicate.save(output_file)


def text_to_speech(text_chunk, output_filename, lang_code):
  for attempt in range(3):
    try:
      asyncio.run(generate_edge_tts(text_chunk, output_filename, lang_code))
      if os.path.exists(output_filename) and os.path.getsize(output_filename) > 0:
        return
    except Exception as e:
      logging.warning(f'[Edge TTS Attempt {attempt+1}] Exception: {e}')
    time.sleep(2)
  raise Exception(f'Failed to generate TTS audio for language: {lang_code}')


def process_audio_for_language(lang_data, lang_code):
  parts = lang_data['parts']
  part_files = []
  unique_prefix = uuid.uuid4().hex[:8]
  final_audio = f'final_audio_{lang_code}_{unique_prefix}.mp3'

  try:
    for i, text in enumerate(parts):
      part_name = f'temp_{lang_code}_{i+1}_{unique_prefix}.mp3'
      text_to_speech(text, part_name, lang_code)
      part_files.append(part_name)

    list_file = f'list_{lang_code}_{unique_prefix}.txt'
    with open(list_file, 'w', encoding='utf-8') as f:
      for pf in part_files:
        f.write(f"file '{pf}'\n")

    subprocess.run(
        [
            FFMPEG_PATH,
            '-y',
            '-f',
            'concat',
            '-safe',
            '0',
            '-i',
            list_file,
            '-c:a',
            'libmp3lame',
            '-q:a',
            '2',
            final_audio,
        ],
        check=True,
        capture_output=True,
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
    raise Exception('BACKGROUND_VIDEO_URL is missing!')

  logging.info('Downloading background video...')
  source_video = f'source_bg_{uuid.uuid4().hex[:8]}.mp4'

  response = make_request_with_proxy_rotation(
      'get', BACKGROUND_VIDEO_URL, stream=True, timeout=120
  )
  if response.status_code != 200:
    raise Exception(
        f'Failed to download background video, status: {response.status_code}'
    )

  with open(source_video, 'wb') as f:
    for chunk in response.iter_content(chunk_size=8192):
      if chunk:
        f.write(chunk)

  duration = 4200.0
  try:
    cmd_probe = [FFMPEG_PATH, '-i', source_video]
    result = subprocess.run(
        cmd_probe, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    for line in result.stderr.splitlines():
      if 'Duration:' in line:
        parts = line.split('Duration:')[1].split(',')[0].strip().split(':')
        duration = (
            float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
        )
        break
  except Exception as e:
    logging.warning(f'Duration extraction failed: {e}')

  max_start = int(duration) - 65
  start_time = random.randint(0, max_start if max_start > 0 else 0)
  output_slice = f'temp_background_slice_{uuid.uuid4().hex[:8]}.mp4'

  cmd_cut = [
      FFMPEG_PATH,
      '-y',
      '-ss',
      str(start_time),
      '-i',
      source_video,
      '-t',
      '60',
      '-c:v',
      'libx264',
      '-c:a',
      'aac',
      output_slice,
  ]
  subprocess.run(cmd_cut, check=True, capture_output=True)

  if os.path.exists(source_video):
    os.remove(source_video)

  return output_slice


def render_video_ffmpeg(bg_video, main_audio, output_video):
  cmd = [
      FFMPEG_PATH,
      '-y',
      '-i',
      bg_video,
      '-i',
      main_audio,
      '-map',
      '0:v:0',
      '-map',
      '1:a:0',
      '-c:v',
      'copy',
      '-c:a',
      'aac',
      '-b:a',
      '192k',
      '-shortest',
      output_video,
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
        raise Exception(f'Missing {CLIENT_SECRETS_FILE}')
      flow = InstalledAppFlow.from_client_secrets_file(
          CLIENT_SECRETS_FILE, SCOPES
      )
      creds = flow.run_local_server(port=0)
    with open(TOKEN_FILE, 'w') as token:
      token.write(creds.to_json())
  return build('youtube', 'v3', credentials=creds)


def upload_to_youtube(video_path, title, tags):
  youtube = get_youtube_service()
  body = {
      'snippet': {
          'title': title,
          'description': f'{title}\n\n#shorts',
          'tags': tags,
          'categoryId': '27',
      },
      'status': {'privacyStatus': 'public', 'selfDeclaredMadeForKids': False},
  }
  media = MediaFileUpload(video_path, chunksize=5 * 1024 * 1024, resumable=True)
  request = youtube.videos().insert(
      part='snippet,status', body=body, media_body=media
  )
  response = None
  while response is None:
    status, response = request.next_chunk()
  logging.info(f"Video uploaded successfully! Video ID: {response['id']}")
  return response['id']


def run_pipeline():
  generated_files = []
  try:
    logging.info('====================================')
    logging.info('Starting automation cycle (Edge TTS)...')
    logging.info('====================================')

    story_data = generate_multilingual_story()
    save_scripts_to_text_file(story_data)

    audio_files = {}
    for lang_code in LANGUAGES.keys():
      if lang_code in story_data:
        logging.info(f'Generating speech for [{lang_code}] via Edge TTS...')
        audio_file = process_audio_for_language(
            story_data[lang_code], lang_code
        )
        audio_files[lang_code] = audio_file
        generated_files.append(audio_file)

    bg_video = download_and_prepare_background()
    generated_files.append(bg_video)

    output_video = f'final_shorts_{uuid.uuid4().hex[:8]}.mp4'
    render_video_ffmpeg(bg_video, audio_files['ar'], output_video)
    generated_files.append(output_video)

    ar_title = story_data['ar']['title']
    ar_tags = story_data['ar']['tags']
    upload_to_youtube(output_video, ar_title, ar_tags)

    logging.info('Automation cycle completed successfully!')

  except Exception as e:
    logging.error(f'Cycle failed: {str(e)}')
    logging.error(traceback.format_exc())
  finally:
    for f in generated_files:
      if os.path.exists(f):
        try:
          os.remove(f)
        except OSError:
          pass
    for pattern in [
        'temp_*.mp4',
        'temp_*.mp3',
        'final_audio_*.mp3',
        'final_shorts_*.mp4',
        'list_*.txt',
        'source_bg_*.mp4',
    ]:
      for f in glob.glob(pattern):
        try:
          os.remove(f)
        except:
          pass
    logging.info('Cleanup completed.')


if __name__ == '__main__':
  run_pipeline()
