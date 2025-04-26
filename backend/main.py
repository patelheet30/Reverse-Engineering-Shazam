from __future__ import annotations

import argparse
import glob
import logging
import multiprocessing
import os
import time
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import List, Optional, Tuple

import config
from src.audio.processor import AudioProcessor
from src.database.manager import DatabaseManager, Match
from src.fingerprinting.generator import Fingerprint, FingerprintGenerator
from src.fingerprinting.peaks import PeakFinder


def setup_logging(log_file: Optional[str] = None) -> None:
    """Set up logging configuration.

    Args:
        log_file: Optional path to save logs to a file
    """
    handlers = [logging.StreamHandler()]

    if log_file:
        log_dir = Path("logs")
        log_dir.mkdir(exist_ok=True)
        file_handler = logging.FileHandler(log_file)
        handlers.append(file_handler)  # type: ignore

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=handlers,
    )


def get_db_path(base_path: Optional[str], db_index: int) -> str:
    """Generate a database path with index and ensure .db extension.

    Args:
        base_path: Optional custom base path for the database
        db_index: Index number to append to the database filename

    Returns:
        Full path to the database file with index
    """
    if base_path is None:
        db_dir = config.DATABASE_DIR
        db_name = config.DB_FILENAME
        name_parts = os.path.splitext(db_name)
        extension = name_parts[1] if name_parts[1] else ".db"
        return str(db_dir / f"{name_parts[0]}_{db_index}{extension}")
    else:
        name_parts = os.path.splitext(base_path)
        extension = name_parts[1] if name_parts[1] else ".db"
        return f"{name_parts[0]}_{db_index}{extension}"


def get_all_db_paths(base_path: Optional[str]) -> List[str]:
    """Get all database paths matching the pattern.

    Args:
        base_path: Optional custom base path for the database

    Returns:
        List of paths to all matching database files
    """
    if base_path is None:
        db_dir = config.DATABASE_DIR
        db_name = config.DB_FILENAME
        name_parts = os.path.splitext(db_name)
        pattern = str(db_dir / f"{name_parts[0]}_*{name_parts[1]}")
    else:
        name_parts = os.path.splitext(base_path)
        pattern = f"{name_parts[0]}_*{name_parts[1]}"

    return sorted(glob.glob(pattern))


def create_audio_processor() -> AudioProcessor:
    """Create an AudioProcessor with settings from config."""
    return AudioProcessor(sample_rate=config.SAMPLE_RATE, mono=config.MONO)


def create_peak_finder() -> PeakFinder:
    """Create a PeakFinder with settings from config."""
    return PeakFinder(
        n_fft=config.N_FFT,
        hop_length=config.HOP_LENGTH,
        window=config.WINDOW,
        neighborhood_size=config.NEIGHBOURHOOD_SIZE,
        threshold_abs=config.THRESHOLD_ABS,
        min_peak_distance=config.MIN_PEAK_DISTANCE,
        max_peaks_total=config.MAX_PEAKS_TOTAL,
        max_peaks_per_frame=config.MAX_PEAKS_PER_FRAME,
        min_frequency=config.MIN_FREQ,
        max_frequency=config.MAX_FREQ,
        freq_bins=config.FREQ_BINS,
    )


def create_fingerprint_generator(
    hash_method: Optional[str] = None,
) -> FingerprintGenerator:
    """Create a FingerprintGenerator with settings from config.

    Args:
        hash_method: Hash method to use, defaults to config value if None
    """
    if hash_method is None:
        hash_method = config.HASH_METHOD

    return FingerprintGenerator(
        fan_value=config.FAN_VALUE,
        min_time_delta=config.MIN_TIME_DELTA,
        max_time_delta=config.MAX_TIME_DELTA,
        hash_bits=config.HASH_BITS,
        freq_bin_count=config.FREQ_BIN_COUNT,
        sample_rate=config.SAMPLE_RATE,
        hop_length=config.HOP_LENGTH,
        hash_method=hash_method,
    )


