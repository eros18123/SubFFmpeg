
# __init__.py

import sys
import os
from pathlib import Path
import re
from datetime import timedelta, datetime
import threading
import time
import urllib.request
import json
import tarfile
import shutil
from zipfile import ZipFile, BadZipFile
import subprocess
from typing import Union, List, Dict, Optional, Any
import uuid

# --- Importações locais do addon ---
from .pt_br import translations as pt_br_translations
from .en_us import translations as en_us_translations
from .processing import setup_process_tab
from .subs_and_time import setup_subs_and_time_tab
from .images import setup_images_tab
from .reviews import setup_preview_tab
from .anki_export import setup_anki_export_tab
from .downloader import setup_downloader_tab

# --- Bloco de Verificação de Dependências ---
_WHISPER_AVAILABLE = True

try:
    from aqt.utils import showInfo, showError, askUser, shortcut
    _aqt_utils_ok = True
except ImportError:
    _aqt_utils_ok = False
    print("AVISO CRÍTICO (Add-on): Não foi possível importar utils de aqt.utils.")
    from PyQt6.QtWidgets import QMessageBox, QScrollArea, QWidget, QTabWidget

    def _showError_substitute(text: str, parent: Optional[QWidget]=None, title: str="Erro"):
        _parent = parent
        if not _parent:
            try: from aqt import mw as _mw_global; _parent = _mw_global
            except: _parent = None
        QMessageBox.critical(_parent, title, text)
    def _showInfo_substitute(text: str, parent: Optional[QWidget]=None, title: str="Informação"):
        _parent = parent
        if not _parent:
            try: from aqt import mw as _mw_global; _parent = _mw_global
            except: _parent = None
        QMessageBox.information(_parent, title, text)
    def _askUser_substitute(text: str, parent: Optional[QWidget]=None, title: str="Confirmação", default_yes: bool=True) -> bool:
        _parent = parent
        if not _parent:
            try: from aqt import mw as _mw_global; _parent = _mw_global
            except: _parent = None
        buttons = QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        default_button = QMessageBox.StandardButton.Yes if default_yes else QMessageBox.StandardButton.No
        reply = QMessageBox.question(_parent, title, text, buttons, default_button)
        return reply == QMessageBox.StandardButton.Yes
    def _shortcut(key_str: str) -> str: return key_str
    showError = _showError_substitute
    showInfo = _showInfo_substitute
    askUser = _askUser_substitute
    shortcut = _shortcut

ADDON_NAME = Path(__file__).parent.name
ADDON_PACKAGE = __name__.split('.')[0]
addon_path = Path(__file__).parent.resolve()
vendor_dir = addon_path / "vendor"
ffmpeg_vendor_dir = addon_path / "ffmpeg_vendor"

USER_CONFIG_FILENAME = f"{ADDON_PACKAGE}_settings.json"
USER_CONFIG_FILE_PATH = addon_path / USER_CONFIG_FILENAME

DEFAULT_APP_LANGUAGE = "pt_BR"

_FFMPEG_PATH: Optional[Path] = None
_FFPROBE_PATH: Optional[Path] = None
FFMPEG_WINDOWS_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
_ffmpeg_global_cancel_event = threading.Event()

AVAILABLE_LANGUAGES: Dict[str, Dict[str, str]] = {
    "pt_BR": {"name": "Português (Brasil)", "flag": "br.jpg"},
    "en_US": {"name": "English (US)", "flag": "us.jpg"},
}

_CURRENT_DIALOG_LANG_FOR_FFMPEG_SETUP = DEFAULT_APP_LANGUAGE

# CORREÇÃO: Atualiza o título do diálogo para usar a variável ADDON_NAME
pt_br_translations["dialog.title"] = f"Divisor de Mídia Avançado ({ADDON_NAME})"
en_us_translations["dialog.title"] = f"Advanced Media Splitter ({ADDON_NAME})"

TRANSLATIONS: Dict[str, Dict[str, str]] = {
    "pt_BR": pt_br_translations,
    "en_US": en_us_translations,
}

_deep_translator_installed = False

def tr_ffmpeg(key: str, **kwargs: Any) -> str:
    lang_code_to_use = None

    if 'dialog_instance' in globals() and dialog_instance and hasattr(dialog_instance, 'current_lang_code'):
        if dialog_instance.current_lang_code in TRANSLATIONS:
            lang_code_to_use = dialog_instance.current_lang_code
    
    if not lang_code_to_use:
        global _CURRENT_DIALOG_LANG_FOR_FFMPEG_SETUP
        if _CURRENT_DIALOG_LANG_FOR_FFMPEG_SETUP and _CURRENT_DIALOG_LANG_FOR_FFMPEG_SETUP in TRANSLATIONS:
            lang_code_to_use = _CURRENT_DIALOG_LANG_FOR_FFMPEG_SETUP

    if not lang_code_to_use:
        try:
            if 'mw' in globals() and mw and hasattr(mw, 'addonManager') and callable(mw.addonManager.getConfig):
                config = mw.addonManager.getConfig(ADDON_PACKAGE)
                if config and "app_language" in config: 
                    loaded_lang = config["app_language"]
                    if loaded_lang in TRANSLATIONS:
                        lang_code_to_use = loaded_lang
        except Exception:
            pass

    if not lang_code_to_use or lang_code_to_use not in TRANSLATIONS:
        lang_code_to_use = DEFAULT_APP_LANGUAGE
        
    translation_string = TRANSLATIONS[lang_code_to_use].get(key, key)

    if key in ["ffmpeg.ask_download_message", "ffmpeg.download_cancelled_message_addon", "ffmpeg.ask_download_title"]:
        return translation_string 
    else:
        return translation_string.format(**kwargs)


def _log_setup(message: str) -> None: print(f"Add-on '{ADDON_NAME}' (Setup): {message}")

from PyQt6.QtCore import QObject as QtQObject, pyqtSignal as QtSignal, QTimer as QtQTimer, Qt, QUrl
from PyQt6.QtWidgets import QProgressDialog, QListWidget, QListWidgetItem, QSlider, QStyle, QMenu
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from PyQt6.QtMultimediaWidgets import QVideoWidget


class FFmpegDownloadSignals(QtQObject):
    progress = QtSignal(int)
    finished = QtSignal(bool, str)
    log_message = QtSignal(str)

def _perform_ffmpeg_download_and_extraction_task(
    url: str,
    zip_target_path: Path,
    extract_to_dir: Path,
    signals: FFmpegDownloadSignals,
    cancel_event: threading.Event
):
    try:
        signals.log_message.emit(tr_ffmpeg("ffmpeg.downloading_message"))

        def reporthook(count, block_size, total_size):
            if cancel_event.is_set():
                raise Exception("Download cancelled by user via event")
            
            downloaded = count * block_size
            if total_size > 0:
                percentage = int(downloaded * 100 / total_size)
                signals.progress.emit(percentage)
            else:
                signals.progress.emit(0)

        urllib.request.urlretrieve(url, zip_target_path, reporthook=reporthook)
        
        if cancel_event.is_set():
            raise Exception("Download completed but cancellation was requested")

        signals.progress.emit(100)
        signals.log_message.emit(tr_ffmpeg("ffmpeg.extracting_message"))

        temp_extract_dir = extract_to_dir / "_temp_ffmpeg_extract"
        if temp_extract_dir.exists():
            shutil.rmtree(temp_extract_dir)
        temp_extract_dir.mkdir(parents=True, exist_ok=True)

        with ZipFile(zip_target_path, 'r') as zip_ref:
            zip_ref.extractall(temp_extract_dir)
        
        extracted_root_dirs = [d for d in temp_extract_dir.iterdir() if d.is_dir()]
        if not extracted_root_dirs:
            raise Exception("Unexpected FFmpeg ZIP structure (no root folder).")
        
        ffmpeg_build_dir = extracted_root_dirs[0]
        source_bin_dir = ffmpeg_build_dir / "bin"

        if not source_bin_dir.is_dir():
            raise Exception(tr_ffmpeg("ffmpeg.extraction_error_no_bin"))

        executables_to_copy = ["ffmpeg.exe", "ffprobe.exe"]
        for exe_name in executables_to_copy:
            source_exe_path = source_bin_dir / exe_name
            if source_exe_path.exists():
                shutil.move(str(source_exe_path), str(extract_to_dir / exe_name))
            else:
                raise Exception(tr_ffmpeg("ffmpeg.extraction_exe_missing", exe_name=exe_name))
        
        signals.finished.emit(True, str(extract_to_dir))

    except Exception as e:
        error_message = str(e)
        if "cancelled by user" in error_message.lower() or "cancellation was requested" in error_message.lower():
            signals.log_message.emit(tr_ffmpeg("ffmpeg.download_cancelled_by_user")) 
            signals.finished.emit(False, tr_ffmpeg("ffmpeg.download_cancelled_by_user")) 
        elif isinstance(e, urllib.error.URLError) or isinstance(e, OSError):
            signals.log_message.emit(tr_ffmpeg("ffmpeg.download_failed_with_error", error=error_message))
            signals.finished.emit(False, tr_ffmpeg("ffmpeg.download_failed_with_error", error=error_message))
        elif isinstance(e, BadZipFile):
            signals.log_message.emit(tr_ffmpeg("ffmpeg.zip_file_error", error=error_message))
            signals.finished.emit(False, tr_ffmpeg("ffmpeg.zip_file_error", error=error_message))
        else:
            signals.log_message.emit(tr_ffmpeg("ffmpeg.extraction_failed", error=error_message))
            signals.finished.emit(False, tr_ffmpeg("ffmpeg.extraction_failed", error=error_message))
            
    finally:
        if zip_target_path.exists():
            zip_target_path.unlink(missing_ok=True)
        if 'temp_extract_dir' in locals() and temp_extract_dir.exists():
            shutil.rmtree(temp_extract_dir, ignore_errors=True)


_ffmpeg_download_dialog_ref: Optional[QProgressDialog] = None

def _download_and_extract_ffmpeg_windows(
    parent_widget_for_dialogs: Optional[QWidget],
    us_flag_html: str, 
    br_flag_html: str
) -> bool:
    global _FFMPEG_PATH, _FFPROBE_PATH
    global _ffmpeg_download_dialog_ref, _ffmpeg_global_cancel_event
    
    try:
        ffmpeg_vendor_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        err_msg = tr_ffmpeg("ffmpeg.error_creating_vendor_dir", path=str(ffmpeg_vendor_dir), error=e)
        _log_setup(f"FFMPEG_SETUP: {err_msg}")
        showError(err_msg, parent=parent_widget_for_dialogs, title=tr_ffmpeg("general.error.title"))
        return False

    zip_path = ffmpeg_vendor_dir / "ffmpeg-download.zip"
    _ffmpeg_global_cancel_event.clear()

    download_signals = FFmpegDownloadSignals()
    
    progress_dialog = QProgressDialog(
        tr_ffmpeg("ffmpeg.downloading_message"), 
        tr_ffmpeg("general.button.cancel"), 0, 100, 
        parent_widget_for_dialogs
    )
    _ffmpeg_download_dialog_ref = progress_dialog

    current_flags = progress_dialog.windowFlags()
    progress_dialog.setWindowFlags(current_flags | Qt.WindowType.WindowMinimizeButtonHint)

    progress_dialog.setWindowModality(Qt.WindowModality.NonModal)
    progress_dialog.setMinimumDuration(0)
    progress_dialog.setAutoClose(False)
    progress_dialog.setValue(0)

    operation_completed_event = threading.Event()
    operation_success_flag = [False]

    def update_dialog_progress(percentage: int):
        if _ffmpeg_download_dialog_ref and _ffmpeg_download_dialog_ref.isVisible():
            _ffmpeg_download_dialog_ref.setValue(percentage)
            _ffmpeg_download_dialog_ref.setLabelText(tr_ffmpeg("ffmpeg.download_progress_label", percent=percentage))

    def on_download_finished(success: bool, message_key_or_error: str):
        global _FFMPEG_PATH, _FFPROBE_PATH, _ffmpeg_download_dialog_ref
        if _ffmpeg_download_dialog_ref and _ffmpeg_download_dialog_ref.isVisible():
            _ffmpeg_download_dialog_ref.close()
        _ffmpeg_download_dialog_ref = None

        if success:
            _log_setup(f"FFMPEG_SETUP: {tr_ffmpeg('ffmpeg.install_success_message', path=message_key_or_error)}")
            ffmpeg_exe_name = "ffmpeg.exe"
            ffprobe_exe_name = "ffprobe.exe"
            addon_ffmpeg_path = ffmpeg_vendor_dir / ffmpeg_exe_name
            addon_ffprobe_path = ffmpeg_vendor_dir / ffprobe_exe_name

            if addon_ffmpeg_path.exists() and addon_ffprobe_path.exists():
                _FFMPEG_PATH = addon_ffmpeg_path
                _FFPROBE_PATH = addon_ffprobe_path
                if str(ffmpeg_vendor_dir) not in os.environ['PATH'].split(os.pathsep):
                    os.environ['PATH'] = str(ffmpeg_vendor_dir) + os.pathsep + os.environ['PATH']
                showInfo(tr_ffmpeg("ffmpeg.install_success_message", path=str(ffmpeg_vendor_dir)), 
                         parent=parent_widget_for_dialogs, title=tr_ffmpeg("general.info.title"))
                operation_success_flag[0] = True
            else:
                _log_setup("FFMPEG_SETUP: Download/Extraction reported success, but executables not found.")
                showError(tr_ffmpeg("ffmpeg.config_after_download_fail"), 
                          parent=parent_widget_for_dialogs, title=tr_ffmpeg("general.error.title"))
                operation_success_flag[0] = False
        else:
            _log_setup(f"FFMPEG_SETUP: Falha - {message_key_or_error}")
            if message_key_or_error == tr_ffmpeg("ffmpeg.download_cancelled_by_user"): 
                cancel_ui_message_base = tr_ffmpeg("ffmpeg.download_cancelled_message_addon")
                cancel_ui_message_formatted = cancel_ui_message_base.format(us_flag_html=us_flag_html, br_flag_html=br_flag_html)
                showInfo(cancel_ui_message_formatted, 
                         parent=parent_widget_for_dialogs, title=tr_ffmpeg("general.info.title"))
            else:
                 showError(tr_ffmpeg("ffmpeg.install_fail_message", error=message_key_or_error), 
                           parent=parent_widget_for_dialogs, title=tr_ffmpeg("general.error.title"))
            operation_success_flag[0] = False
        
        operation_completed_event.set()

    def on_log_message(message: str):
        _log_setup(f"FFMPEG_DOWNLOAD_THREAD: {message}")

    download_signals.progress.connect(update_dialog_progress)
    download_signals.finished.connect(on_download_finished)
    download_signals.log_message.connect(on_log_message)
    
    progress_dialog.canceled.connect(lambda: _ffmpeg_global_cancel_event.set())

    thread = threading.Thread(
        target=_perform_ffmpeg_download_and_extraction_task,
        args=(FFMPEG_WINDOWS_URL, zip_path, ffmpeg_vendor_dir, download_signals, _ffmpeg_global_cancel_event),
        daemon=True 
    )
    thread.start()
    progress_dialog.show()

    while not operation_completed_event.is_set():
        QApplication.processEvents()
        if not thread.is_alive() and not operation_completed_event.is_set():
            _log_setup("FFMPEG_SETUP: Download thread died unexpectedly.")
            if _ffmpeg_download_dialog_ref and _ffmpeg_download_dialog_ref.isVisible():
                _ffmpeg_download_dialog_ref.close()
            _ffmpeg_download_dialog_ref = None
            showError(tr_ffmpeg("ffmpeg.install_fail_message", error="Thread died"), parent=parent_widget_for_dialogs)
            operation_success_flag[0] = False
            break 
        time.sleep(0.1)

    return operation_success_flag[0]


def _ensure_ffmpeg_is_available(parent_widget_for_dialogs: Optional[QWidget]) -> bool:
    global _FFMPEG_PATH, _FFPROBE_PATH
    
    us_flag_path_obj = addon_path / "us.jpg"
    br_flag_path_obj = addon_path / "br.jpg"
    
    us_flag_html = f'<img src="{us_flag_path_obj.as_uri()}" width="20" height="13" style="vertical-align:middle;"> ' if us_flag_path_obj.exists() else ""
    br_flag_html = f'<img src="{br_flag_path_obj.as_uri()}" width="20" height="14" style="vertical-align:middle;"> ' if br_flag_path_obj.exists() else ""
    
    system_ffmpeg = shutil.which("ffmpeg")
    system_ffprobe = shutil.which("ffprobe")

    if system_ffmpeg and system_ffprobe:
        _FFMPEG_PATH = Path(system_ffmpeg)
        _FFPROBE_PATH = Path(system_ffprobe)
        _log_setup(f"FFMPEG_SETUP: {tr_ffmpeg('ffmpeg.using_system_ffmpeg', path=str(_FFMPEG_PATH))}")
        return True

    ffmpeg_exe_name = "ffmpeg.exe" if os.name == 'nt' else "ffmpeg"
    ffprobe_exe_name = "ffprobe.exe" if os.name == 'nt' else "ffprobe"
    
    addon_ffmpeg_path = ffmpeg_vendor_dir / ffmpeg_exe_name
    addon_ffprobe_path = ffmpeg_vendor_dir / ffprobe_exe_name

    if addon_ffmpeg_path.exists() and addon_ffprobe_path.exists():
        _FFMPEG_PATH = addon_ffmpeg_path
        _FFPROBE_PATH = addon_ffprobe_path
        
        if str(ffmpeg_vendor_dir) not in os.environ['PATH'].split(os.pathsep):
            os.environ['PATH'] = str(ffmpeg_vendor_dir) + os.pathsep + os.environ['PATH']
            _log_setup(f"FFMPEG_SETUP: Adicionado {ffmpeg_vendor_dir} ao PATH da sessão.")

        _log_setup(f"FFMPEG_SETUP: {tr_ffmpeg('ffmpeg.using_addon_ffmpeg', path=str(_FFMPEG_PATH))}")
        return True

    if os.name == 'nt':
        ask_title_formatted = tr_ffmpeg("ffmpeg.ask_download_title")
        ask_message_base = tr_ffmpeg("ffmpeg.ask_download_message")
        ask_message_formatted = ask_message_base.format(us_flag_html=us_flag_html, br_flag_html=br_flag_html)

        if askUser(ask_message_formatted, parent=parent_widget_for_dialogs, title=ask_title_formatted):
            if _download_and_extract_ffmpeg_windows(parent_widget_for_dialogs, us_flag_html, br_flag_html):
                return True
            else:
                return False
        else:
            _log_setup("FFMPEG_SETUP: Usuário cancelou o download do FFmpeg.")
            cancel_message_base = tr_ffmpeg("ffmpeg.download_cancelled_message_addon")
            cancel_message_formatted = cancel_message_base.format(us_flag_html=us_flag_html, br_flag_html=br_flag_html)
            info_title_formatted = tr_ffmpeg("general.info.title") 
            showInfo(cancel_message_formatted, parent=parent_widget_for_dialogs, title=info_title_formatted)
            return False
    else:
        _log_setup("FFMPEG_SETUP: FFmpeg não encontrado. Orientando usuário para instalação manual.")
        linux_mac_title_formatted = tr_ffmpeg("ffmpeg.ask_download_title")
        showInfo(tr_ffmpeg("ffmpeg.manual_install_message_linux_mac"), parent=parent_widget_for_dialogs, title=linux_mac_title_formatted)
        return False
    
    _log_setup("FFMPEG_SETUP: FFmpeg não configurado (fim da função _ensure_ffmpeg_is_available).")
    return False

