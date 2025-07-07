# Reverse Engineering Shazam

## Overview

This repository contains a reverse engineering of the Shazam app, which is used for music recognition. The goal of this project is to understand how the app works and to create a similar app using Python.

> [!NOTE]
> Built for a submission for the Project in Mathematics module at Nottingham Trent University.

## Requirements

To run the code, you need to create a virtual environment and install the required packages. You can do this by running the following command in the `backend` directory:

```bash
pip install -r requirements.txt
```

## Usage

There is a separate Drive link, containing a pre-built database of fingerprints. You can use this database to identify songs without having to build your own database. The drive can be found [here](https://drive.google.com/drive/folders/1oSW3iTOMQcXB8543ogFkoi89Y0OF6p9s?usp=sharing).

It is recommended to use the pre-built database, as building your own database can take a long time. However, if you want to build your own database, you can do so by following the instructions at the end of this README.

## CLI

### Identify

To identify a song using the CLI, you can use the following command:

```bash
python main.py identify <path_to_audio_file> --dir <path_to_database_directory>
```

If you're using the Google Drive version of the code, you can use the following command:

```bash
python main.py identify <path_to_audio_file> --dir ../data/database/
```

There are optional arguments you can use with the `identify` command:

- `--hash-method` - Hash method to use for fingerprinting (default: 'both', options: 'v1', 'v2', 'both')
- `--duration` - Duration of the audio file to use for fingerprinting (default: 30 seconds)
- `--threshold` - Threshold for the fingerprinting algorithm (default: 0.05)
- `--workers` - Number of workers to use for fingerprinting (default: 4)

### Build Database

To build your own database, you can use the following command:

```bash
python main.py fingerprint --dir <path_to_song_directory> --db <path_to_database_directory>
```

There are optional arguments you can use with the `fingerprint` command:

- `--workers` - Number of workers to use for building the database (default: 1)
- `--songs-per-db` - Number of songs to include in each database file (default: 25)
- `--hash-method` - Hash method to use for fingerprinting (default: 'both', options: 'v1', 'v2', 'both')
- `--chunk_size` - How many seconds to chunk the audio file into (default: 30)

### REST API - Inbuilt Website

To run the app, you need to have Python and Node installed. You can run the app on the Front by executing the following command in the `backend` directory:

```bash
python api.py
```

In the `frontend` directory, you can run the NextJS app by executing the following command (Note: You need to do this in a separate terminal instance):

```bash
npm run dev
```

Visit `http://localhost:3000` to access the frontend of the app.

### REST API - Custom Website

You can also access the REST API using a custom website. To do this, you need to run the Flask server in the `backend` directory:

```bash
python api.py
```

Then, you can access the API using the following endpoints:

- `http://localhost:8000/api/identify` - This endpoint is used to recognise music. It accepts a POST request with a file upload. The file should be in WAV format.

## Notes

If you choose to build your own database, you can do the following to speed up downloading the songs necessary for the database:

1. Create a list of artist albums from Spotify in the following format:
   `The Weeknd - Starboy - 2ODvWsOgouMbaA5xf0RkJe`/`Artist Name - Album Name - Spotify ID`
2. Open `downloader.py`, and edit lines 7 and 8 to include the path to your database and the list of albums you want to download (step 1).
3. Install `spotdl` at [SpotDL GitHub](https://github.com/spotDL/spotify-downloader), and ensure you change the config file to save the file as format WAV.
4. You can then run the downloader script using the following command: `python downloader.py`.
5. Once the songs are downloaded, you can run the fingerprinting command to build your database.

If you then want to use the frontend, run the `metadata.py` script to create the metadata file. Once the file is created, go to the frontend directory, and run the following commands:

```bash
cd scripts
node generate-songs-data.js
```

This will update the song data in the frontend, allowing you to view which songs are identifiable.

Update the `config.py` file to include all the new paths.
