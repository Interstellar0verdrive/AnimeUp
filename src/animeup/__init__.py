"""animeup - upscale batch di anime su Apple Silicon.

Riscrittura 2026 di upscale_batch_v5.sh, con tre obiettivi:
  - non degradare mai il sorgente prima di darlo in pasto al modello
  - analizzare i tempi in modo corretto invece che euristico
  - lavorare a blocchi, per rendere fattibili i file lunghi e ripartire dopo un crash
"""

__version__ = "2.0.0"
