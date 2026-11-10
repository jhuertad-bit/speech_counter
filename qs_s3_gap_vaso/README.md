# qs_s3_gap_vaso

Job Cloud Run **dedicado** al backfill vaso (`.audio` ∪ prefijo Ticketero ≠ 6).

Misma prep de audio que `qs_s3_to_gcs` (FLAC + loudnorm + split STT). Downstream: **STT Chirp** (`qsmart_transcribe`), ya no Whisper.

No modifica ni despliega `qs_s3_to_gcs`.

Ver [docs/README.md](docs/README.md) y `queuesmart_vaso` (workflow).
