import json, os, base64, subprocess, textwrap, time
import requests

ACC = os.environ["CF_ACCOUNT_ID"]
TOK = os.environ["CF_API_TOKEN"]
FUENTE = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
W, H, FPS = 1080, 1920, 30
VELOCIDAD = 1.1
RELLENO = 0.25
VOZ_PRINCIPAL = "voices/es_ES-davefx-medium.onnx"
VOZ_RESPALDO = "voices/es_ES-mls_10246-low.onnx"
URL_VOZ = ("https://huggingface.co/rhasspy/piper-voices/resolve/main/"
           "es/es_ES/davefx/medium/es_ES-davefx-medium.onnx")
ESTILO = ("warm colorful 2D animated film illustration, soft golden light, "
          "expressive faces, everyday setting, vertical composition, no text, no letters")
ENCUADRES = ["wide establishing shot",
             "close-up shot of the characters, emotional detail, different camera angle"]
BASE = "https://api.cloudflare.com/client/v4/accounts/%s/ai/run/" % ACC
LIMPIA = ("silenceremove=start_periods=1:start_silence=0.03:start_threshold=-45dB,"
          "areverse,"
          "silenceremove=start_periods=1:start_silence=0.03:start_threshold=-45dB,"
          "areverse,"
          "atempo=%s,loudnorm=I=-16:TP=-1.5:LRA=7" % VELOCIDAD)


def run(cmd, **kw):
    subprocess.run(cmd, check=True, **kw)


def descargar(url, ruta):
    r = requests.get(url, stream=True, timeout=300)
    r.raise_for_status()
    with open(ruta, "wb") as f:
        for trozo in r.iter_content(1 << 20):
            f.write(trozo)


def preparar_voz():
    try:
        os.makedirs("voices", exist_ok=True)
        for ext in ("", ".json"):
            if not os.path.exists(VOZ_PRINCIPAL + ext):
                descargar(URL_VOZ + ext, VOZ_PRINCIPAL + ext)
        print("Voz: es_MX claude high")
        return VOZ_PRINCIPAL
    except Exception as e:
        print("No se pudo descargar la voz alta, uso la anterior:", e)
        return VOZ_RESPALDO


def imagen(prompt, ruta):
    url = BASE + "@cf/black-forest-labs/flux-1-schnell"
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


def audio(voz, texto, ruta_final, ruta_cruda):
    run(["piper", "--model", voz, "--output_file", ruta_cruda],
        input=texto.encode("utf-8"))
    run(["ffmpeg", "-y", "-i", ruta_cruda, "-af", LIMPIA, ruta_final])


def duracion(ruta):
    s = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", ruta],
        capture_output=True, text=True, check=True).stdout
    return float(s.strip())


def parte(i, j, img, txt, seg, salida):
    frames = int(seg * FPS) + 1
    sub = "trabajo/sub_%d_%d.txt" % (i, j)
    with open(sub, "w", encoding="utf-8") as f:
        f.write(textwrap.fill(txt, 28))
    m = (2 * (i - 1) + j) % 4
    x = "iw/2-(iw/zoom/2)"
    if m == 0:
        z = "min(zoom+0.0013,1.4)"
    elif m == 1:
        z = "if(eq(on,1),1.4,max(zoom-0.0013,1.0))"
    elif m == 2:
        z = "1.3"
        x = "(iw-iw/zoom)*on/%d" % frames
    else:
        z = "1.3"
        x = "(iw-iw/zoom)*(1-on/%d)" % frames
    vf = ("crop=ih*9/16:ih,scale=1620:2880,"
          "zoompan=z='%s':x='%s':y='ih/2-(ih/zoom/2)':d=%d:s=%dx%d:fps=%d,"
          "drawtext=fontfile=%s:textfile=%s:expansion=none:fontsize=50:"
          "fontcolor=white:borderw=5:bordercolor=black:x=(w-text_w)/2:y=h*0.62:"
          "line_spacing=12,"
          "fade=t=in:st=0:d=0.12,fade=t=out:st=%.2f:d=0.12,format=yuv420p"
          ) % (z, x, frames, W, H, FPS, FUENTE, sub, max(seg - 0.12, 0))
    run(["ffmpeg", "-y", "-i", img, "-vf", vf, "-t", "%.2f" % seg, "-r", str(FPS),
         "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "26", salida])


def clip(i, texto, imgs, wav, salida):
    total = duracion(wav) + RELLENO
    seg = total / 2
    palabras = texto.split()
    k = max(1, len(palabras) // 2)
    textos = [" ".join(palabras[:k]), " ".join(palabras[k:]) or texto]
    partes = []
    for j in range(2):
        p = "trabajo/p_%d_%d.mp4" % (i, j)
        parte(i, j, imgs[j], textos[j], seg, p)
        partes.append(p)
    lista = "trabajo/lista_%d.txt" % i
    with open(lista, "w") as f:
        for p in partes:
            f.write("file '%s'\n" % os.path.basename(p))
    video = "trabajo/v_%d.mp4" % i
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", lista,
         "-c", "copy", video])
    run(["ffmpeg", "-y", "-i", video, "-i", wav, "-map", "0:v", "-map", "1:a",
         "-af", "apad", "-t", "%.2f" % total, "-c:v", "copy", "-c:a", "aac",
         "-ar", "44100", "-ac", "2", salida])
    return total


def main():
    voz = preparar_voz()
    g = json.load(open("guion.json", encoding="utf-8"))
    os.makedirs("trabajo", exist_ok=True)
    os.makedirs("salida", exist_ok=True)
    clips = []
    duracion_total = 0
    for i, e in enumerate(g["escenas"], 1):
        desc = " ".join(g["personajes"][n] for n in e.get("personajes", []))
        imgs = []
        for j, enc in enumerate(ENCUADRES):
            prompt = "%s. %s %s, %s" % (ESTILO, desc, e["imagen"], enc)
            ruta = "trabajo/img_%d_%d.jpg" % (i, j)
            imagen(prompt, ruta)
            imgs.append(ruta)
        cruda = "trabajo/voz_cruda_%d.wav" % i
        wav = "trabajo/voz_%d.wav" % i
        out = "trabajo/clip_%d.mp4" % i
        audio(voz, e["narracion"], wav, cruda)
        duracion_total += clip(i, e["narracion"], imgs, wav, out)
        clips.append(out)
        print("Escena", i, "lista")
    with open("trabajo/lista.txt", "w") as f:
        for c in clips:
            f.write("file '%s'\n" % os.path.basename(c))
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", "trabajo/lista.txt",
         "-c", "copy", "salida/final.mp4"])
    with open("salida/caption.txt", "w", encoding="utf-8") as f:
        f.write(g["titulo"] + "\n\n" + g["descripcion"] + "\n\n" + g["hashtags"])
    print("Duracion total aprox: %.1f s" % duracion_total)


main()

