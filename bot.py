from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, CallbackContext, filters
import yt_dlp
import os
import uuid
import asyncio
import requests


from googleapiclient.discovery import build

# 🔹 ضع هنا توكن البوت الخاص بك
TOKEN = "8012936074:AAFH1E_EkUgnoXG_kz-nTvnbLnvcezTpgcg"

# 🔹 ضع مفتاح YouTube API هنا (لا تشاركه علنًا)
YOUTUBE_API_KEY = "AIzaSyAHqf88q04r7a9DThE_JvqyvD1FH_Ge-sc"

# ✅ إنشاء كائن YouTube API
youtube = build("youtube", "v3", developerKey=YOUTUBE_API_KEY)

def get_video_info(video_id):
    """🔍 جلب معلومات فيديو YouTube"""
    try:
        request = youtube.videos().list(
            part="snippet,contentDetails",
            id=video_id
        )
        response = request.execute()

        if "items" in response and len(response["items"]) > 0:
            video = response["items"][0]
            title = video["snippet"]["title"]
            description = video["snippet"]["description"][:300] + "..."  # اختصار الوصف
            thumbnail = video["snippet"]["thumbnails"]["high"]["url"]
            return title, description, thumbnail
        else:
            return None, None, None
    except Exception as e:
        print(f"❌ خطأ في جلب البيانات: {e}")
        return None, None, None



# ✅ تخزين الروابط لمنع فقدان البيانات أثناء التحميل
link_storage = {}

# ✅ قفل منع الإرسال المكرر لكل فيديو
send_locks = {}