def find_suitable_database(db_path: Optional[str]) -> str:
    """Find the most suitable database for adding a new song.

    Looks for the database with the least songs or creates a new one if needed.

    Args:
        db_path: Optional custom base path for the database

    Returns:
        Path to the database to use
    """
    logger = logging.getLogger(__name__)

    # Get all database files
    db_paths = get_all_db_paths(db_path)

    if not db_paths:
        db_to_use = get_db_path(db_path, 1)
        logger.info(f"Creating new database: {db_to_use}")
        return db_to_use

    # Check each database's song count
    db_to_use = None
    min_songs = float("inf")

    for db in db_paths:
        try:
            db_manager = DatabaseManager(database_path=db)
            stats = db_manager.get_database_stats()
            if hasattr(db_manager, "close"):
                db_manager.close()

            song_count = stats.get("songs", 0)
            if song_count < min_songs and song_count < config.MAX_SONGS_PER_DATABASE:
                min_songs = song_count
                db_to_use = db
        except Exception as e:
            logger.error(f"Error accessing database {db}: {e}")

    # If all databases are full, create a new one
    if db_to_use is None or min_songs >= config.MAX_SONGS_PER_DATABASE:
        next_index = len(db_paths) + 1
        db_to_use = get_db_path(db_path, next_index)
        logger.info(f"Creating new database: {db_to_use}")

    logger.info(f"Using database: {db_to_use}")
    return db_to_use


def process_audio_chunk(
    audio: List[float],
    chunk_index: int,
    chunk_size: int,
    total_chunks: int,
    peak_finder: PeakFinder,
    fingerprint_gen: FingerprintGenerator,
) -> List[Fingerprint]:
    """Process a chunk of audio data to generate fingerprints.

    Args:
        audio: Complete audio data
        chunk_index: Index of the current chunk
        chunk_size: Size of each chunk in seconds
        total_chunks: Total number of chunks
        peak_finder: PeakFinder instance
        fingerprint_gen: FingerprintGenerator instance

    Returns:
        List of fingerprints generated from the chunk
    """
    logger = logging.getLogger(__name__)

    start = chunk_index * chunk_size * config.SAMPLE_RATE
    end = min(len(audio), (chunk_index + 1) * chunk_size * config.SAMPLE_RATE)

    if start >= len(audio):
        return []

    chunk = audio[start:end]
    chunk_duration = len(chunk) / config.SAMPLE_RATE

    logger.info(
        f"Processing chunk {chunk_index + 1}/{total_chunks} ({chunk_duration:.2f}s)"
    )

    chunk_start_time = time.time()
    _, freqs, times, peaks = peak_finder.process_audio(chunk)
    logger.info(
        f"Peak finding completed in {time.time() - chunk_start_time:.2f} seconds"
    )
    logger.info(f"Found {len(peaks)} peaks")

    fp_start_time = time.time()
    chunk_offset = chunk_index * chunk_size
    adjusted_times = times + chunk_offset

    fingerprints = fingerprint_gen.generate_fingerprint(peaks, freqs, adjusted_times)
    logger.info(
        f"Fingerprint generation completed in {time.time() - fp_start_time:.2f} seconds"
    )
    logger.info(f"Generated {len(fingerprints)} fingerprints")

    return fingerprints


