from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, CallbackContext, filters
import yt_dlp
from dotenv import load_dotenv
import os
import uuid
import asyncio
import requests
import re
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload


# تحميل المتغيرات من ملف .env
load_dotenv()

# 🔹 استخدام المتغيرات من ملف .env
TOKEN = os.getenv("TOKEN")
ADSTERRE_AD_URL = os.getenv("ADSTERRE_AD_URL")

# 🔹 التحقق من تحميل المتغيرات بشكل صحيح
if not TOKEN:
    raise ValueError("❌ لم يتم تحميل TOKEN من ملف .env!")
if not ADSTERRE_AD_URL:
    raise ValueError("❌ لم يتم تحميل ADSTERRE_AD_URL من ملف .env!")


# 🛠️ تحميل الفيديو إلى Google Drive والحصول على رابط المشاركة
def upload_to_google_drive(file_path, file_name):
    """رفع الفيديو إلى Google Drive وإرجاع رابط المشاركة."""
    
    SCOPES = ["https://www.googleapis.com/auth/drive.file"]
    SERVICE_ACCOUNT_FILE = "almbot.json"  # تأكد من كتابة اسم الملف الصحيح
    
    creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    service = build("drive", "v3", credentials=creds)

    file_metadata = {"name": file_name, "parents": ["root"]}  # يمكنك تحديد مجلد معين برمز المجلد في Google Drive
    media = MediaFileUpload(file_path, mimetype="video/mp4")

    file = service.files().create(body=file_metadata, media_body=media, fields="id").execute()
    file_id = file.get("id")

    # جعل الملف متاحًا للجميع عبر الرابط
    permission = {"role": "reader", "type": "anyone"}
    service.permissions().create(fileId=file_id, body=permission).execute()

    # إنشاء رابط المشاركة
    file_link = f"https://drive.google.com/file/d/{file_id}/view"
    return file_link



 
watched_ads = {}  # تخزين حالة المستخدمين الذين ضغطوا على زر مشاهدة الإعلان


# ✅ تخزين الروابط لمنع فقدان البيانات أثناء التحميل
link_storage = {}

# ✅ قفل منع الإرسال المكرر لكل فيديو
send_locks = {}

# 🛠️ دالة بدء تشغيل البوت
async def start(update: Update, context: CallbackContext) -> None:
    await update.message.reply_text("👋 أهلاً بك! أرسل لي رابط فيديو وسأقوم بتحميله لك.")

       # 🔍 دالة لتحويل روابط YouTube إلى الصيغة المختصرة youtu.be
def convert_youtube_url(url):
    youtube_regex = (
        r"(?:https?://)?(?:www\.)?"
        r"(?:youtube\.com/(?:watch\?v=|shorts/|embed/)|youtu\.be/)"
        r"([a-zA-Z0-9_-]{11})"
    )
    match = re.search(youtube_regex, url)
    if match:
        video_id = match.group(1)
        return f"https://youtu.be/{video_id}"
    return url  # إذا لم يكن الرابط صحيحًا، نعيده كما هو


# 🔍 دالة لفك اختصار روابط Pinterest
def expand_pinterest_url(short_url):
    try:
        response = requests.head(short_url, allow_redirects=True)
        return response.url  # الحصول على الرابط الحقيقي بعد إعادة التوجيه
    except requests.RequestException as e:
        return None
    


 

