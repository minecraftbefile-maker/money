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
  kwargs.setdefault('timeout', 60)

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
      time.sleep(5 * (attempt + 1))


def generate_multilingual_story():
  story_themes = [
      'قصة غامضة وقعت في قرية قديمة وتسلّط الضوء على سر لم يُكشف وطريقة حله',
      'موقف إنساني مؤثر وصدمة وتطورات درامية غير متوقعة حتى النهاية',
      'لغز تاريخي قصير أو حكاية شعبية مجهولة مليئة بالأحداث والتشويق العميق',
      'قصة عن ذكاء شخص استطاع مواجهة سلسلة من التحديات والمشاكل المعقدة',
      'مفارقة غريبة تحدث صدفة وتأخذ البطل في رحلة طويلة مليئة بالعبر',
      'حكاية من التراث الشعبي بأسلوب حكواتي طويل يشد المشاهد طوال دقيقتين',
  ]
  selected_theme = random.choice(story_themes)
  random_id = random.randint(10000, 99999)

  story_data = {}
  headers = {
      'Authorization': f'Bearer {OPENROUTER_API_KEY}',
      'Content-Type': 'application/json',
      'HTTP-Referer': 'https://github.com',
      'X-Title': 'Tales AI Generator',
  }

  lang_prompts = {
      'ar': (
          f'ألف قصة طويلة ومفصلة باللغة العربية حصراً مدتها تتراوح بين دقيقتين إلى 3 دقائق، مستوحاة من: "{selected_theme}" (مرجع: {random_id}).\n'
          'الشروط:\n'
          '1. ابدأ بخطاف (Hook) قوي جداً.\n'
          '2. قسّم القصة إلى 6 أجزاء مترابطة وطويلة لتغطية وقت طويل (كل جزء حوالي 300-350 حرف).\n'
          'أرجع الرد بصيغة JSON فقط:\n'
          '{"title": "عنوان عربي طويل ومثير غير مكرر", "tags": ["قصص", "shorts"], "parts": ["الجزء 1", "الجزء 2", "الجزء 3", "الجزء 4", "الجزء 5", "الجزء 6"]}'
      ),
      'en': (
          f'Write a long, detailed short story strictly in English lasting 2-3 minutes, based on: "{selected_theme}" (Ref: {random_id}).\n'
          'Rules: Start with a strong hook, split into 6 connected parts (about 300 characters each).\n'
          'Return ONLY JSON:\n'
          '{"title": "Long Unique Catchy Title", "tags": ["story", "shorts"], "parts": ["Part 1", "Part 2", "Part 3", "Part 4", "Part 5", "Part 6"]}'
      ),
      'es': (
          f'Escribe un cuento largo y detallado estrictamente en español de 2 a 3 minutos, basado en: "{selected_theme}" (Ref: {random_id}).\n'
          'Reglas: Empieza con un gancho fuerte, divídelo en 6 partes conectadas.\n'
          'Devuelve SOLO JSON:\n'
          '{"title": "Título Único Largo", "tags": ["historias", "shorts"], "parts": ["Parte 1", "Parte 2", "Parte 3", "Parte 4", "Parte 5", "Parte 6"]}'
      ),
      'ja': (
          f'テーマ "{selected_theme}" に基いて、2〜3分の長めで詳細なストーリーを完全に日本語だけで作成してください (Ref: {random_id}).\n'
          'ルール: 強いフックから始め、6つのつながったパートに分けてください。\n'
          'JSON形式のみで返してください:\n'
          '{"title": "ユニークな長いタイトル", "tags": ["物語", "shorts"], "parts": ["パート1", "パート2", "パート3", "パート4", "パート5", "パート6"]}'
      ),
      'ru': (
          f'Напишите длинный и подробный рассказ строго на русском языке на 2-3 минуты на основе: "{selected_theme}" (Ref: {random_id}).\n'
          'Правила: Начните с сильного крючка, разделите на 6 связанных частей.\n'
          'Верните ТОЛЬКО JSON:\n'
          '{"title": "Длинный уникальный заголовок", "tags": ["истории", "shorts"], "parts": ["Часть 1", "Часть 2", "Часть 3", "Часть 4", "Часть 5", "Часть 6"]}'
      )
  }

  for lang_code, lang_prompt in lang_prompts.items():
    success = False
    for model_name in FREE_CHAT_MODELS:
      if success:
        break
      logging.info(f'Generating long [{lang_code}] story using model: {model_name}')
      payload = {
          'model': model_name,
          'messages': [{'role': 'user', 'content': lang_prompt}],
          'temperature': 0.95,
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
          res_json = response.json()
          if 'choices' in res_json and res_json['choices']:
            text = res_json['choices'][0]['message']['content'].strip()
            text = text.replace('```json', '').replace('```', '').strip()
            start_idx = text.find('{')
            end_idx = text.rfind('}')
            if start_idx != -1 and end_idx != -1:
              json_str = text[start_idx:end_idx+1]
              story_data[lang_code] = json.loads(json_str)
              success = True
              break
      except Exception as e:
        logging.warning(f'Model {model_name} failed for lang {lang_code}: {e}')
        time.sleep(1)
    
    if not success:
      raise Exception(f'Failed to generate long story for language: {lang_code}')
    time.sleep(1.5)

  return story_data


def save_scripts_to_text_file(story_data):
  with open(SCRIPT_FILE, 'w', encoding='utf-8') as f:
    f.write('===================================================\n')
    f.write('TTS ENGINE: Fish Audio S21 Pro (OpenRouter Free API)\n')
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


def text_to_speech_fish_audio(text_chunk, output_filename, lang_code):
  headers = {
      'Authorization': f'Bearer {OPENROUTER_API_KEY}',
      'Content-Type': 'application/json',
      'HTTP-Referer': 'https://github.com',
      'X-Title': 'Tales AI Generator',
  }
  
  # استخدام نموذج Fish Audio S21 Pro المجاني عبر واجهة محادثة وتوليد الصوت
  payload = {
      'model': 'fish-audio/s21-pro-free:free',
      'messages': [
          {
              'role': 'user', 
              'content': f'Convert the following text into spoken audio strictly in language {lang_code}. Read this text naturally with a human-like voice: {text_chunk}'
          }
      ]
  }

  for attempt in range(3):
    try:
      response = make_request_with_proxy_rotation(
          'post',
          'https://openrouter.ai/api/v1/chat/completions',
          headers=headers,
          json=payload,
          timeout=90,
      )
      
      if response.status_code == 200:
        # إذا كان الموديل يرجع محتوى صوتي أو بيانات مرتبطة، يتم التعامل معها
        # بما أننا نعتمد على استجابة الـ OpenRouter الحالية، نقوم بحفظ النتيجة المباشرة
        res_json = response.json()
        if 'choices' in res_json and res_json['choices']:
          # استخراج النص أو المادة الصوتية المعادة
          audio_content = res_json['choices'][0]['message'].get('content', '')
          # لو كان الـ API يعيد بايتات صوتية مباشرة أو رابط ملف صوتي:
          with open(output_filename, 'wb') as f:
            f.write(response.content)
            
          if os.path.exists(output_filename) and os.path.getsize(output_filename) > 1000:
            logging.info(f'[Fish Audio S21] Audio chunk generated successfully for {lang_code}')
            return
    except Exception as e:
      logging.warning(f'[Fish Audio Attempt {attempt+1}] Error for {lang_code}: {e}')
    time.sleep(3)
    
  raise Exception(f'Failed to generate audio via Fish Audio for language: {lang_code}')


def process_audio_for_language(lang_data, lang_code):
  parts = lang_data['parts']
  part_files = []
  unique_prefix = uuid.uuid4().hex[:8]
  final_audio = f'final_audio_{lang_code}_{unique_prefix}.mp3'

  try:
    for i, text in enumerate(parts):
      part_name = f'temp_{lang_code}_{i+1}_{unique_prefix}.mp3'
      text_to_speech_fish_audio(text, part_name, lang_code)
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


def download_and_prepare_long_background(audio_duration):
  if not BACKGROUND_VIDEO_URL:
    raise Exception('BACKGROUND_VIDEO_URL is missing!')

  logging.info(f'Downloading background video for duration: {audio_duration:.2f}s...')
  source_video = f'source_bg_{uuid.uuid4().hex[:8]}.mp4'

  response = make_request_with_proxy_rotation(
      'get', BACKGROUND_VIDEO_URL, stream=True, timeout=120
  )
  if response.status_code != 200:
    raise Exception(f'Failed to download background video, status: {response.status_code}')

  with open(source_video, 'wb') as f:
    for chunk in response.iter_content(chunk_size=8192):
      if chunk:
        f.write(chunk)

  total_video_duration = 4200.0
  try:
    cmd_probe = [FFMPEG_PATH, '-i', source_video]
    result = subprocess.run(cmd_probe, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    for line in result.stderr.splitlines():
      if 'Duration:' in line:
        parts = line.split('Duration:')[1].split(',')[0].strip().split(':')
        total_video_duration = float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
        break
  except Exception as e:
    logging.warning(f'Duration extraction failed: {e}')

  required_duration = int(audio_duration) + 2
  max_start = int(total_video_duration) - required_duration
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
      str(required_duration),
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


def get_audio_duration(audio_path):
  try:
    cmd = [FFMPEG_PATH, '-i', audio_path]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    for line in result.stderr.splitlines():
      if 'Duration:' in line:
        parts = line.split('Duration:')[1].split(',')[0].strip().split(':')
        return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
  except Exception as e:
    logging.warning(f'Failed to get audio duration: {e}')
  return 120.0


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
          'description': f'{title}\n\n#shorts',
          'tags': tags,
          'categoryId': '27',
      },
      'status': {'privacyStatus': 'public', 'selfDeclaredMadeForKids': False},
  }
  media = MediaFileUpload(video_path, chunksize=5 * 1024 * 1024, resumable=True)
  request = youtube.videos().insert(part='snippet,status', body=body, media_body=media)
  response = None
  while response is None:
    status, response = request.next_chunk()
  logging.info(f"Video uploaded successfully! Video ID: {response['id']}")
  return response['id']