def fingerprint_song(
    file_path: str,
    song_name: Optional[str] = None,
    db_path: Optional[str] = None,
    chunk_size: int = 30,
    hash_method: Optional[str] = None,
) -> int:
    """Fingerprint a song and add it to the database.

    Args:
        file_path: Path to the audio file
        song_name: Name of the song (defaults to filename if None)
        db_path: Optional custom base path for the database
        chunk_size: Size of audio chunks to process in seconds
        hash_method: Hash method to use, defaults to config value if None

    Returns:
        Song ID of the added song, or -1 if an error occurred
    """
    logger = logging.getLogger(__name__)
    file_path_obj = Path(file_path)

    if not file_path_obj.exists():
        logger.error(f"File not found: {file_path}")
        return -1

    if song_name is None:
        song_name = file_path_obj.stem

    # Create processors
    audio_proc = create_audio_processor()
    peak_finder = create_peak_finder()
    fingerprint_gen = create_fingerprint_generator(hash_method)

    # Find suitable database
    db_to_use = find_suitable_database(db_path)
    db_manager = DatabaseManager(database_path=db_to_use)

    # Load and process audio
    logger.info(f"Processing song: {song_name} from {file_path}")
    start_time = time.time()
    audio = audio_proc.load_audio(file_path_obj)
    logger.info(f"Audio loaded in {time.time() - start_time:.2f} seconds")

    duration = len(audio) / config.SAMPLE_RATE
    logger.info(f"Audio duration: {duration:.2f} seconds")

    # Process audio in chunks
    all_fingerprints = []
    num_chunks = int(duration / chunk_size) + 1

    for i in range(num_chunks):
        chunk_fingerprints = process_audio_chunk(
            audio,  # type: ignore
            i,
            chunk_size,
            num_chunks,
            peak_finder,
            fingerprint_gen,
        )
        all_fingerprints.extend(chunk_fingerprints)

    # Add to database
    logger.info(f"Adding {len(all_fingerprints)} fingerprints to database")
    song_id = db_manager.add_song(song_name, str(file_path_obj), all_fingerprints)
    logger.info(f"Song added to database with ID: {song_id}")

    if hasattr(db_manager, "close"):
        db_manager.close()

    return song_id


def process_song_worker(
    file_path: Path, chunk_size: int, hash_method: Optional[str] = None
) -> Optional[Tuple[str, str, List[Fingerprint]]]:
    """Worker function for parallel processing of songs.

    Args:
        file_path: Path to the audio file
        chunk_size: Size of audio chunks to process in seconds
        hash_method: Hash method to use

    Returns:
        Tuple of (file_path, song_name, fingerprints) or None if an error occurred
    """
    logger = logging.getLogger(__name__)
    try:
        song_name = file_path.stem
        logger.info(f"Processing file: {file_path.name}")

        # Create processors
        audio_proc = create_audio_processor()
        peak_finder = create_peak_finder()
        fingerprint_gen = create_fingerprint_generator(hash_method)

        # Load and process audio
        start_time = time.time()
        audio = audio_proc.load_audio(file_path)
        logger.info(f"Audio loaded in {time.time() - start_time:.2f} seconds")

        duration = len(audio) / config.SAMPLE_RATE
        logger.info(f"Audio duration: {duration:.2f} seconds")

        # Process audio in chunks
        all_fingerprints = []
        num_chunks = int(duration / chunk_size) + 1

        for j in range(num_chunks):
            chunk_fingerprints = process_audio_chunk(
                audio,  # type: ignore
                j,
                chunk_size,
                num_chunks,
                peak_finder,
                fingerprint_gen,
            )
            all_fingerprints.extend(chunk_fingerprints)

        logger.info(
            f"Finished processing '{song_name}' with {len(all_fingerprints)} fingerprints"
        )
        return (str(file_path), song_name, all_fingerprints)

    except Exception as e:
        logger.error(f"Error processing {file_path.name}: {e}")
        return None


def search_database_worker(
    args: Tuple[str, List[Fingerprint], float],
) -> Tuple[str, List[Match], float]:
    """Worker function for parallel database searching.

    Args:
        args: Tuple of (db_path, fingerprints, threshold)

    Returns:
        Tuple of (db_path, matches, search_time)
    """
    db_path, fingerprints, threshold = args
    logger = logging.getLogger(__name__)

    try:
        db_manager = DatabaseManager(database_path=db_path)

        match_start_time = time.time()
        matches = db_manager.find_matches(fingerprints, threshold=threshold)
        search_time = time.time() - match_start_time

        if hasattr(db_manager, "close"):
            db_manager.close()

        return db_path, matches, search_time
    except Exception as e:
        logger.error(f"Error searching database {db_path}: {e}")
        return db_path, [], 0


