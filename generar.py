
import json, os, base64, subprocess, textwrap, time
import requests

ACC = os.environ["CF_ACCOUNT_ID"]
TOK = os.environ["CF_API_TOKEN"]
VOZ = "voices/es_ES-mls_10246-low.onnx"
FUENTE = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
W, H, FPS = 1080, 1920, 30
VELOCIDAD = 1.15
RELLENO = 0.2
ESTILO = ("warm colorful 2D animated film illustration, soft golden light, "
          "expressive faces, everyday setting, vertical composition, no text, no letters")

LIMPIA = ("silenceremove=start_periods=1:start_silence=0.03:start_threshold=-45dB:"
          "stop_periods=-1:stop_duration=0.3:stop_silence=0.15:stop_threshold=-45dB,"
          "areverse,"
          "silenceremove=start_periods=1:start_silence=0.03:start_threshold=-45dB,"
          "areverse,"
          "atempo=%s,dynaudnorm=f=150:g=15,volume=1.5,alimiter=limit=0.9" % VELOCIDAD)


def run(cmd, **kw):
    subprocess.run(cmd, check=True, **kw)


def imagen(prompt, ruta):
    url = ("https://api.cloudflare.com/client/v4/accounts/%s/ai/run/"
           "@cf/black-forest-labs/flux-1-schnell" % ACC)
    for intento in range(4):
        r = requests.post(url, headers={"Authorization": "Bearer " + TOK},
                          json={"prompt": prompt, "steps": 4}, timeout=120)
        if r.ok:
            img = r.json().get("result", {}).get("image")
            if img:
                with open(ruta, "wb") as f:
                    f.write(base64.b64decode(img))
                return
        print("Reintento imagen:", r.status_code, r.text[:200])
        time.sleep(5 * (intento + 1))
    raise RuntimeError("No se pudo generar la imagen")


def audio(texto, ruta_final, ruta_cruda):
    run(["piper", "--model", VOZ, "--output_file", ruta_cruda], input=texto.encode("utf-8"))
    run(["ffmpeg", "-y", "-i", ruta_cruda, "-af", LIMPIA, ruta_final])


def duracion(ruta):
    s = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", ruta],
        capture_output=True, text=True, check=True).stdout
    return float(s.strip())


def clip(i, texto, img, wav, salida):
    total = duracion(wav) + RELLENO
    frames = int(total * FPS) + 1
    sub = "trabajo/sub_%d.txt" % i
    with open(sub, "w", encoding="utf-8") as f:
        f.write(textwrap.fill(texto, 28))
    modo = i % 3
    x = "iw/2-(iw/zoom/2)"
    if modo == 1:
        z = "min(zoom+0.0012,1.35)"
    elif modo == 2:
        z = "if(eq(on,1),1.35,max(zoom-0.0012,1.0))"
    else:
        z = "1.25"
        x = "(iw-iw/zoom)*on/%d" % frames
    vf = ("crop=ih*9/16:ih,scale=1620:2880,"
          "zoompan=z='%s':x='%s':y='ih/2-(ih/zoom/2)':d=%d:s=%dx%d:fps=%d,"
          "drawtext=fontfile=%s:textfile=%s:expansion=none:fontsize=50:"
          "fontcolor=white:borderw=5:bordercolor=black:x=(w-text_w)/2:y=h*0.62:"
          "line_spacing=12,format=yuv420p") % (z, x, frames, W, H, FPS, FUENTE, sub)
    run(["ffmpeg", "-y", "-i", img, "-i", wav, "-vf", vf, "-af", "apad",
         "-t", "%.2f" % total, "-r", str(FPS), "-c:v", "libx264",
         "-preset", "veryfast", "-crf", "26", "-c:a", "aac",
         "-ar", "44100", "-ac", "2", salida])
    return total


def main():
    g = json.load(open("guion.json", encoding="utf-8"))
    os.makedirs("trabajo", exist_ok=True)
    os.makedirs("salida", exist_ok=True)
    clips = []
    duracion_total = 0
    for i, e in enumerate(g["escenas"], 1):
        desc = " ".join(g["personajes"][n] for n in e.get("personajes", []))
        prompt = "%s. %s %s" % (ESTILO, desc, e["imagen"])
        img = "trabajo/img_%d.jpg" % i
        cruda = "trabajo/voz_cruda_%d.wav" % i
        wav = "trabajo/voz_%d.wav" % i
        out = "trabajo/clip_%d.mp4" % i
        imagen(prompt, img)
        audio(e["narracion"], wav, cruda)
        duracion_total += clip(i, e["narracion"], img, wav, out)
        clips.append(out)
        print("Escena", i, "lista")
    with open("trabajo/lista.txt", "w") as f:
        for c in clips:
            f.write("file '%s'\n" % os.path.basename(c))
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", "trabajo/lista.txt",
         "-c", "copy", "trabajo/union.mp4"])
    run(["ffmpeg", "-y", "-i", "trabajo/union.mp4",
         "-af", "loudnorm=I=-16:TP=-1.5:LRA=7", "-c:v", "copy",
         "-c:a", "aac", "-ar", "44100", "-ac", "2", "salida/final.mp4"])
    with open("salida/caption.txt", "w", encoding="utf-8") as f:
        f.write(g["titulo"] + "\n\n" + g["descripcion"] + "\n\n" + g["hashtags"])
    print("Duracion total aprox: %.1f s" % duracion_total)


main()
