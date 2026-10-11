import json, os, base64, subprocess, textwrap, time
import requests

ACC = os.environ["CF_ACCOUNT_ID"]
TOK = os.environ["CF_API_TOKEN"]
VOZ = "voices/es_ES-mls_10246-low.onnx"
FUENTE = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
W, H, FPS = 1080, 1920, 30
ESTILO = ("warm colorful 2D animated film illustration, soft golden light, "
          "expressive faces, everyday setting, vertical composition, no text, no letters")


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


def audio(texto, ruta):
    run(["piper", "--model", VOZ, "--output_file", ruta], input=texto.encode("utf-8"))


def duracion(ruta):
    s = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", ruta],
        capture_output=True, text=True, check=True).stdout
    return float(s.strip())


def clip(i, texto, img, wav, salida):
    total = duracion(wav) + 0.6
    frames = int(total * FPS) + 1
    sub = "trabajo/sub_%d.txt" % i
    with open(sub, "w", encoding="utf-8") as f:
        f.write(textwrap.fill(texto, 28))
    if i % 2 == 1:
        z = "min(zoom+0.0006,1.2)"
    else:
        z = "if(eq(on,1),1.2,max(zoom-0.0006,1.0))"
    vf = ("crop=ih*9/16:ih,scale=1620:2880,"
          "zoompan=z='%s':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=%d:s=%dx%d:fps=%d,"
          "drawtext=fontfile=%s:textfile=%s:expansion=none:fontsize=50:"
          "fontcolor=white:borderw=5:bordercolor=black:x=(w-text_w)/2:y=h*0.62:"
          "line_spacing=12,format=yuv420p") % (z, frames, W, H, FPS, FUENTE, sub)
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
        wav = "trabajo/voz_%d.wav" % i
        out = "trabajo/clip_%d.mp4" % i
        imagen(prompt, img)
        audio(e["narracion"], wav)
        duracion_total += clip(i, e["narracion"], img, wav, out)
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
