import json
import os
import re

from pymediainfo import MediaInfo

directory = r"YOUR SONG DIRECTORY HERE"

output_file = "metadata_output.json"

metadata_list = []

for filename in os.listdir(directory):
    if filename.lower().endswith(".wav"):
        file_path = os.path.join(directory, filename)
        media_info = MediaInfo.parse(file_path)

        id = None
        song_name = None
        artist = None
        album = None
        youtube_link = None
        count = 0

        for track in media_info.tracks:
            if track.track_type == "General":
                id = f"song_{count}"
                song_name = track.title or track.track_name
                album = track.album
                artist = track.performer
                if track.comment:
                    match = re.search(r"https?://[^\s]+", track.comment)
                    youtube_link = match.group(0) if match else None
                break

        song_id = id if id else ""
        song_name = song_name if song_name else ""
        artist = artist if artist else ""
        album = album if album else ""
        youtube_link = youtube_link if youtube_link else ""

        metadata_list.append(
            {
                "id": song_id,
                "artist": artist,
                "title": song_name,
                "album": album,
                "url": youtube_link,
            }
        )

with open(output_file, "w", encoding="utf-8") as outfile:
    json.dump(metadata_list, outfile, indent=4, ensure_ascii=False)

print(f"Metadata saved to {output_file}")
