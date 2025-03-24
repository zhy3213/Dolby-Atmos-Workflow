import argparse
import pathlib
import dataclasses
import subprocess
import os
import tempfile
import json
import re

CHANNELS = {
    '2.0': {
        'id': 0,
        'names': ['L', 'R'],
    },
    '3.1': {
        'id': 3,
        'names': ['L', 'R', 'C', 'LFE'],
    },
    '5.1': {
        'id': 7,
        'names': ['L', 'R', 'C', 'LFE', 'Ls', 'Rs'],
    },
    '7.1': {
        'id': 11,
        'names': ['L', 'R', 'C', 'LFE', 'Ls', 'Rs', 'Lrs', 'Rrs'],
    },
    '9.1': {
        'id': 12,
        'names': ['L', 'R', 'C', 'LFE', 'Ls', 'Rs', 'Lrs', 'Rrs', 'Lw', 'Rw'],
    },
    '5.1.2': {
        'id': 13,
        'names': ['L', 'R', 'C', 'LFE', 'Ls', 'Rs', 'Ltm', 'Rtm'],
    },
    '5.1.4': {
        'id': 14,
        'names': ['L', 'R', 'C', 'LFE', 'Ls', 'Rs', 'Ltf', 'Rtf', 'Ltr', 'Rtr'],
    },
    '7.1.2': {
        'id': 15,
        'names': ['L', 'R', 'C', 'LFE', 'Ls', 'Rs', 'Lrs', 'Rrs', 'Ltm', 'Rtm'],
    },
    '7.1.4': {
        'id': 16,
        'names': ['L', 'R', 'C', 'LFE', 'Ls', 'Rs', 'Lrs', 'Rrs', 'Ltf', 'Rtf', 'Ltr', 'Rtr'],
    },
    '7.1.6': {
        'id': 17,
        'names': ['L', 'R', 'C', 'LFE', 'Ls', 'Rs', 'Lrs', 'Rrs', 'Ltf', 'Rtf', 'Ltm', 'Rtm', 'Ltr', 'Rtr'],
    },
    '9.1.2': {
        'id': 18,
        'names': ['L', 'R', 'C', 'LFE', 'Ls', 'Rs', 'Lrs', 'Rrs', 'Lw', 'Rw', 'Ltm', 'Rtm'],
    },
    '9.1.4': {
        'id': 19,
        'names': ['L', 'R', 'C', 'LFE', 'Ls', 'Rs', 'Lrs', 'Rrs', 'Lw', 'Rw', 'Ltf', 'Rtf', 'Ltr', 'Rtr'],
    },
    '9.1.6': {
        'id': 20,
        'names': ['L', 'R', 'C', 'LFE', 'Ls', 'Rs', 'Lrs', 'Rrs', 'Lw', 'Rw', 'Ltf', 'Rtf', 'Ltm', 'Rtm', 'Ltr', 'Rtr'],
    },
}


@dataclasses.dataclass
class Config:
    gst_launch: pathlib.Path
    channels: str
    no_numbers: bool
    single: bool
    multi_channel: bool
    keep_temp: bool