# 📥 استقبال الروابط وتحليلها
async def receive_link(update: Update, context: CallbackContext) -> None:
    url = update.message.text.strip()

      # تحويل روابط YouTube إلى الصيغة المختصرة
    if "youtube.com" in url or "youtu.be" in url:
        url = convert_youtube_url(url)

    # 🔹 إذا كان الرابط من Pinterest ولكنه مختصر، قم بفك الاختصار
    if "pin.it" in url:
        expanded_url = expand_pinterest_url(url)
        if expanded_url:
            url = expanded_url  # استخدم الرابط الحقيقي بدلاً من المختصر

    # 🔹 التحقق مما إذا كان الرابط مدعومًا
    if any(platform in url for platform in ["youtube.com", "youtu.be", "facebook.com", "fb.watch",
                                            "instagram.com", "tiktok.com", "twitter.com", "pinterest.com"]):
        unique_id = str(uuid.uuid4())[:8]
        link_storage[unique_id] = url  

        keyboard = [
            [InlineKeyboardButton("🎥 تحميل الفيديو", callback_data=f"video|{unique_id}")],
            [InlineKeyboardButton("🎵 تحميل الصوت فقط", callback_data=f"audio|{unique_id}")],
            [InlineKeyboardButton("❌ إلغاء التحميل", callback_data="cancel_download")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text("🔽 اختر نوع التحميل:", reply_markup=reply_markup)
    else:
        await update.message.reply_text("⚠ هذا الرابط غير مدعوم حالياً.")

# 🎥 تحميل الفيديو
async def download_video(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()

    _, unique_id = query.data.split("|")
    url = link_storage.get(unique_id)

    if not url:
        await query.edit_message_text("⚠ الرابط غير صالح أو انتهت صلاحيته!")
        return

    await query.edit_message_text("⏳ جارٍ تحميل الفيديو، الرجاء الانتظار...")

    asyncio.create_task(handle_video_download(query, url, unique_id))

async def handle_video_download(query, url, unique_id):
    global send_locks

    output_video = f"downloads/{unique_id}.mp4"

    if os.path.exists(output_video):
        os.remove(output_video)

     # ✅ تحديد تنسيق الجودة بناءً على المنصة
    if "youtube.com" in url or "youtu.be" in url:
     ydl_opts = {
        "format": "bestvideo+bestaudio/best",  
        "merge_output_format": "mp4",
        "outtmpl": output_video,
        "socket_timeout": 3600,
        "retries": 30,
        "fragment_retries": 30,
        "hls_prefer_native": True,
        "noplaylist": True,  # تحميل فيديو واحد فقط وليس قائمة تشغيل
        "force_generic_extractor": True,  # فرض استخدام yt-dlp بدون تسجيل الدخول
        "quiet": False,  # عرض تفاصيل التحميل
        "no-check-certificate": True,  # تجاوز مشاكل الشهادات
        "sleep_interval": 2,  # تقليل سرعة الطلبات لمنع الحظر
        "max_sleep_interval": 5,
        "headers": {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/109.0.0.0 Safari/537.36"
        },

        "progress_hooks": [lambda d: print(d)],  # تتبع التحميل


     }

    elif "facebook.com" in url or "fb.watch" in url:
     ydl_opts = {
        "format": "best",  # تحميل أفضل جودة متاحة دون قيود على الدقة
        "merge_output_format": "mp4",
        "outtmpl": output_video,
        "socket_timeout": 3600,
        "retries": 30,
        "fragment_retries": 30,
        "hls_prefer_native": True,
     }
    else:
     ydl_opts = {
        "format": "bestvideo+bestaudio/best",  # تحميل أعلى جودة لباقي المنصات
        "merge_output_format": "mp4",
        "outtmpl": output_video,
        "socket_timeout": 3600,
        "retries": 30,
        "fragment_retries": 30,
        "hls_prefer_native": True,
     }


    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        if os.path.exists(output_video):
            await query.edit_message_text("✅ تم تحميل الفيديو! قبل الإرسال، يرجى مشاهدة الإعلان.")
          

            keyboard = [
                 [InlineKeyboardButton("👀 مشاهدة إعلان قبل الإرسال", callback_data=f"watch_ad|{unique_id}")]
            ]


            reply_markup = InlineKeyboardMarkup(keyboard)

            await query.message.reply_text("🔽 لمتابعة استلام الفيديو، يرجى مشاهدة الإعلان:", reply_markup=reply_markup)
                
                # ✅ تسجيل أن المستخدم لم يشاهد الإعلان بعد
            watched_ads[unique_id] = False  


           

    except Exception as e:
        await query.edit_message_text(f"❌ حدث خطأ أثناء تحميل الفيديو: {str(e)}")

    finally:
        if unique_id in send_locks:
            del send_locks[unique_id]


# 📤 إرسال الفيديو بمحاولة واحدة فقط
MAX_TELEGRAM_VIDEO_SIZE = 50 * 1024 * 1024  # 50MB بالبايت

# 📤 إرسال الفيديو بعد التحقق من حجمه
# 📤 إرسال الفيديو بعد التحقق من حجمه
async def send_video(query, video_path):
    """إرسال الفيديو عبر تيليغرام إذا كان أقل من 50MB، أو رفعه إلى Google Drive إذا كان أكبر."""
    
    file_size = os.path.getsize(video_path)  # الحصول على حجم الفيديو بالبايت
    file_size_mb = file_size / (1024 * 1024)  # تحويل الحجم إلى MB
    
    if file_size_mb > 50:
        # ✅ رفع الفيديو إلى Google Drive وإرسال الرابط للمستخدم
        await query.message.reply_text(f"⚠ الفيديو أكبر من 50MB ({file_size_mb:.2f}MB)، جارٍ رفعه إلى Google Drive...")
        
        video_link = upload_to_google_drive(video_path, os.path.basename(video_path))
        
        await query.message.reply_text(f"✅ تم رفع الفيديو بنجاح! يمكنك تحميله من الرابط التالي:\n{video_link}")
        return  # لا نرسل الفيديو عبر تيليغرام

    try:
        # ✅ إرسال الفيديو إذا كان حجمه أقل من 50MB
        await query.message.reply_text(f"📦 حجم الفيديو: {file_size_mb:.2f}MB، جارٍ الإرسال... ⏳")

        with open(video_path, "rb") as video_file:
            await query.message.reply_video(video=video_file)

        await asyncio.sleep(2)  # تأخير بسيط لمنع الحظر
        await query.message.reply_text("✅ تم إرسال الفيديو بنجاح! 🎉")

    except Exception as e:
        await query.message.reply_text(f"❌ حدث خطأ أثناء إرسال الفيديو: {str(e)}")


async def send_video_after_ad(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()
    
    _, unique_id = query.data.split("|")
    video_path = f"downloads/{unique_id}.mp4"

    if not os.path.exists(video_path):
        await query.edit_message_text("⚠ الملف غير موجود أو تم حذفه!")
        return

    # **تحقق مما إذا كان المستخدم قد ضغط على "تم مشاهدة الإعلان"**
    if watched_ads.get(unique_id, False):
        await query.edit_message_text("📤 جارٍ إرسال الفيديو... ⏳")
        await send_video(query, video_path)
    else:
        await query.message.reply_text("⚠ يجب مشاهدة الإعلان قبل استلام الفيديو!")
 



async def watch_ad_and_send_video(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()

    _, unique_id = query.data.split("|")

    # ✅ تسجيل أن المستخدم قد ضغط على مشاهدة الإعلان
    watched_ads[unique_id] = True  # 🔹 هذا الجزء كان مفقودًا في الكود السابق

    # إرسال رابط الإعلان
    await query.message.reply_text(f"🔗 اضغط على الرابط لمشاهدة الإعلان: {ADSTERRE_AD_URL}")

    # إظهار زر "تم مشاهدة الإعلان" بعد 10 ثوانٍ
    await asyncio.sleep(10)

    keyboard = [
        [InlineKeyboardButton("✅ تم مشاهدة الإعلان، أرسل الفيديو", callback_data=f"send_video|{unique_id}")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.message.reply_text("✅ بعد مشاهدة الإعلان، اضغط على الزر لإرسال الفيديو:", reply_markup=reply_markup)


# 🎵 تحميل الصوت
async def download_audio(update: Update, context: CallbackContext):
    """ دالة لتحميل الصوت من الرابط المرسل، مع تضمين إعلانات قبل الإرسال. """
    
    query = update.callback_query
    await query.answer()

    # استخراج معرف الرابط المخزن
    _, unique_id = query.data.split("|")
    url = link_storage.get(unique_id)

    # التحقق من صحة الرابط
    if not url:
        await query.edit_message_text("⚠ الرابط غير صالح أو انتهت صلاحيته!")
        return

    await query.edit_message_text("⏳ جارٍ تحميل الصوت، الرجاء الانتظار...")

    # تحديد مسارات الملفات
    output_audio = f"downloads/{unique_id}"
    final_audio = f"downloads/{unique_id}.mp3"

    # حذف أي ملفات قديمة لمنع التداخل
    for file in [f"{output_audio}.mp3", f"{output_audio}.m4a", final_audio]:
        if os.path.exists(file):
            os.remove(file)

    # إعدادات yt-dlp لتحميل الصوت
    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": output_audio,  
        "postprocessors": [
            {"key": "FFmpegExtractAudio", "preferredcodec": "mp3"},
            {"key": "FFmpegMetadata"}  
        ]
    }

    try:
        # تحميل الصوت باستخدام yt-dlp
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        await asyncio.sleep(1.5)  # تأخير بسيط لمنع الحظر

        # البحث عن الملفات الصوتية التي تم تحميلها
        downloaded_files = [f for f in os.listdir("downloads") if f.startswith(unique_id) and f.endswith((".mp3", ".m4a", ".webm"))]
        if not downloaded_files:
            raise Exception("⚠ لم يتم العثور على الملف الصوتي بعد التحميل!")

        downloaded_audio = os.path.join("downloads", downloaded_files[0])

        # تحويل أي ملف صوتي غير MP3 إلى MP3
        if not downloaded_audio.endswith(".mp3"):
            converted_audio = downloaded_audio.rsplit(".", 1)[0] + ".mp3"
            os.system(f'ffmpeg -i "{downloaded_audio}" -vn -acodec libmp3lame "{converted_audio}" -y')
            os.remove(downloaded_audio)  # حذف الملف القديم
            downloaded_audio = converted_audio

        # إعادة تسمية الملف النهائي
        os.rename(downloaded_audio, final_audio)

        # التحقق من أن الملف صالح للإرسال
        if os.path.exists(final_audio) and os.path.getsize(final_audio) > 100 * 1024:
            # ✅ تم تحميل الصوت، مطالبة المستخدم بمشاهدة الإعلان قبل الإرسال
            await query.edit_message_text("✅ تم تحميل الصوت! قبل الإرسال، يرجى مشاهدة الإعلان.")

            # 🔹 إنشاء زر مشاهدة الإعلان
            keyboard = [
                [InlineKeyboardButton("👀 مشاهدة إعلان قبل الإرسال", callback_data=f"watch_ad_audio|{unique_id}")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            # 🔹 إرسال رسالة تحفيزية للمستخدم لمتابعة الإعلان
            await query.message.reply_text(
                "🔽 لمتابعة استلام الصوت، يرجى مشاهدة الإعلان:",
                reply_markup=reply_markup
            )

            # ✅ تسجيل أن المستخدم لم يشاهد الإعلان بعد
            watched_ads[unique_id] = False

        else:
            raise Exception("⚠ الملف صغير جدًا أو غير صالح للإرسال!")

    except Exception as e:
        await query.edit_message_text(f"❌ حدث خطأ أثناء تحميل الصوت: {str(e)}")
        log_error(f"Error downloading audio: {e}")

    finally:
        # 🔹 حذف الملف بعد الاستخدام لتوفير المساحة
        if os.path.exists(final_audio):
            os.remove(final_audio)



async def watch_ad_and_send_audio(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()

    _, unique_id = query.data.split("|")

    # ✅ تسجيل أن المستخدم قد ضغط على مشاهدة الإعلان
    watched_ads[unique_id] = True  

    # إرسال رابط الإعلان
    await query.message.reply_text(f"🔗 اضغط على الرابط لمشاهدة الإعلان: {ADSTERRE_AD_URL}")

    # ✅ إظهار زر "تم مشاهدة الإعلان" بعد 10 ثوانٍ
    await asyncio.sleep(10)

    keyboard = [
        [InlineKeyboardButton("✅ تم مشاهدة الإعلان، أرسل الصوت", callback_data=f"send_audio|{unique_id}")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.message.reply_text("✅ بعد مشاهدة الإعلان، اضغط على الزر لإرسال الصوت:", reply_markup=reply_markup)


async def send_audio_after_ad(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()

    _, unique_id = query.data.split("|")
    audio_path = f"downloads/{unique_id}.mp3"

    if not os.path.exists(audio_path):
        await query.edit_message_text("⚠ الملف غير موجود أو تم حذفه!")
        return

    if watched_ads.get(unique_id, False):
        await query.edit_message_text("📤 جارٍ إرسال الصوت... ⏳")

        try:
            with open(audio_path, "rb") as audio_file:
                await query.message.reply_audio(audio=audio_file)

            await asyncio.sleep(2)  # تأخير بسيط لمنع الحظر
            await query.message.reply_text("✅ تم إرسال الصوت بنجاح! 🎉")

            # ✅ حذف الملف بعد الإرسال لتوفير المساحة
            os.remove(audio_path)
            print(f"🗑 تم حذف الملف بعد الإرسال: {audio_path}")

        except Exception as e:
            await query.message.reply_text(f"❌ حدث خطأ أثناء إرسال الصوت: {str(e)}")

    else:
        await query.message.reply_text("⚠ يجب مشاهدة الإعلان قبل استلام الصوت!")



# ❌ إلغاء التحميل
async def cancel_download(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("❌ تم إلغاء التحميل بنجاح!")

# 📝 تسجيل الأخطاء في ملف
def log_error(error_message):
    with open("log.txt", "a", encoding="utf-8") as log_file:
        log_file.write(f"{error_message}\n")

# 🚀 تشغيل البوت
def main():
    app = Application.builder().token(TOKEN).read_timeout(600).write_timeout(600).connect_timeout(600).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, receive_link))
    app.add_handler(CallbackQueryHandler(download_video, pattern="video.*"))
    app.add_handler(CallbackQueryHandler(download_audio, pattern="audio.*"))
    app.add_handler(CallbackQueryHandler(cancel_download, pattern="cancel_download"))
    app.add_handler(CallbackQueryHandler(watch_ad_and_send_video, pattern="watch_ad.*"))
    app.add_handler(CallbackQueryHandler(send_video_after_ad, pattern="send_video.*"))

    app.add_handler(CallbackQueryHandler(watch_ad_and_send_audio, pattern="watch_ad_audio.*"))
    app.add_handler(CallbackQueryHandler(send_audio_after_ad, pattern="send_audio.*"))








    print("✅ البوت يعمل الآن...")
    app.run_polling()

if __name__ == '__main__':
    main()