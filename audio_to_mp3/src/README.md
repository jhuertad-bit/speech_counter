# audio_to_mp3

Cloud Function (Gen2) que convierte **cualquier formato de audio** detectado en GCS hacia **MP3**, en la misma línea que `ogg_to_mp3` pero universal.

## Diferencia con `ogg_to_mp3`

| | `ogg_to_mp3` | `audio_to_mp3` |
|---|--------------|----------------|
| Entrada | Solo `.ogg` | OGG, Opus, WAV, FLAC, M4A, AAC, WMA, AMR, WebM, MP4 (audio), etc. |
| Detección | Por extensión | Extensión + **ffprobe** (valida stream de audio) |
| Motor | pydub + ffmpeg fallback | pydub (con hint por extensión) + **ffmpeg** universal |

## Flujo

```
GCS (audio cualquier formato)
        │ Eventarc object.finalized
        ▼
Cloud Function audio_to_mp3_converter
  • ffprobe valida audio
  • convierte con pydub o ffmpeg (libmp3lame)
        ▼
GCS path_audios_mp3/.../*.mp3
```

## Formatos soportados (configurables)

`.ogg`, `.opus`, `.wav`, `.flac`, `.m4a`, `.aac`, `.wma`, `.amr`, `.3gp`, `.mp4`, `.webm`, `.aiff`, `.caf`, `.mp2`

Archivos `.mp3` en la ruta de entrada se ignoran. Si el MP3 destino ya existe, se omite (`skip_existing_mp3`).

## Requisitos en la imagen

- **ffmpeg** + **ffprobe** (Paquete Debian en `Dockerfile`)
- **pydub** como atajo para formatos comunes
- **libmp3lame** incluido en ffmpeg para salida MP3

## Configuración

`config/config.json`:

- `path_audios_input` — prefijo donde llegan los audios origen
- `path_audios_mp3` — prefijo de salida MP3 (misma partición `fecha_descarga` / `hora_descarga`)
- `audio.supported_extensions` — lista de extensiones
- `audio.default_bitrate` — fallback si no se detecta bitrate

## Despliegue

```bash
cd audio_to_mp3
chmod +x deploy.sh
./deploy.sh
```

Dry-run:

```bash
./deploy.sh --dry-run
```

## Prueba local (sin GCS)

```bash
pip install -r requirements.txt
# Requiere ffmpeg instalado en el sistema
python -c "
from converter import convert_audio_to_mp3
convert_audio_to_mp3('entrada.wav', 'salida.mp3', 'entrada.wav', {'default_bitrate':'128k'})
print('OK')
"
```

## Coexistencia con `ogg_to_mp3`

Puedes usar solo `audio_to_mp3` (cubre OGG también) y desactivar `ogg_to_mp3` para evitar doble conversión, **o** apuntar a prefijos distintos en `config.json`.
