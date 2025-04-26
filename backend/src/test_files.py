#!/usr/bin/env python3
import glob
import os
import subprocess

# Directory paths
test_files_dir = "../data/test_files/"
database_dirs = {
    "v1": "../data/database/fingerprints_v1/",
    "v2": "../data/database/fingerprints_v2/",
    "both": "../data/database/fingerprints_both/",
}

# Get all audio files
audio_files = []
for ext in [".wav", ".mp3", ".flac", ".m4a", ".ogg"]:
    audio_files.extend(glob.glob(os.path.join(test_files_dir, f"*{ext}")))

print(f"Found {len(audio_files)} audio files to process")


# Function to run identification and capture output
def run_identification(file_path, db_path, hash_method):
    cmd = [
        "python3",
        "main.py",
        "identify",
        file_path,
        "--db",
        db_path,
        "--workers",
        "4",
        "--hash-method",
        hash_method,
    ]

    try:
        process = subprocess.run(cmd, capture_output=True, text=True)
        output = process.stdout

        # Check if no matches were found
        if "No matches found" in output:
            return None

        # Extract the match information
        match_info = None
        for line in output.split("\n"):
            if "Song Name:" in line and "Confidence:" in line:
                match_info = line
                break

        return match_info
    except Exception as e:
        print(f"Error running identification for {file_path}: {e}")
        return None


# Process each hash method separately
for hash_method in ["v1", "v2", "both"]:
    print(f"\n\n=== Results for {hash_method} hash method ===\n")

    for file_path in sorted(audio_files):
        file_name = os.path.basename(file_path)
        db_path = database_dirs[hash_method]

        print(f"Processing {file_name}...", end=" ", flush=True)
        match_info = run_identification(file_path, db_path, hash_method)

        if match_info:
            # Extract information from the match line
            parts = match_info.split(", ")
            song_name = parts[0].replace("Song Name: ", "")
            confidence = parts[1].replace("Confidence: ", "")
            offset = parts[2].replace("Offset: ", "")
            match_count = parts[3].replace("Match Count: ", "")

            print("Match found!")
            print(
                f"{file_name} - {song_name} - {confidence} - {offset} - {match_count}"
            )
        else:
            print("No match found")
            print(f"{file_name} - No match found")