def identify_song(
    file_path: str,
    db_path: Optional[str] = None,
    duration: Optional[float] = 10.0,
    threshold: Optional[float] = None,
    max_workers: Optional[int] = None,
    hash_method: Optional[str] = None,
) -> Optional[List[Match]]:
    """Identify a song from an audio sample.

    Args:
        file_path: Path to the audio file
        db_path: Optional custom base path for the database
        duration: Duration of audio to analyze in seconds (None for full file)
        threshold: Match confidence threshold (None for default)
        max_workers: Number of parallel workers (None for auto)
        hash_method: Hash method to use

    Returns:
        List of matching songs or None if no matches found
    """
    logger = logging.getLogger(__name__)
    file_path_obj = Path(file_path)

    if not file_path_obj.exists():
        logger.error(f"File not found: {file_path}")
        return None

    # Set default parameters
    if max_workers is None:
        max_workers = min(multiprocessing.cpu_count(), 4)

    if threshold is None:
        threshold = config.MATCH_THRESHOLD

    # Create processors
    audio_proc = create_audio_processor()
    peak_finder = create_peak_finder()
    fingerprint_gen = create_fingerprint_generator(hash_method)

    # Get list of all database files
    db_paths = get_all_db_paths(db_path)
    if not db_paths:
        logger.error("No database files found")
        return None

    logger.info(f"Found {len(db_paths)} database files to search")

    # Load and process query audio
    logger.info(f"Loading query audio: {file_path}")
    start_time = time.time()
    audio = audio_proc.load_audio(file_path_obj)
    logger.info(f"Audio loaded in {time.time() - start_time:.2f} seconds")

    # Limit duration if needed
    if duration is not None and duration > 0:
        samples = int(duration * config.SAMPLE_RATE)
        if samples < len(audio):
            logger.info(f"Using first {duration:.2f} seconds of audio")
            audio = audio[:samples]

    # Extract peaks and generate fingerprints
    logger.info("Extracting peaks")
    peak_start_time = time.time()
    _, freqs, times, peaks = peak_finder.process_audio(audio)
    logger.info(
        f"Peak finding completed in {time.time() - peak_start_time:.2f} seconds"
    )
    logger.info(f"Found {len(peaks)} peaks")

    logger.info("Generating fingerprints")
    fp_start_time = time.time()
    fingerprints = fingerprint_gen.generate_fingerprint(peaks, freqs, times)
    logger.info(
        f"Fingerprint generation completed in {time.time() - fp_start_time:.2f} seconds"
    )
    logger.info(f"Generated {len(fingerprints)} fingerprints")

    # Search across all databases in parallel
    logger.info(
        f"Searching across {len(db_paths)} databases using {max_workers} workers"
    )
    search_start_time = time.time()

    # Prepare arguments for parallel processing
    search_args = [(db, fingerprints, threshold) for db in db_paths]

    with multiprocessing.Pool(processes=max_workers) as pool:
        results = pool.map(search_database_worker, search_args)

    logger.info(
        f"All database searches completed in {time.time() - search_start_time:.2f} seconds"
    )

    # Process results
    all_matches = []
    for db_path, matches, search_time in results:
        if matches:
            db_name = os.path.basename(db_path)
            logger.info(
                f"Found {len(matches)} potential matches in {db_name} (search time: {search_time:.2f}s)"
            )
            all_matches.extend(matches)

    # Early termination if we have a very strong match
    fast_match_threshold = 0.90
    if all_matches:
        best_match = max(all_matches, key=lambda m: m.confidence)
        if best_match.confidence >= fast_match_threshold:
            logger.info(
                f"Found high-confidence match ({best_match.confidence:.2%}), terminating search early"
            )
            return [best_match]

    # Sort and return top matches
    if all_matches:
        all_matches.sort(key=lambda m: m.confidence, reverse=True)
        top_matches = all_matches[:10]

        logger.info(f"Found {len(all_matches)} matches across all databases")
        logger.info("Top matches:")

        print("Top Match is:")
        match = top_matches[0]
        print(
            f"Song Name: {match.song_name}, Confidence: {match.confidence:.2%}, "
            f"Offset: {match.offset:.2f}s, Match Count: {match.match_count}"
        )

        return top_matches
    else:
        logger.info("No matches found in any database")
        return None