from aqt import mw
from aqt.qt import (
    Qt, QAction, QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QFileDialog, QTextEdit, QProgressBar, QMessageBox, QGroupBox,
    QApplication, QTimer, QComboBox, QGridLayout, QScrollArea, QWidget, QTabWidget,
    pyqtSignal, QCheckBox
)
from PyQt6.QtGui import QIcon


def ms_to_ffmpeg_time(ms: int) -> str:
    td = timedelta(milliseconds=ms)
    hours, remainder = divmod(td.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    milliseconds = td.microseconds // 1000
    return f"{hours:02}:{minutes:02}:{seconds:02}.{milliseconds:03}"

def sanitize_filename(text: str, max_length: int = 60) -> str:
    if not text: return "audio_sem_texto" 
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', text).strip()
    text = re.sub(r'\s+', '_', text)
    return text[:max_length] if len(text) > max_length else (text if text else "processado")

def time_str_to_ms(time_str: str) -> int:
    time_str = time_str.replace(',', '.')
    
    if time_str.count(':') == 1:
        time_str = "00:" + time_str

    try:
        t = datetime.strptime(time_str, '%H:%M:%S.%f')
        delta = timedelta(hours=t.hour, minutes=t.minute, seconds=t.second, microseconds=t.microsecond)
        return int(delta.total_seconds() * 1000)
    except ValueError:
        return 0

def ms_to_srt_time(ms: int) -> str:
    if ms < 0: ms = 0
    td = timedelta(milliseconds=ms)
    total_seconds = td.total_seconds()
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    milliseconds = td.microseconds // 1000
    return f"{int(hours):02}:{int(minutes):02}:{int(seconds):02},{int(milliseconds):03}"

def compose_srt(subtitles_data: List[Dict[str, Any]]) -> str:
    srt_content = []
    for sub in subtitles_data:
        index = sub['id']
        start_time = ms_to_srt_time(sub['start_ms'])
        end_time = ms_to_srt_time(sub['end_ms'])
        text = sub['text']
        srt_content.append(f"{index}\n{start_time} --> {end_time}\n{text}\n")
    return "\n".join(srt_content)

def parse_srt_file(subtitle_file_path: str, log_func: Any, is_translation: bool = False) -> List[Dict[str, Any]]:
    parsed_items: List[Dict[str, Any]] = []
    file_type_str = 'tradução' if is_translation else 'legenda principal'

    if not subtitle_file_path or not Path(subtitle_file_path).is_file():
        log_func(f"Arquivo de {file_type_str} não encontrado ou inválido: '{subtitle_file_path}'")
        return parsed_items

    try:
        with open(subtitle_file_path, 'r', encoding='utf-8') as f:
            content = f.read()
    except UnicodeDecodeError:
        try:
            with open(subtitle_file_path, 'r', encoding='latin-1') as f:
                content = f.read()
                log_func(f"{file_type_str.capitalize()} lida com codificação latin-1 (fallback).")
        except Exception as e:
            log_func(f"ERRO ao ler arquivo de {file_type_str} (UTF-8 e Latin-1 falharam): {e}")
            return parsed_items
    except Exception as e:
        log_func(f"ERRO ao abrir arquivo de {file_type_str}: {e}")
        return parsed_items

    time_pattern = re.compile(r"(\d{2,}:\d{2}:\d{2}[,.]\d{3}|\d{2}:\d{2}[,.]\d{3})\s*-->\s*(\d{2,}:\d{2}:\d{2}[,.]\d{3}|\d{2}:\d{2}[,.]\d{3})")
    blocks = re.split(r'\n\s*\n', content.strip())
    
    sequential_id_counter = 1
    for block in blocks:
        lines = block.strip().split('\n')
        if not lines:
            continue

        time_match = None
        text_lines_start_index = -1
        potential_id = -1
        line_cursor = 0

        if line_cursor < len(lines) and lines[line_cursor].strip().isdigit():
            potential_id = int(lines[line_cursor].strip())
            line_cursor += 1
        
        if line_cursor < len(lines):
            match = time_pattern.search(lines[line_cursor])
            if match:
                time_match = match
                text_lines_start_index = line_cursor + 1
        
        if not time_match:
            line_cursor = 0
            potential_id = -1
            if line_cursor < len(lines):
                match = time_pattern.search(lines[line_cursor])
                if match:
                    time_match = match
                    text_lines_start_index = line_cursor + 1

        if not time_match:
            continue

        start_str = time_match.group(1)
        end_str = time_match.group(2)
        text = " ".join(lines[text_lines_start_index:]).strip()

        if not text:
            continue

        final_id = potential_id if potential_id != -1 else sequential_id_counter

        item_data: Dict[str, Any] = {
            'id': final_id,
            'text': text,
        }
        
        if not is_translation:
            item_data['start_ms'] = time_str_to_ms(start_str)
            item_data['end_ms'] = time_str_to_ms(end_str)
            item_data['media_file_path'] = None
        
        parsed_items.append(item_data)
        sequential_id_counter += 1

    log_func(f"{len(parsed_items)} itens de {file_type_str} carregados do arquivo usando o analisador flexível.")
    return parsed_items

class ProgressSignal(QtQObject):
    update_progress = QtSignal(int, str, int, float)
    finalize = QtSignal(list, int, int, Path)
    log = QtSignal(str)

class ImageConversionSignal(QtQObject):
    update_conversion_progress = QtSignal(int, str, int)
    finalize_conversion = QtSignal(int, int)
    log = QtSignal(str)

class TranscriptionSignal(QtQObject):
    update_status = QtSignal(str)
    finalize = QtSignal(str, object) 
    log = QtSignal(str)

class SimpleAudioSplitterDialog(QDialog):
    CONFIG_KEY_LAST_MEDIA_DIR = "last_media_dir"
    CONFIG_KEY_LAST_MEDIA_FILE = "last_media_file"
    CONFIG_KEY_LAST_SUBTITLE_FILE = "last_subtitle_file"
    CONFIG_KEY_LAST_TRANSLATION_FILE = "last_translation_file"
    CONFIG_KEY_LANGUAGE = "app_language"
    CONFIG_KEY_DIRECT_PROCESS_TO_CM = "direct_process_to_collection_media"
    CONFIG_KEY_DIRECT_IMAGES_TO_CM = "direct_images_to_collection_media"
    CONFIG_KEY_LAST_OUTPUT_FORMAT = "last_output_format_index"
    CONFIG_KEY_LIMIT_TIME_RANGE_ENABLED = "limit_time_range_enabled"
    CONFIG_KEY_LIMIT_START_TIME = "limit_start_time"
    CONFIG_KEY_LIMIT_END_TIME = "limit_end_time"
    CONFIG_KEY_ANKI_DECK_NAME = "anki_last_deck_name"
    CONFIG_KEY_ANKI_MODEL_NAME = "anki_last_model_name"
    CONFIG_KEY_ANKI_FIELD_MEDIA = "anki_last_field_media"
    CONFIG_KEY_ANKI_FIELD_SUB = "anki_last_field_sub"
    CONFIG_KEY_ANKI_FIELD_TRANS = "anki_last_field_trans"
    CONFIG_KEY_ANKI_FIELD_IMG = "anki_last_field_img"
    CONFIG_KEY_PREVIEW_SPEED = "preview_last_speed_index"
    CONFIG_KEY_LAST_PROCESSED_DATA = "last_processed_data"
    CONFIG_KEY_ASSEMBLYAI_API_KEY = "assemblyai_api_key"
    CONFIG_KEY_TRANSCRIPTION_LANG = "transcription_language"
    CONFIG_KEY_ADJUST_CUTS_TO_SILENCE = "adjust_cuts_to_silence"
    CONFIG_KEY_ANKI_SOURCE_FOLDER = "anki_last_source_folder"
    CONFIG_KEY_ANKI_USE_FOLDER_MODE = "anki_use_folder_mode"

    # --- Anexando métodos dos módulos de abas ---
    setup_process_tab = setup_process_tab
    setup_subs_and_time_tab = setup_subs_and_time_tab
    setup_images_tab = setup_images_tab
    setup_preview_tab = setup_preview_tab
    setup_anki_export_tab = setup_anki_export_tab

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent or mw)
        
        self.current_lang_code: str = self._load_config_value(self.CONFIG_KEY_LANGUAGE, DEFAULT_APP_LANGUAGE)
        global _CURRENT_DIALOG_LANG_FOR_FFMPEG_SETUP
        _CURRENT_DIALOG_LANG_FOR_FFMPEG_SETUP = self.current_lang_code

        self.setMinimumSize(850, 750)
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.WindowMinimizeButtonHint | Qt.WindowType.WindowCloseButtonHint | Qt.WindowType.WindowMaximizeButtonHint)
        self.setModal(False)

        self.media_file_path_var: str = self.load_last_media_file()
        self.subtitle_file_path_var: str = self.load_last_subtitle_file() 
        self.translation_file_path_var: str = self.load_last_translation_file()
        self.last_media_dir: str = self.load_last_media_dir()
        self.anki_source_folder_path_var: str = self._load_config_value(self.CONFIG_KEY_ANKI_SOURCE_FOLDER, "")
        self.anki_use_folder_mode: bool = self._load_config_value(self.CONFIG_KEY_ANKI_USE_FOLDER_MODE, False)
        self.files_listed_for_anki_export: List[Path] = []
        
        self.api_key_var: str = self._load_config_value(self.CONFIG_KEY_ASSEMBLYAI_API_KEY, "")
        self.last_transcription_lang_index: int = self._load_config_value(self.CONFIG_KEY_TRANSCRIPTION_LANG, 0)

        self.offset_seconds_var_val: str = "0.0"

        self.subtitles_data: List[Dict[str, Any]] = []
        self.translations_data: List[Dict[str, Any]] = []
        self.processing_thread: Optional[threading.Thread] = None
        self.single_clip_thread: Optional[threading.Thread] = None
        self.image_conversion_thread: Optional[threading.Thread] = None
        self.transcription_thread: Optional[threading.Thread] = None
        self.stop_requested_event = threading.Event()
        self.stop_image_conversion_event = threading.Event()
        self.stop_transcription_event = threading.Event()
        self.images_generated_in_this_session: bool = False



        self.speed_samples: List[float] = []
        self.max_samples: int = 5

        self.startupinfo: Any = None 
        if os.name == 'nt':
            self.startupinfo = subprocess.STARTUPINFO()
            self.startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            self.startupinfo.wShowWindow = subprocess.SW_HIDE

        self.progress_signal = ProgressSignal()
        self.progress_signal.update_progress.connect(self._update_progress_display)
        self.progress_signal.finalize.connect(self._finalize_processing)
        self.progress_signal.log.connect(self.log_message)

        self.image_conversion_signal = ImageConversionSignal()
        self.image_conversion_signal.update_conversion_progress.connect(self._update_image_conversion_progress_display)
        self.image_conversion_signal.finalize_conversion.connect(self._finalize_image_conversion)
        self.image_conversion_signal.log.connect(self.log_message_images_tab)

        self.transcription_signal = TranscriptionSignal()
        self.transcription_signal.update_status.connect(self._update_transcription_status_display)
        self.transcription_signal.finalize.connect(self._finalize_transcription)
        self.transcription_signal.log.connect(self.log_message)

        try:
            if mw and mw.col and mw.col.media:
                user_files_base = Path(mw.col.media.dir()).parent / "user_files"
                self.base_default_output_folder: Path = user_files_base / ADDON_NAME
                self.base_images_output_folder: Path = user_files_base / f"{ADDON_NAME}_images"
            else: raise AttributeError("Anki collection not fully loaded for path setup.")
        except:
            desktop_base = Path.home() / "Desktop" / "ankidesk_data"
            self.base_default_output_folder = desktop_base / ADDON_NAME
            self.base_images_output_folder = desktop_base / f"{ADDON_NAME}_images"
        
        self.output_folder_path_var = str(self.base_default_output_folder) 
        self.images_output_folder: Path = self.base_images_output_folder 

        try:
            self.base_images_output_folder.mkdir(parents=True, exist_ok=True) 
        except Exception as e:
            _log_setup(f"AVISO: Não foi possível criar a pasta de imagens padrão '{self.base_images_output_folder}': {e}")

        self.temp_preview_dir = addon_path / "_preview_temp"
        self.temp_preview_dir.mkdir(exist_ok=True)

        dialog_layout = QVBoxLayout(self)
        
        lang_selector_layout = QHBoxLayout()
        self.language_label_widget = QLabel()
        lang_selector_layout.addWidget(self.language_label_widget)
        self.language_combo = QComboBox()
        self._populate_language_combo() 
        lang_selector_layout.addWidget(self.language_combo)
        lang_selector_layout.addStretch()
        dialog_layout.addLayout(lang_selector_layout) 

        scroll_area = QScrollArea(); scroll_area.setWidgetResizable(True)
        dialog_layout.addWidget(scroll_area) 

        self.main_widget = QWidget()
        scroll_area.setWidget(self.main_widget) 

        main_content_layout = QVBoxLayout(self.main_widget)
        self.tabs = QTabWidget()
        main_content_layout.addWidget(self.tabs) 
        
        self.tab_process = QWidget()
        self.tab_subs_and_time = QWidget()
        self.tab_images = QWidget()
        self.tab_preview = QWidget()
        self.tab_anki_export = QWidget()
        self.tab_downloader = QWidget() # <--- 1. CRIA O ESPAÇO DA NOVA ABA AQUI

        self.tabs.addTab(self.tab_process, "...")
        self.tabs.addTab(self.tab_subs_and_time, "...")
        self.tabs.addTab(self.tab_images, "...")
        self.tabs.addTab(self.tab_preview, "...")
        self.tabs.addTab(self.tab_anki_export, "...")
        self.tabs.addTab(self.tab_downloader, "...") # <--- 2. ADICIONA A ABA NO MENU SUPERIOR

        self.pref_direct_process_to_cm: bool = self._load_config_value(self.CONFIG_KEY_DIRECT_PROCESS_TO_CM, False)
        self.pref_direct_images_to_cm: bool = self._load_config_value(self.CONFIG_KEY_DIRECT_IMAGES_TO_CM, False)
        
        self.last_output_format_index: int = self._load_config_value(self.CONFIG_KEY_LAST_OUTPUT_FORMAT, 1)
        self.limit_time_range_enabled: bool = self._load_config_value(self.CONFIG_KEY_LIMIT_TIME_RANGE_ENABLED, False)
        self.limit_start_time_str: str = self._load_config_value(self.CONFIG_KEY_LIMIT_START_TIME, "00:00:00")
        self.limit_end_time_str: str = self._load_config_value(self.CONFIG_KEY_LIMIT_END_TIME, "00:00:00")
        self.adjust_cuts_to_silence_enabled: bool = self._load_config_value(self.CONFIG_KEY_ADJUST_CUTS_TO_SILENCE, False)

        self.setup_process_tab()
        self.setup_subs_and_time_tab()
        self.setup_images_tab()
        self.setup_preview_tab()
        self.setup_anki_export_tab()
        setup_downloader_tab(self) # <--- 3. DESENHA O CONTEÚDO DA ABA AQUI



        self.anki_use_folder_cb.setChecked(self.anki_use_folder_mode)
        self._on_anki_source_mode_changed(self.anki_use_folder_mode)
        self.load_anki_options() 

        last_speed_index = self._load_config_value(self.CONFIG_KEY_PREVIEW_SPEED, 1)
        self.speed_combo.setCurrentIndex(last_speed_index)

        self.audio_output = QAudioOutput()
        self.media_player.setAudioOutput(self.audio_output)
        self.audio_output.setVolume(0.75)
        self.volume_slider.setValue(75)

        self._on_direct_process_to_cm_changed(self.direct_to_media_collection_cb_process.isChecked())
        self._on_direct_images_to_cm_changed(self.direct_to_media_collection_cb_images.isChecked())
        self._on_limit_time_range_toggled()

        self.language_combo.currentIndexChanged.connect(self._on_language_changed)
        self._retranslate_ui() 

        self._load_last_session_data()

        if not self.subtitles_data:
            if self.subtitle_file_path_var: self.load_subtitles_from_file()
            if self.translation_file_path_var: self.load_translations_from_file()
        
        self.populate_preview_list()
        self.list_output_folder_files()

        self.log_message(self.tr("log.addon_started", addon_name=ADDON_NAME))
        self.log_message(self.tr("process.log.using_config_file_location", path=USER_CONFIG_FILE_PATH))
        self.log_message(self.tr("process.log.default_output_folder_media", path=self.base_default_output_folder))
        self.log_message(self.tr("process.log.default_output_folder_images", path=self.base_images_output_folder))
        
        if _FFMPEG_PATH:
            self.log_message(self.tr("ffmpeg.using_addon_ffmpeg", path=str(_FFMPEG_PATH)) if str(addon_path) in str(_FFMPEG_PATH) 
                             else self.tr("ffmpeg.using_system_ffmpeg", path=str(_FFMPEG_PATH)))
        else: 
            self.log_message(self.tr("process.info.ffmpeg_not_found"))
        
    def tr(self, key: str, **kwargs: Any) -> str:
        try:
            format_args = {"addon_name": ADDON_NAME}
            format_args.update(kwargs)
            return TRANSLATIONS[self.current_lang_code].get(key, key).format(**format_args)
        except KeyError: 
            format_args = {"addon_name": ADDON_NAME}
            format_args.update(kwargs)
            if self.current_lang_code != "en_US" and "en_US" in TRANSLATIONS:
                 return TRANSLATIONS["en_US"].get(key,key).format(**format_args)
            return TRANSLATIONS[DEFAULT_APP_LANGUAGE].get(key, key).format(**format_args)
        except Exception: 
            return key 

    def _populate_language_combo(self) -> None:
        current_selection_index = 0
        for i, (code, lang_data) in enumerate(AVAILABLE_LANGUAGES.items()):
            icon_path = addon_path / lang_data["flag"]
            icon = QIcon(str(icon_path)) if icon_path.exists() else QIcon()
            self.language_combo.addItem(icon, lang_data["name"], code)
            if code == self.current_lang_code:
                current_selection_index = i
        self.language_combo.setCurrentIndex(current_selection_index)

    def _on_language_changed(self) -> None:
        new_lang_code = self.language_combo.currentData()
        if new_lang_code and new_lang_code != self.current_lang_code:
            self.current_lang_code = new_lang_code
            self._save_config_value(self.CONFIG_KEY_LANGUAGE, new_lang_code)
            global _CURRENT_DIALOG_LANG_FOR_FFMPEG_SETUP
            _CURRENT_DIALOG_LANG_FOR_FFMPEG_SETUP = new_lang_code
            self._retranslate_ui()

    def _retranslate_ui(self) -> None:
        self.setWindowTitle(self.tr("dialog.title"))
        self.language_label_widget.setText(self.tr("dialog.language_label"))

        self.tabs.setTabText(self.tabs.indexOf(self.tab_process), self.tr("tab.process.title"))
        self.tabs.setTabText(self.tabs.indexOf(self.tab_subs_and_time), self.tr("tab.subs_and_time.title"))
        self.tabs.setTabText(self.tabs.indexOf(self.tab_images), self.tr("tab.images.title"))
        self.tabs.setTabText(self.tabs.indexOf(self.tab_preview), self.tr("tab.preview.title"))
        self.tabs.setTabText(self.tabs.indexOf(self.tab_anki_export), self.tr("tab.anki_export.title"))

        self.tabs.setTabText(self.tabs.indexOf(self.tab_downloader), self.tr("tab.downloader.title")) # <--- NOVA ABA

        self.files_frame_process.setTitle(self.tr("process.group.files.title"))
        self.media_file_label_process.setText(self.tr("process.label.media_file"))
        self.media_entry.setPlaceholderText(self.tr("process.placeholder.media_file"))
        self.btn_open_media_process.setText(self.tr("process.button.open_media"))
        self.main_subtitle_label_process.setText(self.tr("process.label.main_subtitle"))
        self.sub_entry.setPlaceholderText(self.tr("process.placeholder.main_subtitle"))
        self.btn_open_sub_process.setText(self.tr("process.button.open_subtitle"))
        self.translation_subtitle_label_process.setText(self.tr("process.label.translation_subtitle"))
        self.translation_entry.setPlaceholderText(self.tr("process.placeholder.translation_subtitle"))
        self.btn_open_translation_process.setText(self.tr("process.button.open_translation"))
        self.output_folder_media_label_process.setText(self.tr("process.label.output_folder_media"))
        self.btn_select_out_process.setText(self.tr("process.button.select_output_folder"))
        self.direct_to_media_collection_cb_process.setText(self.tr("process.checkbox.direct_to_collection_media"))
        self.output_format_label_process.setText(self.tr("process.label.output_format"))
        self.output_format_combo.setItemText(0, self.tr("process.format.mp3"))
        self.output_format_combo.setItemText(1, self.tr("process.format.mp4"))
        self.output_format_combo.setItemText(2, self.tr("process.format.webm"))

        self.generation_frame_process.setTitle(self.tr("process.group.generation.title"))
        self.api_info_label.setText(self.tr("process.info.api_key_instructions"))
        self.btn_generate_subs.setText(self.tr("process.button.generate_subs"))
        self.transcription_lang_label.setText(self.tr("process.label.transcription_language"))
        self.api_key_label.setText(self.tr("process.label.api_key"))
        self.api_key_entry.setPlaceholderText(self.tr("process.placeholder.api_key"))

        self.generate_translation_cb.setText(self.tr("process.checkbox.generate_translation"))

        self.offset_frame_process.setTitle(self.tr("process.group.offset.title"))
        self.offset_seconds_label_process.setText(self.tr("process.label.offset_seconds"))
        self.btn_apply_offset_process.setText(self.tr("process.button.apply_offset_save_srt"))
        
        self.time_limit_frame.setTitle(self.tr("process.group.time_limit.title"))
        self.limit_time_range_cb.setText(self.tr("process.checkbox.limit_time_range"))
        self.start_time_label.setText(self.tr("process.label.time_limit_from"))
        self.end_time_label.setText(self.tr("process.label.time_limit_to"))
        self.start_time_entry.setPlaceholderText(self.tr("process.placeholder.time_limit"))
        self.end_time_entry.setPlaceholderText(self.tr("process.placeholder.time_limit"))

        self.single_clip_frame.setTitle(self.tr("process.group.single_clip.title"))
        self.single_clip_start_label.setText(self.tr("process.label.time_limit_from"))
        self.single_clip_end_label.setText(self.tr("process.label.time_limit_to"))
        self.btn_single_clip.setText(self.tr("process.button.single_clip"))

        self.processing_frame_process.setTitle(self.tr("process.group.main_processing.title"))
        self.adjust_cuts_cb.setText(self.tr("process.checkbox.adjust_cuts_to_silence"))
        self.split_button.setText(self.tr("process.button.split_media"))
        self.stop_button.setText(self.tr("process.button.stop_processing"))
        
        current_time_text = self.time_label.text()
        if self.tr("general.na_value") in current_time_text or not current_time_text or "N/A" in current_time_text or "N/D" in current_time_text :
            self.time_label.setText(f"{self.tr('process.label.time_remaining_prefix')} {self.tr('general.na_value')}")
        elif self.tr("process.label.status_calculating") in current_time_text:
            self.time_label.setText(f"{self.tr('process.label.time_remaining_prefix')} {self.tr('process.label.status_calculating')}")
        
        if not (self.processing_thread and self.processing_thread.is_alive()):
             self.status_label.setText(self.tr("process.label.status_ready"))
        self.log_frame_process.setTitle(self.tr("process.group.log.title"))
        
        self.images_frame.setTitle(self.tr("images.group.title"))
        self.images_from_source_info_label.setText(self.tr("images.info.generate_from_source"))
        self.generate_from_source_button.setText(self.tr("images.button.generate_from_source"))
        self.images_tab_info_text_label.setText(self.tr("images.info.source_videos_intro"))
        self.images_tab_output_path_label.setText(f"{self.tr('images.info.output_destination_prefix')}\n{self.images_output_folder}")
        self.direct_to_media_collection_cb_images.setText(self.tr("images.checkbox.direct_to_collection_media"))
        self.convert_videos_button.setText(self.tr("images.button.convert_videos"))
        self.stop_image_conversion_button.setText(self.tr("images.button.stop_conversion"))
        if not (self.image_conversion_thread and self.image_conversion_thread.is_alive()):
            self.image_conversion_status_label.setText(self.tr("images.label.status_ready"))
        self.log_images_frame.setTitle(self.tr("images.group.log.title"))

        self.preview_file_list_group.setTitle(self.tr("preview.group.file_list.title"))
        self.preview_refresh_button.setText(self.tr("preview.button.refresh"))
        self.preview_clear_all_button.setText(self.tr("preview.button.clear_all"))
        self.preview_player_group.setTitle(self.tr("preview.group.player.title"))
        self.subtitle_preview_label.setText(self.tr("preview.label.subtitle"))
        self.show_translation_cb.setText(self.tr("preview.checkbox.show_translation"))
        self.speed_combo.setItemText(0, self.tr("preview.speed.slow"))
        self.speed_combo.setItemText(1, self.tr("preview.speed.normal"))
        self.speed_combo.setItemText(2, self.tr("preview.speed.fast"))
        self.speed_combo.setItemText(3, self.tr("preview.speed.very_fast"))

        self.anki_frame.setTitle(self.tr("anki_export.group.title"))
        self.deck_label_anki.setText(self.tr("anki_export.label.deck"))
        self.note_type_label_anki.setText(self.tr("anki_export.label.note_type"))
        self.audio_field_label_anki.setText(self.tr("anki_export.label.media_field"))
        self.subtitle_field_label_anki.setText(self.tr("anki_export.label.subtitle_field"))
        self.translation_field_label_anki.setText(self.tr("anki_export.label.translation_field"))
        self.image_field_label_anki.setText(self.tr("anki_export.label.image_field"))
        self.anki_use_folder_cb.setText(self.tr("anki_export.checkbox.use_external_folder"))
        self.folder_log_group_anki.setTitle(self.tr("anki_export.group.media_files_anki.title"))
        self.anki_source_folder_label.setText(self.tr("anki_export.label.source_folder"))
        self.btn_select_anki_source_folder.setText(self.tr("anki_export.button.select_source_folder"))
        self.btn_clear_anki_source_folder.setText(self.tr("anki_export.button.clear_source_folder"))
        self.btn_list_files_anki.setText(self.tr("anki_export.button.list_media_files"))
        self.add_to_anki_button.setText(self.tr("anki_export.button.add_to_anki"))

        # --- Retradução da Aba Downloader ---
        if hasattr(self, 'dl_url_group'):
            self.dl_url_group.setTitle(self.tr("dl.group.url"))
            self.dl_url_input.setPlaceholderText(self.tr("dl.placeholder.url"))
            if self.dl_analyze_button.isEnabled():
                self.dl_analyze_button.setText(self.tr("dl.button.analyze"))

            self.dl_save_group.setTitle(self.tr("dl.group.save"))
            self.dl_desktop_radio.setText(self.tr("dl.radio.desktop"))
            self.dl_custom_path_radio.setText(self.tr("dl.radio.custom_path"))
            if not self.dl_custom_path_display.text():
                self.dl_custom_path_display.setPlaceholderText(self.tr("dl.placeholder.no_path"))
            self.dl_browse_button.setText(self.tr("dl.button.browse"))

            self.dl_auth_group.setTitle(self.tr("dl.group.auth"))
            self.dl_no_auth_radio.setText(self.tr("dl.radio.no_auth"))
            self.dl_cookie_file_radio.setText(self.tr("dl.radio.cookie"))
            if not self.dl_cookie_file_display.text():
                self.dl_cookie_file_display.setPlaceholderText(self.tr("dl.placeholder.no_cookie"))
            self.dl_browse_cookie_button.setText(self.tr("dl.button.browse"))

            icon_path = os.path.join(addon_path, "export_icon.png").replace('\\', '/')
            self.dl_cookie_help_label.setText(self.tr("dl.label.cookie_help", icon_path=icon_path))

            self.dl_format_group.setTitle(self.tr("dl.group.format"))
            self.dl_download_subs_checkbox.setText(self.tr("dl.checkbox.subs"))
            self.dl_langs_label.setText(self.tr("dl.label.langs"))
            self.dl_subs_langs_input.setPlaceholderText(self.tr("dl.placeholder.langs"))
            self.dl_subs_langs_input.setToolTip(self.tr("dl.tooltip.langs"))

            self.dl_tabs.setTabText(0, self.tr("dl.tab.video"))
            self.dl_tabs.setTabText(1, self.tr("dl.tab.audio"))

            self.dl_queue_group.setTitle(self.tr("dl.group.queue"))
            self.dl_queue_table.setHorizontalHeaderLabels([self.tr("dl.table.url"), self.tr("dl.table.status"), self.tr("dl.table.progress")])
            self.dl_start_queue_button.setText(self.tr("dl.button.start_queue"))
            self.dl_clear_completed_button.setText(self.tr("dl.button.clear_completed"))

    def _get_safe_anki_media_dir(self) -> Optional[Path]:
        try:
            if mw and mw.col and mw.col.media and mw.col.media.dir():
                return Path(mw.col.media.dir())
        except Exception:
            pass
        return None

    def _on_direct_process_to_cm_changed(self, state: Union[int, bool]) -> None: 
        is_direct = bool(state)
        self.pref_direct_process_to_cm = is_direct
        self._save_config_value(self.CONFIG_KEY_DIRECT_PROCESS_TO_CM, is_direct)
        
        anki_media_dir = self._get_safe_anki_media_dir()
        
        if is_direct:
            if anki_media_dir:
                self.out_entry.setText(str(anki_media_dir))
                self.out_entry.setReadOnly(True)
                self.btn_select_out_process.setEnabled(False)
            else:
                self.log_message(self.tr("general.anki_media_dir_unavailable_warning"))
                self.direct_to_media_collection_cb_process.setChecked(False) 
                self.out_entry.setReadOnly(False)
                self.out_entry.setText(str(self.base_default_output_folder))
                self.btn_select_out_process.setEnabled(True)
        else:
            self.out_entry.setReadOnly(False)
            current_out_text = self.out_entry.text()
            if anki_media_dir and Path(current_out_text) == anki_media_dir:
                 self.out_entry.setText(str(self.base_default_output_folder))
            elif not current_out_text: 
                self.out_entry.setText(str(self.base_default_output_folder))
            self.btn_select_out_process.setEnabled(True)
        self.output_folder_path_var = self.out_entry.text()

    def _on_direct_images_to_cm_changed(self, state: Union[int, bool]) -> None:
        is_direct = bool(state)
        self.pref_direct_images_to_cm = is_direct
        self._save_config_value(self.CONFIG_KEY_DIRECT_IMAGES_TO_CM, is_direct)

        anki_media_dir = self._get_safe_anki_media_dir()

        if is_direct:
            if anki_media_dir:
                self.images_output_folder = anki_media_dir
            else:
                self.log_message_images_tab(self.tr("general.anki_media_dir_unavailable_warning"))
                self.direct_to_media_collection_cb_images.setChecked(False) 
                self.images_output_folder = self.base_images_output_folder
        else:
            self.images_output_folder = self.base_images_output_folder
        
        if hasattr(self, 'images_tab_output_path_label'): 
            self.images_tab_output_path_label.setText(f"{self.tr('images.info.output_destination_prefix')}\n{self.images_output_folder}")

    def _on_anki_source_mode_changed(self, state: Union[int, bool]) -> None:
        use_folder = bool(state)
        self.anki_use_folder_mode = use_folder
        self._save_config_value(self.CONFIG_KEY_ANKI_USE_FOLDER_MODE, use_folder)

        widgets_to_toggle = [
            self.anki_source_folder_label,
            self.anki_source_folder_entry,
            self.btn_select_anki_source_folder,
            self.btn_clear_anki_source_folder,
        ]
        for widget in widgets_to_toggle:
            widget.setEnabled(use_folder)

        self.list_output_folder_files()

    def _load_config_value(self, key: str, default: Any = None) -> Any:
        config = self._load_addon_config()
        return config.get(key, default)

    def _save_config_value(self, key: str, value: Any) -> None:
        config = self._load_addon_config()
        config[key] = value
        self._save_addon_config(config)

    def _load_addon_config(self) -> Dict[str, Any]:
        if not USER_CONFIG_FILE_PATH.exists(): return {}
        try:
            with open(USER_CONFIG_FILE_PATH, 'r', encoding='utf-8') as f: config = json.load(f)
            return config if isinstance(config, dict) else {}
        except (json.JSONDecodeError, OSError) as e:
            print(f"AVISO ({ADDON_NAME}): Erro ao carregar '{USER_CONFIG_FILENAME}': {e}"); return {}

    def _save_addon_config(self, config_data: Dict[str, Any]) -> None:
        try:
            USER_CONFIG_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(USER_CONFIG_FILE_PATH, 'w', encoding='utf-8') as f: json.dump(config_data, f, indent=4)
        except OSError as e: print(f"AVISO ({ADDON_NAME}): Erro ao salvar '{USER_CONFIG_FILENAME}': {e}")

    def _load_last_session_data(self):
        data = self._load_config_value(self.CONFIG_KEY_LAST_PROCESSED_DATA, [])
        if isinstance(data, list):
            self.subtitles_data = data
            if data:
                self.log_message(self.tr("log.session_data_loaded", count=len(data)))

    def load_last_media_file(self) -> str:
        fp = self._load_config_value(self.CONFIG_KEY_LAST_MEDIA_FILE)
        return str(fp) if fp and Path(fp).is_file() else ""

    def save_last_media_file(self, filepath: str) -> None:
        self._save_config_value(self.CONFIG_KEY_LAST_MEDIA_FILE, filepath)

    def load_last_subtitle_file(self) -> str:
        fp = self._load_config_value(self.CONFIG_KEY_LAST_SUBTITLE_FILE)
        return str(fp) if fp and Path(fp).is_file() else ""

    def save_last_subtitle_file(self, filepath: str) -> None:
        self._save_config_value(self.CONFIG_KEY_LAST_SUBTITLE_FILE, filepath)
        self.subtitle_file_path_var = filepath 

    def load_last_translation_file(self) -> str:
        fp = self._load_config_value(self.CONFIG_KEY_LAST_TRANSLATION_FILE)
        return str(fp) if fp and Path(fp).is_file() else ""

    def save_last_translation_file(self, filepath: str) -> None:
        self._save_config_value(self.CONFIG_KEY_LAST_TRANSLATION_FILE, filepath)

    def load_last_media_dir(self) -> str:
        last_dir = self._load_config_value(self.CONFIG_KEY_LAST_MEDIA_DIR)
        if last_dir and Path(last_dir).is_dir(): return str(last_dir)
        config = self._load_addon_config()
        for key in [self.CONFIG_KEY_LAST_MEDIA_FILE, self.CONFIG_KEY_LAST_SUBTITLE_FILE, self.CONFIG_KEY_LAST_TRANSLATION_FILE]:
            fp = config.get(key)
            if fp and Path(fp).is_file(): return str(Path(fp).parent)
        return str(Path.home())

    def save_last_media_dir(self, directory: str) -> None:
        self._save_config_value(self.CONFIG_KEY_LAST_MEDIA_DIR, directory)
        self.last_media_dir = directory

    def _save_api_key(self, key_text: str):
        self._save_config_value(self.CONFIG_KEY_ASSEMBLYAI_API_KEY, key_text)

    def _save_transcription_language(self, index: int):
        self._save_config_value(self.CONFIG_KEY_TRANSCRIPTION_LANG, index)

    def _on_output_format_changed(self, index: int):
        self._save_config_value(self.CONFIG_KEY_LAST_OUTPUT_FORMAT, index)

    def _on_limit_time_range_toggled(self):
        is_enabled = self.limit_time_range_cb.isChecked()
        self.start_time_entry.setEnabled(is_enabled)
        self.end_time_entry.setEnabled(is_enabled)
        self._save_config_value(self.CONFIG_KEY_LIMIT_TIME_RANGE_ENABLED, is_enabled)

    def _parse_simple_time_to_ms(self, time_str: str) -> int:
        parts = time_str.split(':')
        parts = [int(p) for p in parts if p.isdigit()]
        
        seconds = 0
        try:
            if len(parts) == 3: # HH:MM:SS
                seconds = parts[0] * 3600 + parts[1] * 60 + parts[2]
            elif len(parts) == 2: # MM:SS
                seconds = parts[0] * 60 + parts[1]
            elif len(parts) == 1: # SS
                seconds = parts[0]
        except (IndexError, ValueError):
            return 0
            
        return seconds * 1000

    def show_preview_context_menu(self, position):
        if not self.preview_list_widget.selectedItems():
            return

        menu = QMenu()
        delete_action = menu.addAction(self.tr("preview.action.delete"))
        action = menu.exec(self.preview_list_widget.mapToGlobal(position))

        if action == delete_action:
            self.delete_selected_preview_items()

    def delete_selected_preview_items(self):
        selected_items = self.preview_list_widget.selectedItems()
        if not selected_items:
            return

        indices_to_delete = sorted([item.data(Qt.ItemDataRole.UserRole) for item in selected_items], reverse=True)
        
        self.media_player.stop()
        self.media_player.setSource(QUrl())

        for index in indices_to_delete:
            try:
                item_data = self.subtitles_data.pop(index)
                media_path_str = item_data.get("media_file_path")

                if media_path_str:
                    media_path = Path(media_path_str)
                    srt_path = media_path.with_suffix('.srt')
                    
                    media_path.unlink(missing_ok=True)
                    srt_path.unlink(missing_ok=True)
                    self.log_message(f"Excluído: {media_path.name}")

            except (IndexError, Exception) as e:
                self.log_message(f"Erro ao excluir item no índice {index}: {e}")

        self.populate_preview_list()
        self.list_output_folder_files()

    def clear_all_generated_files(self):
        if not self.subtitles_data:
            return

        if not askUser(self.tr("preview.confirm.clear_all.message", count=len(self.subtitles_data)),
                       parent=self, title=self.tr("preview.confirm.clear_all.title")):
            return

        self.media_player.stop()
        self.media_player.setSource(QUrl())
        
        for item_data in self.subtitles_data:
            media_path_str = item_data.get("media_file_path")
            if media_path_str:
                try:
                    media_path = Path(media_path_str)
                    srt_path = media_path.with_suffix('.srt')
                    media_path.unlink(missing_ok=True)
                    srt_path.unlink(missing_ok=True)
                except Exception as e:
                    self.log_message(f"Não foi possível excluir {media_path_str}: {e}")
        
        self.subtitles_data = []
        self.populate_preview_list()
        self.list_output_folder_files()
        self.log_message("Todos os arquivos gerados foram limpos.")

    def change_playback_speed(self):
        index = self.speed_combo.currentIndex()
        self._save_config_value(self.CONFIG_KEY_PREVIEW_SPEED, index)

        current_item = self.preview_list_widget.currentItem()
        if current_item:
            self.on_preview_item_selected(current_item, None)

    def _play_media(self, path_str: str):
        self.media_player.stop()
        self.media_player.setSource(QUrl.fromLocalFile(path_str))
        self.media_player.play()

    def _create_speed_adjusted_media(self, input_path: str, rate: float, output_path: str):
        self.log_message(f"Criando versão com velocidade {rate}x para {Path(input_path).name}...")
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        
        try:
            cmd = [
                str(_FFMPEG_PATH), "-y", "-i", input_path,
                "-filter:a", f"atempo={rate}",
                "-vn", # Ignora o vídeo para processamento mais rápido
                output_path
            ]
            
            if Path(input_path).suffix.lower() in ['.mp4', '.webm', '.mkv', '.mov', '.avi']:
                cmd.pop() # remove output_path
                cmd.pop() # remove -vn
                cmd.extend(["-filter:v", f"setpts={1/rate}*PTS", output_path])

            subprocess.run(cmd, check=True, capture_output=True, text=True, startupinfo=self.startupinfo)
            self._play_media(output_path)
            self.log_message("Versão com velocidade alterada criada com sucesso.")
        except subprocess.CalledProcessError as e:
            self.log_message(f"Erro do FFmpeg ao alterar a velocidade: {e.stderr}")
            showError(f"Não foi possível alterar a velocidade do vídeo/áudio.\nErro: {e.stderr}", self)
        except Exception as e:
            self.log_message(f"Erro inesperado ao alterar a velocidade: {e}")
        finally:
            QApplication.restoreOverrideCursor()

    def toggle_playback(self):
        state = self.media_player.playbackState()
        if state == QMediaPlayer.PlaybackState.PlayingState:
            self.media_player.pause()
        else: # Paused or Stopped state
            if self.media_player.mediaStatus() == QMediaPlayer.MediaStatus.EndOfMedia:
                self.media_player.setPosition(0)
            self.media_player.play()

    def set_volume(self, value):
        volume = float(value) / 100
        if hasattr(self, 'audio_output') and self.audio_output:
            self.audio_output.setVolume(volume)

    def update_play_button_state(self, state):
        if state == QMediaPlayer.PlaybackState.PlayingState:
            self.play_pause_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPause))
        else:
            self.play_pause_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))

    def handle_media_status_changed(self, status):
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self.media_player.pause()

    def populate_preview_list(self) -> None:
        self.preview_list_widget.clear()
        
        has_items = False
        for i, item_data in enumerate(self.subtitles_data):
            media_path_str = item_data.get("media_file_path")
            if media_path_str and Path(media_path_str).is_file():
                has_items = True
                path = Path(media_path_str)
                list_item = QListWidgetItem(path.name)
                list_item.setData(Qt.ItemDataRole.UserRole, i) # Store index
                self.preview_list_widget.addItem(list_item)
        
        if not has_items:
            self.preview_list_widget.addItem(self.tr("preview.info.no_items"))
            self.on_preview_item_selected(None, None)

    def on_preview_item_selected_refresh(self):
        self.on_preview_item_selected(self.preview_list_widget.currentItem(), None)





    def on_preview_item_selected(self, current: Optional[QListWidgetItem], previous: Optional[QListWidgetItem]) -> None:
        if previous:
            try:
                shutil.rmtree(self.temp_preview_dir)
                self.temp_preview_dir.mkdir(exist_ok=True)
            except Exception as e:
                self.log_message(f"Não foi possível limpar o cache de pré-visualização: {e}")

        if not current:
            self.media_player.stop()
            self.subtitle_preview_area.setText(self.tr("preview.info.click_item"))
            return

        item_index = current.data(Qt.ItemDataRole.UserRole)
        if item_index is None:
            self.media_player.stop()
            self.subtitle_preview_area.setText(self.tr("preview.info.click_item"))
            return

        try:
            item_data = self.subtitles_data[item_index]
            original_path_str = item_data.get("media_file_path")
            subtitle_text = item_data.get("text", "")

            # --- INÍCIO DA CORREÇÃO ---
            # Lógica para exibir a legenda (com tradução opcional)
            display_html = f"<div style='font-size: 16px; text-align: center;'>{subtitle_text}</div>"
            if self.show_translation_cb.isChecked():
                translation_text = None
                # Busca a tradução pelo índice correspondente, que é mais robusto
                if self.translations_data and item_index < len(self.translations_data):
                    translation_text = self.translations_data[item_index].get('text')

                if translation_text:
                    display_html = (f"<div style='font-size: 14px; text-align: center;'>"
                                    f"{subtitle_text}<hr style='margin: 2px 20px;'>"
                                    f"<i>{translation_text}</i></div>")
            # --- FIM DA CORREÇÃO ---

            self.subtitle_preview_area.setHtml(display_html)

            # Lógica para tocar a mídia
            if original_path_str and Path(original_path_str).is_file():
                original_path = Path(original_path_str)
                speed_text = self.speed_combo.currentText()
                rate = 1.0
                if "0.5x" in speed_text: rate = 0.5
                elif "1.5x" in speed_text: rate = 1.5
                elif "2x" in speed_text: rate = 2.0

                if rate == 1.0:
                    self._play_media(original_path_str)
                else:
                    temp_filename = f"{original_path.stem}____{rate}x{original_path.suffix}"
                    temp_path = self.temp_preview_dir / temp_filename
                    
                    if temp_path.exists():
                        self._play_media(str(temp_path))
                    else:
                        self._create_speed_adjusted_media(original_path_str, rate, str(temp_path))
            else:
                self.media_player.stop()
                self.subtitle_preview_area.setText(f"Arquivo não encontrado: {original_path_str}")

        except IndexError:
            self.media_player.stop()
            self.subtitle_preview_area.setText("Erro: item não encontrado nos dados.")



    def _save_anki_export_settings(self):
        self._save_config_value(self.CONFIG_KEY_ANKI_DECK_NAME, self.deck_combo.currentText())
        self._save_config_value(self.CONFIG_KEY_ANKI_MODEL_NAME, self.note_type_combo.currentText())
        self._save_config_value(self.CONFIG_KEY_ANKI_FIELD_MEDIA, self.audio_field_combo.currentText())
        self._save_config_value(self.CONFIG_KEY_ANKI_FIELD_SUB, self.subtitle_field_combo.currentText())
        self._save_config_value(self.CONFIG_KEY_ANKI_FIELD_TRANS, self.translation_field_combo.currentText())
        self._save_config_value(self.CONFIG_KEY_ANKI_FIELD_IMG, self.image_field_combo.currentText())

    def _load_and_apply_anki_export_settings(self):
        last_deck = self._load_config_value(self.CONFIG_KEY_ANKI_DECK_NAME)
        if last_deck:
            index = self.deck_combo.findText(last_deck)
            if index != -1:
                self.deck_combo.setCurrentIndex(index)

        last_model = self._load_config_value(self.CONFIG_KEY_ANKI_MODEL_NAME)
        if last_model:
            index = self.note_type_combo.findText(last_model)
            if index != -1:
                self.note_type_combo.setCurrentIndex(index)
        
    def load_anki_options(self) -> None:
        if not mw or not mw.col: self.log_message(self.tr("anki_export.error.anki_collection_unavailable")); return
        
        try: self.deck_combo.currentIndexChanged.disconnect(self._save_anki_export_settings)
        except TypeError: pass
        try: self.note_type_combo.currentIndexChanged.disconnect(self._save_anki_export_settings)
        except TypeError: pass

        self.deck_combo.clear(); self.note_type_combo.clear()
        
        for deck_obj in mw.col.decks.all_names_and_ids(): self.deck_combo.addItem(deck_obj.name, deck_obj.id)
        for model_obj in mw.col.models.all_names_and_ids(): self.note_type_combo.addItem(model_obj.name, model_obj.id)
        
        self._load_and_apply_anki_export_settings()
        
        self.deck_combo.currentIndexChanged.connect(self._save_anki_export_settings)
        self.note_type_combo.currentIndexChanged.connect(self._save_anki_export_settings)

        self.update_anki_fields()

    def update_anki_fields(self) -> None:
        if not mw or not mw.col: return
        
        try: self.audio_field_combo.currentIndexChanged.disconnect(self._save_anki_export_settings)
        except TypeError: pass
        try: self.subtitle_field_combo.currentIndexChanged.disconnect(self._save_anki_export_settings)
        except TypeError: pass
        try: self.translation_field_combo.currentIndexChanged.disconnect(self._save_anki_export_settings)
        except TypeError: pass
        try: self.image_field_combo.currentIndexChanged.disconnect(self._save_anki_export_settings)
        except TypeError: pass

        combos_to_clear = [self.audio_field_combo, self.subtitle_field_combo, self.translation_field_combo, self.image_field_combo]
        for combo in combos_to_clear: combo.clear()
        
        model_id = self.note_type_combo.currentData()
        if model_id:
            model = mw.col.models.get(model_id)
            if model:
                field_names = mw.col.models.field_names(model)
                for combo in combos_to_clear: combo.addItems(field_names)
                
                field_map = {
                    self.audio_field_combo: self.CONFIG_KEY_ANKI_FIELD_MEDIA,
                    self.subtitle_field_combo: self.CONFIG_KEY_ANKI_FIELD_SUB,
                    self.translation_field_combo: self.CONFIG_KEY_ANKI_FIELD_TRANS,
                    self.image_field_combo: self.CONFIG_KEY_ANKI_FIELD_IMG,
                }
                for combo, key in field_map.items():
                    last_field = self._load_config_value(key)
                    if last_field:
                        index = combo.findText(last_field)
                        if index != -1:
                            combo.setCurrentIndex(index)

        self.audio_field_combo.currentIndexChanged.connect(self._save_anki_export_settings)
        self.subtitle_field_combo.currentIndexChanged.connect(self._save_anki_export_settings)
        self.translation_field_combo.currentIndexChanged.connect(self._save_anki_export_settings)
        self.image_field_combo.currentIndexChanged.connect(self._save_anki_export_settings)

    def log_message(self, message: str) -> None:
        full_message = f"[{time.strftime('%H:%M:%S')}] {message}"
        if hasattr(self, 'log_text_area') and self.log_text_area:
            self.log_text_area.append(full_message); self.log_text_area.ensureCursorVisible()
        else: print(full_message)

    def log_message_images_tab(self, message: str) -> None:
        full_message = f"[{time.strftime('%H:%M:%S')}] {message}"
        if hasattr(self, 'log_text_area_images') and self.log_text_area_images:
            self.log_text_area_images.append(full_message); self.log_text_area_images.ensureCursorVisible()
        else: print(f"(Log Imagens) {full_message}")

    def format_time(self, seconds: Optional[float]) -> str:
        if seconds is None or seconds < 0 or seconds == float('inf'): return self.tr("process.label.status_calculating") 
        if seconds < 60: return f"{int(seconds)}s"
        m, s = divmod(int(seconds), 60); h, m_rem = divmod(m, 60) 
        return f"{h}h {m_rem}m {s}s" if h else (f"{m_rem}m {s}s" if m_rem else f"{s}s")

    def select_media_file(self) -> None:
        current_media_path_in_entry = self.media_entry.text()
        start_dir = self.last_media_dir
        if current_media_path_in_entry:
            p_entry = Path(current_media_path_in_entry)
            if p_entry.is_file(): start_dir = str(p_entry.parent)
            elif p_entry.is_dir(): start_dir = str(p_entry)
            elif p_entry.parent.exists() and p_entry.parent.is_dir(): start_dir = str(p_entry.parent)

        filepath, _ = QFileDialog.getOpenFileName(self, self.tr("process.button.open_media"), start_dir, 
                                                  self.tr("process.label.media_file") + " (*.mp3 *.wav *.m4a *.ogg *.flac *.opus *.mp4 *.mkv *.avi *.mov *.webm *.ogv);;" + self.tr("all_files_filter"))
        if filepath:
            self.media_file_path_var = filepath; self.media_entry.setText(filepath)
            self.log_message(f"{self.tr('process.label.media_file')} {self.tr('selected_log_suffix')}: {filepath}")
            self.save_last_media_dir(str(Path(filepath).parent)); self.save_last_media_file(filepath)

            media_p = Path(filepath)
            possible_sub = media_p.with_suffix('.srt')
            if possible_sub.is_file():
                self.sub_entry.setText(str(possible_sub))
                self.log_message(f"{self.tr('process.label.main_subtitle')} {self.tr('auto_found_log_suffix')}: {possible_sub.name}")
                self.load_subtitles_from_file() 
            else:
                self.sub_entry.setText(""); self.subtitle_file_path_var = ""; self.save_last_subtitle_file(""); self.subtitles_data = []

            found_translation = False
            for trans_suffix_pattern in [f"{media_p.stem}_tr.srt", f"{media_p.stem}.tr.srt", f"{media_p.stem}_trad.srt", f"{media_p.stem}.trad.srt", f"{media_p.stem}.pt.srt", f"{media_p.stem}.en.srt", f"{media_p.stem}.es.srt"]:
                possible_trans = media_p.with_name(trans_suffix_pattern)
                if possible_trans.is_file():
                    self.translation_entry.setText(str(possible_trans))
                    self.log_message(f"{self.tr('process.label.translation_subtitle')} {self.tr('auto_found_log_suffix')}: {possible_trans.name}")
                    self.load_translations_from_file()
                    found_translation = True
                    break
            if not found_translation:
                self.translation_entry.setText(""); self.translation_file_path_var = ""; self.save_last_translation_file(""); self.translations_data = []

    def _select_srt_generic(self, entry_widget: QLineEdit, current_path_var_name: str, load_function: Any, save_function: Any, dialog_title_key: str, type_log_text_key: str) -> None:
        current_path_in_entry = entry_widget.text()
        start_dir = self.last_media_dir
        if current_path_in_entry:
            p_entry = Path(current_path_in_entry)
            if p_entry.is_file(): start_dir = str(p_entry.parent)
            elif p_entry.is_dir(): start_dir = str(p_entry)
            elif p_entry.parent.exists() and p_entry.parent.is_dir(): start_dir = str(p_entry.parent)
        
        filepath, _ = QFileDialog.getOpenFileName(self, self.tr(dialog_title_key), start_dir, 
                                                  "Arquivos de Legenda (*.srt *.vtt);;" + self.tr("all_files_filter"))
        if filepath:
            entry_widget.setText(filepath) 
            self.log_message(f"{self.tr(type_log_text_key).capitalize()} {self.tr('selected_log_suffix')}: {filepath}")
            load_function() 
            self.save_last_media_dir(str(Path(filepath).parent))

    def select_subtitle_file(self) -> None:
        self._select_srt_generic(
            self.sub_entry, "subtitle_file_path_var", 
            self.load_subtitles_from_file, self.save_last_subtitle_file,
            "process.button.open_subtitle", "process.label.main_subtitle" 
        )

    def select_translation_file(self) -> None:
        self._select_srt_generic(
            self.translation_entry, "translation_file_path_var",
            self.load_translations_from_file, self.save_last_translation_file,
            "process.button.open_translation", "process.label.translation_subtitle"
        )

    def load_subtitles_from_file(self) -> None:
        srt_path_str = self.sub_entry.text()
        self.subtitles_data = []
        if srt_path_str:
            srt_path = Path(srt_path_str)
            if srt_path.is_file():
                self.subtitles_data = parse_srt_file(str(srt_path), self.log_message, is_translation=False)
                if self.subtitles_data:
                    self.save_last_subtitle_file(str(srt_path)) 
            else: self.log_message(f"{self.tr('process.label.main_subtitle')} {self.tr('path_not_valid_log')}: '{srt_path_str}'")
        else: self.save_last_subtitle_file(""); 

    def load_translations_from_file(self) -> None:
        srt_path_str = self.translation_entry.text()
        self.translations_data = []
        if srt_path_str:
            srt_path = Path(srt_path_str)
            if srt_path.is_file():
                self.translations_data = parse_srt_file(str(srt_path), self.log_message, is_translation=True)
                if self.translations_data:
                    self.save_last_translation_file(str(srt_path)) 
                    if self.subtitles_data and abs(len(self.subtitles_data) - len(self.translations_data)) > max(5, len(self.subtitles_data) * 0.1) :
                        self.log_message(self.tr('subs_translation_count_mismatch_warning_log', 
                                                subs_count=len(self.subtitles_data), 
                                                trans_count=len(self.translations_data)))
            else: self.log_message(f"{self.tr('process.label.translation_subtitle')} {self.tr('path_not_valid_log')}: '{srt_path_str}'")
        else: self.save_last_translation_file("");

    def select_output_dir(self) -> None:
        start_dir = self.out_entry.text() or str(self.base_default_output_folder)
        dirpath = QFileDialog.getExistingDirectory(self, self.tr("process.button.select_output_folder"), start_dir)
        if dirpath:
            self.output_folder_path_var = dirpath; self.out_entry.setText(dirpath)
            self.log_message(f"{self.tr('process.label.output_folder_media')} {self.tr('set_to_log_suffix')}: {dirpath}")

    def select_anki_source_folder(self) -> None:
        start_dir = self.anki_source_folder_path_var or self.last_media_dir
        dirpath = QFileDialog.getExistingDirectory(self, self.tr("anki_export.button.select_source_folder"), start_dir)
        if dirpath:
            self.anki_source_folder_path_var = dirpath
            self.anki_source_folder_entry.setText(dirpath)
            self._save_config_value(self.CONFIG_KEY_ANKI_SOURCE_FOLDER, dirpath)
            self.log_message(f"{self.tr('anki_export.label.source_folder')} {self.tr('set_to_log_suffix')}: {dirpath}")
            self.list_output_folder_files()

    def clear_anki_source_folder(self) -> None:
        """Limpa a seleção da pasta de origem, a lista de arquivos e força a exibição vazia."""
        self.anki_source_folder_path_var = ""
        self.anki_source_folder_entry.clear()
        self._save_config_value(self.CONFIG_KEY_ANKI_SOURCE_FOLDER, "")
        
        # Força a limpeza da lista de arquivos para exportação e da exibição no log
        self.files_listed_for_anki_export = []
        self.folder_files_log.clear()
        
        self.log_message("Pasta de origem limpa. A lista de exportação está vazia.")
        # A chamada para self.list_output_folder_files() é removida intencionalmente
        # para que a lista permaneça vazia até que o usuário a popule novamente.

    def apply_time_offset_and_save_srt(self) -> None:
        if not self.subtitles_data:
            if self.sub_entry.text(): self.load_subtitles_from_file()
            if not self.subtitles_data: 
                QMessageBox.warning(self, self.tr("process.group.offset.title"), self.tr("process.dialog.offset_srt.no_subs_loaded"))
                return
        try: offset_s = float(self.offset_entry.text())
        except ValueError: 
            QMessageBox.critical(self, self.tr("general.error.title"), self.tr("process.dialog.offset_srt.invalid_offset_value"))
            return
        
        offset_ms = int(offset_s * 1000)
        action_desc_key = "process.dialog.offset_srt.action_unchanged"
        if offset_ms > 0: action_desc_key = "process.dialog.offset_srt.action_advanced"
        elif offset_ms < 0: action_desc_key = "process.dialog.offset_srt.action_delayed"
        action_desc = self.tr(action_desc_key)

        self.log_message(self.tr("applying_offset_log", offset_s=offset_s, offset_ms=offset_ms))
        new_subs_data = []
        for s_orig in self.subtitles_data:
            s = dict(s_orig)
            original_start = s['start_ms']; original_end = s['end_ms']
            original_duration = original_end - original_start
            if original_duration <= 0: original_duration = 1 
            s['start_ms'] = max(0, original_start + offset_ms)
            s['end_ms'] = s['start_ms'] + original_duration 
            new_subs_data.append(s)
        self.subtitles_data = new_subs_data

        output_srt_target_folder: Path
        if self.subtitle_file_path_var and Path(self.subtitle_file_path_var).is_file():
            output_srt_target_folder = Path(self.subtitle_file_path_var).parent
            self.log_message(self.tr("process.dialog.offset_srt.log_saving_to_original_folder", path=output_srt_target_folder))
        else:
            main_output_folder_str_ui = self.out_entry.text()
            if not main_output_folder_str_ui:
                main_output_folder_str_ui = str(self.base_default_output_folder)
                self.out_entry.setText(main_output_folder_str_ui)
                self.log_message(self.tr("process.log.using_default_output_folder", path=main_output_folder_str_ui) +
                                 self.tr("process.dialog.offset_srt.log_suffix_original_srt_undefined_fallback"))
            else:
                 self.log_message(self.tr("process.dialog.offset_srt.log_fallback_to_main_output", path=main_output_folder_str_ui))
            output_srt_target_folder = Path(main_output_folder_str_ui)
            showInfo(self.tr("process.dialog.offset_srt.info_fallback_to_main_output", path=str(output_srt_target_folder)),
                     parent=self, title=self.tr("general.info.title"))
        
        try: output_srt_target_folder.mkdir(parents=True,exist_ok=True)
        except Exception as e: 
            QMessageBox.critical(self, self.tr("general.error.title"), 
                                 self.tr("process.dialog.offset_srt.error_creating_folder", path=str(output_srt_target_folder), error=e)) 
            return

        base_name_for_adjusted_srt = self.tr("adjusted_subs_default_filename_stem")
        if self.subtitle_file_path_var and Path(self.subtitle_file_path_var).is_file():
            base_name_for_adjusted_srt = Path(self.subtitle_file_path_var).stem
        elif self.media_entry.text() and Path(self.media_entry.text()).is_file():
            base_name_for_adjusted_srt = Path(self.media_entry.text()).stem + "_" + self.tr("subs_filename_suffix")

        out_srt_path = output_srt_target_folder / f"{base_name_for_adjusted_srt}_{self.tr('adjusted_srt_filename_suffix')}.srt"
        ctr=1 
        while out_srt_path.exists():
            out_srt_path = output_srt_target_folder / f"{base_name_for_adjusted_srt}_{self.tr('adjusted_srt_filename_suffix')}_{ctr}.srt"
            ctr+=1

        try:
            composed_content = compose_srt(self.subtitles_data)
            with open(out_srt_path,'w',encoding='utf-8') as f:
                f.write(composed_content)
            self.log_message(self.tr("adjusted_subs_saved_log", path=str(out_srt_path)))
            self.sub_entry.setText(str(out_srt_path))
            self.save_last_subtitle_file(str(out_srt_path)) 
            QMessageBox.information(self, self.tr("process.dialog.offset_srt.success_title"),
                                    self.tr("process.dialog.offset_srt.success_message", action_desc=action_desc, path=str(out_srt_path)))
        except Exception as e:
            QMessageBox.critical(self, self.tr("process.dialog.offset_srt.error_saving_title"),
                                 self.tr("process.dialog.offset_srt.error_saving_message", error=e))




    def list_output_folder_files(self) -> None:
        self.folder_files_log.clear()
        self.files_listed_for_anki_export = [] # Limpa a lista para exportação
        files_to_list: List[Path] = []
        source_description = ""
        header_text = ""

        use_folder_mode = self.anki_use_folder_cb.isChecked()

        # Prioridade 1: Pasta selecionada manualmente na aba Anki, se o modo estiver ativo
        if use_folder_mode and self.anki_source_folder_path_var and Path(self.anki_source_folder_path_var).is_dir():
            source_folder = Path(self.anki_source_folder_path_var)
            source_description = self.tr("anki_export.log.source.folder")
            
            # --- INÍCIO DA ALTERAÇÃO ---
            # Trocado iterdir() por rglob('*') para buscar recursivamente em subpastas
            files_to_list = sorted([f for f in source_folder.rglob('*') if f.is_file() and f.suffix.lower() in ['.mp3', '.mp4', '.webm']], key=lambda x: x.name)
            # --- FIM DA ALTERAÇÃO ---

            header_text = self.tr("media_files_in_folder_log_header", path=str(source_folder), count=len(files_to_list))
            if not files_to_list:
                self.folder_files_log.setText(self.tr("anki_export.log.no_media_files_found", path=str(source_folder)))
                return

        # Prioridade 2: Arquivos processados na sessão atual (modo padrão)
        else:
            source_description = self.tr("anki_export.log.source.session")
            if not self.subtitles_data:
                self.folder_files_log.setText(self.tr("anki_export.log.no_subtitles_loaded_for_listing"))
                return

            processed_files_in_session: List[Path] = []
            for s_data in self.subtitles_data:
                media_file_path_str = s_data.get('media_file_path')
                if media_file_path_str and Path(media_file_path_str).is_file():
                    processed_files_in_session.append(Path(media_file_path_str))
            
            if not processed_files_in_session:
                self.folder_files_log.setText(self.tr("anki_export.log.no_media_files_processed_in_session"))
                return

            files_to_list = sorted(processed_files_in_session, key=lambda x: x.name)
            folder_path = str(files_to_list[0].parent) if files_to_list else "N/A"
            header_text = self.tr("anki_export.log.processed_media_files_header", folder_path=folder_path, count=len(files_to_list))

        self.files_listed_for_anki_export = files_to_list # Armazena a lista de arquivos
        self.folder_files_log.setText(header_text + "\n".join([f.name for f in files_to_list]))
        self.log_message(self.tr("anki_export.log.files_listed_for_export", count=len(files_to_list), source=source_description))









    def _set_ui_state_for_long_operation(self, is_operating: bool, operation_type: str) -> None:
        self.split_button.setEnabled(not is_operating or operation_type != "split")
        self.stop_button.setEnabled(is_operating and (operation_type == "split" or operation_type == "generation"))

        self.convert_videos_button.setEnabled(not is_operating or operation_type != "image_conversion")
        self.generate_from_source_button.setEnabled(not is_operating or operation_type != "image_conversion")
        self.stop_image_conversion_button.setEnabled(is_operating and operation_type == "image_conversion")
        
        self.btn_generate_subs.setEnabled(not is_operating or operation_type != "generation")
        
        self.add_to_anki_button.setEnabled(not is_operating)

        self.direct_to_media_collection_cb_process.setEnabled(not is_operating)
        self.direct_to_media_collection_cb_images.setEnabled(not is_operating)
        self.language_combo.setEnabled(not is_operating)

        read_only_widgets_base = [self.media_entry, self.sub_entry, self.translation_entry, self.offset_entry, self.api_key_entry]
        
        if self.direct_to_media_collection_cb_process.isChecked():
            self.out_entry.setReadOnly(True)
            self.btn_select_out_process.setEnabled(False)
        else: 
            self.out_entry.setReadOnly(is_operating)
            self.btn_select_out_process.setEnabled(not is_operating)

        for widget in read_only_widgets_base: widget.setReadOnly(is_operating)
        enabled_widgets = [self.output_format_combo, self.transcription_lang_combo, self.translation_lang_combo] 
        for widget in enabled_widgets: widget.setEnabled(not is_operating)
        if self.btn_apply_offset_process: self.btn_apply_offset_process.setEnabled(not is_operating)

        if is_operating:
            if operation_type == "split":
                self.speed_samples = []
                self._update_progress_display(0, self.tr("process_starting_status"), 0, 0)
            elif operation_type == "image_conversion":
                self._update_image_conversion_progress_display(0, self.tr("image_conversion_starting_status"), 0)
            elif operation_type == "generation":
                self._update_progress_display(0, self.tr("transcription.starting_status"), 0, 0)
                self.progress_bar.setRange(0, 0)
        else:
            self.progress_bar.setRange(0, 100)
            
        QApplication.processEvents()













    def start_split_media_process(self) -> None:
        self.images_generated_in_this_session = False
        # --- INÍCIO DA CORREÇÃO ---
        # Limpa os caminhos de arquivos de mídia da operação de divisão anterior.
        # Isso garante que apenas os arquivos da nova operação sejam considerados "da sessão atual".
        self.log_message("Limpando referências de arquivos de mídia da divisão anterior...")
        for item in self.subtitles_data:
            if 'media_file_path' in item:
                del item['media_file_path']
        # --- FIM DA CORREÇÃO ---

        if self.processing_thread and self.processing_thread.is_alive(): 
            QMessageBox.warning(self, self.tr("general.warning.title"), self.tr("process.warning.process_running")); return
        if self.single_clip_thread and self.single_clip_thread.is_alive():
            QMessageBox.warning(self, self.tr("general.warning.title"), self.tr("process.warning.process_running")); return

        media_path = self.media_entry.text(); chosen_format_text = self.output_format_combo.currentText()
        if not _FFMPEG_PATH: 
            showError(self.tr("process.info.ffmpeg_not_found"), parent=self); self.log_message(self.tr("process.info.ffmpeg_not_found")); return
        
        if not media_path or not Path(media_path).is_file(): 
            QMessageBox.critical(self, self.tr("general.error.title"), self.tr("process.error.invalid_media_file")); return
        if not self.subtitles_data:
            if self.sub_entry.text(): self.load_subtitles_from_file()
            if not self.subtitles_data: 
                QMessageBox.critical(self, self.tr("general.error.title"), self.tr("process.error.no_main_subtitle")); return

        output_dir_str = self.out_entry.text() 
        if not output_dir_str: 
            output_dir_str = str(self.base_default_output_folder)
            self.out_entry.setText(output_dir_str)
            self.log_message(self.tr("process.log.using_default_output_folder", path=output_dir_str))

        output_dir_split = Path(output_dir_str)
        try: output_dir_split.mkdir(parents=True, exist_ok=True)
        except Exception as e: 
            QMessageBox.critical(self, self.tr("general.error.title"), 
                                 self.tr("process.error.output_folder_invalid", path=str(output_dir_split), error=e)); return

        file_ext = "mp4" 
        if self.tr("process.format.mp3") in chosen_format_text: file_ext = "mp3"
        elif self.tr("process.format.webm") in chosen_format_text: file_ext = "webm"
        elif self.tr("process.format.mp4") in chosen_format_text: file_ext = "mp4"
        
        subs_to_process = self.subtitles_data
        if self.limit_time_range_cb.isChecked():
            start_time_ms = self._parse_simple_time_to_ms(self.start_time_entry.text())
            end_time_ms = self._parse_simple_time_to_ms(self.end_time_entry.text())
            
            if end_time_ms > start_time_ms:
                original_count = len(subs_to_process)
                subs_to_process = [
                    s for s in subs_to_process 
                    if s['start_ms'] >= start_time_ms and s['end_ms'] <= end_time_ms
                ]
                self.log_message(self.tr("process.log.time_limit_applied", 
                                         count=len(subs_to_process), 
                                         total=original_count,
                                         start=self.start_time_entry.text(),
                                         end=self.end_time_entry.text()))

        self.stop_requested_event.clear()
        self._set_ui_state_for_long_operation(True, "split")
        self.log_message(self.tr("process.log.split_started", format=file_ext, count=len(subs_to_process)))
        thread_subs_data = [dict(s) for s in subs_to_process]
        self.processing_thread = threading.Thread(target=self._perform_media_split_to_files, args=(media_path, output_dir_split, thread_subs_data, file_ext), daemon=True)
        self.processing_thread.start()























    def _perform_media_split_to_files(self, media_fpath_str: str, output_folder: Path, current_subs_data: List[Dict[str,Any]], file_ext: str) -> None:
        if not _FFMPEG_PATH: 
            self.progress_signal.log.emit("CRITICAL: FFmpeg path not set in thread.") 
            self.progress_signal.finalize.emit([], 0, len(current_subs_data), output_folder)
            return

        media_file = Path(media_fpath_str)
        updated_main_subtitles_data: List[Dict[str, Any]] = []
        total_subs = len(current_subs_data)
        files_created = 0
        start_time_proc = time.time()

        for s_info in current_subs_data: s_info['_processed_marker'] = False
        self.progress_signal.update_progress.emit(0, self.tr("preparing_items_status", count=total_subs), total_subs, 0)

        for i, sub_info_original in enumerate(current_subs_data):
            sub_info = dict(sub_info_original)
            sub_info['_processed_marker'] = True
            
            subtitle_id = sub_info['id'] if sub_info.get('id') is not None else i + 1
            
            if self.stop_requested_event.is_set():
                self.progress_signal.log.emit(self.tr("split_interrupted_log"))
                remaining_unprocessed = [dict(s) for s in current_subs_data[i:]]
                for s_rem in remaining_unprocessed: s_rem['_processed_marker'] = False 
                updated_main_subtitles_data.extend(remaining_unprocessed)
                break 
            
            current_progress_val = i + 1
            elapsed_time = time.time() - start_time_proc
            percentage = int((current_progress_val / total_subs) * 100) if total_subs > 0 else 0
            
            status_text = self.tr("processing_item_status", current=current_progress_val, total=total_subs, id=subtitle_id, percent=percentage)
            self.progress_signal.update_progress.emit(current_progress_val, status_text, total_subs, elapsed_time)

            start_ms, end_ms, text = sub_info['start_ms'], sub_info['end_ms'], sub_info['text']

            if not text.strip() or start_ms >= end_ms:
                self.progress_signal.log.emit(self.tr("skipped_item_log", id=subtitle_id))
                updated_main_subtitles_data.append(sub_info)
                continue
            
            base_fname = f"{subtitle_id:04d}-{sanitize_filename(text)}"
            out_fname = f"{base_fname}.{file_ext}"
            out_fpath = output_folder / out_fname
            counter = 1
            while out_fpath.exists(): 
                out_fname = f"{base_fname}_{counter}.{file_ext}"
                out_fpath = output_folder / out_fname
                counter += 1
            
            success_this_segment = False
            ffmpeg_start_time = ms_to_ffmpeg_time(start_ms)
            duration_sec = (end_ms - start_ms) / 1000.0
            if duration_sec <= 0: duration_sec = 0.1

            base_ffmpeg_cmd_list = [str(_FFMPEG_PATH), "-y", "-hide_banner", "-loglevel", "error", 
                                    "-i", str(media_file), 
                                    "-ss", ffmpeg_start_time, "-t", str(duration_sec)]
            
            output_params_list: List[str] = []
            
            # --- INÍCIO DA ALTERAÇÃO ---
            if file_ext == "mp4":
                self.progress_signal.log.emit(self.tr("reencoding_to_mp4_log", id=subtitle_id, filename=out_fname))
                output_params_list = [
                    "-vf", "setpts=PTS-STARTPTS", "-af", "asetpts=PTS-STARTPTS", # <-- CORREÇÃO DEFINITIVA
                    "-c:v", "libx264", "-preset", "fast", "-crf", "23",  
                    "-c:a", "aac", "-b:a", "128k",                      
                    "-map_metadata", "-1",
                    str(out_fpath)
                ]
            elif file_ext == "mp3":
                output_params_list = [
                    "-vn",                                              
                    "-c:a", "libmp3lame", "-q:a", "2",                
                    "-map_metadata", "-1",
                    str(out_fpath)
                ]
            elif file_ext == "webm": 
                self.progress_signal.log.emit(self.tr("reencoding_to_webm_log", id=subtitle_id, filename=out_fname))
                output_params_list = [
                    "-vf", "setpts=PTS-STARTPTS", "-af", "asetpts=PTS-STARTPTS", # <-- CORREÇÃO DEFINITIVA
                    "-c:v", "libvpx-vp9", "-crf", "30", "-b:v", "0", 
                    "-c:a", "libopus", "-b:a", "96k",                
                    "-map_metadata", "-1",
                    str(out_fpath)
                ]
            # --- FIM DA ALTERAÇÃO ---
            else:
                self.progress_signal.log.emit(self.tr("unsupported_ext_for_split_log", ext=file_ext))
                updated_main_subtitles_data.append(sub_info) 
                continue 

            final_ffmpeg_cmd_list = base_ffmpeg_cmd_list + output_params_list

            if final_ffmpeg_cmd_list:
                try:
                    process = subprocess.run(final_ffmpeg_cmd_list, check=True, capture_output=True, text=True, startupinfo=self.startupinfo, encoding='utf-8', errors='replace')
                    success_this_segment = True
                except subprocess.CalledProcessError as e:
                    stderr_msg = e.stderr.strip() if e.stderr else 'N/A'
                    self.progress_signal.log.emit(self.tr("ffmpeg_error_log", id=subtitle_id, ext=file_ext.upper(), filename=out_fname, stderr=stderr_msg))
                    if file_ext in ["mp4", "webm"]:
                         self.progress_signal.log.emit(self.tr("ffmpeg_reencode_fail_warning_log", ext=file_ext.upper(), id=subtitle_id))
                except Exception as e_gen:
                     self.progress_signal.log.emit(self.tr("ffmpeg_general_error_log", id=subtitle_id, ext=file_ext.upper(), error=str(e_gen)))
            
            if success_this_segment:
                sub_info['media_file_path'] = str(out_fpath)
                files_created += 1

                try:
                    clip_sub_data = {
                        'id': 1,
                        'start_ms': 0,
                        'end_ms': end_ms - start_ms,
                        'text': sub_info['text']
                    }
                    srt_content = compose_srt([clip_sub_data])
                    srt_fpath = out_fpath.with_suffix('.srt')
                    with open(srt_fpath, 'w', encoding='utf-8') as f:
                        f.write(srt_content)
                    
                    self.progress_signal.log.emit(self.tr("file_and_srt_created_success_log", filename=out_fname))

                except Exception as e:
                    self.progress_signal.log.emit(self.tr("file_created_success_log", filename=out_fname))
                    self.progress_signal.log.emit(self.tr("process.log.srt_creation_failed", id=subtitle_id, error=str(e)))
            
            updated_main_subtitles_data.append(sub_info) 
        
        self.progress_signal.finalize.emit(updated_main_subtitles_data, files_created, total_subs, output_folder)












    def start_video_to_image_conversion(self) -> None:
        if not _FFMPEG_PATH:
            showError(self.tr("process.info.ffmpeg_not_found"), parent=self)
            self.log_message_images_tab(self.tr("process.info.ffmpeg_not_found")); return

        video_files: List[Path] = []

        if not self.subtitles_data:
            msg = self.tr("images.info.no_subtitles_data_for_videos")
            showInfo(msg, parent=self)
            self.log_message_images_tab(msg)
            return

        for s_data in self.subtitles_data:
            media_file_path_str = s_data.get('media_file_path')
            if media_file_path_str:
                media_path = Path(media_file_path_str)
                if media_path.is_file() and media_path.suffix.lower() in ['.mp4', '.webm']:
                    video_files.append(media_path)
        
        if not video_files:
            msg = self.tr("images.info.no_valid_videos_from_processing", 
                          source=self.tr("images.source_description.processed_items"))
            showInfo(msg, parent=self)
            self.log_message_images_tab(msg)
            return

        try:
            self.images_output_folder.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            showError(self.tr("images.error.cannot_create_images_folder", path=str(self.images_output_folder), error=e), parent=self)
            self.log_message_images_tab(self.tr("images.error.cannot_create_images_folder", path=str(self.images_output_folder), error=e)); return

        self.stop_image_conversion_event.clear()
        self._set_ui_state_for_long_operation(True, "image_conversion")
        self.log_message_images_tab(self.tr("images.log.conversion_started_from_processed",
                                            count=len(video_files), 
                                            path=str(self.images_output_folder)))
        self.image_conversion_thread = threading.Thread(target=self._perform_video_to_image_conversion, args=(video_files, self.images_output_folder), daemon=True)
        self.image_conversion_thread.start()

    def _perform_video_to_image_conversion(self, video_files: List[Path], images_out_folder: Path) -> None:
        if not _FFMPEG_PATH: 
            self.image_conversion_signal.log.emit("CRITICAL: FFmpeg path not set in image conversion thread.") 
            self.image_conversion_signal.finalize_conversion.emit(0, len(video_files))
            return

        total_videos = len(video_files); images_created_count = 0
        self.image_conversion_signal.update_conversion_progress.emit(0, self.tr("preparing_videos_status", count=total_videos), total_videos)
        for i, video_path in enumerate(video_files):
            if self.stop_image_conversion_event.is_set():
                self.image_conversion_signal.log.emit(self.tr("image_conversion_interrupted_log")); break
            current_val = i + 1
            status_text = self.tr("converting_video_status", filename=video_path.name, current=current_val, total=total_videos)
            self.image_conversion_signal.update_conversion_progress.emit(current_val, status_text, total_videos)
            image_filename = video_path.stem + ".jpg"
            image_output_path = images_out_folder / image_filename
            cmd = [str(_FFMPEG_PATH), "-y", "-hide_banner", "-loglevel", "error", 
                   "-i", str(video_path), 
                   "-ss", "00:00:01.000", "-frames:v", "1", "-q:v", "2", 
                   str(image_output_path)]
            try:
                process = subprocess.run(cmd, check=True, capture_output=True, text=True, startupinfo=self.startupinfo, encoding='utf-8', errors='replace')
                if image_output_path.exists() and image_output_path.stat().st_size > 0:
                    self.image_conversion_signal.log.emit(self.tr("image_created_success_log", filename=image_filename))
                    images_created_count += 1
                else:
                    err_msg_base = self.tr("ffmpeg_run_but_image_not_created_log", filename=image_filename)
                    if process.stderr: err_msg_base += f" FFmpeg stderr: {process.stderr.strip()}"
                    self.image_conversion_signal.log.emit(err_msg_base)
            except subprocess.CalledProcessError as e:
                err_msg_base = self.tr("ffmpeg_error_converting_image_log", filename=video_path.name)
                if e.stderr: err_msg_base += f": {e.stderr.strip()}"
                else: err_msg_base += f": {e}"
                self.image_conversion_signal.log.emit(err_msg_base)
            except Exception as e_gen:
                self.image_conversion_signal.log.emit(self.tr("general_error_converting_image_log", filename=video_path.name, error=str(e_gen)))
        self.image_conversion_signal.finalize_conversion.emit(images_created_count, total_videos)

    def start_image_generation_from_source(self) -> None:
        if not _FFMPEG_PATH:
            showError(self.tr("process.info.ffmpeg_not_found"), parent=self)
            self.log_message_images_tab(self.tr("process.info.ffmpeg_not_found")); return

        source_video_path = self.media_entry.text()
        if not source_video_path or not Path(source_video_path).is_file():
            showError(self.tr("process.error.invalid_media_file"), parent=self)
            return
        
        if not self.subtitles_data:
            showError(self.tr("process.error.no_main_subtitle"), parent=self)
            return

        try:
            self.images_output_folder.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            showError(self.tr("images.error.cannot_create_images_folder", path=str(self.images_output_folder), error=e), parent=self)
            self.log_message_images_tab(self.tr("images.error.cannot_create_images_folder", path=str(self.images_output_folder), error=e)); return

        self.stop_image_conversion_event.clear()
        self._set_ui_state_for_long_operation(True, "image_conversion")
        self.log_message_images_tab(self.tr("images.log.generation_from_source_started", count=len(self.subtitles_data)))
        
        subs_data_copy = [dict(s) for s in self.subtitles_data]
        self.image_conversion_thread = threading.Thread(
            target=self._perform_image_generation_from_source, 
            args=(source_video_path, subs_data_copy, self.images_output_folder), 
            daemon=True
        )
        self.image_conversion_thread.start()

    def _perform_image_generation_from_source(self, source_video_path: str, subtitles_data: List[Dict[str, Any]], images_out_folder: Path) -> None:
        if not _FFMPEG_PATH:
            self.image_conversion_signal.log.emit("CRITICAL: FFmpeg path not set in image generation thread.")
            self.image_conversion_signal.finalize_conversion.emit(0, len(subtitles_data))
            return

        total_subs = len(subtitles_data)
        images_created_count = 0
        self.image_conversion_signal.update_conversion_progress.emit(0, self.tr("preparing_subtitles_status", count=total_subs), total_subs)

        for i, sub_info in enumerate(subtitles_data):
            if self.stop_image_conversion_event.is_set():
                self.image_conversion_signal.log.emit(self.tr("image_conversion_interrupted_log"))
                break
            
            current_val = i + 1
            status_text = self.tr("generating_image_from_source_status", current=current_val, total=total_subs)
            self.image_conversion_signal.update_conversion_progress.emit(current_val, status_text, total_subs)

            subtitle_id = sub_info.get('id', i + 1)
            text = sub_info.get('text', '')
            start_ms = sub_info.get('start_ms', 0)
            
            timestamp_str = ms_to_ffmpeg_time(start_ms)
            
            base_fname = f"{subtitle_id:04d}-{sanitize_filename(text)}"
            image_filename = f"{base_fname}.jpg"
            image_output_path = images_out_folder / image_filename
            
            cmd = [
                str(_FFMPEG_PATH), "-y", "-hide_banner", "-loglevel", "error",
                "-ss", timestamp_str,
                "-i", source_video_path,
                "-vframes", "1",
                "-q:v", "2",
                str(image_output_path)
            ]
            
            try:
                process = subprocess.run(cmd, check=True, capture_output=True, text=True, startupinfo=self.startupinfo, encoding='utf-8', errors='replace')
                if image_output_path.exists() and image_output_path.stat().st_size > 0:
                    self.image_conversion_signal.log.emit(self.tr("image_created_success_log", filename=image_filename))
                    images_created_count += 1
                else:
                    err_msg_base = self.tr("ffmpeg_run_but_image_not_created_log", filename=image_filename)
                    if process.stderr: err_msg_base += f" FFmpeg stderr: {process.stderr.strip()}"
                    self.image_conversion_signal.log.emit(err_msg_base)
            except subprocess.CalledProcessError as e:
                err_msg_base = self.tr("ffmpeg_error_converting_image_log", filename=Path(source_video_path).name)
                if e.stderr: err_msg_base += f": {e.stderr.strip()}"
                else: err_msg_base += f": {e}"
                self.image_conversion_signal.log.emit(err_msg_base)
            except Exception as e_gen:
                self.image_conversion_signal.log.emit(self.tr("general_error_converting_image_log", filename=Path(source_video_path).name, error=str(e_gen)))

        self.image_conversion_signal.finalize_conversion.emit(images_created_count, total_subs)

    def _update_progress_display(self, value: int, text_status: str, total_items: Optional[int]=None, elapsed_time: Optional[float]=None) -> None:
        self.status_label.setText(text_status)
        if self.progress_bar.minimum() == 0 and self.progress_bar.maximum() == 0:
            return
            
        percentage = int((value / total_items) * 100) if total_items and total_items > 0 else 0
        self.progress_bar.setValue(percentage); self.progress_label.setText(f"{percentage}%")
        if elapsed_time is not None and elapsed_time > 0 and value > 0 and total_items and total_items > 0 :
            speed = value / elapsed_time; self.speed_samples.append(speed)
            if len(self.speed_samples) > self.max_samples: self.speed_samples.pop(0)
            avg_speed = sum(self.speed_samples) / len(self.speed_samples) if self.speed_samples else 0
            time_rem_str = self.format_time( (total_items - value) / avg_speed) if avg_speed > 0 else self.tr("process.label.status_calculating")
            self.time_label.setText(f"{self.tr('process.label.time_remaining_prefix')} {time_rem_str}")
        else: 
            prefix = self.tr('process.label.time_remaining_prefix')
            status_val = self.tr('general.na_value') if (total_items is not None and value == total_items) or not total_items else self.tr("process.label.status_calculating")
            self.time_label.setText(f"{prefix} {status_val}")
    
    def _update_image_conversion_progress_display(self, value: int, status_text: str, total_items: int) -> None:
        self.image_conversion_status_label.setText(status_text)
        percentage = int((value / total_items) * 100) if total_items > 0 else 0
        self.image_conversion_progress_bar.setValue(percentage)
        self.image_conversion_progress_label.setText(f"{percentage}%")

    def _update_transcription_status_display(self, status_text: str):
        self.status_label.setText(status_text)

    def _finalize_processing(self, updated_subs_data_from_thread: List[Dict[str, Any]], files_created: int, total_subs_initial: int, output_folder_path: Path) -> None:
        processed_ids = {item['id'] for item in updated_subs_data_from_thread}
        
        final_subs_data = [item for item in self.subtitles_data if item['id'] not in processed_ids]
        final_subs_data.extend(updated_subs_data_from_thread)
        final_subs_data.sort(key=lambda x: x['id'])
        self.subtitles_data = final_subs_data

        status_op_key = "op_interrupted_status" if self.stop_requested_event.is_set() else "op_completed_status"
        final_msg_prefix = self.tr("split_finalize_prefix", status=self.tr(status_op_key))

        self.log_message(f"\n{final_msg_prefix} {self.tr('files_created_log_suffix', count=files_created)}")
        
        items_attempted = sum(1 for s_data in updated_subs_data_from_thread if s_data.get('_processed_marker', False))
        current_progress_val_at_end = items_attempted if self.stop_requested_event.is_set() else total_subs_initial
        if total_subs_initial == 0: current_progress_val_at_end = 0
        
        final_percentage = int((current_progress_val_at_end / total_subs_initial) * 100) if total_subs_initial > 0 else 0
        
        status_text = self.tr("split_finalize_detailed_status", prefix=final_msg_prefix, files_count=files_created, items_attempted=items_attempted, total_initial=total_subs_initial, percent=final_percentage)
        
        if not self.stop_requested_event.is_set() and files_created == total_subs_initial and total_subs_initial > 0: 
            status_text = self.tr("split_finalize_all_created_status", prefix=final_msg_prefix, count=files_created)
        
        self._update_progress_display(current_progress_val_at_end, status_text, total_subs_initial, None)
        
        if not self.stop_requested_event.is_set():
            if files_created > 0: 
                showInfo(self.tr("split_finalize_showInfo_success", prefix=final_msg_prefix, count=files_created, path=str(output_folder_path)), parent=self, title=self.tr("general.info.title"))
            elif total_subs_initial > 0: 
                showInfo(self.tr("split_finalize_showInfo_no_files", prefix=final_msg_prefix), parent=self, title=self.tr("general.info.title"))
        
        self._set_ui_state_for_long_operation(False, "split")
        self.processing_thread = None; self.stop_requested_event.clear()
        self.list_output_folder_files() 
        self.populate_preview_list()
        self.log_message(status_text)
        self.status_label.setText(self.tr("process.label.status_ready"))
        self.time_label.setText(f"{self.tr('process.label.time_remaining_prefix')} {self.tr('general.na_value')}")




    def _finalize_image_conversion(self, images_created: int, total_videos: int) -> None:
        status_op_key = "op_interrupted_status" if self.stop_image_conversion_event.is_set() else "op_completed_status"
        final_msg_prefix_base = self.tr("image_conversion_finalize_prefix", status=self.tr(status_op_key))
        
        final_log_msg = self.tr("image_conversion_finalize_log", prefix=final_msg_prefix_base, created_count=images_created, total_count=total_videos)
        self.image_conversion_signal.log.emit(final_log_msg)

        self._set_ui_state_for_long_operation(False, "image_conversion")
        self.image_conversion_thread = None
        self.stop_image_conversion_event.clear()

        status_text_ui = self.tr("image_conversion_finalize_status_ui", prefix=final_msg_prefix_base, count=images_created)
        progress_val_at_end = total_videos if not self.stop_image_conversion_event.is_set() else self.image_conversion_progress_bar.value() 

        self._update_image_conversion_progress_display(progress_val_at_end, status_text_ui, total_videos)

        if not self.stop_image_conversion_event.is_set():
            QTimer.singleShot(2000, lambda: self.image_conversion_status_label.setText(self.tr("images.label.status_ready")))
            if images_created > 0:
                # --- CORREÇÃO AQUI ---
                # A linha deve ser colocada dentro do if, com a indentação correta.
                self.images_generated_in_this_session = True
                # --- FIM DA CORREÇÃO ---

                showInfo(self.tr("images.finalize.info_success", status_text=status_text_ui, path=str(self.images_output_folder)), parent=self, title=self.tr("general.info.title"))
            elif total_videos > 0 :
                 showInfo(self.tr("images.finalize.info_no_images", status_text=status_text_ui), parent=self, title=self.tr("general.info.title"))







    def _finalize_transcription(self, generated_srt_path: str, translated_srt_path: Optional[str]):
        status_op_key = "op_interrupted_status" if self.stop_transcription_event.is_set() else "op_completed_status"
        final_msg_prefix = self.tr("transcription.finalize_prefix", status=self.tr(status_op_key))

        success = False
        info_message = f"{final_msg_prefix}\n"

        if generated_srt_path:
            self.log_message(f"Legenda original salva em: {generated_srt_path}")
            self.sub_entry.setText(generated_srt_path)
            self.load_subtitles_from_file()
            info_message += f"\nLegenda gerada:\n{generated_srt_path}"
            success = True

        if translated_srt_path:
            self.log_message(f"Tradução salva em: {translated_srt_path}")
            self.translation_entry.setText(translated_srt_path)
            self.load_translations_from_file()
            info_message += f"\n\nTradução gerada:\n{translated_srt_path}"
            success = True

        if success:
            showInfo(info_message, parent=self)
        else:
            showInfo(self.tr("transcription.finalize_showInfo_fail", prefix=final_msg_prefix), parent=self)

        self._set_ui_state_for_long_operation(False, "generation")
        self.transcription_thread = None
        self.stop_transcription_event.clear()
        self.status_label.setText(self.tr("process.label.status_ready"))

    def request_stop_processing(self) -> None:
        if self.processing_thread and self.processing_thread.is_alive():
            self.log_message(self.tr("general.log.stop_requested_generic", operation_name=self.tr("general.log.op_name_split")))
            self.stop_requested_event.set()
            self.status_label.setText(self.tr("process.status.stopping")); self.stop_button.setEnabled(False)
        elif self.transcription_thread and self.transcription_thread.is_alive():
            self.log_message(self.tr("general.log.stop_requested_generic", operation_name=self.tr("general.log.op_name_generation")))
            self.stop_transcription_event.set()
            self.status_label.setText(self.tr("process.status.generating_stopping")); self.stop_button.setEnabled(False)

    def request_stop_image_conversion(self) -> None:
        if self.image_conversion_thread and self.image_conversion_thread.is_alive():
            self.log_message_images_tab(self.tr("general.log.stop_requested_generic", operation_name=self.tr("general.log.op_name_images")))
            self.stop_image_conversion_event.set()
            self.image_conversion_status_label.setText(self.tr("images.status.stopping"))
            self.stop_image_conversion_button.setEnabled(False)

    def start_transcription_process(self) -> None:
        api_key = self.api_key_entry.text().strip()
        media_path = self.media_entry.text()
        
        if self.transcription_thread and self.transcription_thread.is_alive():
            QMessageBox.warning(self, self.tr("general.warning.title"), self.tr("process.warning.generation_running"))
            return

        output_dir_str = self.out_entry.text() or str(self.base_default_output_folder)
        output_dir = Path(output_dir_str)
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            QMessageBox.critical(self, self.tr("general.error.title"), self.tr("process.error.output_folder_invalid", path=str(output_dir), error=e))
            return

        generate_translation = self.generate_translation_cb.isChecked()
        
        if media_path and Path(media_path).is_file():
            if not api_key:
                QMessageBox.critical(self, self.tr("general.error.title"), self.tr("process.error.api_key_needed"))
                return

            lang_text = self.transcription_lang_combo.currentText()
            lang_code = "pt" if lang_text == "Português" else "en"
            target_translation_lang = ""
            if generate_translation:
                target_lang_text = self.translation_lang_combo.currentText()
                target_translation_lang = "pt" if target_lang_text == "Português" else "en"

            self.stop_transcription_event.clear()
            self._set_ui_state_for_long_operation(True, "generation")
            self.log_message(self.tr("process.log.generation_started"))
            
            self.transcription_thread = threading.Thread(
                target=self._perform_transcription,
                args=(media_path, output_dir, api_key, lang_code, generate_translation, target_translation_lang),
                daemon=True
            )
            self.transcription_thread.start()

        elif not (media_path and Path(media_path).is_file()) and self.subtitles_data and generate_translation:
            self.log_message("Nenhum arquivo de mídia detectado. Iniciando tradução da legenda carregada...")
            
            target_lang_text = self.translation_lang_combo.currentText()
            target_translation_lang = "pt" if target_lang_text == "Português" else "en"
            
            self.stop_transcription_event.clear()
            self._set_ui_state_for_long_operation(True, "generation")
            
            subs_data_copy = [dict(s) for s in self.subtitles_data]
            self.transcription_thread = threading.Thread(
                target=self._perform_text_translation,
                args=(subs_data_copy, target_translation_lang, output_dir),
                daemon=True
            )
            self.transcription_thread.start()

        else:
            QMessageBox.warning(self, self.tr("general.warning.title"), 
                                "Nenhuma ação a ser executada.\n\n- Para gerar legendas, selecione um arquivo de áudio/vídeo.\n- Para traduzir uma legenda existente, desmarque o arquivo de mídia, carregue a legenda e marque a opção 'Gerar também tradução para:'.")


    def _translate_subs_data_with_deep_translator(self, subs_data: List[Dict[str, Any]], target_lang: str, output_folder: Path, base_filename_stem: str) -> Optional[str]:
        global _deep_translator_installed
        
        if not _deep_translator_installed:
            try:
                from deep_translator import GoogleTranslator
                _deep_translator_installed = True
            except ImportError:
                self.transcription_signal.log.emit("INFO: Biblioteca 'deep-translator' não encontrada. Tentando instalar...")
                mw.taskman.run_on_main(lambda: showInfo("A dependência 'deep-translator' está sendo instalada. Por favor, aguarde..."))
                
                try:
                    subprocess.check_call([sys.executable, "-m", "pip", "install", "deep-translator"])
                    
                    from deep_translator import GoogleTranslator
                    _deep_translator_installed = True
                    self.transcription_signal.log.emit("INFO: 'deep-translator' instalado com sucesso.")
                    mw.taskman.run_on_main(lambda: showInfo("'deep-translator' instalado com sucesso. A tradução continuará."))

                except Exception as e:
                    error_msg = f"ERRO: Falha ao instalar a biblioteca 'deep-translator'.\n\nVerifique sua conexão com a internet e tente reiniciar o Anki.\n\nDetalhes: {e}"
                    self.transcription_signal.log.emit(error_msg)
                    mw.taskman.run_on_main(lambda: showError(error_msg, parent=self))
                    return None

        from deep_translator import GoogleTranslator
        translated_items = []
        total_items = len(subs_data)
        translator = GoogleTranslator(source='auto', target=target_lang)

        try:
            for i, item in enumerate(subs_data):
                if self.stop_transcription_event.is_set():
                    raise InterruptedError("Tradução de texto interrompida")

                status_text = self.tr("translation.performing", current=i + 1, total=total_items)
                self.transcription_signal.update_status.emit(status_text)
                
                original_text = item.get("text", "")
                translated_text = original_text

                if original_text.strip():
                    try:
                        translated_text = translator.translate(original_text)
                    except Exception as e:
                        self.transcription_signal.log.emit(f"AVISO: Falha ao traduzir o item {i+1}: {e}")
                
                new_item = dict(item)
                new_item['text'] = translated_text
                translated_items.append(new_item)

            output_srt_path = output_folder / f"{base_filename_stem}_translated_{target_lang}.srt"
            
            srt_content = compose_srt(translated_items)
            with open(output_srt_path, 'w', encoding='utf-8') as f:
                f.write(srt_content)
            
            return str(output_srt_path)

        except InterruptedError as e:
            self.transcription_signal.log.emit(str(e))
            return None
        except Exception as e:
            self.transcription_signal.log.emit(f"ERRO GERAL na tradução de texto: {e}")
            return None

    def _perform_transcription(self, media_fpath_str: str, output_folder: Path, api_key: str, lang_code: str, generate_translation: bool, target_translation_lang: str):
        UPLOAD_ENDPOINT = "https://api.assemblyai.com/v2/upload"
        TRANSCRIPT_ENDPOINT = "https://api.assemblyai.com/v2/transcript"

        headers = {'authorization': api_key}

        try:
            self.transcription_signal.update_status.emit(self.tr("transcription.uploading"))
            with open(media_fpath_str, 'rb') as f:
                data = f.read()

            upload_req = urllib.request.Request(UPLOAD_ENDPOINT, data=data, headers={**headers, 'Content-Type': 'application/octet-stream'})
            with urllib.request.urlopen(upload_req) as response:
                upload_response_json = json.loads(response.read().decode('utf-8'))
            
            if 'upload_url' not in upload_response_json:
                raise Exception(f"Falha no upload para API: {upload_response_json.get('error', 'Resposta inválida')}")
            audio_url = upload_response_json['upload_url']

            self.transcription_signal.update_status.emit(self.tr("transcription.transcribing"))
            
            transcript_request = {'audio_url': audio_url, 'language_code': lang_code}

            transcript_req = urllib.request.Request(
                TRANSCRIPT_ENDPOINT,
                data=json.dumps(transcript_request).encode('utf-8'),
                headers={**headers, 'Content-Type': 'application/json'}
            )
            with urllib.request.urlopen(transcript_req) as response:
                transcript_response_json = json.loads(response.read().decode('utf-8'))
            
            transcript_id = transcript_response_json['id']
            polling_endpoint = f"{TRANSCRIPT_ENDPOINT}/{transcript_id}"

            while True:
                if self.stop_transcription_event.is_set():
                    raise InterruptedError(self.tr("transcription.interrupted_log"))

                self.transcription_signal.update_status.emit(self.tr("transcription.polling"))
                
                polling_req = urllib.request.Request(polling_endpoint, headers=headers)
                with urllib.request.urlopen(polling_req) as response:
                    polling_response_json = json.loads(response.read().decode('utf-8'))
                
                status = polling_response_json['status']

                if status == 'completed':
                    media_path = Path(media_fpath_str)
                    output_srt_path_str = None
                    translated_srt_path_str = None
                    
                    utterances = polling_response_json.get('utterances')
                    original_subs_data = []

                    if utterances:
                        for i, utterance in enumerate(utterances):
                            original_subs_data.append({
                                'id': i + 1,
                                'start_ms': utterance['start'],
                                'end_ms': utterance['end'],
                                'text': utterance['text']
                            })
                        
                        original_srt_content = compose_srt(original_subs_data)
                        output_srt_path = output_folder / f"{media_path.stem}.srt"
                        with open(output_srt_path, 'w', encoding='utf-8') as f:
                            f.write(original_srt_content)
                        output_srt_path_str = str(output_srt_path)
                    
                    else: # Fallback para o endpoint /srt
                        srt_endpoint = f"{polling_endpoint}/srt"
                        srt_req = urllib.request.Request(srt_endpoint, headers=headers)
                        with urllib.request.urlopen(srt_req) as response:
                            srt_content = response.read().decode('utf-8')
                        
                        output_srt_path = output_folder / f"{media_path.stem}.srt"
                        with open(output_srt_path, 'w', encoding='utf-8') as f:
                            f.write(srt_content)
                        output_srt_path_str = str(output_srt_path)
                        
                        original_subs_data = parse_srt_file(output_srt_path_str, self.transcription_signal.log.emit)

                    if generate_translation and original_subs_data:
                        translated_srt_path_str = self._translate_subs_data_with_deep_translator(
                            original_subs_data, 
                            target_translation_lang, 
                            output_folder, 
                            media_path.stem
                        )
                    elif generate_translation and not original_subs_data:
                        self.transcription_signal.log.emit("AVISO: A transcrição foi bem-sucedida, mas não foi possível analisar os dados para tradução.")


                    self.transcription_signal.finalize.emit(output_srt_path_str or "", translated_srt_path_str)
                    break
                elif status == 'error':
                    error_details = polling_response_json.get('error', 'Erro desconhecido')
                    raise Exception(f"Falha na transcrição da API: {error_details}")
                
                time.sleep(3)

        except InterruptedError:
            self.transcription_signal.log.emit(self.tr("transcription.interrupted_log"))
            self.transcription_signal.finalize.emit("", None)
        except Exception as e:
            error_msg = self.tr("transcription.error_log", error=str(e))
            self.transcription_signal.log.emit(error_msg)
            self.transcription_signal.finalize.emit("", None)

    def _perform_text_translation(self, subs_data: List[Dict[str, Any]], target_lang: str, output_folder: Path):
        base_name = "translated_subtitles"
        if self.subtitle_file_path_var:
            base_name = Path(self.subtitle_file_path_var).stem
        
        translated_srt_path = self._translate_subs_data_with_deep_translator(
            subs_data, target_lang, output_folder, base_name
        )
        
        self.transcription_signal.finalize.emit("", translated_srt_path)





 

    def add_items_to_anki(self) -> None:
        if not hasattr(self, 'files_listed_for_anki_export') or not self.files_listed_for_anki_export:
            showInfo(self.tr("anki_export.log.no_media_files_found", path="origem selecionada"),
                     parent=self, title=self.tr("anki_export.info.no_processed_items_for_export_title"))
            return

        if not mw or not mw.col:
            showError(self.tr("anki_export.error.anki_collection_unavailable"), parent=self, title=self.tr("general.error.title"))
            return

        items_to_add = self.files_listed_for_anki_export
        
        deck_id = self.deck_combo.currentData()
        model_id = self.note_type_combo.currentData()
        media_field = self.audio_field_combo.currentText()
        sub_field = self.subtitle_field_combo.currentText()
        trans_field = self.translation_field_combo.currentText()
        img_field = self.image_field_combo.currentText()

        if not all([deck_id, model_id, media_field, sub_field]):
            showError(self.tr("anki_export.error.missing_selections"), parent=self, title=self.tr("general.error.title"))
            return

        model = mw.col.models.get(model_id)
        if not model:
            showError(self.tr("anki_export.error.note_type_not_found", model_id=model_id), parent=self, title=self.tr("general.error.title"))
            return
        
        model_fields = mw.col.models.field_names(model)
        field_map = {
            self.tr("anki_export.error.field_desc.media"): (media_field, True),
            self.tr("anki_export.error.field_desc.main_subtitle"): (sub_field, True),
            self.tr("anki_export.error.field_desc.translation"): (trans_field, False),
            self.tr("anki_export.error.field_desc.image"): (img_field, False)
        }
        for field_desc, (field_name, is_mandatory) in field_map.items():
            if field_name:
                if field_name not in model_fields:
                    showError(self.tr("anki_export.error.field_not_in_model", field_desc=field_desc, field_name=field_name, model_name=model['name']), parent=self, title=self.tr("general.error.title"))
                    return
            elif is_mandatory:
                showError(self.tr("anki_export.error.field_not_selected", field_desc=field_desc), parent=self, title=self.tr("general.error.title"))
                return

        selected_fields_values = [f for f in [media_field, sub_field, trans_field, img_field] if f]
        if len(selected_fields_values) != len(set(selected_fields_values)):
            if not askUser(self.tr("anki_export.confirm.combined_fields_message"), parent=self, title=self.tr("anki_export.confirm.combined_fields_title")):
                return

        notes_added = 0
        mw.progress.start(label=self.tr("anki_export.progress.adding_notes"), max=len(items_to_add), parent=self, immediate=True)
        anki_media_collection_dir = Path(mw.col.media.dir())

        sub_map = {s['id']: s['text'] for s in self.subtitles_data if 'id' in s}
        trans_map = {t['id']: t['text'] for t in self.translations_data if 'id' in t}

        for i, local_media_path in enumerate(items_to_add):
            item_filename_on_disk = local_media_path.name
            mw.progress.update(value=i + 1, label=self.tr("anki_export.progress.adding_note_item", current=i + 1, total=len(items_to_add), filename=item_filename_on_disk))
            if mw.progress.want_cancel():
                break

            anki_media_filename: Optional[str] = None
            anki_image_filename_for_cleanup: Optional[str] = None

            try:
                anki_media_filename = mw.col.media.add_file(str(local_media_path))
                if not anki_media_filename:
                    self.log_message(self.tr("failed_to_copy_main_media_log", filename=local_media_path.name))
                    continue
            except Exception as e:
                self.log_message(self.tr("error_adding_main_media_log", filename=local_media_path.name, error=str(e)))
                continue

            note = mw.col.new_note(model)
            
            media_ext = local_media_path.suffix.lower()
            media_content_str = ""

            # --- INÍCIO DA ALTERAÇÃO ---
            # Lógica específica para cada formato de mídia
            if media_ext == '.webm':
                video_id = str(uuid.uuid4())
                src_filename = anki_media_filename
                media_content_str = (
                    f'<video id="{video_id}" class="video-js anki-video" controls="true" preload="auto" style="max-width: 500px; max-height: 400px;">'
                    f'    <source src="{src_filename}" type="video/webm">'
                    f'</video>'
                )
            elif media_ext == '.mp4':
                # Usa o formato nativo do Anki para MP4, que funciona como áudio/vídeo
                media_content_str = f'[sound:{anki_media_filename}]'
            else: 
                # Usa a tag <audio> para MP3 e outros formatos de áudio
                media_content_str = f'<audio controls src="{anki_media_filename}"></audio>'
            # --- FIM DA ALTERAÇÃO ---

            main_subtitle_text = ""
            translation_text = ""
            match = re.match(r'^(\d+)', item_filename_on_disk)
            if match:
                file_id = int(match.group(1))
                main_subtitle_text = sub_map.get(file_id, "")
                translation_text = trans_map.get(file_id, "")

            image_content_str: Optional[str] = None
            #if img_field:
             #   expected_image_name = local_media_path.stem + ".jpg"

            if img_field and self.images_generated_in_this_session: # <-- LINHA MODIFICADA
                expected_image_name = local_media_path.stem + ".jpg"
                expected_image_path = self.images_output_folder / expected_image_name


            if img_field and self.images_generated_in_this_session: # <-- LINHA MODIFICADA
                expected_image_name = local_media_path.stem + ".jpg"


                if expected_image_path.is_file():
                    try:
                        temp_anki_image_filename = mw.col.media.add_file(str(expected_image_path))
                        if temp_anki_image_filename:
                            anki_image_filename_for_cleanup = temp_anki_image_filename
                            image_content_str = f'<img src="{temp_anki_image_filename}">'
                        else:
                            self.log_message(self.tr("failed_to_copy_image_log", filename=expected_image_path.name))
                    except Exception as e_img:
                        self.log_message(self.tr("error_adding_image_log", filename=expected_image_path.name, error=str(e_img)))
            
            accumulated_field_data: Dict[str, List[str]] = {}
            def _add_content_to_accumulated_data(anki_field_name_target: Optional[str], content_to_add: Optional[str]) -> None:
                if anki_field_name_target and content_to_add:
                    if anki_field_name_target not in accumulated_field_data:
                        accumulated_field_data[anki_field_name_target] = []
                    accumulated_field_data[anki_field_name_target].append(str(content_to_add))

            _add_content_to_accumulated_data(media_field, media_content_str)
            _add_content_to_accumulated_data(sub_field, main_subtitle_text)
            _add_content_to_accumulated_data(trans_field, translation_text)
            _add_content_to_accumulated_data(img_field, image_content_str)

            for anki_model_field_name in model_fields:
                if anki_model_field_name in accumulated_field_data:
                    note[anki_model_field_name] = "<br>".join(accumulated_field_data[anki_model_field_name])
            
            try:
                mw.col.add_note(note, deck_id)
                notes_added += 1
            except Exception as e_add:
                self.log_message(self.tr("error_adding_note_log", filename=str(anki_media_filename), error=str(e_add)))
                if anki_media_filename:
                    try:
                        (anki_media_collection_dir / anki_media_filename).unlink(missing_ok=True)
                    except Exception as e_unlink_media:
                        self.log_message(self.tr("error_cleaning_orphan_media_log", filename=anki_media_filename, error=str(e_unlink_media)))
                if anki_image_filename_for_cleanup:
                    try:
                        (anki_media_collection_dir / anki_image_filename_for_cleanup).unlink(missing_ok=True)
                    except Exception as e_unlink_image:
                        self.log_message(self.tr("error_cleaning_orphan_image_log", filename=anki_image_filename_for_cleanup, error=str(e_unlink_image)))

        mw.progress.finish()
        msg_end_key = ""
        msg_args: Dict[str, Any] = {}

        if notes_added > 0:
            mw.reset()
            msg_end_key = "anki_export.info.notes_added_success"
            msg_args = {"count": notes_added, "deck_name": self.deck_combo.currentText()}
        elif len(items_to_add) > 0 and not mw.progress.want_cancel():
            msg_end_key = "anki_export.info.no_notes_added"
        elif mw.progress.want_cancel():
            msg_end_key = "anki_export.info.addition_cancelled"
            msg_args = {"count": notes_added}
        
        if msg_end_key:
            showInfo(self.tr(msg_end_key, **msg_args), parent=self, title=self.tr("general.info.title"))
        
        self.log_message(self.tr("anki_export.log.completed_anki_add", count=notes_added))
        self.list_output_folder_files()














    def closeEvent(self, event: Any) -> None: 
        if hasattr(self, 'dl_worker'):
            self.dl_worker.stop()
            self.dl_worker_thread.quit()
            self.dl_worker_thread.wait()
           




        self._save_config_value(self.CONFIG_KEY_LAST_PROCESSED_DATA, self.subtitles_data)
        self.media_player.stop()
        try:
            shutil.rmtree(self.temp_preview_dir, ignore_errors=True)
        except Exception as e:
            self.log_message(f"Não foi possível limpar a pasta de pré-visualização temporária: {e}")

        active_threads_info = [
            (self.tr("general.log.op_name_split"), self.processing_thread, self.request_stop_processing),
            (self.tr("general.log.op_name_images"), self.image_conversion_thread, self.request_stop_image_conversion),
            (self.tr("general.log.op_name_generation"), self.transcription_thread, self.request_stop_processing),
        ]
        if _ffmpeg_global_cancel_event and not _ffmpeg_global_cancel_event.is_set():
             if _ffmpeg_download_dialog_ref and _ffmpeg_download_dialog_ref.isVisible():
                 pass

        running_threads = [(name, th, stop_fn) for name, th, stop_fn in active_threads_info if th and th.is_alive()]

        if running_threads:
            thread_names_list = [name for name, _, _ in running_threads]
            thread_names = self.tr("and_joiner_for_thread_names").join(thread_names_list) if len(thread_names_list) > 1 else thread_names_list[0]

            if askUser(self.tr("general.dialog.close_confirmation_message", thread_names=thread_names), 
                       parent=self, title=self.tr("general.dialog.close_confirmation_title")):
                for name, thread, stop_func in running_threads:
                    stop_func() 
                    self.log_message(self.tr("general.log.waiting_for_thread_generic", thread_name=name))
                    thread.join(timeout=3.0)
                    if thread.is_alive(): 
                        self.log_message(self.tr("general.log.thread_not_finished_warning_generic", thread_name=name))
                event.accept()
            else: event.ignore()
        else:
            if _ffmpeg_download_dialog_ref and _ffmpeg_download_dialog_ref.isVisible():
                _ffmpeg_global_cancel_event.set()
                _ffmpeg_download_dialog_ref.close()
            event.accept()

    def start_single_clip_process(self) -> None:
        if self.processing_thread and self.processing_thread.is_alive():
            QMessageBox.warning(self, self.tr("general.warning.title"), self.tr("process.warning.process_running"))
            return
        if self.single_clip_thread and self.single_clip_thread.is_alive():
            QMessageBox.warning(self, self.tr("general.warning.title"), self.tr("process.warning.process_running"))
            return

        media_path = self.media_entry.text()
        if not media_path or not Path(media_path).is_file():
            showError(self.tr("process.error.invalid_media_file"), parent=self)
            return

        output_dir_str = self.out_entry.text()
        if not output_dir_str:
            output_dir_str = str(self.base_default_output_folder)
            self.out_entry.setText(output_dir_str)
        output_dir = Path(output_dir_str)
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            showError(self.tr("process.error.output_folder_invalid", path=str(output_dir), error=e), parent=self)
            return

        start_ms = self._parse_simple_time_to_ms(self.single_clip_start_entry.text())
        end_ms = self._parse_simple_time_to_ms(self.single_clip_end_entry.text())

        if end_ms <= start_ms:
            showError(self.tr("process.error.invalid_time_range"), parent=self)
            return

        chosen_format_text = self.output_format_combo.currentText()
        file_ext = "mp4"
        if self.tr("process.format.mp3") in chosen_format_text: file_ext = "mp3"
        elif self.tr("process.format.webm") in chosen_format_text: file_ext = "webm"

        self._set_ui_state_for_long_operation(True, "single_clip")
        self.status_label.setText(self.tr("process.log.single_clip_started", filename=Path(media_path).name))
        self.progress_bar.setRange(0, 0)
        self.progress_label.setText("")
        
        subs_data_copy = [dict(s) for s in self.subtitles_data]

        self.single_clip_thread = threading.Thread(
            target=self._perform_single_clip,
            args=(media_path, output_dir, start_ms, end_ms, file_ext, subs_data_copy),
            daemon=True
        )
        self.single_clip_thread.start()










    def _perform_single_clip(self, media_fpath_str: str, output_folder: Path, start_ms: int, end_ms: int, file_ext: str, subtitles_data: List[Dict[str, Any]]):
        media_file = Path(media_fpath_str)
        start_time_str = self.single_clip_start_entry.text().replace(":", "")
        end_time_str = self.single_clip_end_entry.text().replace(":", "")
        
        out_fname = f"{media_file.stem}_clip_{start_time_str}_to_{end_time_str}.{file_ext}"
        out_fpath = output_folder / out_fname
        
        ffmpeg_start_time = ms_to_ffmpeg_time(start_ms)
        
        # --- INÍCIO DA CORREÇÃO ---
        # Usar duração (-t) em vez de tempo final (-to) para maior precisão e consistência.
        duration_sec = (end_ms - start_ms) / 1000.0
        if duration_sec <= 0:
            duration_sec = 0.1 # Duração mínima para evitar erros

        # Comando base com busca precisa (-i antes de -ss) e usando duração (-t)
        base_cmd = [
            str(_FFMPEG_PATH), "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(media_file),
            "-ss", ffmpeg_start_time,
            "-t", str(duration_sec),
        ]

        cmd = []
        if file_ext == "mp3":
            cmd = base_cmd + [
                "-vn",
                "-c:a", "libmp3lame", "-q:a", "2",
                "-map_metadata", "-1",
                str(out_fpath)
            ]
        elif file_ext == "webm":
            cmd = base_cmd + [
                # Adiciona filtros para resetar os timestamps, garantindo que o clipe comece em 00:00
                "-vf", "setpts=PTS-STARTPTS", "-af", "asetpts=PTS-STARTPTS",
                "-c:v", "libvpx-vp9", "-crf", "30", "-b:v", "0",
                "-c:a", "libopus", "-b:a", "96k",
                "-map_metadata", "-1",
                str(out_fpath)
            ]
        else:  # Padrão para MP4
            cmd = base_cmd + [
                # Adiciona filtros para resetar os timestamps, garantindo que o clipe comece em 00:00
                "-vf", "setpts=PTS-STARTPTS", "-af", "asetpts=PTS-STARTPTS",
                "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                "-c:a", "aac", "-b:a", "128k",
                "-map_metadata", "-1",
                str(out_fpath)
            ]
        # --- FIM DA CORREÇÃO ---

        success = False
        error_msg = ""
        srt_fpath_or_none: Optional[Path] = None
        srt_error_msg = ""

        try:
            result = subprocess.run(cmd, check=True, capture_output=True, text=True, startupinfo=self.startupinfo, encoding='utf-8', errors='replace')
            success = True
        except subprocess.CalledProcessError as e:
            error_msg = e.stderr.strip()

        if success and subtitles_data:
            clip_subs = []
            sub_index = 1
            for sub in subtitles_data:
                if sub['start_ms'] < end_ms and sub['end_ms'] > start_ms:
                    new_start = max(0, sub['start_ms'] - start_ms)
                    new_end = sub['end_ms'] - start_ms
                    
                    clip_subs.append({
                        'id': sub_index,
                        'start_ms': new_start,
                        'end_ms': new_end,
                        'text': sub['text']
                    })
                    sub_index += 1

            if clip_subs:
                try:
                    srt_content = compose_srt(clip_subs)
                    srt_fpath = out_fpath.with_suffix('.srt')
                    with open(srt_fpath, 'w', encoding='utf-8') as f:
                        f.write(srt_content)
                    srt_fpath_or_none = srt_fpath
                except Exception as e:
                    srt_error_msg = str(e)

        mw.taskman.run_on_main(lambda: self._finalize_single_clip(success, out_fpath, error_msg, srt_fpath_or_none, srt_error_msg))









    def _finalize_single_clip(self, success: bool, path: Path, error_msg: str, srt_path: Optional[Path], srt_error: str):
        self.progress_bar.setRange(0, 100)
        if success:
            self.progress_bar.setValue(100)
            self.progress_label.setText("100%")
            if srt_path:
                msg = self.tr("process.log.single_clip_and_srt_success", path=str(path.parent))
                self.log_message(msg)
                showInfo(msg, parent=self)
            else:
                msg = self.tr("process.log.single_clip_success", path=str(path))
                self.log_message(msg)
                showInfo(msg, parent=self)
            
            if srt_error:
                err_msg = self.tr("process.log.single_clip_srt_error", error=srt_error)
                self.log_message(err_msg)
                showError(err_msg, parent=self)
        else:
            self.progress_bar.setValue(0)
            self.progress_label.setText("0%")
            err_msg = self.tr("process.log.single_clip_error", filename=path.name, stderr=error_msg)
            self.log_message(err_msg)
            showError(err_msg, parent=self)
        
        self.status_label.setText(self.tr("process.label.status_ready"))
        self._set_ui_state_for_long_operation(False, "single_clip")
        self.single_clip_thread = None