# 🛠️ دالة بدء تشغيل البوت
async def start(update: Update, context: CallbackContext) -> None:
    await update.message.reply_text("👋 أهلاً بك! أرسل لي رابط فيديو وسأقوم بتحميله لك.")

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

    # 🔹 إذا كان الرابط من Pinterest ولكنه مختصر، قم بفك الاختصار
    if "pin.it" in url:
        expanded_url = expand_pinterest_url(url)
        if expanded_url:
            url = expanded_url  # استخدم الرابط الحقيقي بدلاً من المختصر

    # 🔹 التحقق مما إذا كان الرابط من YouTube
    if "youtube.com" in url or "youtu.be" in url:
        video_id = url.split("v=")[-1] if "v=" in url else url.split("/")[-1]
        title, description, thumbnail = get_video_info(video_id)  # جلب معلومات الفيديو من API

        if title:
            unique_id = str(uuid.uuid4())[:8]
            link_storage[unique_id] = url  

            keyboard = [
                [InlineKeyboardButton("🎥 تحميل الفيديو", callback_data=f"video|{unique_id}")],
                [InlineKeyboardButton("🎵 تحميل الصوت فقط", callback_data=f"audio|{unique_id}")],
                [InlineKeyboardButton("❌ إلغاء التحميل", callback_data="cancel_download")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            message = f"🎬 **العنوان:** {title}\n📜 **الوصف:** {description}"
            await update.message.reply_photo(photo=thumbnail, caption=message, reply_markup=reply_markup)
        else:
            await update.message.reply_text("⚠ لم يتم العثور على الفيديو!")

    # 🔹 باقي المنصات تبقى كما هي
    elif any(platform in url for platform in ["facebook.com", "fb.watch", "instagram.com", "tiktok.com", "twitter.com", "pinterest.com"]):
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
        "format": "bestvideo[height<=480]+bestaudio/best[height<=480]",  # تحميل بجودة 480p ليوتيوب
        "merge_output_format": "mp4",
        "outtmpl": output_video,
        "socket_timeout": 3600,
        "retries": 30,
        "fragment_retries": 30,
        "hls_prefer_native": True,
        "cookiefile": "cookies.txt"  # إضافة ملف الكوكيز
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
        "cookiefile": "cookies.txt"  # إضافة ملف الكوكيز
     }


    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        if os.path.exists(output_video):
            await query.edit_message_text("✅ تم تحميل الفيديو! جارٍ الإرسال... 📤")
            await asyncio.sleep(1)

            # ✅ إنشاء قفل خاص بهذا unique_id إذا لم يكن موجودًا
            if unique_id not in send_locks:
                send_locks[unique_id] = asyncio.Lock()

            # ✅ تنفيذ الإرسال داخل القفل لتجنب التكرار
            async with send_locks[unique_id]:
                await send_video(query, output_video)

    except Exception as e:
        await query.edit_message_text(f"❌ حدث خطأ أثناء تحميل الفيديو: {str(e)}")

    finally:
        if unique_id in send_locks:
            del send_locks[unique_id]  # 🔹 إزالة القفل بعد الإرسال
        if os.path.exists(output_video):
            os.remove(output_video)


# 📤 إرسال الفيديو بمحاولة واحدة فقط
MAX_TELEGRAM_VIDEO_SIZE = 50 * 1024 * 1024  # 50MB بالبايت

# 📤 إرسال الفيديو بعد التحقق من حجمه
async def send_video(query, video_path):
    """إرسال الفيديو مرة واحدة فقط بعد التحقق من الحجم"""
    
    file_size = os.path.getsize(video_path)  # الحصول على حجم الفيديو بالبايت
    file_size_mb = file_size / (1024 * 1024)  # تحويل الحجم إلى MB
    
    # ✅ إذا كان الفيديو أكبر من 50MB، لا يتم إرساله
    if file_size_mb > 50:
        await query.message.reply_text(
            f"⚠ الفيديو كبير جدًا ({file_size_mb:.2f}MB)، لا يمكن إرساله عبر تيليغرام."
        )
        return  # إيقاف التنفيذ

    try:
        # ✅ إذا كان الحجم أقل من 50MB، يتم الإرسال
        await query.message.reply_text(f"📦 حجم الفيديو: {file_size_mb:.2f}MB، جارٍ الإرسال... ⏳")

        with open(video_path, "rb") as video_file:
            await query.message.reply_video(video=video_file)

        await asyncio.sleep(2)  # تأخير بسيط لمنع الحظر
        await query.message.reply_text("✅ تم إرسال الفيديو بنجاح! 🎉")

    except Exception:
        # ✅ تغيير الرسالة عند حدوث خطأ أثناء الإرسال
        await query.message.reply_text(
            "⏳ الفيديو الذي تحاول إرساله قد يكون كبيرًا أو الاتصال بطيء، يرجى الانتظار قليلاً..."
        )



# 🎵 تحميل الصوت
async def download_audio(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()

    _, unique_id = query.data.split("|")
    url = link_storage.get(unique_id)

    if not url:
        await query.edit_message_text("⚠ الرابط غير صالح أو انتهت صلاحيته!")
        return

    await query.edit_message_text("⏳ جارٍ تحميل الصوت، الرجاء الانتظار...")

    output_audio = "downloads/audio"
    final_audio = "downloads/final_audio.mp3"

    for file in [output_audio + ".mp3", output_audio + ".m4a", final_audio]:
        if os.path.exists(file):
            os.remove(file)

    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": output_audio,  
        "postprocessors": [
            {"key": "FFmpegExtractAudio", "preferredcodec": "mp3"},
            {"key": "FFmpegMetadata"}  
        ]
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        await asyncio.sleep(1.5)

        downloaded_files = [f for f in os.listdir("downloads") if f.startswith("audio") and f.endswith((".mp3", ".m4a", ".webm"))]
        if not downloaded_files:
            raise Exception("⚠ لم يتم العثور على الملف الصوتي بعد التحميل!")

        downloaded_audio = os.path.join("downloads", downloaded_files[0])

        if not downloaded_audio.endswith(".mp3"):
            converted_audio = downloaded_audio.rsplit(".", 1)[0] + ".mp3"
            os.system(f'ffmpeg -i "{downloaded_audio}" -vn -acodec libmp3lame "{converted_audio}" -y')
            os.remove(downloaded_audio)
            downloaded_audio = converted_audio

        os.rename(downloaded_audio, final_audio)

        if os.path.exists(final_audio) and os.path.getsize(final_audio) > 100 * 1024:
            await query.edit_message_text("✅ تم تحميل الصوت! جارٍ الإرسال... 🎵")
            with open(final_audio, "rb") as audio_file:
                await query.message.reply_audio(audio=audio_file)
        else:
            raise Exception("⚠ الملف صغير جدًا أو غير صالح للإرسال!")

    except Exception as e:
        await query.edit_message_text(f"❌ حدث خطأ أثناء تحميل الصوت: {str(e)}")
        log_error(f"Error downloading audio: {e}")

    finally:
        if os.path.exists(final_audio):
            os.remove(final_audio)

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

    print("✅ البوت يعمل الآن...")
    app.run_polling()

if __name__ == '__main__':
    main()