def fingerprint_directory(
    directory: str,
    db_path: Optional[str] = None,
    extensions: Optional[List[str]] = None,
    chunk_size: int = 30,
    max_workers: Optional[int] = None,
    songs_per_db: int = config.MAX_SONGS_PER_DATABASE,
    hash_method: Optional[str] = None,
) -> None:
    """Fingerprint all audio files in a directory.

    Args:
        directory: Path to the directory containing audio files
        db_path: Optional custom base path for the database
        extensions: List of file extensions to process (None for defaults)
        chunk_size: Size of audio chunks to process in seconds
        max_workers: Number of parallel workers (None for auto)
        songs_per_db: Maximum number of songs per database file
        hash_method: Hash method to use
    """
    logger = logging.getLogger(__name__)
    directory_obj = Path(directory)

    if not directory_obj.exists() or not directory_obj.is_dir():
        logger.error(f"Directory not found: {directory}")
        return

    if extensions is None:
        extensions = [".mp3", ".wav", ".flac", ".m4a", ".ogg"]

    if max_workers is None:
        max_workers = min(multiprocessing.cpu_count(), 4)

    # Find all audio files
    audio_files = []
    for ext in extensions:
        # Recursively find files in all subdirectories
        audio_files.extend(directory_obj.glob(f"**/*{ext}"))

    if not audio_files:
        logger.error(f"No audio files found in {directory}")
        return

    logger.info(f"Found {len(audio_files)} audio files")
    logger.info(f"Processing with {max_workers} parallel workers")

    # Process files in parallel
    start_time = time.time()
    all_results = []

    with multiprocessing.Pool(processes=max_workers) as pool:
        process_func = partial(
            process_song_worker, chunk_size=chunk_size, hash_method=hash_method
        )

        for i, result in enumerate(
            pool.imap_unordered(process_func, sorted(audio_files))
        ):
            if result:
                all_results.append(result)

            if (i + 1) % 10 == 0 or (i + 1) == len(audio_files):
                logger.info(
                    f"Processed {i + 1}/{len(audio_files)} files "
                    f"({(i + 1) / len(audio_files) * 100:.1f}%)"
                )

    processing_time = time.time() - start_time
    logger.info(f"Parallel processing completed in {processing_time:.2f} seconds")
    logger.info(f"Successfully processed {len(all_results)}/{len(audio_files)} files")

    # Calculate how many databases we need
    total_songs = len(all_results)
    num_databases = (total_songs + songs_per_db - 1) // songs_per_db
    logger.info(
        f"Distributing {total_songs} songs across {num_databases} databases "
        f"({songs_per_db} songs per database)"
    )

    # Group songs into database batches
    db_batches = {}
    for i, result in enumerate(all_results):
        db_index = (i // songs_per_db) + 1
        if db_index not in db_batches:
            db_batches[db_index] = []
        db_batches[db_index].append(result)

    # Process each database
    for db_index, songs in db_batches.items():
        actual_db_path = get_db_path(db_path, db_index)
        logger.info(f"Creating database {db_index}/{num_databases}: {actual_db_path}")

        db_manager = DatabaseManager(database_path=actual_db_path)
        db_start_time = time.time()

        for file_path, song_name, fingerprints in songs:
            try:
                logger.info(
                    f"Adding '{song_name}' with {len(fingerprints)} fingerprints to database {db_index}"
                )
                db_manager.add_song(song_name, file_path, fingerprints)
            except Exception as e:
                logger.error(f"Error adding {song_name} to database {db_index}: {e}")

        db_time = time.time() - db_start_time
        logger.info(
            f"Database {db_index} completed in {db_time:.2f} seconds with {len(songs)} songs"
        )

        if hasattr(db_manager, "close"):
            db_manager.close()

    logger.info(f"Total processing time: {time.time() - start_time:.2f} seconds")


def show_db_stats(db_path: Optional[str] = None) -> None:
    """Show statistics for all databases.

    Args:
        db_path: Optional custom base path for the database
    """
    logger = logging.getLogger(__name__)

    # Get all database files
    db_paths = get_all_db_paths(db_path)

    if not db_paths:
        logger.error("No database files found")
        return

    logger.info(f"Found {len(db_paths)} database files")

    total_songs = 0
    total_fingerprints = 0

    for i, db in enumerate(db_paths):
        logger.info(f"Database {i + 1}: {db}")
        db_manager = DatabaseManager(database_path=db)

        stats = db_manager.get_database_stats()
        logger.info(f"  Statistics: {stats}")

        total_songs += stats.get("num_songs", 0)
        total_fingerprints += stats.get("num_fingerprints", 0)

        if hasattr(db_manager, "close"):
            db_manager.close()

    logger.info(
        f"Total across all databases: {total_songs} songs, {total_fingerprints} fingerprints"
    )


def create_argument_parser() -> argparse.ArgumentParser:
    """Create the command-line argument parser.

    Returns:
        Configured argparse.ArgumentParser instance
    """
    parser = argparse.ArgumentParser(description="Audio Fingerprinting System")
    subparsers = parser.add_subparsers(dest="command")

    # Fingerprint command
    fp_parser = subparsers.add_parser("fingerprint", help="Fingerprint a song")
    fp_parser.add_argument("path", help="Path to audio file or directory")
    fp_parser.add_argument("--name", help="Song name (for single files)")
    fp_parser.add_argument("--db", help="Path to database file")
    fp_parser.add_argument("--dir", action="store_true", help="Process directory")
    fp_parser.add_argument(
        "--chunk-size", type=int, default=30, help="Chunk size in seconds"
    )
    fp_parser.add_argument("--log", "-l", action="store_true", help="Save logs to file")
    fp_parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Number of parallel workers for directory processing",
    )
    fp_parser.add_argument(
        "--songs-per-db",
        type=int,
        default=config.MAX_SONGS_PER_DATABASE,
        help="Maximum number of songs per database file",
    )
    fp_parser.add_argument(
        "--hash-method",
        choices=["v1", "v2", "both"],
        default=None,
        help="Hash method to use (v1, v2, or both)",
    )

    # Identify command
    id_parser = subparsers.add_parser("identify", help="Identify a song")
    id_parser.add_argument("path", help="Path to audio file")
    id_parser.add_argument("--db", help="Base path to database files")
    id_parser.add_argument(
        "--duration", type=float, default=10.0, help="Duration to analyze in seconds"
    )
    id_parser.add_argument("--threshold", type=float, help="Matching threshold")
    id_parser.add_argument("--log", "-l", action="store_true", help="Save logs to file")
    id_parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help="Number of parallel workers for database searching",
    )
    id_parser.add_argument(
        "--hash-method",
        choices=["v1", "v2", "both"],
        default=None,
        help="Hash method to use (v1, v2, or both)",
    )

    # Stats command
    stats_parser = subparsers.add_parser("stats", help="Show database statistics")
    stats_parser.add_argument("--db", help="Base path to database files")
    stats_parser.add_argument(
        "--log", "-l", action="store_true", help="Save logs to file"
    )

    return parser


def main() -> None:
    """Main entry point for the command-line interface."""
    parser = create_argument_parser()
    args = parser.parse_args()

    # Set up logging
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = None

    if args.command and getattr(args, "log", False):
        log_file = f"logs/{args.command}_{timestamp}.log"

    setup_logging(log_file)
    _ = logging.getLogger(__name__)

    # Execute command
    if args.command == "fingerprint":
        hash_method = getattr(args, "hash_method", None)
        if args.dir:
            fingerprint_directory(
                args.path,
                args.db,
                None,
                args.chunk_size,
                args.workers,
                getattr(args, "songs_per_db", config.MAX_SONGS_PER_DATABASE),
                hash_method=hash_method,
            )
        else:
            fingerprint_song(
                args.path, args.name, args.db, args.chunk_size, hash_method=hash_method
            )
    elif args.command == "identify":
        identify_song(
            args.path,
            args.db,
            args.duration,
            args.threshold,
            getattr(args, "workers", None),
            hash_method=getattr(args, "hash_method", None),
        )
    elif args.command == "stats":
        show_db_stats(args.db)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