dialog_instance: Optional[SimpleAudioSplitterDialog] = None
def open_simple_audio_splitter() -> None:
    global dialog_instance, _FFMPEG_PATH, _FFPROBE_PATH, _CURRENT_DIALOG_LANG_FOR_FFMPEG_SETUP

    initial_lang_code = DEFAULT_APP_LANGUAGE
    try:
        if 'mw' in globals() and mw and hasattr(mw, 'addonManager') and callable(mw.addonManager.getConfig):
            config = mw.addonManager.getConfig(ADDON_PACKAGE)
            if config and SimpleAudioSplitterDialog.CONFIG_KEY_LANGUAGE in config:
                loaded_lang = config[SimpleAudioSplitterDialog.CONFIG_KEY_LANGUAGE]
                if loaded_lang in TRANSLATIONS: 
                    initial_lang_code = loaded_lang
    except Exception as e:
        _log_setup(f"AVISO: Não foi possível carregar o idioma da config em open_simple_audio_splitter: {e}")
    
    _CURRENT_DIALOG_LANG_FOR_FFMPEG_SETUP = initial_lang_code

    if not _ensure_ffmpeg_is_available(mw):
        _log_setup("FFmpeg não pôde ser configurado. O diálogo do addon não será aberto.")
        return

    if dialog_instance is None or not dialog_instance.isVisible():
        try: 
            dialog_instance = SimpleAudioSplitterDialog(mw)
        except Exception as e: 
            showError(f"Erro ao criar janela '{ADDON_NAME}': {e}", parent=mw, title="Erro")
            _log_setup(f"Erro criar Dialog: {e}"); return
    dialog_instance.show(); dialog_instance.raise_(); dialog_instance.activateWindow()

