"""Entrée de la ligne de commande pour l'exécutable autonome."""
import multiprocessing
import sys

from dracoconv.cli import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())
