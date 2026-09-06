"""Index the extracted flower evidence folders in a portable SQLite file."""
import argparse
import json
from pathlib import Path

from rollform_extractor.historical_roller_library import build_roller_library

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("library", type=Path)
    parser.add_argument("database", type=Path)
    args = parser.parse_args()
    print(json.dumps(build_roller_library(args.library, args.database), indent=2))