def add_menu_item() -> None:
    if not mw:
        _log_setup("AVISO CRÍTICO: 'mw' não disponível globalmente no setup do menu.")
        return
    
    lang_code_for_menu = DEFAULT_APP_LANGUAGE
    try:
        if hasattr(mw, 'addonManager') and callable(mw.addonManager.getConfig):
            config = mw.addonManager.getConfig(ADDON_PACKAGE) 
            if config and SimpleAudioSplitterDialog.CONFIG_KEY_LANGUAGE in config:
                loaded_lang = config[SimpleAudioSplitterDialog.CONFIG_KEY_LANGUAGE]
                if loaded_lang in TRANSLATIONS:
                     lang_code_for_menu = loaded_lang
    except Exception as e:
        _log_setup(f"AVISO: Não foi possível carregar o idioma da config para o item de menu: {e}")
    
    menu_text_key = "dialog.title"
    menu_text_base = TRANSLATIONS[lang_code_for_menu].get(menu_text_key, f"Advanced Media Splitter ({ADDON_NAME})")
    
    clean_menu_text = re.sub(r'<[^>]+>', '', menu_text_base).strip()
    clean_menu_text = clean_menu_text.split(' / ')[0].strip() 

    menu_text = clean_menu_text.format(addon_name=ADDON_NAME) + "..."
    
    action = QAction(menu_text, mw)
    action.triggered.connect(open_simple_audio_splitter)
    if hasattr(mw, 'form') and hasattr(mw.form, 'menuTools'):
        mw.form.menuTools.addAction(action)
    else: _log_setup("AVISO: menuTools não disponível para adicionar item de menu.")

if 'mw' in globals() and mw:
    try:
        if hasattr(mw.addonManager, 'set_config_action') and callable(mw.addonManager.set_config_action):
             mw.addonManager.set_config_action(ADDON_PACKAGE, open_simple_audio_splitter)
        elif hasattr(mw.addonManager, 'setConfigAction') and callable(mw.addonManager.setConfigAction):
             mw.addonManager.setConfigAction(ADDON_PACKAGE, open_simple_audio_splitter)
    except AttributeError: _log_setup("AVISO: set_config_action não disponível.")
    add_menu_item()
else: _log_setup("AVISO CRÍTICO: 'mw' não disponível globalmente no setup do menu.")