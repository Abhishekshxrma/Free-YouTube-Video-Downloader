import streamlit as st
from pytubefix import YouTube
import os
import subprocess
import re
import time
from pathlib import Path

# --- Page Config ---
st.set_page_config(page_title="Zenith 4K Downloader", page_icon="⚡", layout="centered")

# --- Styles ---
st.markdown("""
    <style>
    .stApp { background-color: #0e1117; color: white; }
    .stButton > button { background-color: #FF4B4B; color: white; border-radius: 8px; width: 100%; }
    .success-box { padding: 15px; background-color: #1f77b4; border-radius: 10px; text-align: center; margin-top: 20px;}
    .info-text { font-size: 0.9em; color: #bbb; }
    </style>
""", unsafe_allow_html=True)

# --- Helper: Format Bytes ---
def format_bytes(size):
    power = 2**10
    n = 0
    power_labels = {0 : '', 1: 'K', 2: 'M', 3: 'G', 4: 'T'}
    while size > power:
        size /= power
        n += 1
    return f"{size:.1f} {power_labels[n]}B"

# --- Helper: Download Monitor Class ---
class DownloadMonitor:
    def __init__(self):
        self.bar = None
        self.text = None
        self.total_size = 0
        self.last_time = 0
        self.last_bytes = 0

    def set_ui(self, bar, text, total_size):
        self.bar = bar
        self.text = text
        self.total_size = total_size
        self.last_time = time.time()
        self.last_bytes = total_size # bytes_remaining starts at total

    def on_progress(self, stream, chunk, bytes_remaining):
        if not self.bar: return
        
        current_time = time.time()
        # Update UI every 0.1s to avoid freezing
        if current_time - self.last_time > 0.1 or bytes_remaining == 0:
            
            # Calculate Progress
            downloaded = self.total_size - bytes_remaining
            pct = downloaded / self.total_size if self.total_size > 0 else 0
            
            # Calculate Speed
            time_diff = current_time - self.last_time
            bytes_diff = self.last_bytes - bytes_remaining
            
            speed = 0
            if time_diff > 0:
                speed = bytes_diff / time_diff # Bytes per second
            
            # Update Streamlit UI
            self.bar.progress(min(pct, 1.0))
            self.text.markdown(f"""
                <span style="color:#4CAF50"><b>Downloading... {int(pct*100)}%</b></span><br>
                <span class="info-text">📦 {format_bytes(downloaded)} / {format_bytes(self.total_size)} | ⚡ {format_bytes(speed)}/s</span>
            """, unsafe_allow_html=True)
            
            # Update tracking vars
            self.last_time = current_time
            self.last_bytes = bytes_remaining

# Initialize global monitor in session state if not present
if 'monitor' not in st.session_state:
    st.session_state.monitor = DownloadMonitor()

# --- Helper Functions ---
def get_download_folder():
    return str(Path.home() / "Downloads")

def sanitize_filename(name):
    return re.sub(r'[<>:"/\\|?*]', '', name)

def merge_audio_video(video_path, audio_path, output_path):
    try:
        cmd = [
            'ffmpeg', '-y',
            '-i', video_path,
            '-i', audio_path,
            '-c:v', 'copy',
            '-c:a', 'aac',
            output_path
        ]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except FileNotFoundError:
        st.error("❌ FFmpeg not found! Please install FFmpeg.")
        return False
    except Exception as e:
        st.error(f"❌ Error merging files: {e}")
        return False

# --- UI Header ---
st.title("⚡ Zenith Auto-Saver")
st.write("Paste link -> Select Quality -> Auto-saves to your Downloads folder.")

# --- Step 1: Input & Fetch ---
url = st.text_input("YouTube URL", placeholder="Paste link here...")
fetch_clicked = st.button("Download")

