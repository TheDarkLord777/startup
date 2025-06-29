from fastapi import FastAPI, File, UploadFile, Request, HTTPException, Form
from fastapi.responses import JSONResponse
import subprocess
import uuid
import os
import time
from pathlib import Path
import hashlib
from fastapi.middleware.cors import CORSMiddleware # CORSMiddleware import qilingan
import requests

app = FastAPI()

origins = [
    "http://localhost",
    "http://localhost:8000",
    "http://34.51.187.94",
    "http://34.51.187.94:8000",
    "http://34.51.187.94:8000/upload/",
    "http://34.51.187.94:8000/upload",
    "http://34.51.187.94:8000/upload",
    "*" ,
    "null",
     
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"]  # Expose all headers in the response
)

UPLOAD_DIR = Path("uploads/tmp")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

PROCESSED_FILE_HASHES = set() 
print(f"[INFO] Server ishga tushdi. PROCESSED_FILE_HASHES to'plami dastlabki holati: {len(PROCESSED_FILE_HASHES)} ta hash.")

@app.post("/upload/")
async def upload(request: Request, file: UploadFile = File(...)): # `UploadFile` obyektidan foydalanamiz
    print(f"[INFO] Yangi yuklash so'rovi keldi. Hozirda PROCESSED_FILE_HASHES: {len(PROCESSED_FILE_HASHES)} ta hash.")
    total_received = 0
    total_size = int(request.headers.get("content-length", 0)) # Bu Content-Length xizmat sarlavhasidan olinadi
    
    temp_input_filename = f"{uuid.uuid4()}_{file.filename}"
    temp_input_path = UPLOAD_DIR / temp_input_filename
    
    output_filename = f"{uuid.uuid4()}.wav"
    output_path = UPLOAD_DIR / output_filename

    SIZE_TOLERANCE_BYTES = 1024 
    
    file_hasher = hashlib.sha256() 

    try:
        # Fayl kontentini diskka yozish va progressni loglash
        # `file.read()` `UploadFile` obyektidan bo'laklab o'qiydi
        with open(temp_input_path, "wb") as buffer:
            while chunk := await file.read(1024 * 1024): # Faylni 1MB lik bo'laklarga bo'lib o'qish
                total_received += len(chunk)
                buffer.write(chunk)
                file_hasher.update(chunk) # Har bir bo'lakdan hash hisoblashda foydalanish
                percent = (total_received / total_size) * 100 if total_size else 0
                # Real vaqtda qabul qilish/diskka yozish progressi
                print(f"[INFO] Qabul qilinmoqda va diskka yozilmoqda: {total_received / 1024 / 1024:.2f} MB / {total_size / 1024 / 1024:.2f} MB ({percent:.2f}%)")

        # Fayl diskka to'liq yozilganini tasdiqlash logi
        print(f"[INFO] Fayl diskka to'liq yozildi: {temp_input_path.name}") 
        
        file_hash = file_hasher.hexdigest()

        # Fayl allaqachon qayta ishlanganligini tekshirish
        if file_hash in PROCESSED_FILE_HASHES:
            print(f"[INFO] Fayl takrorlandi: {file.filename} (Hash: {file_hash}). Qayta ishlov berilmaydi.")
            raise HTTPException(
                status_code=409, # Conflict status code
                detail=f"Bu fayl ({file.filename}) allaqachon qayta ishlangan. Hash: {file_hash}" # Xato xabariga hash qo'shildi
            )
        
        # Fayl yangi bo'lsa, uni hashlarga qo'shish
        PROCESSED_FILE_HASHES.add(file_hash)
        print(f"[INFO] Fayl hashi PROCESSED_FILE_HASHES'ga qo'shildi. Hozir: {len(PROCESSED_FILE_HASHES)} ta hash.")


        # Yuklash hajmi tekshiruvi
        if total_size > 0 and abs(total_received - total_size) > SIZE_TOLERANCE_BYTES:
            print(f"[ERROR] Yuklash hajmi mos kelmadi. Kutilgan: {total_size} bayt, Qabul qilingan: {total_received} bayt.")
            raise HTTPException(status_code=400, detail="Fayl to'liq yuklanmadi yoki hajmi mos kelmadi.")
        
        actual_written_size = temp_input_path.stat().st_size
        if total_size > 0 and abs(actual_written_size - total_size) > SIZE_TOLERANCE_BYTES:
            print(f"[ERROR] Diskka yozilgan fayl hajmi mos kelmadi. Kutilgan: {total_size} bayt, Yozilgan: {actual_written_size} bayt.")
            raise HTTPException(status_code=400, detail="Fayl to'liq yuklanmadi yoki diskka yozishda xato.")

        print(f"[INFO] FFmpeg jarayoni boshlanmoqda...") 
        process = subprocess.Popen(
            [
                "ffmpeg",
                "-loglevel", "error",
                "-analyzeduration", "100M",
                "-probesize", "100M",
                "-i", str(temp_input_path), # FFmpeg diskdagi faylni o'qiydi
                "-vn", "-ar", "16000", "-ac", "1", "-f", "wav",
                str(output_path)
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE
        )
        
        return_code = process.wait()
        stderr_output = process.stderr.read().decode(errors='ignore') if process.stderr else ""

        if return_code != 0:
            print(f"[FFMPEG ERROR - Exit Code {return_code}]:\n{stderr_output}")
            raise HTTPException(status_code=500, detail=f"FFmpeg xatosi (Exit Code {return_code}): {stderr_output.strip()}")

        if not output_path.exists() or output_path.stat().st_size < 1024 * 100:
            print(f"[FFMPEG OUTPUT WARNING]: Chiqish fayli mavjud emas yoki juda kichik.\n{stderr_output}")
            raise HTTPException(status_code=500, detail=f"Chiqish fayli mavjud emas yoki juda kichik. FFmpeg xatosi: {stderr_output.strip()}")

        # Bu tekshiruv fayl ishlanganidan keyin takrorlanmaydi, faqat kirishda tekshirish etarli.
        # Agar qandaydir sababga ko'ra bu yerga qayta kelsa, ehtiyot chorasi.
        # Bu yerda temp_input_path.exists() sharti ortiqcha, chunki fayl hozirgina ishlandi.
        # Asosiy tekshiruv fayl hashi to'plamda bor-yo'qligi bo'lishi kerak.
        # if file_hash in PROCESSED_FILE_HASHES and temp_input_path.exists(): # Hash allaqachon mavjud bo'lsa va fayl ham bo'lsa
        #     print(f"[INFO] Fayl takrorlandi (keyinroq aniqlandi): {file_hash}).")
        #     if output_path.exists():
        #         os.remove(output_path)
        #         print(f"[CLEANUP] Takrorlangan fayl bo'lganligi sababli WAV o'chirildi: {output_path.name}")
        #     raise HTTPException(
        #         status_code=409, 
        #         detail=f"Bu fayl allaqachon qayta ishlangan. Hash: {file_hash}"
        #     )
        
        print(f"[INFO] Fayl muvaffaqiyatli qayta ishlandi: {output_path.name}") 

        return JSONResponse(content={
            "status": "success",
            "received_mb": round(total_received / 1024 / 1024, 2),
            "total_mb": round(total_size / 1024 / 1024, 2),
            "percentage": f"{(total_received / total_size) * 100:.2f}%" if total_size else "unknown",
            "output": str(output_path.name),
            "file_hash": file_hash
        })

    except HTTPException as he:
        # Xato yuz bersa, agar hash saqlangan bo'lsa, uni olib tashlash
        if 'file_hash' in locals() and file_hash in PROCESSED_FILE_HASHES: # Tuzatilgan tekshiruv
            PROCESSED_FILE_HASHES.remove(file_hash)
        raise he
    except Exception as e:
        print(f"[ERROR] Umumiy xato yuz berdi: {e}")
        # Xato yuz bersa, agar hash saqlangan bo'lsa, uni olib tashlash
        if 'file_hash' in locals() and file_hash in PROCESSED_FILE_HASHES: # Tuzatilgan tekshiruv
            PROCESSED_FILE_HASHES.remove(file_hash)
        raise HTTPException(status_code=500, detail=f"Serverda xato yuz berdi: {str(e)}")
    finally:
        if temp_input_path.exists():
            try:
                os.remove(temp_input_path)
                print(f"[CLEANUP] Deleted temporary input file: {temp_input_path.name}")
            except Exception as e:
                print(f"[CLEANUP ERROR] Could not delete temp input file {temp_input_path.name}: {e}")
        
        # Natijaviy WAV faylni faqatgina xato holatida tozalash
        # Bu qism faqat yuqoridagi 'try' blokidan HTTPException chiqsa ishga tushadi
        if 'output_path' in locals() and output_path.exists() and "he" in locals():
            if isinstance(he, HTTPException) and he.status_code != 200: 
                try:
                    os.remove(output_path)
                    print(f"[CLEANUP] Xato tufayli natijaviy WAV fayl o'chirildi: {output_path.name}")
                except Exception as e:
                    print(f"[CLEANUP ERROR] Natijaviy WAV faylni o'chirishda xato: {output_path.name}: {e}")

@app.post("/upload_and_ask/")
async def upload_and_ask(wav_filename: str = Form(...), question: str = Form(...)):
    """
    Send a processed WAV file and a question to the external API.
    
    Args:
        wav_filename: The name of the processed WAV file to send
        question: The question to ask about the file
    """
    try:
        # Check if the WAV file exists
        wav_path = UPLOAD_DIR / wav_filename
        if not wav_path.exists():
            raise HTTPException(status_code=404, detail=f"WAV file not found: {wav_filename}")
        
        print(f"[INFO] Sending WAV file {wav_filename} with question: {question}")
        
        # Prepare the files and data for the request
        files = {
            'file': (wav_filename, open(wav_path, 'rb'), 'audio/wav')
        }
        data = {
            'question': question
        }
        
        # Send the request to the external API
        response = requests.post(
            'http://152.70.188.165:18000/upload_and_ask/',
            files=files,
            data=data
        )
        
        # Check if the request was successful
        response.raise_for_status()
        
        # Return the response from the external API
        return response.json()
    
    except requests.RequestException as e:
        print(f"[ERROR] Request to external API failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to communicate with external API: {str(e)}")
    except Exception as e:
        print(f"[ERROR] Error in upload_and_ask: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Server error: {str(e)}")
    finally:
        # Close any open file handles
        if 'files' in locals() and 'file' in files:
            files['file'][1].close()
