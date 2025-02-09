from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, CallbackContext, filters
import yt_dlp
import os
import uuid
import asyncio
import requests
import re




# 🔹 ضع هنا توكن البوت الخاص بك
TOKEN = "8012936074:AAFH1E_EkUgnoXG_kz-nTvnbLnvcezTpgcg"

# ✅ تخزين الروابط لمنع فقدان البيانات أثناء التحميل
link_storage = {}

# ✅ قفل منع الإرسال المكرر لكل فيديو
send_locks = {}

# 🛠️ دالة بدء تشغيل البوت
async def start(update: Update, context: CallbackContext) -> None:
    await update.message.reply_text("👋 أهلاً بك! أرسل لي رابط فيديو وسأقوم بتحميله لك.")

# 📥 استقبال الروابط وتحليلها
async def receive_link(update: Update, context: CallbackContext) -> None:
    url = update.message.text.strip()

    # 🔹 استخراج Video ID من رابط YouTube
    def extract_video_id(url):
        pattern = r"(?:v=|\/)([0-9A-Za-z_-]{11}).*"
        match = re.search(pattern, url)
        return match.group(1) if match else None

    if "youtube.com" in url or "youtu.be" in url:
        video_id = extract_video_id(url)
        print(f"🔍 Video ID Extracted: {video_id}")  # ✅ التحقق من استخراج الـ ID 
        
        if not video_id:
            await update.message.reply_text("⚠ لم يتم استخراج معرف الفيديو، تأكد من صحة الرابط!")
            return

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

    ydl_opts = {
        "format": "best[height<=480]",  # تحميل بجودة 480p لتجنب القيود
        "merge_output_format": "mp4",
        "outtmpl": output_video,
        "socket_timeout": 3600,
        "retries": 30,
        "fragment_retries": 30,
        "hls_prefer_native": True,
        "noplaylist": True,  # تأكد من تحميل الفيديو فقط وليس قائمة تشغيل
        "ignoreerrors": True,  # تجاوز الأخطاء
        "no_warnings": True,  # منع إظهار التحذيرات
        "force_generic_extractor": True,  # إجبار yt-dlp على استخدام استخراج عام
        "geo_bypass": True,  # تجاوز القيود الجغرافية
        "quiet": True,  # تقليل الإخراج لتجنب إزعاج المستخدم
        "cookiesfrombrowser": ("chrome",)  # ✅ استخدام كوكيز المتصفح مباشرة
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


# 📤 إرسال الفيديو بعد التحقق من حجمه
async def send_video(query, video_path):
    """إرسال الفيديو مرة واحدة فقط بعد التحقق من الحجم"""
    
    file_size = os.path.getsize(video_path)
    file_size_mb = file_size / (1024 * 1024)  # تحويل الحجم إلى MB
    
    if file_size_mb > 50:
        await query.message.reply_text(f"⚠ الفيديو كبير جدًا ({file_size_mb:.2f}MB)، لا يمكن إرساله عبر تيليغرام.")
        return

    try:
        await query.message.reply_text(f"📦 حجم الفيديو: {file_size_mb:.2f}MB، جارٍ الإرسال... ⏳")

        with open(video_path, "rb") as video_file:
            await query.message.reply_video(video=video_file)

        await asyncio.sleep(2)
        await query.message.reply_text("✅ تم إرسال الفيديو بنجاح! 🎉")

    except Exception:
        await query.message.reply_text("⏳ الفيديو الذي تحاول إرساله قد يكون كبيرًا أو الاتصال بطيء، يرجى الانتظار قليلاً...")

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

    output_audio = "downloads/audio.mp3"

    if os.path.exists(output_audio):
        os.remove(output_audio)

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

        await query.edit_message_text("✅ تم تحميل الصوت! جارٍ الإرسال... 🎵")
        with open(output_audio, "rb") as audio_file:
            await query.message.reply_audio(audio=audio_file)

    except Exception as e:
        await query.edit_message_text(f"❌ حدث خطأ أثناء تحميل الصوت: {str(e)}")

    finally:
        if os.path.exists(output_audio):
            os.remove(output_audio)

# ❌ إلغاء التحميل
async def cancel_download(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("❌ تم إلغاء التحميل بنجاح!")

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