if url and (fetch_clicked or 'yt_obj' in st.session_state):
    try:
        if fetch_clicked:
            with st.spinner("🔍 Fetching video details..."):
                # Hook the monitor's callback here
                st.session_state.yt_obj = YouTube(url, on_progress_callback=st.session_state.monitor.on_progress)
        
        yt = st.session_state.yt_obj

        # Display Info
        st.write("---")
        c1, c2 = st.columns([1, 2])
        with c1:
            st.image(yt.thumbnail_url, use_container_width=True)
        with c2:
            st.subheader(yt.title)
            st.caption(f"Length: {yt.length}s | Views: {yt.views:,}")

        # --- Step 2: Resolution Options ---
        st.write("### ⚙️ Select Quality")

        # Get Audio Size Reference (for High Res calc)
        # We assume the best audio track is used for merging
        best_audio = yt.streams.filter(only_audio=True).order_by('abr').desc().first()
        audio_size = best_audio.filesize if best_audio else 0

        resolutions = {}
        all_streams = yt.streams.filter(file_extension='mp4', type='video').order_by('resolution').desc()
        
        for s in all_streams:
            if s.resolution and s.resolution not in resolutions:
                resolutions[s.resolution] = s

        if not resolutions:
            st.warning("No suitable streams found.")
        else:
            # Build Dropdown Labels with File Size
            res_options = {}
            for res, stream in resolutions.items():
                is_adaptive = not stream.is_progressive
                
                # Estimate total size
                if is_adaptive:
                    est_size = stream.filesize + audio_size
                    label = f"{res} (High Res) - ~{format_bytes(est_size)}"
                else:
                    est_size = stream.filesize
                    label = f"{res} (Standard) - {format_bytes(est_size)}"
                
                res_options[label] = res

            selected_label = st.selectbox("Choose Resolution", list(res_options.keys()))
            selected_res = res_options[selected_label]
            selected_stream = resolutions[selected_res]

            # --- Step 3: Auto-Save Logic ---
            is_adaptive = not selected_stream.is_progressive
            action_text = f"⬇️ Download {selected_res}"
            
            if st.button(action_text):
                # UI Elements for Progress
                status_text = st.empty()
                progress_bar = st.progress(0)
                
                save_path = get_download_folder()
                clean_filename = sanitize_filename(selected_stream.default_filename)
                final_path = os.path.join(save_path, clean_filename)

                try:
                    if is_adaptive:
                        # 1. Video Download
                        st.session_state.monitor.set_ui(progress_bar, status_text, selected_stream.filesize)
                        status_text.text("⬇️ Phase 1/3: Downloading Video Track...")
                        video_path = selected_stream.download(output_path=save_path, filename_prefix="temp_video_")
                        
                        # 2. Audio Download
                        st.session_state.monitor.set_ui(progress_bar, status_text, audio_size)
                        status_text.text("⬇️ Phase 2/3: Downloading Audio Track...")
                        audio_path = best_audio.download(output_path=save_path, filename_prefix="temp_audio_")

                        # 3. Merge
                        with st.spinner("⚙️ Phase 3/3: Merging Audio & Video (this may take a moment)..."):
                            success = merge_audio_video(video_path, audio_path, final_path)
                        
                        # Cleanup
                        if os.path.exists(video_path): os.remove(video_path)
                        if os.path.exists(audio_path): os.remove(audio_path)

                        if success:
                            progress_bar.progress(100)
                            status_text.markdown("### ✅ Download Complete!")
                            st.success(f"Saved to: {final_path}")
                            st.balloons()
                    else:
                        # Standard Download
                        st.session_state.monitor.set_ui(progress_bar, status_text, selected_stream.filesize)
                        status_text.text("⬇️ Downloading Standard Stream...")
                        out_file = selected_stream.download(output_path=save_path, filename=clean_filename)
                        
                        progress_bar.progress(100)
                        status_text.markdown("### ✅ Download Complete!")
                        st.success(f"Saved to: {out_file}")
                        st.balloons()
                    
                except Exception as e:
                    st.error(f"Error: {e}")

    except Exception as e:
        st.error(f"Could not process URL. Error: {e}")