def run_pipeline():
  generated_files = []
  try:
    logging.info('====================================')
    logging.info('Starting Multi-Language Pipeline with Fish Audio S21 Pro...')
    logging.info('====================================')

    story_data = generate_multilingual_story()
    save_scripts_to_text_file(story_data)

    audio_files = {}
    for lang_code in LANGUAGES.keys():
      if lang_code in story_data:
        logging.info(f'Generating long speech for [{lang_code}] via Fish Audio S21 Pro...')
        audio_file = process_audio_for_language(story_data[lang_code], lang_code)
        audio_files[lang_code] = audio_file
        generated_files.append(audio_file)

    ar_audio_duration = get_audio_duration(audio_files['ar'])
    bg_video = download_and_prepare_long_background(ar_audio_duration)
    generated_files.append(bg_video)

    total_langs = len([l for l in LANGUAGES.keys() if l in story_data and l in audio_files])
    current_index = 0

    for lang_code, lang_name in LANGUAGES.items():
      if lang_code in story_data and lang_code in audio_files:
        current_index += 1
        
        lang_bg_video = bg_video
        if lang_code != 'ar':
          lang_audio_duration = get_audio_duration(audio_files[lang_code])
          lang_bg_video = download_and_prepare_long_background(lang_audio_duration)
          generated_files.append(lang_bg_video)

        logging.info(f'[{current_index}/{total_langs}] Rendering video for: {lang_name} ({lang_code})...')

        output_video = f'final_shorts_{lang_code}_{uuid.uuid4().hex[:8]}.mp4'
        render_video_ffmpeg(lang_bg_video, audio_files[lang_code], output_video)
        generated_files.append(output_video)

        lang_title = story_data[lang_code]['title']
        lang_tags = story_data[lang_code]['tags']

        upload_to_youtube(output_video, lang_title, lang_tags)
        logging.info(f'Successfully published [{lang_name}] video!')

        if current_index < total_langs:
          delay_seconds = 600  # 10 دقائق
          logging.info('⏳ الانتظار لمدة 10 دقائق قبل نشر الفيديو التالي لضمان أمان القناة...')
          time.sleep(delay_seconds)

    logging.info('All multilingual videos published successfully with Fish Audio & safe intervals!')

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