class AtmosDecode:
    def __init__(self, config: Config):
        # No need to check Windows path in Wine environment
        self.config: Config = config
        self.temp_files = []

    def decode(self, input_file: pathlib.Path, out_file: pathlib.Path | None = None):
        if not input_file.is_file():
            raise RuntimeError(f'Input file {input_file.absolute()} is not a file')

        # Check if the file is a container format that might contain Atmos
        container_file = False
        container_exts = ['.mp4', '.mkv', '.mov', '.m4v', '.ts', '.mts']
        if input_file.suffix.lower() in container_exts:
            container_file = True
            # Extract audio track
            audio_file = self._extract_atmos_track(input_file)
            if not audio_file:
                raise RuntimeError(f'No Dolby Atmos (E-AC3 or TrueHD) track found in {input_file.absolute()}')
            
            # Use the extracted audio file for processing
            actual_input_file = audio_file
        else:
            actual_input_file = input_file

        try:
            with actual_input_file.open('rb') as f:
                first_bytes = f.read(10)

                eac3_sync_word = 0x0B77.to_bytes(2, 'big')
                truehd_sync_word = 0xF8726FBA.to_bytes(4, 'big')

                if first_bytes.startswith(eac3_sync_word):
                    command_fun = self.prepare_eac3_decode_command
                elif truehd_sync_word in first_bytes:
                    command_fun = self.prepare_truehd_decode_command
                else:
                    raise RuntimeError(f'Source file must be in E-AC3 or TrueHD format')

            channel_layout = CHANNELS[self.config.channels]
            out_channel_config_id, channel_names = channel_layout['id'], channel_layout['names']

            if self.config.multi_channel:
                # Generate a single multi-channel file
                out_file_path = out_file if out_file is not None else input_file.with_suffix('.wav')
                command = command_fun(actual_input_file, out_file_path, -1, out_channel_config_id, multi_channel=True)
                print(f'Decoding to multi-channel file "{out_file_path}"')
                subprocess.run(command)
            else:
                # Generate multiple mono files
                processes = []
                for channel_id, channel_name in enumerate(channel_names):
                    if self.config.no_numbers:
                        suffix = f'.{channel_name}.wav'
                    else:
                        suffix = f'.{str(channel_id + 1).zfill(2)}_{channel_name}.wav'

                    out_file_path = out_file.with_suffix(suffix) if out_file is not None else input_file.with_suffix(suffix)

                    command = command_fun(actual_input_file, out_file_path, channel_id, out_channel_config_id)

                    if self.config.single:
                        print(f'Decoding "{out_file_path}"')
                        subprocess.run(command)
                    else:
                        processes.append(subprocess.Popen(command))

                if not self.config.single:
                    for process in processes:
                        process.wait()
        finally:
            # Clean up temporary files
            if not self.config.keep_temp:
                for temp_file in self.temp_files:
                    try:
                        if temp_file.exists():
                            temp_file.unlink()
                    except Exception as e:
                        print(f"Warning: Failed to delete temporary file {temp_file}: {e}")

    def _extract_atmos_track(self, input_file: pathlib.Path) -> pathlib.Path | None:
        """Extract Dolby Atmos audio track from container file"""
        print(f"Analyzing {input_file} for Dolby Atmos audio tracks...")
        
        # Get stream info using ffprobe
        ffprobe_cmd = [
            'ffprobe', 
            '-v', 'quiet', 
            '-print_format', 'json', 
            '-show_streams', 
            '-select_streams', 'a', 
            str(input_file.absolute())
        ]
        
        try:
            process = subprocess.run(ffprobe_cmd, capture_output=True, text=True, check=True)
            stream_info = json.loads(process.stdout)
        except subprocess.CalledProcessError as e:
            print(f"Error analyzing file: {e}")
            return None
        except json.JSONDecodeError:
            print("Error parsing ffprobe output")
            return None
        
        # Find the Dolby Atmos track
        atmos_stream_index = None
        is_eac3 = False
        is_truehd = False
        
        for stream in stream_info.get('streams', []):
            codec_name = stream.get('codec_name', '').lower()
            codec_long_name = stream.get('codec_long_name', '').lower()
            tags = stream.get('tags', {})
            
            # Look for Atmos indicators
            is_atmos = False
            if 'atmos' in codec_long_name or 'atmos' in tags.get('title', '').lower() or 'atmos' in tags.get('handler_name', '').lower():
                is_atmos = True
            
            if codec_name == 'eac3' or codec_name == 'ac3':
                if is_atmos or 'joc' in codec_long_name:
                    atmos_stream_index = stream['index']
                    is_eac3 = True
                    break
            elif codec_name == 'truehd' or 'mlp' in codec_name:
                if is_atmos:
                    atmos_stream_index = stream['index']
                    is_truehd = True
                    break
        
        if atmos_stream_index is None:
            # Check again without Atmos requirement, just look for any supported format
            for stream in stream_info.get('streams', []):
                codec_name = stream.get('codec_name', '').lower()
                if codec_name == 'eac3':
                    atmos_stream_index = stream['index']
                    is_eac3 = True
                    break
                elif codec_name == 'truehd' or 'mlp' in codec_name:
                    atmos_stream_index = stream['index']
                    is_truehd = True
                    break
        
        if atmos_stream_index is None:
            print("No Dolby Atmos or compatible audio track found")
            return None
        
        # Create temp file for extracted audio
        suffix = '.ec3' if is_eac3 else '.thd'
        temp_dir = pathlib.Path(tempfile.gettempdir())
        temp_file = temp_dir / f"extracted_atmos_{input_file.stem}{suffix}"
        self.temp_files.append(temp_file)
        
        # Extract the audio track
        print(f"Extracting audio track {atmos_stream_index} to {temp_file}...")
        
        ffmpeg_cmd = [
            'ffmpeg', 
            '-y',
            '-i', str(input_file.absolute()),
            '-map', f'0:{atmos_stream_index}',
            '-c:a', 'copy',
            str(temp_file)
        ]
        
        try:
            subprocess.run(ffmpeg_cmd, capture_output=True, check=True)
            print(f"Successfully extracted audio track to {temp_file}")
            return temp_file
        except subprocess.CalledProcessError as e:
            print(f"Error extracting audio track: {e}")
            return None

    def prepare_eac3_decode_command(
            self,
            input_file: pathlib.Path,
            out_file: pathlib.Path,
            channel_id: int,
            out_channel_config_id: int,
            multi_channel: bool = False
    ) -> list[str]:
        if multi_channel:
            return [
                'wine',
                r'C:\Program Files\Dolby\Dolby Reference Player\gst-launch-1.0.exe',
                '--gst-plugin-path', r'C:\Program Files\Dolby\Dolby Reference Player\gst-plugins',
                'filesrc', f'location={self._prepare_file_path(input_file)}', '!',
                'dlbac3parse', '!',
                'dlbaudiodecbin', f'out-ch-config={out_channel_config_id}', '!',
                'wavenc', '!',
                'filesink', f'location={self._prepare_file_path(out_file)}'
            ]
        else:
            return [
                'wine',
                r'C:\Program Files\Dolby\Dolby Reference Player\gst-launch-1.0.exe',
                '--gst-plugin-path', r'C:\Program Files\Dolby\Dolby Reference Player\gst-plugins',
                'filesrc', f'location={self._prepare_file_path(input_file)}', '!',
                'dlbac3parse', '!',
                'dlbaudiodecbin', f'out-ch-config={out_channel_config_id}', '!',
                'deinterleave', 'name=d', f'd.src_{channel_id}', '!',
                'wavenc', '!',
                'filesink', f'location={self._prepare_file_path(out_file)}'
            ]

    def prepare_truehd_decode_command(
            self,
            input_file: pathlib.Path,
            out_file: pathlib.Path,
            channel_id: int,
            out_channel_config_id: int,
            multi_channel: bool = False
    ) -> list[str]:
        if multi_channel:
            return [
                'wine',
                r'C:\Program Files\Dolby\Dolby Reference Player\gst-launch-1.0.exe',
                '--gst-plugin-path', r'C:\Program Files\Dolby\Dolby Reference Player\gst-plugins',
                'filesrc', f'location={self._prepare_file_path(input_file)}', '!',
                'dlbtruehdparse', 'align-major-sync=false', '!',
                'dlbaudiodecbin', 'truehddec-presentation=16', f'out-ch-config={out_channel_config_id}', '!',
                'wavenc', '!',
                'filesink', f'location={self._prepare_file_path(out_file)}'
            ]
        else:
            return [
                'wine',
                r'C:\Program Files\Dolby\Dolby Reference Player\gst-launch-1.0.exe',
                '--gst-plugin-path', r'C:\Program Files\Dolby\Dolby Reference Player\gst-plugins',
                'filesrc', f'location={self._prepare_file_path(input_file)}', '!',
                'dlbtruehdparse', 'align-major-sync=false', '!',
                'dlbaudiodecbin', 'truehddec-presentation=16', f'out-ch-config={out_channel_config_id}', '!',
                'deinterleave', 'name=d', f'd.src_{channel_id}', '!',
                'wavenc', '!',
                'filesink', f'location={self._prepare_file_path(out_file)}'
            ]

    def _prepare_file_path(self, source: pathlib.Path) -> str:
        abs_path = str(source.absolute())
        # Convert Unix path to Wine path format
        wine_path = f"z:{abs_path.replace('/', '\\')}"
        return wine_path.replace('\\', '\\\\')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '-i', '--input',
        help='Path to source file (video container or raw Dolby audio)',
        type=pathlib.Path,
        required=True,
    )
    parser.add_argument(
        '-o', '--output',
        help='Path to output base file',
        type=pathlib.Path,
    )
    parser.add_argument(
        '-c', '--channels',
        help='Output channel configuration',
        type=str,
        default='9.1.6',
        choices=CHANNELS.keys(),
    )
    parser.add_argument(
        '-nn', '--no_numbers',
        help='Do not use numbers in output channel names',
        action='store_true',
    )
    parser.add_argument(
        '-s', '--single',
        help='Decode one channel at a time',
        action='store_true',
    )
    parser.add_argument(
        '-m', '--multi_channel',
        help='Generate a single multi-channel WAV file instead of separate mono files',
        action='store_true',
    )
    parser.add_argument(
        '-k', '--keep_temp',
        help='Keep temporary extracted audio files',
        action='store_true',
    )
    args = parser.parse_args()
    args_dataclass = Config(
        gst_launch=pathlib.Path(r'C:\Program Files\Dolby\Dolby Reference Player\gst-launch-1.0.exe'),
        channels=args.channels,
        no_numbers=args.no_numbers,
        single=args.single,
        multi_channel=args.multi_channel,
        keep_temp=args.keep_temp,
    )

    decoder = AtmosDecode(args_dataclass)
    decoder.decode(args.input, args.output)


if __name__ == '__main__':
    try:
        main()
    except RuntimeError as e:
        print(e)