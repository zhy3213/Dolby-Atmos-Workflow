#!/bin/bash

# Check if input file is provided
if [ $# -lt 1 ]; then
    echo "Usage: $0 <input_video_file> [output_wav_file]"
    echo "  input_video_file: Path to the input video file (required)"
    echo "  output_wav_file: Path to the output WAV file (optional)"
    exit 1
fi

# Get input file path
input_file="$1"

# Check if input file exists
if [ ! -f "$input_file" ]; then
    echo "Error: Input file '$input_file' does not exist"
    exit 1
fi

# Convert input path to absolute path
input_file=$(realpath "$input_file")

# Set output file path
if [ $# -ge 2 ]; then
    output_file="$2"
else
    # Use the same directory as input file
    output_file="$(dirname "$input_file")/$(basename "${input_file%.*}").wav"
fi

# Convert output path to absolute path
output_file=$(realpath "$output_file")

# Convert paths to wine format (z: prefix)
wine_input="z:$input_file"
wine_output="z:$output_file"

# Construct and execute the command
cmd="wine \"/Users/zhanghaoyang/.wine/drive_c/Program Files/Dolby/Dolby Reference Player/drp.exe\" \
    \"$wine_input\" \
    --audio-out-file \"$wine_output\" \
    --ac4dec-drc-enabled false \
    --ac4dec-front-speaker-angle 30 \
    --ac4dec-out-cplx-level 5.1.2 \
    --out-ch-config 7.1 \
    --truehddec-presentation 8"

echo "Executing command: $cmd"
eval "$cmd" 